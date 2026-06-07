from __future__ import annotations

import csv
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = Path(r"k:\ustc-lizl\Liuwj2Lizl\ALL-Auto\8-simulation\System-APT\systemSimulation")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import target_cfg
from research.tracking_truth_analysis.run_truth_analysis import (
    BaseOnlyProgram,
    Sample,
    _match_snapshot,
    _obs_angle,
    _truth_angle,
)
from simulation.bootstrap import build_runtime


@dataclass
class MotionCase:
    name: str
    title: str
    duration_s: float
    delay_ms: float
    obs_mode: str
    motion_type: str
    initial_x_m: float
    initial_y_m: float
    initial_z_m: float
    velocity_x_mps: float = 0.0
    velocity_y_mps: float = 0.0
    velocity_z_mps: float = 0.0
    accel_x_mps2: float = 0.0
    accel_y_mps2: float = 0.0
    accel_z_mps2: float = 0.0
    sin_amplitude_m: float = 15.0
    sin_frequency_hz: float = 0.2


def _apply_case(case: MotionCase) -> dict[str, float]:
    """保存旧配置并写入本轮实验配置，结束后用于恢复。"""
    backup = {
        "motion_type": target_cfg.motion_type,
        "initial_x_m": target_cfg.initial_x_m,
        "initial_y_m": target_cfg.initial_y_m,
        "initial_z_m": target_cfg.initial_z_m,
        "velocity_x_mps": target_cfg.velocity_x_mps,
        "velocity_y_mps": target_cfg.velocity_y_mps,
        "velocity_z_mps": target_cfg.velocity_z_mps,
        "accel_x_mps2": target_cfg.accel_x_mps2,
        "accel_y_mps2": target_cfg.accel_y_mps2,
        "accel_z_mps2": target_cfg.accel_z_mps2,
        "sin_amplitude_m": target_cfg.sin_amplitude_m,
        "sin_frequency_hz": target_cfg.sin_frequency_hz,
    }
    target_cfg.motion_type = case.motion_type
    target_cfg.initial_x_m = case.initial_x_m
    target_cfg.initial_y_m = case.initial_y_m
    target_cfg.initial_z_m = case.initial_z_m
    target_cfg.velocity_x_mps = case.velocity_x_mps
    target_cfg.velocity_y_mps = case.velocity_y_mps
    target_cfg.velocity_z_mps = case.velocity_z_mps
    target_cfg.accel_x_mps2 = case.accel_x_mps2
    target_cfg.accel_y_mps2 = case.accel_y_mps2
    target_cfg.accel_z_mps2 = case.accel_z_mps2
    target_cfg.sin_amplitude_m = case.sin_amplitude_m
    target_cfg.sin_frequency_hz = case.sin_frequency_hz
    return backup


def _restore_case(backup: dict[str, float]) -> None:
    for key, value in backup.items():
        setattr(target_cfg, key, value)


def _run_case(case: MotionCase) -> list[Sample]:
    backup = _apply_case(case)
    try:
        program = BaseOnlyProgram()
        runtime = build_runtime(delay_ms=case.delay_ms, control_program=program, obs_mode=case.obs_mode)
        steps = max(1, int(case.duration_s / runtime.dt_s))
        snapshots = [runtime.step(1) for _ in range(steps)]
        snapshot_index = {round(float(s.timestamp), 9): s for s in snapshots}

        samples: list[Sample] = []
        for i, item in enumerate(program.obs_samples):
            obs = item["obs"]
            det = item["det"]
            truth_ts = float(item["truth_ts"])
            snap = _match_snapshot(snapshot_index, snapshots, truth_ts)
            obs_target_yaw, obs_gimbal_yaw, obs_err = _obs_angle(obs, det)
            truth_target_yaw, truth_gimbal_yaw, truth_err, target_rate, gimbal_rate = _truth_angle(snap)
            samples.append(
                Sample(
                    idx=i,
                    ts=float(item["ts"]),
                    truth_ts=float(snap.timestamp),
                    obs_target_yaw_deg=obs_target_yaw,
                    obs_gimbal_yaw_deg=obs_gimbal_yaw,
                    obs_err_yaw_deg=obs_err,
                    truth_target_yaw_deg=truth_target_yaw,
                    truth_gimbal_yaw_deg=truth_gimbal_yaw,
                    truth_err_yaw_deg=truth_err,
                    target_yaw_rate_dps=target_rate,
                    gimbal_yaw_rate_dps=gimbal_rate,
                    detected=1 if det is not None and det.found else 0,
                    u_px=float(det.cx) if det is not None and det.found and det.cx is not None else float("nan"),
                    cx_px=float((getattr(obs.get("frame"), "intrinsics", {}) or {}).get("cx", float("nan"))),
                    f_px=float((getattr(obs.get("frame"), "intrinsics", {}) or {}).get("f_px", float("nan"))),
                    yaw_rate_cmd_dps=float(item["yaw_rate_cmd_dps"]),
                )
            )
        return samples
    finally:
        _restore_case(backup)


def _mid_window_mask(samples: list[Sample], seconds: float = 3.0) -> np.ndarray:
    """取有效观测时间范围正中间的一段窗口，用于局部放大观察。"""
    ts = np.array([s.ts for s in samples], dtype=float)
    detected = np.array([s.detected for s in samples], dtype=int)
    valid_ts = ts[np.isfinite(ts) & (detected == 1)]
    if valid_ts.size == 0:
        valid_ts = ts[np.isfinite(ts)]
    if valid_ts.size == 0:
        return np.zeros(len(samples), dtype=bool)

    center = float(valid_ts[0] + valid_ts[-1]) * 0.5
    half = seconds * 0.5
    mask = (ts >= center - half) & (ts <= center + half)
    if np.any(mask):
        return mask

    nearest_idx = int(np.nanargmin(np.abs(ts - center)))
    fallback = np.zeros(len(samples), dtype=bool)
    fallback[nearest_idx] = True
    return fallback


def _plot_case_view(samples: list[Sample], case: MotionCase, out_path: Path, mask: np.ndarray, title_suffix: str) -> None:
    """按给定时间窗口出图，上图看目标角和云台角，下图看跟踪误差。"""
    ts_all = np.array([s.ts for s in samples], dtype=float)
    target_all = np.array([s.truth_target_yaw_deg for s in samples], dtype=float)
    gimbal_all = np.array([s.truth_gimbal_yaw_deg for s in samples], dtype=float)
    err_all = np.array([s.truth_err_yaw_deg for s in samples], dtype=float)

    ts = ts_all[mask]
    target = target_all[mask]
    gimbal = gimbal_all[mask]
    err = err_all[mask]

    fig, axes = plt.subplots(2, 1, figsize=(11, 6.8), sharex=True, constrained_layout=True)
    axes[0].plot(ts, target, label="target yaw", color="#c62828", linewidth=1.8)
    axes[0].plot(ts, gimbal, label="gimbal yaw", color="#1565c0", linewidth=1.8)
    axes[0].set_title(f"{case.title}{title_suffix}")
    axes[0].set_ylabel("angle (deg)")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend(loc="best")

    axes[1].plot(ts, err, label="target - gimbal", color="#ef6c00", linewidth=1.7)
    axes[1].axhline(0.0, color="#888a85", linestyle="--", linewidth=1.0)
    axes[1].set_xlabel("time (s)")
    axes[1].set_ylabel("error (deg)")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend(loc="best")
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def _plot_case(samples: list[Sample], case: MotionCase, out_dir: Path) -> None:
    """同时输出全程图和中间 3 秒放大图。"""
    full_mask = np.ones(len(samples), dtype=bool)
    mid_mask = _mid_window_mask(samples, seconds=3.0)
    _plot_case_view(samples, case, out_dir / f"{case.name}_truth_yaw.png", full_mask, "")
    _plot_case_view(
        samples,
        case,
        out_dir / f"{case.name}_truth_yaw_mid3s.png",
        mid_mask,
        " | middle 3s zoom",
    )


def _write_case_csv(samples: list[Sample], case: MotionCase, out_dir: Path) -> None:
    path = out_dir / f"{case.name}_raw.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(samples[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(s) for s in samples)


def _summary(samples: list[Sample], case: MotionCase) -> str:
    truth_err = np.array([s.truth_err_yaw_deg for s in samples], dtype=float)
    target = np.array([s.truth_target_yaw_deg for s in samples], dtype=float)
    gimbal = np.array([s.truth_gimbal_yaw_deg for s in samples], dtype=float)

    mask = np.isfinite(truth_err)
    truth_abs = np.abs(truth_err[mask])
    peak_target_idx = int(np.nanargmax(target))
    peak_gimbal_idx = int(np.nanargmax(gimbal))
    trough_target_idx = int(np.nanargmin(target))
    trough_gimbal_idx = int(np.nanargmin(gimbal))
    peak_dt = float(samples[peak_gimbal_idx].ts - samples[peak_target_idx].ts)
    trough_dt = float(samples[trough_gimbal_idx].ts - samples[trough_target_idx].ts)

    lines = [
        f"[{case.name}] {case.title}",
        f"motion_type={case.motion_type}",
        f"samples={len(samples)}",
        f"truth_err_mean_abs={float(np.mean(truth_abs)) if len(truth_abs) else float('nan'):.4f}",
        f"truth_err_rms={float(np.sqrt(np.mean(truth_abs ** 2))) if len(truth_abs) else float('nan'):.4f}",
        f"target_peak_t={samples[peak_target_idx].ts:.4f}",
        f"gimbal_peak_t={samples[peak_gimbal_idx].ts:.4f}",
        f"peak_dt_gimbal_minus_target={peak_dt:.4f}",
        f"target_trough_t={samples[trough_target_idx].ts:.4f}",
        f"gimbal_trough_t={samples[trough_gimbal_idx].ts:.4f}",
        f"trough_dt_gimbal_minus_target={trough_dt:.4f}",
        "note=periodic motion may make global peak timing misleading; use the mid3s zoom image as the main visual check.",
    ]
    return "\n".join(lines)


def main() -> None:
    out_root = Path(r"k:\ustc-lizl\Liuwj2Lizl\ALL-Auto\8-simulation\System-APT\systemSimulation\research\tracking_truth_analysis\output")
    out_root.mkdir(parents=True, exist_ok=True)
    out_dir = out_root / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_motion_compare"
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = [
        MotionCase(
            name="sinusoidal",
            title="Sinusoidal Target | truth yaw vs gimbal yaw",
            duration_s=12.0,
            delay_ms=26.0,
            obs_mode="realistic",
            motion_type="sinusoidal",
            initial_x_m=100.0,
            initial_y_m=0.0,
            initial_z_m=0.0,
            sin_amplitude_m=15.0,
            sin_frequency_hz=0.2,
        ),
        MotionCase(
            name="constant_velocity",
            title="Constant Velocity Target | truth yaw vs gimbal yaw",
            duration_s=12.0,
            delay_ms=26.0,
            obs_mode="realistic",
            motion_type="constant_velocity",
            initial_x_m=100.0,
            initial_y_m=-15.0,
            initial_z_m=0.0,
            velocity_x_mps=0.0,
            velocity_y_mps=2.5,
            velocity_z_mps=0.0,
        ),
        MotionCase(
            name="constant_accel",
            title="Constant Accel Target | truth yaw vs gimbal yaw",
            duration_s=12.0,
            delay_ms=26.0,
            obs_mode="realistic",
            motion_type="constant_accel",
            initial_x_m=100.0,
            initial_y_m=-15.0,
            initial_z_m=0.0,
            velocity_x_mps=0.0,
            velocity_y_mps=0.6,
            velocity_z_mps=0.0,
            accel_x_mps2=0.0,
            accel_y_mps2=0.25,
            accel_z_mps2=0.0,
        ),
    ]

    summaries: list[str] = []
    for case in cases:
        samples = _run_case(case)
        _write_case_csv(samples, case, out_dir)
        _plot_case(samples, case, out_dir)
        summaries.append(_summary(samples, case))

    (out_dir / "summary.txt").write_text("\n\n".join(summaries), encoding="utf-8")
    print(out_dir)


if __name__ == "__main__":
    main()
