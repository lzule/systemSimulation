from __future__ import annotations

from typing import Callable, Optional

from runtime.types import Command, CommandResult


class RaspiClient:
    def __init__(
        self,
        submit_command: Callable[[Command], None],
        get_state: Callable[[], dict],
        set_delay: Callable[[dict], CommandResult],
        get_delay: Callable[[], dict],
        load_program: Callable[[object], CommandResult],
    ):
        self._submit = submit_command
        self._get_state = get_state
        self._set_delay = set_delay
        self._get_delay = get_delay
        self._load_program = load_program

    def power_on(self, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="raspi", action="power_on", timestamp=timestamp))

    def power_off(self, timestamp: Optional[float] = None) -> None:
        self._submit(Command(target="raspi", action="power_off", timestamp=timestamp))

    def get_state(self) -> dict:
        return self._get_state()

    def set_delay_profile(self, **kwargs) -> CommandResult:
        return self._set_delay(kwargs)

    def get_delay_profile(self) -> dict:
        return self._get_delay()

    def load_control_program(self, program) -> CommandResult:
        return self._load_program(program)

