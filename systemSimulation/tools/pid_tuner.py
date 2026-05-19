"""Runtime-based PID tuner.

Usage:
    python tools/pid_tuner.py
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import camera_cfg, target_cfg
from entities.camera.entity import detect_beacon_centroid
from runtime.digital_twin_runtime import DigitalTwinRuntime

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output",
    "pid_tuner.png",
)
os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)


@dataclass
class Candidate:
    label: str
    kp: float
    ki: float
    kd: float


PID_CANDIDATES = [
    Candidate("0 Aggressive", 0.675, 0.00, 0.00),
    Candidate("1 Aggressive", 0.675, 0.60, 0.00),
    Candidate("2 Aggressive", 0.675, 0.60, 0.01),
]


def wrap_pm180(angle_deg: float) -> float:
    return (angle_deg + 180.0) % 360.0 - 180.0


def compute_metrics(data: dict, stable_from_s: float) -> dict:
    t = data["t"]
    px_err = data["delayed_pixel_error"]
    ang_err = data["true_angle_error_deg"]
    track = data["tracking"].astype(bool)
    yaw = data["yaw_deg_internal"]

    mask = (t >= stable_from_s) & track & np.isfinite(px_err)
    metrics = {
        "rms_px": np.nan,
        "rms_deg": np.nan,
        "max_px": np.nan,
        "track_ratio": float(track.sum() / max(1, len(track))),
        "settle_s": np.nan,
        "yaw_span_deg": float(np.nanmax(yaw) - np.nanmin(yaw)) if len(yaw) else 0.0,
    }
    if np.any(mask):
        metrics["rms_px"] = float(np.sqrt(np.mean(px_err[mask] ** 2)))
        metrics["rms_deg"] = float(np.sqrt(np.mean(ang_err[mask] ** 2)))
        metrics["max_px"] = float(np.nanmax(np.abs(px_err[mask])))

    win = 30
    for i in range(max(0, len(t) - win)):
        if np.all(np.isfinite(px_err[i : i + win])) and np.all(np.abs(px_err[i : i + win]) < 10):
            metrics["settle_s"] = float(t[i])
            break
    return metrics


def run_candidate(candidate: Candidate, duration_s: float, stable_from_s: float) -> tuple[dict, dict]:
    rt = DigitalTwinRuntime()
    rt.gimbal_client.power_on()
    rt.camera_client.power_on()
    rt.raspi_client.power_on()
    rt.step(400)

    rt.gimbal_client.set_mode("RATE_MODE", rt.t)
    rt.step(4)

    integ = 0.0
    prev_e = 0.0

    samples = {
        "t": [],
        "delayed_pixel_error": [],
        "true_angle_error_deg": [],
        "tracking": [],
        "target_bearing_deg": [],
        "gimbal_angle_deg": [],
        "yaw_deg_internal": [],
        "pid_output_dps": [],
    }

    n_steps = int(duration_s / rt.dt_s)
    for _ in range(n_steps):
        snap = rt.step(1)
        frame = rt.camera_client.get_frame()
        found = False
        px_err = math.nan
        yaw_rate_cmd = 0.0
        if frame is not None:
            det = detect_beacon_centroid(frame.image, threshold=camera_cfg.detection_threshold)
            if det.found:
                found = True
                px_err = float(det.cx - frame.intrinsics["cx"])
                integ += px_err * rt.dt_s
                deriv = (px_err - prev_e) / rt.dt_s
                prev_e = px_err
                yaw_rate_cmd = candidate.kp * px_err + candidate.ki * integ + candidate.kd * deriv
                yaw_rate_cmd = max(-60.0, min(60.0, yaw_rate_cmd))
                rt.gimbal_client.set_rate_target(yaw_rate_cmd, 0.0, snap.timestamp)
            else:
                integ *= 0.98
                rt.gimbal_client.set_rate_target(0.0, 0.0, snap.timestamp)

        yaw_internal = float(snap.gimbal["yaw_deg_internal"])
        target_bearing = float(snap.target["bearing_deg"])
        true_angle_err = wrap_pm180(target_bearing - yaw_internal)

        samples["t"].append(float(snap.timestamp))
        samples["delayed_pixel_error"].append(px_err)
        samples["true_angle_error_deg"].append(true_angle_err)
        samples["tracking"].append(bool(found))
        samples["target_bearing_deg"].append(target_bearing)
        samples["gimbal_angle_deg"].append(float(snap.gimbal["yaw_deg_display"]))
        samples["yaw_deg_internal"].append(yaw_internal)
        samples["pid_output_dps"].append(float(yaw_rate_cmd))

    arr = {k: np.array(v) for k, v in samples.items()}
    metrics = compute_metrics(arr, stable_from_s=stable_from_s)
    return arr, metrics


def render_report(records: list[tuple[str, dict]], metrics_list: list[tuple[Candidate, dict]], output_path: str) -> None:
    fig = plt.figure(figsize=(17, 12))
    fig.suptitle(
        (
            f"Runtime PID Tuner | f={camera_cfg.focal_length_mm}mm "
            f"FOV={camera_cfg.fov_h_deg:.1f}deg px/deg={camera_cfg.px_per_deg:.1f} "
            f"motion={target_cfg.motion_type}"
        ),
        fontsize=11,
        fontweight="bold",
    )

    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=0.5, wspace=0.30, left=0.07, right=0.97, top=0.92, bottom=0.07)
    ax_px = fig.add_subplot(gs[0, :])
    ax_angle = fig.add_subplot(gs[1, 0])
    ax_cmd = fig.add_subplot(gs[1, 1])
    ax_stat = fig.add_subplot(gs[2, :])

    colors = ["#1565C0", "#C62828", "#2E7D32", "#E65100", "#6A1B9A"]
    for i, (label, data) in enumerate(records):
        color = colors[i % len(colors)]
        ax_px.plot(data["t"], data["delayed_pixel_error"], color=color, label=label)
        ax_angle.plot(data["t"], data["target_bearing_deg"], color=color, linestyle="--", alpha=0.45)
        ax_angle.plot(data["t"], data["gimbal_angle_deg"], color=color, label=label)
        ax_cmd.plot(data["t"], data["pid_output_dps"], color=color, label=label)

    for ax, ylabel, title in [
        (ax_px, "Pixel error (px)", "Pixel Error"),
        (ax_angle, "Angle (deg)", "Tracking (dashed=target, solid=gimbal)"),
        (ax_cmd, "Vel command (deg/s)", "PID Output"),
    ]:
        ax.set_xlabel("Time (s)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.axhline(0, color="#888888", linewidth=0.8)
        ax.grid(True)
        ax.legend(fontsize=8, loc="upper right")

    ax_stat.axis("off")
    col_labels = ["PID Params", "RMS px", "RMS deg", "Max px", "Settle", "Track ratio", "Yaw span"]
    rows = []
    for c, m in metrics_list:
        rows.append(
            [
                f"Kp={c.kp} Ki={c.ki} Kd={c.kd}",
                f"{m['rms_px']:.2f}" if not np.isnan(m["rms_px"]) else "---",
                f"{m['rms_deg']:.3f}" if not np.isnan(m["rms_deg"]) else "---",
                f"{m['max_px']:.1f}" if not np.isnan(m["max_px"]) else "---",
                f"{m['settle_s']:.2f}s" if not np.isnan(m["settle_s"]) else "---",
                f"{m['track_ratio']*100:.1f}%",
                f"{m['yaw_span_deg']:.1f}",
            ]
        )
    tbl = ax_stat.table(cellText=rows, colLabels=col_labels, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.9)
    ax_stat.set_title("Performance Metrics", pad=10, fontweight="bold")

    plt.savefig(output_path, dpi=140, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def run_all(
    output_path: str = OUTPUT_PATH,
    duration_s: float = 15.0,
    stable_from_s: float = 3.0,
    candidates: list[Candidate] | None = None,
    render_plot: bool = True,
) -> list[tuple[Candidate, dict]]:
    candidates = candidates or PID_CANDIDATES
    print("=" * 60)
    print("Runtime PID Tuner")
    print(
        f"f={camera_cfg.focal_length_mm}mm, motion={target_cfg.motion_type}, "
        f"duration={duration_s}s, candidates={len(candidates)}"
    )
    print("-" * 60)

    records: list[tuple[str, dict]] = []
    metrics_list: list[tuple[Candidate, dict]] = []

    for c in candidates:
        print(f"[{c.label}] Kp={c.kp} Ki={c.ki} Kd={c.kd} ...", end="", flush=True)
        data, metrics = run_candidate(c, duration_s=duration_s, stable_from_s=stable_from_s)
        records.append((c.label, data))
        metrics_list.append((c, metrics))
        rms = f"{metrics['rms_px']:.2f}" if not np.isnan(metrics["rms_px"]) else "N/A"
        settle = f"{metrics['settle_s']:.2f}s" if not np.isnan(metrics["settle_s"]) else "N/A"
        print(f" RMS={rms} settle={settle} track={metrics['track_ratio']*100:.1f}%")

    if render_plot:
        render_report(records, metrics_list, output_path=output_path)
        print(f"Saved: {output_path}")

    valid = [(idx, m["rms_px"]) for idx, (_, m) in enumerate(metrics_list) if not np.isnan(m["rms_px"])]
    if valid:
        best_idx = min(valid, key=lambda x: x[1])[0]
        best = candidates[best_idx]
        print(f"Best: [{best.label}] Kp={best.kp} Ki={best.ki} Kd={best.kd}")
    print("=" * 60)
    return metrics_list


def main() -> None:
    parser = argparse.ArgumentParser(description="Runtime PID tuner")
    parser.add_argument("--duration", type=float, default=15.0, help="duration in seconds")
    parser.add_argument("--stable-from", type=float, default=3.0, help="metrics stable window start second")
    parser.add_argument("--output", default=OUTPUT_PATH, help="output plot path")
    args = parser.parse_args()
    run_all(output_path=args.output, duration_s=args.duration, stable_from_s=args.stable_from)


if __name__ == "__main__":
    main()
