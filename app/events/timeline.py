"""伪并发时间线：暂停/单步/调速/泳道上限。实现 T3（issue #4）。

设计定案：evidence/decisions/2026-09-19-T3事件引擎设计定案.md

调度规则摘要：
- 拍首快照：每拍只推进拍首已活跃的分支（按 branch_id 升序，前后台交错各一步），
  本拍 Fork/晋升产生的分支下一拍才推进。
- 拍末补位：拍末把活跃分支按 id 升序取前 lane_limit 条入泳道（出生、晋升、
  释放统一按此规则；泳道分支不降级）；新入道且后台步进过的分支补发 Enqueue，
  拼在本拍事件列表末尾。
- 后台分支：不发 Enqueue/Consume/Fork/DeadEnd，但 Complete 照发（计数不受影响）。
- 全部分支终止或达到 max_completes → CycleFound（若有）拼最后一拍末尾，置 finished。
"""

from __future__ import annotations

from .player import TopoPlayer
from .protocol import StepEvent


class Timeline:
    def __init__(
        self,
        player: TopoPlayer,
        lane_limit: int = 8,
        tick_ms: int = 400,
        max_completes: int | None = None,
    ):
        self.player = player
        self.lane_limit = max(0, int(lane_limit))
        self.tick_ms = tick_ms
        if max_completes is not None:
            player.set_max_completes(max_completes)
        self.state = "running"
        self._lanes: set[int] = set()
        self._relane()  # 初始占道（新分支尚未步进，无需补发）

    def tick(self) -> list[StepEvent]:
        """推进一拍；paused/finished 下为防御式空操作（返回空列表）。"""
        if self.state != "running":
            return []
        return self._advance()

    def pause(self) -> None:
        if self.state == "running":
            self.state = "paused"

    def resume(self) -> None:
        if self.state == "paused":
            self.state = "running"

    def step_once(self) -> list[StepEvent]:
        """单步：running 下先自动暂停再走一拍；finished 下空操作。"""
        if self.state == "finished":
            return []
        if self.state == "running":
            self.pause()
        events = self._advance()
        if self.state != "finished":
            self.state = "paused"
        return events

    def set_speed(self, ms: int) -> None:
        self.tick_ms = max(1, int(ms))

    def player_state_completed(self) -> list[tuple[str, ...]]:
        """公共只读视图：至今已完成的全部拓扑序（含后台分支），按完成顺序。"""
        return self.player.completed_orders()

    def active_lane_ids(self) -> list[int]:
        """公共只读视图：当前可视化泳道中的分支 id（升序），供渲染层/测试。"""
        return sorted(self._lanes)

    # ---- 内部 ----

    def _advance(self) -> list[StepEvent]:
        events: list[StepEvent] = []
        for bid in self.player.live_ids():  # 拍首快照，本轮新生分支不在其中
            if self.player.is_finished:    # 拍中触顶（max_completes）即停
                break
            events.extend(self.player.step_branch(bid, visual=bid in self._lanes))
        self._relane(events)               # 拍末补位 + 补发 Enqueue
        if self.player.is_finished:
            events.extend(self.player.finalize_events())
            self.state = "finished"
        return events

    def _relane(self, events: list[StepEvent] | None = None) -> None:
        """泳道归属 = 活跃分支按 id 升序取前 lane_limit 条（统一覆盖出生/晋升/释放）。"""
        new_lanes = set(self.player.live_ids()[: self.lane_limit])
        entered = sorted(new_lanes - self._lanes)
        self._lanes = new_lanes
        if events is not None:
            for bid in entered:
                events.extend(self.player.promote(bid))
