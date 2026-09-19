"""StepEvent 协议定义（唯一权威出处）。实现 T3（issue #4）。

设计定案：evidence/decisions/2026-09-19-T3事件引擎设计定案.md
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Enqueue:
    node: str
    branch_id: int


@dataclass(frozen=True)
class Consume:
    node: str
    branch_id: int


@dataclass(frozen=True)
class Fork:
    branch_id: int      # 原分支
    new_branch_id: int  # 新分出的分支
    node: str           # 分叉时被选走的节点


@dataclass(frozen=True)
class Complete:
    branch_id: int
    order: tuple[str, ...]


@dataclass(frozen=True)
class DeadEnd:
    branch_id: int
    stuck_nodes: frozenset[str]


@dataclass(frozen=True)
class CycleFound:
    stuck_nodes: frozenset[str]


StepEvent = Enqueue | Consume | Fork | Complete | DeadEnd | CycleFound


def event_to_dict(event: StepEvent) -> dict:
    """事件 → JSON 友好 dict（golden 文件与测试共用的唯一序列化口径）。

    frozenset → 升序 list、tuple → list；type 为事件类名。
    注：依赖 vars()，事件类保持普通 frozen dataclass，勿加 slots=True。
    """
    out = {"type": type(event).__name__}
    for name, value in vars(event).items():
        if isinstance(value, frozenset):
            out[name] = sorted(value)
        elif isinstance(value, tuple):
            out[name] = list(value)
        else:
            out[name] = value
    return out
