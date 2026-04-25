from __future__ import annotations

import numpy as np


class ZoomController:
    def __init__(self, tau_s: float = 0.2, max_rate_mmps: float = 120.0):
        self.tau_s = float(tau_s)
        self.max_rate_mmps = float(max_rate_mmps)

    def update(self, f_current_mm: float, f_target_mm: float, zoom_rate_cmd_mmps: float, dt: float) -> float:
        if abs(zoom_rate_cmd_mmps) > 1e-9:
            f_current_mm += float(np.clip(zoom_rate_cmd_mmps, -self.max_rate_mmps, self.max_rate_mmps)) * dt
        else:
            alpha = dt / (self.tau_s + dt)
            f_current_mm = (1.0 - alpha) * f_current_mm + alpha * f_target_mm
        return float(f_current_mm)

