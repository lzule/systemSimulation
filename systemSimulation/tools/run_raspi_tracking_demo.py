"""Raspi 控制器联调示例（相机+云台跟踪运动目标）。"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from dataclasses import dataclass

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from entities.raspi.tracker_program import BaselineTrackerProgram, TrackerTuning
from runtime.digital_twin_runtime import DigitalTwinRuntime


@dataclass
class TrackingMetrics:
    sample_count: int = 0
    in_fov_count: int = 0
    valid_error_count: int = 0
    abs_error_sum: float = 0.0
    abs_error_max: float = 0.0

    def add(self, u_px: float, cx_px: float, in_fov: bool) -> None:
        self.sample_count += 1
        if in_fov:
            self.in_fov_count += 1
        if isinstance(u_px, float) and math.isfinite(u_px):
            err = abs(u_px - cx_px)
            self.valid_error_count += 1
            self.abs_error_sum += err
            self.abs_error_max = max(self.abs_error_max, err)

    @property
    def mean_abs_error_px(self) -> float:
        if self.valid_error_count == 0:
            return float("nan")
        return self.abs_error_sum / self.valid_error_count

    @property
    def in_fov_ratio(self) -> float:
        if self.sample_count == 0:
            return float("nan")
        return self.in_fov_count / self.sample_count


def wait_until_ready(rt: DigitalTwinRuntime, max_steps: int = 2000) -> None:
    """推进仿真直到云台/相机/树莓派均 READY。"""

    for _ in range(max_steps):
        snap = rt.step(1)
        g = snap.gimbal["power_state"]
        c = snap.camera["power_state"]
        r = snap.raspi["power_state"]
        if g == "READY" and c == "READY" and r == "READY":
            return
    raise RuntimeError("等待设备 READY 超时，请检查上电流程配置。")


def run_tracking_demo(duration_s: float, mode: str, delay_ms: float) -> TrackingMetrics:
    rt = DigitalTwinRuntime()

    # 1) 上电
    rt.gimbal_client.power_on()
    rt.camera_client.power_on()
    rt.raspi_client.power_on()

    # 2) 等待设备 READY，避免未就绪阶段命令被拒绝
    wait_until_ready(rt)

    # 3) 加载 Raspi 控制程序模板
    tracker = BaselineTrackerProgram(
        TrackerTuning(
            yaw_rate_kp_dps_per_px=0.08,
            max_yaw_rate_dps=60.0,
            deadband_px=2.0,
            lost_target_hold_rate_dps=0.0,
            enable_zoom_control=False,
        )
    )
    rt.raspi_client.load_control_program(tracker)
    if delay_ms > 0.0:
        delay_s = delay_ms / 1000.0
        rt.raspi_client.set_delay_profile(
            image_read_delay_s=delay_s,
            image_process_delay_s=delay_s,
            state_read_delay_s=delay_s * 0.5,
            command_tx_delay_s=delay_s,
            jitter_std_s=0.0,
        )

    metrics = TrackingMetrics()
    n_steps = max(1, int(duration_s / rt.dt_s))
    print(f"[demo] mode={mode}, duration={duration_s:.2f}s, dt={rt.dt_s:.4f}, steps={n_steps}, delay_ms={delay_ms:.1f}")

    if mode == "realtime":
        rt.start(mode="realtime")
        t0 = time.time()
        while time.time() - t0 <= duration_s:
            snap = rt.get_world_snapshot()
            frame = rt.camera_client.get_frame()
            cx_px = float("nan") if frame is None else float(frame.intrinsics["cx"])
            u_px = float(snap.camera.get("u_px", float("nan")))
            in_fov = bool(snap.camera.get("in_fov", False))
            metrics.add(u_px, cx_px, in_fov)
            print(
                f"\rt={snap.timestamp:6.2f}s yaw={snap.gimbal['yaw_deg_display']:7.2f} "
                f"u={u_px:8.2f} in_fov={int(in_fov)} backlog={snap.raspi['pipeline_backlog_len']:3d}",
                end="",
                flush=True,
            )
            time.sleep(max(0.01, rt.dt_s))
        rt.stop()
        print()
    else:
        for i in range(n_steps):
            snap = rt.step(1)
            frame = rt.camera_client.get_frame()
            cx_px = float("nan") if frame is None else float(frame.intrinsics["cx"])
            u_px = float(snap.camera.get("u_px", float("nan")))
            in_fov = bool(snap.camera.get("in_fov", False))
            metrics.add(u_px, cx_px, in_fov)
            if i % max(1, int(0.2 / rt.dt_s)) == 0:
                print(
                    f"t={snap.timestamp:6.2f}s yaw={snap.gimbal['yaw_deg_display']:7.2f} "
                    f"u={u_px:8.2f} in_fov={int(in_fov)} "
                    f"obs_lag={snap.raspi['last_process_latency_s']*1000.0:7.2f}ms"
                )

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Raspi 控制器实例联调示例")
    parser.add_argument("--duration", type=float, default=8.0, help="运行时长（秒）")
    parser.add_argument("--mode", choices=["offline", "realtime"], default="offline", help="运行模式")
    parser.add_argument("--delay-ms", type=float, default=0.0, help="链路延时（毫秒）")
    args = parser.parse_args()

    metrics = run_tracking_demo(duration_s=args.duration, mode=args.mode, delay_ms=args.delay_ms)
    print("\n=== 联调结果摘要 ===")
    print(f"样本数: {metrics.sample_count}")
    print(f"在FOV比例: {metrics.in_fov_ratio*100.0:.2f}%")
    print(f"平均像素误差: {metrics.mean_abs_error_px:.2f}px")
    print(f"最大像素误差: {metrics.abs_error_max:.2f}px")


if __name__ == "__main__":
    main()
