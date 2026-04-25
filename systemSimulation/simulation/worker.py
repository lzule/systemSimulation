"""仿真推进线程。"""

from __future__ import annotations

import threading
import time
from typing import Optional

from simulation.bootstrap import apply_delay_profile
from simulation.qt_compat import QtCore
from simulation.state_buffer import UiStateBuffer


class SimWorker(QtCore.QThread):
    """仿真推进线程，负责高频 step 与状态写入缓冲。"""

    error_signal = QtCore.pyqtSignal(str)
    finished_signal = QtCore.pyqtSignal()

    def __init__(self, runtime, state_buf: UiStateBuffer, mode: str, duration_s: float, sim_hz: float = 200.0):
        super().__init__()
        self.runtime = runtime
        self.state_buf = state_buf
        self.mode = mode
        self.duration_s = float(duration_s)
        self.sim_hz = float(sim_hz)

        self._stop_flag = False
        self._paused = True
        self._lock = threading.Lock()
        self._pending_delay_ms: Optional[float] = None

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused

    def stop(self) -> None:
        with self._lock:
            self._stop_flag = True

    def request_delay_ms(self, delay_ms: float) -> None:
        with self._lock:
            self._pending_delay_ms = float(delay_ms)

    def _is_stopped(self) -> bool:
        with self._lock:
            return self._stop_flag

    def _is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def _take_pending_delay(self) -> Optional[float]:
        with self._lock:
            pending = self._pending_delay_ms
            self._pending_delay_ms = None
            return pending

    def _apply_delay_if_needed(self) -> None:
        pending_ms = self._take_pending_delay()
        if pending_ms is None:
            return
        apply_delay_profile(self.runtime, pending_ms)

    def run(self) -> None:
        try:
            dt_target = 1.0 / max(1.0, self.sim_hz)
            t_last = time.perf_counter()
            while not self._is_stopped():
                if self._is_paused():
                    self.msleep(4)
                    continue

                self._apply_delay_if_needed()
                snap = self.runtime.step(1)
                frame = self.runtime.camera_client.get_frame()
                self.state_buf.push(snap, frame)

                if snap.timestamp >= self.duration_s:
                    self.finished_signal.emit()
                    break

                if self.mode == "realtime":
                    t_now = time.perf_counter()
                    elapsed = t_now - t_last
                    sleep_s = max(0.0, dt_target - elapsed)
                    if sleep_s > 0.0:
                        time.sleep(sleep_s)
                    t_last = time.perf_counter()
        except Exception as exc:  # noqa: BLE001
            self.error_signal.emit(str(exc))
