from __future__ import annotations

from collections import deque


class RaspiDelayModel:
    """延迟模型：支持 latest（单槽抓最新帧）和 fifo（有限队列）两种缓冲策略。

    latest 模式：空闲时抓取最新帧开始处理，忙时丢弃新帧（当前默认行为）。
    fifo 模式：空闲时入队新观测，队列满时丢弃最旧帧；状态机空闲后从队列取下一帧处理。
    """

    IDLE = 0
    READING = 1      # 正在读取观测（obs_read 延迟）
    PROCESSING = 2   # 正在处理图像（image_process 延迟）
    SENDING = 3      # 正在发送命令（command_tx 延迟）

    def __init__(self, buffer_policy: str = "latest", queue_capacity: int = 1):
        if buffer_policy not in ("latest", "fifo"):
            raise ValueError(f"未知缓冲策略: {buffer_policy!r}，可选: latest / fifo")
        self.buffer_policy = buffer_policy
        self.queue_capacity = max(1, queue_capacity)
        self.state = self.IDLE
        self.ready_at = 0.0
        self._pending_obs = None
        self._obs_capture_ts = 0.0
        # fifo 模式的缓冲队列
        self._obs_queue: deque = deque()

    def reset(self) -> None:
        self.state = self.IDLE
        self.ready_at = 0.0
        self._pending_obs = None
        self._obs_capture_ts = 0.0
        self._obs_queue.clear()

    def try_start(self, timestamp: float, world_obs: dict, obs_read_delay: float) -> bool:
        """尝试接收新观测。

        latest 模式：空闲时抓取最新帧进入 READING，忙时返回 False。
        fifo 模式：空闲时入队并立即进入 READING；忙时入队缓冲，队列满时丢弃最旧帧。
        """
        if self.buffer_policy == "fifo":
            if self.state == self.IDLE:
                # 先检查队列中是否有积压的观测，如果有就先处理积压
                if self._obs_queue:
                    self._pending_obs, self._obs_capture_ts = self._obs_queue.popleft()
                else:
                    self._pending_obs = world_obs
                    self._obs_capture_ts = timestamp
                self.state = self.READING
                self.ready_at = timestamp + obs_read_delay
                return True
            else:
                # 忙时入队缓冲；队列满时丢弃最旧帧
                self._obs_queue.append((world_obs, timestamp))
                while len(self._obs_queue) > self.queue_capacity:
                    self._obs_queue.popleft()
                return False
        else:
            # latest 模式：保持原有单槽行为
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

    @property
    def queue_len(self) -> int:
        """当前缓冲队列中的积压观测数量。"""
        return len(self._obs_queue)
