from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from config import (
    AxisLimitConfig,
    ControlPreset,
    GimbalConfig,
    LoopConfig,
    axis_limit_cfg,
    control_preset_cfg,
    gimbal_cfg,
    loop_cfg,
)
from entities.gimbal.control import ANGLE_MODE, RATE_MODE, CascadedController2Axis
from entities.gimbal.model import GimbalPlant2Axis
from runtime.types import POWER_BOOTING, POWER_OFF, POWER_READY, CommandResult


@dataclass
class GimbalState:
    timestamp: float
    power_state: str
    mode: str
    yaw_deg_internal: float
    yaw_deg_display: float
    pitch_deg: float
    yaw_rate_dps: float
    pitch_rate_dps: float
    yaw_rate_ref_dps: float
    pitch_rate_ref_dps: float
    angle_tick: bool
    rate_tick: bool
    last_command_apply_timestamp: Optional[float] = None


class GimbalEntity:
    def __init__(
        self,
        gimbal_config: GimbalConfig | None = None,
        axis_config: AxisLimitConfig | None = None,
        loop_config: LoopConfig | None = None,
        control_preset: ControlPreset | None = None,
    ):
        self.gimbal_cfg = gimbal_config or gimbal_cfg
        self.axis_cfg = axis_config or axis_limit_cfg
        self.loop_cfg = loop_config or loop_cfg
        self.control_preset = control_preset or control_preset_cfg

        self.power_state = POWER_OFF
        self.boot_remaining_s = 0.0
        self.boot_delay_s = float(self.gimbal_cfg.boot_delay_s)

        self.plant = GimbalPlant2Axis(self.axis_cfg, self.gimbal_cfg)
        self.controller = CascadedController2Axis(self.loop_cfg, self.control_preset, self.axis_cfg)
        self.last_command_apply_timestamp: Optional[float] = None

        self._last_ctrl = {
            "yaw_rate_ref_dps": 0.0,
            "pitch_rate_ref_dps": 0.0,
            "angle_tick": False,
            "rate_tick": False,
        }

    @staticmethod
    def wrap_0_360(angle_deg: float) -> float:
        return angle_deg % 360.0

    def power_on(self, timestamp: float) -> CommandResult:
        if self.power_state in (POWER_BOOTING, POWER_READY):
            return CommandResult(True, "ALREADY_ON", "gimbal already on", timestamp)
        self.power_state = POWER_BOOTING
        self.boot_remaining_s = self.boot_delay_s
        self.last_command_apply_timestamp = timestamp
        return CommandResult(True, "OK", "gimbal booting", timestamp)

    def power_off(self, timestamp: float) -> CommandResult:
        self.power_state = POWER_OFF
        self.boot_remaining_s = 0.0
        self.plant.reset()
        self.controller.reset()
        self.last_command_apply_timestamp = timestamp
        return CommandResult(True, "OK", "gimbal off", timestamp)

    def _reject_if_not_ready(self) -> Optional[CommandResult]:
        if self.power_state != POWER_READY:
            return CommandResult(False, "NOT_READY", f"gimbal state={self.power_state}")
        return None

    def set_mode(self, mode: str, timestamp: float) -> CommandResult:
        rejected = self._reject_if_not_ready()
        if rejected:
            return rejected
        self.controller.set_mode(mode)
        self.last_command_apply_timestamp = timestamp
        return CommandResult(True, "OK", "mode set", timestamp)

    def set_angle_target(self, yaw_deg: float, pitch_deg: float, timestamp: float) -> CommandResult:
        rejected = self._reject_if_not_ready()
        if rejected:
            return rejected
        self.controller.set_angle_target(yaw_deg, pitch_deg, timestamp)
        self.last_command_apply_timestamp = timestamp
        return CommandResult(True, "OK", "angle target set", timestamp)

    def set_rate_target(self, yaw_rate_dps: float, pitch_rate_dps: float, timestamp: float) -> CommandResult:
        rejected = self._reject_if_not_ready()
        if rejected:
            return rejected
        self.controller.set_rate_target(yaw_rate_dps, pitch_rate_dps, timestamp)
        self.last_command_apply_timestamp = timestamp
        return CommandResult(True, "OK", "rate target set", timestamp)

    def update(self, dt: float, timestamp: float) -> GimbalState:
        if self.power_state == POWER_BOOTING:
            self.boot_remaining_s -= dt
            if self.boot_remaining_s <= 0.0:
                self.power_state = POWER_READY

        if self.power_state == POWER_READY:
            plant_state = self.plant.get_state()
            ctrl = self.controller.step(
                yaw_deg=plant_state.yaw_deg_internal,
                pitch_deg=plant_state.pitch_deg,
                yaw_rate_dps=plant_state.yaw_rate_dps,
                pitch_rate_dps=plant_state.pitch_rate_dps,
                dt=dt,
            )
            self._last_ctrl = ctrl
            plant_state = self.plant.step((ctrl["yaw_rate_cmd_dps"], ctrl["pitch_rate_cmd_dps"]), dt)
        else:
            plant_state = self.plant.get_state()
            ctrl = self._last_ctrl

        return GimbalState(
            timestamp=timestamp,
            power_state=self.power_state,
            mode=self.controller.mode,
            yaw_deg_internal=plant_state.yaw_deg_internal,
            yaw_deg_display=self.wrap_0_360(plant_state.yaw_deg_internal),
            pitch_deg=plant_state.pitch_deg,
            yaw_rate_dps=plant_state.yaw_rate_dps,
            pitch_rate_dps=plant_state.pitch_rate_dps,
            yaw_rate_ref_dps=ctrl["yaw_rate_ref_dps"],
            pitch_rate_ref_dps=ctrl["pitch_rate_ref_dps"],
            angle_tick=bool(ctrl["angle_tick"]),
            rate_tick=bool(ctrl["rate_tick"]),
            last_command_apply_timestamp=self.last_command_apply_timestamp,
        )

    def get_state(self, timestamp: float) -> Dict[str, float | str | bool | None]:
        state = self.update(0.0, timestamp)
        return {
            "timestamp": state.timestamp,
            "power_state": state.power_state,
            "mode": state.mode,
            "yaw_deg_internal": state.yaw_deg_internal,
            "yaw_deg_display": state.yaw_deg_display,
            "pitch_deg": state.pitch_deg,
            "yaw_rate_dps": state.yaw_rate_dps,
            "pitch_rate_dps": state.pitch_rate_dps,
            "yaw_rate_ref_dps": state.yaw_rate_ref_dps,
            "pitch_rate_ref_dps": state.pitch_rate_ref_dps,
            "angle_tick": state.angle_tick,
            "rate_tick": state.rate_tick,
            "last_command_apply_timestamp": state.last_command_apply_timestamp,
        }

    def get_measured_state(self, timestamp: float) -> Dict[str, float]:
        """返回编码器量化后的角度值（不修改内部连续状态）。

        当 encoder_resolution_deg <= 0 时退化为无量化，直接返回连续值。
        """
        state = self.get_state(timestamp)
        res = self.gimbal_cfg.encoder_resolution_deg
        if res <= 0.0:
            return {
                "yaw_deg_internal": state["yaw_deg_internal"],
                "pitch_deg": state["pitch_deg"],
                "yaw_rate_dps": state["yaw_rate_dps"],
                "pitch_rate_dps": state["pitch_rate_dps"],
            }
        return {
            "yaw_deg_internal": round(state["yaw_deg_internal"] / res) * res,
            "pitch_deg": round(state["pitch_deg"] / res) * res,
            "yaw_rate_dps": state["yaw_rate_dps"],
            "pitch_rate_dps": state["pitch_rate_dps"],
        }
