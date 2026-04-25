from __future__ import annotations

from typing import Callable, Optional

from runtime.types import Command


class GimbalClient:
    def __init__(self, submit_command: Callable[[Command], None], get_state: Callable[[], dict], get_status: Callable[[], dict]):
        self._submit = submit_command
        self._get_state = get_state
        self._get_status = get_status

    def power_on(self, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="gimbal", action="power_on", timestamp=timestamp))

    def power_off(self, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="gimbal", action="power_off", timestamp=timestamp))

    def set_mode(self, mode: str, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="gimbal", action="set_mode", payload={"mode": mode}, timestamp=timestamp))

    def set_angle_target(self, yaw: float, pitch: float, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="gimbal", action="set_angle_target", payload={"yaw": yaw, "pitch": pitch}, timestamp=timestamp))

    def set_rate_target(self, yaw_rate: float, pitch_rate: float, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="gimbal", action="set_rate_target", payload={"yaw_rate": yaw_rate, "pitch_rate": pitch_rate}, timestamp=timestamp))

    def get_state(self) -> dict:
        return self._get_state()

    def get_device_status(self) -> dict:
        return self._get_status()

