from __future__ import annotations


class RaspiDelayModel:
    """单槽忙/闲延迟模型：Pi 空闲时抓取最新帧开始处理，忙时跳过，不排队旧帧。"""

    IDLE = 0
    READING = 1      # 正在读取观测（obs_read 延迟）
    PROCESSING = 2   # 正在处理图像（image_process 延迟）
    SENDING = 3      # 正在发送命令（command_tx 延迟）

    def __init__(self):
        self.state = self.IDLE
        self.ready_at = 0.0
        self._pending_obs = None
        self._obs_capture_ts = 0.0

    def reset(self) -> None:
        self.state = self.IDLE
        self.ready_at = 0.0
        self._pending_obs = None
        self._obs_capture_ts = 0.0

    def try_start(self, timestamp: float, world_obs: dict, obs_read_delay: float) -> bool:
        """空闲时抓取最新帧，进入 READING 阶段。忙时返回 False。"""
        if self.state != self.IDLE:
            return False
        self._pending_obs = world_obs
        self._obs_capture_ts = timestamp
        self.state = self.READING
        self.ready_at = timestamp + obs_read_delay
        return True

    def tick(self, timestamp: float, process_delay: float, cmd_tx_delay: float,
             control_program, jitter_fn) -> list[tuple[float, list]]:
        """推进状态机。返回 [(obs_capture_ts, cmds), ...]"""
        results = []

        if self.state == self.READING and timestamp >= self.ready_at:
            self.state = self.PROCESSING
            self.ready_at = timestamp + process_delay + jitter_fn()

        if self.state == self.PROCESSING and timestamp >= self.ready_at:
            cmds = control_program.on_tick(self._pending_obs)
            self.state = self.SENDING
            self.ready_at = timestamp + cmd_tx_delay + jitter_fn()
            results.append((self._obs_capture_ts, cmds))

        if self.state == self.SENDING and timestamp >= self.ready_at:
            self.state = self.IDLE
            self._pending_obs = None

        return results

    def is_busy(self) -> bool:
        return self.state != self.IDLE
