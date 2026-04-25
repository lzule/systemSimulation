"""
PyQt5 camera pinhole viewer.

Run:
    python tools/camera_3d_viewer.py
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass

from PyQt5 import QtCore, QtGui, QtWidgets

import matplotlib

matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import CameraConfig, camera_cfg
from entities.camera.model import CameraImagingModel


matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "WenQuanYi Zen Hei",
    "Arial Unicode MS",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False


COLORS = {
    "bg": "#FFFFFF",
    "grid": "#D3D9E3",
    "card_bg": "#F5F7FF",
    "card_edge": "#AEBFFF",
    "optical": "#1565C0",
    "fov": "#E67E22",
    "target": "#C62828",
    "ok": "#2E7D32",
    "warn": "#D32F2F",
    "txt": "#1B2440",
}


@dataclass
class ProjectionState:
    u_px: float
    v_px: float
    in_sensor: bool


class MatplotlibCard(FigureCanvas):
    def __init__(self, width: float, height: float, dpi: int = 100):
        fig = Figure(figsize=(width, height), dpi=dpi, facecolor=COLORS["card_bg"])
        super().__init__(fig)
        self.figure = fig
        self.setStyleSheet(
            f"background:{COLORS['card_bg']}; border:1px solid {COLORS['card_edge']}; border-radius:8px;"
        )


class CameraViewerWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("相机针孔模型可视化（PyQt5）")
        self.resize(1580, 980)

        self.cfg = CameraConfig()
        self.cfg.focal_length_mm = camera_cfg.focal_length_mm
        self.cam_model = CameraImagingModel(self.cfg)

        self.target_dist_m = 30.0
        self.target_x_m = 1.0
        self.target_y_m = 0.6
        self.default_elev = 20
        self.default_azim = -58
        self._validated_once = False

        self._build_ui()
        self._update_all()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        title = QtWidgets.QLabel("相机针孔模型可视化")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size:30px; font-weight:700; color:#101827;")
        root.addWidget(title)

        content = QtWidgets.QHBoxLayout()
        content.setSpacing(12)
        root.addLayout(content, 1)

        # Left: 3D
        self.canvas3d = MatplotlibCard(width=8.5, height=6.0)
        self.ax3d = self.canvas3d.figure.add_subplot(111, projection="3d")
        content.addWidget(self.canvas3d, 3)

        # Right: 2D + info
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        content.addLayout(right, 2)

        self.canvas2d = MatplotlibCard(width=5.0, height=3.0)
        self.ax2d = self.canvas2d.figure.add_subplot(111)
        right.addWidget(self.canvas2d, 3)

        self.info_card = QtWidgets.QFrame()
        self.info_card.setStyleSheet(
            f"background:{COLORS['card_bg']}; border:1px solid {COLORS['card_edge']}; border-radius:8px;"
        )
        info_layout = QtWidgets.QVBoxLayout(self.info_card)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(8)

        info_title = QtWidgets.QLabel("参数与说明")
        info_title.setStyleSheet("font-size:24px; font-weight:700; color:#1B2440; border:none;")
        info_layout.addWidget(info_title)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet(f"color:{COLORS['card_edge']};")
        info_layout.addWidget(sep)

        self.info_grid = QtWidgets.QGridLayout()
        self.info_grid.setHorizontalSpacing(20)
        self.info_grid.setVerticalSpacing(6)
        info_layout.addLayout(self.info_grid)

        self.value_labels: dict[str, QtWidgets.QLabel] = {}
        keys = [
            "f_mm",
            "f_px",
            "FOV_h",
            "px/deg",
            "1px@target",
            "FOV_span@D",
            "u(px)",
            "v(px)",
            "在传感器内?",
        ]
        for i, k in enumerate(keys):
            lk = QtWidgets.QLabel(k)
            lk.setStyleSheet("font-size:20px; color:#1B2440; border:none;")
            lv = QtWidgets.QLabel("")
            lv.setStyleSheet("font-size:20px; color:#1B2440; border:none;")
            self.info_grid.addWidget(lk, i, 0, alignment=QtCore.Qt.AlignLeft)
            self.info_grid.addWidget(lv, i, 1, alignment=QtCore.Qt.AlignLeft)
            self.value_labels[k] = lv

        right.addWidget(self.info_card, 2)

        # Bottom controls
        controls = QtWidgets.QFrame()
        controls.setStyleSheet("background:#FFFFFF; border:none;")
        ctl_layout = QtWidgets.QGridLayout(controls)
        ctl_layout.setContentsMargins(4, 0, 4, 0)
        ctl_layout.setHorizontalSpacing(24)
        ctl_layout.setVerticalSpacing(12)
        root.addWidget(controls, 0)

        self.sliders: dict[str, QtWidgets.QSlider] = {}
        self.slider_values: dict[str, QtWidgets.QLabel] = {}

        def add_slider(row: int, col_base: int, key: str, text: str, vmin: float, vmax: float, vinit: float, scale: int = 100):
            label = QtWidgets.QLabel(text)
            label.setStyleSheet("font-size:18px; color:#111827;")
            slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            slider.setMinimum(int(vmin * scale))
            slider.setMaximum(int(vmax * scale))
            slider.setValue(int(vinit * scale))
            slider.setSingleStep(1)
            value = QtWidgets.QLabel(f"{vinit:.2f}")
            value.setFixedWidth(90)
            value.setAlignment(QtCore.Qt.AlignCenter)
            value.setStyleSheet("font-size:20px; color:#1B2440; border:1px solid #CDD5E3; border-radius:6px; padding:2px 6px;")

            ctl_layout.addWidget(label, row, col_base + 0, 1, 1)
            ctl_layout.addWidget(slider, row, col_base + 1, 1, 4)
            ctl_layout.addWidget(value, row, col_base + 5, 1, 1)

            self.sliders[key] = slider
            self.slider_values[key] = value

            return scale

        self.scale_f = add_slider(0, 0, "focal", "f (mm)", self.cfg.focal_min_mm, min(self.cfg.focal_max_mm, 200.0), self.cfg.focal_length_mm)
        self.scale_d = add_slider(0, 6, "dist", "Dist (m)", 5.0, 200.0, self.target_dist_m)
        self.scale_tx = add_slider(1, 0, "tx", "Target X (m)", -10.0, 10.0, self.target_x_m)
        self.scale_ty = add_slider(1, 6, "ty", "Target Y (m)", -10.0, 10.0, self.target_y_m)

        btn_box = QtWidgets.QVBoxLayout()
        self.btn_reset_view = QtWidgets.QPushButton("Reset View")
        self.btn_reset_param = QtWidgets.QPushButton("Reset Params")
        for b in (self.btn_reset_view, self.btn_reset_param):
            b.setStyleSheet("font-size:18px; padding:8px 14px;")
            btn_box.addWidget(b)
        ctl_layout.addLayout(btn_box, 0, 12, 2, 1)

        for s in self.sliders.values():
            s.valueChanged.connect(self._on_slider_changed)
        self.btn_reset_view.clicked.connect(self._on_reset_view)
        self.btn_reset_param.clicked.connect(self._on_reset_params)

    def _on_slider_changed(self):
        self.cfg.focal_length_mm = self.sliders["focal"].value() / self.scale_f
        self.target_dist_m = self.sliders["dist"].value() / self.scale_d
        self.target_x_m = self.sliders["tx"].value() / self.scale_tx
        self.target_y_m = self.sliders["ty"].value() / self.scale_ty
        self.cam_model = CameraImagingModel(self.cfg)

        self.slider_values["focal"].setText(f"{self.cfg.focal_length_mm:.2f}")
        self.slider_values["dist"].setText(f"{self.target_dist_m:.2f}")
        self.slider_values["tx"].setText(f"{self.target_x_m:.2f}")
        self.slider_values["ty"].setText(f"{self.target_y_m:.2f}")

        self._update_all()

    def _on_reset_view(self):
        self.ax3d.view_init(elev=self.default_elev, azim=self.default_azim)
        self.canvas3d.draw_idle()

    def _on_reset_params(self):
        self.sliders["focal"].setValue(int(camera_cfg.focal_length_mm * self.scale_f))
        self.sliders["dist"].setValue(int(30.0 * self.scale_d))
        self.sliders["tx"].setValue(int(1.0 * self.scale_tx))
        self.sliders["ty"].setValue(int(0.6 * self.scale_ty))

    def _project(self) -> ProjectionState:
        c = self.cfg
        z_mm = self.target_dist_m * 1000.0
        x_mm = self.target_x_m * 1000.0
        y_mm = self.target_y_m * 1000.0

        fx = c.focal_length_px
        fy = fx
        u = fx * (x_mm / z_mm) + c.cx
        v = fy * (y_mm / z_mm) + (c.resolution_h / 2.0)
        in_sensor = (0.0 <= u <= c.resolution_w) and (0.0 <= v <= c.resolution_h)
        return ProjectionState(u_px=u, v_px=v, in_sensor=in_sensor)

    def _validate_projection(self, p: ProjectionState):
        if self.target_dist_m <= 0:
            return

        alpha_x = math.atan2(self.target_x_m, self.target_dist_m)
        u_model = self.cam_model.focal_px(self.cfg.focal_length_mm) * math.tan(alpha_x) + self.cfg.cx
        assert abs(u_model - p.u_px) < 1e-6

        base_e = abs(p.u_px - self.cfg.cx)
        test_f = self.cfg.focal_length_mm * 1.1
        fx2 = test_f / self.cfg.pixel_size_mm
        u2 = fx2 * (self.target_x_m / self.target_dist_m) + self.cfg.cx
        assert abs(u2 - self.cfg.cx) >= base_e - 1e-9

        far_d = self.target_dist_m * 1.2
        u_far = self.cfg.focal_length_px * (self.target_x_m / far_d) + self.cfg.cx
        assert abs(u_far - self.cfg.cx) <= base_e + 1e-9

        in_ref = (0.0 <= p.u_px <= self.cfg.resolution_w) and (0.0 <= p.v_px <= self.cfg.resolution_h)
        assert p.in_sensor == in_ref

        if not self._validated_once:
            self.statusBar().showMessage("投影计算校验通过", 3000)
            self._validated_once = True

    def _draw_3d(self, p: ProjectionState):
        ax = self.ax3d
        c = self.cfg
        ax.clear()
        ax.set_facecolor(COLORS["bg"])
        ax.grid(True, color=COLORS["grid"], alpha=0.85)

        fov_half = math.radians(c.fov_h_deg / 2.0)
        d = self.target_dist_m
        x_t, y_t, z_t = self.target_x_m, self.target_y_m, d
        fov_span = 2.0 * d * math.tan(fov_half)
        half_w = fov_span / 2.0
        half_h = half_w * (c.sensor_h_mm / c.sensor_w_mm)

        ax.scatter([0], [0], [0], color=COLORS["optical"], s=82, label="针孔")
        ax.quiver(0, 0, 0, 0, 0, max(1.0, d * 0.35), color=COLORS["optical"], linewidth=2.2, arrow_length_ratio=0.08)

        corners = [(-half_w, -half_h, d), (half_w, -half_h, d), (half_w, half_h, d), (-half_w, half_h, d)]
        for cx, cy, cz in corners:
            ax.plot([0, cx], [0, cy], [0, cz], "--", lw=1.2, color=COLORS["fov"], alpha=0.8)
        for i0, i1 in ((0, 1), (1, 2), (2, 3), (3, 0)):
            a, b = corners[i0], corners[i1]
            ax.plot([a[0], b[0]], [a[1], b[1]], [a[2], b[2]], color=COLORS["fov"], lw=1.5)
        faces = [[[0, 0, 0], corners[0], corners[1]], [[0, 0, 0], corners[1], corners[2]], [[0, 0, 0], corners[2], corners[3]], [[0, 0, 0], corners[3], corners[0]]]
        ax.add_collection3d(Poly3DCollection(faces, facecolor=COLORS["fov"], alpha=0.08, edgecolor="none"))

        ax.scatter([x_t], [y_t], [z_t], color=COLORS["target"], s=95, label="目标点")
        ax.plot([0, x_t], [0, y_t], [0, z_t], color=COLORS["target"], lw=1.9, alpha=0.88)
        ax.text(x_t, y_t, z_t, f"  T({x_t:.1f},{y_t:.1f},{z_t:.1f})m", color=COLORS["target"], fontsize=9)

        lim_xy = max(abs(x_t), abs(y_t), half_w, 2.0) * 1.25
        ax.set_xlim(-lim_xy, lim_xy)
        ax.set_ylim(-lim_xy, lim_xy)
        ax.set_zlim(0.0, max(3.0, d * 1.12))
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")
        ax.set_zlabel("Z (m, optical axis)")
        ax.set_title("3D 场景视图：相机朝向与 FOV", fontsize=12, fontweight="bold", pad=8)
        ax.view_init(elev=self.default_elev, azim=self.default_azim)
        ax.legend(loc="upper left", fontsize=10)

        self.canvas3d.draw_idle()

    def _draw_2d(self, p: ProjectionState):
        ax = self.ax2d
        c = self.cfg
        ax.clear()
        ax.set_facecolor(COLORS["card_bg"])
        for sp in ax.spines.values():
            sp.set_color(COLORS["card_edge"])
            sp.set_linewidth(1.4)

        ax.grid(True, color=COLORS["grid"], linestyle="--", alpha=0.8)
        ax.set_title("2D 像平面视图：目标投影位置", fontsize=12, fontweight="bold")
        ax.set_xlim(0, c.resolution_w)
        ax.set_ylim(c.resolution_h, 0)
        ax.set_xlabel("u / px")
        ax.set_ylabel("v / px")

        ax.add_patch(
            matplotlib.patches.Rectangle((0, 0), c.resolution_w, c.resolution_h, fill=False, edgecolor=COLORS["optical"], linewidth=2.0, label="传感器边框")
        )
        cx = c.cx
        cy = c.resolution_h / 2.0
        ax.axvline(cx, color=COLORS["optical"], linestyle=":", linewidth=1.5)
        ax.axhline(cy, color=COLORS["optical"], linestyle=":", linewidth=1.5)
        ax.text(cx + 6, 18, "cx", color=COLORS["optical"], fontsize=10)
        ax.text(8, cy - 8, "cy", color=COLORS["optical"], fontsize=10)

        status_color = COLORS["ok"] if p.in_sensor else COLORS["warn"]
        status_txt = "在传感器内" if p.in_sensor else "超出传感器范围"
        ax.scatter([p.u_px], [p.v_px], color=status_color, s=95, label="投影点", zorder=5)
        ax.text(
            8,
            c.resolution_h - 10,
            f"u={p.u_px:.1f}px, v={p.v_px:.1f}px, 状态：{status_txt}",
            fontsize=10.5,
            color=status_color,
            va="top",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#FFFFFF", edgecolor=status_color, alpha=0.96),
        )
        ax.legend(loc="upper right", fontsize=10)

        self.canvas2d.draw_idle()

    def _update_info(self, p: ProjectionState):
        c = self.cfg
        fov_half = math.radians(c.fov_h_deg / 2.0)
        fov_span = 2.0 * self.target_dist_m * math.tan(fov_half)
        mm_per_px = self.target_dist_m * 1000.0 * math.tan(math.atan(1.0 / c.focal_length_px))

        values = {
            "f_mm": f"{c.focal_length_mm:8.2f} mm",
            "f_px": f"{c.focal_length_px:8.2f} px",
            "FOV_h": f"{c.fov_h_deg:8.2f} deg",
            "px/deg": f"{c.px_per_deg:8.2f}",
            "1px@target": f"{mm_per_px:8.2f} mm",
            "FOV_span@D": f"{fov_span:8.2f} m",
            "u(px)": f"{p.u_px:8.2f}",
            "v(px)": f"{p.v_px:8.2f}",
            "在传感器内?": "是" if p.in_sensor else "否",
        }
        for k, v in values.items():
            self.value_labels[k].setText(v)

    def _update_all(self):
        p = self._project()
        self._validate_projection(p)
        self._draw_3d(p)
        self._draw_2d(p)
        self._update_info(p)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("camera_3d_viewer")
    win = CameraViewerWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

