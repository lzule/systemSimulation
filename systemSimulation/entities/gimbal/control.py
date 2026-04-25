from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from config import (
    AxisLimitConfig,
    ControlPreset,
    LoopConfig,
    axis_limit_cfg,
    control_preset_cfg,
    loop_cfg,
)
from runtime.types import wrap_pm180

ANGLE_MODE = "ANGLE_MODE"
RATE_MODE = "RATE_MODE"


@dataclass
class ControllerTickFlags:
    angle_tick: bool = False
    rate_tick: bool = False


class CascadedController2Axis:
    def __init__(
        self,
        loop_config: LoopConfig | None = None,
        control_preset: ControlPreset | None = None,
        axis_config: AxisLimitConfig | None = None,
    ):
        self.loop_cfg = loop_config or loop_cfg
        self.preset = control_preset or control_preset_cfg
        self.axis_cfg = axis_config or axis_limit_cfg

        self.angle_dt = 1.0 / max(1e-6, self.loop_cfg.angle_loop_hz)
        self.rate_dt = 1.0 / max(1e-6, self.loop_cfg.rate_loop_hz)
        self.reset()

    def reset(self) -> None:
        self.mode = ANGLE_MODE
        self._latest_angle_cmd = {"yaw_deg": 0.0, "pitch_deg": 0.0, "timestamp": 0.0}
        self._latest_rate_cmd = {"yaw_rate_dps": 0.0, "pitch_rate_dps": 0.0, "timestamp": 0.0}
        self._yaw_rate_ref_dps = 0.0
        self._pitch_rate_ref_dps = 0.0
        self._yaw_rate_i = 0.0
        self._pitch_rate_i = 0.0
        self._angle_accum_s = 0.0
        self._rate_accum_s = 0.0

    def set_mode(self, mode: str) -> None:
        if mode not in (ANGLE_MODE, RATE_MODE):
            raise ValueError(f"Unsupported mode: {mode}")
        if mode != self.mode:
            self._yaw_rate_i = 0.0
            self._pitch_rate_i = 0.0
        self.mode = mode

    def set_angle_target(self, yaw_deg: float, pitch_deg: float, timestamp: float) -> None:
        pitch_deg = max(self.axis_cfg.pitch_min_deg, min(self.axis_cfg.pitch_max_deg, pitch_deg))
        self._latest_angle_cmd = {
            "yaw_deg": float(yaw_deg),
            "pitch_deg": float(pitch_deg),
            "timestamp": float(timestamp),
        }

    def set_rate_target(self, yaw_rate_dps: float, pitch_rate_dps: float, timestamp: float) -> None:
        max_rate = float(self.axis_cfg.max_rate_dps)
        self._latest_rate_cmd = {
            "yaw_rate_dps": max(-max_rate, min(max_rate, float(yaw_rate_dps))),
            "pitch_rate_dps": max(-max_rate, min(max_rate, float(pitch_rate_dps))),
            "timestamp": float(timestamp),
        }

    def _compute_outer_rate_ref(self, yaw_deg: float, pitch_deg: float) -> None:
        yaw_err_deg = wrap_pm180(self._latest_angle_cmd["yaw_deg"] - yaw_deg)
        pitch_err_deg = self._latest_angle_cmd["pitch_deg"] - pitch_deg

        yaw_ref = self.preset.angle_kp_yaw * yaw_err_deg
        pitch_ref = self.preset.angle_kp_pitch * pitch_err_deg

        max_rate = float(self.axis_cfg.max_rate_dps)
        self._yaw_rate_ref_dps = max(-max_rate, min(max_rate, yaw_ref))
        self._pitch_rate_ref_dps = max(-max_rate, min(max_rate, pitch_ref))

    def _compute_inner_cmd(self, yaw_rate_dps: float, pitch_rate_dps: float, dt: float) -> Dict[str, float]:
        yaw_rate_err = self._yaw_rate_ref_dps - yaw_rate_dps
        pitch_rate_err = self._pitch_rate_ref_dps - pitch_rate_dps

        self._yaw_rate_i += yaw_rate_err * dt
        self._pitch_rate_i += pitch_rate_err * dt

        i_lim = abs(float(self.preset.rate_integral_limit))
        self._yaw_rate_i = max(-i_lim, min(i_lim, self._yaw_rate_i))
        self._pitch_rate_i = max(-i_lim, min(i_lim, self._pitch_rate_i))

        yaw_cmd = self.preset.rate_kp_yaw * yaw_rate_err + self.preset.rate_ki_yaw * self._yaw_rate_i
        pitch_cmd = self.preset.rate_kp_pitch * pitch_rate_err + self.preset.rate_ki_pitch * self._pitch_rate_i

        cmd_lim = abs(float(self.preset.actuator_cmd_limit_dps))
        yaw_cmd = max(-cmd_lim, min(cmd_lim, yaw_cmd))
        pitch_cmd = max(-cmd_lim, min(cmd_lim, pitch_cmd))

        return {
            "yaw_rate_cmd_dps": yaw_cmd,
            "pitch_rate_cmd_dps": pitch_cmd,
        }

    def step(
        self,
        yaw_deg: float,
        pitch_deg: float,
        yaw_rate_dps: float,
        pitch_rate_dps: float,
        dt: float,
    ) -> Dict[str, float]:
        dt = max(1e-6, float(dt))
        self._angle_accum_s += dt
        self._rate_accum_s += dt
        ticks = ControllerTickFlags()

        if self.mode == RATE_MODE:
            self._yaw_rate_ref_dps = self._latest_rate_cmd["yaw_rate_dps"]
            self._pitch_rate_ref_dps = self._latest_rate_cmd["pitch_rate_dps"]
        else:
            while self._angle_accum_s >= self.angle_dt:
                self._angle_accum_s -= self.angle_dt
                self._compute_outer_rate_ref(yaw_deg, pitch_deg)
                ticks.angle_tick = True

        last_cmd = {"yaw_rate_cmd_dps": 0.0, "pitch_rate_cmd_dps": 0.0}
        while self._rate_accum_s >= self.rate_dt:
            self._rate_accum_s -= self.rate_dt
            last_cmd = self._compute_inner_cmd(yaw_rate_dps, pitch_rate_dps, self.rate_dt)
            ticks.rate_tick = True

        if not ticks.rate_tick:
            last_cmd = self._compute_inner_cmd(yaw_rate_dps, pitch_rate_dps, dt)

        return {
            **last_cmd,
            "yaw_rate_ref_dps": self._yaw_rate_ref_dps,
            "pitch_rate_ref_dps": self._pitch_rate_ref_dps,
            "yaw_rate_integral": self._yaw_rate_i,
            "pitch_rate_integral": self._pitch_rate_i,
            "mode": self.mode,
            "angle_tick": ticks.angle_tick,
            "rate_tick": ticks.rate_tick,
        }

