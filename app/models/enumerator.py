"""Kahn 拓扑分析与显式栈全序搜索。"""

from dataclasses import dataclass
from typing import Iterator


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
