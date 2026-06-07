"""30fps vs 60fps 相机帧率对比实验脚本。

三阶段实验：
  Phase A: Kp网格搜索 — 对每个帧率(30/60fps)扫描Kp，找最优值
  Phase B: 多seed对比 — 在各自最优Kp下跑多seed benchmark
  Phase C: 可视化报告 — 生成Kp曲线图、对比表、误差图

用法:
    cd systemSimulation
    conda run -n simulation python tools/frame_rate_experiment.py
    conda run -n simulation python tools/frame_rate_experiment.py --kp-min 0.1 --kp-max 3.0 --kp-step 0.1
    conda run -n simulation python tools/frame_rate_experiment.py --skip-tuning   # 跳过Kp扫描，手动指定Kp
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import csv
import json
import math
from datetime import datetime
from typing import Any

import numpy as np

import config
from simulation.bootstrap import build_runtime
from entities.raspi.tracker_program import BaselineTrackerProgram, TrackerTuning


# ============================================================
# 场景定义（与 run_benchmark.py 保持一致）
# ============================================================

SCENARIOS = {
    "B1": {"delay_ms": 0.0, "description": "基线对照(sin 100m 15m 0.2Hz, 0ms延时)"},
    "B2": {"delay_ms": 26.0, "description": "轻非理想(sin 100m 15m 0.2Hz, 26ms延时)"},
    "B3": {"delay_ms": 52.0, "description": "中难度(sin 80m 20m 0.3Hz, 52ms延时)"},
}

SEEDS = [42, 123, 456, 789, 1024]
FRAME_RATES = [30, 60]


# ============================================================
# 仿真运行与指标采集
# ============================================================

def run_simulation(
    frame_rate_hz: float,
    kp: float,
    delay_ms: float = 0.0,
    duration_s: float = 20.0,
    seed: int = 42,
) -> dict:
    """跑一次仿真，返回帧级数据和汇总指标。"""
    # 设置帧率
    config.camera_cfg.frame_rate_hz = frame_rate_hz

    # 设置目标种子
    np.random.seed(seed)
    config.target_cfg.random_seed = seed

    # 创建控制程序
    tuning = TrackerTuning(yaw_rate_kp_dps_per_px=kp, pitch_rate_kp_dps_per_px=kp)
    program = BaselineTrackerProgram(tuning)

    # 构建运行时
    runtime = build_runtime(
        delay_ms=delay_ms,
        control_program=program,
        obs_mode="research",
    )

    cx = config.camera_cfg.resolution_w / 2.0
    cy = config.camera_cfg.resolution_h / 2.0
    dt = runtime.dt_s
    steps = int(duration_s / dt)

    # 帧级数据采集
    timestamps = []
    pixel_errors_total = []
    pixel_errors_x = []
    pixel_errors_y = []
    in_fov_flags = []
    angle_errors = []
    frame_ids = []

    for _ in range(steps):
        snap = runtime.step(1)
        t = snap.timestamp

        # 几何角度误差
        target_bearing = math.degrees(math.atan2(snap.target["y_m"], snap.target["x_m"]))
        yaw = snap.gimbal["yaw_deg_internal"]
        angle_err = ((target_bearing - yaw + 180) % 360) - 180

        in_fov = bool(snap.camera.get("in_fov", False))
        u_px = float(snap.camera.get("u_px", float("nan")))
        v_px = float(snap.camera.get("v_px", float("nan")))
        frame_id = int(snap.camera.get("frame_id", 0))

        if in_fov and math.isfinite(u_px) and math.isfinite(v_px):
            pe_x = u_px - cx
            pe_y = cy - v_px
            pe_total = math.sqrt(pe_x ** 2 + pe_y ** 2)
        else:
            pe_x = float("nan")
            pe_y = float("nan")
            pe_total = float("nan")

        timestamps.append(t)
        pixel_errors_total.append(pe_total)
        pixel_errors_x.append(pe_x)
        pixel_errors_y.append(pe_y)
        in_fov_flags.append(in_fov)
        angle_errors.append(angle_err)
        frame_ids.append(frame_id)

    # 恢复默认帧率
    config.camera_cfg.frame_rate_hz = 0.0

    ts = np.array(timestamps)
    pe = np.array(pixel_errors_total, dtype=float)
    ae = np.array(angle_errors)
    iv = np.array(in_fov_flags)
    fids = np.array(frame_ids)

    # 稳态指标（t >= 3s）
    stable = (ts >= 3.0) & iv & np.isfinite(pe)
    stable_pe = pe[stable]
    stable_ae = ae[ts >= 3.0]

    rms_px = float(np.sqrt(np.nanmean(stable_pe ** 2))) if len(stable_pe) > 0 else float("nan")
    mean_px = float(np.nanmean(stable_pe)) if len(stable_pe) > 0 else float("nan")
    max_px = float(np.nanmax(stable_pe)) if len(stable_pe) > 0 else float("nan")
    rms_deg = float(np.sqrt(np.nanmean(stable_ae ** 2))) if len(stable_ae) > 0 else float("nan")

    # 跟踪率（稳态）
    stable_iv = iv[ts >= 3.0]
    tracking_rate = float(stable_iv.sum() / max(1, len(stable_iv)))

    # 跟踪效率（稳态误差 < 30px）
    if len(stable_pe) > 0:
        tracking_efficiency = float((stable_pe < 30.0).sum() / len(stable_pe))
    else:
        tracking_efficiency = 0.0

    # 丢锁次数
    lock_loss_count = 0
    was_tracking = False
    for i in range(len(ts)):
        if ts[i] < 3.0:
            continue
        if iv[i] and not was_tracking:
            was_tracking = True
        elif not iv[i] and was_tracking:
            lock_loss_count += 1
            was_tracking = False

    # 有效帧率（frame_id增长率）
    if len(fids) > 10:
        dt_total = ts[-1] - ts[0]
        fid_delta = fids[-1] - fids[0]
        effective_fps = fid_delta / dt_total if dt_total > 0 else 0.0
    else:
        effective_fps = 0.0

    return {
        "rms_pixel_error": rms_px,
        "mean_pixel_error": mean_px,
        "max_pixel_error": max_px,
        "rms_angle_error_deg": rms_deg,
        "tracking_rate": tracking_rate,
        "tracking_efficiency": tracking_efficiency,
        "lock_loss_count": lock_loss_count,
        "effective_fps": effective_fps,
        "timestamps": ts,
        "pixel_errors_total": pe,
        "angle_errors": ae,
        "in_fov_flags": iv,
    }


# ============================================================
# Phase A: Kp 网格搜索
# ============================================================

def phase_a_kp_sweep(kp_min: float, kp_max: float, kp_step: float, duration_s: float) -> dict:
    """对 30fps 和 60fps 分别扫描 Kp，找最优值。"""
    results = {}

    for fps in FRAME_RATES:
        print(f"\n{'=' * 60}")
        print(f"Phase A: Kp 扫描 @ {fps}fps")
        print(f"{'=' * 60}")

        kp_values = np.arange(kp_min, kp_max + kp_step / 2, kp_step)
        sweep = []

        for i, kp in enumerate(kp_values):
            kp = round(float(kp), 4)
            r = run_simulation(frame_rate_hz=fps, kp=kp, delay_ms=0.0, duration_s=duration_s, seed=42)
            sweep.append({"kp": kp, **{k: v for k, v in r.items() if not isinstance(v, np.ndarray)}})
            bar = "#" * int(r["rms_pixel_error"] / 2)
            print(f"  [{i+1:2d}/{len(kp_values)}] Kp={kp:.3f}  RMS={r['rms_pixel_error']:6.2f}px  "
                  f"angle_RMS={r['rms_angle_error_deg']:5.2f}°  track={r['tracking_rate']*100:5.1f}%  "
                  f"eff_fps={r['effective_fps']:.1f}  {bar}")

        # 找最优 Kp（最小 RMS 像素误差）
        sweep_sorted = sorted(sweep, key=lambda x: x["rms_pixel_error"] if math.isfinite(x["rms_pixel_error"]) else 1e9)
        best = sweep_sorted[0]

        print(f"\n  最优 Kp = {best['kp']:.3f}  RMS = {best['rms_pixel_error']:.2f}px  "
              f"angle_RMS = {best['rms_angle_error_deg']:.2f}°  track = {best['tracking_rate']*100:.1f}%")

        results[fps] = {"sweep": sweep, "best_kp": best["kp"], "best_rms": best["rms_pixel_error"]}

    return results


# ============================================================
# Phase B: 多 seed 对比
# ============================================================

def phase_b_comparison(optimal_kps: dict, duration_s: float) -> dict:
    """在各自最优 Kp 下跑多 seed benchmark。"""
    results = {}

    for fps in FRAME_RATES:
        kp = optimal_kps[fps]
        print(f"\n{'=' * 60}")
        print(f"Phase B: 多 seed 对比 @ {fps}fps, Kp={kp:.3f}")
        print(f"{'=' * 60}")

        for scenario_id, scenario in SCENARIOS.items():
            scenario_results = []
            for seed in SEEDS:
                r = run_simulation(
                    frame_rate_hz=fps, kp=kp,
                    delay_ms=scenario["delay_ms"],
                    duration_s=duration_s, seed=seed,
                )
                scenario_results.append({k: v for k, v in r.items() if not isinstance(v, np.ndarray)})
                print(f"  {scenario_id} seed={seed:4d}  RMS={r['rms_pixel_error']:6.2f}px  "
                      f"track={r['tracking_rate']*100:5.1f}%  eff_fps={r['effective_fps']:.1f}")

            # 计算均值
            metrics_keys = ["rms_pixel_error", "mean_pixel_error", "max_pixel_error",
                          "rms_angle_error_deg", "tracking_rate", "tracking_efficiency",
                          "lock_loss_count", "effective_fps"]
            means = {}
            for k in metrics_keys:
                vals = [sr[k] for sr in scenario_results if math.isfinite(sr[k])]
                means[k] = float(np.mean(vals)) if vals else float("nan")

            results[(fps, scenario_id)] = {
                "seeds": scenario_results,
                "means": means,
            }
            print(f"  {scenario_id} 均值: RMS={means['rms_pixel_error']:.2f}px  "
                  f"track={means['tracking_rate']*100:.1f}%  eff_fps={means['effective_fps']:.1f}")

    return results


# ============================================================
# Phase C: 可视化与报告
# ============================================================

def phase_c_visualize(sweep_results: dict, comparison_results: dict, output_dir: str):
    """生成可视化图表和报告。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "kp_tuning"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "comparison"), exist_ok=True)

    # --- Kp 调优曲线 ---
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = {30: "#2196F3", 60: "#FF5722"}
    for fps in FRAME_RATES:
        sweep = sweep_results[fps]["sweep"]
        kps = [s["kp"] for s in sweep]
        rms = [s["rms_pixel_error"] for s in sweep]
        ax.plot(kps, rms, "o-", color=colors[fps], label=f"{fps}fps", markersize=4)
        best_kp = sweep_results[fps]["best_kp"]
        best_rms = sweep_results[fps]["best_rms"]
        ax.plot(best_kp, best_rms, "*", color=colors[fps], markersize=15, zorder=5)
        ax.annotate(f"最优 Kp={best_kp:.2f}\nRMS={best_rms:.1f}px",
                    xy=(best_kp, best_rms), xytext=(best_kp + 0.3, best_rms + 5),
                    fontsize=9, color=colors[fps])
    ax.set_xlabel("Kp (dps/px)")
    ax.set_ylabel("RMS Pixel Error (px)")
    ax.set_title("Kp Tuning: 30fps vs 60fps")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "kp_tuning", "kp_sweep_curve.png"), dpi=150)
    plt.close(fig)

    # --- Kp 扫描 CSV ---
    for fps in FRAME_RATES:
        sweep = sweep_results[fps]["sweep"]
        csv_path = os.path.join(output_dir, "kp_tuning", f"kp_sweep_{fps}fps.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=sweep[0].keys())
            writer.writeheader()
            writer.writerows(sweep)

    # --- 对比柱状图 ---
    metrics_to_plot = ["rms_pixel_error", "tracking_rate", "tracking_efficiency", "effective_fps"]
    metric_labels = ["RMS Pixel Error (px)", "Tracking Rate (%)", "Tracking Efficiency (%)", "Effective FPS"]

    fig, axes = plt.subplots(1, len(metrics_to_plot), figsize=(16, 5))
    x = np.arange(len(SCENARIOS))
    width = 0.35

    for ax, metric, label in zip(axes, metrics_to_plot, metric_labels):
        for i, fps in enumerate(FRAME_RATES):
            vals = []
            for scenario_id in SCENARIOS:
                key = (fps, scenario_id)
                v = comparison_results[key]["means"].get(metric, 0.0)
                if metric in ("tracking_rate", "tracking_efficiency"):
                    v *= 100
                vals.append(v)
            ax.bar(x + i * width, vals, width, label=f"{fps}fps", color=colors[fps], alpha=0.8)
        ax.set_xlabel("Scenario")
        ax.set_ylabel(label)
        ax.set_xticks(x + width / 2)
        ax.set_xticklabels(list(SCENARIOS.keys()))
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")

    fig.suptitle("30fps vs 60fps Performance Comparison (Optimal Kp)", fontsize=14)
    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, "comparison", "metrics_bar_chart.png"), dpi=150)
    plt.close(fig)

    # --- 对比表 CSV ---
    table_path = os.path.join(output_dir, "comparison", "comparison_table.csv")
    metrics_keys = ["rms_pixel_error", "mean_pixel_error", "max_pixel_error",
                   "rms_angle_error_deg", "tracking_rate", "tracking_efficiency",
                   "lock_loss_count", "effective_fps"]
    with open(table_path, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["fps", "scenario", "optimal_kp"] + metrics_keys
        writer.writerow(header)
        for fps in FRAME_RATES:
            kp = sweep_results[fps]["best_kp"]
            for scenario_id in SCENARIOS:
                means = comparison_results[(fps, scenario_id)]["means"]
                row = [fps, scenario_id, f"{kp:.3f}"] + [f"{means.get(k, 0.0):.2f}" for k in metrics_keys]
                writer.writerow(row)

    # --- 报告 ---
    report_path = os.path.join(output_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 30fps vs 60fps 相机帧率对比实验报告\n\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## 1. 实验配置\n\n")
        f.write("| 参数 | 值 |\n|------|----|\n")
        f.write(f"| 仿真时长 | {args.duration}s |\n")
        f.write(f"| Kp扫描范围 | {args.kp_min} ~ {args.kp_max}, 步长 {args.kp_step} |\n")
        f.write(f"| 种子 | {SEEDS} |\n")
        f.write(f"| 算法 | BaselineTrackerProgram (纯Kp控制) |\n")
        f.write(f"| 观测模式 | research |\n")
        f.write(f"| 延迟管线 | 保留默认(读取5ms+处理15ms+发送3ms) |\n\n")

        f.write("## 2. 最优Kp\n\n")
        f.write("| 帧率 | 最优Kp | RMS像素误差 |\n|------|--------|-------------|\n")
        for fps in FRAME_RATES:
            f.write(f"| {fps}fps | {sweep_results[fps]['best_kp']:.3f} | {sweep_results[fps]['best_rms']:.2f}px |\n")
        f.write("\n")

        f.write("## 3. 性能对比（最优Kp下，5种子均值）\n\n")
        f.write("| 帧率 | 场景 | RMS(px) | 角度RMS(°) | 跟踪率 | 跟踪效率 | 有效fps |\n")
        f.write("|------|------|---------|-----------|--------|---------|--------|\n")
        for fps in FRAME_RATES:
            kp = sweep_results[fps]["best_kp"]
            for scenario_id in SCENARIOS:
                m = comparison_results[(fps, scenario_id)]["means"]
                f.write(f"| {fps}fps | {scenario_id} | {m.get('rms_pixel_error',0):.2f} | "
                       f"{m.get('rms_angle_error_deg',0):.2f} | {m.get('tracking_rate',0)*100:.1f}% | "
                       f"{m.get('tracking_efficiency',0)*100:.1f}% | {m.get('effective_fps',0):.1f} |\n")
        f.write("\n")

        f.write("## 4. 结论\n\n")
        # 自动生成结论
        fps30_b1 = comparison_results[(30, "B1")]["means"]
        fps60_b1 = comparison_results[(60, "B1")]["means"]
        rms_30 = fps30_b1.get("rms_pixel_error", 0)
        rms_60 = fps60_b1.get("rms_pixel_error", 0)
        if math.isfinite(rms_30) and math.isfinite(rms_60):
            improvement = (rms_30 - rms_60) / rms_30 * 100
            f.write(f"B1场景下，60fps相比30fps，RMS像素误差{'降低' if improvement > 0 else '升高'}"
                   f" {abs(improvement):.1f}%。\n")
        f.write("\n详见图表：\n")
        f.write("- `kp_tuning/kp_sweep_curve.png` — Kp调优曲线\n")
        f.write("- `comparison/metrics_bar_chart.png` — 性能对比柱状图\n")
        f.write("- `comparison/comparison_table.csv` — 完整数据表\n")

    print(f"\n报告已保存: {report_path}")
    print(f"图表已保存: {output_dir}/")


# ============================================================
# 主入口
# ============================================================

def main():
    global args
    parser = argparse.ArgumentParser(description="30fps vs 60fps 相机帧率对比实验")
    parser.add_argument("--kp-min", type=float, default=0.1, help="Kp扫描下界")
    parser.add_argument("--kp-max", type=float, default=3.0, help="Kp扫描上界")
    parser.add_argument("--kp-step", type=float, default=0.1, help="Kp扫描步长")
    parser.add_argument("--duration", type=float, default=20.0, help="每次仿真时长(秒)")
    parser.add_argument("--output-dir", type=str, default="output/frame_rate_experiment", help="输出目录")
    parser.add_argument("--skip-tuning", action="store_true", help="跳过Kp扫描，使用手动指定值")
    parser.add_argument("--kp-30fps", type=float, default=1.1, help="手动指定30fps的Kp（--skip-tuning时生效）")
    parser.add_argument("--kp-60fps", type=float, default=1.1, help="手动指定60fps的Kp（--skip-tuning时生效）")
    args = parser.parse_args()

    output_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        args.output_dir,
    )

    print("=" * 60)
    print("30fps vs 60fps 相机帧率对比实验")
    print("=" * 60)
    print(f"Kp范围: {args.kp_min} ~ {args.kp_max}, 步长: {args.kp_step}")
    print(f"仿真时长: {args.duration}s")
    print(f"输出目录: {output_dir}")

    # Phase A: Kp 扫描
    if args.skip_tuning:
        print(f"\n跳过Kp扫描，使用手动值: 30fps Kp={args.kp_30fps}, 60fps Kp={args.kp_60fps}")
        sweep_results = {
            30: {"best_kp": args.kp_30fps, "best_rms": float("nan"), "sweep": []},
            60: {"best_kp": args.kp_60fps, "best_rms": float("nan"), "sweep": []},
        }
    else:
        sweep_results = phase_a_kp_sweep(args.kp_min, args.kp_max, args.kp_step, args.duration)

    optimal_kps = {fps: sweep_results[fps]["best_kp"] for fps in FRAME_RATES}

    # Phase B: 多 seed 对比
    comparison_results = phase_b_comparison(optimal_kps, args.duration)

    # Phase C: 可视化与报告
    phase_c_visualize(sweep_results, comparison_results, output_dir)


if __name__ == "__main__":
    main()
