from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = Path(r"k:\ustc-lizl\Liuwj2Lizl\ALL-Auto\8-simulation\System-APT\systemSimulation")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import target_cfg
from entities.camera.entity import detect_beacon_centroid
from entities.raspi.trackers.rate_p_tracker import RatePTracker
from runtime.types import wrap_pm180
from simulation.bootstrap import build_runtime


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


class BaseOnlyProgram:
    """只使用当前 base 速率控制。"""

    def __init__(self) -> None:
        self.tracker = RatePTracker()
        self.obs_samples: list[dict] = []
        self._idx = 0

    @staticmethod
    def _angle_from_pixels(delta_px: float, f_px: float) -> float:
        return math.degrees(math.atan2(delta_px, f_px))

    def on_tick(self, obs: dict):
        frame = obs.get("frame")
        det = detect_beacon_centroid(frame.image) if frame is not None else None
        commands = self.tracker.compute_commands(obs, None, None)
        yaw_rate_cmd_dps = 0.0
        for cmd in reversed(commands):
            if cmd.target == "gimbal" and cmd.action == "set_rate_target":
                yaw_rate_cmd_dps = float(cmd.payload.get("yaw_rate", 0.0))
                break

        self.obs_samples.append(
            {
                "idx": self._idx,
                "ts": float(obs.get("timestamp", float("nan"))),
                # realistic 模式下 obs["target"] 会被清空，所以真值对齐必须回到观测包自己的时间戳。
                "truth_ts": float(obs.get("timestamp", float("nan"))),
                "obs": obs,
                "det": det,
                "yaw_rate_cmd_dps": yaw_rate_cmd_dps,
            }
        )
        self._idx += 1
        return commands


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
    # 这里需要的是“目标方位角角速度”，不能把平面线速度直接当成角速度。
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
            f"无法按时间戳对齐观测与真值快照: obs_ts={truth_ts:.9f}, nearest_snapshot_ts={float(best.timestamp):.9f}"
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


def _plot(samples: list[Sample], path: Path, title: str, mode: str, window: Optional[tuple[float, float]] = None) -> None:
    ts = np.array([s.ts for s in samples], dtype=float)
    if mode == "obs":
        target = np.array([s.obs_target_yaw_deg for s in samples], dtype=float)
        gimbal = np.array([s.obs_gimbal_yaw_deg for s in samples], dtype=float)
        err = np.array([s.obs_err_yaw_deg for s in samples], dtype=float)
        err_label = "obs error"
        ylab = "obs angle (deg)"
    else:
        target = np.array([s.truth_target_yaw_deg for s in samples], dtype=float)
        gimbal = np.array([s.truth_gimbal_yaw_deg for s in samples], dtype=float)
        err = np.array([s.truth_err_yaw_deg for s in samples], dtype=float)
        err_label = "truth error"
        ylab = "truth angle (deg)"

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, constrained_layout=True)
    axes[0].plot(ts, target, label="target yaw", color="#c62828", linewidth=1.7)
    axes[0].plot(ts, gimbal, label="gimbal yaw", color="#1565c0", linewidth=1.7)
    axes[0].set_ylabel(ylab)
    axes[0].set_title(title)
    axes[0].grid(True, alpha=0.25)
    axes[0].legend(loc="best")

    axes[1].plot(ts, err, label=err_label, color="#ef6c00", linewidth=1.6)
    axes[1].axhline(0.0, color="#888a85", linestyle="--", linewidth=1.0)
    axes[1].set_xlabel("time (s)")
    axes[1].set_ylabel("error (deg)")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend(loc="best")

    if window is not None:
        for ax in axes:
            ax.set_xlim(*window)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3 or len(b) < 3:
        return float("nan")
    if np.allclose(a, a[0]) or np.allclose(b, b[0]):
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _scatter(x: np.ndarray, y: np.ndarray, path: Path, title: str, xlabel: str, ylabel: str) -> None:
    fig, ax = plt.subplots(1, 1, figsize=(7.2, 5.4), constrained_layout=True)
    ax.scatter(x, y, s=10, alpha=0.65, color="#1565c0")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="truth view analysis for base tracker")
    parser.add_argument("--output-root", default=r"k:\ustc-lizl\Liuwj2Lizl\ALL-Auto\8-simulation\System-APT\systemSimulation\research\tracking_truth_analysis\output")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--delay-ms", type=float, default=26.0)
    parser.add_argument("--obs-mode", default="realistic", choices=["debug", "research", "realistic"])
    parser.add_argument("--zoom-seconds", type=float, default=3.0)
    args = parser.parse_args()

    # 目标轨迹只作为仿真输入，不作为分析前提。
    target_cfg.motion_type = "sinusoidal"
    target_cfg.sin_amplitude_m = 15.0
    target_cfg.sin_frequency_hz = 0.2

    out_root = Path(args.output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    out_dir = out_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    program = BaseOnlyProgram()
    runtime = build_runtime(delay_ms=args.delay_ms, control_program=program, obs_mode=args.obs_mode)
    steps = max(1, int(args.duration / runtime.dt_s))
    snapshots = []
    for _ in range(steps):
        snapshots.append(runtime.step(1))
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
                cx_px=float(getattr(getattr(obs.get("frame"), "intrinsics", {}) or {}, "get", lambda *_: float("nan"))("cx")),
                f_px=float((getattr(obs.get("frame"), "intrinsics", {}) or {}).get("f_px", float("nan"))),
                yaw_rate_cmd_dps=float(item["yaw_rate_cmd_dps"]),
            )
        )

    write_path = out_dir / "base_truth_analysis_raw.csv"
    with write_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(samples[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(s) for s in samples)

    window = _mid_window(samples, args.zoom_seconds)
    _plot(samples, out_dir / "obs_yaw_overview.png", "obs view | target vs gimbal", "obs")
    _plot(samples, out_dir / "obs_yaw_mid3s.png", "obs view | target vs gimbal (mid 3s)", "obs", window)
    _plot(samples, out_dir / "truth_yaw_overview.png", "truth view | target vs gimbal", "truth")
    _plot(samples, out_dir / "truth_yaw_mid3s.png", "truth view | target vs gimbal (mid 3s)", "truth", window)

    truth_err = np.array([s.truth_err_yaw_deg for s in samples], dtype=float)
    obs_err = np.array([s.obs_err_yaw_deg for s in samples], dtype=float)
    target_rate = np.array([s.target_yaw_rate_dps for s in samples], dtype=float)
    gimbal_rate = np.array([s.gimbal_yaw_rate_dps for s in samples], dtype=float)
    finite_diag = np.isfinite(truth_err) & np.isfinite(obs_err) & np.isfinite(target_rate) & np.isfinite(gimbal_rate)
    _scatter(
        np.abs(target_rate[finite_diag]),
        np.abs(truth_err[finite_diag]),
        out_dir / "truth_error_vs_target_rate.png",
        "truth error vs target rate",
        "|target yaw rate| (deg/s)",
        "|truth error| (deg)",
    )
    _scatter(
        np.abs(gimbal_rate[finite_diag]),
        np.abs(truth_err[finite_diag]),
        out_dir / "truth_error_vs_gimbal_rate.png",
        "truth error vs gimbal rate",
        "|gimbal yaw rate| (deg/s)",
        "|truth error| (deg)",
    )
    _scatter(
        np.abs(obs_err[np.isfinite(obs_err)]),
        np.abs(truth_err[np.isfinite(truth_err)]),
        out_dir / "obs_error_vs_truth_error.png",
        "obs error vs truth error",
        "|obs error| (deg)",
        "|truth error| (deg)",
    )

    finite = np.isfinite(truth_err) & np.isfinite(obs_err) & np.isfinite(target_rate) & np.isfinite(gimbal_rate)
    truth_err_abs = np.abs(truth_err[np.isfinite(truth_err)])
    obs_err_abs = np.abs(obs_err[np.isfinite(obs_err)])
    target_rate_abs = np.abs(target_rate[np.isfinite(target_rate)])
    gimbal_rate_abs = np.abs(gimbal_rate[np.isfinite(gimbal_rate)])
    lines = [
        "truth view analysis summary",
        "",
        f"output: {out_dir}",
        f"duration: {args.duration:.1f}s",
        f"delay: {args.delay_ms:.1f}ms",
        f"obs_mode: {args.obs_mode}",
        f"samples: {len(samples)}",
        f"obs_truth_err_mean_abs: {float(np.mean(obs_err_abs)) if len(obs_err_abs) else float('nan'):.4f}",
        f"truth_err_mean_abs: {float(np.mean(truth_err_abs)) if len(truth_err_abs) else float('nan'):.4f}",
        f"truth_err_rms: {float(np.sqrt(np.mean(truth_err_abs ** 2))) if len(truth_err_abs) else float('nan'):.4f}",
        f"corr_abs_trutherr_targetrate: {_corr(np.abs(truth_err[finite]), np.abs(target_rate[finite])):.4f}",
        f"corr_abs_trutherr_gimbalrate: {_corr(np.abs(truth_err[finite]), np.abs(gimbal_rate[finite])):.4f}",
    ]
    (out_dir / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
    print(out_dir)


if __name__ == "__main__":
    main()
