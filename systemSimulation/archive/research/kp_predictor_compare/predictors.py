"""角度域预测器 — Kalman 滤波 + FFT 正弦拟合。

遵循四时段时序：
  时段 1: 从 obs 读取云台角度/角速度 + 相机内参
  时段 2: 像素检测 + 云台角度 → 目标世界角度
  时段 3: 预测目标世界角度到 t+horizon
  时段 4: 由调用方读取 obs 云台角度，计算误差并转为速率命令

预测器不预设系统延时。horizon 从连续 obs 时间戳自动估算。
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from runtime.types import wrap_pm180


# ── 角度 ↔ 像素转换 ──────────────────────────────────────────────

def pixel_to_angle(
    det_u: float, det_v: float,
    cx: float, cy: float, f_px: float,
    gimbal_yaw: float, gimbal_pitch: float,
) -> tuple[float, float]:
    """像素检测 + 云台角度 → 目标世界角度 (时段 2)."""
    dy = math.degrees(math.atan2(det_u - cx, f_px))
    dp = math.degrees(math.atan2(-(det_v - cy), f_px))
    return wrap_pm180(gimbal_yaw + dy), gimbal_pitch + dp


def angle_to_pixel_error(
    target_yaw: float, target_pitch: float,
    gimbal_yaw: float, gimbal_pitch: float,
    cx: float, cy: float, f_px: float,
) -> tuple[float, float]:
    """目标角度 - 云台角度 → 像素误差 (时段 4 辅助).

    返回 (pred_u - cx, pred_v - cy)，可直接送入 Kp。
    """
    ey = max(-89.0, min(89.0, wrap_pm180(target_yaw - gimbal_yaw)))
    ep = max(-89.0, min(89.0, target_pitch - gimbal_pitch))
    return (f_px * math.tan(math.radians(ey)),
            -f_px * math.tan(math.radians(ep)))


# ── 通用辅助 ────────────────────────────────────────────────────

def _finite(v: float) -> bool:
    return math.isfinite(v)


def _read_gimbal_intrinsics(obs: dict):
    """从 obs 中提取云台状态和相机内参 (时段 1)."""
    gimbal = obs.get("gimbal") or {}
    frame = obs.get("frame")
    intrinsics = getattr(frame, "intrinsics", {}) or {}

    g_yaw = float(gimbal.get("yaw_deg_internal", float("nan")))
    g_pitch = float(gimbal.get("pitch_deg", float("nan")))
    g_yaw_rate = float(gimbal.get("yaw_rate_dps", 0.0))
    g_pitch_rate = float(gimbal.get("pitch_rate_dps", 0.0))
    cx = float(intrinsics.get("cx", float("nan")))
    cy = float(intrinsics.get("cy", float("nan")))
    f_px = float(intrinsics.get("f_px", float("nan")))

    ok = all(_finite(v) for v in [g_yaw, g_pitch, cx, cy, f_px]) and f_px > 0
    if not ok:
        return None
    return g_yaw, g_pitch, g_yaw_rate, g_pitch_rate, cx, cy, f_px


# ── Kalman 角度预测器 ────────────────────────────────────────────

class KalmanAnglePredictor:
    """角度域线性卡尔曼滤波器。

    状态 x = [yaw, pitch, yaw_rate, pitch_rate]
    观测 z = [yaw, pitch]
    模型: 恒速 (rate 不变 + 过程噪声)
    """

    def __init__(
        self,
        q_pos: float = 0.5,
        q_vel: float = 3.0,
        r_meas: float = 0.1,
    ) -> None:
        self._q_pos = q_pos
        self._q_vel = q_vel
        self._r_meas = r_meas

        self._x = np.zeros(4)
        self._P = np.eye(4) * 1000.0
        self._initialized = False
        self._last_ts: Optional[float] = None
        self._obs_dt: Optional[float] = None
        self._yaw_anchor: Optional[float] = None

        # 时段 1 缓存 (最新一次 obs 的云台状态)
        self._gimbal_yaw: Optional[float] = None
        self._gimbal_pitch: Optional[float] = None
        self._gimbal_yaw_rate: Optional[float] = None
        self._gimbal_pitch_rate: Optional[float] = None
        self._cx: Optional[float] = None
        self._cy: Optional[float] = None
        self._f_px: Optional[float] = None

    def update(self, obs: dict, detection) -> None:
        ts = float(obs.get("timestamp", float("nan")))
        if not _finite(ts):
            return

        info = _read_gimbal_intrinsics(obs)
        if info is None:
            return
        g_yaw, g_pitch, g_yaw_rate, g_pitch_rate, cx, cy, f_px = info
        self._gimbal_yaw = g_yaw
        self._gimbal_pitch = g_pitch
        self._gimbal_yaw_rate = g_yaw_rate
        self._gimbal_pitch_rate = g_pitch_rate
        self._cx = cx
        self._cy = cy
        self._f_px = f_px

        # 估算 obs_dt
        if self._last_ts is not None and ts > self._last_ts:
            self._obs_dt = ts - self._last_ts
        self._last_ts = ts

        dt = self._obs_dt if self._obs_dt else 0.0

        # 时段 2: 像素 → 世界角度 (仅在有检测时)
        if detection is None or not getattr(detection, "found", False):
            # 无检测 → 只做 KF predict，不 update
            if self._initialized and dt > 0:
                F = self._build_F(dt)
                Q = self._build_Q(dt)
                self._x = F @ self._x
                self._P = F @ self._P @ F.T + Q
            return

        det_cx = getattr(detection, "cx", None)
        det_cy = getattr(detection, "cy", None)
        if det_cx is None or det_cy is None:
            return

        t_yaw, t_pitch = pixel_to_angle(
            float(det_cx), float(det_cy), cx, cy, f_px, g_yaw, g_pitch,
        )

        # yaw 解卷绕
        if self._yaw_anchor is not None:
            diff = t_yaw - self._yaw_anchor
            t_yaw = self._yaw_anchor + (diff + 180.0) % 360.0 - 180.0
        self._yaw_anchor = t_yaw

        if not self._initialized:
            self._x = np.array([t_yaw, t_pitch, 0.0, 0.0])
            self._P = np.eye(4) * 1000.0
            self._initialized = True
            return

        if dt <= 0:
            return

        # KF predict
        F = self._build_F(dt)
        Q = self._build_Q(dt)
        self._x = F @ self._x
        self._P = F @ self._P @ F.T + Q

        # KF update
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        R = np.diag([self._r_meas ** 2, self._r_meas ** 2])
        z = np.array([t_yaw, t_pitch])
        innov = z - H @ self._x
        S = H @ self._P @ H.T + R
        K = self._P @ H.T @ np.linalg.inv(S)
        self._x = self._x + K @ innov
        self._P = (np.eye(4) - K @ H) @ self._P

    def predict_angle(self, horizon_s: float) -> Optional[tuple[float, float]]:
        """时段 3: 预测目标世界角度。

        Args:
            horizon_s: 预测时间跨度。调用方可从 obs_dt 估算。

        Returns:
            (predicted_target_yaw, predicted_target_pitch) 或 None。
        """
        if not self._initialized:
            return None
        pred_yaw = self._x[0] + self._x[2] * horizon_s
        pred_pitch = self._x[1] + self._x[3] * horizon_s
        return float(wrap_pm180(pred_yaw)), float(pred_pitch)

    @property
    def obs_dt(self) -> Optional[float]:
        return self._obs_dt

    @staticmethod
    def _build_F(dt: float) -> np.ndarray:
        return np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ], dtype=float)

    def _build_Q(self, dt: float) -> np.ndarray:
        qp = self._q_pos ** 2 * dt
        qv = self._q_vel ** 2 * dt
        return np.diag([qp, qp, qv, qv])


# ── FFT 正弦预测器 ──────────────────────────────────────────────

class FFTSineAnglePredictor:
    """FFT 频率检测 + 正弦模型外推。

    对角度历史做 FFT 找主频 → 正弦+线性拟合 → 外推到 t+horizon。
    无显著周期成分时退化为线性外推。
    """

    def __init__(
        self,
        window_size: int = 150,
        min_samples: int = 20,
        freq_floor: float = 0.05,
        freq_ceil: float = 3.0,
        peak_snr: float = 3.0,
    ) -> None:
        self._window = window_size
        self._min_samples = min_samples
        self._freq_floor = freq_floor
        self._freq_ceil = freq_ceil
        self._peak_snr = peak_snr

        self._history: list[tuple[float, float, float]] = []  # (ts, yaw, pitch)
        self._last_ts: Optional[float] = None
        self._obs_dt: Optional[float] = None
        self._yaw_anchor: Optional[float] = None

        # 时段 1 缓存
        self._gimbal_yaw: Optional[float] = None
        self._gimbal_pitch: Optional[float] = None
        self._cx: Optional[float] = None
        self._cy: Optional[float] = None
        self._f_px: Optional[float] = None

    def update(self, obs: dict, detection) -> None:
        ts = float(obs.get("timestamp", float("nan")))
        if not _finite(ts):
            return

        info = _read_gimbal_intrinsics(obs)
        if info is None:
            return
        g_yaw, g_pitch, _, _, cx, cy, f_px = info
        self._gimbal_yaw = g_yaw
        self._gimbal_pitch = g_pitch
        self._cx = cx
        self._cy = cy
        self._f_px = f_px

        if self._last_ts is not None and ts > self._last_ts:
            self._obs_dt = ts - self._last_ts
        self._last_ts = ts

        if detection is None or not getattr(detection, "found", False):
            return
        det_cx = getattr(detection, "cx", None)
        det_cy = getattr(detection, "cy", None)
        if det_cx is None or det_cy is None:
            return

        t_yaw, t_pitch = pixel_to_angle(
            float(det_cx), float(det_cy), cx, cy, f_px, g_yaw, g_pitch,
        )
        if self._yaw_anchor is not None:
            diff = t_yaw - self._yaw_anchor
            t_yaw = self._yaw_anchor + (diff + 180.0) % 360.0 - 180.0
        self._yaw_anchor = t_yaw

        self._history.append((ts, t_yaw, t_pitch))
        if len(self._history) > self._window:
            self._history = self._history[-self._window:]

    def predict_angle(self, horizon_s: float) -> Optional[tuple[float, float]]:
        if len(self._history) < self._min_samples:
            return None
        if self._obs_dt is None or self._obs_dt <= 0:
            return None

        ts = np.array([h[0] for h in self._history])
        yaws = np.array([h[1] for h in self._history])
        pitches = np.array([h[2] for h in self._history])

        # 解卷绕
        yaws_uw = np.rad2deg(np.unwrap(np.deg2rad(yaws)))
        rel_t = ts - ts[0]
        t_now = rel_t[-1]
        t_pred = t_now + horizon_s

        pred_yaw = self._fit_and_extrapolate(rel_t, yaws_uw, t_pred)
        pred_pitch = self._linear_extrapolate(rel_t, pitches, t_pred)

        return float(wrap_pm180(pred_yaw)), float(pred_pitch)

    @property
    def obs_dt(self) -> Optional[float]:
        return self._obs_dt

    def _fit_and_extrapolate(
        self, t: np.ndarray, y: np.ndarray, t_pred: float,
    ) -> float:
        """FFT 找主频 → 正弦+线性拟合 → 外推。无主频则线性外推。"""
        dt = float(np.median(np.diff(t)))
        if dt <= 0:
            return float(y[-1])

        centered = y - np.mean(y)
        spec = np.abs(np.fft.rfft(centered))
        freqs = np.fft.rfftfreq(len(centered), d=dt)

        if len(spec) <= 1:
            return self._linear_extrapolate(t, y, t_pred)

        # 在有效频率范围内找峰值
        mask = (freqs >= self._freq_floor) & (freqs <= self._freq_ceil)
        valid_spec = spec.copy()
        valid_spec[~mask] = 0

        noise_floor = np.median(spec[1:]) if len(spec) > 2 else 0.0
        peak_idx = int(np.argmax(valid_spec[1:])) + 1
        peak_amp = valid_spec[peak_idx]

        if peak_amp <= noise_floor * self._peak_snr or freqs[peak_idx] <= 0:
            return self._linear_extrapolate(t, y, t_pred)

        f_peak = float(freqs[peak_idx])
        omega = 2.0 * math.pi * f_peak

        # 在峰值附近精调频率
        best_loss = float("inf")
        best_f = f_peak
        best_c = None
        for f_try in np.linspace(max(self._freq_floor, f_peak * 0.7),
                                  min(self._freq_ceil, f_peak * 1.3), 15):
            w = 2.0 * math.pi * f_try
            A = np.column_stack([np.sin(w * t), np.cos(w * t), t, np.ones_like(t)])
            c, *_ = np.linalg.lstsq(A, y, rcond=None)
            loss = float(np.mean((A @ c - y) ** 2))
            if loss < best_loss:
                best_loss = loss
                best_f = f_try
                best_c = c

        if best_c is None:
            return self._linear_extrapolate(t, y, t_pred)

        w = 2.0 * math.pi * best_f
        pred = (best_c[0] * math.sin(w * t_pred)
                + best_c[1] * math.cos(w * t_pred)
                + best_c[2] * t_pred
                + best_c[3])

        # 安全检查：预测值不应偏离观测范围太远
        y_range = float(np.max(y) - np.min(y))
        y_mid = float(np.mean(y))
        if abs(pred - y_mid) > 3.0 * y_range + 1.0:
            return self._linear_extrapolate(t, y, t_pred)

        return float(pred)

    @staticmethod
    def _linear_extrapolate(t: np.ndarray, y: np.ndarray, t_pred: float) -> float:
        n = min(30, len(t))
        c = np.polyfit(t[-n:], y[-n:], 1)
        return float(c[0] * t_pred + c[1])
