from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np

from config import AxisLimitConfig, GimbalConfig, axis_limit_cfg, gimbal_cfg


@dataclass
class Gimbal2AxisState:
    yaw_deg_internal: float
    pitch_deg: float
    yaw_rate_dps: float
    pitch_rate_dps: float


class GimbalPlant2Axis:
    def __init__(self, axis_cfg: AxisLimitConfig | None = None, legacy_gimbal_cfg: GimbalConfig | None = None):
        self.axis_cfg = axis_cfg or axis_limit_cfg
        self.legacy_gimbal_cfg = legacy_gimbal_cfg or gimbal_cfg
        self.response_tau_s = max(0.0, float(self.legacy_gimbal_cfg.response_tau_s))
        self.static_friction_threshold_dps = float(self.legacy_gimbal_cfg.static_friction_threshold_dps)
        # 参数偏差：初始化时对 tau 施加随机偏差，偏差是硬件属性，运行中不变
        tau_deviation_ratio = float(self.legacy_gimbal_cfg.tau_deviation_ratio)
        if tau_deviation_ratio > 0.0:
            tau_actual = self.response_tau_s * (1.0 + np.random.normal(0.0, tau_deviation_ratio))
            self.response_tau_s = max(1e-12, tau_actual)
        self.reset()

    def reset(self) -> None:
        self.yaw_deg_internal = float(self.legacy_gimbal_cfg.initial_angle_deg)
        self.pitch_deg = 0.0
        self.yaw_rate_dps = 0.0
        self.pitch_rate_dps = 0.0

    def _first_order_rate_update(self, current_rate_dps: float, cmd_rate_dps: float, dt: float) -> float:
        if self.response_tau_s <= 1e-12:
            return cmd_rate_dps
        alpha = dt / (self.response_tau_s + dt)
        return (1.0 - alpha) * current_rate_dps + alpha * cmd_rate_dps

    def step(self, rate_cmd: Tuple[float, float] | Dict[str, float], dt: float) -> Gimbal2AxisState:
        if isinstance(rate_cmd, dict):
            yaw_cmd = float(rate_cmd.get("yaw_rate_cmd_dps", 0.0))
            pitch_cmd = float(rate_cmd.get("pitch_rate_cmd_dps", 0.0))
        else:
            yaw_cmd = float(rate_cmd[0])
            pitch_cmd = float(rate_cmd[1])

        max_rate = float(self.axis_cfg.max_rate_dps)
        yaw_cmd = max(-max_rate, min(max_rate, yaw_cmd))
        pitch_cmd = max(-max_rate, min(max_rate, pitch_cmd))

        # 静摩擦死区：静止时低速率命令被吸收
        threshold = self.static_friction_threshold_dps
        if threshold > 0.0:
            if abs(self.yaw_rate_dps) < 1e-9 and abs(yaw_cmd) < threshold:
                yaw_cmd = 0.0
            if abs(self.pitch_rate_dps) < 1e-9 and abs(pitch_cmd) < threshold:
                pitch_cmd = 0.0

        self.yaw_rate_dps = self._first_order_rate_update(self.yaw_rate_dps, yaw_cmd, dt)
        self.pitch_rate_dps = self._first_order_rate_update(self.pitch_rate_dps, pitch_cmd, dt)

        self.yaw_deg_internal += self.yaw_rate_dps * dt
        next_pitch = self.pitch_deg + self.pitch_rate_dps * dt

        if next_pitch <= self.axis_cfg.pitch_min_deg:
            self.pitch_deg = float(self.axis_cfg.pitch_min_deg)
            if self.pitch_rate_dps < 0.0:
                self.pitch_rate_dps = 0.0
        elif next_pitch >= self.axis_cfg.pitch_max_deg:
            self.pitch_deg = float(self.axis_cfg.pitch_max_deg)
            if self.pitch_rate_dps > 0.0:
                self.pitch_rate_dps = 0.0
        else:
            self.pitch_deg = next_pitch

        return self.get_state()

    def get_state(self) -> Gimbal2AxisState:
        return Gimbal2AxisState(
            yaw_deg_internal=self.yaw_deg_internal,
            pitch_deg=self.pitch_deg,
            yaw_rate_dps=self.yaw_rate_dps,
            pitch_rate_dps=self.pitch_rate_dps,
        )

