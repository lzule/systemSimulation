from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict

from config import TargetConfig, target_cfg
from entities.target.model import TargetKinematics2D


@dataclass
class TargetState:
    timestamp: float
    x_m: float
    y_m: float
    bearing_deg: float
    distance_m: float
    vx_mps: float = 0.0
    vy_mps: float = 0.0


class TargetEntity:
    def __init__(self, cfg: TargetConfig | None = None):
        self.cfg = cfg or target_cfg
        self.model = TargetKinematics2D(self.cfg)
        self.state = TargetState(
            0.0,
            self.cfg.initial_x_m,
            self.cfg.initial_y_m,
            math.degrees(math.atan2(self.cfg.initial_y_m, self.cfg.initial_x_m)),
            math.hypot(self.cfg.initial_x_m, self.cfg.initial_y_m),
        )

    def update(self, dt: float, timestamp: float) -> TargetState:
        x, y = self.model.step(dt)
        self.state = TargetState(
            timestamp=timestamp,
            x_m=x,
            y_m=y,
            bearing_deg=self.model.bearing_deg,
            distance_m=self.model.distance_m,
            vx_mps=self.model.vx,
            vy_mps=self.model.vy,
        )
        return self.state

    def get_state(self) -> Dict[str, float]:
        return {
            "timestamp": self.state.timestamp,
            "x_m": self.state.x_m,
            "y_m": self.state.y_m,
            "bearing_deg": self.state.bearing_deg,
            "distance_m": self.state.distance_m,
            "vx_mps": self.state.vx_mps,
            "vy_mps": self.state.vy_mps,
        }
