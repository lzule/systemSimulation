import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.digital_twin_runtime import DigitalTwinRuntime
from simulation.bootstrap import build_runtime


class TestRuntimeApi(unittest.TestCase):
    def test_state_contract_and_runtime_behavior(self):
        rt = DigitalTwinRuntime()
        rt.gimbal_client.power_on()
        rt.camera_client.power_on()
        rt.raspi_client.power_on()
        rt.step(400)

        st = rt.get_world_snapshot().gimbal
        for key in (
            "yaw_deg_internal",
            "yaw_deg_display",
            "pitch_deg",
            "yaw_rate_dps",
            "pitch_rate_dps",
            "mode",
            "timestamp",
        ):
            self.assertIn(key, st)

        rt.gimbal_client.set_mode("RATE_MODE", rt.t)
        for _ in range(20):
            snap = rt.step()
            if snap.gimbal["mode"] == "RATE_MODE":
                break
        rt.gimbal_client.set_rate_target(30.0, 0.0, rt.t)
        rt.step(5)
        ys = [rt.step().gimbal["yaw_deg_internal"] for _ in range(400)]
        self.assertGreater(ys[-1], ys[0])

        rt.gimbal_client.set_rate_target(0.0, 120.0, rt.t)
        for _ in range(1200):
            rt.step()
        self.assertLessEqual(rt.get_world_snapshot().gimbal["pitch_deg"], 90.0001)

        rt.gimbal_client.set_rate_target(0.0, -120.0, rt.t)
        for _ in range(1600):
            rt.step()
        self.assertGreaterEqual(rt.get_world_snapshot().gimbal["pitch_deg"], -135.0001)

        rt.gimbal_client.set_rate_target(10.0, 0.0, rt.t)
        rt.gimbal_client.set_rate_target(50.0, 0.0, rt.t)
        s = rt.step(2)
        self.assertAlmostEqual(s.gimbal["yaw_rate_ref_dps"], 50.0, places=9)

        rt.gimbal_client.set_mode("ANGLE_MODE")
        rt.gimbal_client.set_angle_target(90.0, 10.0, rt.t)
        ticks = [bool(rt.step().gimbal["angle_tick"]) for _ in range(200)]
        self.assertGreaterEqual(sum(ticks), 45)
        self.assertLessEqual(sum(ticks), 55)

        rt.gimbal_client.set_mode("RATE_MODE")
        rt.gimbal_client.set_rate_target(0.0, 0.0, rt.t)
        ticks2 = [bool(rt.step().gimbal["angle_tick"]) for _ in range(120)]
        self.assertEqual(sum(ticks2), 0)

    def test_build_runtime_exposes_control_program_in_snapshot(self):
        rt = build_runtime(0.0, obs_mode="research")
        snap = rt.step(400)

        self.assertIn("control_program_name", snap.raspi)
        self.assertEqual(snap.raspi["control_program_name"], "BaselineTrackerProgram")

    def test_camera_snapshot_exposes_imaging_physics(self):
        """快照中的 camera 应携带 distance_m / sigma_px / brightness 三项物理量。"""
        rt = build_runtime(0.0, obs_mode="research")
        snap = rt.step(50)

        self.assertIn("distance_m", snap.camera)
        self.assertIn("sigma_px", snap.camera)
        self.assertIn("brightness", snap.camera)
        # 默认 beacon_sigma_px=6.0, sigma_ref=80m, 距离约 100m 时 sigma ≈ 6.0/(1+100/80) ≈ 2.67
        # 允许较大误差（距离不固定）
        self.assertGreater(snap.camera["distance_m"], 0.0)
        self.assertGreater(snap.camera["sigma_px"], 0.0)
        self.assertLessEqual(snap.camera["sigma_px"], 6.0)  # 不超过 base

    def test_camera_sigma_decreases_with_distance(self):
        """启用距离相关 sigma 后，距离越远 sigma 越小（与物理模型一致）。"""
        from config import camera_cfg
        original_ref = camera_cfg.sigma_ref_distance_m
        original_base = camera_cfg.beacon_sigma_px
        camera_cfg.sigma_ref_distance_m = 50.0
        camera_cfg.beacon_sigma_px = 6.0
        try:
            rt = build_runtime(0.0, obs_mode="research")
            snap = rt.step(50)
            d = snap.camera["distance_m"]
            sigma = snap.camera["sigma_px"]
            expected = 6.0 / (1.0 + d / 50.0)
            self.assertAlmostEqual(sigma, expected, places=5)
            self.assertLess(sigma, 6.0)
        finally:
            camera_cfg.sigma_ref_distance_m = original_ref
            camera_cfg.beacon_sigma_px = original_base


if __name__ == "__main__":
    unittest.main()
