"""角度域线性卡尔曼预测器（研究用）。

状态向量: [yaw_world, pitch_world, yaw_rate, pitch_rate]（度、度/秒）
观测: [yaw_world, pitch_world]（来自时段 2 的像素+云台合成）

工作流程对应"四时段时序"：
- 时段 1: obs 中读取云台角度/速率/内参
- 时段 2: 像素检测 + 云台角度 → 目标世界角度，作为观测送入 KF
- 时段 3: KF 预测 + 更新；predict() 时用 F^n_steps 外推到命令生效时刻
- 时段 4: 云台积分 + 反投影回像素

为公平对比，本实现与 entities/raspi/predictors/linear_kf.py 的滤波结构一致，
仅把状态从像素空间换成角度空间，加上时段 4 的反投影。
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from runtime.types import Detection, wrap_pm180

from research.predictor_motion_compare.angle_utils import (
    gimbal_integrate,
    pixel_to_world_angle,
    world_angle_to_pixel,
)


class AngleLinearKF:
    """角度域线性卡尔曼滤波预测器。

    状态: x = [yaw, pitch, yaw_rate, pitch_rate]ᵀ
    观测: z = [yaw, pitch]ᵀ
    模型: 恒速（rate 不变 + 高斯过程噪声）

    Args:
        process_noise_pos_dps: 角度过程噪声标准差，默认 1.0 度
        process_noise_vel_dps: 角速度过程噪声标准差，默认 5.0 度/秒
        measurement_noise_dps: 观测噪声标准差，默认 0.3 度
    """

    def __init__(
        self,
        process_noise_pos_dps: float = 1.0,
        process_noise_vel_dps: float = 5.0,
        measurement_noise_dps: float = 0.3,
    ) -> None:
        self.process_noise_pos_dps = process_noise_pos_dps
        self.process_noise_vel_dps = process_noise_vel_dps
        self.measurement_noise_dps = measurement_noise_dps

        self._x: np.ndarray = np.zeros(4)
        self._P: np.ndarray = np.eye(4) * 1000.0

        self._last_timestamp: Optional[float] = None
        self._dt: float = 0.0
        self._yaw_unwrap_anchor: Optional[float] = None  # 最近一次 yaw 观测，用于解卷绕
        self._initialized: bool = False

        # 时段 1 缓存
        self._gimbal_yaw_t1: Optional[float] = None
        self._gimbal_pitch_t1: Optional[float] = None
        self._gimbal_yaw_rate_t1: Optional[float] = None
        self._gimbal_pitch_rate_t1: Optional[float] = None
        self._cx_center: Optional[float] = None
        self._cy_center: Optional[float] = None
        self._f_px: Optional[float] = None

    # ---- KF 矩阵构造 ----

    @staticmethod
    def _build_F(dt: float) -> np.ndarray:
        return np.array([
            [1.0, 0.0, dt,  0.0],
            [0.0, 1.0, 0.0, dt ],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ])

    def _build_Q(self, dt: float) -> np.ndarray:
        q_pos = (self.process_noise_pos_dps ** 2) * dt
        q_vel = (self.process_noise_vel_dps ** 2) * dt
        return np.diag([q_pos, q_pos, q_vel, q_vel])

    @staticmethod
    def _build_H() -> np.ndarray:
        return np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ])

    def _build_R(self) -> np.ndarray:
        r2 = self.measurement_noise_dps ** 2
        return np.diag([r2, r2])

    # ---- 时段 1 + 2 ----

    def update(self, obs: dict, detection: Optional[Detection]) -> None:
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

        # 时段 1 缓存
        self._gimbal_yaw_t1 = gimbal_yaw
        self._gimbal_pitch_t1 = gimbal_pitch
        self._gimbal_yaw_rate_t1 = gimbal_yaw_rate
        self._gimbal_pitch_rate_t1 = gimbal_pitch_rate
        self._cx_center = cx_center
        self._cy_center = cy_center
        self._f_px = f_px

        # 计算 dt 并预测一步
        if self._last_timestamp is None:
            dt = 0.0
        else:
            dt = ts - self._last_timestamp
        self._last_timestamp = ts
        if dt > 0.0:
            self._dt = dt

        if self._initialized and self._dt > 0.0:
            F = self._build_F(self._dt)
            Q = self._build_Q(self._dt)
            self._x = F @ self._x
            self._P = F @ self._P @ F.T + Q

        # 时段 2：像素 → 世界角度（仅在有有效检测时）
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

        # 解卷绕：让连续观测的 yaw 不在 ±180 处跳变
        if self._yaw_unwrap_anchor is not None:
            diff = target_yaw_world - self._yaw_unwrap_anchor
            diff_wrapped = (diff + 180.0) % 360.0 - 180.0
            target_yaw_world = self._yaw_unwrap_anchor + diff_wrapped
        self._yaw_unwrap_anchor = target_yaw_world

        z = np.array([target_yaw_world, target_pitch_world])

        if not self._initialized:
            self._x = np.array([target_yaw_world, target_pitch_world, 0.0, 0.0])
            self._P = np.eye(4) * 1000.0
            self._initialized = True
            return

        # KF 更新
        H = self._build_H()
        R = self._build_R()
        innov = z - H @ self._x
        S = H @ self._P @ H.T + R
        K = self._P @ H.T @ np.linalg.inv(S)
        self._x = self._x + K @ innov
        self._P = (np.eye(4) - K @ H) @ self._P

    # ---- 时段 3 + 4 ----

    def predict(self, n_steps: int) -> Optional[tuple[float, float]]:
        if not self._initialized:
            return None
        if (self._gimbal_yaw_t1 is None or self._gimbal_pitch_t1 is None
                or self._cx_center is None or self._f_px is None):
            return None

        n = max(1, int(n_steps))
        horizon_s = self._dt * n

        # 时段 3：线性外推（恒速模型 → F^n 等价于 pos + vel * horizon_s）
        pred_yaw_unwrapped = self._x[0] + self._x[2] * horizon_s
        pred_pitch_world = self._x[1] + self._x[3] * horizon_s
        pred_yaw_world = float(wrap_pm180(pred_yaw_unwrapped))

        # 时段 4：云台积分
        gimbal_yaw_t4, gimbal_pitch_t4 = gimbal_integrate(
            gimbal_yaw_deg=self._gimbal_yaw_t1,
            gimbal_pitch_deg=self._gimbal_pitch_t1,
            gimbal_yaw_rate_dps=self._gimbal_yaw_rate_t1 or 0.0,
            gimbal_pitch_rate_dps=self._gimbal_pitch_rate_t1 or 0.0,
            horizon_s=horizon_s,
        )

        # 反投影
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
