"""算法 → 确定性事件流（Kahn 步进 + 显式分支工作队列）。实现 T3（issue #4）。

设计定案：evidence/decisions/2026-09-19-T3事件引擎设计定案.md

核心语义摘要：
- 逐拍交错：iter_events() 等价于"无限泳道的 Timeline 逐 tick 拼接"——每轮按
  branch_id 升序把所有活跃分支各推进一步，本轮新生的分支下一轮才推进。
- 某步候选 ≥2 个：按字典序选最小者 Consume，其余备选各开一条新分支（各发一条
  Fork，node=原分支所选）。新分支首步必须消费 Fork 时绑定的备选，且不再分叉
  （该步的全部备选已由亲代延续与兄弟分支覆盖，再分叉会重复枚举）。
- Enqueue 仅在节点首次进入该分支候选池时发（按分支计，池互相独立）。
- 环：分支候选耗尽且仍有剩余节点 → DeadEnd(该分支剩余全体)；全部分支终止后
  发一条 CycleFound(卡住节点并集)，拼在最后一轮/拍的事件末尾。
- 一切集合遍历一律 sorted() 字典序（抵御哈希随机化，保证跨进程确定性）。
- max_completes：累计 Complete 达到上限立即收工，不再发任何事件；
  且分叉前有前置保险丝——"已完成数 + 活跃分支数"达到上限即不再 Fork
  （每条活跃分支最终至多 1 个 Complete，上界自洽），防宽并行图分支爆炸。
"""

from __future__ import annotations

from collections.abc import Iterator

from ..models import Graph
from .protocol import Complete, Consume, CycleFound, DeadEnd, Enqueue, Fork, StepEvent


class _Branch:
    """一条分支 = 一个正在推进的部分拓扑序（Kahn 状态快照）。"""

    __slots__ = (
        "bid", "indeg", "frontier", "enqueued", "order", "bound", "pending_visual",
    )

    def __init__(
        self,
        bid: int,
        indeg: dict[str, int],
        frontier: set[str],
        order: list[str],
        bound: str | None,
    ):
        self.bid = bid
        self.indeg = indeg            # dict[str, int]：各节点剩余入度
        self.frontier = frontier      # set[str]：当前候选（入度已降为 0）
        self.enqueued: set = set()    # 本分支已发过 Enqueue 的节点（每分支独立空池起步）
        self.order = order            # list[str]：已消费序列
        self.bound = bound            # str | None：Fork 绑定的首步备选
        self.pending_visual = False   # 后台步进过、候选池尚未对观众补发


class _Kernel:
    """步进内核：player 与 Timeline 共用；分支工作队列显式维护在 _branches。"""

    def __init__(self, graph: Graph, max_completes: int | None):
        self._nodes = graph.nodes
        self._succs: dict[str, list[str]] = {n: [] for n in graph.nodes}
        for u, v in graph.edges:
            self._succs[u].append(v)
        for lst in self._succs.values():
            lst.sort()
        self.max_completes = max_completes
        self._branches: dict[int, _Branch] = {}
        self._next_id = 1
        self.completed: list[tuple[str, ...]] = []
        self._stuck_union: set[str] = set()
        self._finalized = False
        self.capped = False
        indeg = {n: 0 for n in graph.nodes}
        for _, v in graph.edges:
            indeg[v] += 1
        frontier = {n for n, d in indeg.items() if d == 0}
        self._branches[0] = _Branch(0, indeg, frontier, [], None)

    @property
    def is_finished(self) -> bool:
        return self.capped or not self._branches

    def live_ids(self) -> list[int]:
        return sorted(self._branches)

    def step_branch(self, bid: int, visual: bool = True) -> list[StepEvent]:
        """推进一条分支一步。visual=False 供 Timeline 后台分支使用：
        状态照常推进、Complete 照发，Enqueue/Consume/Fork/DeadEnd 不发。"""
        br = self._branches.get(bid)
        if br is None or self.capped:
            return []
        events: list[StepEvent] = []
        if br.frontier:
            candidates = sorted(br.frontier)
            if visual:
                for n in candidates:
                    if n not in br.enqueued:
                        br.enqueued.add(n)
                        events.append(Enqueue(n, bid))
            first_born = br.bound is not None
            choice = br.bound if first_born else candidates[0]
            br.bound = None
            # 分叉候选需要"消费前"快照，先记住再改状态
            alternatives = [] if first_born else [a for a in candidates if a != choice]
            if alternatives:
                pre_indeg, pre_frontier, pre_order = dict(br.indeg), set(br.frontier), list(br.order)
            if visual:
                events.append(Consume(choice, bid))
            br.order.append(choice)
            br.frontier.discard(choice)
            for alt in alternatives:
                # 前置保险丝：每条活跃分支最终至多产出 1 个 Complete，
                # "已完成数 + 活跃分支数"达到 max_completes 后不再开新分支——
                # 防止宽并行图在首个 Complete 出现前分支阶乘爆炸（定案 §9）
                if (
                    self.max_completes is not None
                    and len(self.completed) + len(self._branches) >= self.max_completes
                ):
                    break
                child = _Branch(self._next_id, dict(pre_indeg), set(pre_frontier), list(pre_order), alt)
                self._next_id += 1
                self._branches[child.bid] = child
                if visual:
                    events.append(Fork(bid, child.bid, choice))
            unlocked = []
            for succ in self._succs[choice]:
                br.indeg[succ] -= 1
                if br.indeg[succ] == 0:
                    br.frontier.add(succ)
                    unlocked.append(succ)
            if visual:
                for n in sorted(unlocked):
                    if n not in br.enqueued:
                        br.enqueued.add(n)
                        events.append(Enqueue(n, bid))
            if len(br.order) == len(self._nodes):
                self.completed.append(tuple(br.order))
                events.append(Complete(bid, tuple(br.order)))  # Complete 不分前后台，照发
                del self._branches[bid]
                self._check_cap()
        else:
            remaining = self._nodes - set(br.order)
            if remaining:
                stuck = frozenset(remaining)
                self._stuck_union |= stuck
                if visual:
                    events.append(DeadEnd(bid, stuck))
                del self._branches[bid]
            else:  # 空图：首步即完成
                self.completed.append(())
                events.append(Complete(bid, ()))
                del self._branches[bid]
                self._check_cap()
        if not visual:
            br.pending_visual = True  # br 已出字典也无妨：死分支不会被晋升
        return events

    def promote(self, bid: int) -> list[StepEvent]:
        """后台分支晋升泳道：补发其当前候选池（后台期间从未发过 Enqueue）。"""
        br = self._branches.get(bid)
        if br is None or not br.pending_visual:
            return []
        br.pending_visual = False
        events = []
        for n in sorted(br.frontier):
            if n not in br.enqueued:
                br.enqueued.add(n)
                events.append(Enqueue(n, bid))
        return events

    def finalize_events(self) -> list[StepEvent]:
        """全部终止后调用一次：有分支卡死过则发 CycleFound（截断收工不发）。"""
        if self._finalized:
            return []
        self._finalized = True
        if self._stuck_union and not self.capped:
            return [CycleFound(frozenset(self._stuck_union))]
        return []

    def _check_cap(self) -> None:
        if self.max_completes is not None and len(self.completed) >= self.max_completes:
            self.capped = True


class TopoPlayer:
    """Graph → 确定性 StepEvent 流。

    iter_events() 每次调用都从全新内核开始（同一 player 可重复播放）；
    Timeline 通过下方"调度内核接口"在常驻内核上逐步推进，两层共用同一实现。
    """

    def __init__(self, graph: Graph, max_completes: int | None = None):
        if max_completes is not None and max_completes < 1:
            raise ValueError("max_completes 须为 None（不截断）或 ≥ 1")
        self.graph = graph
        self.max_completes = max_completes
        self._kernel = _Kernel(graph, max_completes)

    def set_max_completes(self, max_completes: int | None) -> None:
        """运行期调整截断上限（同步常驻内核；Timeline 用，勿直改私有内核）。"""
        if max_completes is not None and max_completes < 1:
            raise ValueError("max_completes 须为 None（不截断）或 ≥ 1")
        self.max_completes = max_completes
        self._kernel.max_completes = max_completes

    def iter_events(self) -> Iterator[StepEvent]:
        """契约：确定性（同输入两次播放逐项相等）；对无环图每条完整序恰一次 Complete。"""
        kernel = _Kernel(self.graph, self.max_completes)
        while not kernel.is_finished:
            for bid in kernel.live_ids():
                yield from kernel.step_branch(bid)
        yield from kernel.finalize_events()

    # ---- 调度内核接口（Timeline 专用，公共 API 的一部分）----

    def live_ids(self) -> list[int]:
        return self._kernel.live_ids()

    def step_branch(self, bid: int, visual: bool = True) -> list[StepEvent]:
        return self._kernel.step_branch(bid, visual)

    def promote(self, bid: int) -> list[StepEvent]:
        return self._kernel.promote(bid)

    @property
    def is_finished(self) -> bool:
        return self._kernel.is_finished

    def finalize_events(self) -> list[StepEvent]:
        return self._kernel.finalize_events()

    def completed_orders(self) -> list[tuple[str, ...]]:
        return list(self._kernel.completed)
