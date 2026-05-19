"""线程安全状态缓冲。"""

from __future__ import annotations

import math
import threading
from collections import deque
from typing import Any, Deque, List, Optional

import numpy as np

from runtime.types import Detection
from simulation.types import FrameSample, wrap_pm180


class UiStateBuffer:
    """线程安全缓冲：仿真线程写入，UI 线程读取。"""

    def __init__(self, max_curve_len: int = 5000, max_frame_len: int = 240):
        self._lock = threading.Lock()
        self.latest_snapshot: Optional[Any] = None
        self.latest_frame: Optional[FrameSample] = None
        self.frame_hist: Deque[FrameSample] = deque(maxlen=max_frame_len)

        self.t_hist: Deque[float] = deque(maxlen=max_curve_len)
        self.x_hist: Deque[float] = deque(maxlen=max_curve_len)
        self.y_hist: Deque[float] = deque(maxlen=max_curve_len)
        self.err_hist: Deque[float] = deque(maxlen=max_curve_len)
        self.rate_hist: Deque[float] = deque(maxlen=max_curve_len)
        self.angle_err_hist: Deque[float] = deque(maxlen=max_curve_len)
        self.atp_state_hist: Deque[str] = deque(maxlen=max_curve_len)

        # 每帧关键指标（用于导出 metrics.csv）
        self.metrics_log: List[dict] = []
        # ATP 状态变迁事件（用于导出 event_log.json）
        self.event_log: List[dict] = []
        self._last_atp_state: str = ""

    def clear(self) -> None:
        with self._lock:
            self.latest_snapshot = None
            self.latest_frame = None
            self.frame_hist.clear()
            self.t_hist.clear()
            self.x_hist.clear()
            self.y_hist.clear()
            self.err_hist.clear()
            self.rate_hist.clear()
            self.angle_err_hist.clear()
            self.atp_state_hist.clear()
            self.metrics_log.clear()
            self.event_log.clear()
            self._last_atp_state = ""

    @staticmethod
    def _extract_detection(frame: Any) -> Detection:
        """优先使用相机仿真 GT 点，缺失时回退到阈值质心检测。"""
        gt = getattr(frame, "optional_gt", None)
        if isinstance(gt, dict) and gt.get("in_fov"):
            u_px = gt.get("u_px")
            v_px = gt.get("v_px")
            if u_px is not None and v_px is not None:
                return Detection(found=True, cx=float(u_px), cy=float(v_px), confidence=1.0)

        image = frame.image
        ys, xs = np.where(image >= 180)
        if len(xs) == 0:
            return Detection(found=False, confidence=0.0)
        return Detection(found=True, cx=float(xs.mean()), cy=float(ys.mean()), confidence=1.0)

    def push(self, snapshot: Any, frame: Any) -> None:
        with self._lock:
            self.latest_snapshot = snapshot
            t_s = float(snapshot.timestamp)
            x_m = float(snapshot.target["x_m"])
            y_m = float(snapshot.target["y_m"])
            yaw_deg_internal = float(snapshot.gimbal["yaw_deg_internal"])
            target_bearing_deg = math.degrees(math.atan2(y_m, x_m))
            angle_err = wrap_pm180(target_bearing_deg - yaw_deg_internal)
            atp_state = str(snapshot.raspi.get("atp_state", ""))

            self.t_hist.append(t_s)
            self.x_hist.append(x_m)
            self.y_hist.append(y_m)
            self.rate_hist.append(float(snapshot.gimbal.get("yaw_rate_ref_dps", 0.0)))
            self.angle_err_hist.append(angle_err)
            self.atp_state_hist.append(atp_state)

            if frame is None:
                self.err_hist.append(float("nan"))
                err = float("nan")
            else:
                det = self._extract_detection(frame)
                fs = FrameSample(
                    timestamp=float(frame.timestamp),
                    image=frame.image.copy(),
                    intrinsics=dict(frame.intrinsics),
                    detection=det,
                )
                self.latest_frame = fs
                self.frame_hist.append(fs)

                u_px = float(snapshot.camera.get("u_px", float("nan")))
                cx = float(frame.intrinsics.get("cx", 0.0))
                err = float("nan") if not math.isfinite(u_px) else (u_px - cx)
                self.err_hist.append(err)

            # 记录每帧指标
            self.metrics_log.append({
                "t": t_s,
                "x_m": x_m,
                "y_m": y_m,
                "z_m": float(snapshot.target.get("z_m", 0.0)),
                "yaw_deg": yaw_deg_internal,
                "angle_err_deg": angle_err,
                "pixel_err": err,
                "atp_state": atp_state,
                "distance_m": float(snapshot.camera.get("distance_m", 0.0)),
                "sigma_px": float(snapshot.camera.get("sigma_px", 0.0)),
                "in_fov": int(bool(snapshot.camera.get("in_fov", False))),
            })

            # 检测 ATP 状态变迁
            if atp_state and atp_state != self._last_atp_state:
                self.event_log.append({
                    "t": t_s,
                    "from": self._last_atp_state,
                    "to": atp_state,
                })
                self._last_atp_state = atp_state

    def read_latest(self) -> tuple[Optional[Any], Optional[FrameSample]]:
        with self._lock:
            return self.latest_snapshot, self.latest_frame

    def read_curves(self) -> tuple[list[float], list[float], list[float], list[float], list[float], list[float], list[str]]:
        with self._lock:
            return (
                list(self.t_hist),
                list(self.x_hist),
                list(self.y_hist),
                list(self.err_hist),
                list(self.rate_hist),
                list(self.angle_err_hist),
                list(self.atp_state_hist),
            )

    def read_logs(self) -> tuple[list[dict], list[dict]]:
        with self._lock:
            return list(self.metrics_log), list(self.event_log)

    def find_frame_at_or_before(self, timestamp_s: float) -> Optional[FrameSample]:
        with self._lock:
            for sample in reversed(self.frame_hist):
                if sample.timestamp <= timestamp_s:
                    return sample
            return self.frame_hist[0] if self.frame_hist else None
