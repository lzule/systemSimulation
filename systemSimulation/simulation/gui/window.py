"""主仪表盘窗口实现。"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Optional

import numpy as np

from config import gimbal_cfg, raspi_delay_cfg, scene_cfg
from simulation.bootstrap import build_runtime, load_control_program_from_path
from simulation.headless import apply_target_overrides
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
        self.scene_cfg = scene_cfg
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
        self._algo_key_override: str = ""
        apply_target_overrides(self.cfg)
        self.runtime = build_runtime(self.cfg.delay_ms, control_program=cp, obs_mode=self.cfg.obs_mode)
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
        root_layout.setSpacing(4)

        # ── 顶部状态摘要条 ──
        summary_bar = QtWidgets.QFrame()
        summary_bar.setStyleSheet(
            f"background: {COLOR['panel']}; border: 1px solid {COLOR['border']}; "
            "border-radius: 6px; padding: 4px 10px;"
        )
        summary_layout = QtWidgets.QHBoxLayout(summary_bar)
        summary_layout.setContentsMargins(10, 4, 10, 4)
        summary_layout.setSpacing(16)

        self.summary_labels: dict[str, QtWidgets.QLabel] = {}
        for key, default in [
            ("state", "已暂停"), ("t", "0.00s"), ("distance", "距离: --"),
            ("atp_state", "--"),
            ("control_program", "--"), ("obs_mode", str(self.cfg.obs_mode)),
            ("target_type", str(self.cfg.target_type) if self.cfg.target_type else self._get_target_motion_type()),
            ("delay", f"{self.cfg.delay_ms:.0f}ms"), ("backlog", "0"),
        ]:
            lbl = QtWidgets.QLabel(default)
            lbl.setStyleSheet(f"color: {COLOR['text_main']}; font-weight: 600; font-size: 10pt;")
            summary_layout.addWidget(lbl)
            self.summary_labels[key] = lbl
        summary_layout.addStretch(1)
        self.lbl_fps_summary = QtWidgets.QLabel(f"FPS: 0.0")
        self.lbl_fps_summary.setStyleSheet(f"color: {COLOR['text_sub']}; font-size: 9pt;")
        summary_layout.addWidget(self.lbl_fps_summary)
        root_layout.addWidget(summary_bar)

        # ── 顶部操作条 ──
        toolbar_box = QtWidgets.QFrame()
        toolbar_box.setStyleSheet(
            f"background: {COLOR['panel']}; border: 1px solid {COLOR['border']}; border-radius: 6px;"
        )
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar_box)
        toolbar_layout.setContentsMargins(8, 4, 8, 4)
        toolbar_layout.setSpacing(6)

        self.btn_start = QtWidgets.QPushButton(UI_TEXT["start"])
        self.btn_pause = QtWidgets.QPushButton(UI_TEXT["pause"])
        self.btn_reset = QtWidgets.QPushButton(UI_TEXT["reset"])
        self.btn_save = QtWidgets.QPushButton(UI_TEXT["save"])

        # 延时微调（仅数值，无"应用"按钮）
        self.delay_label = QtWidgets.QLabel(UI_TEXT["delay_label"])
        self.delay_spin = QtWidgets.QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 500.0)
        self.delay_spin.setSingleStep(5.0)
        self.delay_spin.setDecimals(1)
        self.delay_spin.setValue(self.cfg.delay_ms)

        self.lbl_runtime_state = QtWidgets.QLabel(UI_TEXT["paused"])
        self.lbl_runtime_state.setStyleSheet(f"color: {COLOR['warn']}; font-weight: 700; font-size: 9pt;")

        for w in (self.btn_start, self.btn_pause, self.btn_reset, self.btn_save,
                  self.delay_label, self.delay_spin):
            toolbar_layout.addWidget(w)

        # ── 算法 / 观测模式 / 目标运动 下拉选择器 ──
        combo_style = "min-width: 140px; padding: 2px 6px;"

        toolbar_layout.addWidget(QtWidgets.QLabel("算法:"))
        self.combo_algorithm = QtWidgets.QComboBox()
        self.combo_algorithm.setStyleSheet(combo_style)
        _algo_keys = [
            "baseline_rate_p", "rate_pi", "alpha_beta_tracker",
            "linear_kf_tracker", "atp_search_track_baseline", "angle_mode_realistic",
        ]
        for k in _algo_keys:
            self.combo_algorithm.addItem(k, k)
        toolbar_layout.addWidget(self.combo_algorithm)

        toolbar_layout.addWidget(QtWidgets.QLabel("观测模式:"))
        self.combo_obs_mode = QtWidgets.QComboBox()
        self.combo_obs_mode.setStyleSheet(combo_style)
        for m in ("debug", "research", "realistic"):
            self.combo_obs_mode.addItem(m, m)
        idx = self.combo_obs_mode.findData(self.cfg.obs_mode or "debug")
        if idx >= 0:
            self.combo_obs_mode.setCurrentIndex(idx)
        toolbar_layout.addWidget(self.combo_obs_mode)

        toolbar_layout.addWidget(QtWidgets.QLabel("目标运动:"))
        self.combo_target_type = QtWidgets.QComboBox()
        self.combo_target_type.setStyleSheet(combo_style)
        for m in ("sinusoidal", "constant_velocity", "constant_accel", "random_walk", "waypoint"):
            self.combo_target_type.addItem(m, m)
        cur_type = self.cfg.target_type or self._get_target_motion_type()
        idx2 = self.combo_target_type.findData(cur_type)
        if idx2 >= 0:
            self.combo_target_type.setCurrentIndex(idx2)
        toolbar_layout.addWidget(self.combo_target_type)

        self.combo_algorithm.currentIndexChanged.connect(self._on_combo_changed)
        self.combo_obs_mode.currentIndexChanged.connect(self._on_combo_changed)
        self.combo_target_type.currentIndexChanged.connect(self._on_combo_changed)

        # 延时链路信息（τ 标签说明一阶惯性）
        read_ms = raspi_delay_cfg.image_read_delay_s * 1000
        proc_ms = raspi_delay_cfg.image_process_delay_s * 1000
        send_ms = raspi_delay_cfg.command_tx_delay_s * 1000
        tau_ms = gimbal_cfg.response_tau_s * 1000
        self.lbl_delay_chain = QtWidgets.QLabel(
            f"  链路延时: 读取{read_ms:.0f}ms → 处理{proc_ms:.0f}ms → 发送{send_ms:.0f}ms"
            f" │ 云台响应τ: {tau_ms:.0f}ms（一阶惯性，非通信延时）│ 观测延迟: --ms"
        )
        self.lbl_delay_chain.setStyleSheet("color: #666; font-size: 9pt;")
        toolbar_layout.addWidget(self.lbl_delay_chain)

        toolbar_layout.addStretch(1)
        self.lbl_fps = QtWidgets.QLabel(f"{UI_TEXT['fps']}: 0.0")
        self.lbl_fps.setStyleSheet(f"color: {COLOR['text_sub']}; font-size: 9pt;")
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

        timeline_box = QtWidgets.QGroupBox("底部时间轴（误差 / 角速度）")
        timeline_layout = QtWidgets.QVBoxLayout(timeline_box)
        timeline_layout.setContentsMargins(8, 8, 8, 8)
        if pg is not None:
            self.timeline_container = QtWidgets.QWidget()
            tl_vbox = QtWidgets.QVBoxLayout(self.timeline_container)
            tl_vbox.setContentsMargins(0, 0, 0, 0)
            tl_vbox.setSpacing(2)
            self.timeline_container_layout = tl_vbox
            timeline_layout.addWidget(self.timeline_container)
        else:
            self.timeline_container = None
            timeline_layout.addWidget(QtWidgets.QLabel("pyqtgraph 未安装，无法显示曲线"))
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
        right_layout.addWidget(camera_row_box, 5)

        self._build_cards(right_layout)
        self._build_diag_section(right_layout)

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

    def _build_cards(self, parent_layout: QtWidgets.QVBoxLayout) -> None:
        cards_bar = QtWidgets.QFrame()
        cards_bar.setFixedHeight(50)
        cards_bar.setStyleSheet(
            f"background: {COLOR['panel']}; border: 1px solid {COLOR['border']}; border-radius: 6px;"
        )
        bar_layout = QtWidgets.QHBoxLayout(cards_bar)
        bar_layout.setContentsMargins(10, 4, 10, 4)
        bar_layout.setSpacing(12)

        label_style = f"color: {COLOR['text_sub']}; font-size: 8pt;"
        value_style = f"color: {COLOR['text_main']}; font-size: 12pt; font-weight: 700;"

        cards = [
            ("像素误差", "err"), ("角度误差", "angle_err"), ("距离", "distance"),
        ]
        self.card_value_labels: dict[str, QtWidgets.QLabel] = {}

        for title, key in cards:
            cell = QtWidgets.QWidget()
            vbox = QtWidgets.QVBoxLayout(cell)
            vbox.setContentsMargins(4, 0, 4, 0)
            vbox.setSpacing(0)
            lbl = QtWidgets.QLabel(title)
            lbl.setStyleSheet(label_style)
            val = QtWidgets.QLabel("--")
            val.setStyleSheet(value_style)
            val.setAlignment(QtCore.Qt.AlignCenter)
            vbox.addWidget(lbl, alignment=QtCore.Qt.AlignCenter)
            vbox.addWidget(val, alignment=QtCore.Qt.AlignCenter)
            bar_layout.addWidget(cell, 1)
            self.card_value_labels[key] = val

        parent_layout.addWidget(cards_bar)

    def _build_diag_section(self, parent_layout: QtWidgets.QVBoxLayout) -> None:
        diag_box = QtWidgets.QGroupBox("诊断信息")
        layout = QtWidgets.QVBoxLayout(diag_box)
        layout.setContentsMargins(8, 8, 8, 8)

        self.diag_tree = QtWidgets.QTreeWidget()
        self.diag_tree.setColumnCount(2)
        self.diag_tree.setHeaderLabels(["字段", "值"])
        self.diag_tree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.diag_tree.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.diag_tree.setFocusPolicy(QtCore.Qt.NoFocus)
        self.diag_tree.setAlternatingRowColors(True)
        self.diag_tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.diag_tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.diag_tree.setStyleSheet(
            """
            QTreeWidget {
                background: #ffffff;
                border: 1px solid #d6dce7;
                border-radius: 6px;
            }
            QTreeWidget::item { padding: 2px 4px; }
            QHeaderView::section {
                background: #f0f4fb;
                font-weight: 700;
                border: 1px solid #d6dce7;
                padding: 4px;
                color: #1f2a44;
            }
            """
        )

        # 4 个顶级节点
        self.diag_top_items: dict[str, QtWidgets.QTreeWidgetItem] = {}
        for key, title in (("gimbal", "云台"), ("camera", "相机"), ("raspi", "树莓派"), ("target", "目标")):
            top = QtWidgets.QTreeWidgetItem(self.diag_tree, [title, ""])
            top.setFont(0, QtGui.QFont("Microsoft YaHei UI", 9, QtGui.QFont.Bold))
            top.setForeground(0, QtGui.QBrush(QtGui.QColor(COLOR["text_main"])))
            top.setExpanded(True)
            self.diag_top_items[key] = top

        layout.addWidget(self.diag_tree)
        parent_layout.addWidget(diag_box, 6)

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
        if pg is None or self.timeline_container is None:
            return

        vbox = self.timeline_container_layout

        # GraphicsLayoutWidget：共享 X 轴的多行布局
        self.timeline_gw = pg.GraphicsLayoutWidget()
        self.timeline_gw.setBackground("#ffffff")  # 整体白色背景

        # ── 上图：像素误差(px) 左轴 + 角度误差(deg) 右轴 ──
        self.plot_err = self.timeline_gw.addPlot(row=0, col=0)
        self.plot_err.vb.setBackgroundColor("#f5f6f8")
        self.plot_err.showGrid(x=True, y=True, alpha=0.24)
        self.plot_err.setLabel("left", "像素误差", units="px")
        self.plot_err.getAxis("left").setStyle(tickTextOffset=10)
        # 隐藏上图 X 轴所有元素，只保留占位空间（与下图对齐）
        self.plot_err.getAxis("bottom").setStyle(showValues=False)
        self.plot_err.getAxis("bottom").setHeight(40)  # 预留与下图 X 轴标签等高的空间
        self.plot_err.addLegend(offset=(8, 8))

        self.curve_err = self.plot_err.plot(
            [], [], pen=pg.mkPen(COLOR["err"], width=2), name="pixel_error (px)"
        )

        # 右 Y 轴：角度误差
        self.plot_err.showAxis("right")
        self.plot_err.getAxis("right").setStyle(tickTextOffset=10)
        self.plot_err.getAxis("right").setLabel("角度误差", units="deg")
        self.plot_err_vb_right = pg.ViewBox()
        self.plot_err.scene().addItem(self.plot_err_vb_right)
        self.plot_err.getAxis("right").linkToView(self.plot_err_vb_right)
        self.plot_err_vb_right.setXLink(self.plot_err)

        self.curve_angle = pg.PlotCurveItem(
            [], [], pen=pg.mkPen(COLOR["angle"], width=2)
        )
        self.plot_err_vb_right.addItem(self.curve_angle)
        self.plot_err.legend.addItem(self.curve_angle, "angle_err (deg)")

        def _update_err_right_axis() -> None:
            self.plot_err_vb_right.setGeometry(self.plot_err.vb.sceneBoundingRect())
            self.plot_err_vb_right.linkedViewChanged(self.plot_err.vb, self.plot_err_vb_right.XAxis)

        self._update_err_right_axis = _update_err_right_axis
        _update_err_right_axis()
        self.plot_err.vb.sigResized.connect(_update_err_right_axis)

        # ── 下图：角速度(dps) ──
        self.plot_rate = self.timeline_gw.addPlot(row=1, col=0)
        self.plot_rate.vb.setBackgroundColor("#ffffff")
        self.plot_rate.showGrid(x=True, y=True, alpha=0.24)
        self.plot_rate.setLabel("left", "角速度", units="dps")
        self.plot_rate.setLabel("bottom", "t", units="s")
        self.plot_rate.getAxis("left").setStyle(tickTextOffset=10)
        self.plot_rate.getAxis("bottom").setStyle(tickTextOffset=8)
        self.plot_rate.addLegend(offset=(8, 8))

        # 下图也显示右轴（空），确保绘图区与上图等宽
        self.plot_rate.showAxis("right")
        self.plot_rate.getAxis("right").setStyle(showValues=False)

        self.curve_rate = self.plot_rate.plot(
            [], [], pen=pg.mkPen(COLOR["rate"], width=2), name="yaw_rate_ref (dps)"
        )

        # X 轴联动
        self.plot_rate.setXLink(self.plot_err)

        # ATP 状态背景色区域列表（叠加在 plot_rate 上）
        self.atp_regions: list = []
        self._last_atp_state_drawn: str = ""

        # 当前 ATP 状态标签（显示在时间轴 GroupBox 标题旁）
        self.lbl_current_atp = QtWidgets.QLabel("ATP: --")
        self.lbl_current_atp.setStyleSheet(f"color: {COLOR['text_sub']}; font-size: 9pt; font-weight: 700;")
        vbox.addWidget(self.lbl_current_atp)

        vbox.addWidget(self.timeline_gw)

    def _set_runtime_state(self, text: str, running: bool) -> None:
        self.lbl_runtime_state.setText(text)
        self.lbl_runtime_state.setStyleSheet(f"color: {COLOR['ok' if running else 'warn']}; font-weight: 700; font-size: 9pt;")
        self.summary_labels["state"].setText(text)
        self.summary_labels["state"].setStyleSheet(
            f"color: {COLOR['ok' if running else 'warn']}; font-weight: 700; font-size: 10pt;"
        )

    def _get_target_motion_type(self) -> str:
        from config import target_cfg
        return getattr(target_cfg, "motion_type", "sinusoidal")

    def _on_start(self) -> None:
        self.worker.set_paused(False)
        self._set_runtime_state(UI_TEXT["running"], True)
        self.statusBar().showMessage(UI_TEXT["running"], 1200)

    def _on_pause(self) -> None:
        self.worker.set_paused(True)
        self._set_runtime_state(UI_TEXT["paused"], False)
        self.statusBar().showMessage(UI_TEXT["paused"], 1200)

    def _build_control_program(self):
        """根据下拉选择或 cfg 路径构建控制程序实例。"""
        if self._algo_key_override:
            from tools.run_benchmark import ALGORITHM_REGISTRY
            factory = ALGORITHM_REGISTRY.get(self._algo_key_override)
            if factory is not None:
                return factory()
        if self.cfg.control_program_path:
            return load_control_program_from_path(self.cfg.control_program_path)
        return None

    def _on_reset(self) -> None:
        self.worker.set_paused(True)
        self.worker.stop()
        self.worker.wait(2000)

        cp = self._build_control_program()
        apply_target_overrides(self.cfg)
        self.runtime = build_runtime(float(self.delay_spin.value()), control_program=cp, obs_mode=self.cfg.obs_mode)
        self.state_buf.clear()
        self.worker = SimWorker(self.runtime, self.state_buf, mode=self.cfg.mode, duration_s=self.cfg.duration_s, sim_hz=200.0)
        self.worker.error_signal.connect(self._on_worker_error)
        self.worker.finished_signal.connect(self._on_worker_finished)
        self.worker.start()
        if self.cfg.mode == "realtime":
            self._on_start()
        self.statusBar().showMessage(UI_TEXT["reset_done"], 1500)

    def _on_save(self) -> None:
        import json
        ts = int(time.time())
        out_dir = os.path.join("output", f"ui_export_{ts}")
        os.makedirs(out_dir, exist_ok=True)

        # 截图
        png_path = os.path.join(out_dir, "dashboard.png")
        self.grab().save(png_path)

        # 运行摘要
        snap, frame = self.state_buf.read_latest()
        summary = {
            "timestamp": ts,
            "control_program": self.cfg.control_program_path or "BaselineTrackerProgram",
            "obs_mode": self.cfg.obs_mode,
            "target_type": self.cfg.target_type or self._get_target_motion_type(),
            "delay_ms": float(self.delay_spin.value()),
        }
        if snap is not None:
            summary["sim_time"] = snap.timestamp
            summary["atp_state"] = str(snap.raspi.get("atp_state", ""))
            summary["in_fov"] = bool(snap.camera.get("in_fov", False))
            summary["backlog"] = snap.raspi.get("pipeline_backlog_len", 0)

        json_path = os.path.join(out_dir, "summary.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        self.statusBar().showMessage(f"已导出: {out_dir}/", 3000)

    def _on_combo_changed(self) -> None:
        """算法/观测模式/目标运动下拉切换时立即重置仿真。"""
        self.cfg.obs_mode = self.combo_obs_mode.currentData()
        self.cfg.target_type = self.combo_target_type.currentData()
        self._algo_key_override = self.combo_algorithm.currentData()
        self._on_reset()
        self.statusBar().showMessage(
            f"已切换: 算法={self._algo_key_override}  观测={self.cfg.obs_mode}  目标={self.cfg.target_type}", 2000
        )

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
        self._export_session_results()

    def _export_session_results(self) -> None:
        import csv
        import json as _json
        ts = int(time.time())
        out_dir = os.path.join("output", f"session_{ts}")
        os.makedirs(out_dir, exist_ok=True)

        # 1. 窗口截图
        self.grab().save(os.path.join(out_dir, "dashboard.png"))

        # 2. 运行摘要
        snap, _ = self.state_buf.read_latest()
        metrics_log, event_log = self.state_buf.read_logs()
        summary = {
            "timestamp": ts,
            "control_program": self._algo_key_override or self.cfg.control_program_path or "BaselineTrackerProgram",
            "obs_mode": self.cfg.obs_mode,
            "target_type": self.cfg.target_type or self._get_target_motion_type(),
            "delay_ms": float(self.delay_spin.value()),
            "total_frames": len(metrics_log),
            "atp_events": len(event_log),
        }
        if snap is not None:
            summary["sim_time"] = snap.timestamp
            summary["atp_state"] = str(snap.raspi.get("atp_state", ""))
            summary["in_fov"] = bool(snap.camera.get("in_fov", False))
        with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
            _json.dump(summary, f, indent=2, ensure_ascii=False)

        # 3. 每帧指标 CSV
        if metrics_log:
            keys = list(metrics_log[0].keys())
            with open(os.path.join(out_dir, "metrics.csv"), "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(metrics_log)

        # 4. ATP 状态变迁事件
        with open(os.path.join(out_dir, "event_log.json"), "w", encoding="utf-8") as f:
            _json.dump(event_log, f, indent=2, ensure_ascii=False)

        # 5. 场景配置快照
        from config import (camera_cfg, gimbal_cfg as gcfg, target_cfg,
                            raspi_delay_cfg as rdcfg, obs_cfg)
        import dataclasses
        scene_config = {
            "camera": dataclasses.asdict(camera_cfg),
            "gimbal": dataclasses.asdict(gcfg),
            "target": {k: v for k, v in dataclasses.asdict(target_cfg).items() if k != "waypoints"},
            "raspi_delay": dataclasses.asdict(rdcfg),
            "obs": dataclasses.asdict(obs_cfg),
        }
        with open(os.path.join(out_dir, "scene_config.json"), "w", encoding="utf-8") as f:
            _json.dump(scene_config, f, indent=2, ensure_ascii=False)

        self.statusBar().showMessage(f"已自动保存: {out_dir}/", 4000)

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
        z_m = float(snapshot.target.get("z_m", 0.0))
        yaw_deg = float(snapshot.gimbal["yaw_deg_display"])
        yaw_rad = math.radians(yaw_deg)
        bearing_deg = math.degrees(math.atan2(y_m, x_m))
        angle_err = wrap_pm180(bearing_deg - float(snapshot.gimbal["yaw_deg_internal"]))

        path = QtGui.QPainterPath()
        path.moveTo(x_hist[0], y_hist[0])
        for x, y in zip(x_hist[1:], y_hist[1:]):
            path.lineTo(x, y)
        self.world_traj_item.setPath(path)

        # z 编码：颜色（z>0 偏蓝，z<0 偏黄，z=0 红）和尺寸
        z_clamp = max(-30.0, min(30.0, z_m))
        if z_clamp >= 0:
            t = z_clamp / 30.0
            r = int(231 * (1 - t) + 52 * t)
            g = int(76 * (1 - t) + 152 * t)
            b = int(60 * (1 - t) + 219 * t)
        else:
            t = (-z_clamp) / 30.0
            r = int(231 * (1 - t) + 241 * t)
            g = int(76 * (1 - t) + 196 * t)
            b = int(60 * (1 - t) + 15 * t)
        target_color = QtGui.QColor(r, g, b)
        radius = 2.8 + z_clamp * 0.05  # z 越高越大
        radius = max(1.5, min(5.0, radius))
        self.world_target_item.setRect(-radius, -radius, 2 * radius, 2 * radius)
        self.world_target_item.setPen(QtGui.QPen(target_color, 1.2))
        self.world_target_item.setBrush(QtGui.QBrush(target_color))
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
        radius_fov = line_len * 0.75
        self.world_fov_left.setLine(0.0, 0.0, radius_fov * math.cos(ang_l), radius_fov * math.sin(ang_l))
        self.world_fov_right.setLine(0.0, 0.0, radius_fov * math.cos(ang_r), radius_fov * math.sin(ang_r))

        arc = QtGui.QPainterPath()
        arc.moveTo(radius_fov * math.cos(ang_l), radius_fov * math.sin(ang_l))
        for i in range(1, 33):
            a_deg = yaw_deg - fov_h_deg / 2.0 + i * (fov_h_deg / 32.0)
            ax = radius_fov * math.cos(math.radians(a_deg))
            ay = radius_fov * math.sin(math.radians(a_deg))
            arc.lineTo(ax, ay)
        self.world_fov_arc.setPath(arc)

        in_fov = bool(snapshot.camera["in_fov"])
        msg = (
            f"yaw={yaw_deg:.2f}°  目标方位={bearing_deg:.2f}°  "
            f"角度误差={angle_err:.2f}°  z={z_m:.1f}m  {'在视野内' if in_fov else '视野外'}"
            f"  [俯视图 - z编码: 高=蓝，低=黄]"
        )
        self.world_title.setText(msg)
        self.world_title.setBrush(QtGui.QBrush(QtGui.QColor(COLOR["ok"] if in_fov else COLOR["warn"])))
        scene_rect = self.world_view.sceneRect()
        self.world_title.setPos(scene_rect.left() + 6.0, scene_rect.top() + 6.0)

        lim = max(50.0, abs(x_m) + 12.0, abs(y_m) + 12.0, line_len * 0.9)
        self.world_view.ensure_range(lim)

    def _draw_timeline(self, t_list: list[float], err_list: list[float], rate_list: list[float], angle_err_list: list[float], atp_state_list: list[str]) -> None:
        if pg is None or self.timeline_container is None:
            return
        if not t_list:
            return

        t_np = np.asarray(t_list, dtype=float)
        err_np = np.asarray(err_list, dtype=float)
        rate_np = np.asarray(rate_list, dtype=float)
        angle_np = np.asarray(angle_err_list, dtype=float)

        t_max = float(t_np[-1])
        t_min = max(0.0, t_max - self.scene_cfg.plot_window_s)
        mask = (t_np >= t_min) & (t_np <= t_max)
        t_np = t_np[mask]
        err_np = err_np[mask]
        rate_np = rate_np[mask]
        angle_np = angle_np[mask]
        atp_windowed = [atp_state_list[i] for i in range(len(mask)) if mask[i]]
        if len(t_np) == 0:
            return

        valid_err = np.isfinite(err_np)
        valid_rate = np.isfinite(rate_np)
        valid_angle = np.isfinite(angle_np)

        # ── 上图：像素误差(左轴) + 角度误差(右轴) ──
        t_err, y_err = self._decimate_xy(t_np[valid_err], err_np[valid_err])
        t_angle, y_angle = self._decimate_xy(t_np[valid_angle], angle_np[valid_angle])
        self.curve_err.setData(t_err, y_err)
        self.curve_angle.setData(t_angle, y_angle)

        # 左轴范围（像素误差）
        if len(y_err) > 0:
            e_min, e_max = float(np.min(y_err)), float(np.max(y_err))
            e_pad = max(5.0, 0.12 * max(1.0, e_max - e_min))
            self.plot_err.vb.setYRange(e_min - e_pad, e_max + e_pad, padding=0.0)
        # 右轴范围（角度误差）
        if len(y_angle) > 0:
            a_min, a_max = float(np.min(y_angle)), float(np.max(y_angle))
            a_pad = max(1.0, 0.12 * max(1.0, a_max - a_min))
            self.plot_err_vb_right.setYRange(a_min - a_pad, a_max + a_pad, padding=0.0)

        self.plot_err.vb.setXRange(t_min, t_max + 0.01, padding=0.0)

        # ── 下图：角速度 ──
        t_rate, y_rate = self._decimate_xy(t_np[valid_rate], rate_np[valid_rate])
        self.curve_rate.setData(t_rate, y_rate)
        if len(y_rate) > 0:
            r_min, r_max = float(np.min(y_rate)), float(np.max(y_rate))
            r_pad = max(3.0, 0.12 * max(1.0, r_max - r_min))
            self.plot_rate.vb.setYRange(r_min - r_pad, r_max + r_pad, padding=0.0)
        self.plot_rate.vb.setXRange(t_min, t_max + 0.01, padding=0.0)

        # ── ATP 状态背景色（LinearRegionItem 叠加在 plot_rate 上）──
        atp_colors = {
            "SEARCH": "#e74c3c", "ACQUIRE": "#f39c12",
            "TRACK_COARSE": "#3498db", "TRACK_FINE": "#27ae60",
            "LOST": "#e74c3c", "REACQUIRE": "#f39c12",
        }
        # 清除旧区域
        for region in self.atp_regions:
            self.plot_rate.removeItem(region)
        self.atp_regions.clear()

        if atp_windowed and len(t_np) > 0:
            # 扫描连续状态段
            seg_start = 0
            for i in range(1, len(atp_windowed) + 1):
                cur = atp_windowed[i - 1]
                nxt = atp_windowed[i] if i < len(atp_windowed) else None
                if nxt != cur:
                    if cur and cur in atp_colors:
                        x0 = float(t_np[seg_start])
                        x1 = float(t_np[i - 1])
                        color = QtGui.QColor(atp_colors[cur])
                        color.setAlpha(40)
                        region = pg.LinearRegionItem(
                            values=(x0, x1),
                            orientation="vertical",
                            brush=pg.mkBrush(color),
                            pen=pg.mkPen(None),
                            movable=False,
                        )
                        self.plot_rate.addItem(region)
                        self.atp_regions.append(region)
                    seg_start = i

            # 更新当前 ATP 状态标签
            last_state = atp_windowed[-1] if atp_windowed else ""
            atp_color = atp_colors.get(last_state, COLOR["text_sub"])
            self.lbl_current_atp.setText(f"ATP: {last_state or '--'}")
            self.lbl_current_atp.setStyleSheet(
                f"color: {atp_color}; font-size: 9pt; font-weight: 700;"
            )

    @staticmethod
    def _camera_info_text(frame: Optional[FrameSample], u_px: float, v_px: float, in_fov: bool) -> tuple[str, bool]:
        if frame is None:
            return "无帧", False
        cx = float(frame.intrinsics.get("cx", frame.image.shape[1] * 0.5))
        cy = float(frame.intrinsics.get("cy", frame.image.shape[0] * 0.5))
        du = u_px - cx if math.isfinite(u_px) else float("nan")
        dv = v_px - cy if math.isfinite(v_px) else float("nan")
        sigma_px = float(frame.intrinsics.get("sigma_px", 0.0))
        du_str = f"{du:.1f}" if math.isfinite(du) else "--"
        dv_str = f"{dv:.1f}" if math.isfinite(dv) else "--"
        text = f"du={du_str}, dv={dv_str} | sigma={sigma_px:.1f}px"
        return text, in_fov

    @staticmethod
    def _camera_info_from_frame(frame: Optional[FrameSample]) -> tuple[str, bool]:
        if frame is None:
            return "No frame", False
        w = int(frame.image.shape[1])
        h = int(frame.image.shape[0])
        cx = float(frame.intrinsics.get("cx", w * 0.5))
        cy = float(frame.intrinsics.get("cy", h * 0.5))
        sigma_px = float(frame.intrinsics.get("sigma_px", float("nan")))
        det = frame.detection
        if det.found and det.cx is not None and det.cy is not None:
            u_px = float(det.cx)
            v_px = float(det.cy)
            du = u_px - cx
            dv = v_px - cy
            ok = True
            det_text = f"u={u_px:.1f}, v={v_px:.1f}"
        else:
            du = float("nan")
            dv = float("nan")
            ok = False
            det_text = "u=--, v=--"
        text = (
            f"{w}x{h}px  |  t={frame.timestamp:.3f}s  |  "
            f"{det_text}  |  du={du:.1f}, dv={dv:.1f}  |  "
            f"sigma={sigma_px:.2f}px  |  {'detected' if ok else 'not detected'}"
        )
        return text, ok

    def _update_summary(self, snapshot: Any) -> None:
        r = snapshot.raspi
        c = snapshot.camera
        self.summary_labels["t"].setText(f"{snapshot.timestamp:.2f}s")
        self.summary_labels["distance"].setText(f"距离: {float(c.get('distance_m', 0.0)):.1f}m")
        atp = str(r.get("atp_state", "--")) or "--"
        atp_colors = {"SEARCH": "#e74c3c", "ACQUIRE": "#f39c12", "TRACK_COARSE": "#3498db", "TRACK_FINE": "#27ae60", "LOST": "#e74c3c", "REACQUIRE": "#f39c12"}
        atp_color = atp_colors.get(atp, COLOR["text_sub"])
        self.summary_labels["atp_state"].setText(f"ATP: {atp}")
        self.summary_labels["atp_state"].setStyleSheet(f"color: {atp_color}; font-weight: 700; font-size: 10pt;")
        self.summary_labels["control_program"].setText(f"算法: {r.get('control_program_name', '--')}")
        self.summary_labels["delay"].setText(f"延时: {r.get('last_process_latency_s', 0)*1000:.1f}ms")
        self.summary_labels["backlog"].setText(f"backlog: {r.get('pipeline_backlog_len', 0)}")

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
        in_fov = bool(c["in_fov"])

        # 状态卡片
        self.card_value_labels["err"].setText(f"{du:.1f}" if math.isfinite(du) else "--")
        self.card_value_labels["angle_err"].setText(f"{angle_err:.2f}°")
        dist_m = float(c.get("distance_m", 0.0))
        self.card_value_labels["distance"].setText(f"{dist_m:.1f}m")

    def _update_diag_tab(self, snapshot: Any, raw_frame: Optional[FrameSample], raspi_frame: Optional[FrameSample]) -> None:
        g = snapshot.gimbal
        c = snapshot.camera
        r = snapshot.raspi
        t = snapshot.target
        raw_ts = float("nan") if raw_frame is None else raw_frame.timestamp
        raspi_ts = float("nan") if raspi_frame is None else raspi_frame.timestamp

        gimbal_items: list[tuple[str, str]] = [
            ("模式", str(g["mode"])),
            ("偏航角（内部）", f"{g['yaw_deg_internal']:.2f}°"),
            ("偏航角（显示）", f"{g['yaw_deg_display']:.2f}°"),
            ("俯仰角", f"{g['pitch_deg']:.2f}°"),
            ("偏航角速度", f"{g['yaw_rate_dps']:.2f} dps"),
            ("偏航角速度指令", f"{g.get('yaw_rate_ref_dps', 0.0):.2f} dps"),
            ("电源状态", str(g.get("power_state", ""))),
        ]
        camera_items: list[tuple[str, str]] = [
            ("焦距", f"{c['f_current_mm']:.1f} mm"),
            ("帧序号", f"{c['frame_id']}"),
            ("目标像素 u", f"{c['u_px']:.1f} px"),
            ("目标像素 v", f"{c['v_px']:.1f} px"),
            ("距离", f"{float(c.get('distance_m', 0.0)):.1f} m"),
            ("光斑 sigma", f"{float(c.get('sigma_px', 0.0)):.2f} px"),
            ("亮度", f"{float(c.get('brightness', 0.0)):.3f}"),
            ("原始帧时间戳", f"{raw_ts:.3f} s"),
            ("Raspi帧时间戳", f"{raspi_ts:.3f} s"),
        ]
        raspi_items: list[tuple[str, str]] = [
            ("ATP 状态", str(r.get("atp_state", "--"))),
            ("控制程序", str(r.get("control_program_name", "--"))),
            ("观测时间戳", f"{float(r.get('effective_obs_timestamp', float('nan'))):.3f} s"),
            ("管线积压", f"{r['pipeline_backlog_len']}"),
            ("处理延时", f"{float(r['last_process_latency_s']) * 1000:.1f} ms"),
            ("指令生效时间戳", f"{float(r.get('last_command_apply_timestamp', float('nan'))):.3f} s"),
            ("电源状态", str(r.get("power_state", ""))),
        ]
        target_items: list[tuple[str, str]] = [
            ("仿真时间", f"{snapshot.timestamp:.3f} s"),
            ("位置 x", f"{float(t.get('x_m', float('nan'))):.2f} m"),
            ("位置 y", f"{float(t.get('y_m', float('nan'))):.2f} m"),
            ("位置 z", f"{float(t.get('z_m', float('nan'))):.2f} m"),
            ("速度 vx", f"{float(t.get('vx_mps', float('nan'))):.2f} m/s"),
            ("速度 vy", f"{float(t.get('vy_mps', float('nan'))):.2f} m/s"),
            ("速度 vz", f"{float(t.get('vz_mps', float('nan'))):.2f} m/s"),
        ]
        self._fill_diag_tree("gimbal", gimbal_items)
        self._fill_diag_tree("camera", camera_items)
        self._fill_diag_tree("raspi", raspi_items)
        self._fill_diag_tree("target", target_items)

    def _fill_diag_tree(self, key: str, items: list[tuple[str, str]]) -> None:
        top = self.diag_top_items[key]
        # 复用已有子节点，不足则新增，多余则删除
        while top.childCount() < len(items):
            child = QtWidgets.QTreeWidgetItem(top, ["", ""])
            child.setForeground(0, QtGui.QBrush(QtGui.QColor(COLOR["text_sub"])))
            child.setForeground(1, QtGui.QBrush(QtGui.QColor(COLOR["text_main"])))
            child.setFont(1, QtGui.QFont("Microsoft YaHei UI", 9, QtGui.QFont.Bold))
        while top.childCount() > len(items):
            top.removeChild(top.child(top.childCount() - 1))
        for i, (field, value) in enumerate(items):
            child = top.child(i)
            child.setText(0, field)
            child.setText(1, value)

    def _update_fps_label(self) -> None:
        self._ui_tick_counter += 1
        now = time.perf_counter()
        elapsed = now - self._last_ui_perf
        if elapsed >= 1.0:
            self._fps_value = self._ui_tick_counter / elapsed
            self._ui_tick_counter = 0
            self._last_ui_perf = now
            self.lbl_fps.setText(f"{UI_TEXT['fps']}: {self._fps_value:.1f}")
            self.lbl_fps_summary.setText(f"FPS: {self._fps_value:.1f}")

    def _render_tick(self) -> None:
        snapshot, raw_frame = self.state_buf.read_latest()
        if snapshot is None:
            self._update_fps_label()
            return

        t_list, x_hist, y_hist, err_list, rate_list, angle_err_list, atp_state_list = self.state_buf.read_curves()
        self._draw_world(snapshot, x_hist, y_hist)
        self._draw_timeline(t_list, err_list, rate_list, angle_err_list, atp_state_list)

        self.raw_panel.view.update_frame(raw_frame)
        u_px = float(snapshot.camera.get("u_px", float("nan")))
        v_px = float(snapshot.camera.get("v_px", float("nan")))
        in_fov = bool(snapshot.camera.get("in_fov", False))
        raw_info, raw_ok = self._camera_info_text(raw_frame, u_px, v_px, in_fov)
        self.raw_panel.set_info_text(raw_info, raw_ok)

        raspi_obs_ts = float(snapshot.raspi.get("effective_obs_timestamp", float("nan")))
        raspi_frame = None if not math.isfinite(raspi_obs_ts) else self.state_buf.find_frame_at_or_before(raspi_obs_ts)
        self.raspi_panel.view.update_frame(raspi_frame)
        raspi_info, raspi_ok = self._camera_info_text(raspi_frame, u_px, v_px, in_fov)
        # 在 Raspi 面板标题中显示帧延时差
        if raspi_frame is not None and raw_frame is not None:
            frame_lag_ms = (raw_frame.timestamp - raspi_frame.timestamp) * 1000
            self.raspi_panel.title_label.setText(f"Raspi 延时视角（滞后 {frame_lag_ms:.1f}ms）")
        self.raspi_panel.set_info_text(raspi_info, raspi_ok)

        self._update_core_tab(snapshot, raw_frame)
        self._update_diag_tab(snapshot, raw_frame, raspi_frame)
        self._update_summary(snapshot)
        self._update_fps_label()

        # 实时更新观测延迟
        read_ms = raspi_delay_cfg.image_read_delay_s * 1000
        proc_ms = raspi_delay_cfg.image_process_delay_s * 1000
        send_ms = raspi_delay_cfg.command_tx_delay_s * 1000
        tau_ms = gimbal_cfg.response_tau_s * 1000
        obs_lat_ms = float(snapshot.raspi.get("last_process_latency_s", 0.0)) * 1000
        self.lbl_delay_chain.setText(
            f"  延时链路: 读取{read_ms:.0f}ms → 处理{proc_ms:.0f}ms → 发送{send_ms:.0f}ms + 云台τ{tau_ms:.0f}ms │ 观测延迟: {obs_lat_ms:.1f}ms"
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self.ui_timer.stop()
        self.worker.stop()
        self.worker.wait(2000)
        self._settings.setValue("main_splitter_sizes", self.main_splitter.sizes())
        super().closeEvent(event)
