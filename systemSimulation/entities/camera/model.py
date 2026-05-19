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

    def fov_h_half_rad(self, f_mm: float) -> float:
        return math.atan(self.cfg.sensor_w_mm / (2.0 * f_mm))

    def fov_v_half_rad(self, f_mm: float) -> float:
        return math.atan(self.cfg.sensor_h_mm / (2.0 * f_mm))

    def render_beacon_frame(self, alpha_rad: float, beta_rad: float, f_mm: float, timestamp: float, distance_m: float = 0.0) -> Tuple[np.ndarray, bool, float, float, float, float]:
        h, w = int(self.cfg.resolution_h), int(self.cfg.resolution_w)
        frame = np.zeros((h, w), dtype=np.uint8)
        sigma_base = self.cfg.beacon_sigma_px

        # 距离相关 sigma
        if self.cfg.sigma_ref_distance_m > 0.0 and distance_m > 0.0:
            sigma = sigma_base / (1.0 + distance_m / self.cfg.sigma_ref_distance_m)
        else:
            sigma = sigma_base

        fov_h_half = self.fov_h_half_rad(f_mm)
        fov_v_half = self.fov_v_half_rad(f_mm)
        in_fov = abs(alpha_rad) <= fov_h_half and abs(beta_rad) <= fov_v_half
        u = float("nan")
        v = float("nan")
        brightness = 0.0
        if in_fov:
            f_px = self.focal_px(f_mm)
            cx = w / 2.0
            cy = h / 2.0
            u = f_px * math.tan(alpha_rad) + cx
            v = cy - f_px * math.tan(beta_rad)
            if 0 <= u < w and 0 <= v < h:
                # 丢检判断：sigma 越小丢检概率越高
                render_blob = True
                if self.cfg.miss_detection_base_rate > 0.0 or self.cfg.miss_sigma_gain_px > 0.0:
                    eps = 1e-8
                    miss_rate = np.clip(
                        self.cfg.miss_detection_base_rate + self.cfg.miss_sigma_gain_px / max(sigma, eps),
                        0.0, 1.0,
                    )
                    if np.random.random() < miss_rate:
                        render_blob = False

                if render_blob:
                    # 亮度计算
                    if self.cfg.brightness_ref_distance_m > 0.0 and distance_m > 0.0:
                        brightness = self.cfg.brightness_base / (1.0 + distance_m / self.cfg.brightness_ref_distance_m)
                    else:
                        brightness = self.cfg.brightness_base
                    if self.cfg.brightness_jitter_std > 0.0:
                        brightness += np.random.normal(0.0, self.cfg.brightness_jitter_std)
                    brightness = float(np.clip(brightness, 0.0, 1.0))

                    xs = np.arange(w, dtype=np.float32)
                    ys = np.arange(h, dtype=np.float32)
                    gx = np.exp(-0.5 * ((xs - u) / sigma) ** 2)
                    gy = np.exp(-0.5 * ((ys - v) / sigma) ** 2)
                    blob = np.outer(gy, gx)
                    frame = np.clip(blob * brightness * 255.0, 0.0, 255.0).astype(np.uint8)

        noise = np.random.normal(0.0, scene_cfg.pixel_noise_std, size=frame.shape)
        frame = np.clip(frame.astype(np.float32) + noise, 0.0, 255.0).astype(np.uint8)
        return frame, in_fov, u, v, float(sigma), float(brightness)
