"""树莓派跟踪器 Kp 自动扫参工具。

扫描不同 Kp 值，跑离线仿真，输出跟踪误差对比表，找到最优 Kp。

用法:
    cd systemSimulation
    python tools/tune_tracker_kp.py
    python tools/tune_tracker_kp.py --kp-min 0.02 --kp-max 0.20 --kp-step 0.01
    python tools/tune_tracker_kp.py --duration 10
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import math

import numpy as np

from simulation.bootstrap import build_runtime
from entities.raspi.tracker_program import BaselineTrackerProgram, TrackerTuning


def run_one_kp(kp: float, duration_s: float = 20.0) -> dict:
    """跑一次仿真，返回跟踪指标。"""
    tuning = TrackerTuning(yaw_rate_kp_dps_per_px=kp)
    runtime = build_runtime(control_program=BaselineTrackerProgram(tuning))

    angle_errors = []
    pixel_errors = []
    steps = int(duration_s / runtime.dt_s)

    for _ in range(steps):
        snap = runtime.step(1)
        t = snap.timestamp
        target_bearing = math.degrees(math.atan2(snap.target["y_m"], snap.target["x_m"]))
        yaw = snap.gimbal["yaw_deg_internal"]
        angle_err = ((target_bearing - yaw + 180) % 360) - 180
        angle_errors.append(abs(angle_err))

        if snap.camera["in_fov"]:
            cx = snap.camera.get("u_px", float("nan"))
            if math.isfinite(cx):
                pixel_errors.append(abs(cx - 320))

    ae = np.array(angle_errors)
    pe = np.array(pixel_errors) if pixel_errors else np.array([0.0])

    return {
        "kp": kp,
        "angle_rms": float(np.sqrt((ae ** 2).mean())),
        "angle_mean": float(ae.mean()),
        "angle_max": float(ae.max()),
        "pixel_rms": float(np.sqrt((pe ** 2).mean())) if len(pixel_errors) > 0 else 0.0,
        "pixel_mean": float(pe.mean()) if len(pixel_errors) > 0 else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description="树莓派跟踪器 Kp 自动扫参")
    parser.add_argument("--kp-min", type=float, default=0.02, help="Kp 扫描下界")
    parser.add_argument("--kp-max", type=float, default=0.30, help="Kp 扫描上界")
    parser.add_argument("--kp-step", type=float, default=0.01, help="Kp 扫描步长")
    parser.add_argument("--duration", type=float, default=20.0, help="每次仿真时长(秒)")
    args = parser.parse_args()

    kp_values = np.arange(args.kp_min, args.kp_max + args.kp_step / 2, args.kp_step)
    print(f"Kp 扫参: {args.kp_min:.3f} ~ {args.kp_max:.3f}, 步长 {args.kp_step:.3f}, 共 {len(kp_values)} 组, 每组 {args.duration:.0f}s\n")

    results = []
    for i, kp in enumerate(kp_values):
        kp = round(float(kp), 4)
        r = run_one_kp(kp, args.duration)
        results.append(r)
        bar = "#" * int(r["angle_rms"] * 5)
        print(f"  [{i + 1:2d}/{len(kp_values)}] Kp={kp:.3f}  angle_rms={r['angle_rms']:6.2f}°  max={r['angle_max']:6.2f}°  px_rms={r['pixel_rms']:6.1f}  {bar}")

    # 按角度误差 RMS 排序
    results.sort(key=lambda x: x["angle_rms"])

    print(f"\n{'=' * 75}")
    print(f"{'排名':>4s}  {'Kp':>6s}  {'角度RMS(°)':>10s}  {'角度均值(°)':>10s}  {'角度最大(°)':>10s}  {'像素RMS':>8s}")
    print(f"{'-' * 75}")
    for i, r in enumerate(results):
        marker = " <<<" if i == 0 else ""
        print(f"{i + 1:4d}  {r['kp']:6.3f}  {r['angle_rms']:10.2f}  {r['angle_mean']:10.2f}  {r['angle_max']:10.2f}  {r['pixel_rms']:8.1f}{marker}")

    best = results[0]
    print(f"\n最优 Kp = {best['kp']:.3f}  角度 RMS = {best['angle_rms']:.2f}°  最大 = {best['angle_max']:.2f}°")
    print(f"\n将 config.py 中 tracker_tuning_cfg.yaw_rate_kp_dps_per_px 改为 {best['kp']:.3f}")


if __name__ == "__main__":
    main()
