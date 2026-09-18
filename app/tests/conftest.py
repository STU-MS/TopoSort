"""行为测试共享数据：5 节点标准图（全组统一基准）。

图：
    A → C, A → E, B → C, C → D

合法拓扑序恰 7 条：
    A B C D E / A B C E D / A B E C D
    A E B C D
    B A C D E / B A C E D / B A E C D
"""

CANON_TEXT = "<A,C>\n<A,E>\n<B,C>\n<C,D>\n"

CANON_ORDERS = [
    ["A", "B", "C", "D", "E"],
    ["A", "B", "C", "E", "D"],
    ["A", "B", "E", "C", "D"],
    ["A", "E", "B", "C", "D"],
    ["B", "A", "C", "D", "E"],
    ["B", "A", "C", "E", "D"],
    ["B", "A", "E", "C", "D"],
]

CANON_COMPLETE_COUNT = 7
