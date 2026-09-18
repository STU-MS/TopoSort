"""图数据结构 + 分层。实现 T2（issue #3）。"""

from dataclasses import dataclass
from typing import Iterator

from app.models.enumerator import analyze, count_orders, iter_topo_orders


class CycleError(ValueError):
    """请求仅对 DAG 有定义的操作时，输入图包含环。"""


@dataclass(frozen=True)
class Graph:
    """不可变有向图。构造请走 app.models.parse()。"""

    nodes: frozenset[str]
    edges: frozenset[tuple[str, str]]

    def layers(self) -> dict[str, int]:
        """返回最长路径分层；有环时抛出 CycleError。"""

        layers, stuck = analyze(self.nodes, self.edges)
        if stuck:
            stuck_text = ", ".join(sorted(stuck))
            raise CycleError(f"有环图无法分层，卡住节点：{stuck_text}")
        return layers

    def has_cycle(self) -> bool:
        return bool(self.cycle_nodes())

    def cycle_nodes(self) -> frozenset[str]:
        _, stuck = analyze(self.nodes, self.edges)
        return stuck

    def iter_topo_orders(
        self,
        max_count: int | None = None,
    ) -> Iterator[list[str]]:
        """按字典序稳定产出全部拓扑序；max_count 截断；有环时产出空。"""

        return iter_topo_orders(self.nodes, self.edges, max_count=max_count)

    def count_orders(self) -> int:
        return count_orders(self.nodes, self.edges)
