from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from entities.camera.entity import detect_beacon_centroid
from entities.gimbal.control import RATE_MODE
from runtime.types import Command


@dataclass(frozen=True)
class TrackerTuning:
    """基线跟踪参数（可按项目需求替换）。"""

    yaw_rate_kp_dps_per_px: float = 0.08
    max_yaw_rate_dps: float = 60.0
    deadband_px: float = 2.0
    lost_target_hold_rate_dps: float = 0.0

    enable_zoom_control: bool = False
    zoom_in_error_px: float = 40.0
    zoom_out_error_px: float = 120.0
    zoom_step_mm: float = 1.0
    zoom_cooldown_s: float = 0.15


class BaselineTrackerProgram:
    """Raspi 侧可复用跟踪控制模板。

    处理流程：
    1. 从 `obs` 中读取 `frame`，检测目标质心。
    2. 计算像素误差 `pixel_error_x = u - cx`。
    3. 比例映射为 yaw 角速度命令，并做限幅。
    4. 输出云台命令；可选附加相机变焦命令。

    说明：
    - 命令中的 timestamp 使用观测时间戳。
    - runtime 采用 latest-wins，命令在下一 tick 生效。
    """

    def __init__(self, tuning: Optional[TrackerTuning] = None):
        self.tuning = tuning or TrackerTuning()
        self.last_pixel_error_x: float = 0.0
        self.last_detection_found: bool = False
        self.last_yaw_rate_cmd_dps: float = 0.0
        self._last_zoom_cmd_ts: float = -1e9

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _build_mode_command_if_needed(self, obs: dict, timestamp: float) -> list[Command]:
        gimbal_state = obs.get("gimbal") or {}
        mode = str(gimbal_state.get("mode", ""))
        if mode == RATE_MODE:
            return []
        return [Command(target="gimbal", action="set_mode", payload={"mode": RATE_MODE}, timestamp=timestamp, source="raspi_tracker")]

    def _build_zoom_command(self, obs: dict, pixel_error_x: float, timestamp: float) -> list[Command]:
        if not self.tuning.enable_zoom_control:
            return []
        if timestamp - self._last_zoom_cmd_ts < self.tuning.zoom_cooldown_s:
            return []

        camera_state = obs.get("camera") or {}
        f_current_mm = float(camera_state.get("f_current_mm", 12.0))
        f_target_mm = f_current_mm

        abs_err = abs(pixel_error_x)
        if abs_err < self.tuning.zoom_in_error_px:
            f_target_mm = f_current_mm + self.tuning.zoom_step_mm
        elif abs_err > self.tuning.zoom_out_error_px:
            f_target_mm = f_current_mm - self.tuning.zoom_step_mm

        if f_target_mm == f_current_mm:
            return []

        self._last_zoom_cmd_ts = timestamp
        return [
            Command(
                target="camera",
                action="set_zoom_target_mm",
                payload={"f_mm": f_target_mm},
                timestamp=timestamp,
                source="raspi_tracker",
            )
        ]

    def on_tick(self, obs: dict) -> list[Command]:
        timestamp = float(obs.get("timestamp", 0.0))
        commands = self._build_mode_command_if_needed(obs, timestamp)

        frame = obs.get("frame")
        if frame is None:
            return commands

        det = detect_beacon_centroid(frame.image)
        self.last_detection_found = bool(det.found)
        if not det.found or det.cx is None:
            yaw_rate_cmd_dps = self.tuning.lost_target_hold_rate_dps
            pixel_error_x = self.last_pixel_error_x
        else:
            cx = float(frame.intrinsics["cx"])
            pixel_error_x = float(det.cx) - cx
            if abs(pixel_error_x) < self.tuning.deadband_px:
                pixel_error_x = 0.0
            yaw_rate_cmd_dps = self.tuning.yaw_rate_kp_dps_per_px * pixel_error_x
            yaw_rate_cmd_dps = self._clamp(yaw_rate_cmd_dps, -self.tuning.max_yaw_rate_dps, self.tuning.max_yaw_rate_dps)

        self.last_pixel_error_x = pixel_error_x
        self.last_yaw_rate_cmd_dps = yaw_rate_cmd_dps

        commands.append(
            Command(
                target="gimbal",
                action="set_rate_target",
                payload={"yaw_rate": yaw_rate_cmd_dps, "pitch_rate": 0.0},
                timestamp=timestamp,
                source="raspi_tracker",
            )
        )
        commands.extend(self._build_zoom_command(obs, pixel_error_x, timestamp))
        return commands
