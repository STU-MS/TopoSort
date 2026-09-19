"""T3 事件引擎契约测试（验收标准本身）。

结构：
- T1 预埋用例：走 parse()，T2 合入后转绿（设计定案 §10，过渡期红属路标）。
- T3 行为用例：直接构造 Graph + 读取 evidence/test-data golden 三件套，
  不依赖 T2（.in 仅含严格 `<a,b>` 行，测试端做最小读取，宽松解析归 models）。

设计定案：evidence/decisions/2026-09-19-T3事件引擎设计定案.md
"""

import json
from pathlib import Path

from app.events import (
    Complete,
    Consume,
    CycleFound,
    DeadEnd,
    Enqueue,
    Fork,
    Timeline,
    TopoPlayer,
    event_to_dict,
)
from app.models import Graph, parse
from app.tests.conftest import CANON_COMPLETE_COUNT, CANON_ORDERS, CANON_TEXT

TESTDATA = Path(__file__).resolve().parents[2] / "evidence" / "test-data"
CASE_STD = "001-标准五节点图"
CASE_CYCLE = "002-二节点环"
CASE_CYCLE_DOWN = "003-环带下游"


def graph_from_in(case: str) -> Graph:
    """golden 用例只含严格 `<a,b>` 行，做最小读取；宽松容错解析归 app.models。"""
    nodes, edges = set(), set()
    for line in (TESTDATA / f"{case}.in").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        left, right = line.strip("<>").split(",")
        a, b = left.strip(), right.strip()
        nodes.add(a)
        nodes.add(b)
        edges.add((a, b))
    return Graph(frozenset(nodes), frozenset(edges))


def events_of(case: str) -> list:
    return list(TopoPlayer(graph_from_in(case)).iter_events())


def golden_of(case: str) -> list[dict]:
    return json.loads((TESTDATA / f"{case}.events.json").read_text(encoding="utf-8"))


# ---------- T1 预埋用例（依赖 T2 的 parse；T2 合入后转绿） ----------


class TestDeterminism:
    def test_same_input_same_event_sequence(self):
        g = parse(CANON_TEXT)
        a = list(TopoPlayer(g).iter_events())
        b = list(TopoPlayer(g).iter_events())
        assert a == b
        assert len(a) > 0

    def test_canon_completes_count(self):  # 原名 test_canon_completes_six，随 6→7 修正更名（refs #13）
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


# ---------- T3 行为用例（不依赖 parse；Graph 直构 + golden 三件套） ----------


class TestGolden:
    """golden = TopoPlayer.iter_events() 全量流（设计定案 §6），逐项相等。"""

    def test_standard_graph_matches_golden(self):
        events = events_of(CASE_STD)
        assert [event_to_dict(e) for e in events] == golden_of(CASE_STD)

    def test_standard_graph_counts(self):
        events = events_of(CASE_STD)
        completes = [e for e in events if isinstance(e, Complete)]
        forks = [e for e in events if isinstance(e, Fork)]
        assert len(completes) == CANON_COMPLETE_COUNT  # 7（2026-09-19 修正，refs #13）
        assert len(forks) == 6  # 验收条款：Fork 数正确
        assert sorted(c.order for c in completes) == sorted(tuple(o) for o in CANON_ORDERS)

    def test_pure_cycle_matches_golden(self):
        events = events_of(CASE_CYCLE)
        assert [event_to_dict(e) for e in events] == golden_of(CASE_CYCLE)
        assert [type(e).__name__ for e in events] == ["DeadEnd", "CycleFound"]
        assert events[0].stuck_nodes == frozenset({"A", "B"})

    def test_cycle_with_downstream_matches_golden(self):
        events = events_of(CASE_CYCLE_DOWN)
        assert [event_to_dict(e) for e in events] == golden_of(CASE_CYCLE_DOWN)
        found = [e for e in events if isinstance(e, CycleFound)][0]
        assert found.stuck_nodes == frozenset({"A", "B", "C"})  # 环 ∪ 环下游

    def test_determinism_two_runs_graph_direct(self):
        a, b = events_of(CASE_STD), events_of(CASE_STD)
        assert a == b and len(a) > 0


class TestKernelSemantics:
    def test_fork_child_first_consume_is_bound_alternative(self):
        first_consume: dict[int, str] = {}
        for e in events_of(CASE_STD):
            if isinstance(e, Consume) and e.branch_id not in first_consume:
                first_consume[e.branch_id] = e.node
        for e in events_of(CASE_STD):
            if isinstance(e, Fork):
                assert first_consume[e.new_branch_id] != e.node

    def test_enqueue_only_on_first_pool_entry_per_branch(self):
        seen: set[tuple[str, int]] = set()
        for e in events_of(CASE_STD):
            if isinstance(e, Enqueue):
                key = (e.node, e.branch_id)
                assert key not in seen
                seen.add(key)

    def test_iter_events_equals_unlimited_timeline(self):
        """逐拍交错一致性：iter_events() = 无限泳道 Timeline 逐 tick 拼接（定案 §8）。"""
        flat = events_of(CASE_STD)
        tl = Timeline(TopoPlayer(graph_from_in(CASE_STD)), lane_limit=8, tick_ms=1)
        collected = []
        while tl.state != "finished":
            collected.extend(tl.tick())
        assert collected == flat

    def test_max_completes_cap(self):
        tl = Timeline(
            TopoPlayer(graph_from_in(CASE_STD)), lane_limit=8, tick_ms=1, max_completes=3
        )
        while tl.state != "finished":
            tl.tick()
        assert len(tl.player_state_completed()) == 3

    def test_prefork_fuse_bounds_wide_parallel_graph(self):
        """前置保险丝：宽并行双链图（16 节点，C(16,8)=12870 序）在截断下
        收工且计数恰为 cap，且活跃分支峰值被 cap 封死——保险丝失效时
        峰值会冲到数千（实测 3915），此断言必红。"""
        nodes = {f"{t}{i}" for t in "ab" for i in range(8)}
        edges = {(f"{t}{i}", f"{t}{i + 1}") for t in "ab" for i in range(7)}
        tl = Timeline(
            TopoPlayer(Graph(frozenset(nodes), frozenset(edges)), max_completes=50),
            lane_limit=8,
            tick_ms=1,
        )
        ticks = 0
        while tl.state != "finished":
            tl.tick()
            ticks += 1
            assert ticks < 10000, "前置保险丝失效：宽并行图未在有限拍内收工"
            assert len(tl.player.live_ids()) <= 50, "前置保险丝失效：活跃分支峰值未被 cap 封死"
        assert len(tl.player_state_completed()) == 50

    def test_empty_graph_completes_once(self):
        events = list(TopoPlayer(Graph(frozenset(), frozenset())).iter_events())
        assert events == [Complete(0, ())]


class TestTimelineScheduling:
    def _run(self, lane_limit: int):
        tl = Timeline(TopoPlayer(graph_from_in(CASE_STD)), lane_limit=lane_limit, tick_ms=1)
        ticks = []
        while tl.state != "finished":
            ticks.append(tl.tick())
        return tl, ticks

    def test_lanes_within_limit_and_overflow_counted(self):
        tl, ticks = self._run(lane_limit=2)
        assert len(tl.player_state_completed()) == CANON_COMPLETE_COUNT
        for tick_events in ticks:
            stepped = {e.branch_id for e in tick_events if isinstance(e, Consume)}
            assert len(stepped) <= 2  # 任一拍可视化"步进"的分支不超过 lane_limit
            assert len(tl.active_lane_ids()) <= 2
            # 拍末补位：非步进分支的 Enqueue 只能出现在本拍步进/终止事件之后
            last_step = max(
                i for i, e in enumerate(tick_events)
                if isinstance(e, (Consume, Fork, DeadEnd, Complete))
            )
            for i, e in enumerate(tick_events):
                if isinstance(e, Enqueue) and e.branch_id not in stepped:
                    assert i > last_step

    def test_newborn_branch_not_stepped_same_tick(self):
        _, ticks = self._run(lane_limit=8)
        for tick_events in ticks:
            born = {e.new_branch_id for e in tick_events if isinstance(e, Fork)}
            stepped = {e.branch_id for e in tick_events if isinstance(e, Consume)}
            assert not (born & stepped)  # 拍首快照：新生分支下一拍才走

    def test_promotion_appended_after_release_same_tick(self):
        tl, ticks = self._run(lane_limit=1)
        seen_complete_tick = False
        for tick_events in ticks:
            completes = [e for e in tick_events if isinstance(e, Complete)]
            if completes:
                seen_complete_tick = True
                after = tick_events[tick_events.index(completes[0]) + 1:]
                assert any(isinstance(e, Enqueue) for e in after)  # 拍末补位补发
                break
        assert seen_complete_tick  # 防静默通过：标准图必有 Complete 拍


class TestStateMachineFullTable:
    """定案 §4 转移表全覆盖：running/paused/finished × tick/step_once/pause/resume/set_speed。"""

    def _tl(self):
        return Timeline(TopoPlayer(graph_from_in(CASE_STD)), lane_limit=2, tick_ms=1)

    def test_full_transition_table(self):
        tl = self._tl()
        # running：tick 推进、step_once 自动暂停、pause→paused
        assert tl.state == "running"
        assert isinstance(tl.tick(), list)
        tl.pause()
        assert tl.state == "paused"
        tl.pause()  # 幂等
        assert tl.state == "paused"
        assert tl.tick() == []  # paused 防御式空操作
        assert isinstance(tl.step_once(), list)
        assert tl.state == "paused"
        tl.resume()
        assert tl.state == "running"
        tl.resume()  # 幂等
        assert tl.state == "running"
        tl.set_speed(10)
        assert tl.tick_ms == 10
        tl.set_speed(0)
        assert tl.tick_ms == 1  # 下限保护
        while tl.state != "finished":
            tl.tick()
        # finished：全部操作空转/幂等
        assert tl.tick() == []
        assert tl.step_once() == []
        tl.pause()
        assert tl.state == "finished"
        tl.resume()
        assert tl.state == "finished"
        tl.set_speed(50)
        assert tl.tick_ms == 50

    def test_step_once_from_running_auto_pauses(self):
        tl = self._tl()
        events = tl.step_once()
        assert tl.state == "paused"
        assert isinstance(events, list) and len(events) > 0

    def test_step_once_reaches_finished(self):
        tl = self._tl()
        tl.pause()
        while tl.state == "paused":
            tl.step_once()
        assert tl.state == "finished"
        assert len(tl.player_state_completed()) == CANON_COMPLETE_COUNT

    def test_cyclefound_emitted_in_final_tick(self):
        tl = Timeline(TopoPlayer(graph_from_in(CASE_CYCLE)), lane_limit=2, tick_ms=1)
        last = []
        while tl.state != "finished":
            last = tl.tick()
        assert any(isinstance(e, CycleFound) for e in last)  # 拼最后一拍末尾，不丢失
