"""ATP（捕获-跟踪-保持）状态机。

定义云台 ATP 全流程的状态转换逻辑，包括搜索、捕获、粗跟踪、精跟踪、
丢失和重捕获六个核心状态。本模块仅负责状态转换，不直接发送设备命令。

状态转移图::

    SEARCH ──n_detect_enter帧检出──▶ ACQUIRE
    ACQUIRE ──n_acquire_confirm帧确认──▶ TRACK_COARSE
    TRACK_COARSE ──n_fine_enter帧低误差──▶ TRACK_FINE
    TRACK_COARSE ──n_lost_enter帧丢失──▶ LOST
    TRACK_FINE ──n_lost_enter帧丢失──▶ LOST
    LOST ──立即──▶ REACQUIRE
    REACQUIRE ──n_detect_enter帧检出──▶ ACQUIRE
    REACQUIRE ──超时──▶ SEARCH
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from config import ATPStateMachineConfig, atp_sm_cfg


class AtpState(Enum):
    """ATP 状态枚举。"""
    SEARCH = "SEARCH"               # 搜索：大范围光栅扫描
    ACQUIRE = "ACQUIRE"             # 捕获：确认目标存在
    TRACK_COARSE = "TRACK_COARSE"   # 粗跟踪：误差较大
    TRACK_FINE = "TRACK_FINE"       # 精跟踪：误差已收敛
    LOST = "LOST"                   # 丢失：目标暂时丢失
    REACQUIRE = "REACQUIRE"         # 重捕获：快速小范围搜索


class AtpStateMachine:
    """ATP 状态机，纯状态转换逻辑。

    不直接发送设备命令，由上层 AtpControlProgram 根据状态决定具体动作。

    Args:
        config: 状态机配置，为 None 时使用全局默认配置。
    """

    def __init__(self, config: Optional[ATPStateMachineConfig] = None):
        self._cfg = config or atp_sm_cfg
        self._state = AtpState.SEARCH

        # 连续帧计数器
        self._consecutive_detect: int = 0       # 连续检出帧数
        self._consecutive_lost: int = 0         # 连续丢失帧数
        self._consecutive_low_error: int = 0    # 连续低误差帧数

        # REACQUIRE 超时计时
        self._reacquire_elapsed_s: float = 0.0

        # 搜索扫描状态（光栅扫描位置追踪）
        self._search_yaw_deg: float = 0.0
        self._search_pitch_deg: float = 0.0
        self._search_yaw_direction: int = 1      # 1=正向，-1=反向
        self._search_pitch_direction: int = 1
        self._search_dwell_count: int = 0         # 当前步驻留计数
        self._search_pitch_stepping: int = 0      # pitch 步进剩余帧数

        # 上一次 update 的像素误差（供外部查询）
        self._last_pixel_error: Optional[float] = None

    @property
    def state(self) -> AtpState:
        """当前 ATP 状态。"""
        return self._state

    @property
    def last_pixel_error(self) -> Optional[float]:
        """最近一次 update 的像素误差（None 表示无有效检测）。"""
        return self._last_pixel_error

    def update(
        self,
        detection_found: bool,
        pixel_error: Optional[float],
        dt: float,
    ) -> AtpState:
        """根据检测结果和像素误差推进状态机。

        Args:
            detection_found: 本帧是否检测到目标。
            pixel_error: 像素误差（到画面中心的距离），None 表示无有效检测。
            dt: 本帧与上一帧的时间间隔（秒）。

        Returns:
            当前（可能已更新的）ATP 状态。
        """
        self._last_pixel_error = pixel_error if detection_found else None

        # 更新连续计数器
        if detection_found:
            self._consecutive_detect += 1
            self._consecutive_lost = 0
        else:
            self._consecutive_detect = 0
            self._consecutive_lost += 1

        # 计算像素误差是否足够小（仅在有检测时判定）
        if detection_found and pixel_error is not None:
            if pixel_error < self._cfg.coarse_error_threshold_px:
                self._consecutive_low_error += 1
            else:
                self._consecutive_low_error = 0
        else:
            self._consecutive_low_error = 0

        # 根据当前状态执行转移（瞬态如 LOST 会在同一 tick 内级联转移）
        max_iterations = 5  # 防止意外无限循环
        for _ in range(max_iterations):
            old_state = self._state
            self._dispatch_transition(dt)
            if self._state == old_state:
                break
            # 状态发生变化，执行回调
            self._on_state_changed(old_state, self._state)

        return self._state

    def _dispatch_transition(self, dt: float) -> None:
        """根据当前状态判定并执行状态转移。"""
        if self._state == AtpState.SEARCH:
            self._transition_from_search()
        elif self._state == AtpState.ACQUIRE:
            self._transition_from_acquire()
        elif self._state == AtpState.TRACK_COARSE:
            self._transition_from_track_coarse()
        elif self._state == AtpState.TRACK_FINE:
            self._transition_from_track_fine()
        elif self._state == AtpState.LOST:
            self._transition_from_lost(dt)
        elif self._state == AtpState.REACQUIRE:
            self._transition_from_reacquire(dt)

    # === 各状态的转移逻辑 ===

    def _transition_from_search(self) -> None:
        """SEARCH: 连续 n_detect_enter 帧检出 → ACQUIRE。"""
        if self._consecutive_detect >= self._cfg.n_detect_enter:
            self._state = AtpState.ACQUIRE

    def _transition_from_acquire(self) -> None:
        """ACQUIRE: 连续 n_acquire_confirm 帧确认且误差有效 → TRACK_COARSE；
                    连续 n_lost_enter 帧丢失 → LOST。"""
        if self._consecutive_lost >= self._cfg.n_lost_enter:
            self._state = AtpState.LOST
        elif self._consecutive_detect >= self._cfg.n_acquire_confirm:
            # 检出足够多帧且像素误差有效（由 _consecutive_detect 保证连续检出）
            self._state = AtpState.TRACK_COARSE

    def _transition_from_track_coarse(self) -> None:
        """TRACK_COARSE: 连续 n_fine_enter 帧低误差 → TRACK_FINE；
                         连续 n_lost_enter 帧丢失 → LOST。"""
        if self._consecutive_lost >= self._cfg.n_lost_enter:
            self._state = AtpState.LOST
        elif self._consecutive_low_error >= self._cfg.n_fine_enter:
            self._state = AtpState.TRACK_FINE

    def _transition_from_track_fine(self) -> None:
        """TRACK_FINE: 连续 n_lost_enter 帧丢失 → LOST。"""
        if self._consecutive_lost >= self._cfg.n_lost_enter:
            self._state = AtpState.LOST

    def _transition_from_lost(self, dt: float) -> None:
        """LOST: 失锁后立即转入 REACQUIRE（同一 tick 内完成）。"""
        # LOST 是瞬态，在 _on_state_changed 之后的下一个 dispatch 周期
        # 不会被单独看到——这里直接转到 REACQUIRE
        self._state = AtpState.REACQUIRE
        self._reacquire_elapsed_s = 0.0
        self._reset_search()

    def _transition_from_reacquire(self, dt: float) -> None:
        """REACQUIRE: 连续 n_detect_enter 帧重新检出 → ACQUIRE；
                       超时 → SEARCH。"""
        self._reacquire_elapsed_s += dt
        if self._consecutive_detect >= self._cfg.n_detect_enter:
            self._state = AtpState.ACQUIRE
        elif self._reacquire_elapsed_s >= self._cfg.reacquire_timeout_s:
            self._state = AtpState.SEARCH

    # === 状态变化回调 ===

    def _on_state_changed(self, old_state: AtpState, new_state: AtpState) -> None:
        """状态变化时重置相关计数器。"""
        if new_state == AtpState.SEARCH:
            self._reset_search()
        elif new_state == AtpState.REACQUIRE:
            self._reacquire_elapsed_s = 0.0
            self._reset_search()
        elif new_state == AtpState.ACQUIRE:
            # 检出计数器保留（用于 TRACK_COARSE 的连续确认）
            pass
        elif new_state == AtpState.TRACK_COARSE:
            self._consecutive_low_error = 0

    # === 搜索扫描状态管理 ===

    def _reset_search(self) -> None:
        """重置搜索扫描位置。"""
        self._search_yaw_deg = 0.0
        self._search_pitch_deg = 0.0
        self._search_yaw_direction = 1
        self._search_pitch_direction = 1
        self._search_dwell_count = 0
        self._search_pitch_stepping = 0

    def get_next_search_rate(self) -> tuple[float, float]:
        """获取搜索/重捕获模式下的角速度命令。

        使用光栅扫描策略：先沿 yaw 方向往返扫描，到达边界后 pitch 步进一层，
        然后 yaw 反向继续扫描。pitch 步进通过发送固定帧数的 pitch_rate 脉冲实现。

        Returns:
            (yaw_rate_dps, pitch_rate_dps) 搜索角速度命令。
        """
        if self._state == AtpState.REACQUIRE:
            rate = self._cfg.reacquire_search_rate_dps
            step = self._cfg.reacquire_search_step_deg
        else:
            rate = self._cfg.search_rate_dps
            step = self._cfg.search_step_deg

        # pitch 步进中：发送 pitch_rate 直到步进完成
        if self._search_pitch_stepping > 0:
            self._search_pitch_stepping -= 1
            pitch_rate = rate * 0.3 * self._search_pitch_direction
            return (0.0, pitch_rate)

        # 当前 yaw 步驻留未完成，继续发送同方向速率
        if self._search_dwell_count < self._cfg.search_dwell_frames:
            self._search_dwell_count += 1
            yaw_rate = rate * self._search_yaw_direction
            return (yaw_rate, 0.0)

        # 驻留完成，推进 yaw 位置
        self._search_dwell_count = 0
        self._search_yaw_deg += step * self._search_yaw_direction

        # yaw 到达边界，反向并启动 pitch 步进
        if abs(self._search_yaw_deg) >= self._cfg.search_yaw_range_deg:
            self._search_yaw_direction *= -1
            self._search_pitch_deg += step * self._search_pitch_direction

            # pitch 到达边界，反向
            if abs(self._search_pitch_deg) >= self._cfg.search_pitch_range_deg:
                self._search_pitch_direction *= -1

            # 启动 pitch 步进：用 search_dwell_frames 帧发送 pitch_rate
            self._search_pitch_stepping = self._cfg.search_dwell_frames

        # 如果刚启动了 pitch 步进，本帧开始步进
        if self._search_pitch_stepping > 0:
            self._search_pitch_stepping -= 1
            pitch_rate = rate * 0.3 * self._search_pitch_direction
            return (0.0, pitch_rate)

        yaw_rate = rate * self._search_yaw_direction
        return (yaw_rate, 0.0)

    def reset(self) -> None:
        """将状态机重置为初始 SEARCH 状态。"""
        self._state = AtpState.SEARCH
        self._consecutive_detect = 0
        self._consecutive_lost = 0
        self._consecutive_low_error = 0
        self._reacquire_elapsed_s = 0.0
        self._last_pixel_error = None
        self._reset_search()
