from __future__ import annotations

from typing import Callable


class TargetClient:
    def __init__(self, get_state: Callable[[], dict]):
        self._get_state = get_state

    def get_state(self) -> dict:
        return self._get_state()

