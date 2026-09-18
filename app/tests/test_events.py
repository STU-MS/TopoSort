"""T3 事件引擎契约测试（验收标准本身）。骨架阶段红，T3 完成后全绿。"""
from app.events import Complete, CycleFound, Timeline, TopoPlayer
from app.models import parse
from app.tests.conftest import CANON_COMPLETE_COUNT, CANON_TEXT

PAUSE_TRANSITIONS = [
    ("running", "pause", "paused"),
    ("paused", "resume", "running"),
]


class TestDeterminism:
    def test_same_input_same_event_sequence(self):
        g = parse(CANON_TEXT)
        a = list(TopoPlayer(g).iter_events())
        b = list(TopoPlayer(g).iter_events())
        assert a == b
        assert len(a) > 0

    def test_canon_completes_seven(self):
        events = list(TopoPlayer(parse(CANON_TEXT)).iter_events())
        completes = [e for e in events if isinstance(e, Complete)]
        assert len(completes) == CANON_COMPLETE_COUNT

    def test_cycle_graph_emits_cyclefound(self):
        events = list(TopoPlayer(parse("<A,B>\n<B,A>\n")).iter_events())
        assert any(isinstance(e, CycleFound) for e in events)


class TestTimeline:
    def _timeline(self):
        return Timeline(TopoPlayer(parse(CANON_TEXT)), lane_limit=2, tick_ms=1)

    def test_state_machine_transitions(self):
        tl = self._timeline()
        assert tl.state == "running"
        tl.pause()
        assert tl.state == "paused"
        tl.resume()
        assert tl.state == "running"

    def test_step_once_when_paused(self):
        tl = self._timeline()
        tl.pause()
        before = self._completed(tl)
        events = tl.step_once()
        assert isinstance(events, list)  # 一拍：每个活跃分支各走一步
        assert self._completed(tl) >= before

    def test_lane_limit_and_overflow_still_counted(self):
        tl = self._timeline()
        while tl.state != "finished":
            tl.tick()
        completes = tl.player_state_completed()  # 公共只读视图
        assert len(completes) == CANON_COMPLETE_COUNT  # 溢出泳道仍计数

    @staticmethod
    def _completed(tl) -> int:
        view = tl.player_state_completed()
        return len(view)

    def test_run_to_finish_all_orders_counted(self):
        tl = self._timeline()
        while tl.state != "finished":
            tl.tick()
        assert self._completed(tl) == CANON_COMPLETE_COUNT
