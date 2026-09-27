"""结果面板：列出全部合法拓扑序 + 导出 txt。实现 T5（issue #6）。

契约：结果列表每条 = 一行空格分隔的完整拓扑序。
"""
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ResultsPanel(QWidget):
    """右栏下半：结果流。对外给的是「序列列表」而不是控件文本。"""

    export_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._orders: list[list[str]] = []

        self.title = QLabel("结果流（0 条）")
        self.list = QListWidget()
        self.export_btn = QPushButton("导出 txt…")
        self.copy_btn = QPushButton("复制全部")

        buttons = QHBoxLayout()
        buttons.addWidget(self.export_btn)
        buttons.addWidget(self.copy_btn)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.list, 1)
        layout.addLayout(buttons)

        self.export_btn.clicked.connect(self.export_requested)
        self.copy_btn.clicked.connect(self.copy_all)

    # ---- 对外 API ----

    def set_orders(self, orders, truncated: bool = False) -> None:
        """灌入结果。truncated=True 表示这是被上限截断的前若干条（标题如实写明）。"""

        self._orders = [list(o) for o in orders]
        self.list.clear()
        for i, order in enumerate(self._orders, start=1):
            self.list.addItem(f"{i}. {' '.join(order)}")
        if truncated:
            self.title.setText(f"结果流（已列出前 {len(self._orders)} 条 · 还有更多，见状态行）")
        else:
            self.title.setText(f"结果流（{len(self._orders)} 条）")

    def orders(self) -> list[list[str]]:
        return [list(o) for o in self._orders]

    def text(self) -> str:
        """导出/复制用的纯文本：一行一条序，空格分隔。"""
        return "\n".join(" ".join(o) for o in self._orders)

    def save_txt(self, path: Path) -> None:
        Path(path).write_text(self.text(), encoding="utf-8", newline="")

    def copy_all(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.text())
