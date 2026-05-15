from __future__ import annotations

import math
import numpy as np

from config import TargetConfig, target_cfg


class TargetKinematics3D:
    def __init__(self, cfg: TargetConfig | None = None):
        self.cfg = cfg or target_cfg
        self.x: float = self.cfg.initial_x_m
        self.y: float = self.cfg.initial_y_m
        self.z: float = self.cfg.initial_z_m
        self.vx: float = 0.0
        self.vy: float = 0.0
        self.vz: float = 0.0
        self.t: float = 0.0

        if self.cfg.motion_type in ("constant_velocity", "constant_accel"):
            self.vx = self.cfg.velocity_x_mps
            self.vy = self.cfg.velocity_y_mps
            self.vz = self.cfg.velocity_z_mps
        elif self.cfg.motion_type == "random_walk":
            self._rng = np.random.default_rng(self.cfg.random_seed)
        elif self.cfg.motion_type == "waypoint":
            self._wp_index = 0
            self._wp_list = self.cfg.waypoints or []
        elif self.cfg.motion_type != "sinusoidal":
            raise ValueError(f"Unknown motion_type: {self.cfg.motion_type}")

    def step(self, dt: float) -> tuple[float, float, float]:
        self.t += dt
        cfg = self.cfg
        if cfg.motion_type == "constant_velocity":
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.z += self.vz * dt
        elif cfg.motion_type == "constant_accel":
            self.vx += cfg.accel_x_mps2 * dt
            self.vy += cfg.accel_y_mps2 * dt
            self.vz += cfg.accel_z_mps2 * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.z += self.vz * dt
        elif cfg.motion_type == "sinusoidal":
            self.x = cfg.initial_x_m
            self.y = cfg.sin_amplitude_m * math.sin(2 * math.pi * cfg.sin_frequency_hz * self.t)
            self.z = cfg.sin_z_amplitude_m * math.sin(2 * math.pi * cfg.sin_z_frequency_hz * self.t)
            omega = 2 * math.pi * cfg.sin_frequency_hz
            self.vx = 0.0
            self.vy = cfg.sin_amplitude_m * omega * math.cos(omega * self.t)
            omega_z = 2 * math.pi * cfg.sin_z_frequency_hz
            self.vz = cfg.sin_z_amplitude_m * omega_z * math.cos(omega_z * self.t)
        elif cfg.motion_type == "random_walk":
            ax = self._rng.uniform(-cfg.random_max_accel_mps2, cfg.random_max_accel_mps2)
            ay = self._rng.uniform(-cfg.random_max_accel_mps2, cfg.random_max_accel_mps2)
            az = self._rng.uniform(-cfg.random_max_accel_mps2, cfg.random_max_accel_mps2)
            self.vx = self.vx * cfg.random_damping + ax * dt
            self.vy = self.vy * cfg.random_damping + ay * dt
            self.vz = self.vz * cfg.random_damping + az * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.z += self.vz * dt
        elif cfg.motion_type == "waypoint":
            self._step_waypoint(dt)
        return self.x, self.y, self.z

    def _step_waypoint(self, dt: float) -> None:
        """航点导航：按顺序飞向每个航点，到达后切换下一个。"""
        if not self._wp_list:
            self.vx = 0.0
            self.vy = 0.0
            self.vz = 0.0
            return

        wp = self._wp_list[self._wp_index]
        tx, ty, tz, speed = wp[0], wp[1], wp[2] if len(wp) > 3 else 0.0, wp[3] if len(wp) > 3 else wp[2]
        # 兼容旧格式 (x, y, speed) 和新格式 (x, y, z, speed)
        if len(wp) == 3:
            tx, ty, speed = wp[0], wp[1], wp[2]
            tz = 0.0
        elif len(wp) == 4:
            tx, ty, tz, speed = wp[0], wp[1], wp[2], wp[3]

        dx = tx - self.x
        dy = ty - self.y
        dz = tz - self.z
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)

        if dist < self.cfg.waypoint_arrival_radius_m:
            self.x = tx
            self.y = ty
            self.z = tz
            self._wp_index += 1
            if self._wp_index >= len(self._wp_list):
                self._wp_index = len(self._wp_list) - 1
                self.vx = 0.0
                self.vy = 0.0
                self.vz = 0.0
                return
            wp = self._wp_list[self._wp_index]
            if len(wp) == 3:
                tx, ty, speed = wp[0], wp[1], wp[2]
                tz = 0.0
            elif len(wp) == 4:
                tx, ty, tz, speed = wp[0], wp[1], wp[2], wp[3]
            dx = tx - self.x
            dy = ty - self.y
            dz = tz - self.z
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)

        if speed <= 0.0 or dist < 1e-6:
            self.vx = 0.0
            self.vy = 0.0
            self.vz = 0.0
            return

        move = min(speed * dt, dist)
        ratio = move / dist
        self.vx = (dx / dist) * speed
        self.vy = (dy / dist) * speed
        self.vz = (dz / dist) * speed
        self.x += dx * ratio
        self.y += dy * ratio
        self.z += dz * ratio

    @property
    def azimuth_deg(self) -> float:
        return math.degrees(math.atan2(self.y, self.x))

    @property
    def bearing_deg(self) -> float:
        """向后兼容别名，等同于 azimuth_deg。"""
        return self.azimuth_deg

    @property
    def elevation_deg(self) -> float:
        horizontal_dist = math.sqrt(self.x * self.x + self.y * self.y)
        return math.degrees(math.atan2(self.z, horizontal_dist))

    @property
    def distance_m(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)


# 向后兼容别名
TargetKinematics2D = TargetKinematics3D
