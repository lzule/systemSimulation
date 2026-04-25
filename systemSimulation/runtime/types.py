from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


# === 合法 Command target + action 组合 ===

GIMBAL_COMMANDS = {
    "power_on": "上电",
    "power_off": "关电",
    "set_mode": "设置模式（payload: {mode: ANGLE_MODE|RATE_MODE}）",
    "set_angle_target": "设角度目标（payload: {yaw: deg, pitch: deg}）",
    "set_rate_target": "设角速度目标（payload: {yaw_rate: dps, pitch_rate: dps}）",
}

CAMERA_COMMANDS = {
    "power_on": "上电",
    "power_off": "关电",
    "set_zoom_target_mm": "设焦距目标（payload: {f_mm: float}）",
    "zoom_by": "相对变焦（payload: {delta_mm: float}）",
    "set_zoom_rate_mmps": "恒速变焦（payload: {rate_mmps: float}）",
}

RASPI_COMMANDS = {
    "power_on": "上电",
    "power_off": "关电",
}

ALL_COMMANDS = {
    "gimbal": GIMBAL_COMMANDS,
    "camera": CAMERA_COMMANDS,
    "raspi": RASPI_COMMANDS,
}


# === 电源状态常量 ===

POWER_OFF = "OFF"
POWER_BOOTING = "BOOTING"
POWER_READY = "READY"
POWER_FAULT = "FAULT"


def wrap_pm180(angle_deg: float) -> float:
    """将角度归一化到 [-180, 180) 区间。"""
    return (angle_deg + 180.0) % 360.0 - 180.0


# === 核心类型 ===

@dataclass
class CommandResult:
    accepted: bool
    code: str
    message: str
    applied_timestamp: Optional[float] = None


@dataclass
class Command:
    target: str       # "gimbal" | "camera" | "raspi"，合法组合见 ALL_COMMANDS
    action: str       # 具体动作，见 GIMBAL_COMMANDS / CAMERA_COMMANDS / RASPI_COMMANDS
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[float] = None
    source: str = "external"


@dataclass
class Detection:
    found: bool
    cx: Optional[float] = None
    cy: Optional[float] = None
    confidence: float = 0.0


@dataclass
class FramePacket:
    timestamp: float
    image: np.ndarray        # 灰度图像 (H, W) uint8
    intrinsics: Dict[str, float]  # f_mm, f_px, cx, cy, width, height
    optional_gt: Optional[Dict[str, float]] = None  # u_px, v_px, in_fov


@dataclass
class WorldSnapshot:
    timestamp: float
    target: Dict[str, Any]   # x_m, y_m, bearing_deg, distance_m, vx_mps, vy_mps
    gimbal: Dict[str, Any]   # power_state, mode, yaw_deg_internal, yaw_deg_display, pitch_deg,
                             # yaw_rate_dps, pitch_rate_dps, yaw_rate_ref_dps, angle_tick, rate_tick
    camera: Dict[str, Any]   # power_state, f_current_mm, f_target_mm, frame_id, in_fov, u_px, v_px
    raspi: Dict[str, Any]    # power_state, effective_obs_timestamp, pipeline_backlog_len,
                             # last_process_latency_s, delay_metrics

