"""端到端闭环基线测试。

验证完整跟踪回路（Target → Gimbal → Camera → Raspi → Command → Gimbal）的稳态性能。
本测试作为阶段 0 的闸门条件之一：至少 1 个端到端闭环测试纳入自动测试。

通过标准：
- 稳态窗口（t≥3s）跟踪率 ≥ 80%
- 稳态角度误差 RMS < 3.0°
- 稳态角度误差峰值 < 8.0°
- 无发散（最后 10s 误差线性回归斜率 < 0.1 deg/s）
"""

import math
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import camera_cfg, raspi_delay_cfg, RaspiDelayConfig
from simulation.bootstrap import build_runtime


def wrap_pm180(angle_deg: float) -> float:
    return (angle_deg + 180.0) % 360.0 - 180.0


def run_tracking_simulation(
    duration_s: float = 20.0,
    seed: int = 42,
) -> dict:
    """运行完整闭环仿真，返回每 tick 采样数据和汇总指标。

    Returns:
        dict 含 keys: t, angle_err, pixel_err, in_fov, metrics
    """
    np.random.seed(seed)

    # 重置延时配置（防止前置测试修改模块级单例）
    _default_delay = RaspiDelayConfig()
    raspi_delay_cfg.image_read_delay_s = _default_delay.image_read_delay_s
    raspi_delay_cfg.image_process_delay_s = _default_delay.image_process_delay_s
    raspi_delay_cfg.state_read_delay_s = _default_delay.state_read_delay_s
    raspi_delay_cfg.command_tx_delay_s = _default_delay.command_tx_delay_s
    raspi_delay_cfg.jitter_std_s = _default_delay.jitter_std_s

    rt = build_runtime(delay_ms=0.0)

    n_steps = int(duration_s / rt.dt_s)
    t_arr = []
    angle_err_arr = []
    pixel_err_arr = []
    in_fov_arr = []

    for _ in range(n_steps):
        snap = rt.step(1)
        t_arr.append(snap.timestamp)

        target_bearing = float(snap.target["bearing_deg"])
        yaw = float(snap.gimbal["yaw_deg_internal"])
        angle_err = wrap_pm180(target_bearing - yaw)
        angle_err_arr.append(angle_err)

        in_fov = bool(snap.camera["in_fov"])
        in_fov_arr.append(in_fov)

        if in_fov:
            u_px = float(snap.camera["u_px"])
            pixel_err_arr.append(abs(u_px - camera_cfg.cx))
        else:
            pixel_err_arr.append(float("nan"))

    t = np.array(t_arr)
    angle_err = np.array(angle_err_arr)
    pixel_err = np.array(pixel_err_arr, dtype=float)
    in_fov = np.array(in_fov_arr, dtype=bool)

    stable_from_s = 3.0
    stable_mask = (t >= stable_from_s)
    stable_in_fov = in_fov[stable_mask]

    metrics = {
        "tracking_ratio": float(stable_in_fov.sum() / max(1, len(stable_in_fov))),
        "overall_tracking_ratio": float(in_fov.sum() / max(1, len(in_fov))),
        "angle_error_rms_deg": float(np.nan),
        "angle_error_max_deg": float(np.nan),
        "pixel_error_rms_px": float(np.nan),
        "no_divergence": False,
        "divergence_slope_deg_per_s": float(np.nan),
    }

    stable_and_in_fov = (t >= stable_from_s) & in_fov & np.isfinite(pixel_err)

    if np.any(stable_and_in_fov):
        stable_angle_err = angle_err[stable_and_in_fov]
        metrics["angle_error_rms_deg"] = float(np.sqrt(np.mean(stable_angle_err**2)))
        metrics["angle_error_max_deg"] = float(np.max(np.abs(stable_angle_err)))

        stable_px = pixel_err[stable_and_in_fov]
        metrics["pixel_error_rms_px"] = float(np.sqrt(np.mean(stable_px**2)))

    last_10s_mask = (t >= (duration_s - 10.0)) & np.isfinite(angle_err)
    if np.sum(last_10s_mask) > 10:
        t_last = t[last_10s_mask]
        err_last = angle_err[last_10s_mask]
        slope = np.polyfit(t_last, err_last, 1)[0]
        metrics["divergence_slope_deg_per_s"] = float(slope)
        metrics["no_divergence"] = abs(slope) < 0.1

    return {
        "t": t,
        "angle_err": angle_err,
        "pixel_err": pixel_err,
        "in_fov": in_fov,
        "metrics": metrics,
    }


class TestE2EBaselineTracking(unittest.TestCase):
    """端到端闭环基线测试：验证完整跟踪回路的稳态性能。"""

    @classmethod
    def setUpClass(cls):
        cls.result = run_tracking_simulation(duration_s=20.0, seed=42)
        cls.metrics = cls.result["metrics"]

    def test_tracking_ratio_above_threshold(self):
        """稳态窗口（t≥3s）内跟踪率 ≥ 80%。"""
        self.assertGreaterEqual(
            self.metrics["tracking_ratio"],
            0.80,
            f"稳态跟踪率 {self.metrics['tracking_ratio']:.1%} 低于 80%",
        )

    def test_angle_error_rms_below_threshold(self):
        """稳态角度误差 RMS < 3.0°。"""
        self.assertLess(
            self.metrics["angle_error_rms_deg"],
            3.0,
            f"角度 RMS {self.metrics['angle_error_rms_deg']:.3f}° 超过 3.0°",
        )

    def test_angle_error_max_below_threshold(self):
        """稳态角度误差峰值 < 8.0°。"""
        self.assertLess(
            self.metrics["angle_error_max_deg"],
            8.0,
            f"角度峰值 {self.metrics['angle_error_max_deg']:.3f}° 超过 8.0°",
        )

    def test_no_divergence(self):
        """最后 10s 无发散（回归斜率 < 0.1 deg/s）。"""
        self.assertTrue(
            self.metrics["no_divergence"],
            f"检测到发散趋势，斜率 = {self.metrics['divergence_slope_deg_per_s']:.4f} deg/s",
        )

    def test_pixel_error_rms_reasonable(self):
        """像素误差 RMS < 50px（FOV ≈ 21°，640px，约 1.6°）。"""
        self.assertLess(
            self.metrics["pixel_error_rms_px"],
            50.0,
            f"像素 RMS {self.metrics['pixel_error_rms_px']:.1f}px 超过 50px",
        )

    def test_result_deterministic(self):
        """同样种子重复运行宏观指标一致。"""
        result2 = run_tracking_simulation(duration_s=20.0, seed=42)
        self.assertAlmostEqual(
            self.metrics["angle_error_rms_deg"],
            result2["metrics"]["angle_error_rms_deg"],
            places=1,
            msg="角度 RMS 两次运行偏差过大",
        )
        self.assertEqual(
            self.metrics["no_divergence"],
            result2["metrics"]["no_divergence"],
            "发散判断两次运行不一致",
        )


class TestE2EBaselineWithDelay(unittest.TestCase):
    """带延时的端到端闭环测试：验证延时闭环仍可跟踪。"""

    @classmethod
    def setUpClass(cls):
        np.random.seed(42)

        # 重置延时配置
        _default_delay = RaspiDelayConfig()
        raspi_delay_cfg.image_read_delay_s = _default_delay.image_read_delay_s
        raspi_delay_cfg.image_process_delay_s = _default_delay.image_process_delay_s
        raspi_delay_cfg.state_read_delay_s = _default_delay.state_read_delay_s
        raspi_delay_cfg.command_tx_delay_s = _default_delay.command_tx_delay_s
        raspi_delay_cfg.jitter_std_s = _default_delay.jitter_std_s

        rt = build_runtime(delay_ms=20.0)
        duration_s = 10.0
        n_steps = int(duration_s / rt.dt_s)

        angle_errors = []
        in_fov_count = 0
        total_count = 0

        for _ in range(n_steps):
            snap = rt.step(1)
            if snap.timestamp < 3.0:
                continue
            total_count += 1
            target_bearing = float(snap.target["bearing_deg"])
            yaw = float(snap.gimbal["yaw_deg_internal"])
            angle_errors.append(abs(wrap_pm180(target_bearing - yaw)))
            if snap.camera["in_fov"]:
                in_fov_count += 1

        cls.tracking_ratio = in_fov_count / max(1, total_count)
        cls.angle_rms = float(np.sqrt(np.mean(np.array(angle_errors) ** 2)))

    def test_delayed_tracking_ratio(self):
        """20ms 延时下跟踪率 ≥ 80%。"""
        self.assertGreaterEqual(self.tracking_ratio, 0.80)

    def test_delayed_angle_rms(self):
        """20ms 延时下角度 RMS < 3.0°。"""
        self.assertLess(self.angle_rms, 3.0)


if __name__ == "__main__":
    unittest.main()
