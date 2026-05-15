"""运行基线实验并输出 JSON 格式结果。

用法:
    python tools/run_baseline.py
    python tools/run_baseline.py --output output/baseline_results.json
    python tools/run_baseline.py --duration 20 --seed 42
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from baseline import get_baseline_config
from config import camera_cfg
from simulation.bootstrap import build_runtime


def wrap_pm180(angle_deg: float) -> float:
    return (angle_deg + 180.0) % 360.0 - 180.0


def run_baseline(duration_s: float = 20.0, seed: int = 42) -> dict:
    """运行基线实验，返回完整结果字典。"""
    np.random.seed(seed)
    rt = build_runtime(delay_ms=0.0)

    n_steps = int(duration_s / rt.dt_s)
    dt = rt.dt_s

    samples = []
    angle_errors = []
    pixel_errors = []
    in_fov_flags = []

    for i in range(n_steps):
        snap = rt.step(1)
        t = snap.timestamp

        target_bearing = float(snap.target["bearing_deg"])
        yaw = float(snap.gimbal["yaw_deg_internal"])
        angle_err = wrap_pm180(target_bearing - yaw)

        in_fov = bool(snap.camera["in_fov"])
        u_px = float(snap.camera["u_px"]) if in_fov else float("nan")

        if in_fov:
            pixel_errors.append(abs(u_px - camera_cfg.cx))
        else:
            pixel_errors.append(float("nan"))
        angle_errors.append(angle_err)
        in_fov_flags.append(in_fov)

        if i % 100 == 0:
            samples.append({
                "t": round(t, 4),
                "yaw": round(yaw, 4),
                "bearing": round(target_bearing, 4),
                "angle_err": round(angle_err, 4),
                "u_px": round(u_px, 4) if in_fov else None,
                "in_fov": in_fov,
            })

    angle_err_arr = np.array(angle_errors)
    px_err_arr = np.array(pixel_errors, dtype=float)
    in_fov_arr = np.array(in_fov_flags, dtype=bool)
    t_arr = np.arange(n_steps) * dt

    stable_mask = (t_arr >= 3.0) & in_fov_arr & np.isfinite(px_err_arr)

    metrics = {
        "tracking_ratio": float(in_fov_arr.sum() / len(in_fov_arr)),
        "angle_error_rms_deg": float(np.nan),
        "angle_error_max_deg": float(np.nan),
        "pixel_error_rms_px": float(np.nan),
        "no_divergence": False,
        "divergence_slope_deg_per_s": float(np.nan),
    }

    if np.any(stable_mask):
        stable_ae = angle_err_arr[stable_mask]
        stable_pe = px_err_arr[stable_mask]
        metrics["angle_error_rms_deg"] = float(np.sqrt(np.mean(stable_ae**2)))
        metrics["angle_error_max_deg"] = float(np.max(np.abs(stable_ae)))
        metrics["pixel_error_rms_px"] = float(np.sqrt(np.mean(stable_pe**2)))

    last_10s = (t_arr >= (duration_s - 10.0))
    if np.sum(last_10s) > 10:
        t_last = t_arr[last_10s]
        err_last = angle_err_arr[last_10s]
        slope = float(np.polyfit(t_last, err_last, 1)[0])
        metrics["divergence_slope_deg_per_s"] = slope
        metrics["no_divergence"] = abs(slope) < 0.1

    return {
        "metadata": _build_metadata(),
        "config_snapshot": _build_config_snapshot(),
        "metrics": metrics,
        "time_series_summary": samples,
    }


def _build_metadata() -> dict:
    git_hash = "unknown"
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        pass

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_hash": git_hash,
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "platform": platform.platform(),
    }


def _build_config_snapshot() -> dict:
    bc = get_baseline_config()
    return {
        "target_motion_type": bc.target_motion_type,
        "target_sin_amplitude_m": bc.target_sin_amplitude_m,
        "target_sin_frequency_hz": bc.target_sin_frequency_hz,
        "tracker_yaw_rate_kp": bc.tracker_yaw_rate_kp,
        "tracker_deadband_px": bc.tracker_deadband_px,
        "cam_focal_length_mm": bc.cam_focal_length_mm,
        "cam_resolution": f"{bc.cam_resolution_w}x{bc.cam_resolution_h}",
        "cam_beacon_sigma_px": bc.cam_beacon_sigma_px,
        "scene_dt_s": bc.scene_dt_s,
        "scene_pixel_noise_std": bc.scene_pixel_noise_std,
        "baseline_delay_ms": bc.baseline_delay_ms,
        "baseline_seed": bc.baseline_seed,
    }


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="运行基线实验并输出结果")
    parser.add_argument("--output", default=None, help="输出 JSON 路径")
    parser.add_argument("--duration", type=float, default=20.0, help="仿真时长（秒）")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    output_path = args.output
    if output_path is None:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "baseline_results.json")

    print(f"[Baseline] Running: duration={args.duration}s, seed={args.seed}")
    result = run_baseline(duration_s=args.duration, seed=args.seed)

    m = result["metrics"]
    print(f"  tracking_ratio: {m['tracking_ratio']:.1%}")
    print(f"  angle_rms: {m['angle_error_rms_deg']:.3f} deg")
    print(f"  angle_max: {m['angle_error_max_deg']:.3f} deg")
    print(f"  pixel_rms: {m['pixel_error_rms_px']:.1f} px")
    print(f"  no_divergence: {m['no_divergence']} (slope={m['divergence_slope_deg_per_s']:.4f} deg/s)")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[Baseline] Results saved: {output_path}")


if __name__ == "__main__":
    main()
