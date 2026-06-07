"""角度域 + 短时 FFT 多频分解预测器（研究用）。

工作流程对应"四时段时序"：
- 时段 1（采样）：obs 中读取 gimbal_yaw_t1, gimbal_pitch_t1, yaw_rate_t1, pitch_rate_t1, intrinsics
- 时段 2（建模）：像素检测 + 云台角度 → 目标世界角度，存入历史
- 时段 3（预测）：对世界角度历史做短时 FFT，找主频，最小二乘拟合，外推
- 时段 4（控制）：云台积分到命令生效时刻，反投影得到像素

参数：
    window_seconds=2.0   历史窗口长度（频率分辨率 0.5Hz）
    fit_period_s=0.1     重新拟合周期
    max_frequencies=3    主频上限
    energy_threshold=0.1 主频能量阈值（相对最大功率）
    min_samples_full=100 进入完整 FFT 流程的最少样本数
    min_samples_linear=24 退化为线性外推的最少样本数
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from runtime.types import Detection, wrap_pm180

from research.predictor_motion_compare.angle_utils import (
    gimbal_integrate,
    pixel_to_world_angle,
    unwrap_yaw_series,
    world_angle_to_pixel,
)


@dataclass
class _FitResult:
    """拟合结果缓存。"""
    omegas: np.ndarray            # 选中的角频率（rad/s），可能为空
    coef_yaw: np.ndarray          # yaw 模型系数
    coef_pitch: np.ndarray        # pitch 模型系数
    ts_anchor: float              # 拟合时的最后样本时间戳（t=0 在此时刻）
    yaw_mean: float               # yaw 均值（unwrap 后）
    pitch_mean: float             # pitch 均值


class AngleSineFFTPredictor:
    """角度域 + 短时 FFT 多频预测器。"""

    def __init__(
        self,
        window_seconds: float = 5.0,
        fit_period_s: float = 0.1,
        max_frequencies: int = 3,
        energy_threshold: float = 0.1,
        min_samples_full: int = 60,
        min_samples_linear: int = 16,
        history_capacity: int = 1200,
    ) -> None:
        self.window_seconds = window_seconds
        self.fit_period_s = fit_period_s
        self.max_frequencies = max_frequencies
        self.energy_threshold = energy_threshold
        self.min_samples_full = min_samples_full
        self.min_samples_linear = min_samples_linear

        # 历史：(ts, target_yaw_world, target_pitch_world)
        self._history: deque[tuple[float, float, float]] = deque(maxlen=history_capacity)

        # 时段 1 缓存：最近一次有效观测的 gimbal 状态和相机内参
        self._gimbal_yaw_t1: Optional[float] = None
        self._gimbal_pitch_t1: Optional[float] = None
        self._gimbal_yaw_rate_t1: Optional[float] = None
        self._gimbal_pitch_rate_t1: Optional[float] = None
        self._cx_center: Optional[float] = None
        self._cy_center: Optional[float] = None
        self._f_px: Optional[float] = None

        self._fit: Optional[_FitResult] = None
        self._last_fit_ts: float = float("-inf")

    # ---- 时段 1 + 2：采样与建模 ----

    def update(self, obs: dict, detection: Optional[Detection]) -> None:
        """有有效检测时积累历史样本。"""
        ts = float(obs.get("timestamp", float("nan")))
        if not math.isfinite(ts):
            return

        gimbal = obs.get("gimbal") or {}
        frame = obs.get("frame")
        intrinsics = getattr(frame, "intrinsics", {}) or {}

        gimbal_yaw = float(gimbal.get("yaw_deg_internal", float("nan")))
        gimbal_pitch = float(gimbal.get("pitch_deg", float("nan")))
        gimbal_yaw_rate = float(gimbal.get("yaw_rate_dps", 0.0))
        gimbal_pitch_rate = float(gimbal.get("pitch_rate_dps", 0.0))
        cx_center = float(intrinsics.get("cx", float("nan")))
        cy_center = float(intrinsics.get("cy", float("nan")))
        f_px = float(intrinsics.get("f_px", float("nan")))

        if not (math.isfinite(gimbal_yaw) and math.isfinite(gimbal_pitch)
                and math.isfinite(cx_center) and math.isfinite(cy_center)
                and math.isfinite(f_px) and f_px > 0.0):
            return

        # 缓存 gimbal/intrinsics 给时段 4 用，无论有无检测
        self._gimbal_yaw_t1 = gimbal_yaw
        self._gimbal_pitch_t1 = gimbal_pitch
        self._gimbal_yaw_rate_t1 = gimbal_yaw_rate
        self._gimbal_pitch_rate_t1 = gimbal_pitch_rate
        self._cx_center = cx_center
        self._cy_center = cy_center
        self._f_px = f_px

        # 无有效检测：不更新历史
        if detection is None or not detection.found or detection.cx is None or detection.cy is None:
            return

        target_yaw_world, target_pitch_world = pixel_to_world_angle(
            cx_det=float(detection.cx),
            cy_det=float(detection.cy),
            cx_center=cx_center,
            cy_center=cy_center,
            f_px=f_px,
            gimbal_yaw_deg=gimbal_yaw,
            gimbal_pitch_deg=gimbal_pitch,
        )

        # 严格递增时间戳
        if self._history and ts <= self._history[-1][0]:
            ts = self._history[-1][0] + 1e-6

        self._history.append((ts, target_yaw_world, target_pitch_world))

    # ---- 时段 3 + 4：预测与反投影 ----

    def predict(self, n_steps: int) -> Optional[tuple[float, float]]:
        """预测 n_steps 后命令生效时刻的目标像素位置。"""
        if not self._history:
            return None
        if (self._gimbal_yaw_t1 is None or self._gimbal_pitch_t1 is None
                or self._cx_center is None or self._f_px is None):
            return None

        last_ts, last_yaw_world, last_pitch_world = self._history[-1]
        last_dt = self._estimate_dt()
        horizon_s = max(0.0, last_dt * float(max(1, int(n_steps))))

        # 时段 3：预测目标世界角度
        if len(self._history) < self.min_samples_linear:
            pred_yaw_world = last_yaw_world
            pred_pitch_world = last_pitch_world
        elif len(self._history) < self.min_samples_full:
            pred_yaw_world, pred_pitch_world = self._linear_extrapolate(horizon_s)
        else:
            if self._fit is None or (last_ts - self._last_fit_ts) >= self.fit_period_s:
                self._fit = self._refit(last_dt)
                self._last_fit_ts = last_ts
            if self._fit is None:
                pred_yaw_world, pred_pitch_world = self._linear_extrapolate(horizon_s)
            else:
                pred_yaw_world, pred_pitch_world = self._eval_fit(self._fit, horizon_s, last_ts)

        # 时段 4：云台积分到命令生效时刻
        gimbal_yaw_t4, gimbal_pitch_t4 = gimbal_integrate(
            gimbal_yaw_deg=self._gimbal_yaw_t1,
            gimbal_pitch_deg=self._gimbal_pitch_t1,
            gimbal_yaw_rate_dps=self._gimbal_yaw_rate_t1 or 0.0,
            gimbal_pitch_rate_dps=self._gimbal_pitch_rate_t1 or 0.0,
            horizon_s=horizon_s,
        )

        # 反投影到像素
        pred_cx, pred_cy = world_angle_to_pixel(
            target_yaw_world_deg=pred_yaw_world,
            target_pitch_world_deg=pred_pitch_world,
            gimbal_yaw_deg=gimbal_yaw_t4,
            gimbal_pitch_deg=gimbal_pitch_t4,
            cx_center=self._cx_center,
            cy_center=self._cy_center,
            f_px=self._f_px,
        )
        return pred_cx, pred_cy

    # ---- 内部辅助 ----

    def _estimate_dt(self) -> float:
        """估计采样间隔。"""
        if len(self._history) < 2:
            return 0.0
        ts_arr = np.array([item[0] for item in self._history], dtype=float)
        dts = np.diff(ts_arr)
        if dts.size == 0:
            return 0.0
        dt = float(np.median(dts))
        return max(dt, 1e-6)

    def _linear_extrapolate(self, horizon_s: float) -> tuple[float, float]:
        """退化模式：拟合 [1, t] 做线性外推。"""
        history = list(self._history)
        ts = np.array([item[0] for item in history], dtype=float)
        yaw = unwrap_yaw_series(np.array([item[1] for item in history], dtype=float))
        pitch = np.array([item[2] for item in history], dtype=float)
        last_ts = ts[-1]

        # 仅用最近 window_seconds 的样本
        mask = ts >= last_ts - self.window_seconds
        if mask.sum() >= 2:
            ts = ts[mask]
            yaw = yaw[mask]
            pitch = pitch[mask]

        t_rel = ts - last_ts
        if np.ptp(t_rel) < 1e-9:
            return float(wrap_pm180(yaw[-1])), float(pitch[-1])

        design = np.column_stack([np.ones_like(t_rel), t_rel])
        coef_yaw, *_ = np.linalg.lstsq(design, yaw, rcond=None)
        coef_pitch, *_ = np.linalg.lstsq(design, pitch, rcond=None)

        pred_yaw_unwrapped = float(coef_yaw[0] + coef_yaw[1] * horizon_s)
        pred_pitch = float(coef_pitch[0] + coef_pitch[1] * horizon_s)
        return float(wrap_pm180(pred_yaw_unwrapped)), pred_pitch

    def _refit(self, last_dt: float) -> Optional[_FitResult]:
        """完整 FFT 流程：找主频 + 最小二乘求系数。"""
        history = list(self._history)
        ts_full = np.array([item[0] for item in history], dtype=float)
        yaw_full = np.array([item[1] for item in history], dtype=float)
        pitch_full = np.array([item[2] for item in history], dtype=float)
        last_ts = ts_full[-1]

        mask = ts_full >= last_ts - self.window_seconds
        if mask.sum() < self.min_samples_full:
            return None
        ts = ts_full[mask]
        yaw = unwrap_yaw_series(yaw_full[mask])
        pitch = pitch_full[mask]

        if np.ptp(ts) < 1e-6 or last_dt <= 0.0:
            return None

        # 找主频（用 yaw 残差的频谱；pitch 共用同一组 ω）
        yaw_mean = float(np.mean(yaw))
        pitch_mean = float(np.mean(pitch))
        y_centered = yaw - yaw_mean

        N = y_centered.size
        window = np.hanning(N)
        spectrum = np.fft.rfft(y_centered * window)
        freqs = np.fft.rfftfreq(N, d=last_dt)
        power = np.abs(spectrum) ** 2

        omegas: list[float] = []
        if power.size > 1:
            # 排除 DC（freqs[0]==0）
            nonzero = np.arange(1, power.size)
            if nonzero.size:
                power_nonzero = power[nonzero]
                peak_max = float(power_nonzero.max())
                if peak_max > 0.0:
                    threshold = self.energy_threshold * peak_max
                    sorted_idx = nonzero[np.argsort(-power[nonzero])]
                    for idx in sorted_idx[: self.max_frequencies]:
                        if power[idx] >= threshold and freqs[idx] > 0.0:
                            omegas.append(2.0 * math.pi * float(freqs[idx]))

        # 设计矩阵：[1, t, sin(ω₁t), cos(ω₁t), ...]
        t_rel = ts - last_ts
        cols = [np.ones_like(t_rel), t_rel]
        for omega in omegas:
            cols.append(np.sin(omega * t_rel))
            cols.append(np.cos(omega * t_rel))
        design = np.column_stack(cols)

        coef_yaw, *_ = np.linalg.lstsq(design, yaw, rcond=None)
        coef_pitch, *_ = np.linalg.lstsq(design, pitch, rcond=None)

        return _FitResult(
            omegas=np.array(omegas, dtype=float),
            coef_yaw=coef_yaw,
            coef_pitch=coef_pitch,
            ts_anchor=last_ts,
            yaw_mean=yaw_mean,
            pitch_mean=pitch_mean,
        )

    def _eval_fit(
        self,
        fit: _FitResult,
        horizon_s: float,
        last_ts: float,
    ) -> tuple[float, float]:
        """基于缓存的拟合系数外推到 last_ts + horizon_s。"""
        # 拟合时的相对时间是 ts - fit.ts_anchor，为了让缓存依然适用
        # 当前时刻相对锚点的偏移
        t_eval = (last_ts - fit.ts_anchor) + horizon_s

        basis = [1.0, t_eval]
        for omega in fit.omegas:
            basis.append(math.sin(omega * t_eval))
            basis.append(math.cos(omega * t_eval))
        basis_arr = np.array(basis, dtype=float)

        pred_yaw_unwrapped = float(basis_arr @ fit.coef_yaw)
        pred_pitch = float(basis_arr @ fit.coef_pitch)
        return float(wrap_pm180(pred_yaw_unwrapped)), pred_pitch
