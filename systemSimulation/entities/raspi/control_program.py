from __future__ import annotations

from typing import Protocol

from runtime.types import Command


class ControlProgram(Protocol):
    """Raspi 控制程序协议。

    输入:
    - `obs`: runtime 在本 tick 传入的观测字典，结构:
        {
            "timestamp": float,             # 仿真时间
            "target": {
                "x_m": float, "y_m": float, # 目标位置（米）
                "bearing_deg": float,        # 方位角
                "distance_m": float,         # 距离
                "vx_mps": float, "vy_mps": float,  # 速度
            },
            "gimbal": {
                "power_state": str,          # OFF / BOOTING / READY
                "mode": str,                 # ANGLE_MODE / RATE_MODE
                "yaw_deg_internal": float,    # Yaw 内部角度（连续）
                "yaw_deg_display": float,     # Yaw 显示角度 [0, 360)
                "pitch_deg": float,           # Pitch 角度
                "yaw_rate_dps": float,        # Yaw 实际角速度
                "pitch_rate_dps": float,      # Pitch 实际角速度
            },
            "camera": {
                "f_current_mm": float,        # 当前焦距
                "frame_id": int,              # 帧号
                "in_fov": bool,               # 目标是否在视场内
                "u_px": float, "v_px": float, # 目标像素坐标（NaN=不在视场内）
            },
            "frame": FramePacket | None,     # 渲染帧（image, intrinsics, optional_gt）
        }
      详细字段见 runtime.types.WorldSnapshot。

    输出:
    - `list[Command]`: 本 tick 要提交的设备命令列表。
      合法命令见 runtime.types.ALL_COMMANDS。

    语义:
    - runtime 内部采用设备内 latest-wins 命令仲裁。
    - 命令通常在下一 tick 生效（或按 timestamp 调度）。
    """

    def on_tick(self, obs: dict) -> list[Command]:
        ...


class NoopControlProgram:
    """空控制程序：不输出任何控制命令。"""

    def on_tick(self, obs: dict) -> list[Command]:
        return []

