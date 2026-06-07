from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from config import scene_cfg

_logger = logging.getLogger(__name__)
from entities.camera.entity import CameraEntity
from entities.camera.client import CameraClient
from entities.gimbal.entity import GimbalEntity
from entities.gimbal.client import GimbalClient
from entities.raspi.entity import RaspiEntity
from entities.raspi.client import RaspiClient
from entities.target.entity import TargetEntity
from runtime.types import Command, CommandResult, WorldSnapshot


@dataclass
class _ScheduledCommand:
    apply_at: float
    command: Command


class DigitalTwinRuntime:
    def __init__(self, dt_s: Optional[float] = None, obs_filter=None):
        self.dt_s = float(dt_s if dt_s is not None else scene_cfg.dt_s)
        self._time = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._obs_filter = obs_filter

        self.target = TargetEntity()
        self.gimbal = GimbalEntity()
        self.camera = CameraEntity()
        self.raspi = RaspiEntity()

        self._pending_commands: List[_ScheduledCommand] = []
        self._last_snapshot = WorldSnapshot(
            timestamp=0.0,
            target=self.target.get_state(),
            gimbal=self.gimbal.get_state(0.0),
            camera=self.camera.get_state(),
            raspi=self.raspi.get_state(),
        )

        self.gimbal_client = GimbalClient(self.submit_command, self._get_gimbal_state, self._get_gimbal_status)
        self.camera_client = CameraClient(self.submit_command, self._get_camera_state, self._get_camera_frame)
        self.raspi_client = RaspiClient(self.submit_command, self._get_raspi_state, self.raspi.set_delay_profile, self.raspi.get_delay_profile, self.raspi.load_control_program)

    @property
    def t(self) -> float:
        return self._time

    def submit_command(self, command: Command) -> None:
        with self._lock:
            ts = self._time if command.timestamp is None else float(command.timestamp)
            apply_at = max(self._time + self.dt_s, ts)
            self._pending_commands.append(_ScheduledCommand(apply_at=apply_at, command=command))

    def _submit_command_at(self, command: Command, apply_at: float) -> None:
        with self._lock:
            self._pending_commands.append(_ScheduledCommand(apply_at=apply_at, command=command))

    def _dispatch(self, command: Command) -> CommandResult:
        ts = self._time
        if command.target == "gimbal":
            if command.action == "power_on":
                return self.gimbal.power_on(ts)
            if command.action == "power_off":
                return self.gimbal.power_off(ts)
            if command.action == "set_mode":
                return self.gimbal.set_mode(str(command.payload["mode"]), ts)
            if command.action == "set_angle_target":
                return self.gimbal.set_angle_target(float(command.payload["yaw"]), float(command.payload["pitch"]), ts)
            if command.action == "set_rate_target":
                return self.gimbal.set_rate_target(float(command.payload["yaw_rate"]), float(command.payload["pitch_rate"]), ts)
        elif command.target == "camera":
            if command.action == "power_on":
                return self.camera.power_on(ts)
            if command.action == "power_off":
                return self.camera.power_off(ts)
            if command.action == "set_zoom_target_mm":
                return self.camera.set_zoom_target_mm(float(command.payload["f_mm"]), ts)
            if command.action == "zoom_by":
                return self.camera.zoom_by(float(command.payload["delta_mm"]), ts)
            if command.action == "set_zoom_rate_mmps":
                return self.camera.set_zoom_rate_mmps(float(command.payload["rate_mmps"]), ts)
        elif command.target == "raspi":
            if command.action == "power_on":
                return self.raspi.power_on(ts)
            if command.action == "power_off":
                return self.raspi.power_off(ts)
        return CommandResult(False, "UNKNOWN", f"unknown command {command.target}.{command.action}")

    def _apply_due_commands(self) -> None:
        due: List[_ScheduledCommand] = [c for c in self._pending_commands if c.apply_at <= self._time]
        self._pending_commands = [c for c in self._pending_commands if c.apply_at > self._time]
        for item in due:
            result = self._dispatch(item.command)
            if not result.accepted:
                _logger.debug(
                    "命令被拒绝: %s.%s -> %s (%s)",
                    item.command.target, item.command.action, result.code, result.message
                )

    def step(self, n: int = 1) -> WorldSnapshot:
        with self._lock:
            for _ in range(max(1, int(n))):
                # 固定顺序：收命令 -> Target -> Gimbal -> Camera -> Raspi -> 发布快照
                self._apply_due_commands()
                self._time += self.dt_s

                target_state = self.target.update(self.dt_s, self._time)
                gimbal_state = self.gimbal.update(self.dt_s, self._time)
                camera_state = self.camera.update(self.dt_s, self._time, target_state.__dict__, gimbal_state.__dict__)

                world_obs = {
                    "timestamp": self._time,
                    "target": target_state.__dict__,
                    "gimbal": gimbal_state.__dict__,
                    "camera": camera_state.__dict__,
                    "frame": self.camera.get_frame(),
                }
                # 观测过滤：按 obs_mode 整形控制器可见字段
                if self._obs_filter and getattr(self._obs_filter, "mode", "") == "realistic":
                    gimbal_measured = self.gimbal.get_measured_state(self._time)
                    gimbal_measured["mode"] = gimbal_state.mode
                    raspi_obs = self._obs_filter.filter_obs(world_obs, gimbal_measured=gimbal_measured)
                else:
                    raspi_obs = self._obs_filter.filter_obs(world_obs) if self._obs_filter else world_obs
                raspi_state = self.raspi.update(self._time, raspi_obs, self._submit_command_at, self.dt_s)

                self._last_snapshot = WorldSnapshot(
                    timestamp=self._time,
                    target=target_state.__dict__.copy(),
                    gimbal=gimbal_state.__dict__.copy(),
                    camera=camera_state.__dict__.copy(),
                    raspi=raspi_state.__dict__.copy(),
                )
            return self._last_snapshot

    def start(self, mode: str = "realtime") -> None:
        if mode not in ("realtime", "offline"):
            raise ValueError("mode must be realtime or offline")
        if mode == "offline":
            return
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                t0 = time.perf_counter()
                self.step(1)
                elapsed = time.perf_counter() - t0
                sleep_s = max(0.0, self.dt_s - elapsed)
                time.sleep(sleep_s)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def get_world_snapshot(self) -> WorldSnapshot:
        with self._lock:
            return WorldSnapshot(
                timestamp=self._last_snapshot.timestamp,
                target=self._last_snapshot.target.copy(),
                gimbal=self._last_snapshot.gimbal.copy(),
                camera=self._last_snapshot.camera.copy(),
                raspi=self._last_snapshot.raspi.copy(),
            )

    def _get_gimbal_state(self) -> dict:
        return self.get_world_snapshot().gimbal

    def _get_gimbal_status(self) -> dict:
        s = self.get_world_snapshot().gimbal
        return {"power_state": s["power_state"], "mode": s["mode"]}

    def _get_camera_state(self) -> dict:
        return self.get_world_snapshot().camera

    def _get_camera_frame(self):
        return self.camera.get_frame()

    def _get_raspi_state(self) -> dict:
        return self.get_world_snapshot().raspi
