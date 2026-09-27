"""T5 界面壳契约测试（offscreen 全链路，验收标准本身）。骨架红，T5 后全绿。

说明：MainWindow 完成后必须是 QWidget 子类（qtbot.addWidget 要求）。
骨架期 MainWindow 只是普通类 → 这些测试以“跳过”表达“未开工”，T5 实装后自动生效。
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QWidget  # noqa: E402

# 标准图常量取自 conftest，不在本文件复制——复制正是 6/7 数量偏差的来源（refs #13）
from app.tests.conftest import CANON_COMPLETE_COUNT, CANON_TEXT  # noqa: E402
from app.ui import MainWindow  # noqa: E402

# T5 未实装时 MainWindow 只是普通类 → 整文件跳过；实装为 QWidget 后自动生效
pytestmark = pytest.mark.skipif(
    not (isinstance(MainWindow, type) and issubclass(MainWindow, QWidget)),
    reason="T5 未实装（MainWindow 需为 QWidget）",
)


@pytest.fixture()
def win(qtbot):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


# 4 条独立 3 链：真值 12!/(3!^4) = 369,600 条 ≫ 上限 ⇒ 触发截断与总数估算
WIDE_TEXT = "\n".join(f"<{c}{i},{c}{i + 1}>" for c in "ABCD" for i in (1, 2))


class TestEndToEnd:
    def test_paste_start_results(self, win):
        win.set_input(CANON_TEXT)
        win.click_start()
        # 标准图合法序数口径见 evidence/decisions/2026-09-19-标准图数量修正.md（7 条）
        assert len(win.results()) == CANON_COMPLETE_COUNT

    def test_cycle_error_message(self, win):
        win.set_input("<A,B>\n<B,A>\n")
        win.click_start()
        assert win.error_text() and "环" in win.error_text()

    def test_parse_error_reports_lineno(self, win):
        win.set_input("<A,B>\n<A>\n")
        win.click_start()
        assert win.error_text() and "2" in win.error_text()


class TestFileIO:
    def test_save_open_roundtrip(self, win, tmp_path):
        f = tmp_path / "case.txt"
        win.set_input(CANON_TEXT)  # 原用例漏设输入，见 issue #6 留言
        win.save_to(f)
        win.load_from(f)
        assert win.input_text() == CANON_TEXT


class TestResultCap:
    """结果上限（MAX_ORDERS=2000）：列表与动画共用同一个数，超限时给出总数估算。"""

    def test_list_and_animation_share_one_cap(self, win):
        from app.ui.main_window import MAX_ORDERS

        win.set_input(WIDE_TEXT)
        win.click_start()
        assert len(win.results()) == MAX_ORDERS
        assert win._timeline.player.max_completes == MAX_ORDERS

    def test_truncation_says_so_in_title_and_status(self, win):
        win.set_input(WIDE_TEXT)
        win.click_start()
        assert "已达上限" in win.status.text()
        assert "万条" in win.status.text()
        assert "还有更多" in win.results_panel.title.text()

    def test_small_graph_has_no_truncation_wording(self, win):
        win.set_input(CANON_TEXT)
        win.click_start()
        assert win.status.text() == f"共 {CANON_COMPLETE_COUNT} 条合法拓扑序"
        assert "更多" not in win.results_panel.title.text()
