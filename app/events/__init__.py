"""events：算法→动画的解耦层（纯逻辑，零 Qt 依赖——CI 强制）。

公共 API：

    StepEvent         # dataclass 联合类型，见 protocol.py
    event_to_dict(e)  # 事件 → JSON 友好 dict（golden 文件唯一序列化口径）
    TopoPlayer(graph, max_completes: int | None = None)
        .iter_events() -> Iterator[StepEvent]   # 确定性：同输入两次播放逐项相等；
                                                # 逐拍交错（= 无限泳道 Timeline 逐拍拼接）
        事件类型：Enqueue(node, branch_id) / Consume(node, branch_id) /
                  Fork(branch_id, new_branch_id, node) / Complete(branch_id, order) /
                  DeadEnd(branch_id, stuck_nodes) / CycleFound(stuck_nodes)
        调度内核接口（Timeline 专用）：live_ids / step_branch(bid, visual) /
        promote(bid) / is_finished / finalize_events / completed_orders

    Timeline(player, lane_limit: int = 8, tick_ms: int = 400, max_completes=None)
        .tick() -> list[StepEvent]   # 每拍交错推进所有活跃分支一步（伪并发）
        .pause() / .resume() / .step_once() -> list[StepEvent]
        .set_speed(ms)               # 调整拍间隔
        .state -> "running" | "paused" | "finished"
        .player_state_completed() -> list[tuple[str, ...]]   # 已完成序只读视图
        .active_lane_ids() -> list[int]                      # 当前泳道分支只读视图
        契约：拍首快照+拍末补位；超出 lane_limit 的分支不展示但 Complete 照发、
        照常计数；全部分支终止（或达 max_completes）后 state=finished，
        CycleFound 拼最后一拍末尾。设计定案见 evidence/decisions/
        2026-09-19-T3事件引擎设计定案.md
"""

from app.events.player import TopoPlayer
from app.events.protocol import (
    Complete,
    Consume,
    CycleFound,
    DeadEnd,
    Enqueue,
    Fork,
    StepEvent,
    event_to_dict,
)
from app.events.timeline import Timeline

__all__ = [
    "StepEvent", "Enqueue", "Consume", "Fork", "Complete", "DeadEnd", "CycleFound",
    "TopoPlayer", "Timeline", "event_to_dict",
]
