from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from config import CameraConfig, camera_cfg, scene_cfg


class CameraImagingModel:
    def __init__(self, cfg: CameraConfig | None = None):
        self.cfg = cfg or camera_cfg

    def focal_px(self, f_mm: float) -> float:
        pixel_size_mm = self.cfg.sensor_w_mm / self.cfg.resolution_w
        return f_mm / pixel_size_mm

    def fov_half_rad(self, f_mm: float) -> float:
        return math.atan(self.cfg.sensor_w_mm / (2.0 * f_mm))

    def render_beacon_frame(self, alpha_rad: float, f_mm: float, timestamp: float) -> Tuple[np.ndarray, bool, float, float]:
        h, w = int(self.cfg.resolution_h), int(self.cfg.resolution_w)
        frame = np.zeros((h, w), dtype=np.uint8)
        sigma = self.cfg.beacon_sigma_px

        in_fov = abs(alpha_rad) <= self.fov_half_rad(f_mm)
        u = float("nan")
        v = float("nan")
        if in_fov:
            u = self.focal_px(f_mm) * math.tan(alpha_rad) + w / 2.0
            v = h / 2.0
            if 0 <= u < w:
                xs = np.arange(w, dtype=np.float32)
                ys = np.arange(h, dtype=np.float32)
                gx = np.exp(-0.5 * ((xs - u) / sigma) ** 2)
                gy = np.exp(-0.5 * ((ys - v) / sigma) ** 2)
                blob = np.outer(gy, gx)
                frame = np.clip(blob * 255.0, 0.0, 255.0).astype(np.uint8)

        noise = np.random.normal(0.0, scene_cfg.pixel_noise_std, size=frame.shape)
        frame = np.clip(frame.astype(np.float32) + noise, 0.0, 255.0).astype(np.uint8)
        return frame, in_fov, u, v

