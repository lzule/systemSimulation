"""主仪表盘窗口实现。"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Optional

import numpy as np

from simulation.bootstrap import build_runtime, load_control_program_from_path
from simulation.gui.panels import CameraPanel, WorldView
from simulation.qt_compat import QtCore, QtGui, QtWidgets, pg
from simulation.state_buffer import UiStateBuffer
from simulation.types import AppConfig, COLOR, FrameSample, UI_TEXT, wrap_pm180
from simulation.worker import SimWorker


class DashboardWindow(QtWidgets.QMainWindow):
    """实时仪表盘窗口。"""

    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.cfg = cfg
        self._last_ui_perf = time.perf_counter()
        self._ui_tick_counter = 0
        self._fps_value = 0.0
        self._settings = QtCore.QSettings("zoom_pid", "dashboard")

        self.setWindowTitle(UI_TEXT["title"])
        self.resize(1680, 980)
        self.setMinimumSize(1360, 860)
        self.setStyleSheet(
            f"""
            QWidget {{
                font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", sans-serif;
                font-size: 10pt;
                color: {COLOR["text_main"]};
            }}
            QMainWindow, QFrame, QWidget {{
                background-color: {COLOR["bg"]};
            }}
            QGroupBox {{
                background: {COLOR["panel"]};
                border: 1px solid {COLOR["border"]};
                border-radius: 8px;
                margin-top: 8px;
                font-weight: 700;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px 0 4px;
            }}
            QPushButton {{
                min-height: 30px;
                border: 1px solid {COLOR["border"]};
                border-radius: 6px;
                background: #ffffff;
                padding: 2px 10px;
            }}
            QPushButton:hover {{
                background: #f0f4fb;
            }}
            QTabWidget::pane {{
                border: 1px solid {COLOR["border"]};
                background: {COLOR["panel"]};
                border-radius: 6px;
            }}
            QTabBar::tab {{
                min-width: 96px;
                padding: 4px 8px;
            }}
            QLabel[state="kv_label"] {{
                font-weight: 600;
                qproperty-alignment: "AlignCenter";
            }}
            QLabel[state="kv_value"] {{
                font-weight: 700;
                qproperty-alignment: "AlignCenter";
            }}
            """
        )

        cp = load_control_program_from_path(self.cfg.control_program_path) if self.cfg.control_program_path else None
        self.runtime = build_runtime(self.cfg.delay_ms, control_program=cp)
        self.state_buf = UiStateBuffer()
        self.worker = SimWorker(self.runtime, self.state_buf, mode=self.cfg.mode, duration_s=self.cfg.duration_s, sim_hz=200.0)
        self.worker.error_signal.connect(self._on_worker_error)
        self.worker.finished_signal.connect(self._on_worker_finished)

        self._build_ui()
        self._build_world_items()
        self._build_timeline()

        self.ui_timer = QtCore.QTimer(self)
        self.ui_timer.setInterval(33)
        self.ui_timer.timeout.connect(self._render_tick)
        self.ui_timer.start()

        self.worker.start()
        if self.cfg.mode == "realtime":
            self._on_start()

    def _build_ui(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        root_layout = QtWidgets.QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        toolbar_box = QtWidgets.QGroupBox("控制栏")
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar_box)
        toolbar_layout.setContentsMargins(8, 8, 8, 8)

        self.btn_start = QtWidgets.QPushButton(UI_TEXT["start"])
        self.btn_pause = QtWidgets.QPushButton(UI_TEXT["pause"])
        self.btn_reset = QtWidgets.QPushButton(UI_TEXT["reset"])
        self.btn_save = QtWidgets.QPushButton(UI_TEXT["save"])
        self.delay_label = QtWidgets.QLabel(UI_TEXT["delay_label"])
        self.delay_spin = QtWidgets.QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 500.0)
        self.delay_spin.setSingleStep(5.0)
        self.delay_spin.setDecimals(1)
        self.delay_spin.setValue(self.cfg.delay_ms)
        self.btn_apply_delay = QtWidgets.QPushButton(UI_TEXT["apply_delay"])

        self.lbl_fps = QtWidgets.QLabel(f"{UI_TEXT['fps']}: 0.0")
        self.lbl_runtime_state = QtWidgets.QLabel(UI_TEXT["paused"])
        self.lbl_runtime_state.setStyleSheet(f"color: {COLOR['warn']}; font-weight: 700;")

        for w in (
            self.btn_start,
            self.btn_pause,
            self.btn_reset,
            self.btn_save,
            self.delay_label,
            self.delay_spin,
            self.btn_apply_delay,
        ):
            toolbar_layout.addWidget(w)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self.lbl_fps)
        toolbar_layout.addWidget(self.lbl_runtime_state)
        root_layout.addWidget(toolbar_box)

        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        root_layout.addWidget(self.main_splitter, 1)

        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        world_box = QtWidgets.QGroupBox("世界视图（轨迹 / 云台指向 / FOV）")
        world_layout = QtWidgets.QVBoxLayout(world_box)
        world_layout.setContentsMargins(8, 8, 8, 8)
        self.world_view = WorldView()
        world_layout.addWidget(self.world_view)
        left_layout.addWidget(world_box, 6)

        timeline_box = QtWidgets.QGroupBox("底部时间轴（误差 / 命令 / 角度误差）")
        timeline_layout = QtWidgets.QVBoxLayout(timeline_box)
        timeline_layout.setContentsMargins(8, 8, 8, 8)
        self.timeline_plot = pg.PlotWidget() if pg is not None else QtWidgets.QLabel("pyqtgraph 未安装，无法显示曲线")
        timeline_layout.addWidget(self.timeline_plot)
        left_layout.addWidget(timeline_box, 4)

        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        camera_row_box = QtWidgets.QGroupBox("双视角对比")
        camera_row_layout = QtWidgets.QHBoxLayout(camera_row_box)
        camera_row_layout.setContentsMargins(8, 8, 8, 8)
        camera_row_layout.setSpacing(8)
        self.raw_panel = CameraPanel("相机原始视角")
        self.raspi_panel = CameraPanel("Raspi 延时视角")
        camera_row_layout.addWidget(self.raw_panel, 1)
        camera_row_layout.addWidget(self.raspi_panel, 1)
        right_layout.addWidget(camera_row_box, 6)

        tab_box = QtWidgets.QGroupBox("信息区")
        tab_box_layout = QtWidgets.QVBoxLayout(tab_box)
        tab_box_layout.setContentsMargins(8, 8, 8, 8)
        self.info_tabs = QtWidgets.QTabWidget()
        self.tab_core = QtWidgets.QWidget()
        self.tab_diag = QtWidgets.QWidget()
        self.info_tabs.addTab(self.tab_core, UI_TEXT["tab_core"])
        self.info_tabs.addTab(self.tab_diag, UI_TEXT["tab_diag"])
        self.info_tabs.setCurrentIndex(0)
        tab_box_layout.addWidget(self.info_tabs)
        right_layout.addWidget(tab_box, 4)

        self._build_core_tab()
        self._build_diag_tab()

        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(right_panel)

        saved = self._settings.value("main_splitter_sizes", None)
        if isinstance(saved, list) and len(saved) == 2:
            try:
                self.main_splitter.setSizes([int(saved[0]), int(saved[1])])
            except Exception:  # noqa: BLE001
                self.main_splitter.setSizes([960, 640])
        else:
            self.main_splitter.setSizes([960, 640])

        self.btn_start.clicked.connect(self._on_start)
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_apply_delay.clicked.connect(self._on_apply_delay)

    def _build_core_tab(self) -> None:
        layout = QtWidgets.QGridLayout(self.tab_core)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)

        rows = [
            ("仿真时间", "t", "控制模式", "mode"),
            ("姿态 yaw", "yaw", "姿态 pitch", "pitch"),
            ("角速度", "yaw_rate", "角度误差", "angle_err"),
            ("像素 u", "u", "像素 v", "v"),
            ("偏差 du", "du", "偏差 dv", "dv"),
            ("在视野内", "in_fov", "Raspi backlog", "backlog"),
            ("obs_lag", "obs_lag", "", ""),
        ]
        self.core_value_labels: dict[str, QtWidgets.QLabel] = {}

        for row_idx, (l1, k1, l2, k2) in enumerate(rows):
            label1 = QtWidgets.QLabel(l1)
            label1.setProperty("state", "kv_label")
            value1 = QtWidgets.QLabel("--")
            value1.setProperty("state", "kv_value")
            layout.addWidget(label1, row_idx, 0)
            layout.addWidget(value1, row_idx, 1)
            self.core_value_labels[k1] = value1

            label2 = QtWidgets.QLabel(l2)
            label2.setProperty("state", "kv_label")
            value2 = QtWidgets.QLabel("--" if k2 else "")
            value2.setProperty("state", "kv_value")
            layout.addWidget(label2, row_idx, 2)
            layout.addWidget(value2, row_idx, 3)
            if k2:
                self.core_value_labels[k2] = value2

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        layout.setColumnStretch(3, 1)

    def _build_diag_tab(self) -> None:
        layout = QtWidgets.QVBoxLayout(self.tab_diag)
        layout.setContentsMargins(8, 8, 8, 8)
        self.diag_entity_tabs = QtWidgets.QTabWidget()
        self.diag_entity_tabs.setStyleSheet(
            """
            QTabBar::tab {
                min-width: 72px;
                padding: 2px 6px;
                font-size: 9pt;
            }
            """
        )
        layout.addWidget(self.diag_entity_tabs)

        self.diag_entity_tables: dict[str, QtWidgets.QTableWidget] = {}
        for key, title in (
            ("gimbal", "云台"),
            ("camera", "相机"),
            ("raspi", "树莓派"),
            ("target", "目标"),
        ):
            tab = QtWidgets.QWidget()
            tab_layout = QtWidgets.QVBoxLayout(tab)
            tab_layout.setContentsMargins(4, 4, 4, 4)
            table = QtWidgets.QTableWidget()
            table.setColumnCount(4)
            table.setHorizontalHeaderLabels(["字段", "值", "字段", "值"])
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
            table.setFocusPolicy(QtCore.Qt.NoFocus)
            table.setAlternatingRowColors(True)
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
            table.setStyleSheet(
                """
                QTableWidget {
                    background: #ffffff;
                    border: 1px solid #d6dce7;
                    gridline-color: #e8edf6;
                    border-radius: 6px;
                }
                QHeaderView::section {
                    background: #f0f4fb;
                    font-weight: 700;
                    border: 1px solid #d6dce7;
                    padding: 5px;
                    color: #1f2a44;
                }
                """
            )
            table.setShowGrid(True)
            tab_layout.addWidget(table)
            self.diag_entity_tabs.addTab(tab, title)
            self.diag_entity_tables[key] = table

    def _build_world_items(self) -> None:
        scene = self.world_view.scene()
        self.world_traj_item = QtWidgets.QGraphicsPathItem()
        self.world_traj_item.setPen(QtGui.QPen(QtGui.QColor(COLOR["traj"]), 1.8))
        scene.addItem(self.world_traj_item)

        self.world_target_item = QtWidgets.QGraphicsEllipseItem(-2.8, -2.8, 5.6, 5.6)
        self.world_target_item.setPen(QtGui.QPen(QtGui.QColor(COLOR["target"]), 1.2))
        self.world_target_item.setBrush(QtGui.QBrush(QtGui.QColor(COLOR["target"])))
        scene.addItem(self.world_target_item)

        self.world_origin_item = QtWidgets.QGraphicsEllipseItem(-2.4, -2.4, 4.8, 4.8)
        self.world_origin_item.setPen(QtGui.QPen(QtGui.QColor(COLOR["origin"]), 1.2))
        self.world_origin_item.setBrush(QtGui.QBrush(QtGui.QColor(COLOR["origin"])))
        scene.addItem(self.world_origin_item)

        self.world_gimbal_line = QtWidgets.QGraphicsLineItem()
        self.world_gimbal_line.setPen(QtGui.QPen(QtGui.QColor(COLOR["gimbal"]), 1.8, QtCore.Qt.DashLine))
        scene.addItem(self.world_gimbal_line)

        self.world_fov_left = QtWidgets.QGraphicsLineItem()
        self.world_fov_left.setPen(QtGui.QPen(QtGui.QColor(COLOR["fov"]), 1.2))
        scene.addItem(self.world_fov_left)
        self.world_fov_right = QtWidgets.QGraphicsLineItem()
        self.world_fov_right.setPen(QtGui.QPen(QtGui.QColor(COLOR["fov"]), 1.2))
        scene.addItem(self.world_fov_right)
        self.world_fov_arc = QtWidgets.QGraphicsPathItem()
        self.world_fov_arc.setPen(QtGui.QPen(QtGui.QColor(COLOR["fov"]), 1.2))
        scene.addItem(self.world_fov_arc)

        self.world_title = QtWidgets.QGraphicsSimpleTextItem("")
        self.world_title.setBrush(QtGui.QBrush(QtGui.QColor(COLOR["text_main"])))
        self.world_title.setFont(QtGui.QFont("Microsoft YaHei UI", 9))
        self.world_title.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations, True)
        scene.addItem(self.world_title)

    def _build_timeline(self) -> None:
        if pg is None or not isinstance(self.timeline_plot, pg.PlotWidget):
            return

        self.timeline_plot.setBackground("#ffffff")
        self.timeline_plot.showGrid(x=True, y=True, alpha=0.24)
        self.timeline_plot.addLegend(offset=(8, 8))
        self.timeline_plot.setLabel("bottom", "t", units="s")
        self.timeline_plot.setLabel("left", "value")
        self.timeline_plot.getAxis("left").setStyle(tickTextOffset=10)
        self.timeline_plot.getAxis("bottom").setStyle(tickTextOffset=8)

        self.curve_err = self.timeline_plot.plot(
            [], [], pen=pg.mkPen(COLOR["err"], width=2), name="pixel_error_x (px)"
        )
        self.curve_rate = self.timeline_plot.plot(
            [], [], pen=pg.mkPen(COLOR["rate"], width=2), name="yaw_rate_ref (dps)"
        )
        self.curve_angle = self.timeline_plot.plot(
            [], [], pen=pg.mkPen(COLOR["angle"], width=2), name="angle_err (deg)"
        )

    def _set_runtime_state(self, text: str, running: bool) -> None:
        self.lbl_runtime_state.setText(text)
        self.lbl_runtime_state.setStyleSheet(f"color: {COLOR['ok' if running else 'warn']}; font-weight: 700;")

    def _on_start(self) -> None:
        self.worker.set_paused(False)
        self._set_runtime_state(UI_TEXT["running"], True)
        self.statusBar().showMessage(UI_TEXT["running"], 1200)

    def _on_pause(self) -> None:
        self.worker.set_paused(True)
        self._set_runtime_state(UI_TEXT["paused"], False)
        self.statusBar().showMessage(UI_TEXT["paused"], 1200)

    def _on_reset(self) -> None:
        self.worker.set_paused(True)
        self.worker.stop()
        self.worker.wait(2000)

        cp = load_control_program_from_path(self.cfg.control_program_path) if self.cfg.control_program_path else None
        self.runtime = build_runtime(float(self.delay_spin.value()), control_program=cp)
        self.state_buf.clear()
        self.worker = SimWorker(self.runtime, self.state_buf, mode=self.cfg.mode, duration_s=self.cfg.duration_s, sim_hz=200.0)
        self.worker.error_signal.connect(self._on_worker_error)
        self.worker.finished_signal.connect(self._on_worker_finished)
        self.worker.start()
        if self.cfg.mode == "realtime":
            self._on_start()
        self.statusBar().showMessage(UI_TEXT["reset_done"], 1500)

    def _on_save(self) -> None:
        os.makedirs("output", exist_ok=True)
        path = os.path.join("output", f"dashboard_snapshot_{int(time.time())}.png")
        self.grab().save(path)
        self.statusBar().showMessage(f"{UI_TEXT['save_done']}: {path}", 2500)

    def _on_apply_delay(self) -> None:
        delay_ms = float(self.delay_spin.value())
        self.worker.request_delay_ms(delay_ms)
        self.statusBar().showMessage(f"{UI_TEXT['apply_delay_done']}: {delay_ms:.1f} ms", 2000)

    def _on_worker_error(self, err: str) -> None:
        QtWidgets.QMessageBox.critical(self, UI_TEXT["thread_error"], err)
        self._on_pause()

    def _on_worker_finished(self) -> None:
        self.worker.set_paused(True)
        self._set_runtime_state(UI_TEXT["finished"], False)
        self.statusBar().showMessage(UI_TEXT["finished"], 2000)

    @staticmethod
    def _decimate_xy(x: np.ndarray, y: np.ndarray, max_points: int = 700) -> tuple[np.ndarray, np.ndarray]:
        """简单等距降采样，避免高频曲线绘制过粗或过密。"""
        n = len(x)
        if n <= max_points:
            return x, y
        step = max(1, n // max_points)
        return x[::step], y[::step]

    def _draw_world(self, snapshot: Any, x_hist: list[float], y_hist: list[float]) -> None:
        if not x_hist:
            return

        x_m = float(snapshot.target["x_m"])
        y_m = float(snapshot.target["y_m"])
        yaw_deg = float(snapshot.gimbal["yaw_deg_display"])
        yaw_rad = math.radians(yaw_deg)
        bearing_deg = math.degrees(math.atan2(y_m, x_m))
        angle_err = wrap_pm180(bearing_deg - float(snapshot.gimbal["yaw_deg_internal"]))

        path = QtGui.QPainterPath()
        path.moveTo(x_hist[0], y_hist[0])
        for x, y in zip(x_hist[1:], y_hist[1:]):
            path.lineTo(x, y)
        self.world_traj_item.setPath(path)
        self.world_target_item.setPos(x_m, y_m)
        self.world_origin_item.setPos(0.0, 0.0)

        line_len = max(20.0, math.hypot(x_m, y_m))
        gx = line_len * math.cos(yaw_rad)
        gy = line_len * math.sin(yaw_rad)
        self.world_gimbal_line.setLine(0.0, 0.0, gx, gy)

        f_mm = float(snapshot.camera["f_current_mm"])
        sensor_w_mm = 4.8
        fov_h_deg = 2.0 * math.degrees(math.atan(sensor_w_mm / (2.0 * max(1e-6, f_mm))))
        ang_l = math.radians(yaw_deg - fov_h_deg / 2.0)
        ang_r = math.radians(yaw_deg + fov_h_deg / 2.0)
        radius = line_len * 0.75
        self.world_fov_left.setLine(0.0, 0.0, radius * math.cos(ang_l), radius * math.sin(ang_l))
        self.world_fov_right.setLine(0.0, 0.0, radius * math.cos(ang_r), radius * math.sin(ang_r))

        arc = QtGui.QPainterPath()
        arc.moveTo(radius * math.cos(ang_l), radius * math.sin(ang_l))
        for i in range(1, 33):
            a_deg = yaw_deg - fov_h_deg / 2.0 + i * (fov_h_deg / 32.0)
            ax = radius * math.cos(math.radians(a_deg))
            ay = radius * math.sin(math.radians(a_deg))
            arc.lineTo(ax, ay)
        self.world_fov_arc.setPath(arc)

        in_fov = bool(snapshot.camera["in_fov"])
        msg = (
            f"yaw={yaw_deg:.2f}°  目标方位={bearing_deg:.2f}°  "
            f"角度误差={angle_err:.2f}°  {'在视野内' if in_fov else '视野外'}"
        )
        self.world_title.setText(msg)
        self.world_title.setBrush(QtGui.QBrush(QtGui.QColor(COLOR["ok"] if in_fov else COLOR["warn"])))
        scene_rect = self.world_view.sceneRect()
        self.world_title.setPos(scene_rect.left() + 6.0, scene_rect.top() + 6.0)

        lim = max(50.0, abs(x_m) + 12.0, abs(y_m) + 12.0, line_len * 0.9)
        self.world_view.ensure_range(lim)

    def _draw_timeline(self, t_list: list[float], err_list: list[float], rate_list: list[float], angle_err_list: list[float]) -> None:
        if pg is None or not isinstance(self.timeline_plot, pg.PlotWidget):
            return
        if not t_list:
            return

        t_np = np.asarray(t_list, dtype=float)
        err_np = np.asarray(err_list, dtype=float)
        rate_np = np.asarray(rate_list, dtype=float)
        angle_np = np.asarray(angle_err_list, dtype=float)

        t_max = float(t_np[-1])
        t_min = max(0.0, t_max - 15.0)
        mask = (t_np >= t_min) & (t_np <= t_max)
        t_np = t_np[mask]
        err_np = err_np[mask]
        rate_np = rate_np[mask]
        angle_np = angle_np[mask]
        if len(t_np) == 0:
            return

        valid_err = np.isfinite(err_np)
        valid_rate = np.isfinite(rate_np)
        valid_angle = np.isfinite(angle_np)

        t_err, y_err = self._decimate_xy(t_np[valid_err], err_np[valid_err])
        t_rate, y_rate = self._decimate_xy(t_np[valid_rate], rate_np[valid_rate])
        t_angle, y_angle = self._decimate_xy(t_np[valid_angle], angle_np[valid_angle])

        self.curve_err.setData(t_err, y_err)
        self.curve_rate.setData(t_rate, y_rate)
        self.curve_angle.setData(t_angle, y_angle)

        all_y = np.concatenate([arr for arr in (y_err, y_rate, y_angle) if len(arr) > 0])
        if len(all_y) > 0:
            y_min = float(np.min(all_y))
            y_max = float(np.max(all_y))
            pad = max(5.0, 0.12 * max(1.0, y_max - y_min))
            self.timeline_plot.setXRange(t_min, t_max + 0.01, padding=0.0)
            self.timeline_plot.setYRange(y_min - pad, y_max + pad, padding=0.0)

    @staticmethod
    def _camera_info_text(frame: Optional[FrameSample], u_px: float, v_px: float, in_fov: bool) -> tuple[str, bool]:
        if frame is None:
            return "无帧", False
        w = int(frame.image.shape[1])
        h = int(frame.image.shape[0])
        cx = float(frame.intrinsics.get("cx", w * 0.5))
        cy = float(frame.intrinsics.get("cy", h * 0.5))
        du = u_px - cx if math.isfinite(u_px) else float("nan")
        dv = v_px - cy if math.isfinite(v_px) else float("nan")
        text = (
            f"{w}x{h}px  |  cx={cx:.1f}, cy={cy:.1f}  |  "
            f"u={u_px:.1f}, v={v_px:.1f}  |  du={du:.1f}, dv={dv:.1f}  |  "
            f"{'在视野内' if in_fov else '视野外'}"
        )
        return text, in_fov

    def _update_core_tab(self, snapshot: Any, raw_frame: Optional[FrameSample]) -> None:
        g = snapshot.gimbal
        c = snapshot.camera
        r = snapshot.raspi
        x_m = float(snapshot.target["x_m"])
        y_m = float(snapshot.target["y_m"])
        bearing_deg = math.degrees(math.atan2(y_m, x_m))
        angle_err = wrap_pm180(bearing_deg - float(g["yaw_deg_internal"]))
        cx = float(raw_frame.intrinsics.get("cx", float("nan"))) if raw_frame else float("nan")
        cy = float(raw_frame.intrinsics.get("cy", float("nan"))) if raw_frame else float("nan")
        u_px = float(c["u_px"])
        v_px = float(c["v_px"])
        du = (u_px - cx) if math.isfinite(u_px) and math.isfinite(cx) else float("nan")
        dv = (v_px - cy) if math.isfinite(v_px) and math.isfinite(cy) else float("nan")

        values = {
            "t": f"{snapshot.timestamp:.3f} s",
            "mode": str(g["mode"]),
            "yaw": f"{float(g['yaw_deg_display']):.2f}°",
            "pitch": f"{float(g['pitch_deg']):.2f}°",
            "yaw_rate": f"{float(g['yaw_rate_dps']):.2f} dps",
            "angle_err": f"{angle_err:.2f}°",
            "u": f"{u_px:.1f}",
            "v": f"{v_px:.1f}",
            "du": f"{du:.1f}",
            "dv": f"{dv:.1f}",
            "in_fov": "是" if bool(c["in_fov"]) else "否",
            "backlog": str(r["pipeline_backlog_len"]),
            "obs_lag": f"{float(r['last_process_latency_s']) * 1000.0:.2f} ms",
        }
        for key, text in values.items():
            self.core_value_labels[key].setText(text)
        self.core_value_labels["in_fov"].setStyleSheet(
            f"color: {COLOR['ok' if bool(c['in_fov']) else 'warn']}; font-weight: 700;"
        )

    def _update_diag_tab(self, snapshot: Any, raw_frame: Optional[FrameSample], raspi_frame: Optional[FrameSample]) -> None:
        g = snapshot.gimbal
        c = snapshot.camera
        r = snapshot.raspi
        t = snapshot.target
        raw_ts = float("nan") if raw_frame is None else raw_frame.timestamp
        raspi_ts = float("nan") if raspi_frame is None else raspi_frame.timestamp

        gimbal_items: list[tuple[str, str]] = [
            ("mode", str(g["mode"])),
            ("yaw_internal", f"{g['yaw_deg_internal']:.4f}"),
            ("yaw_display", f"{g['yaw_deg_display']:.4f}"),
            ("pitch_deg", f"{g['pitch_deg']:.4f}"),
            ("yaw_rate_dps", f"{g['yaw_rate_dps']:.4f}"),
            ("yaw_rate_ref", f"{g.get('yaw_rate_ref_dps', 0.0):.4f}"),
            ("power_state", str(g.get("power_state", ""))),
        ]
        camera_items: list[tuple[str, str]] = [
            ("f_current_mm", f"{c['f_current_mm']:.4f}"),
            ("frame_id", f"{c['frame_id']}"),
            ("u_px", f"{c['u_px']:.4f}"),
            ("v_px", f"{c['v_px']:.4f}"),
            ("in_fov", f"{int(bool(c['in_fov']))}"),
            ("raw_frame_ts", f"{raw_ts:.4f}"),
            ("raspi_frame_ts", f"{raspi_ts:.4f}"),
        ]
        raspi_items: list[tuple[str, str]] = [
            ("effective_obs_ts", f"{float(r.get('effective_obs_timestamp', float('nan'))):.4f}"),
            ("pipeline_backlog", f"{r['pipeline_backlog_len']}"),
            ("proc_latency_s", f"{float(r['last_process_latency_s']):.6f}"),
            ("cmd_apply_ts", f"{float(r.get('last_command_apply_timestamp', float('nan'))):.4f}"),
            ("power_state", str(r.get("power_state", ""))),
        ]
        target_items: list[tuple[str, str]] = [
            ("timestamp", f"{snapshot.timestamp:.4f}"),
            ("x_m", f"{float(t.get('x_m', float('nan'))):.4f}"),
            ("y_m", f"{float(t.get('y_m', float('nan'))):.4f}"),
            ("z_m", f"{float(t.get('z_m', float('nan'))):.4f}"),
            ("vx_mps", f"{float(t.get('vx_mps', float('nan'))):.4f}"),
            ("vy_mps", f"{float(t.get('vy_mps', float('nan'))):.4f}"),
            ("vz_mps", f"{float(t.get('vz_mps', float('nan'))):.4f}"),
        ]
        self._fill_diag_table(self.diag_entity_tables["gimbal"], gimbal_items)
        self._fill_diag_table(self.diag_entity_tables["camera"], camera_items)
        self._fill_diag_table(self.diag_entity_tables["raspi"], raspi_items)
        self._fill_diag_table(self.diag_entity_tables["target"], target_items)

    def _fill_diag_table(self, table: QtWidgets.QTableWidget, items: list[tuple[str, str]]) -> None:
        """将诊断键值对填充为 4 列（2 组字段-值）的表格。"""
        group_size = 2
        row_count = (len(items) + group_size - 1) // group_size
        table.setRowCount(row_count)
        table.setColumnCount(4)

        for row in range(row_count):
            for cidx in range(4):
                cell = QtWidgets.QTableWidgetItem("")
                cell.setTextAlignment(QtCore.Qt.AlignCenter)
                table.setItem(row, cidx, cell)

        for idx, (key, value) in enumerate(items):
            row = idx // group_size
            slot = idx % group_size
            key_col = slot * 2
            val_col = key_col + 1

            key_item = QtWidgets.QTableWidgetItem(key)
            key_item.setTextAlignment(QtCore.Qt.AlignCenter)
            key_item.setForeground(QtGui.QBrush(QtGui.QColor(COLOR["text_sub"])))
            key_item.setFont(QtGui.QFont("Microsoft YaHei UI", 9, QtGui.QFont.DemiBold))
            val_item = QtWidgets.QTableWidgetItem(value)
            val_item.setTextAlignment(QtCore.Qt.AlignCenter)
            val_item.setForeground(QtGui.QBrush(QtGui.QColor(COLOR["text_main"])))
            val_item.setFont(QtGui.QFont("Microsoft YaHei UI", 9, QtGui.QFont.Bold))
            table.setItem(row, key_col, key_item)
            table.setItem(row, val_col, val_item)

    def _update_fps_label(self) -> None:
        self._ui_tick_counter += 1
        now = time.perf_counter()
        elapsed = now - self._last_ui_perf
        if elapsed >= 1.0:
            self._fps_value = self._ui_tick_counter / elapsed
            self._ui_tick_counter = 0
            self._last_ui_perf = now
            self.lbl_fps.setText(f"{UI_TEXT['fps']}: {self._fps_value:.1f}")

    def _render_tick(self) -> None:
        snapshot, raw_frame = self.state_buf.read_latest()
        if snapshot is None:
            self._update_fps_label()
            return

        t_list, x_hist, y_hist, err_list, rate_list, angle_err_list = self.state_buf.read_curves()
        self._draw_world(snapshot, x_hist, y_hist)
        self._draw_timeline(t_list, err_list, rate_list, angle_err_list)

        u_px = float(snapshot.camera["u_px"])
        v_px = float(snapshot.camera["v_px"])
        in_fov = bool(snapshot.camera["in_fov"])

        self.raw_panel.view.update_frame(raw_frame)
        raw_info, raw_ok = self._camera_info_text(raw_frame, u_px, v_px, in_fov)
        self.raw_panel.set_info_text(raw_info, raw_ok)

        raspi_obs_ts = float(snapshot.raspi.get("effective_obs_timestamp", float("nan")))
        raspi_frame = None if not math.isfinite(raspi_obs_ts) else self.state_buf.find_frame_at_or_before(raspi_obs_ts)
        self.raspi_panel.view.update_frame(raspi_frame)
        raspi_info, raspi_ok = self._camera_info_text(raspi_frame, u_px, v_px, in_fov)
        self.raspi_panel.set_info_text(raspi_info, raspi_ok)

        self._update_core_tab(snapshot, raw_frame)
        self._update_diag_tab(snapshot, raw_frame, raspi_frame)
        self._update_fps_label()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.ui_timer.stop()
        self.worker.stop()
        self.worker.wait(2000)
        self._settings.setValue("main_splitter_sizes", self.main_splitter.sizes())
        super().closeEvent(event)
