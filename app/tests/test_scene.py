"""T4 渲染场景契约测试（offscreen，验收标准本身）。骨架红，T4 后全绿。"""
import os
from inspect import signature
from os import PathLike
from typing import Iterable, get_type_hints

import pytest
from PySide6.QtCore import Property, QObject, QPropertyAnimation
from PySide6.QtWidgets import QPushButton, QWidget

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.scene import CandidatePool, Effects, GraphBoard  # noqa: E402
from app.events import (  # noqa: E402
    Complete,
    Consume,
    CycleFound,
    DeadEnd,
    Enqueue,
    Fork,
    StepEvent,
)
from conftest import CANON_EDGES, CANON_LAYERS, CANON_NODES  # noqa: E402
from tools import capture_t4_screenshots  # noqa: E402


class _AnimationProbe(QObject):
    def __init__(self):
        super().__init__()
        self._visual_opacity = 1.0
        self._pulse_scale = 1.0

    @Property(float)
    def visual_opacity(self):
        return self._visual_opacity

    @visual_opacity.setter
    def visual_opacity(self, value):
        self._visual_opacity = float(value)

    @Property(float)
    def pulse_scale(self):
        return self._pulse_scale

    @pulse_scale.setter
    def pulse_scale(self, value):
        self._pulse_scale = float(value)


@pytest.fixture()
def board(qtbot):
    value = GraphBoard(CANON_NODES, CANON_EDGES, CANON_LAYERS)
    qtbot.addWidget(value)
    return value


class TestVisualStates:
    def test_initial_idle(self, board):
        assert board.node_state("A") == "idle"

    def test_enqueue_then_consume(self, board):
        board.apply_event(Enqueue("A", 0))
        assert board.node_state("A") == "ready"
        board.apply_event(Consume("A", 0))
        assert board.node_state("A") == "ghost"

    def test_stuck_nodes_marked(self, board):
        board.apply_event(CycleFound(frozenset({"A", "B"})))
        assert board.node_state("A") == "stuck"
        assert board.node_state("B") == "stuck"

    def test_dead_end_marks_known_nodes_only(self, board):
        board.apply_event(DeadEnd(0, frozenset({"A", "missing"})))
        assert board.node_state("A") == "stuck"
        assert board.node_state("B") == "idle"

    def test_fork_and_complete_do_not_change_board_state(self, board):
        board.apply_event(Enqueue("A", 0))
        before = board.node_state("A")
        board.apply_event(Fork(0, 1, "A"))
        board.apply_event(Complete(1, ("A", "B")))
        assert board.node_state("A") == before

    def test_unknown_events_and_invalid_edges_are_ignored(self, qtbot):
        board = GraphBoard({"A"}, {("A", "missing")}, {"A": 0})
        qtbot.addWidget(board)
        board.apply_event(Enqueue("missing", 0))
        assert board.node_state("A") == "idle"
        assert len(board._node_items) == 1
        assert board._edge_items == {}

    def test_repeated_events_do_not_duplicate_items(self, board):
        board.apply_event(Enqueue("A", 0))
        board.apply_event(Enqueue("A", 1))
        assert len(board._node_items) == len(CANON_NODES)


class TestExport:
    def test_png_nonempty(self, board, tmp_path):
        out = tmp_path / "graph.png"
        board.export_png(out)
        assert out.exists() and out.stat().st_size > 0

    def test_board_export_handles_empty_graph(self, qtbot, tmp_path):
        board = GraphBoard(set(), set(), {})
        qtbot.addWidget(board)
        out = tmp_path / "empty.png"
        board.export_png(out)
        assert out.exists() and out.stat().st_size > 0


class TestCandidatePool:
    @staticmethod
    def _chips(pool):
        return [
            button.text()
            for button in pool.findChildren(QPushButton)
            if button.property("candidate_chip")
        ]

    def test_is_qwidget_and_set_ready_replaces_sorted_unique_chips(self, qtbot):
        pool = CandidatePool()
        qtbot.addWidget(pool)
        assert isinstance(pool, QWidget)
        pool.set_ready(["B", "A", "A"])
        assert self._chips(pool) == ["A", "B"]
        pool.set_ready(["C"])
        assert self._chips(pool) == ["C"]

    def test_on_consume_removes_requested_chip(self, qtbot):
        pool = CandidatePool()
        qtbot.addWidget(pool)
        pool.set_ready(["A", "B"])
        pool.on_consume("A")
        pool.set_ready(["B"])
        assert self._chips(pool) == ["B"]

    def test_export_png_nonempty(self, qtbot, tmp_path):
        pool = CandidatePool()
        qtbot.addWidget(pool)
        pool.set_ready(["A", "B"])
        out = tmp_path / "pool.png"
        pool.export_png(out)
        assert out.exists() and out.stat().st_size > 0


def test_consume_dims_incident_edges_without_changing_state(board):
    before = board.node_state("A")
    board.apply_event(Consume("A", 0))
    assert before == "idle"
    assert board.node_state("A") == "ghost"
    assert board._edge_items[("A", "C")].opacity() < 1.0
    assert board._edge_items[("A", "E")].opacity() < 1.0
    assert board._edge_items[("B", "C")].opacity() == 1.0
    assert board._edge_items[("C", "D")].opacity() == 1.0


def test_pan_zoom_does_not_change_semantic_state(board):
    board.apply_event(Enqueue("A", 0))
    board.scale(1.25, 1.25)
    assert board.node_state("A") == "ready"


def test_effect_durations_bounded():
    assert 0 < Effects.GHOST_MS <= 1000
    assert 0 < Effects.PULSE_MS <= 1000
    assert 0 < Effects.EDGE_DIM_MS <= 1000


def test_effect_factories_create_bounded_qt_animations():
    probe = _AnimationProbe()
    pulse = Effects.pulse(probe)
    ghost = Effects.ghost(probe)
    edge = Effects.edge_dim(probe)
    assert all(isinstance(animation, QPropertyAnimation) for animation in (pulse, ghost, edge))
    assert pulse.duration() == Effects.PULSE_MS
    assert ghost.duration() == Effects.GHOST_MS
    assert edge.duration() == Effects.EDGE_DIM_MS


def test_capture_active_state_fans_out_enqueue_then_consume():
    calls = []

    class BoardRecorder:
        def apply_event(self, event):
            calls.append(("board", event))

    class PoolRecorder:
        def set_ready(self, nodes):
            calls.append(("pool-ready", tuple(nodes)))

        def on_consume(self, node):
            calls.append(("pool-consume", node))

    assert hasattr(capture_t4_screenshots, "_prepare_active_state")
    capture_t4_screenshots._prepare_active_state(
        BoardRecorder(), PoolRecorder(), "A"
    )

    assert calls == [
        ("board", Enqueue("A", 0)),
        ("pool-ready", ("A",)),
        ("board", Consume("A", 0)),
        ("pool-consume", "A"),
    ]


def test_capture_ready_state_keeps_board_and_pool_in_sync():
    calls = []

    class BoardRecorder:
        def apply_event(self, event):
            calls.append(("board", event))

    class PoolRecorder:
        def set_ready(self, nodes):
            calls.append(("pool-ready", tuple(nodes)))

    assert hasattr(capture_t4_screenshots, "_prepare_ready_state")
    capture_t4_screenshots._prepare_ready_state(
        BoardRecorder(), PoolRecorder(), ("A", "B")
    )

    assert calls == [
        ("board", Enqueue("A", 0)),
        ("board", Enqueue("B", 0)),
        ("pool-ready", ("A", "B")),
    ]


def test_capture_active_frame_waits_until_animation_midpoint(monkeypatch):
    delays = []

    class TestClock:
        @staticmethod
        def qWait(milliseconds):
            delays.append(milliseconds)

    monkeypatch.setattr(capture_t4_screenshots, "QTest", TestClock)
    assert hasattr(capture_t4_screenshots, "_wait_for_active_frame")
    capture_t4_screenshots._wait_for_active_frame()

    assert delays == [Effects.PULSE_MS // 2]


def test_public_scene_api_has_explicit_boundary_types():
    board_hints = get_type_hints(GraphBoard.apply_event)
    pool_hints = get_type_hints(CandidatePool.set_ready)
    board_export_hints = get_type_hints(GraphBoard.export_png)
    pool_export_hints = get_type_hints(CandidatePool.export_png)

    assert board_hints == {"event": StepEvent, "return": type(None)}
    assert pool_hints == {"nodes": Iterable[str], "return": type(None)}
    assert board_export_hints["path"] == str | PathLike[str]
    assert pool_export_hints["path"] == str | PathLike[str]
    assert signature(GraphBoard.export_png).return_annotation in (None, "None")
    assert signature(CandidatePool.export_png).return_annotation in (None, "None")
