from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from config import CameraConfig, camera_cfg, scene_cfg
from entities.camera.control import ZoomController
from entities.camera.model import CameraImagingModel
from runtime.types import POWER_BOOTING, POWER_OFF, POWER_READY, CommandResult, Detection, FramePacket


@dataclass
class CameraState:
    timestamp: float
    power_state: str
    f_current_mm: float
    f_target_mm: float
    zoom_rate_cmd_mmps: float
    frame_id: int
    in_fov: bool
    u_px: float
    v_px: float


def detect_beacon_centroid(image: np.ndarray, threshold: int = None) -> Detection:
    if threshold is None:
        threshold = camera_cfg.detection_threshold
    ys, xs = np.where(image >= threshold)
    if len(xs) == 0:
        return Detection(found=False, confidence=0.0)
    cx = float(xs.mean())
    cy = float(ys.mean())
    confidence = float(np.clip(image[ys, xs].mean() / 255.0, 0.0, 1.0))
    return Detection(found=True, cx=cx, cy=cy, confidence=confidence)


class CameraEntity:
    def __init__(self, cfg: CameraConfig | None = None):
        self.cfg = cfg or camera_cfg
        self.power_state = POWER_OFF
        self.boot_delay_s = float(self.cfg.boot_delay_s)
        self.boot_remaining_s = 0.0

        self.f_current_mm = float(self.cfg.focal_length_mm)
        self.f_target_mm = float(self.cfg.focal_length_mm)
        self.zoom_rate_cmd_mmps = 0.0
        self.zoom_ctrl = ZoomController(tau_s=0.2, max_rate_mmps=120.0)
        self.imaging = CameraImagingModel(self.cfg)

        self.frame_id = 0
        self.last_frame: Optional[FramePacket] = None
        self._last_state = CameraState(0.0, POWER_OFF, self.f_current_mm, self.f_target_mm, 0.0, 0, False, float("nan"), float("nan"))

    def power_on(self, timestamp: float) -> CommandResult:
        if self.power_state in (POWER_BOOTING, POWER_READY):
            return CommandResult(True, "ALREADY_ON", "camera already on", timestamp)
        self.power_state = POWER_BOOTING
        self.boot_remaining_s = self.boot_delay_s
        return CommandResult(True, "OK", "camera booting", timestamp)

    def power_off(self, timestamp: float) -> CommandResult:
        self.power_state = POWER_OFF
        self.boot_remaining_s = 0.0
        self.zoom_rate_cmd_mmps = 0.0
        self.last_frame = None
        return CommandResult(True, "OK", "camera off", timestamp)

    def _reject_if_not_ready(self) -> Optional[CommandResult]:
        if self.power_state != POWER_READY:
            return CommandResult(False, "NOT_READY", f"camera state={self.power_state}")
        return None

    def set_zoom_target_mm(self, f_mm: float, timestamp: float) -> CommandResult:
        rejected = self._reject_if_not_ready()
        if rejected:
            return rejected
        self.f_target_mm = float(np.clip(f_mm, self.cfg.focal_min_mm, self.cfg.focal_max_mm))
        self.zoom_rate_cmd_mmps = 0.0
        return CommandResult(True, "OK", "zoom target set", timestamp)

    def zoom_by(self, delta_mm: float, timestamp: float) -> CommandResult:
        return self.set_zoom_target_mm(self.f_target_mm + delta_mm, timestamp)

    def set_zoom_rate_mmps(self, rate_mmps: float, timestamp: float) -> CommandResult:
        rejected = self._reject_if_not_ready()
        if rejected:
            return rejected
        self.zoom_rate_cmd_mmps = float(np.clip(rate_mmps, -self.zoom_ctrl.max_rate_mmps, self.zoom_ctrl.max_rate_mmps))
        return CommandResult(True, "OK", "zoom rate set", timestamp)

    def _focal_px(self) -> float:
        return self.imaging.focal_px(self.f_current_mm)

    def _fov_h_half_rad(self) -> float:
        return self.imaging.fov_h_half_rad(self.f_current_mm)

    def _fov_v_half_rad(self) -> float:
        return self.imaging.fov_v_half_rad(self.f_current_mm)

    def _update_zoom(self, dt: float) -> None:
        self.f_current_mm = self.zoom_ctrl.update(self.f_current_mm, self.f_target_mm, self.zoom_rate_cmd_mmps, dt)
        self.f_current_mm = float(np.clip(self.f_current_mm, self.cfg.focal_min_mm, self.cfg.focal_max_mm))

    def _render_frame(self, alpha_rad: float, beta_rad: float, timestamp: float) -> Tuple[np.ndarray, bool, float, float]:
        return self.imaging.render_beacon_frame(alpha_rad, beta_rad, self.f_current_mm, timestamp)

    def update(self, dt: float, timestamp: float, target_state: Dict[str, float], gimbal_state: Dict[str, float]) -> CameraState:
        if self.power_state == POWER_BOOTING:
            self.boot_remaining_s -= dt
            if self.boot_remaining_s <= 0.0:
                self.power_state = POWER_READY

        in_fov = False
        u_px = float("nan")
        v_px = float("nan")
        if self.power_state == POWER_READY:
            self._update_zoom(dt)

            # 水平偏差角 alpha = azimuth - yaw
            azimuth = math.atan2(target_state["y_m"], target_state["x_m"])
            yaw = math.radians(gimbal_state["yaw_deg_internal"])
            alpha = (azimuth - yaw + math.pi) % (2.0 * math.pi) - math.pi

            # 垂直偏差角 beta = elevation - pitch
            x = target_state["x_m"]
            y = target_state["y_m"]
            z = target_state.get("z_m", 0.0)
            horizontal_dist = math.sqrt(x * x + y * y)
            elevation = math.atan2(z, horizontal_dist)
            pitch = math.radians(gimbal_state["pitch_deg"])
            beta = elevation - pitch

            frame, in_fov, u_px, v_px = self._render_frame(alpha, beta, timestamp)
            intrinsics = {
                "f_mm": self.f_current_mm,
                "f_px": self._focal_px(),
                "cx": self.cfg.resolution_w / 2.0,
                "cy": self.cfg.resolution_h / 2.0,
                "width": float(self.cfg.resolution_w),
                "height": float(self.cfg.resolution_h),
            }
            gt = {"u_px": u_px, "v_px": v_px, "in_fov": float(in_fov)} if in_fov else None
            self.last_frame = FramePacket(timestamp=timestamp, image=frame, intrinsics=intrinsics, optional_gt=gt)
            self.frame_id += 1

        self._last_state = CameraState(
            timestamp=timestamp,
            power_state=self.power_state,
            f_current_mm=self.f_current_mm,
            f_target_mm=self.f_target_mm,
            zoom_rate_cmd_mmps=self.zoom_rate_cmd_mmps,
            frame_id=self.frame_id,
            in_fov=in_fov,
            u_px=u_px,
            v_px=v_px,
        )
        return self._last_state

    def get_state(self) -> Dict[str, float | str | bool]:
        s = self._last_state
        return {
            "timestamp": s.timestamp,
            "power_state": s.power_state,
            "f_current_mm": s.f_current_mm,
            "f_target_mm": s.f_target_mm,
            "zoom_rate_cmd_mmps": s.zoom_rate_cmd_mmps,
            "frame_id": s.frame_id,
            "in_fov": s.in_fov,
            "u_px": s.u_px,
            "v_px": s.v_px,
        }

    def get_frame(self) -> Optional[FramePacket]:
        return self.last_frame
