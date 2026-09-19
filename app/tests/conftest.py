"""行为测试共享数据：5 节点标准图（全组统一基准）。

图：
    A → C, A → E, B → C, C → D

合法拓扑序恰 6 条：
    A B C D E / A B C E D / A B E C D
    B A C D E / B A C E D / B A E C D
"""

CANON_TEXT = "<A,C>\n<A,E>\n<B,C>\n<C,D>\n"

CANON_ORDERS = [
    ["A", "B", "C", "D", "E"],
    ["A", "B", "C", "E", "D"],
    ["A", "B", "E", "C", "D"],
    ["B", "A", "C", "D", "E"],
    ["B", "A", "C", "E", "D"],
    ["B", "A", "E", "C", "D"],
]

CANON_COMPLETE_COUNT = 6

CANON_NODES = frozenset({"A", "B", "C", "D", "E"})
CANON_EDGES = frozenset({("A", "C"), ("A", "E"), ("B", "C"), ("C", "D")})
CANON_LAYERS = {"A": 0, "B": 0, "C": 1, "D": 2, "E": 1}
