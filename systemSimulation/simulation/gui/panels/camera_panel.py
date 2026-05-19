"""相机视角面板组件。"""

from __future__ import annotations

from typing import Optional

import numpy as np

from simulation.qt_compat import QtCore, QtGui, QtWidgets
from simulation.types import COLOR, FrameSample


class CameraImageView(QtWidgets.QGraphicsView):
    """相机画面视图：图像 + 主点 + 检测点。"""

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setRenderHint(QtGui.QPainter.Antialiasing, True)
        self.setBackgroundBrush(QtGui.QColor("#f4f7fb"))
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setAlignment(QtCore.Qt.AlignCenter)

        self.pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self.scene().addItem(self.pixmap_item)

        pen_center = QtGui.QPen(QtGui.QColor(COLOR["center"]), 1.0, QtCore.Qt.DashLine)
        self.center_v = QtWidgets.QGraphicsLineItem()
        self.center_v.setPen(pen_center)
        self.scene().addItem(self.center_v)
        self.center_h = QtWidgets.QGraphicsLineItem()
        self.center_h.setPen(pen_center)
        self.scene().addItem(self.center_h)

        # 检测中心十字标记（替代原实心红点，不遮挡底层光斑）
        cross_pen = QtGui.QPen(QtGui.QColor(COLOR["target"]), 1.0)
        self.target_cross_h = QtWidgets.QGraphicsLineItem(-4.0, 0.0, 4.0, 0.0)
        self.target_cross_h.setPen(cross_pen)
        self.scene().addItem(self.target_cross_h)
        self.target_cross_v = QtWidgets.QGraphicsLineItem(0.0, -4.0, 0.0, 4.0)
        self.target_cross_v.setPen(cross_pen)
        self.scene().addItem(self.target_cross_v)

        # 光斑轮廓圈（sigma 同步，半径 = 3*sigma）
        self.target_outline_item = QtWidgets.QGraphicsEllipseItem(-9.0, -9.0, 18.0, 18.0)
        outline_color = QtGui.QColor(COLOR["target"])
        outline_color.setAlpha(140)
        self.target_outline_item.setPen(QtGui.QPen(outline_color, 1.0, QtCore.Qt.DashLine))
        self.target_outline_item.setBrush(QtGui.QBrush(QtCore.Qt.NoBrush))
        self.scene().addItem(self.target_outline_item)

    @staticmethod
    def _to_pixmap(gray_image: np.ndarray) -> QtGui.QPixmap:
        h, w = gray_image.shape
        image = QtGui.QImage(gray_image.data, w, h, gray_image.strides[0], QtGui.QImage.Format_Grayscale8)
        return QtGui.QPixmap.fromImage(image.copy())

    def update_frame(self, frame_sample: Optional[FrameSample]) -> None:
        if frame_sample is None:
            return
        pixmap = self._to_pixmap(frame_sample.image)
        self.pixmap_item.setPixmap(pixmap)
        w = float(pixmap.width())
        h = float(pixmap.height())
        self.scene().setSceneRect(0.0, 0.0, w, h)

        cx = float(frame_sample.intrinsics.get("cx", w * 0.5))
        cy = float(frame_sample.intrinsics.get("cy", h * 0.5))
        self.center_v.setLine(cx, 0.0, cx, h)
        self.center_h.setLine(0.0, cy, w, cy)

        det = frame_sample.detection
        if det.found and det.cx is not None and det.cy is not None:
            cx_f, cy_f = float(det.cx), float(det.cy)
            self.target_cross_h.setLine(cx_f - 4.0, cy_f, cx_f + 4.0, cy_f)
            self.target_cross_v.setLine(cx_f, cy_f - 4.0, cx_f, cy_f + 4.0)
            self.target_cross_h.setVisible(True)
            self.target_cross_v.setVisible(True)
            sigma_px = float(frame_sample.intrinsics.get("sigma_px", 3.0))
            r = max(2.0, 3.0 * sigma_px)
            self.target_outline_item.setRect(-r, -r, 2 * r, 2 * r)
            self.target_outline_item.setVisible(True)
            self.target_outline_item.setPos(cx_f, cy_f)
        else:
            self.target_cross_h.setVisible(False)
            self.target_cross_v.setVisible(False)
            self.target_outline_item.setVisible(False)

        self.fitInView(self.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self.scene().sceneRect().isNull():
            self.fitInView(self.scene().sceneRect(), QtCore.Qt.KeepAspectRatio)


class CameraPanel(QtWidgets.QWidget):
    """单路视角面板：上方信息条 + 下方图像。"""

    def __init__(self, title: str):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setStyleSheet("font-weight: 700;")
        self.info_label = QtWidgets.QLabel("--")
        self.info_label.setStyleSheet(f"color: {COLOR['text_sub']};")
        self.info_label.setAlignment(QtCore.Qt.AlignCenter)
        self.info_label.setWordWrap(True)
        self.view = CameraImageView()
        self.view.setMinimumHeight(260)

        layout.addWidget(self.title_label)
        layout.addWidget(self.info_label)
        layout.addWidget(self.view, 1)

    def set_info_text(self, text: str, ok: bool) -> None:
        self.info_label.setText(text)
        self.info_label.setStyleSheet(f"color: {COLOR['ok' if ok else 'warn']};")
