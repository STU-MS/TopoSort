"""T2 算法内核行为测试。

规则：只走公共 API（app.models 导出），测试图来自 evidence/test-data。
"""

import json
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
