from __future__ import annotations

from typing import Callable, Optional

from runtime.types import Command


class CameraClient:
    def __init__(self, submit_command: Callable[[Command], None], get_state: Callable[[], dict], get_frame: Callable[[], object]):
        self._submit = submit_command
        self._get_state = get_state
        self._get_frame = get_frame

    def power_on(self, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="camera", action="power_on", timestamp=timestamp))

    def power_off(self, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="camera", action="power_off", timestamp=timestamp))

    def set_zoom_target_mm(self, f_mm: float, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="camera", action="set_zoom_target_mm", payload={"f_mm": f_mm}, timestamp=timestamp))

    def zoom_by(self, delta_mm: float, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="camera", action="zoom_by", payload={"delta_mm": delta_mm}, timestamp=timestamp))

    def set_zoom_rate_mmps(self, rate_mmps: float, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="camera", action="set_zoom_rate_mmps", payload={"rate_mmps": rate_mmps}, timestamp=timestamp))

    def get_camera_state(self) -> dict:
        return self._get_state()

    def get_frame(self):
        return self._get_frame()

