import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from entities.gimbal.control import ANGLE_MODE, RATE_MODE, CascadedController2Axis
from entities.gimbal.model import GimbalPlant2Axis


class TestGimbal2AxisCore(unittest.TestCase):
    def test_rate_saturation_and_pitch_limits(self):
        plant = GimbalPlant2Axis()
        ctrl = CascadedController2Axis()
        dt = 0.005

        ctrl.set_mode(ANGLE_MODE)
        ctrl.set_angle_target(220.0, 30.0, 0.0)

        max_rate = 0.0
        for _ in range(3000):
            out = ctrl.step(
                plant.yaw_deg_internal,
                plant.pitch_deg,
                plant.yaw_rate_dps,
                plant.pitch_rate_dps,
                dt,
            )
            st = plant.step((out["yaw_rate_cmd_dps"], out["pitch_rate_cmd_dps"]), dt)
            max_rate = max(max_rate, abs(st.yaw_rate_dps), abs(st.pitch_rate_dps))

        self.assertLessEqual(max_rate, 60.0001)

        for _ in range(1200):
            plant.step((0.0, 120.0), dt)
        self.assertLessEqual(plant.pitch_deg, 90.0001)

        for _ in range(1600):
            plant.step((0.0, -120.0), dt)
        self.assertGreaterEqual(plant.pitch_deg, -135.0001)

    def test_latest_wins_and_tick_semantics(self):
        plant = GimbalPlant2Axis()
        ctrl = CascadedController2Axis()
        dt = 0.005

        ctrl.set_mode(RATE_MODE)
        ctrl.set_rate_target(5.0, 0.0, 1.0)
        ctrl.set_rate_target(50.0, 0.0, 1.001)
        out = ctrl.step(
            plant.yaw_deg_internal,
            plant.pitch_deg,
            plant.yaw_rate_dps,
            plant.pitch_rate_dps,
            dt,
        )
        self.assertAlmostEqual(out["yaw_rate_ref_dps"], 50.0, places=9)

        ctrl.set_mode(ANGLE_MODE)
        ctrl.set_angle_target(100.0, 0.0, 2.0)

        angle_ticks = 0
        for _ in range(200):
            out = ctrl.step(
                plant.yaw_deg_internal,
                plant.pitch_deg,
                plant.yaw_rate_dps,
                plant.pitch_rate_dps,
                dt,
            )
            angle_ticks += int(out["angle_tick"])

        self.assertGreaterEqual(angle_ticks, 45)
        self.assertLessEqual(angle_ticks, 55)

        ctrl.set_mode(RATE_MODE)
        rate_mode_angle_ticks = 0
        for _ in range(150):
            out = ctrl.step(
                plant.yaw_deg_internal,
                plant.pitch_deg,
                plant.yaw_rate_dps,
                plant.pitch_rate_dps,
                dt,
            )
            rate_mode_angle_ticks += int(out["angle_tick"])

        self.assertEqual(rate_mode_angle_ticks, 0)


if __name__ == "__main__":
    unittest.main()
