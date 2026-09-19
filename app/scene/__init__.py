"""scene：渲染场景（只认事件，不懂算法）。实现 T4（issue #5）。

公共 API：

    GraphBoard(graph_nodes, graph_edges, layers: dict[str, int])
        .apply_event(event: StepEvent)      # 更新节点/边视觉状态
        .node_state(node) -> str            # "idle"|"ready"|"ghost"|"stuck"
        .export_png(path: Path) -> None     # 非空图片
        支持平移缩放（滚轮/拖拽）

    Effects  # 动画时长常量集中此处（毫秒）
        GHOST_MS = 300 / PULSE_MS = 250 / EDGE_DIM_MS = 200

    CandidatePool
        .set_ready(nodes: Iterable[str])    # 就绪芯片亮黄
        .on_consume(node)                   # 芯片熄灭
        .export_png(path: Path) -> None     # 导出候选池区域
"""

from .board import GraphBoard
from .effects import Effects
from .pool import CandidatePool

__all__ = ["GraphBoard", "Effects", "CandidatePool"]
