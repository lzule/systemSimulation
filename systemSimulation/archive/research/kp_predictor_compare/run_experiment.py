"""Kp + 角度预测对比实验。

对比三种控制方法在两种延时水平下的跟踪表现：
  - base:     纯 Kp，无预测
  - kalman:   Kp + Kalman 角度域预测 (四时段管道)
  - fft_sine: Kp + FFT 正弦预测 (四时段管道)

用法:
    cd systemSimulation
    conda run -n simulation python research/kp_predictor_compare/run_experiment.py
    conda run -n simulation python research/kp_predictor_compare/run_experiment.py --delays 26 50
    conda run -n simulation python research/kp_predictor_compare/run_experiment.py --duration 12
"""
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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import target_cfg, tracker_tuning_cfg
from entities.camera.entity import detect_beacon_centroid
from entities.raspi.atp_state_machine import AtpState
from entities.raspi.trackers.rate_p_tracker import RatePTracker
from runtime.types import Command, wrap_pm180
from simulation.bootstrap import build_runtime

from research.kp_predictor_compare.predictors import (
    KalmanAnglePredictor,
    FFTSineAnglePredictor,
    angle_to_pixel_error,
)


# ── 数据记录 ────────────────────────────────────────────────────

@dataclass
class Sample:
    idx: int
    ts: float
    gimbal_yaw: float
    target_yaw: float
    err_yaw: float
    detected: int
    yaw_rate_cmd: float
    method: str


# ── 控制程序 ────────────────────────────────────────────────────

class ExperimentProgram:
    """实验用控制程序。

    base 方法：直接用 RatePTracker (无预测)。
    kalman / fft_sine：四时段管道 → 预测目标角度 → 转为像素误差 → RatePTracker。

    时段 4 不做云台积分，误差 = predicted_target_angle - gimbal_angle_from_obs。
    """

    def __init__(self, method: str = "base"):
        self.method = method
        self.tracker = RatePTracker()
        self.samples: list[Sample] = []
        self._idx = 0

        if method == "kalman":
            self.predictor = KalmanAnglePredictor()
        elif method == "fft_sine":
            self.predictor = FFTSineAnglePredictor()
        else:
            self.predictor = None

    def on_tick(self, obs: dict) -> list[Command]:
        ts = float(obs.get("timestamp", 0.0))
        frame = obs.get("frame")
        gimbal = obs.get("gimbal") or {}
        intrinsics = getattr(frame, "intrinsics", {}) or {}

        # 检测
        det = detect_beacon_centroid(frame.image) if frame is not None else None
        found = det is not None and det.found and det.cx is not None

        gimbal_yaw = float(gimbal.get("yaw_deg_internal", float("nan")))
        cx = float(intrinsics.get("cx", float("nan")))
        f_px = float(intrinsics.get("f_px", float("nan")))
        cy = float(intrinsics.get("cy", float("nan")))
        gimbal_pitch = float(gimbal.get("pitch_deg", float("nan")))

        # 预测器更新
        prediction = None
        if self.predictor is not None:
            self.predictor.update(obs, det)

            # 估算 horizon: 从 obs_dt 自动估算，不预设延时
            p_dt = self.predictor.obs_dt
            if p_dt is not None and p_dt > 0 and found:
                pred_angle = self.predictor.predict_angle(p_dt)
                if pred_angle is not None:
                    pred_yaw, pred_pitch = pred_angle
                    # 时段 4: 误差 = 预测目标角度 - 云台当前角度 (从 obs)
                    if math.isfinite(gimbal_yaw) and math.isfinite(gimbal_pitch):
                        pe_u, pe_v = angle_to_pixel_error(
                            pred_yaw, pred_pitch,
                            gimbal_yaw, gimbal_pitch,
                            cx, cy, f_px,
                        )
                        # 包装成 RatePTracker 期望的 prediction 格式
                        prediction = (cx + pe_u, cy + pe_v)

        # 控制命令
        commands = self.tracker.compute_commands(obs, AtpState.TRACK_COARSE, prediction)

        # 提取速率命令
        yaw_rate_cmd = 0.0
        for cmd in reversed(commands):
            if cmd.target == "gimbal" and cmd.action == "set_rate_target":
                yaw_rate_cmd = float(cmd.payload.get("yaw_rate", 0.0))
                break

        # 记录采样
        target_yaw = float("nan")
        err_yaw = float("nan")
        if found and math.isfinite(gimbal_yaw) and math.isfinite(cx) and math.isfinite(f_px) and f_px > 0:
            rel = math.degrees(math.atan2(float(det.cx) - cx, f_px))
            target_yaw = wrap_pm180(gimbal_yaw + rel)
            err_yaw = wrap_pm180(target_yaw - gimbal_yaw)

        self.samples.append(Sample(
            idx=self._idx, ts=ts,
            gimbal_yaw=gimbal_yaw,
            target_yaw=target_yaw,
            err_yaw=err_yaw,
            detected=1 if found else 0,
            yaw_rate_cmd=yaw_rate_cmd,
            method=self.method,
        ))
        self._idx += 1
        return commands


# ── 实验运行 ────────────────────────────────────────────────────

def run_single(
    method: str,
    motion: str,
    delay_ms: float,
    duration: float,
    seed: int,
) -> list[Sample]:
    """跑单组实验并返回采样数据。"""
    np.random.seed(seed)
    target_cfg.motion_type = motion
    prog = ExperimentProgram(method=method)
    rt = build_runtime(delay_ms=delay_ms, control_program=prog, obs_mode="realistic")
    steps = max(1, int(duration / rt.dt_s))
    for _ in range(steps):
        rt.step(1)
    return prog.samples


def compute_metrics(samples: list[Sample], zoom_s: float) -> dict:
    """计算跟踪指标。"""
    err = np.array([s.err_yaw for s in samples], dtype=float)
    det = np.array([s.detected for s in samples])
    ts = np.array([s.ts for s in samples])

    finite = np.isfinite(err)
    fe = err[finite]
    detected_rate = float(det.mean()) if len(det) > 0 else 0.0

    # 全程指标
    full_mae = float(np.mean(np.abs(fe))) if fe.size > 0 else float("nan")
    full_rms = float(np.sqrt(np.mean(fe ** 2))) if fe.size > 0 else float("nan")

    # 中间 zoom_s 秒指标
    valid_ts = ts[finite]
    mid_mae = full_mae
    if valid_ts.size > 0 and valid_ts[-1] - valid_ts[0] > zoom_s:
        center = 0.5 * (valid_ts[0] + valid_ts[-1])
        left = center - zoom_s / 2
        right = center + zoom_s / 2
        mask = finite & (ts >= left) & (ts <= right)
        mid_err = err[mask]
        if mid_err.size > 0:
            mid_mae = float(np.mean(np.abs(mid_err)))

    return {
        "samples": len(samples),
        "detected_rate": detected_rate,
        "full_mae_deg": full_mae,
        "full_rms_deg": full_rms,
        "mid_mae_deg": mid_mae,
    }


# ── 绘图 ────────────────────────────────────────────────────────

def zoom_bounds(samples: list[Sample], zoom_s: float) -> Optional[tuple[float, float]]:
    valid = [s.ts for s in samples if math.isfinite(s.err_yaw)]
    if not valid:
        return None
    lo, hi = min(valid), max(valid)
    if hi - lo <= zoom_s:
        return (lo, hi)
    c = 0.5 * (lo + hi)
    l, r = c - zoom_s / 2, c + zoom_s / 2
    if l < lo:
        r += lo - l
        l = lo
    if r > hi:
        l -= r - hi
        r = hi
    return (l, r)


def plot_comparison(
    all_samples: dict[str, list[Sample]],
    output_dir: Path,
    title_prefix: str,
    zoom_s: float,
) -> None:
    """多方法对比图 (上半: 目标角 vs 云台角, 下半: 误差)。"""
    colors = {"base": "#204a87", "kalman": "#cc0000", "fft_sine": "#4e9a06"}
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True, constrained_layout=True)

    for method, samples in all_samples.items():
        ts = np.array([s.ts for s in samples])
        tgt = np.array([s.target_yaw for s in samples], dtype=float)
        gmb = np.array([s.gimbal_yaw for s in samples], dtype=float)
        err = np.array([s.err_yaw for s in samples], dtype=float)
        c = colors.get(method, "#888888")
        lbl = method

        axes[0].plot(ts, tgt, color=c, linewidth=1.5, alpha=0.7, linestyle="--", label=f"{lbl} target")
        axes[0].plot(ts, gmb, color=c, linewidth=1.2, alpha=0.9, label=f"{lbl} gimbal")
        axes[1].plot(ts, err, color=c, linewidth=1.3, label=lbl)

    axes[0].set_ylabel("angle (deg)")
    axes[0].set_title(f"{title_prefix} — target vs gimbal yaw")
    axes[0].legend(loc="best", fontsize=8, ncol=2)
    axes[0].grid(True, alpha=0.25)

    axes[1].axhline(0, color="#888a85", linestyle="--", linewidth=0.8)
    axes[1].set_xlabel("time (s)")
    axes[1].set_ylabel("error (deg)")
    axes[1].set_title(f"{title_prefix} — tracking error")
    axes[1].legend(loc="best", fontsize=8)
    axes[1].grid(True, alpha=0.25)

    zb = zoom_bounds(list(all_samples.values())[0], zoom_s)
    if zb:
        fig2, ax2 = plt.subplots(1, 1, figsize=(12, 4), constrained_layout=True)
        for method, samples in all_samples.items():
            ts = np.array([s.ts for s in samples])
            err = np.array([s.err_yaw for s in samples], dtype=float)
            c = colors.get(method, "#888888")
            ax2.plot(ts, err, color=c, linewidth=1.5, label=method)
        ax2.axhline(0, color="#888a85", linestyle="--", linewidth=0.8)
        ax2.set_xlim(zb)
        ax2.set_xlabel("time (s)")
        ax2.set_ylabel("error (deg)")
        ax2.set_title(f"{title_prefix} — error mid {zoom_s:.0f}s")
        ax2.legend(loc="best", fontsize=8)
        ax2.grid(True, alpha=0.25)
        fig2.savefig(output_dir / f"comparison_mid{int(zoom_s)}s.png", dpi=150)
        plt.close(fig2)

    fig.savefig(output_dir / "comparison_overview.png", dpi=150)
    plt.close(fig)


# ── CSV ──────────────────────────────────────────────────────────

def write_csv(path: Path, samples: list[Sample]) -> None:
    if not samples:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(samples[0]).keys()))
        w.writeheader()
        for s in samples:
            w.writerow(asdict(s))


# ── 主流程 ──────────────────────────────────────────────────────

METHODS = ["base", "kalman", "fft_sine"]
MOTIONS = ["sinusoidal", "constant_velocity", "constant_accel"]
MOTION_LABELS = {
    "sinusoidal": "正弦运动",
    "constant_velocity": "匀速运动",
    "constant_accel": "匀加速运动",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Kp + 角度预测对比实验")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--delays", nargs="+", type=float, default=[26.0, 50.0])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--zoom-seconds", type=float, default=3.0)
    parser.add_argument("--methods", nargs="+", default=METHODS, choices=METHODS)
    parser.add_argument("--motions", nargs="+", default=MOTIONS, choices=MOTIONS)
    args = parser.parse_args()

    output_root = Path(__file__).resolve().parent / "output"
    output_root.mkdir(parents=True, exist_ok=True)
    ts_dir = output_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    ts_dir.mkdir(parents=True, exist_ok=True)

    all_metrics: list[dict] = []

    for delay_ms in args.delays:
        delay_dir = ts_dir / f"delay_{int(delay_ms):03d}ms"
        delay_dir.mkdir(exist_ok=True)
        for motion in args.motions:
            motion_dir = delay_dir / motion
            motion_dir.mkdir(exist_ok=True)

            all_samples: dict[str, list[Sample]] = {}
            for method in args.methods:
                print(f"  running {method} / {motion} / {delay_ms:.0f}ms ...", flush=True)
                samples = run_single(method, motion, delay_ms, args.duration, args.seed)
                all_samples[method] = samples
                write_csv(motion_dir / f"{method}_raw.csv", samples)

                m = compute_metrics(samples, args.zoom_seconds)
                m["method"] = method
                m["motion"] = motion
                m["delay_ms"] = delay_ms
                all_metrics.append(m)

            # 对比图
            plot_comparison(
                all_samples, motion_dir,
                f"{MOTION_LABELS.get(motion, motion)} / {delay_ms:.0f}ms",
                args.zoom_seconds,
            )

    # ── 汇总 ──
    summary_lines = [
        "Kp + 角度预测对比实验",
        "",
        f"输出目录: {ts_dir}",
        f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"仿真时长: {args.duration:.1f}s",
        f"延时水平: {args.delays} ms",
        f"观测模式: realistic",
        f"随机种子: {args.seed}",
        f"局部放大: mid {args.zoom_seconds:.0f}s",
        "",
        "指标说明:",
        "- full_mae: 全程平均绝对误差 (deg)",
        "- mid_mae: 中间 N 秒平均绝对误差 (deg)",
        "- detected_rate: 目标检出率",
        "",
    ]

    for delay_ms in args.delays:
        summary_lines.append(f"═══ delay = {delay_ms:.0f} ms ═══")
        for motion in args.motions:
            summary_lines.append(f"  [{MOTION_LABELS.get(motion, motion)}]")
            for method in args.methods:
                row = next(
                    r for r in all_metrics
                    if r["method"] == method and r["motion"] == motion and r["delay_ms"] == delay_ms
                )
                summary_lines.append(
                    f"    {method:10s}: mid_mae={row['mid_mae_deg']:.4f}°  "
                    f"full_mae={row['full_mae_deg']:.4f}°  "
                    f"det={row['detected_rate']:.3f}"
                )
            # 找最优
            rows = [r for r in all_metrics if r["motion"] == motion and r["delay_ms"] == delay_ms]
            best = min(rows, key=lambda r: r["mid_mae_deg"])
            summary_lines.append(f"    → 最优: {best['method']} (mid_mae={best['mid_mae_deg']:.4f}°)")
            summary_lines.append("")

    summary_txt = "\n".join(summary_lines)
    (ts_dir / "summary.txt").write_text(summary_txt, encoding="utf-8")
    print(summary_txt)

    # CSV 汇总
    if all_metrics:
        with (ts_dir / "summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(all_metrics[0].keys()))
            w.writeheader()
            for row in all_metrics:
                w.writerow(row)

    print(f"\n结果输出到: {ts_dir}")


if __name__ == "__main__":
    main()
