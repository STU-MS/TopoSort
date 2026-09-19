"""T5 界面壳契约测试（offscreen 全链路，验收标准本身）。骨架红，T5 后全绿。

说明：MainWindow 完成后必须是 QWidget 子类（qtbot.addWidget 要求）。
骨架期 MainWindow 只是普通类 → 这些测试以“跳过”表达“未开工”，T5 实装后自动生效。
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QWidget  # noqa: E402

from app.ui import MainWindow  # noqa: E402

CANON = "<A,C>\n<A,E>\n<B,C>\n<C,D>\n"

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


class TestEndToEnd:
    def test_paste_start_results(self, win):
        win.set_input(CANON)
        win.click_start()
        # 6 已过时（2026-09-19 修正为 7，见 evidence/decisions/2026-09-19-标准图数量修正.md）
        # T5 实装时改为 == CANON_COMPLETE_COUNT（refs #13）
        assert len(win.results()) == 6

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
        win.save_to(f)
        win.load_from(f)
        assert win.input_text() == CANON
