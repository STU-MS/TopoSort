"""候选池芯片与独立 PNG 导出。"""

from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from .effects import Effects


class CandidatePool(QWidget):
    """顶部候选芯片区域。

    ``set_ready`` 替换显示集合，``on_consume`` 增量移除一个节点。候选
    推导和 branch 维度由调用方负责，组件只呈现传入的全局集合。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("CandidatePool")
        self.setMinimumHeight(54)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._ready_nodes: set[str] = set()
        self._chips: dict[str, QPushButton] = {}
        self._fade_animations: dict[str, QPropertyAnimation] = {}
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(12, 8, 12, 8)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)

    def _new_chip(self, node: str) -> QPushButton:
        chip = QPushButton(node, self)
        chip.setProperty("candidate_chip", True)
        chip.setObjectName(f"candidate-{node}")
        chip.setCursor(Qt.CursorShape.ArrowCursor)
        chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        chip.setStyleSheet(
            "QPushButton {"
            "background-color: #e4b94f; color: #201a08;"
            "border: 2px solid #ffe7a0; border-radius: 12px;"
            "padding: 5px 12px; font-weight: 700;"
            "}"
        )
        return chip

    def _clear_chips(self) -> None:
        for animation in list(self._fade_animations.values()):
            animation.stop()
            animation.deleteLater()
        self._fade_animations.clear()
        for chip in list(self._chips.values()):
            self._layout.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self._chips.clear()

    def _rebuild(self) -> None:
        self._clear_chips()
        for node in sorted(self._ready_nodes):
            chip = self._new_chip(node)
            self._chips[node] = chip
            self._layout.insertWidget(self._layout.count() - 1, chip)
        self.adjustSize()

    def set_ready(self, nodes: Iterable[str]) -> None:
        """Replace the visible ready set with unique, sorted node names."""

        self._ready_nodes = {str(node) for node in nodes}
        self._rebuild()

    def on_consume(self, node: str) -> None:
        """Remove a chip semantically and fade its current widget away."""

        name = str(node)
        if name not in self._ready_nodes:
            return
        self._ready_nodes.remove(name)
        chip = self._chips.get(name)
        if chip is None:
            return
        effect = QGraphicsOpacityEffect(chip)
        effect.setOpacity(1.0)
        chip.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(Effects.PULSE_MS)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_animations[name] = animation

        def finish() -> None:
            self._layout.removeWidget(chip)
            self._chips.pop(name, None)
            self._fade_animations.pop(name, None)
            chip.deleteLater()
            animation.deleteLater()

        animation.finished.connect(finish)
        animation.start()

    def export_png(self, path: str | PathLike[str]) -> None:
        """Render the current candidate-chip region to a non-empty PNG."""

        self.adjustSize()
        width = max(240, self.sizeHint().width(), self.width())
        height = max(54, self.sizeHint().height(), self.height())
        if self.width() != width or self.height() != height:
            self.resize(width, height)
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor("#17243a"))
        painter = QPainter(image)
        self.render(painter, QPoint(0, 0))
        painter.end()
        image.save(str(Path(path)), "PNG")
