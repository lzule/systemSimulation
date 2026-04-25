"""世界坐标视图组件。"""

from __future__ import annotations

import math

from simulation.qt_compat import QtCore, QtGui, QtWidgets
from simulation.types import COLOR


class WorldView(QtWidgets.QGraphicsView):
    """世界视图：网格背景 + 轨迹/姿态图元。"""

    def __init__(self) -> None:
        super().__init__()
        self.setRenderHint(QtGui.QPainter.Antialiasing, True)
        self.setBackgroundBrush(QtGui.QColor(COLOR["bg"]))
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.scene().setSceneRect(-120.0, -120.0, 240.0, 240.0)
        self.scale(1.0, -1.0)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self._last_lim = 120.0

    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:  # noqa: N802
        painter.save()
        minor_pen = QtGui.QPen(QtGui.QColor("#edf1f8"), 0)
        major_pen = QtGui.QPen(QtGui.QColor("#d8dfec"), 0)
        step_minor = 5.0
        step_major = 25.0
        left = math.floor(rect.left() / step_minor) * step_minor
        top = math.floor(rect.top() / step_minor) * step_minor
        x = left
        while x <= rect.right():
            painter.setPen(major_pen if abs((x / step_major) - round(x / step_major)) < 1e-9 else minor_pen)
            painter.drawLine(QtCore.QLineF(x, rect.top(), x, rect.bottom()))
            x += step_minor
        y = top
        while y <= rect.bottom():
            painter.setPen(major_pen if abs((y / step_major) - round(y / step_major)) < 1e-9 else minor_pen)
            painter.drawLine(QtCore.QLineF(rect.left(), y, rect.right(), y))
            y += step_minor

        axis_pen = QtGui.QPen(QtGui.QColor("#97a6bf"), 0)
        painter.setPen(axis_pen)
        painter.drawLine(QtCore.QLineF(rect.left(), 0.0, rect.right(), 0.0))
        painter.drawLine(QtCore.QLineF(0.0, rect.top(), 0.0, rect.bottom()))
        painter.restore()

    def ensure_range(self, lim: float) -> None:
        if abs(lim - self._last_lim) < 1e-6:
            return
        self._last_lim = lim
        scene_rect = QtCore.QRectF(-lim, -lim, 2.0 * lim, 2.0 * lim)
        self.scene().setSceneRect(scene_rect)
        self.fitInView(scene_rect, QtCore.Qt.KeepAspectRatio)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), QtCore.Qt.KeepAspectRatio)
