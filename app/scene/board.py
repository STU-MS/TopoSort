"""分层拓扑图画布与事件驱动视觉状态。"""

from __future__ import annotations

from os import PathLike
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt, Property, QPropertyAnimation
from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPen, QPolygonF, QImage
from PySide6.QtWidgets import QGraphicsObject, QGraphicsScene, QGraphicsView

from app.events.protocol import (
    Complete,
    Consume,
    CycleFound,
    DeadEnd,
    Enqueue,
    Fork,
    StepEvent,
)

from .effects import Effects


class _NodeItem(QGraphicsObject):
    """QObject-compatible node item so QPropertyAnimation can drive it."""

    RADIUS = 27.0

    def __init__(self, node: str, parent: QGraphicsObject | None = None):
        super().__init__(parent)
        self.node = node
        self._fill = QColor("#42516a")
        self._pen = QColor("#9aabc4")
        self._visual_opacity = 1.0
        self._pulse_scale = 1.0
        self.setZValue(1.0)

    @Property(float)
    def visual_opacity(self) -> float:
        return self._visual_opacity

    @visual_opacity.setter
    def visual_opacity(self, value: float) -> None:
        self._visual_opacity = max(0.0, min(1.0, float(value)))
        self.setOpacity(self._visual_opacity)
        self.update()

    @Property(float)
    def pulse_scale(self) -> float:
        return self._pulse_scale

    @pulse_scale.setter
    def pulse_scale(self, value: float) -> None:
        self._pulse_scale = max(0.75, min(1.35, float(value)))
        self.update()

    def set_style(self, fill: str, pen: str) -> None:
        self._fill = QColor(fill)
        self._pen = QColor(pen)
        self.update()

    def boundingRect(self) -> QRectF:
        margin = 8.0
        radius = self.RADIUS + margin
        return QRectF(-radius, -radius, radius * 2, radius * 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(self._pulse_scale, self._pulse_scale)
        painter.setBrush(QBrush(self._fill))
        painter.setPen(QPen(self._pen, 2.2))
        painter.drawEllipse(QPointF(0.0, 0.0), self.RADIUS, self.RADIUS)
        painter.setPen(QPen(QColor("#f4f7fb")))
        painter.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))
        painter.drawText(
            QRectF(-self.RADIUS, -self.RADIUS, self.RADIUS * 2, self.RADIUS * 2),
            Qt.AlignmentFlag.AlignCenter,
            self.node,
        )
        painter.restore()


class _EdgeItem(QGraphicsObject):
    """Directed edge with a QObject opacity property for dimming."""

    def __init__(self, source: QPointF, target: QPointF, parent: QGraphicsObject | None = None):
        super().__init__(parent)
        self.source = source
        self.target = target
        self._visual_opacity = 1.0
        self.setZValue(0.0)

    @Property(float)
    def visual_opacity(self) -> float:
        return self._visual_opacity

    @visual_opacity.setter
    def visual_opacity(self, value: float) -> None:
        self._visual_opacity = max(0.0, min(1.0, float(value)))
        self.setOpacity(self._visual_opacity)
        self.update()

    def boundingRect(self) -> QRectF:
        rect = QRectF(self.source, self.target).normalized()
        return rect.adjusted(-14.0, -14.0, 14.0, 14.0)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        del option, widget
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        line = self.target - self.source
        length = (line.x() ** 2 + line.y() ** 2) ** 0.5
        if length <= 0.01:
            painter.restore()
            return
        unit = QPointF(line.x() / length, line.y() / length)
        start = self.source + unit * _NodeItem.RADIUS
        end = self.target - unit * _NodeItem.RADIUS
        pen = QPen(QColor("#7184a1"), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(start, end)

        arrow_size = 8.0
        left = QPointF(-unit.y(), unit.x())
        base = end - unit * arrow_size
        arrow = QPolygonF(
            [
                end,
                base + left * arrow_size * 0.55,
                base - left * arrow_size * 0.55,
            ]
        )
        painter.setBrush(QBrush(QColor("#7184a1")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(arrow)
        painter.restore()


class GraphBoard(QGraphicsView):
    """分层图画布，只消费集合、分层映射和 StepEvent。"""

    _COLORS = {
        "idle": ("#42516a", "#9aabc4"),
        "ready": ("#e4b94f", "#ffe7a0"),
        "active": ("#2c9de0", "#8bd4ff"),
        "ghost": ("#657184", "#aab4c3"),
        "stuck": ("#e55353", "#ffb0b0"),
    }

    def __init__(
        self,
        graph_nodes: Iterable[str],
        graph_edges: Iterable[tuple[str, str]],
        layers: dict[str, int],
    ):
        super().__init__()
        self.setObjectName("GraphBoard")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#0f1726")))
        self._zoom = 1.0
        self._pan_anchor: QPointF | None = None
        self._node_items: dict[str, _NodeItem] = {}
        self._edge_items: dict[tuple[str, str], _EdgeItem] = {}
        self._states: dict[str, str] = {}
        self._animations: list[QPropertyAnimation] = []

        nodes = sorted({str(node) for node in graph_nodes})
        node_set = set(nodes)
        edges = sorted(
            {
                (str(source), str(target))
                for source, target in graph_edges
                if str(source) in node_set and str(target) in node_set
            }
        )
        normalized_layers = {str(node): int(level) for node, level in layers.items()}
        positions = self._layout_positions(nodes, normalized_layers)

        for source, target in edges:
            edge = _EdgeItem(positions[source], positions[target])
            self._edge_items[(source, target)] = edge
            self._scene.addItem(edge)

        for node in nodes:
            item = _NodeItem(node)
            item.setPos(positions[node])
            self._node_items[node] = item
            self._states[node] = "idle"
            self._scene.addItem(item)

        self._set_scene_rect(positions)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    @staticmethod
    def _layout_positions(nodes: list[str], layers: dict[str, int]) -> dict[str, QPointF]:
        if not nodes:
            return {}
        grouped: dict[int, list[str]] = {}
        for node in nodes:
            grouped.setdefault(layers.get(node, 0), []).append(node)
        layer_numbers = sorted(grouped)
        min_layer = layer_numbers[0]
        positions: dict[str, QPointF] = {}
        column_gap = 190.0
        row_gap = 92.0
        margin_x = 80.0
        for layer in layer_numbers:
            names = sorted(grouped[layer])
            total_height = (len(names) - 1) * row_gap
            start_y = 100.0 - total_height / 2.0
            x = margin_x + (layer - min_layer) * column_gap
            for index, node in enumerate(names):
                positions[node] = QPointF(x, start_y + index * row_gap)
        return positions

    def _set_scene_rect(self, positions: dict[str, QPointF]) -> None:
        if positions:
            xs = [point.x() for point in positions.values()]
            ys = [point.y() for point in positions.values()]
            width = max(320.0, max(xs) - min(xs) + 160.0)
            height = max(220.0, max(ys) - min(ys) + 180.0)
            left = min(xs) - 80.0
            top = min(ys) - 90.0
            self._scene.setSceneRect(left, top, width, height)
        else:
            self._scene.setSceneRect(0.0, 0.0, 320.0, 220.0)

    def _set_node_style(self, node: str, state: str) -> None:
        item = self._node_items.get(node)
        if item is None:
            return
        fill, pen = self._COLORS[state]
        item.set_style(fill, pen)
        if state != "active":
            item.pulse_scale = 1.0
        if state != "ghost":
            item.visual_opacity = 1.0

    def _retain_animation(self, animation: QPropertyAnimation) -> None:
        animation.setParent(self)
        self._animations.append(animation)

        def forget() -> None:
            if animation in self._animations:
                self._animations.remove(animation)
            animation.deleteLater()

        animation.finished.connect(forget)
        animation.start()

    def _stop_node_animations(self, node: str) -> None:
        item = self._node_items.get(node)
        if item is None:
            return
        for animation in list(self._animations):
            if animation.targetObject() is item:
                animation.stop()
                self._animations.remove(animation)
                animation.deleteLater()

    def _consume(self, node: str) -> None:
        item = self._node_items.get(node)
        if item is None or self._states.get(node) == "stuck":
            return
        self._stop_node_animations(node)
        self._states[node] = "ghost"
        item.set_style(*self._COLORS["active"])
        item.visual_opacity = 1.0

        pulse = Effects.pulse(item)
        ghost = Effects.ghost(item)

        def finish_ghost() -> None:
            if self._states.get(node) == "ghost":
                item.set_style(*self._COLORS["ghost"])

        ghost.finished.connect(finish_ghost)
        self._retain_animation(pulse)
        self._retain_animation(ghost)

        for (source, target), edge in self._edge_items.items():
            if source == node or target == node:
                self._stop_edge_animations(edge)
                edge.visual_opacity = min(edge.visual_opacity, 0.75)
                self._retain_animation(Effects.edge_dim(edge, edge.visual_opacity))

    @staticmethod
    def _stop_edge_animations_for(
        animations: list[QPropertyAnimation], edge: _EdgeItem
    ) -> None:
        for animation in list(animations):
            if animation.targetObject() is edge:
                animation.stop()
                animations.remove(animation)
                animation.deleteLater()

    def _stop_edge_animations(self, edge: _EdgeItem) -> None:
        self._stop_edge_animations_for(self._animations, edge)

    def apply_event(self, event: StepEvent) -> None:
        """Apply one protocol event to the global visual projection."""

        if isinstance(event, Enqueue):
            if event.node in self._node_items and self._states.get(event.node) != "stuck":
                self._stop_node_animations(event.node)
                self._states[event.node] = "ready"
                self._set_node_style(event.node, "ready")
            return
        if isinstance(event, Consume):
            self._consume(event.node)
            return
        if isinstance(event, (DeadEnd, CycleFound)):
            for node in event.stuck_nodes:
                if node not in self._node_items:
                    continue
                self._stop_node_animations(node)
                self._states[node] = "stuck"
                item = self._node_items[node]
                item.visual_opacity = 1.0
                self._set_node_style(node, "stuck")
            return
        if isinstance(event, (Fork, Complete)):
            return

    def node_state(self, node: str) -> str:
        return self._states.get(node, "idle")

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        self._zoom = max(0.25, min(3.0, self._zoom * factor))
        self.resetTransform()
        self.scale(self._zoom, self._zoom)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_anchor = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pan_anchor is not None:
            current = event.position()
            delta = current - self._pan_anchor
            self._pan_anchor = current
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_anchor is not None:
            self._pan_anchor = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def export_png(self, path: str | PathLike[str]) -> None:
        """Render the current graph scene to a non-empty PNG."""

        target = Path(path)
        source = self._scene.itemsBoundingRect().adjusted(-32.0, -32.0, 32.0, 32.0)
        if source.width() < 1.0 or source.height() < 1.0:
            source = QRectF(0.0, 0.0, 320.0, 220.0)
        width = max(320, int(source.width()))
        height = max(220, int(source.height()))
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor("#0f1726"))
        painter = QPainter(image)
        self._scene.render(painter, QRectF(0.0, 0.0, width, height), source)
        painter.end()
        image.save(str(target), "PNG")
