"""Kahn 拓扑分析与显式栈全序搜索。"""

import random
from dataclasses import dataclass
from typing import Iterator

ESTIMATE_SAMPLES = 10000     # 抽样次数：15 门课图 60ms（误差 −3.5%）、44 门课图 207ms
ESTIMATE_SEED = 20260927     # 固定种子 ⇒ 估计值可复现（实测跨进程逐位相同）
ESTIMATE_SATURATED = 10 ** 308  # 浮点下溢时的饱和值（极宽图）


@dataclass
class _Frame:
    """一个回溯深度的候选游标，以及进入该深度时选择的节点。"""

    candidates: tuple[str, ...]
    next_index: int = 0
    chosen: str | None = None


def _prepare(
    nodes: frozenset[str],
    edges: frozenset[tuple[str, str]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    adjacency_lists = {node: [] for node in nodes}
    indegree = {node: 0 for node in nodes}
    for source, target in edges:
        adjacency_lists[source].append(target)
        indegree[target] += 1
    adjacency = {
        node: tuple(sorted(neighbors))
        for node, neighbors in adjacency_lists.items()
    }
    return adjacency, indegree


def analyze(
    nodes: frozenset[str],
    edges: frozenset[tuple[str, str]],
) -> tuple[dict[str, int], frozenset[str]]:
    """返回最长路径分层和 Kahn 扫描后仍被阻塞的节点。"""

    adjacency, indegree = _prepare(nodes, edges)
    ready = sorted(node for node in nodes if indegree[node] == 0)
    layers = {node: 0 for node in nodes}
    cursor = 0

    while cursor < len(ready):
        node = ready[cursor]
        cursor += 1
        for child in adjacency[node]:
            layers[child] = max(layers[child], layers[node] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    stuck = frozenset(node for node, degree in indegree.items() if degree > 0)
    return layers, stuck


def _search(
    nodes: frozenset[str],
    edges: frozenset[tuple[str, str]],
    *,
    emit_orders: bool,
    max_count: int | None = None,
) -> Iterator[list[str] | None]:
    """遍历 Kahn 选择树；计数模式只产生哨兵，不复制完整路径。"""

    if max_count is not None and max_count <= 0:
        return

    adjacency, indegree = _prepare(nodes, edges)
    path: list[str] = []
    initial = tuple(sorted(node for node in nodes if indegree[node] == 0))
    stack = [_Frame(initial)]
    produced = 0

    while stack:
        frame = stack[-1]

        if len(path) == len(nodes):
            yield path.copy() if emit_orders else None
            produced += 1
            stack.pop()
            _undo(frame, path, adjacency, indegree)
            if max_count is not None and produced >= max_count:
                return
            continue

        if frame.next_index >= len(frame.candidates):
            stack.pop()
            _undo(frame, path, adjacency, indegree)
            continue

        chosen = frame.candidates[frame.next_index]
        frame.next_index += 1
        path.append(chosen)

        unlocked = []
        for child in adjacency[chosen]:
            indegree[child] -= 1
            if indegree[child] == 0:
                unlocked.append(child)

        next_candidates = tuple(
            sorted(
                candidate
                for candidate in (*frame.candidates, *unlocked)
                if candidate != chosen
            )
        )
        stack.append(_Frame(next_candidates, chosen=chosen))


def _undo(
    frame: _Frame,
    path: list[str],
    adjacency: dict[str, tuple[str, ...]],
    indegree: dict[str, int],
) -> None:
    if frame.chosen is None:
        return
    chosen = frame.chosen
    for child in adjacency[chosen]:
        indegree[child] += 1
    popped = path.pop()
    if popped != chosen:
        raise RuntimeError("拓扑序回溯状态损坏")


def iter_topo_orders(
    nodes: frozenset[str],
    edges: frozenset[tuple[str, str]],
    max_count: int | None = None,
) -> Iterator[list[str]]:
    """按字典序生成拓扑序；环图不产生结果。"""

    for order in _search(
        nodes,
        edges,
        emit_orders=True,
        max_count=max_count,
    ):
        if order is not None:
            yield order


def count_orders(
    nodes: frozenset[str],
    edges: frozenset[tuple[str, str]],
) -> int:
    """精确计数，但不构造或保存完整拓扑序。"""

    return sum(1 for _ in _search(nodes, edges, emit_orders=False))


def estimate_order_count(
    nodes: frozenset[str],
    edges: frozenset[tuple[str, str]],
    samples: int = ESTIMATE_SAMPLES,
    seed: int = ESTIMATE_SEED,
) -> int:
    """抽样估计拓扑序总数：给结果数阶乘级爆炸、精确计数跑不完的图一个量级。

    原理：随机拓扑排序（每步在候选集中等概率选一个）得到某个完整序的概率
    p = ∏ 1/|候选集_i|，而 Σ_all_orders p = 1，故 E[1/p] = 总数——1/p 就是总数的
    无偏估计量，取 samples 次平均即得估计值。只读图、不构造候选分支，内存恒定。

    精度（实测，固定种子）：k 个独立节点恰为 k!；15 门课图真值 1,332,720 →
    估计 1,285,578（−3.5%，样本越多越贴近真值）；44 门课图估计 ≈2.3×10^41，
    换种子跨度约 4× ⇒ 只当量级看。有环图返回 0。
    """

    if samples < 1:
        raise ValueError("samples 须为 ≥ 1 的整数")
    adjacency, base_indegree = _prepare(nodes, edges)
    rng = random.Random(seed)
    total = 0.0
    for _ in range(samples):
        indegree = dict(base_indegree)
        frontier = [node for node in sorted(nodes) if indegree[node] == 0]
        if not frontier:
            return 0                      # 有环：没有任何源点
        probability = 1.0
        visited = 0
        while frontier:
            width = len(frontier)
            chosen = frontier.pop(rng.randrange(width))
            probability *= 1.0 / width
            visited += 1
            for child in adjacency[chosen]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    frontier.append(child)
        if visited != len(nodes):
            return 0                      # 有环：走不完所有节点
        if probability == 0.0:
            return ESTIMATE_SATURATED     # 浮点下溢，退化为「极大」
        total += 1.0 / probability
    return int(round(total / samples))
