import unittest

import numpy as np

from entities.raspi.tracker_program import BaselineTrackerProgram, TrackerTuning


class _Frame:
    def __init__(self, image, cx):
        self.image = image
        self.intrinsics = {"cx": cx}


class TestTrackerProgram(unittest.TestCase):
    def test_emit_mode_and_rate_command_when_target_found(self):
        prog = BaselineTrackerProgram(TrackerTuning(yaw_rate_kp_dps_per_px=0.1, max_yaw_rate_dps=60.0))

        image = np.zeros((8, 8), dtype=np.uint8)
        image[4, 6] = 255
        obs = {
            "timestamp": 1.0,
            "gimbal": {"mode": "ANGLE_MODE"},
            "frame": _Frame(image, cx=4.0),
            "camera": {},
        }
        cmds = prog.on_tick(obs)

        self.assertGreaterEqual(len(cmds), 2)
        self.assertEqual(cmds[0].target, "gimbal")
        self.assertEqual(cmds[0].action, "set_mode")
        self.assertEqual(cmds[1].action, "set_rate_target")
        self.assertGreater(cmds[1].payload["yaw_rate"], 0.0)

    def test_hold_rate_when_target_lost(self):
        prog = BaselineTrackerProgram(TrackerTuning(lost_target_hold_rate_dps=0.0))
        obs = {
            "timestamp": 1.0,
            "gimbal": {"mode": "RATE_MODE"},
            "frame": None,
            "camera": {},
        }
        cmds = prog.on_tick(obs)
        self.assertEqual(cmds, [])


if __name__ == "__main__":
    unittest.main()

