"""T4 动画时长与 Qt 动效工厂。

`Effects` 不保存算法状态，只负责把集中管理的时长转换为可复用的
``QPropertyAnimation``。目标对象由 ``GraphBoard`` 或 ``CandidatePool``
持有，因而 scene 层可以在 offscreen 测试中确定性地启动和检查动画。
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation


class Effects:
    """渲染层动画常量和小型动画工厂。"""

    GHOST_MS = 300
    PULSE_MS = 250
    EDGE_DIM_MS = 200

    @staticmethod
    def _make(
        target,
        property_name: bytes,
        duration: int,
        start_value,
        end_value,
    ) -> QPropertyAnimation:
        animation = QPropertyAnimation(target, property_name)
        animation.setDuration(duration)
        animation.setStartValue(start_value)
        animation.setEndValue(end_value)
        animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        return animation

    @classmethod
    def pulse(cls, target) -> QPropertyAnimation:
        """Create a blue-node pulse animation via ``pulse_scale``."""

        animation = cls._make(target, b"pulse_scale", cls.PULSE_MS, 1.0, 1.0)
        animation.setKeyValueAt(0.5, 1.14)
        return animation

    @classmethod
    def ghost(cls, target, start: float = 1.0) -> QPropertyAnimation:
        """Fade a graphics item to the retained ghost opacity."""

        return cls._make(target, b"visual_opacity", cls.GHOST_MS, start, 0.45)

    @classmethod
    def edge_dim(cls, target, start: float = 1.0) -> QPropertyAnimation:
        """Fade an incident edge without removing it from the scene."""

        return cls._make(target, b"visual_opacity", cls.EDGE_DIM_MS, start, 0.3)
