import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.digital_twin_runtime import DigitalTwinRuntime


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


if __name__ == "__main__":
    unittest.main()
