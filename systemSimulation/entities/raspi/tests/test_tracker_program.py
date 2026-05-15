import unittest

import numpy as np

from entities.raspi.tracker_program import BaselineTrackerProgram, TrackerTuning


class _Frame:
    def __init__(self, image, cx, cy=None):
        self.image = image
        intrinsics = {"cx": cx}
        if cy is not None:
            intrinsics["cy"] = cy
        self.intrinsics = intrinsics


class TestTrackerProgram(unittest.TestCase):
    def test_emit_mode_and_rate_command_when_target_found(self):
        prog = BaselineTrackerProgram(TrackerTuning(yaw_rate_kp_dps_per_px=0.1, max_yaw_rate_dps=60.0))

        image = np.zeros((8, 8), dtype=np.uint8)
        image[4, 6] = 255
        obs = {
            "timestamp": 1.0,
            "gimbal": {"mode": "ANGLE_MODE"},
            "frame": _Frame(image, cx=4.0, cy=4.0),
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


class TestPitchRateTracking(unittest.TestCase):
    """验证 BaselineTrackerProgram 的纵向控制输出。"""

    def _make_obs_with_det(self, det_cx, det_cy, cx=320.0, cy=240.0):
        """构造一个含目标检测的观测。"""
        image = np.zeros((480, 640), dtype=np.uint8)
        # 在 det_cy, det_cx 位置放置亮点
        iy, ix = int(np.clip(det_cy, 0, 479)), int(np.clip(det_cx, 0, 639))
        image[iy, ix] = 255
        return {
            "timestamp": 1.0,
            "gimbal": {"mode": "RATE_MODE"},
            "frame": _Frame(image, cx=cx, cy=cy),
            "camera": {},
        }

    def test_target_above_pitch_rate_positive(self):
        """目标在画面上方（det_cy < cy）→ pitch_rate > 0（向上跟踪）。"""
        prog = BaselineTrackerProgram(TrackerTuning(
            pitch_rate_kp_dps_per_px=1.0, max_pitch_rate_dps=60.0, deadband_v_px=1.0
        ))
        obs = self._make_obs_with_det(det_cx=320.0, det_cy=200.0, cx=320.0, cy=240.0)
        cmds = prog.on_tick(obs)
        rate_cmd = [c for c in cmds if c.action == "set_rate_target"][0]
        self.assertGreater(rate_cmd.payload["pitch_rate"], 0.0)

    def test_target_below_pitch_rate_negative(self):
        """目标在画面下方（det_cy > cy）→ pitch_rate < 0（向下跟踪）。"""
        prog = BaselineTrackerProgram(TrackerTuning(
            pitch_rate_kp_dps_per_px=1.0, max_pitch_rate_dps=60.0, deadband_v_px=1.0
        ))
        obs = self._make_obs_with_det(det_cx=320.0, det_cy=280.0, cx=320.0, cy=240.0)
        cmds = prog.on_tick(obs)
        rate_cmd = [c for c in cmds if c.action == "set_rate_target"][0]
        self.assertLess(rate_cmd.payload["pitch_rate"], 0.0)

    def test_deadband_v_px_suppresses_small_error(self):
        """垂直像素误差在 deadband 内时 pitch_rate=0。"""
        prog = BaselineTrackerProgram(TrackerTuning(
            pitch_rate_kp_dps_per_px=1.0, max_pitch_rate_dps=60.0, deadband_v_px=10.0
        ))
        # det_cy=243, cy=240 → 偏差 3px，小于 deadband=10
        obs = self._make_obs_with_det(det_cx=320.0, det_cy=243.0, cx=320.0, cy=240.0)
        cmds = prog.on_tick(obs)
        rate_cmd = [c for c in cmds if c.action == "set_rate_target"][0]
        self.assertAlmostEqual(rate_cmd.payload["pitch_rate"], 0.0)

    def test_pitch_rate_clamped(self):
        """pitch_rate 不超过 max_pitch_rate_dps。"""
        prog = BaselineTrackerProgram(TrackerTuning(
            pitch_rate_kp_dps_per_px=10.0, max_pitch_rate_dps=30.0, deadband_v_px=1.0
        ))
        # det_cy=140, cy=240 → 偏差 100px，kp=10 → 1000 dps，应被限幅到 30
        obs = self._make_obs_with_det(det_cx=320.0, det_cy=140.0, cx=320.0, cy=240.0)
        cmds = prog.on_tick(obs)
        rate_cmd = [c for c in cmds if c.action == "set_rate_target"][0]
        self.assertAlmostEqual(rate_cmd.payload["pitch_rate"], 30.0)

    def test_lost_target_pitch_rate_uses_hold(self):
        """丢目标后 pitch_rate 使用 lost_target_hold_rate_dps。"""
        prog = BaselineTrackerProgram(TrackerTuning(
            lost_target_hold_rate_dps=5.0,
        ))
        # 先看到目标，建立 last_pixel_error_y
        obs1 = self._make_obs_with_det(det_cx=320.0, det_cy=200.0, cx=320.0, cy=240.0)
        prog.on_tick(obs1)
        # 然后丢目标（空白帧），此时 hold rate 生效
        blank_image = np.zeros((480, 640), dtype=np.uint8)
        obs2 = {
            "timestamp": 2.0,
            "gimbal": {"mode": "RATE_MODE"},
            "frame": _Frame(blank_image, cx=320.0, cy=240.0),
            "camera": {},
        }
        cmds = prog.on_tick(obs2)
        rate_cmd = [c for c in cmds if c.action == "set_rate_target"][0]
        self.assertAlmostEqual(rate_cmd.payload["pitch_rate"], 5.0)

    def test_yaw_and_pitch_independent(self):
        """yaw_rate 和 pitch_rate 独立计算。"""
        prog = BaselineTrackerProgram(TrackerTuning(
            yaw_rate_kp_dps_per_px=1.0, max_yaw_rate_dps=60.0, deadband_px=1.0,
            pitch_rate_kp_dps_per_px=2.0, max_pitch_rate_dps=60.0, deadband_v_px=1.0,
        ))
        # 目标偏右上：det_cx=340(右偏), det_cy=220(上偏)
        obs = self._make_obs_with_det(det_cx=340.0, det_cy=220.0, cx=320.0, cy=240.0)
        cmds = prog.on_tick(obs)
        rate_cmd = [c for c in cmds if c.action == "set_rate_target"][0]
        self.assertGreater(rate_cmd.payload["yaw_rate"], 0.0)
        self.assertGreater(rate_cmd.payload["pitch_rate"], 0.0)
        # pitch_rate 应为 2.0 * (240-220) = 40, yaw_rate 应为 1.0 * (340-320) = 20
        self.assertGreater(rate_cmd.payload["pitch_rate"], rate_cmd.payload["yaw_rate"])


if __name__ == "__main__":
    unittest.main()

