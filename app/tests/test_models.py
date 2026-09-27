"""T2 算法内核行为测试。

规则：只走公共 API（app.models 导出），测试图来自 evidence/test-data。
"""

import json
import math
from pathlib import Path

import pytest

import app.models as models
from app.models import Graph, ParseError, parse

DATA_DIR = Path(__file__).resolve().parents[2] / "evidence" / "test-data"


def load_case(stem: str) -> tuple[str, dict]:
    text = (DATA_DIR / f"{stem}.in").read_text(encoding="utf-8")
    expected = json.loads(
        (DATA_DIR / f"{stem}.expected").read_text(encoding="utf-8")
    )
    return text, expected


def is_valid_order(order, graph: Graph) -> bool:
    """性质断言：序是节点的完整排列，且尊重所有边方向。"""
    if sorted(order) != sorted(graph.nodes):
        return False
    pos = {n: i for i, n in enumerate(order)}
    return all(pos[a] < pos[b] for a, b in graph.edges)


class TestParse:
    def test_canon_graph(self):
        text, _ = load_case("001-标准五节点")
        g = parse(text)
        assert g.nodes == frozenset("ABCDE")
        assert g.edges == frozenset({("A", "C"), ("A", "E"), ("B", "C"), ("C", "D")})

    def test_tolerates_blank_lines_and_fullwidth_and_bare(self):
        text, expected = load_case("002-宽容格式与重复边")
        g = parse(text)
        assert g.edges == frozenset({("A", "B"), ("B", "C")})
        assert list(g.iter_topo_orders()) == expected["orders"]

    def test_duplicate_edges_dedup(self):
        text, _ = load_case("002-宽容格式与重复边")
        assert len(parse(text).edges) == 2

    @pytest.mark.parametrize(
        "stem",
        ["004-第二行格式错误", "005-自环非法", "008-多余括号非法"],
    )
    def test_bad_input_reports_lineno(self, stem):
        text, expected = load_case(stem)
        with pytest.raises(ParseError) as ei:
            parse(text)
        assert ei.value.lineno == expected["parse_error_lineno"]
        assert str(expected["parse_error_lineno"]) in str(ei.value)


class TestCycle:
    def test_cycle_reports_all_stuck_nodes(self):
        text, expected = load_case("003-环与下游阻塞")
        g = parse(text)
        assert g.has_cycle() is True
        assert g.cycle_nodes() == frozenset(expected["cycle_nodes"])
        assert list(g.iter_topo_orders()) == []
        assert g.count_orders() == 0

    def test_layers_raises_public_cycle_error(self):
        text, _ = load_case("003-环与下游阻塞")
        with pytest.raises(models.CycleError) as ei:
            parse(text).layers()
        assert isinstance(ei.value, ValueError)


class TestEnumerate:
    def test_canon_seven_orders_all_valid(self):
        text, expected = load_case("001-标准五节点")
        g = parse(text)
        orders = list(g.iter_topo_orders())
        assert len(orders) == 7
        assert all(is_valid_order(o, g) for o in orders)
        assert orders == expected["orders"]

    def test_max_count_truncates(self):
        text, expected = load_case("001-标准五节点")
        assert list(parse(text).iter_topo_orders(max_count=2)) == expected["orders"][:2]

    def test_stability_same_input_same_sequence(self):
        text, _ = load_case("001-标准五节点")
        g = parse(text)
        assert list(g.iter_topo_orders()) == list(g.iter_topo_orders())

    def test_count_matches_enumeration(self):
        text, _ = load_case("001-标准五节点")
        g = parse(text)
        assert g.count_orders() == len(list(g.iter_topo_orders()))

    @pytest.mark.parametrize(
        "stem",
        ["006-30节点稀疏链", "007-60节点稀疏链"],
    )
    def test_sparse_chain_count_and_first_order(self, stem):
        text, expected = load_case(stem)
        g = parse(text)
        assert g.count_orders() == expected["count"]
        assert list(g.iter_topo_orders(max_count=1)) == expected["orders_capped"]


class TestLayers:
    def test_canon_layers(self):
        text, _ = load_case("001-标准五节点")
        g = parse(text)
        layers = g.layers()
        assert layers["A"] == 0 and layers["B"] == 0
        assert layers["C"] == 1
        assert layers["D"] == 2 and layers["E"] == 1


class TestRealCourseGraphs:
    """真实课程图：任务书图1（15 门课）与学业指南计算机培养方案（44 门课 86 条先修关系）。

    数据来源：`report/data/figure1-courses.txt`（任务书图1 逐边核对转录）、
    `report/data/study-guide-cs.txt`（2024 版学业指南第 287–291 页附表1「先修课程要求」列）。
    只做结构/前缀断言，**不做全量枚举**：009 有 156 万条、010 是 10^41 量级。
    """

    @pytest.mark.parametrize("stem", ["009-任务书图一", "010-学业指南计算机培养方案"])
    def test_structure_layers_and_first_orders(self, stem):
        text, expected = load_case(stem)
        g = parse(text)
        assert len(g.nodes) == expected["nodes"]
        assert len(g.edges) == expected["edges"]
        assert g.cycle_nodes() == frozenset(expected["cycle_nodes"])
        assert max(g.layers().values()) + 1 == expected["layer_count"]
        assert list(g.iter_topo_orders(max_count=3)) == expected["orders_capped"]

    def test_figure1_exact_count(self):
        """任务书图1：合法序恰 1,566,180 条（精确计数约 4s；界面在 2000 条处截断并估算总数）。"""
        text, expected = load_case("009-任务书图一")
        assert parse(text).count_orders() == expected["count"] == 1566180

    def test_guide_graph_count_is_astronomical(self):
        """44 门课图精确计数不可终止 ⇒ 用抽样估计说明量级（>1e10 已足够）。"""
        text, _ = load_case("010-学业指南计算机培养方案")
        assert parse(text).estimate_orders() > 10**10


class TestEstimateOrders:
    """抽样估计（结果数阶乘级爆炸、精确计数跑不完时的量级）：
    evidence/decisions/2026-09-27-结果上限与总数估算.md"""

    @pytest.mark.parametrize("k", [5, 10, 14])
    def test_independent_nodes_estimate_exact(self, k):
        """k 个互不相干的节点：每条序概率相同 ⇒ 估计值恰为 k!。"""
        g = Graph(frozenset(f"n{i}" for i in range(k)), frozenset())
        assert g.estimate_orders() == math.factorial(k)

    def test_canon_graph_estimate_near_seven(self):
        text, _ = load_case("001-标准五节点")
        assert 6 <= parse(text).estimate_orders() <= 9

    def test_sparse_chain_estimate_is_one(self):
        text, _ = load_case("006-30节点稀疏链")
        assert parse(text).estimate_orders() == 1

    def test_estimate_is_deterministic(self):
        """固定种子 ⇒ 两次调用逐位相等（可复现，与枚举器同一要求）。"""
        text, _ = load_case("007-60节点稀疏链")
        g = parse(text)
        assert g.estimate_orders() == g.estimate_orders()

    def test_cycle_estimate_is_zero(self):
        assert parse("<A,B>\n<B,A>\n").estimate_orders() == 0

    def test_wide_graph_within_ten_percent(self):
        """4 条独立 3 链：真值 12!/(3!^4) = 369600，估计误差应 < 10%。"""
        text = "\n".join(f"<{c}{i},{c}{i + 1}>" for c in "ABCD" for i in (1, 2))
        g = parse(text)
        assert abs(g.estimate_orders() - 369600) / 369600 < 0.10
