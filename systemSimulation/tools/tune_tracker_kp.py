"""树莓派跟踪器 Kp 自动扫参工具（黄金分割搜索 + pitch 敏感性验证）。

搜索流程：
  Phase 1: 一维黄金分割搜索 yaw_kp（固定 pitch_kp=默认值）
  Phase 2: 多 seed 验证最优 yaw_kp
  Phase 3: pitch_kp 敏感性检查

使用快速相机模式（fast_camera=True）加速仿真，加速比 ~170×。

用法:
    cd systemSimulation
    conda run -n simulation python tools/tune_tracker_kp.py
    conda run -n simulation python tools/tune_tracker_kp.py --kp-min 0.3 --kp-max 3.0 --tolerance 0.05
    conda run -n simulation python tools/tune_tracker_kp.py --duration 10 --no-fast
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import math

import numpy as np

from simulation.bootstrap import build_runtime
from entities.raspi.tracker_program import BaselineTrackerProgram, TrackerTuning


# 黄金分割比例
_PHI = (1.0 + math.sqrt(5.0)) / 2.0
_RESPTOL = 1e-6  # 黄金分割收敛残差


def run_one_kp(yaw_kp: float, pitch_kp: float, duration_s: float = 20.0,
               seed: int = 42, fast_camera: bool = True) -> dict:
    """跑一次仿真，返回跟踪指标。"""
    np.random.seed(seed)
    tuning = TrackerTuning(yaw_rate_kp_dps_per_px=yaw_kp, pitch_rate_kp_dps_per_px=pitch_kp)
    runtime = build_runtime(control_program=BaselineTrackerProgram(tuning), fast_camera=fast_camera)

    pixel_errors = []
    angle_errors = []
    steps = int(duration_s / runtime.dt_s)

    for _ in range(steps):
        snap = runtime.step(1)
        if snap.timestamp < 3.0:
            continue

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
        "yaw_kp": yaw_kp,
        "pitch_kp": pitch_kp,
        "seed": seed,
        "angle_rms": float(np.sqrt((ae ** 2).mean())),
        "angle_mean": float(ae.mean()),
        "angle_max": float(ae.max()),
        "pixel_rms": float(np.sqrt((pe ** 2).mean())) if len(pixel_errors) > 0 else 0.0,
        "pixel_mean": float(pe.mean()) if len(pixel_errors) > 0 else 0.0,
    }


def golden_section_search(eval_fn, lo: float, hi: float, tolerance: float = 0.1,
                          max_iter: int = 50) -> tuple[float, float, list[dict]]:
    """一维黄金分割搜索，最小化 eval_fn。

    Returns:
        (best_x, best_val, history) 其中 history 为所有评估记录。
    """
    history = []

    # 初始两个内点
    c = hi - (hi - lo) / _PHI
    d = lo + (hi - lo) / _PHI

    fc = eval_fn(c)
    fd = eval_fn(d)
    history.append(fc)
    history.append(fd)

    n_iter = 2
    while abs(hi - lo) > tolerance and n_iter < max_iter:
        if fc["pixel_rms"] < fd["pixel_rms"]:
            hi = d
            d = c
            fd = fc
            c = hi - (hi - lo) / _PHI
            fc = eval_fn(c)
            history.append(fc)
        else:
            lo = c
            c = d
            fc = fd
            d = lo + (hi - lo) / _PHI
            fd = eval_fn(d)
            history.append(fd)
        n_iter += 1

    best = min(history, key=lambda r: r["pixel_rms"])
    return best["yaw_kp"], best["pixel_rms"], history


def main():
    parser = argparse.ArgumentParser(description="树莓派跟踪器 Kp 自动扫参（黄金分割搜索）")
    parser.add_argument("--kp-min", type=float, default=0.3, help="yaw_kp 搜索下界")
    parser.add_argument("--kp-max", type=float, default=5.0, help="yaw_kp 搜索上界")
    parser.add_argument("--tolerance", type=float, default=0.05, help="黄金分割收敛精度")
    parser.add_argument("--pitch-kp", type=float, default=1.1, help="固定的 pitch_kp 值")
    parser.add_argument("--duration", type=float, default=20.0, help="每次仿真时长(秒)")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 123, 456, 789, 1024],
                        help="多 seed 验证用的种子列表")
    parser.add_argument("--no-fast", action="store_true", help="禁用快速相机模式")
    args = parser.parse_args()

    fast_camera = not args.no_fast

    print("=" * 70)
    print("Kp 黄金分割搜索")
    print("=" * 70)
    print(f"yaw_kp 范围: [{args.kp_min:.3f}, {args.kp_max:.3f}], 精度: {args.tolerance:.3f}")
    print(f"pitch_kp: {args.pitch_kp:.3f} (固定)")
    print(f"duration: {args.duration:.0f}s, fast_camera: {fast_camera}")
    print()

    # Phase 1: 一维黄金分割搜索 yaw_kp
    print("--- Phase 1: 黄金分割搜索 yaw_kp ---")

    def eval_yaw_kp(kp):
        r = run_one_kp(kp, args.pitch_kp, args.duration, seed=42, fast_camera=fast_camera)
        bar = "#" * max(1, int(r["pixel_rms"] / 2))
        print(f"  yaw_kp={kp:.4f}  rms={r['pixel_rms']:6.2f}px  angle_rms={r['angle_rms']:5.2f}°  {bar}")
        return r

    best_kp, best_rms, phase1_history = golden_section_search(
        eval_yaw_kp, args.kp_min, args.kp_max, args.tolerance
    )
    print(f"\nPhase 1 完成: {len(phase1_history)} 次评估")
    print(f"  最优 yaw_kp ≈ {best_kp:.4f}, rms ≈ {best_rms:.2f}px")

    # Phase 2: 多 seed 验证
    print(f"\n--- Phase 2: 多 seed 验证 (yaw_kp={best_kp:.4f}) ---")
    phase2_results = []
    for seed in args.seeds:
        r = run_one_kp(best_kp, args.pitch_kp, args.duration, seed=seed, fast_camera=fast_camera)
        phase2_results.append(r)
        print(f"  seed={seed:4d}  rms={r['pixel_rms']:6.2f}px  angle_rms={r['angle_rms']:5.2f}°")

    rms_values = [r["pixel_rms"] for r in phase2_results]
    mean_rms = float(np.mean(rms_values))
    std_rms = float(np.std(rms_values))
    print(f"  RMS: {mean_rms:.2f} ± {std_rms:.2f}px")

    # Phase 3: pitch_kp 敏感性检查
    print(f"\n--- Phase 3: pitch_kp 敏感性检查 ---")
    pitch_test_values = [max(0.3, args.pitch_kp * 0.6), args.pitch_kp, args.pitch_kp * 1.5]
    pitch_results = {}
    for pkp in pitch_test_values:
        rms_list = []
        for seed in args.seeds:
            r = run_one_kp(best_kp, pkp, args.duration, seed=seed, fast_camera=fast_camera)
            rms_list.append(r["pixel_rms"])
        pitch_results[pkp] = float(np.mean(rms_list))
        print(f"  pitch_kp={pkp:.3f}  mean_rms={pitch_results[pkp]:.2f}px")

    # 判断 pitch 敏感性
    pitch_rms_range = max(pitch_results.values()) - min(pitch_results.values())
    pitch_sensitive = pitch_rms_range > mean_rms * 0.05
    print(f"  RMS 范围: {pitch_rms_range:.2f}px ({'敏感' if pitch_sensitive else '不敏感'})")

    # 最终结果
    print("\n" + "=" * 70)
    print("最终结果")
    print("=" * 70)
    print(f"最优 yaw_kp:   {best_kp:.4f}")
    print(f"最优 pitch_kp: {args.pitch_kp:.3f} ({'需进一步搜索' if pitch_sensitive else '不敏感，默认值即可'})")
    print(f"RMS (多seed):  {mean_rms:.2f} ± {std_rms:.2f}px")
    print(f"总仿真次数:   {len(phase1_history) + len(phase2_results) + len(pitch_test_values) * len(args.seeds)}")
    print(f"\n建议 config.py 中 tracker_tuning_cfg.yaw_rate_kp_dps_per_px = {best_kp:.4f}")


if __name__ == "__main__":
    main()
