from __future__ import annotations

import math
import numpy as np

from config import TargetConfig, target_cfg


class TargetKinematics2D:
    def __init__(self, cfg: TargetConfig | None = None):
        self.cfg = cfg or target_cfg
        self.x: float = self.cfg.initial_x_m
        self.y: float = self.cfg.initial_y_m
        self.vx: float = 0.0
        self.vy: float = 0.0
        self.t: float = 0.0

        if self.cfg.motion_type in ("constant_velocity", "constant_accel"):
            self.vx = self.cfg.velocity_x_mps
            self.vy = self.cfg.velocity_y_mps
        elif self.cfg.motion_type == "random_walk":
            self._rng = np.random.default_rng(self.cfg.random_seed)
        elif self.cfg.motion_type == "waypoint":
            self._wp_index = 0
            self._wp_list = self.cfg.waypoints or []
        elif self.cfg.motion_type != "sinusoidal":
            raise ValueError(f"Unknown motion_type: {self.cfg.motion_type}")

    def step(self, dt: float) -> tuple[float, float]:
        self.t += dt
        cfg = self.cfg
        if cfg.motion_type == "constant_velocity":
            self.x += self.vx * dt
            self.y += self.vy * dt
        elif cfg.motion_type == "constant_accel":
            self.vx += cfg.accel_x_mps2 * dt
            self.vy += cfg.accel_y_mps2 * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
        elif cfg.motion_type == "sinusoidal":
            self.x = cfg.initial_x_m
            self.y = cfg.sin_amplitude_m * math.sin(2 * math.pi * cfg.sin_frequency_hz * self.t)
            omega = 2 * math.pi * cfg.sin_frequency_hz
            self.vx = 0.0
            self.vy = cfg.sin_amplitude_m * omega * math.cos(omega * self.t)
        elif cfg.motion_type == "random_walk":
            ax = self._rng.uniform(-cfg.random_max_accel_mps2, cfg.random_max_accel_mps2)
            ay = self._rng.uniform(-cfg.random_max_accel_mps2, cfg.random_max_accel_mps2)
            self.vx = self.vx * cfg.random_damping + ax * dt
            self.vy = self.vy * cfg.random_damping + ay * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
        elif cfg.motion_type == "waypoint":
            self._step_waypoint(dt)
        return self.x, self.y

    def _step_waypoint(self, dt: float) -> None:
        """航点导航：按顺序飞向每个航点，到达后切换下一个。"""
        if not self._wp_list:
            self.vx = 0.0
            self.vy = 0.0
            return

        wp = self._wp_list[self._wp_index]
        tx, ty, speed = wp
        dx = tx - self.x
        dy = ty - self.y
        dist = math.hypot(dx, dy)

        if dist < self.cfg.waypoint_arrival_radius_m:
            self.x = tx
            self.y = ty
            self._wp_index += 1
            if self._wp_index >= len(self._wp_list):
                self._wp_index = len(self._wp_list) - 1
                self.vx = 0.0
                self.vy = 0.0
                return
            wp = self._wp_list[self._wp_index]
            tx, ty, speed = wp
            dx = tx - self.x
            dy = ty - self.y
            dist = math.hypot(dx, dy)

        if speed <= 0.0 or dist < 1e-6:
            self.vx = 0.0
            self.vy = 0.0
            return

        move = min(speed * dt, dist)
        ratio = move / dist
        self.vx = (dx / dist) * speed
        self.vy = (dy / dist) * speed
        self.x += dx * ratio
        self.y += dy * ratio

    @property
    def bearing_deg(self) -> float:
        return math.degrees(math.atan2(self.y, self.x))

    @property
    def distance_m(self) -> float:
        return math.hypot(self.x, self.y)
