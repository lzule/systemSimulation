"""角度模式跟踪器。

使用云台 ANGLE_MODE 输出角度目标命令。
将像素误差转换为角度修正量，直接驱动云台转到目标角度。
仅在 realistic 模式下可用（需要 gimbal 角度反馈）。
"""

from __future__ import annotations

import math
from typing import Optional

from entities.camera.entity import detect_beacon_centroid
from entities.gimbal.control import ANGLE_MODE
from entities.raspi.atp_state_machine import AtpState
from runtime.types import Command


class AngleModeTracker:
    """角度模式跟踪器。

    从 obs["gimbal"] 读取当前角度，将像素误差转换为角度修正量，
    输出 ANGLE_MODE 的角度目标命令。仅适用于 realistic 模式。

    参数:
        angle_kp: 角度修正增益（默认 1.0），乘以角度修正量。
    """

    def __init__(self, tuning: Optional[dict] = None):
        """初始化角度模式跟踪器。

        Args:
            tuning: 自定义参数字典。支持的键：angle_kp（默认 1.0）。
        """
        if tuning is not None:
            self._angle_kp = float(tuning.get("angle_kp", 1.0))
        else:
            self._angle_kp = 1.0

        # 上一帧状态
        self.last_pixel_error_x: float = 0.0
        self.last_pixel_error_y: float = 0.0
        self.last_detection_found: bool = False

    def compute_commands(
        self,
        obs: dict,
        atp_state: AtpState,
        prediction: Optional[tuple[float, float]],
    ) -> list[Command]:
        """计算角度目标命令。

        Args:
            obs: 观测字典，包含 timestamp, frame, gimbal, camera 等。
            atp_state: 当前 ATP 状态。
            prediction: 预测器输出的预测像素位置 (px_x, px_y)，可为 None。

        Returns:
            命令列表。
        """
        timestamp = float(obs.get("timestamp", 0.0))
        commands = []

        # 确保处于 ANGLE_MODE
        gimbal_state = obs.get("gimbal") or {}
        mode = str(gimbal_state.get("mode", ""))
        if mode != ANGLE_MODE:
            commands.append(Command(
                target="gimbal",
                action="set_mode",
                payload={"mode": ANGLE_MODE},
                timestamp=timestamp,
                source="tracker_angle_mode",
            ))

        frame = obs.get("frame")
        if frame is None:
            return commands

        # 读取云台当前角度（realistic 模式提供）
        yaw_deg_internal = gimbal_state.get("yaw_deg_internal")
        pitch_deg = gimbal_state.get("pitch_deg")
        if yaw_deg_internal is None or pitch_deg is None:
            # 无角度反馈，无法计算角度目标，返回空
            return commands

        yaw_deg_internal = float(yaw_deg_internal)
        pitch_deg = float(pitch_deg)

        # 质心检测
        det = detect_beacon_centroid(frame.image)
        self.last_detection_found = bool(det.found)

        if not det.found or det.cx is None:
            # 丢失目标：保持当前角度不变
            return commands

        cx = float(frame.intrinsics["cx"])
        cy = float(frame.intrinsics["cy"])
        f_px = float(frame.intrinsics["f_px"])

        # 确定用于计算误差的位置：优先使用预测值
        if prediction is not None:
            ref_x, ref_y = prediction
        else:
            ref_x, ref_y = float(det.cx), float(det.cy)

        # 像素误差
        pixel_error_x = ref_x - cx
        pixel_error_y = cy - ref_y  # 目标在上方时为正

        # 像素误差 → 角度修正量
        px_per_deg = f_px * (math.pi / 180.0)
        delta_yaw_deg = (pixel_error_x / px_per_deg) * self._angle_kp
        delta_pitch_deg = (pixel_error_y / px_per_deg) * self._angle_kp

        # 计算角度目标
        target_yaw = yaw_deg_internal + delta_yaw_deg
        target_pitch = pitch_deg + delta_pitch_deg

        self.last_pixel_error_x = pixel_error_x
        self.last_pixel_error_y = pixel_error_y

        commands.append(Command(
            target="gimbal",
            action="set_angle_target",
            payload={"yaw": target_yaw, "pitch": target_pitch},
            timestamp=timestamp,
            source="tracker_angle_mode",
        ))
        return commands
