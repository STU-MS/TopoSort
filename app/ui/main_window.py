"""主窗口。实现 T5（issue #6）。

布局：
    ┌──────────────────────────────────────────────────────────┐
    │ ControlBar  开始 / 暂停 / 单步 / 跳完 · 速度              │
    ├──────────────┬────────────────────────┬──────────────────┤
    │ InputPanel   │  GraphBoard            │  LanesPanel      │
    │ 关系文本框   │  （分层图画布）        │  ──────────      │
    │ 打开/保存    │                        │  ResultsPanel    │
    ├──────────────┴────────────────────────┴──────────────────┤
    │ 状态行 / 错误文案（解析错含行号、发现环）                 │
    └──────────────────────────────────────────────────────────┘

依赖方向：ui → models / events / scene，只走各包 __init__ 导出的公共 API。

降级策略：T2/T3/T4 未合并时，其公共 API 抛 NotImplementedError。本层捕获后
在状态行提示「某模块尚未完成」，界面不崩溃、结果流留空；模块一旦合并，同一份
代码自动转真，无需改动。
"""
from pathlib import Path
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.events import Timeline, TopoPlayer
from app.models import ParseError, parse
from app.scene import GraphBoard
from app.ui.control_bar import ControlBar
from app.ui.input_panel import FILE_FILTER, InputPanel
from app.ui.lanes import LANE_LIMIT, LanesPanel
from app.ui.results import ResultsPanel

MAX_ORDERS = 2000  # 结果流上限（结果列表与动画收工共用同一个数）：阶乘爆炸时截断，避免界面卡死


def human_count(value) -> str:
    """大数的中文可读写法（只保留 2 位有效数字——抽样估计不配更多位数）：

    约 1,234 条 / 约 3.7 万条 / 约 130 万条 / 约 4.8 亿条 / 约 10^41 量级（抽样估计）
    """

    if value < 10**4:
        return f"约 {int(value):,} 条"
    exponent = int(math.floor(math.log10(value)))
    rounded = round(value, -(exponent - 1))  # 2 位有效数字
    if rounded < 10**8:
        return f"约 {rounded / 10**4:.1f} 万条" if rounded < 10**5 else f"约 {rounded / 10**4:.0f} 万条"
    if rounded < 10**12:
        return f"约 {rounded / 10**8:.0f} 亿条"
    return f"约 10^{exponent} 量级（抽样估计）"

CANVAS_HINT_IDLE = "图画板：点「开始」后在此绘制关系图"

INFO_STYLE = "QLabel { padding: 4px 8px; color: #333; }"
ERROR_STYLE = "QLabel { padding: 4px 8px; color: #a4262c; background: #fde7e9; font-weight: bold; }"


class MainWindow(QWidget):
    """T5 唯一入口。qtbot 要求：必须是 QWidget 子类。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TopoSort — 拓扑排序演示")
        self._results: list[list[str]] = []
        self._error: str | None = None
        self._total_hint = ""
        self._timeline = None
        self._board = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._build_ui()
        self.set_running(False)

    # ------------------------------------------------------------------ 布局

    def _build_ui(self) -> None:
        self.control = ControlBar()
        self.input_panel = InputPanel()
        self.lanes = LanesPanel(lane_limit=LANE_LIMIT)
        self.results_panel = ResultsPanel()

        self.canvas = QFrame()
        self.canvas.setFrameShape(QFrame.StyledPanel)
        self._canvas_layout = QVBoxLayout(self.canvas)
        self._canvas_hint = QLabel(CANVAS_HINT_IDLE)
        self._canvas_hint.setAlignment(Qt.AlignCenter)
        self._canvas_hint.setWordWrap(True)
        self._canvas_layout.addWidget(self._canvas_hint)

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.lanes)
        right.addWidget(self.results_panel)
        right.setSizes([300, 300])

        middle = QSplitter(Qt.Horizontal)
        middle.addWidget(self.input_panel)
        middle.addWidget(self.canvas)
        middle.addWidget(right)
        middle.setSizes([300, 520, 420])

        self.status = QLabel("就绪：粘贴或打开 <a,b> 关系后点「开始」")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(INFO_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.addWidget(self.control)
        root.addWidget(middle, 1)
        root.addWidget(self.status)

        self.control.start_clicked.connect(self.click_start)
        self.control.pause_toggled.connect(self._on_pause)
        self.control.step_clicked.connect(self._on_step)
        self.control.finish_clicked.connect(self._on_finish)
        self.control.speed_changed.connect(self._on_speed)
        self.input_panel.open_requested.connect(self._on_open)
        self.input_panel.save_requested.connect(self._on_save)
        self.results_panel.export_requested.connect(self._on_export)

    # ------------------------------------------------------- 公共 API（契约）

    def set_input(self, text: str) -> None:
        self.input_panel.set_text(text)
        self._clear_output()

    def input_text(self) -> str:
        return self.input_panel.text()

    def click_start(self) -> None:
        """全链路：解析 → 环检测/枚举 → 结果流 → 动画时间线。"""
        self._clear_output()
        try:
            graph = parse(self.input_text())
        except ParseError as exc:
            # 文案含 "第 N 行"，测试断言行号
            self._fail(f"解析错误：{exc}")
            return
        except NotImplementedError:
            self._fail("算法内核（models 模块）尚未完成，无法解析输入")
            return

        try:
            if graph.has_cycle():
                nodes = "、".join(sorted(graph.cycle_nodes()))
                self._fail(f"检测到环：{{{nodes}}} 相互依赖，不存在拓扑序")
                return
            self._results = [list(o) for o in graph.iter_topo_orders(MAX_ORDERS)]
        except NotImplementedError:
            self._fail("算法内核（models 模块）尚未完成，无法枚举拓扑序")
            return

        # 结果被上限截断时给个总数说法（抽样估计：精确计数在大图上跑不完）
        self._total_hint = self._estimate_hint(graph)
        self.results_panel.set_orders(self._results, truncated=bool(self._total_hint))
        self._mount_board(graph)
        if self._total_hint:
            self._note(f"已列出前 {len(self._results)} 条（已达上限）· {self._total_hint}")
        else:
            self._note(f"共 {len(self._results)} 条合法拓扑序")
        self._start_animation(graph)

    def _estimate_hint(self, graph) -> str:
        """仅当结果数触到上限时才估算总数；未截断返回空串。"""

        if len(self._results) < MAX_ORDERS:
            return ""
        try:
            return f"结果总数{human_count(graph.estimate_orders())}"
        except NotImplementedError:
            return "实际结果更多（总数估算不可用）"

    def _end_note(self) -> str:
        """演示结束文案；结果被截断时带上总数说法，别让状态行看起来像「全部就这么多」。"""

        base = f"演示结束：共 {len(self._results)} 条合法拓扑序"
        return f"{base} · {self._total_hint}" if self._total_hint else base

    def results(self) -> list[list[str]]:
        return [list(o) for o in self._results]

    def error_text(self):
        return self._error

    def save_to(self, path) -> None:
        self.input_panel.save_to(Path(path))

    def load_from(self, path) -> None:
        self.input_panel.load_from(Path(path))
        self._clear_output()

    # ------------------------------------------------------------ 动画时间线

    def _start_animation(self, graph) -> None:
        try:
            player = TopoPlayer(graph, max_completes=MAX_ORDERS)
            self._timeline = Timeline(
                player,
                lane_limit=LANE_LIMIT,
                tick_ms=self.control.speed_ms(),
            )
        except NotImplementedError:
            self._note("事件引擎（events 模块）尚未完成，跳过动画演示（结果已给出）")
            return
        self.set_running(True)
        self._timer.start(self.control.speed_ms())

    def _on_tick(self) -> None:
        if self._timeline is None:
            self._timer.stop()
            return
        try:
            events = self._timeline.tick()
        except NotImplementedError:
            self._timer.stop()
            self.set_running(False)
            self._note("事件引擎（events 模块）尚未完成，动画已停止（结果流不受影响）")
            return
        self._apply_events(events)
        if getattr(self._timeline, "state", "finished") == "finished":
            self._timer.stop()
            self.set_running(False)
            self._note(self._end_note())

    def _apply_events(self, events) -> None:
        for event in events or []:
            self.lanes.on_event(event)
            if self._board is not None:
                try:
                    self._board.apply_event(event)
                except NotImplementedError:
                    pass

    # -------------------------------------------------------------- 控制条槽

    def _on_pause(self, paused: bool) -> None:
        if self._timeline is None:
            return
        try:
            if paused:
                self._timeline.pause()
                self._timer.stop()
            else:
                self._timeline.resume()
                self._timer.start(self.control.speed_ms())
        except NotImplementedError:
            self._note("事件引擎（events 模块）尚未完成，暂停/恢复不可用")

    def _on_step(self) -> None:
        if self._timeline is None:
            return
        try:
            events = self._timeline.step_once()
        except NotImplementedError:
            self._note("事件引擎（events 模块）尚未完成，单步不可用")
            return
        self._apply_events(events)

    def _on_finish(self) -> None:
        if self._timeline is None:
            return
        self._timer.stop()
        self.set_running(False)
        try:
            for _ in range(10000):
                if getattr(self._timeline, "state", "finished") == "finished":
                    break
                self._apply_events(self._timeline.tick())
        except NotImplementedError:
            self._note("事件引擎（events 模块）尚未完成，跳完不可用")
            return
        self._note(self._end_note())

    def _on_speed(self, ms: int) -> None:
        if self._timeline is not None and self._timer.isActive():
            self._timer.start(ms)
        if self._timeline is not None:
            try:
                self._timeline.set_speed(ms)
            except NotImplementedError:
                pass

    # -------------------------------------------------------------- 文件菜单

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开关系文件", "", FILE_FILTER)
        if path:
            self.load_from(path)

    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存关系文件", "relations.txt", FILE_FILTER)
        if path:
            self.save_to(path)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出结果", "orders.txt", "文本 (*.txt)")
        if path:
            self.results_panel.save_txt(path)

    # ------------------------------------------------------------------ 杂项

    def set_running(self, running: bool) -> None:
        self.control.set_running(running)

    def _mount_board(self, graph) -> None:
        """挂上分层画布；渲染层不可用时退回占位提示，不影响结果流。"""
        try:
            board = GraphBoard(graph.nodes, graph.edges, graph.layers())
        except NotImplementedError:
            self._canvas_hint.setText("图画板：渲染模块（scene 模块）尚未完成")
            return
        except Exception as exc:  # 渲染层异常不该拖垮整个界面
            self._canvas_hint.setText(f"图画板初始化失败：{exc}")
            return
        self._canvas_hint.hide()
        self._canvas_layout.addWidget(board)
        self._board = board

    def _drop_board(self) -> None:
        """卸掉旧画布。每次开始都重建：否则改输入后画布会停留在上一张图。"""
        if self._board is not None:
            self._canvas_layout.removeWidget(self._board)
            self._board.deleteLater()
            self._board = None
        self._canvas_hint.setText(CANVAS_HINT_IDLE)
        self._canvas_hint.show()

    def _clear_output(self) -> None:
        self._timer.stop()
        self._timeline = None
        self._results = []
        self._error = None
        self._total_hint = ""
        self.results_panel.set_orders([])
        self.lanes.reset()
        self._drop_board()
        self.set_running(False)

    def _note(self, text: str) -> None:
        self.status.setStyleSheet(INFO_STYLE)
        self.status.setText(text)

    def _fail(self, text: str) -> None:
        self._error = text
        self.status.setStyleSheet(ERROR_STYLE)
        self.status.setText(text)


__all__ = ["MainWindow", "MAX_ORDERS"]
