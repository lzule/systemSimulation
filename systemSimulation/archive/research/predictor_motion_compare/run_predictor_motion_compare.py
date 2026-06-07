from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = Path(r"k:\ustc-lizl\Liuwj2Lizl\ALL-Auto\8-simulation\System-APT\systemSimulation")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import scene_cfg, target_cfg
from entities.camera.entity import detect_beacon_centroid
from entities.raspi.atp_state_machine import AtpState
from entities.raspi.trackers.rate_p_tracker import RatePTracker
from runtime.types import wrap_pm180
from simulation.bootstrap import build_runtime

from research.predictor_motion_compare.angle_kalman_predictor import AngleLinearKF
from research.predictor_motion_compare.sine_decomposition_predictor import AngleSineFFTPredictor


@dataclass(frozen=True)
class MotionCase:
    name: str
    title: str
    motion_type: str
    seed: int
    duration_s: float = 12.0
    delay_ms: float = 26.0
    initial_x_m: float = 100.0
    initial_y_m: float = 0.0
    initial_z_m: float = 0.0
    velocity_x_mps: float = 0.0
    velocity_y_mps: float = 0.0
    velocity_z_mps: float = 0.0
    accel_x_mps2: float = 0.0
    accel_y_mps2: float = 0.0
    accel_z_mps2: float = 0.0
    sin_amplitude_m: float = 15.0
    sin_frequency_hz: float = 0.2


@dataclass(frozen=True)
class MethodCase:
    name: str
    title: str
    factory: Callable[[], object | None]


@dataclass
class Sample:
    idx: int
    ts: float
    truth_ts: float
    obs_target_yaw_deg: float
    obs_gimbal_yaw_deg: float
    obs_err_yaw_deg: float
    truth_target_yaw_deg: float
    truth_gimbal_yaw_deg: float
    truth_err_yaw_deg: float
    target_yaw_rate_dps: float
    gimbal_yaw_rate_dps: float
    detected: int
    u_px: float
    cx_px: float
    f_px: float
    yaw_rate_cmd_dps: float


class PredictorAwareRateProgram:
    """只改 predictor 的研究用控制壳，保持 RatePTracker 不变。

    n_steps 按 "总延时 / 当前 obs 间隔" 动态计算：
      total_delay_s = delay_ms + 1 × runtime_dt  (从观测捕获到命令生效)
      n_steps = round(total_delay_s / obs_dt)
    obs_dt 来自实际相邻 on_tick 调用的时间戳差，
    因为延时管线的存在，它通常不等于 runtime_dt。
    """

    def __init__(
        self,
        predictor: object | None,
        delay_ms: float,
        runtime_dt_s: float,
    ) -> None:
        self.tracker = RatePTracker()
        self.predictor = predictor
        self.obs_samples: list[dict] = []
        self._idx = 0
        self._total_delay_s = float(delay_ms) / 1000.0 + float(runtime_dt_s)
        self._last_ts: Optional[float] = None
        self._fallback_n_steps = max(1, int(round(self._total_delay_s / float(runtime_dt_s))))

    def on_tick(self, obs: dict):
        ts = float(obs.get("timestamp", float("nan")))
        if self._last_ts is None or not math.isfinite(self._last_ts) or not math.isfinite(ts):
            n_steps = self._fallback_n_steps
        else:
            obs_dt = max(ts - self._last_ts, 1e-6)
            n_steps = max(1, int(round(self._total_delay_s / obs_dt)))
        self._last_ts = ts

        frame = obs.get("frame")
        det = detect_beacon_centroid(frame.image) if frame is not None else None
        if self.predictor is not None:
            self.predictor.update(obs, det)
            prediction = self.predictor.predict(n_steps=n_steps)
        else:
            prediction = None

        commands = self.tracker.compute_commands(obs, AtpState.TRACK_COARSE, prediction)
        yaw_rate_cmd_dps = 0.0
        for cmd in reversed(commands):
            if cmd.target == "gimbal" and cmd.action == "set_rate_target":
                yaw_rate_cmd_dps = float(cmd.payload.get("yaw_rate", 0.0))
                break

        self.obs_samples.append(
            {
                "idx": self._idx,
                "ts": ts,
                "truth_ts": ts,
                "obs": obs,
                "det": det,
                "yaw_rate_cmd_dps": yaw_rate_cmd_dps,
            }
        )
        self._idx += 1
        return commands


def _apply_case(case: MotionCase) -> dict[str, object]:
    backup: dict[str, object] = {
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
        "sin_z_amplitude_m": target_cfg.sin_z_amplitude_m,
        "sin_z_frequency_hz": target_cfg.sin_z_frequency_hz,
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


def _restore_case(backup: dict[str, object]) -> None:
    for key, value in backup.items():
        setattr(target_cfg, key, value)


def _obs_angle(obs: dict, det) -> tuple[float, float, float]:
    frame = obs.get("frame")
    gimbal = obs.get("gimbal") or {}
    intrinsics = getattr(frame, "intrinsics", {}) or {}
    cx = float(intrinsics.get("cx", float("nan")))
    f_px = float(intrinsics.get("f_px", float("nan")))
    gimbal_yaw = float(gimbal.get("yaw_deg_internal", float("nan")))
    if det is None or not det.found or det.cx is None or not math.isfinite(cx) or not math.isfinite(f_px) or f_px <= 0.0:
        return float("nan"), gimbal_yaw, float("nan")
    target_yaw = wrap_pm180(gimbal_yaw + math.degrees(math.atan2(float(det.cx) - cx, f_px)))
    err = wrap_pm180(target_yaw - gimbal_yaw)
    return target_yaw, gimbal_yaw, err


def _truth_angle(snapshot) -> tuple[float, float, float, float, float]:
    target = snapshot.target or {}
    gimbal = snapshot.gimbal or {}
    target_yaw = float(target.get("azimuth_deg", float("nan")))
    gimbal_yaw = float(gimbal.get("yaw_deg_internal", float("nan")))
    x = float(target.get("x_m", float("nan")))
    y = float(target.get("y_m", float("nan")))
    vx = float(target.get("vx_mps", float("nan")))
    vy = float(target.get("vy_mps", float("nan")))
    denom = x * x + y * y
    if math.isfinite(x) and math.isfinite(y) and math.isfinite(vx) and math.isfinite(vy) and denom > 1e-12:
        target_rate = math.degrees((x * vy - y * vx) / denom)
    else:
        target_rate = float("nan")
    gimbal_rate = float(gimbal.get("yaw_rate_dps", float("nan")))
    err = wrap_pm180(target_yaw - gimbal_yaw) if math.isfinite(target_yaw) and math.isfinite(gimbal_yaw) else float("nan")
    return target_yaw, gimbal_yaw, err, target_rate, gimbal_rate


def _match_snapshot(snapshot_index, snapshots, truth_ts: float):
    if not snapshots or not math.isfinite(truth_ts):
        return None
    exact = snapshot_index.get(round(float(truth_ts), 9))
    if exact is not None:
        return exact
    best = min(snapshots, key=lambda s: abs(float(s.timestamp) - truth_ts))
    if abs(float(best.timestamp) - truth_ts) > 1e-6:
        raise RuntimeError(
            f"无法按时间戳对齐观测与真值: obs_ts={truth_ts:.9f}, nearest_snapshot_ts={float(best.timestamp):.9f}"
        )
    return best


def _mid_window(samples: list[Sample], seconds: float) -> tuple[float, float]:
    ts = [s.ts for s in samples if math.isfinite(s.truth_target_yaw_deg)]
    if not ts:
        ts = [s.ts for s in samples]
    if not ts:
        return 0.0, seconds
    start, end = min(ts), max(ts)
    if end - start <= seconds:
        return start, end
    center = 0.5 * (start + end)
    return max(start, center - seconds / 2.0), min(end, center + seconds / 2.0)


def _plot_motion_bundle(
    samples_by_method: list[tuple[MethodCase, list[Sample]]],
    path: Path,
    title: str,
    window: Optional[tuple[float, float]] = None,
) -> None:
    rows = len(samples_by_method)
    fig, axes = plt.subplots(rows, 2, figsize=(13.5, 3.6 * rows), sharex=True, constrained_layout=True)
    if rows == 1:
        axes = np.array([axes])

    for row, (method, samples) in enumerate(samples_by_method):
        ts = np.array([s.ts for s in samples], dtype=float)
        target = np.array([s.truth_target_yaw_deg for s in samples], dtype=float)
        gimbal = np.array([s.truth_gimbal_yaw_deg for s in samples], dtype=float)
        err = np.array([s.truth_err_yaw_deg for s in samples], dtype=float)

        ax0 = axes[row, 0]
        ax1 = axes[row, 1]

        ax0.plot(ts, target, label="target yaw", color="#c62828", linewidth=1.7)
        ax0.plot(ts, gimbal, label="gimbal yaw", color="#1565c0", linewidth=1.7)
        ax0.set_ylabel("angle (deg)")
        ax0.set_title(method.title)
        ax0.grid(True, alpha=0.25)
        ax0.legend(loc="best")

        ax1.plot(ts, err, label="truth error", color="#ef6c00", linewidth=1.6)
        ax1.axhline(0.0, color="#888a85", linestyle="--", linewidth=1.0)
        ax1.set_ylabel("error (deg)")
        ax1.grid(True, alpha=0.25)
        ax1.legend(loc="best")

        if window is not None:
            ax0.set_xlim(*window)
            ax1.set_xlim(*window)

    axes[-1, 0].set_xlabel("time (s)")
    axes[-1, 1].set_xlabel("time (s)")
    fig.suptitle(title)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _run_case(motion: MotionCase, method: MethodCase) -> list[Sample]:
    backup = _apply_case(motion)
    rng_state = np.random.get_state()
    np.random.seed(motion.seed)
    try:
        predictor = method.factory()
        program = PredictorAwareRateProgram(
            predictor=predictor,
            delay_ms=motion.delay_ms,
            runtime_dt_s=float(scene_cfg.dt_s),
        )
        runtime = build_runtime(delay_ms=motion.delay_ms, control_program=program, obs_mode="realistic")
        steps = max(1, int(motion.duration_s / runtime.dt_s))
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
            frame = obs.get("frame")
            intrinsics = getattr(frame, "intrinsics", {}) or {}
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
                    cx_px=float(intrinsics.get("cx", float("nan"))),
                    f_px=float(intrinsics.get("f_px", float("nan"))),
                    yaw_rate_cmd_dps=float(item["yaw_rate_cmd_dps"]),
                )
            )
        return samples
    finally:
        np.random.set_state(rng_state)
        _restore_case(backup)


def _write_case_csv(samples: list[Sample], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(samples[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(s) for s in samples)


def _summarize_case(motion: MotionCase, method: MethodCase, samples: list[Sample], window_seconds: float) -> dict[str, object]:
    truth_err = np.array([s.truth_err_yaw_deg for s in samples], dtype=float)
    obs_err = np.array([s.obs_err_yaw_deg for s in samples], dtype=float)
    detected = np.array([s.detected for s in samples], dtype=float)
    mask = np.isfinite(truth_err)
    mid_start, mid_end = _mid_window(samples, window_seconds)
    mid_mask = np.array([(mid_start <= s.ts <= mid_end) and math.isfinite(s.truth_err_yaw_deg) for s in samples], dtype=bool)

    truth_abs = np.abs(truth_err[mask])
    obs_abs = np.abs(obs_err[np.isfinite(obs_err)])
    mid_truth_abs = np.abs(truth_err[mid_mask])
    mid_obs_abs = np.abs(obs_err[np.array([(mid_start <= s.ts <= mid_end) and math.isfinite(s.obs_err_yaw_deg) for s in samples], dtype=bool)])

    return {
        "motion": motion.name,
        "method": method.name,
        "samples": len(samples),
        "detected_rate": float(np.mean(detected)) if len(detected) else float("nan"),
        "truth_err_mean_abs": float(np.mean(truth_abs)) if len(truth_abs) else float("nan"),
        "truth_err_rms": float(np.sqrt(np.mean(truth_abs ** 2))) if len(truth_abs) else float("nan"),
        "mid3s_truth_err_mean_abs": float(np.mean(mid_truth_abs)) if len(mid_truth_abs) else float("nan"),
        "mid3s_truth_err_rms": float(np.sqrt(np.mean(mid_truth_abs ** 2))) if len(mid_truth_abs) else float("nan"),
        "obs_err_mean_abs": float(np.mean(obs_abs)) if len(obs_abs) else float("nan"),
        "obs_err_rms": float(np.sqrt(np.mean(obs_abs ** 2))) if len(obs_abs) else float("nan"),
        "mid3s_obs_err_mean_abs": float(np.mean(mid_obs_abs)) if len(mid_obs_abs) else float("nan"),
        "mid3s_obs_err_rms": float(np.sqrt(np.mean(mid_obs_abs ** 2))) if len(mid_obs_abs) else float("nan"),
    }


def _build_motions() -> list[MotionCase]:
    return [
        MotionCase(
            name="sinusoidal",
            title="Sinusoidal motion",
            motion_type="sinusoidal",
            seed=4201,
            initial_x_m=100.0,
            initial_y_m=0.0,
            initial_z_m=0.0,
            sin_amplitude_m=15.0,
            sin_frequency_hz=0.2,
        ),
        MotionCase(
            name="constant_velocity",
            title="Constant velocity motion",
            motion_type="constant_velocity",
            seed=4202,
            initial_x_m=100.0,
            initial_y_m=-15.0,
            initial_z_m=0.0,
            velocity_x_mps=0.0,
            velocity_y_mps=2.5,
            velocity_z_mps=0.0,
        ),
        MotionCase(
            name="constant_accel",
            title="Constant acceleration motion",
            motion_type="constant_accel",
            seed=4203,
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


def _build_methods() -> list[MethodCase]:
    return [
        MethodCase(name="no_prediction", title="No prediction", factory=lambda: None),
        MethodCase(name="kalman", title="Angle-domain Kalman", factory=AngleLinearKF),
        MethodCase(name="sine_decomp", title="Angle-domain Sine FFT", factory=AngleSineFFTPredictor),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="compare no-prediction / kalman / sine-decomposition under realistic motion")
    parser.add_argument("--output-root", default=r"k:\ustc-lizl\Liuwj2Lizl\ALL-Auto\8-simulation\System-APT\systemSimulation\research\predictor_motion_compare\output")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--delay-ms", type=float, default=26.0)
    parser.add_argument("--zoom-seconds", type=float, default=3.0)
    parser.add_argument("--motions", nargs="*", default=None, choices=["sinusoidal", "constant_velocity", "constant_accel"])
    parser.add_argument("--methods", nargs="*", default=None, choices=["no_prediction", "kalman", "sine_decomp"])
    args = parser.parse_args()

    motions = _build_motions()
    methods = _build_methods()
    if args.motions:
        motions = [m for m in motions if m.name in set(args.motions)]
    if args.methods:
        methods = [m for m in methods if m.name in set(args.methods)]
    motions = [
        replace(motion, duration_s=args.duration, delay_ms=args.delay_ms)
        for motion in motions
    ]

    out_root = Path(args.output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    out_dir = out_root / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_predictor_motion_compare"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, object]] = []
    summary_lines: list[str] = []

    for motion in motions:
        motion_dir = out_dir / motion.name
        motion_dir.mkdir(parents=True, exist_ok=True)
        case_results: list[tuple[MethodCase, list[Sample]]] = []

        for method in methods:
            samples = _run_case(motion, method)
            case_results.append((method, samples))
            _write_case_csv(samples, motion_dir / f"{method.name}_raw.csv")
            summary_rows.append(_summarize_case(motion, method, samples, args.zoom_seconds))

        window = _mid_window(case_results[0][1], args.zoom_seconds) if case_results else None
        _plot_motion_bundle(case_results, motion_dir / f"{motion.name}_overview.png", f"{motion.title} | overview", None)
        _plot_motion_bundle(case_results, motion_dir / f"{motion.name}_mid3s.png", f"{motion.title} | middle 3s", window)

        motion_rows = [r for r in summary_rows if r["motion"] == motion.name]
        ranked = sorted(motion_rows, key=lambda r: r["mid3s_truth_err_mean_abs"])
        summary_lines.append(f"[{motion.name}] {motion.title}")
        for row in ranked:
            summary_lines.append(
                f"  {row['method']}: mid3s_truth_err_mean_abs={row['mid3s_truth_err_mean_abs']:.4f}, "
                f"truth_err_mean_abs={row['truth_err_mean_abs']:.4f}, detected_rate={row['detected_rate']:.3f}"
            )
        summary_lines.append(f"  best={ranked[0]['method']}")
        summary_lines.append("")

    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    (out_dir / "summary.txt").write_text(
        "\n".join(
            [
                "predictor motion compare summary",
                "",
                f"output: {out_dir}",
                f"duration: {args.duration:.1f}s",
                f"delay: {args.delay_ms:.1f}ms",
                f"obs_mode: realistic",
                f"zoom_seconds: {args.zoom_seconds:.1f}",
                "",
                "note: mid3s is the main visual check; overview is for context.",
                "",
                *summary_lines,
            ]
        ),
        encoding="utf-8",
    )

    print(out_dir)


if __name__ == "__main__":
    main()
