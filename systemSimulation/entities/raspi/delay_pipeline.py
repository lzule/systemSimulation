from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any, List, Tuple


@dataclass
class ScheduledItem:
    available_at: float
    payload: Any


class DelayPipeline:
    def __init__(self):
        self._obs_heap: List[Tuple[float, int, Any]] = []
        self._proc_heap: List[Tuple[float, int, Any]] = []
        self._cmd_heap: List[Tuple[float, int, Any]] = []
        self._seq = 0

    def _push(self, heap: list, available_at: float, payload: Any) -> None:
        self._seq += 1
        heapq.heappush(heap, (available_at, self._seq, payload))

    def push_obs(self, available_at: float, payload: Any) -> None:
        self._push(self._obs_heap, available_at, payload)

    def push_proc(self, available_at: float, payload: Any) -> None:
        self._push(self._proc_heap, available_at, payload)

    def push_cmd(self, available_at: float, payload: Any) -> None:
        self._push(self._cmd_heap, available_at, payload)

    def pop_ready_obs(self, now: float) -> list[Any]:
        items = []
        while self._obs_heap and self._obs_heap[0][0] <= now:
            items.append(heapq.heappop(self._obs_heap)[2])
        return items

    def pop_ready_proc(self, now: float) -> list[Any]:
        items = []
        while self._proc_heap and self._proc_heap[0][0] <= now:
            items.append(heapq.heappop(self._proc_heap)[2])
        return items

    def pop_ready_cmd(self, now: float) -> list[Any]:
        items = []
        while self._cmd_heap and self._cmd_heap[0][0] <= now:
            items.append(heapq.heappop(self._cmd_heap)[2])
        return items

    def backlog_len(self) -> int:
        return len(self._obs_heap) + len(self._proc_heap) + len(self._cmd_heap)
