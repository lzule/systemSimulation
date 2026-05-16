"""ATP 控制程序 — 持有 ATP 状态机 + 可插拔 tracker/predictor。

本模块实现 AtpControlProgram 类，是 ATP 算法框架的核心调度器。
根据 ATP 状态机的当前状态，选择不同的控制策略：

- SEARCH / REACQUIRE: 执行光栅扫描（开环速率命令）
- ACQUIRE: 保持当前跟踪但保守（降速）
- TRACK_COARSE / TRACK_FINE: 调用可插拔 tracker 的 compute_commands()
- LOST: 停止速率命令

可插拔组件（鸭子类型协议）：

Tracker 协议:
    compute_commands(obs: dict, atp_state: AtpState, prediction: tuple[float,float]|None) -> list[Command]

Predictor 协议:
    update(obs: dict, detection: Detection|None) -> None
    predict(n_steps: int) -> tuple[float, float] | None
"""

from __future__ import annotations

from typing import Optional

from config import ATPStateMachineConfig
from entities.camera.entity import detect_beacon_centroid
from entities.gimbal.control import RATE_MODE
from entities.raspi.atp_state_machine import AtpState, AtpStateMachine
from runtime.types import Command


class AtpControlProgram:
    """ATP 控制程序，持有状态机 + 可插拔 tracker/predictor。

    本类实现了 ControlProgram 协议（on_tick 方法），可被 RaspiEntity 直接使用。

    Args:
        tracker: 跟踪器实例，必须有 compute_commands(obs, atp_state, prediction) -> list[Command] 方法。
        predictor: 预测器实例（可选），必须有 update(obs, detection) 和 predict(n_steps) 方法。
        config: ATP 状态机配置，为 None 时使用全局默认配置。
    """

    def __init__(
        self,
        tracker=None,
        predictor=None,
        config: Optional[ATPStateMachineConfig] = None,
    ):
        self.state_machine = AtpStateMachine(config)
        self.tracker = tracker
        self.predictor = predictor

        # 上一帧时间戳，用于计算 dt
        self._last_timestamp: Optional[float] = None

        # 上一次发送的模式（避免重复发送 set_mode 命令）
        self._last_gimbal_mode: Optional[str] = None

        # 最近一次发送的速率命令（供 benchmark FrameCollector 采集）
        self.last_yaw_rate_cmd_dps: float = 0.0
        self.last_pitch_rate_cmd_dps: float = 0.0
        self.last_detection_found: bool = False

        # ACQUIRE 模式下的保守速率缩放因子
        self._acquire_rate_scale: float = 0.5

    def on_tick(self, obs: dict) -> list[Command]:
        """每个 tick 调用一次，根据 ATP 状态输出控制命令。

        处理流程：
        1. 从 obs 获取帧数据并执行检测
        2. 计算像素误差
        3. 更新预测器（如有）
        4. 记录检测结果
        5. 推进 ATP 状态机
        6. 根据状态选择控制策略并生成命令

        Args:
            obs: 观测字典，结构见 control_program.ControlProgram 协议说明。

        Returns:
            本 tick 要提交的设备命令列表。
        """
        timestamp = float(obs.get("timestamp", 0.0))

        # 计算 dt
        if self._last_timestamp is None:
            dt = 0.0
        else:
            dt = timestamp - self._last_timestamp
        self._last_timestamp = timestamp

        # === 1. 获取检测结果 ===
        frame = obs.get("frame")
        detection = None
        detection_found = False
        pixel_error = None

        if frame is not None:
            detection = detect_beacon_centroid(frame.image)
            detection_found = bool(detection.found)

            if detection_found and detection.cx is not None and detection.cy is not None:
                cx = float(frame.intrinsics["cx"])
                cy = float(frame.intrinsics["cy"])
                # 像素误差：检测点到画面中心的欧氏距离
                dx = float(detection.cx) - cx
                dy = float(detection.cy) - cy
                pixel_error = (dx * dx + dy * dy) ** 0.5

        # === 2. 更新预测器 ===
        prediction = None
        if self.predictor is not None:
            self.predictor.update(obs, detection)
            prediction = self.predictor.predict(n_steps=3)

        # === 3. 记录检测结果（供 benchmark 采集）===
        self.last_detection_found = detection_found

        # === 4. 更新 ATP 状态机 ===
        atp_state = self.state_machine.update(
            detection_found=detection_found,
            pixel_error=pixel_error,
            dt=dt,
        )

        # === 5. 根据状态生成命令 ===
        commands = self._ensure_rate_mode(obs, timestamp)

        if atp_state == AtpState.SEARCH:
            commands.extend(self._do_search(timestamp))
        elif atp_state == AtpState.ACQUIRE:
            commands.extend(self._do_acquire(obs, timestamp, prediction))
        elif atp_state == AtpState.TRACK_COARSE:
            commands.extend(self._do_track(obs, atp_state, timestamp, prediction))
        elif atp_state == AtpState.TRACK_FINE:
            commands.extend(self._do_track(obs, atp_state, timestamp, prediction))
        elif atp_state == AtpState.LOST:
            commands.extend(self._do_lost(timestamp))
        elif atp_state == AtpState.REACQUIRE:
            commands.extend(self._do_reacquire(timestamp))

        # 记录最近一次速率命令（供 FrameCollector 采集）
        self._record_last_rate(commands)

        return commands

    # === 模式管理 ===

    def _ensure_rate_mode(self, obs: dict, timestamp: float) -> list[Command]:
        """确保云台处于 RATE_MODE，避免重复发送。"""
        if self._last_gimbal_mode == RATE_MODE:
            return []
        gimbal_state = obs.get("gimbal") or {}
        mode = str(gimbal_state.get("mode", ""))
        if mode == RATE_MODE:
            self._last_gimbal_mode = RATE_MODE
            return []
        self._last_gimbal_mode = RATE_MODE
        return [Command(
            target="gimbal",
            action="set_mode",
            payload={"mode": RATE_MODE},
            timestamp=timestamp,
            source="atp_control",
        )]

    # === 各状态的命令生成 ===

    def _do_search(self, timestamp: float) -> list[Command]:
        """SEARCH 状态：光栅扫描，按固定速率旋转。"""
        yaw_rate, pitch_rate = self.state_machine.get_next_search_rate()
        return [Command(
            target="gimbal",
            action="set_rate_target",
            payload={"yaw_rate": yaw_rate, "pitch_rate": pitch_rate},
            timestamp=timestamp,
            source="atp_control",
        )]

    def _do_acquire(self, obs: dict, timestamp: float, prediction) -> list[Command]:
        """ACQUIRE 状态：保守跟踪，降速运行。

        如果有 tracker 且有检出，调用 tracker 但将速率缩放；
        否则发送零速率保持当前姿态。
        """
        if self.tracker is not None:
            cmds = self.tracker.compute_commands(
                obs, AtpState.ACQUIRE, prediction,
            )
            # 保守缩放速率命令
            return self._scale_rate_commands(cmds, self._acquire_rate_scale)
        return [Command(
            target="gimbal",
            action="set_rate_target",
            payload={"yaw_rate": 0.0, "pitch_rate": 0.0},
            timestamp=timestamp,
            source="atp_control",
        )]

    def _do_track(
        self, obs: dict, atp_state: AtpState, timestamp: float, prediction,
    ) -> list[Command]:
        """TRACK_COARSE / TRACK_FINE 状态：调用 tracker 生成跟踪命令。"""
        if self.tracker is not None:
            return self.tracker.compute_commands(obs, atp_state, prediction)
        # 无 tracker 时停止运动
        return [Command(
            target="gimbal",
            action="set_rate_target",
            payload={"yaw_rate": 0.0, "pitch_rate": 0.0},
            timestamp=timestamp,
            source="atp_control",
        )]

    def _do_lost(self, timestamp: float) -> list[Command]:
        """LOST 状态：停止速率命令，等待转入 REACQUIRE。"""
        return [Command(
            target="gimbal",
            action="set_rate_target",
            payload={"yaw_rate": 0.0, "pitch_rate": 0.0},
            timestamp=timestamp,
            source="atp_control",
        )]

    def _do_reacquire(self, timestamp: float) -> list[Command]:
        """REACQUIRE 状态：快速小范围搜索。"""
        yaw_rate, pitch_rate = self.state_machine.get_next_search_rate()
        return [Command(
            target="gimbal",
            action="set_rate_target",
            payload={"yaw_rate": yaw_rate, "pitch_rate": pitch_rate},
            timestamp=timestamp,
            source="atp_control",
        )]

    # === 辅助方法 ===

    @staticmethod
    def _scale_rate_commands(commands: list[Command], scale: float) -> list[Command]:
        """缩放速率命令中的 yaw_rate 和 pitch_rate。"""
        scaled = []
        for cmd in commands:
            if (cmd.target == "gimbal"
                    and cmd.action == "set_rate_target"
                    and cmd.payload):
                new_payload = dict(cmd.payload)
                if "yaw_rate" in new_payload:
                    new_payload["yaw_rate"] *= scale
                if "pitch_rate" in new_payload:
                    new_payload["pitch_rate"] *= scale
                scaled.append(Command(
                    target=cmd.target,
                    action=cmd.action,
                    payload=new_payload,
                    timestamp=cmd.timestamp,
                    source=cmd.source,
                ))
            else:
                scaled.append(cmd)
        return scaled

    def _record_last_rate(self, commands: list[Command]) -> None:
        """从命令列表中提取最后的速率命令值，供外部采集。"""
        for cmd in reversed(commands):
            if (cmd.target == "gimbal"
                    and cmd.action == "set_rate_target"
                    and cmd.payload):
                self.last_yaw_rate_cmd_dps = float(cmd.payload.get("yaw_rate", 0.0))
                self.last_pitch_rate_cmd_dps = float(cmd.payload.get("pitch_rate", 0.0))
                return
