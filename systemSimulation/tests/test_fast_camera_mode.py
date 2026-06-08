"""测试快速相机模式和黄金分割搜索的正确性。"""
import math
import unittest

import numpy as np

from entities.camera.model import CameraImagingModel
from entities.camera.entity import CameraEntity, detect_beacon_centroid
from simulation.bootstrap import build_runtime
from entities.raspi.tracker_program import BaselineTrackerProgram, TrackerTuning


class TestFastCameraMode(unittest.TestCase):
    """快速相机模式测试。"""

    def test_fast_mode_no_image(self):
        """快速模式 render 返回 None 作为 image。"""
        model = CameraImagingModel()
        alpha = math.radians(1.0)
        beta = math.radians(0.5)
        result = model.render_beacon_fast(alpha, beta, 12.0, 0.0, 100.0)
        image, in_fov, u, v, sigma, brightness = result
        self.assertIsNone(image)
        self.assertTrue(in_fov)
        self.assertTrue(math.isfinite(u))
        self.assertTrue(math.isfinite(v))

    def test_fast_mode_out_of_fov(self):
        """快速模式在 FOV 外返回 in_fov=False。"""
        model = CameraImagingModel()
        alpha = math.radians(50.0)  # 远超 FOV
        result = model.render_beacon_fast(alpha, 0.0, 12.0, 0.0, 100.0)
        _, in_fov, u, v, _, _ = result
        self.assertFalse(in_fov)

    def test_fast_mode_noise_is_small(self):
        """快速模式噪声很小，不影响控制。"""
        model = CameraImagingModel()
        alpha = math.radians(2.0)
        beta = math.radians(1.0)
        n = 1000
        us = []
        for _ in range(n):
            _, _, u, _, _, _ = model.render_beacon_fast(alpha, beta, 12.0, 0.0, 100.0)
            if math.isfinite(u):
                us.append(u)
        std_u = float(np.std(us))
        # 噪声标准差应远小于 1px（实测约 0.12px）
        self.assertLess(std_u, 1.0)

    def test_camera_entity_fast_mode(self):
        """CameraEntity 快速模式正确初始化并产生有效状态。"""
        cam = CameraEntity(fast_mode=True)
        cam.power_on(0.0)
        # 模拟 boot 完成
        cam.boot_remaining_s = 0.0
        cam.power_state = "READY"
        state = cam.update(
            0.005, 1.0,
            {"x_m": 95.0, "y_m": 10.0, "z_m": 0.0},
            {"yaw_deg_internal": 5.0, "pitch_deg": 0.0},
        )
        self.assertTrue(state.in_fov)
        self.assertTrue(math.isfinite(state.u_px))

    def test_runtime_fast_camera(self):
        """build_runtime(fast_camera=True) 能正常完成仿真。"""
        np.random.seed(42)
        tuning = TrackerTuning(yaw_rate_kp_dps_per_px=1.1)
        runtime = build_runtime(
            control_program=BaselineTrackerProgram(tuning),
            fast_camera=True,
        )
        snap = runtime.step(1)
        self.assertIsNotNone(snap)
        self.assertIn("yaw_deg_display", snap.gimbal)

    def test_fast_mode_rms_close_to_full(self):
        """快速模式与完整模式的 RMS 偏差 < 10%。"""
        tuning = TrackerTuning(yaw_rate_kp_dps_per_px=1.1, pitch_rate_kp_dps_per_px=1.1)

        # 快速模式
        np.random.seed(42)
        rt_fast = build_runtime(
            control_program=BaselineTrackerProgram(tuning),
            fast_camera=True,
        )
        steps = int(5.0 / rt_fast.dt_s)
        errs_fast = []
        for _ in range(steps):
            snap = rt_fast.step(1)
            if snap.timestamp >= 3.0 and snap.camera["in_fov"]:
                u = snap.camera.get("u_px", float("nan"))
                if math.isfinite(u):
                    errs_fast.append(abs(u - 320.0))

        # 完整模式
        np.random.seed(42)
        rt_full = build_runtime(
            control_program=BaselineTrackerProgram(tuning),
            fast_camera=False,
        )
        errs_full = []
        for _ in range(steps):
            snap = rt_full.step(1)
            if snap.timestamp >= 3.0 and snap.camera["in_fov"]:
                u = snap.camera.get("u_px", float("nan"))
                if math.isfinite(u):
                    errs_full.append(abs(u - 320.0))

        rms_fast = float(np.sqrt(np.mean(np.array(errs_fast) ** 2)))
        rms_full = float(np.sqrt(np.mean(np.array(errs_full) ** 2)))
        diff_pct = abs(rms_fast - rms_full) / max(rms_full, 0.01) * 100
        self.assertLess(diff_pct, 10.0,
                        f"RMS diff {diff_pct:.1f}% > 10%: fast={rms_fast:.2f}, full={rms_full:.2f}")

    def test_full_mode_unaffected(self):
        """完整模式（fast_camera=False）行为不受快速模式代码影响。"""
        np.random.seed(42)
        tuning = TrackerTuning(yaw_rate_kp_dps_per_px=1.1)
        runtime = build_runtime(
            control_program=BaselineTrackerProgram(tuning),
            fast_camera=False,
        )
        steps = int(2.0 / runtime.dt_s)
        for _ in range(steps):
            snap = runtime.step(1)
        # 验证帧图像存在
        frame = runtime.camera.get_frame()
        self.assertIsNotNone(frame)
        self.assertIsNotNone(frame.image)
        self.assertEqual(frame.image.shape, (480, 640))


class TestGoldenSectionSearch(unittest.TestCase):
    """黄金分割搜索测试。"""

    def test_finds_minimum(self):
        """黄金分割法能找到单峰函数的最小值。"""
        # 二次函数 f(x) = (x - 2.5)^2 + 1，最小值在 x=2.5
        evals = []
        def eval_fn(x):
            val = (x - 2.5) ** 2 + 1.0
            r = {"yaw_kp": x, "pixel_rms": val, "angle_rms": val}
            evals.append(r)
            return r

        from tools.tune_tracker_kp import golden_section_search
        best_x, best_val, history = golden_section_search(eval_fn, 0.0, 10.0, tolerance=0.01)
        self.assertAlmostEqual(best_x, 2.5, delta=0.05)
        self.assertAlmostEqual(best_val, 1.0, delta=0.01)
        # 黄金分割应比均匀网格少得多
        self.assertLess(len(history), 30)


if __name__ == "__main__":
    unittest.main()
