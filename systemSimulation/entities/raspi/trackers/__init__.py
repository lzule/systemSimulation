"""跟踪器包。

Tracker 协议（鸭子类型）:
    compute_commands(obs: dict, atp_state: AtpState, prediction: tuple[float,float]|None) -> list[Command]

可用跟踪器：
    RatePTracker       — 速率P控制器
    RatePITracker      — 速率PI控制器（P + 积分项）
    AngleModeTracker   — 角度模式控制器（直接输出角度目标）
"""

from entities.raspi.trackers.rate_p_tracker import RatePTracker
from entities.raspi.trackers.rate_pi_tracker import RatePITracker
from entities.raspi.trackers.angle_mode_tracker import AngleModeTracker

__all__ = [
    "RatePTracker",
    "RatePITracker",
    "AngleModeTracker",
]
