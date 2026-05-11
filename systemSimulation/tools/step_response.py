"""云台控制工作台 — 实时阶跃响应分析 GUI。

启动后云台自动上电并持续运行，用户随时注入角速率/角度指令，
实时观察角度和角速度变化。支持全局时间线和单次指令响应片段双视角。

使用:
    python tools/step_response.py
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field

import numpy as np

try:
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import (
        QApplication,
        QComboBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QPushButton,
        QSplitter,
        QVBoxLayout,
        QWidget,
    )
    import pyqtgraph as pg
except ImportError as exc:
    raise SystemExit("需要 PyQt5 + pyqtgraph: pip install PyQt5 pyqtgraph") from exc

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from config import AxisLimitConfig, ControlPreset, GimbalConfig, LoopConfig  # noqa: E402
from config import yaw_display_cfg  # noqa: E402
from entities.gimbal.control import ANGLE_MODE, RATE_MODE  # noqa: E402
from entities.gimbal.entity import GimbalEntity  # noqa: E402
from runtime.types import POWER_READY  # noqa: E402

# ── 配色 ──────────────────────────────────────────────

C = {
    "bg": "#F7F8FC", "panel": "#FFFFFF", "border": "#E5E7EB",
    "text": "#1F2937", "muted": "#9CA3AF", "accent": "#3B82F6",
    "rate_cmd": "#3B82F6", "rate_actual": "#1D4ED8",
    "angle_cmd": "#EF4444", "angle_actual": "#B91C1C",
    "pitch_cmd": "#8B5CF6", "pitch_actual": "#6D28D9",
    "grid": "#E5E7EB",
}

# ── 数据结构 ──────────────────────────────────────────

DT_S = 0.005  # 仿真步长 5ms


@dataclass
class CommandRecord:
    idx: int
    t_inject: float
    mode: str        # "RATE" / "ANGLE"
    axis: str        # "yaw" / "pitch"
    value: float
    # 指标（settling 后填充）
    t_settled: float | None = None
    delay_ms: float = 0.0
    rise_ms: float = 0.0
    settle_ms: float = 0.0
    overshoot_pct: float = 0.0
    ss_error_pct: float = 0.0
    steady_value: float = 0.0
    # 原始数据
    seg_t: list[float] = field(default_factory=list)
    seg_actual: list[float] = field(default_factory=list)
    seg_ref: list[float] = field(default_factory=list)
    settled: bool = False


def _first_progress_time(t: np.ndarray, y: np.ndarray, start: float, target: float, progress: float) -> float | None:
    """Return the first time the response reaches a normalized progress threshold."""
    delta = target - start
    if abs(delta) < 1e-9:
        return None
    progress_curve = (y - start) / delta
    hit = np.where(progress_curve >= progress)[0]
    if len(hit) == 0:
        return None
    return float(t[int(hit[0])])


# ── 仿真引擎 ──────────────────────────────────────────

class GimbalSim:
    """包装 GimbalEntity，持续仿真并记录数据。"""

    def __init__(self):
        self.entity = GimbalEntity()
        self.entity.power_on(timestamp=0.0)
        self.t = 0.0
        self.ready = False
        self._latest_state = None

        # 全局历史（numpy 缓冲，最多保留 60s）
        max_pts = int(60.0 / DT_S)
        self._buf_t = np.zeros(max_pts)
        self._buf_yaw = np.zeros(max_pts)
        self._buf_rate = np.zeros(max_pts)
        self._buf_rate_ref = np.zeros(max_pts)
        self._buf_pitch = np.zeros(max_pts)
        self._buf_pitch_rate = np.zeros(max_pts)
        self._buf_pitch_rate_ref = np.zeros(max_pts)
        self._n = 0

        # 活跃指令
        self.commands: list[CommandRecord] = []
        self._active_cmd: CommandRecord | None = None
        self._cmd_counter = 0

    def advance(self, real_dt: float) -> None:
        """推进仿真 real_dt 秒。"""
        steps = max(1, int(real_dt / DT_S))
        for _ in range(steps):
            self.t += DT_S
            state = self.entity.update(DT_S, self.t)

            if not self.ready and state.power_state == POWER_READY:
                self.ready = True
            self._latest_state = state

            # 记录
            i = self._n % len(self._buf_t)
            self._buf_t[i] = self.t
            self._buf_yaw[i] = state.yaw_deg_display
            self._buf_rate[i] = state.yaw_rate_dps
            self._buf_rate_ref[i] = state.yaw_rate_ref_dps
            self._buf_pitch[i] = state.pitch_deg
            self._buf_pitch_rate[i] = state.pitch_rate_dps
            self._buf_pitch_rate_ref[i] = state.pitch_rate_ref_dps
            self._n += 1

            # 追踪活跃指令
            if self._active_cmd and not self._active_cmd.settled:
                self._track_command(state)

    def history(self, last_s: float = 20.0):
        """返回最近 last_s 秒的数据。"""
        total = min(self._n, len(self._buf_t))
        if total == 0:
            return tuple(np.array([]) for _ in range(7))
        idx = np.arange(self._n - total, self._n) % len(self._buf_t)
        t = self._buf_t[idx]
        t_max = t[-1] if len(t) > 0 else 0
        t_min = max(0.0, t_max - last_s)
        mask = t >= t_min
        return (
            t[mask], self._buf_yaw[idx[mask]], self._buf_rate[idx[mask]],
            self._buf_rate_ref[idx[mask]], self._buf_pitch[idx[mask]],
            self._buf_pitch_rate[idx[mask]], self._buf_pitch_rate_ref[idx[mask]],
        )

    def inject(self, mode: str, axis: str, value: float) -> CommandRecord | None:
        """注入指令并返回记录。"""
        if not self.ready:
            return None

        if mode == "RATE":
            self.entity.set_mode(RATE_MODE, self.t)
            if axis == "yaw":
                self.entity.set_rate_target(value, 0.0, self.t)
            else:
                self.entity.set_rate_target(0.0, value, self.t)
        else:
            self.entity.set_mode(ANGLE_MODE, self.t)
            if axis == "yaw":
                self.entity.set_angle_target(value, 0.0, self.t)
            else:
                self.entity.set_angle_target(0.0, value, self.t)

        self._cmd_counter += 1
        rec = CommandRecord(
            idx=self._cmd_counter, t_inject=self.t,
            mode=mode, axis=axis, value=value,
        )
        # 记录注入时刻的初始值
        state = self.entity.get_state(self.t)
        rec.seg_t.append(0.0)
        if axis == "yaw":
            actual = state["yaw_rate_dps"] if mode == "RATE" else state["yaw_deg_display"]
            ref_val = state["yaw_rate_ref_dps"] if mode == "RATE" else value
        else:
            actual = state["pitch_rate_dps"] if mode == "RATE" else state["pitch_deg"]
            ref_val = state["pitch_rate_ref_dps"] if mode == "RATE" else value
        rec.seg_actual.append(float(actual))
        rec.seg_ref.append(float(ref_val))

        self.commands.append(rec)
        self._active_cmd = rec
        return rec

    def _track_command(self, state) -> None:
        rec = self._active_cmd
        if rec is None:
            return

        dt_since = self.t - rec.t_inject
        rec.seg_t.append(dt_since)

        if rec.axis == "yaw":
            actual = state.yaw_rate_dps if rec.mode == "RATE" else state.yaw_deg_display
            ref = state.yaw_rate_ref_dps if rec.mode == "RATE" else rec.value
        else:
            actual = state.pitch_rate_dps if rec.mode == "RATE" else state.pitch_deg
            ref = state.pitch_rate_ref_dps if rec.mode == "RATE" else rec.value

        rec.seg_actual.append(float(actual))
        rec.seg_ref.append(float(ref))

        # 检查是否已建立（±2% 持续 100ms）
        if len(rec.seg_actual) < 10:
            return

        arr = np.array(rec.seg_actual[-int(0.1 / DT_S):])
        final = arr[-1]
        target = rec.value
        if abs(target) < 1e-9:
            settled = np.all(np.abs(arr) < 0.1)
        else:
            settled = np.all(np.abs(arr - target) / abs(target) < 0.02)

        if settled:
            rec.settled = True
            rec.t_settled = self.t
            rec.steady_value = float(arr[-1])
            self._compute_metrics(rec)
            self._active_cmd = None

    @staticmethod
    def _compute_metrics(rec: CommandRecord) -> None:
        t = np.array(rec.seg_t)
        y = np.array(rec.seg_actual)
        target = rec.value

        if len(t) < 5 or abs(target) < 1e-9:
            return

        # 延迟时间：首次偏离初始值 > 1% target
        y0 = y[0]
        threshold = abs(target) * 0.01
        mask_moved = np.abs(y - y0) > threshold
        if mask_moved.any():
            rec.delay_ms = float(t[mask_moved.argmax()]) * 1000

        # 上升/下降时间统一按归一化进度计算，兼容正向和负向阶跃。
        t_10 = _first_progress_time(t, y, y0, target, 0.1)
        t_90 = _first_progress_time(t, y, y0, target, 0.9)
        if t_10 is not None and t_90 is not None and t_90 >= t_10:
            rec.rise_ms = (t_90 - t_10) * 1000

        # 建立时间：进入 ±2% 并保持到最后
        band = abs(target) * 0.02
        for i in range(len(y)):
            if np.all(np.abs(y[i:] - target) <= band):
                rec.settle_ms = float(t[i]) * 1000
                break

        # 超调量
        if target > y0:
            peak = float(y.max())
        else:
            peak = float(y.min())
        rec.overshoot_pct = max(0.0, (abs(peak - target) / abs(target)) * 100) if abs(target) > 1e-9 else 0.0

        # 稳态误差
        rec.ss_error_pct = ((rec.steady_value - target) / abs(target)) * 100 if abs(target) > 1e-9 else 0.0


# ── 主窗口 ──────────────────────────────────────────────

class StepResponseWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("云台控制工作台 — 阶跃响应分析")
        self.resize(1200, 800)
        self.setMinimumSize(960, 640)
        self.setStyleSheet(f"QMainWindow {{ background: {C['bg']}; }}")

        self.sim = GimbalSim()
        self._wall_time = time.monotonic()
        self._selected_cmd: CommandRecord | None = None
        self._cmd_markers: dict[int, list[pg.InfiniteLine]] = {}  # rec.idx → [rate_marker, angle_marker]

        self._build_ui()

        # 仿真定时器 60fps
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    # ── UI 构建 ──

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        # 指令注入栏
        self._build_cmd_bar(root)

        # 全局视图
        self._build_global_view(root)

        # 下方：片段视图 + 指令历史
        bottom = QSplitter(Qt.Horizontal)
        self._build_segment_view(bottom)
        self._build_history_list(bottom)
        bottom.setSizes([700, 300])
        root.addWidget(bottom, 1)

        # 状态栏
        self._build_status_bar(root)

    def _build_cmd_bar(self, parent):
        bar = QWidget()
        bar.setStyleSheet(f"background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 6px;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        # 模式
        layout.addWidget(self._label("模式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["RATE_MODE", "ANGLE_MODE"])
        self.mode_combo.setFixedWidth(140)
        self.mode_combo.setStyleSheet(f"padding: 4px 8px; border: 1px solid {C['border']}; border-radius: 4px;")
        layout.addWidget(self.mode_combo)

        # 轴
        layout.addWidget(self._label("轴:"))
        self.axis_combo = QComboBox()
        self.axis_combo.addItems(["yaw", "pitch"])
        self.axis_combo.setFixedWidth(80)
        self.axis_combo.setStyleSheet(f"padding: 4px 8px; border: 1px solid {C['border']}; border-radius: 4px;")
        layout.addWidget(self.axis_combo)

        # 指令值
        self.mode_combo.currentIndexChanged.connect(self._update_unit_hint)
        layout.addWidget(self._label("指令值:"))
        self.value_input = QLineEdit("10.0")
        self.value_input.setFixedWidth(100)
        self.value_input.setStyleSheet(
            f"padding: 4px 8px; border: 1px solid {C['border']}; border-radius: 4px;"
            f"font-family: Consolas, monospace;"
        )
        layout.addWidget(self.value_input)
        self.unit_hint = QLabel("°/s")
        self.unit_hint.setStyleSheet(f"color: {C['muted']}; font-size: 9pt;")
        layout.addWidget(self.unit_hint)

        # 发送
        send_btn = QPushButton("发送指令")
        send_btn.setCursor(Qt.PointingHandCursor)
        send_btn.setStyleSheet(f"""
            QPushButton {{ background: {C['accent']}; color: white; border: none;
                           border-radius: 6px; padding: 8px 20px; font-weight: 600; }}
            QPushButton:hover {{ background: #2563EB; }}
        """)
        send_btn.clicked.connect(self._send_command)
        layout.addWidget(send_btn)

        # 停止
        stop_btn = QPushButton("停止")
        stop_btn.setCursor(Qt.PointingHandCursor)
        stop_btn.setStyleSheet(f"""
            QPushButton {{ background: white; color: {C['text']}; border: 1px solid {C['border']};
                           border-radius: 6px; padding: 8px 16px; }}
            QPushButton:hover {{ background: #F3F4F6; }}
        """)
        stop_btn.clicked.connect(self._stop)
        layout.addWidget(stop_btn)

        layout.addStretch()
        parent.addWidget(bar)

    def _build_global_view(self, parent):
        group = QWidget()
        group.setStyleSheet(f"background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 6px;")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        header = QLabel("  全局时间线")
        header.setStyleSheet(f"font-size: 10pt; font-weight: 600; color: {C['text']}; padding: 4px;")
        layout.addWidget(header)

        # 角速率图
        self.rate_plot = pg.PlotWidget()
        self.rate_plot.setBackground("white")
        self.rate_plot.showGrid(x=True, y=True, alpha=0.2)
        self.rate_plot.setXRange(0, 5)
        self.rate_plot.setLabel("left", "角速率", units="°/s")
        self.rate_plot.addLegend(offset=(8, 8))
        self.g_rate_ref = self.rate_plot.plot([], [], pen=pg.mkPen(C["rate_cmd"], width=2, style=pg.QtCore.Qt.DashLine), name="速率指令")
        self.g_rate = self.rate_plot.plot([], [], pen=pg.mkPen(C["rate_actual"], width=2), name="速率实际")

        # 角度图（X 轴联动）
        self.angle_plot = pg.PlotWidget()
        self.angle_plot.setBackground("white")
        self.angle_plot.showGrid(x=True, y=True, alpha=0.2)
        self.angle_plot.setXRange(0, 5)
        self.angle_plot.setLabel("left", "角度", units="°")
        self.angle_plot.setLabel("bottom", "t", units="s")
        self.angle_plot.addLegend(offset=(8, 8))
        self.g_angle_ref = self.angle_plot.plot([], [], pen=pg.mkPen(C["angle_cmd"], width=2, style=pg.QtCore.Qt.DashLine), name="角度目标")
        self.g_angle = self.angle_plot.plot([], [], pen=pg.mkPen(C["angle_actual"], width=2), name="角度实际")

        layout.addWidget(self.rate_plot)
        layout.addWidget(self.angle_plot)
        parent.addWidget(group, 1)

    def _build_segment_view(self, parent):
        group = QWidget()
        group.setStyleSheet(f"background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 6px;")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self.seg_header = QLabel("  响应片段（点击历史记录查看）")
        self.seg_header.setStyleSheet(f"font-size: 10pt; font-weight: 600; color: {C['text']}; padding: 4px;")
        layout.addWidget(self.seg_header)

        self.seg_plot = pg.PlotWidget()
        self.seg_plot.setBackground("white")
        self.seg_plot.showGrid(x=True, y=True, alpha=0.2)
        self.seg_plot.setLabel("bottom", "t", units="ms")
        self.seg_plot.setXRange(0, 500)

        self.s_ref = self.seg_plot.plot([], [], pen=pg.mkPen(C["rate_cmd"], width=2, style=pg.QtCore.Qt.DashLine), name="指令")
        self.s_actual = self.seg_plot.plot([], [], pen=pg.mkPen(C["rate_actual"], width=2), name="实际")
        self.seg_plot.addLegend(offset=(8, 8))

        # 指标标注区
        self.seg_metrics = QLabel("")
        self.seg_metrics.setWordWrap(True)
        self.seg_metrics.setStyleSheet(f"font-size: 9pt; color: {C['text']}; padding: 8px;")

        layout.addWidget(self.seg_plot)
        layout.addWidget(self.seg_metrics)
        parent.addWidget(group)

    def _build_history_list(self, parent):
        group = QWidget()
        group.setStyleSheet(f"background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 6px;")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        header = QLabel("  指令历史")
        header.setStyleSheet(f"font-size: 10pt; font-weight: 600; color: {C['text']}; padding: 4px;")
        layout.addWidget(header)

        self.history_list = QListWidget()
        self.history_list.setStyleSheet(f"""
            QListWidget {{ border: none; font-family: Consolas, monospace; font-size: 9pt; }}
            QListWidget::item {{ padding: 6px; border-bottom: 1px solid {C['border']}; }}
            QListWidget::item:selected {{ background: {C['accent']}22; color: {C['accent']}; }}
        """)
        self.history_list.currentRowChanged.connect(self._on_history_selected)
        layout.addWidget(self.history_list)
        parent.addWidget(group)

    def _build_status_bar(self, parent):
        preset = ControlPreset()
        yaw_mode_str = "[0,360)" if yaw_display_cfg.default_mode == "0_360" else "[-180,180)"
        bar = QLabel(
            f"  状态: 初始化中...  |  Yaw显示: {yaw_mode_str}  |  "
            f"PID: Kp={preset.angle_kp_yaw}/{preset.rate_kp_yaw}  Ki={preset.rate_ki_yaw}  "
            f"τ={GimbalConfig().response_tau_s*1000:.0f}ms  |  "
            f"速率误差: --  角度误差: --"
        )
        bar.setStyleSheet(f"""
            background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 4px;
            font-size: 9pt; color: {C['muted']}; padding: 4px 8px;
        """)
        self._status_label = bar
        parent.addWidget(bar)

    @staticmethod
    def _label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: 10pt; color: {C['text']};")
        return lbl

    def _update_unit_hint(self):
        is_rate = self.mode_combo.currentText() == "RATE_MODE"
        self.unit_hint.setText("°/s" if is_rate else "°")

    def _selected_axis(self) -> str:
        return self.axis_combo.currentText()

    def _current_series(self, history_window_s: float):
        t, yaw, rate, rate_ref, pitch, pitch_rate, pitch_rate_ref = self.sim.history(history_window_s)
        axis = self._selected_axis()
        if axis == "pitch":
            return t, pitch, pitch_rate, pitch_rate_ref, axis
        return t, yaw, rate, rate_ref, axis

    # ── 仿真循环 ──

    def _tick(self):
        now = time.monotonic()
        real_dt = min(now - self._wall_time, 0.05)
        self._wall_time = now

        self.sim.advance(real_dt)

        # 更新状态 + 实时误差
        if self.sim.ready:
            # 计算实时误差
            t_hist, angle_h, rate_h, rate_ref_h, axis = self._current_series(1.0)
            rate_err = float(rate_ref_h[-1] - rate_h[-1]) if len(rate_h) > 0 else 0.0
            angle_err_str = "--"
            if self.sim._latest_state is not None:
                mode = self.sim._latest_state.mode
                if mode == ANGLE_MODE:
                    angle_target = self._get_active_angle_target(axis)
                    if angle_target is not None:
                        angle_err = angle_target - float(angle_h[-1]) if len(angle_h) > 0 else 0.0
                        angle_err_str = f"{angle_err:+.2f}°"

            self._status_label.setText(
                f"  READY  |  axis={axis}  |  t={self.sim.t:.2f}s  |  "
                f"速率误差: {rate_err:+.2f}°/s  |  角度误差: {angle_err_str}"
            )
        else:
            self._status_label.setText(
                f"  BOOTING ({self.sim.t:.2f}s)..."
            )

        # 更新全局曲线
        self._draw_global()

        # 仅刷新刚 settled 的指令（已刷新过的跳过）
        if self.sim._active_cmd is None:
            for rec in self.sim.commands:
                if rec.settled and not getattr(rec, '_ui_refreshed', False):
                    self._refresh_history_item(rec)
                    rec._ui_refreshed = True

    def _draw_global(self):
        t, angle, rate, rate_ref, axis = self._current_series(20.0)
        if len(t) < 2:
            return

        # 角速率图
        self.g_rate_ref.setData(t, rate_ref)
        self.g_rate.setData(t, rate)

        # 角度图 — 目标角度：从当前轴最近的 ANGLE 指令推断，否则用实际值
        self.g_angle.setData(t, angle)
        # 角度参考线：找到最近的 ANGLE 指令目标
        angle_ref_val = self._get_active_angle_target(axis)
        if angle_ref_val is not None:
            self.g_angle_ref.setData(t, np.full_like(t, angle_ref_val))
        else:
            self.g_angle_ref.setData([], [])

        t_max = t[-1]
        t_min = max(0, t_max - 15)

        # X 范围同步
        self.rate_plot.setXRange(t_min, t_max + 0.1, padding=0.0)
        self.angle_plot.setXRange(t_min, t_max + 0.1, padding=0.0)

        mask = t >= t_min

        # 角速率 Y 范围（独立）
        r_vals = np.concatenate([rate[mask], rate_ref[mask]])
        r_vals = r_vals[np.isfinite(r_vals)]
        if len(r_vals) > 0:
            pad = max(2.0, (r_vals.max() - r_vals.min()) * 0.15)
            self.rate_plot.setYRange(r_vals.min() - pad, r_vals.max() + pad)

        # 角度 Y 范围（独立）
        a_vals = angle[mask]
        a_vals = a_vals[np.isfinite(a_vals)]
        if len(a_vals) > 0:
            pad = max(2.0, (a_vals.max() - a_vals.min()) * 0.15)
            self.angle_plot.setYRange(a_vals.min() - pad, a_vals.max() + pad)

        # 指令标记线（增量管理，避免每帧重建）
        # 清理滚出视野的旧标记
        stale = [idx for idx, markers in self._cmd_markers.items()
                 if self.sim.commands[idx - 1].t_inject < t_min]
        for idx in stale:
            for m in self._cmd_markers.pop(idx):
                pwidget = self.rate_plot if m in list(self.rate_plot.items()) else self.angle_plot
                try:
                    pwidget.removeItem(m)
                except Exception:
                    pass

        # 添加新指令的标记
        for rec in self.sim.commands:
            if rec.idx not in self._cmd_markers and rec.t_inject >= t_min:
                pen = pg.mkPen(C["accent"], width=1, style=pg.QtCore.Qt.DotLine)
                m1 = pg.InfiniteLine(pos=rec.t_inject, angle=90, pen=pen)
                m2 = pg.InfiniteLine(pos=rec.t_inject, angle=90, pen=pen)
                self.rate_plot.addItem(m1)
                self.angle_plot.addItem(m2)
                self._cmd_markers[rec.idx] = [m1, m2]

    def _get_active_angle_target(self, axis: str) -> float | None:
        """返回当前轴最近的 ANGLE 模式指令目标值。"""
        for rec in reversed(self.sim.commands):
            if rec.mode == "ANGLE" and rec.axis == axis:
                return rec.value
        return None

    # ── 指令注入 ──

    def _send_command(self):
        if not self.sim.ready:
            return
        try:
            value = float(self.value_input.text())
        except ValueError:
            return

        mode = "RATE" if self.mode_combo.currentText() == "RATE_MODE" else "ANGLE"
        axis = self.axis_combo.currentText()
        rec = self.sim.inject(mode, axis, value)
        if rec is None:
            return

        # 添加历史条目
        unit = "°/s" if mode == "RATE" else "°"
        text = f"#{rec.idx:<3} t={rec.t_inject:>6.2f}s  {mode:<6} {axis:<5} {value:>+7.1f}{unit:>3}  → 等待..."
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, rec.idx)
        self.history_list.addItem(item)
        self.history_list.setCurrentRow(self.history_list.count() - 1)

    def _stop(self):
        """发送零速率指令停止云台。"""
        if not self.sim.ready:
            return
        self.sim.entity.set_mode(RATE_MODE, self.sim.t)
        self.sim.entity.set_rate_target(0.0, 0.0, self.sim.t)

    # ── 历史选择 → 片段视图 ──

    def _on_history_selected(self, row: int):
        if row < 0 or row >= self.history_list.count():
            return
        item = self.history_list.item(row)
        idx = item.data(Qt.UserRole)
        rec = next((r for r in self.sim.commands if r.idx == idx), None)
        if rec is None:
            return

        self._selected_cmd = rec
        self._draw_segment(rec)

    def _draw_segment(self, rec: CommandRecord):
        if len(rec.seg_t) < 2:
            return

        t_ms = np.array(rec.seg_t) * 1000
        actual = np.array(rec.seg_actual)
        ref = np.array(rec.seg_ref)

        self.s_ref.setData(t_ms, ref)
        self.s_actual.setData(t_ms, actual)

        # Y 轴标签跟随模式
        if rec.mode == "RATE":
            self.seg_plot.setLabel("left", "角速率", units="°/s")
        else:
            self.seg_plot.setLabel("left", "角度", units="°")

        self.seg_plot.setXRange(0, max(t_ms[-1], 100))
        y_lo = min(actual.min(), ref.min()) - 1
        y_hi = max(actual.max(), ref.max()) + 1
        self.seg_plot.setYRange(y_lo, y_hi)

        mode_str = "角速率" if rec.mode == "RATE" else "角度"
        unit = "°/s" if rec.mode == "RATE" else "°"
        self.seg_header.setText(f"  响应片段 #{rec.idx}  {mode_str} {rec.value:+.1f}{unit} ({rec.axis})")

        # 指标
        if rec.settled:
            self.seg_metrics.setText(
                f"延迟: {rec.delay_ms:.1f}ms  |  "
                f"上升: {rec.rise_ms:.1f}ms  |  "
                f"建立: {rec.settle_ms:.1f}ms  |  "
                f"超调: {rec.overshoot_pct:.1f}%  |  "
                f"稳态误差: {rec.ss_error_pct:.1f}%  |  "
                f"稳态值: {rec.steady_value:.2f}{unit}"
            )
        else:
            self.seg_metrics.setText("响应中...")

    def _refresh_history_item(self, rec: CommandRecord):
        for i in range(self.history_list.count()):
            item = self.history_list.item(i)
            if item.data(Qt.UserRole) == rec.idx:
                unit = "°/s" if rec.mode == "RATE" else "°"
                text = (
                    f"#{rec.idx:<3} t={rec.t_inject:>6.2f}s  {rec.mode:<6} {rec.axis:<5} "
                    f"{rec.value:>+7.1f}{unit:>3}  → "
                    f"上升{rec.rise_ms:>5.0f}ms  建立{rec.settle_ms:>5.0f}ms  "
                    f"超调{rec.overshoot_pct:>5.1f}%"
                )
                item.setText(text)
                if self._selected_cmd and self._selected_cmd.idx == rec.idx:
                    self._draw_segment(rec)
                break


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    pg.setConfigOptions(antialias=True)
    window = StepResponseWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
