"""速率PI控制器跟踪器。

在 RatePTracker 基础上加入积分项，用于消除稳态误差。
维护误差积分，输出速率 = kp * error + ki * integral。
"""

from __future__ import annotations

from typing import Optional

from config import tracker_tuning_cfg
from entities.camera.entity import detect_beacon_centroid
from entities.gimbal.control import RATE_MODE
from entities.raspi.atp_state_machine import AtpState
from runtime.types import Command


class RatePITracker:
    """速率PI控制器跟踪器。

    在 P 控制基础上增加积分项，消除目标持续偏移导致的稳态误差。
    积分项做抗饱和限幅，丢失目标时清零积分。
    """

    def __init__(self, tuning: Optional[dict] = None):
        """初始化速率PI控制器。

        Args:
            tuning: 自定义参数字典，覆盖全局默认值。为 None 时使用 tracker_tuning_cfg。
                支持的键：yaw_rate_kp_dps_per_px, max_yaw_rate_dps, deadband_px,
                          lost_target_hold_rate_dps, pitch_rate_kp_dps_per_px,
                          max_pitch_rate_dps, deadband_v_px,
                          yaw_rate_ki_dps_per_px, pitch_rate_ki_dps_per_px,
                          integral_limit。
        """
        if tuning is not None:
            self._kp_yaw = float(tuning.get("yaw_rate_kp_dps_per_px", tracker_tuning_cfg.yaw_rate_kp_dps_per_px))
            self._max_yaw = float(tuning.get("max_yaw_rate_dps", tracker_tuning_cfg.max_yaw_rate_dps))
            self._deadband_x = float(tuning.get("deadband_px", tracker_tuning_cfg.deadband_px))
            self._hold_rate = float(tuning.get("lost_target_hold_rate_dps", tracker_tuning_cfg.lost_target_hold_rate_dps))
            self._kp_pitch = float(tuning.get("pitch_rate_kp_dps_per_px", tracker_tuning_cfg.pitch_rate_kp_dps_per_px))
            self._max_pitch = float(tuning.get("max_pitch_rate_dps", tracker_tuning_cfg.max_pitch_rate_dps))
            self._deadband_y = float(tuning.get("deadband_v_px", tracker_tuning_cfg.deadband_v_px))
            self._ki_yaw = float(tuning.get("yaw_rate_ki_dps_per_px", 0.1))
            self._ki_pitch = float(tuning.get("pitch_rate_ki_dps_per_px", 0.1))
            self._integral_limit = float(tuning.get("integral_limit", 30.0))
        else:
            self._kp_yaw = tracker_tuning_cfg.yaw_rate_kp_dps_per_px
            self._max_yaw = tracker_tuning_cfg.max_yaw_rate_dps
            self._deadband_x = tracker_tuning_cfg.deadband_px
            self._hold_rate = tracker_tuning_cfg.lost_target_hold_rate_dps
            self._kp_pitch = tracker_tuning_cfg.pitch_rate_kp_dps_per_px
            self._max_pitch = tracker_tuning_cfg.max_pitch_rate_dps
            self._deadband_y = tracker_tuning_cfg.deadband_v_px
            self._ki_yaw = 0.1
            self._ki_pitch = 0.1
            self._integral_limit = 30.0

        # 积分状态
        self._integral_x: float = 0.0
        self._integral_y: float = 0.0

        # 上一帧时间戳，用于计算 dt
        self._last_timestamp: Optional[float] = None

        # 上一帧状态
        self.last_pixel_error_x: float = 0.0
        self.last_pixel_error_y: float = 0.0
        self.last_detection_found: bool = False

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        """限幅。"""
        return max(low, min(high, value))

    def _ensure_rate_mode(self, obs: dict, timestamp: float) -> list[Command]:
        """确保云台处于 RATE_MODE，否则发送切换命令。"""
        gimbal_state = obs.get("gimbal") or {}
        mode = str(gimbal_state.get("mode", ""))
        if mode == RATE_MODE:
            return []
        return [Command(
            target="gimbal",
            action="set_mode",
            payload={"mode": RATE_MODE},
            timestamp=timestamp,
            source="tracker_rate_pi",
        )]

    def compute_commands(
        self,
        obs: dict,
        atp_state: AtpState,
        prediction: Optional[tuple[float, float]],
    ) -> list[Command]:
        """计算速率命令（含积分项）。

        Args:
            obs: 观测字典，包含 timestamp, frame, gimbal, camera 等。
            atp_state: 当前 ATP 状态。
            prediction: 预测器输出的预测像素位置 (px_x, px_y)，可为 None。

        Returns:
            命令列表。
        """
        timestamp = float(obs.get("timestamp", 0.0))
        commands = self._ensure_rate_mode(obs, timestamp)

        # 计算 dt
        if self._last_timestamp is not None:
            dt = timestamp - self._last_timestamp
            dt = max(dt, 1e-6)  # 防止 dt 为零或负数
        else:
            dt = 0.0  # 首帧不累加积分
        self._last_timestamp = timestamp

        frame = obs.get("frame")
        if frame is None:
            return commands

        # 质心检测
        det = detect_beacon_centroid(frame.image)
        self.last_detection_found = bool(det.found)

        if not det.found or det.cx is None:
            # 丢失目标：输出 hold_rate，清零积分
            yaw_rate = self._hold_rate
            pitch_rate = self._hold_rate
            self._integral_x = 0.0
            self._integral_y = 0.0
        else:
            cx = float(frame.intrinsics["cx"])
            cy = float(frame.intrinsics["cy"])

            # 确定用于计算误差的位置：优先使用预测值
            if prediction is not None:
                ref_x, ref_y = prediction
            else:
                ref_x, ref_y = float(det.cx), float(det.cy)

            # 水平像素误差
            pixel_error_x = ref_x - cx
            if abs(pixel_error_x) < self._deadband_x:
                pixel_error_x = 0.0

            # 垂直像素误差：cy - ref_y，目标在上方时为正
            pixel_error_y = cy - ref_y
            if abs(pixel_error_y) < self._deadband_y:
                pixel_error_y = 0.0

            # 累加积分（仅在有有效 dt 时）
            if dt > 0.0:
                self._integral_x += pixel_error_x * dt
                self._integral_y += pixel_error_y * dt

            # 积分限幅（抗饱和）
            self._integral_x = self._clamp(self._integral_x, -self._integral_limit, self._integral_limit)
            self._integral_y = self._clamp(self._integral_y, -self._integral_limit, self._integral_limit)

            # PI控制：rate = kp * error + ki * integral
            yaw_rate = self._clamp(
                self._kp_yaw * pixel_error_x + self._ki_yaw * self._integral_x,
                -self._max_yaw, self._max_yaw,
            )
            pitch_rate = self._clamp(
                self._kp_pitch * pixel_error_y + self._ki_pitch * self._integral_y,
                -self._max_pitch, self._max_pitch,
            )

            self.last_pixel_error_x = pixel_error_x
            self.last_pixel_error_y = pixel_error_y

        commands.append(Command(
            target="gimbal",
            action="set_rate_target",
            payload={"yaw_rate": yaw_rate, "pitch_rate": pitch_rate},
            timestamp=timestamp,
            source="tracker_rate_pi",
        ))
        return commands
