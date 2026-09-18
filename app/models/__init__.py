"""models：图模型与拓扑排序算法内核（纯逻辑，零 Qt 依赖——CI 强制）。

公共 API（测试与上层只准使用这些名字）：

    parse(text: str) -> Graph
        解析 `<a,b>` 关系文本。宽容：空白行、全角括号（）与 <>、`a,b` 无括号。
        错误：ParseError（含行号 lineno、原文 line）。
        契约：重复边只保留一条；自环视为非法输入（ParseError）。

    Graph
        .nodes -> frozenset[str]
        .edges -> frozenset[tuple[str, str]]
        .layers() -> dict[str, int]      # 最长路径分层：源点为 0 层
        .has_cycle() -> bool
        .cycle_nodes() -> frozenset[str] # 卡住的节点集（无环时为空）
        .iter_topo_orders(max_count: int | None = None) -> Iterator[list[str]]
            按字典序稳定产出全部拓扑序（显式栈回溯，非递归）；
            max_count 截断；有环时产出为空序列。
        .count_orders() -> int           # 仅计数，不构造完整序列

    CycleError
        Graph.layers() 收到有环图时抛出的 ValueError 子类。
"""

from app.models.graph import CycleError, Graph
from app.models.parser import ParseError, parse

__all__ = ["CycleError", "Graph", "ParseError", "parse"]
