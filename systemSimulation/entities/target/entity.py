from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Dict

from config import TargetConfig, target_cfg
from entities.target.model import TargetKinematics3D


@dataclass
class TargetState:
    timestamp: float
    x_m: float
    y_m: float
    z_m: float
    azimuth_deg: float
    elevation_deg: float
    distance_m: float
    vx_mps: float = 0.0
    vy_mps: float = 0.0
    vz_mps: float = 0.0
    bearing_deg: float = 0.0  # 向后兼容别名


class TargetEntity:
    def __init__(self, cfg: TargetConfig | None = None):
        # 深拷贝配置，确保每个 TargetEntity 拥有独立配置副本，
        # 避免全局 target_cfg 被原地修改后影响已有实例
        self.cfg = copy.deepcopy(cfg or target_cfg)
        self.model = TargetKinematics3D(self.cfg)
        azimuth = math.degrees(math.atan2(self.cfg.initial_y_m, self.cfg.initial_x_m))
        horizontal_dist = math.sqrt(self.cfg.initial_x_m ** 2 + self.cfg.initial_y_m ** 2)
        elevation = math.degrees(math.atan2(self.cfg.initial_z_m, horizontal_dist))
        dist = math.sqrt(self.cfg.initial_x_m ** 2 + self.cfg.initial_y_m ** 2 + self.cfg.initial_z_m ** 2)
        self.state = TargetState(
            0.0,
            self.cfg.initial_x_m,
            self.cfg.initial_y_m,
            self.cfg.initial_z_m,
            azimuth,
            elevation,
            dist,
            self.model.vx,
            self.model.vy,
            self.model.vz,
            azimuth,  # bearing_deg 别名
        )

    def update(self, dt: float, timestamp: float) -> TargetState:
        x, y, z = self.model.step(dt)
        self.state = TargetState(
            timestamp=timestamp,
            x_m=x,
            y_m=y,
            z_m=z,
            azimuth_deg=self.model.azimuth_deg,
            elevation_deg=self.model.elevation_deg,
            distance_m=self.model.distance_m,
            vx_mps=self.model.vx,
            vy_mps=self.model.vy,
            vz_mps=self.model.vz,
            bearing_deg=self.model.azimuth_deg,  # 别名
        )
        return self.state

    def get_state(self) -> Dict[str, float]:
        return {
            "timestamp": self.state.timestamp,
            "x_m": self.state.x_m,
            "y_m": self.state.y_m,
            "z_m": self.state.z_m,
            "bearing_deg": self.state.bearing_deg,
            "azimuth_deg": self.state.azimuth_deg,
            "elevation_deg": self.state.elevation_deg,
            "distance_m": self.state.distance_m,
            "vx_mps": self.state.vx_mps,
            "vy_mps": self.state.vy_mps,
            "vz_mps": self.state.vz_mps,
        }
