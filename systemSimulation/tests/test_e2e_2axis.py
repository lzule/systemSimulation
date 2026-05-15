"""双轴闭环 e2e 基线测试：验证 z=0 回归 + z>0 双轴跟踪。"""

import copy
import math
import unittest

from config import target_cfg
from simulation.bootstrap import build_runtime

# 保存原始配置，测试后恢复
_ORIG_TARGET_CFG = copy.deepcopy(target_cfg.__dict__)


def _restore_target_cfg():
    """恢复 target_cfg 到测试前状态。"""
    target_cfg.__dict__.clear()
    target_cfg.__dict__.update(_ORIG_TARGET_CFG)


def _run_session(duration_s: float, z_amplitude: float = 0.0, z_freq: float = 0.0) -> list:
    """运行无 GUI 闭环仿真并收集快照。"""
    target_cfg.initial_z_m = 0.0
    target_cfg.sin_z_amplitude_m = z_amplitude
    target_cfg.sin_z_frequency_hz = z_freq
    target_cfg.motion_type = "sinusoidal"
    target_cfg.initial_x_m = 100.0
    target_cfg.sin_amplitude_m = 15.0
    target_cfg.sin_frequency_hz = 0.2

    runtime = build_runtime()
    n_steps = max(1, int(duration_s / runtime.dt_s))
    snapshots = []
    for _ in range(n_steps):
        snap = runtime.step(1)
        snapshots.append(snap)
    return snapshots


class TestE2E2AxisRegression(unittest.TestCase):
    """z=0 场景下确认与阶段0基线一致（回归测试）。"""

    @classmethod
    def setUpClass(cls):
        cls.snapshots = _run_session(10.0, z_amplitude=0.0, z_freq=0.0)

    @classmethod
    def tearDownClass(cls):
        _restore_target_cfg()

    def test_z_zero_v_px_near_center(self):
        """z=0 时 v_px 应始终在画面中心附近"""
        for snap in self.snapshots:
            if snap.camera["in_fov"] and not math.isnan(snap.camera["v_px"]):
                self.assertAlmostEqual(snap.camera["v_px"], 240.0, delta=5.0,
                                       msg="z=0 下 v_px 应在 h/2 附近")

    def test_z_zero_pitch_rate_near_zero(self):
        """z=0 时 pitch_rate 应接近 0（无高度变化）"""
        for snap in self.snapshots[400:]:  # 跳过前 2s 稳定期
            gimbal = snap.gimbal
            if "pitch_deg" in gimbal:
                self.assertAlmostEqual(gimbal["pitch_deg"], 0.0, delta=2.0,
                                       msg="z=0 下 pitch 应接近 0")


class TestE2E2AxisWithHeight(unittest.TestCase):
    """z>0 场景下确认双轴跟踪工作正常。"""

    @classmethod
    def setUpClass(cls):
        cls.snapshots = _run_session(10.0, z_amplitude=10.0, z_freq=0.15)

    @classmethod
    def tearDownClass(cls):
        _restore_target_cfg()

    def test_v_px_not_always_center(self):
        """有 z 运动时 v_px 不应始终在中心"""
        v_values = [s.camera["v_px"] for s in self.snapshots
                    if s.camera["in_fov"] and not math.isnan(s.camera["v_px"])]
        v_range = max(v_values) - min(v_values)
        self.assertGreater(v_range, 5.0, "有 z 运动时 v_px 应有明显变化")

    def test_pitch_not_zero(self):
        """有 z 运动时 pitch 不应始终为 0"""
        pitch_values = [s.gimbal["pitch_deg"] for s in self.snapshots[400:]]
        pitch_range = max(pitch_values) - min(pitch_values)
        self.assertGreater(pitch_range, 0.5, "有 z 运动时 pitch 应有明显变化")

    def test_elevation_nonzero(self):
        """有 z 运动时 target 的 elevation 应非零"""
        elevations = [s.target["elevation_deg"] for s in self.snapshots[200:]
                      if "elevation_deg" in s.target]
        if elevations:
            max_abs = max(abs(e) for e in elevations)
            self.assertGreater(max_abs, 0.1, "有 z 运动时 elevation 应非零")

    def test_z_m_present_in_target(self):
        """target 状态中应包含 z_m"""
        for snap in self.snapshots[:10]:
            self.assertIn("z_m", snap.target, "target 状态应包含 z_m 字段")


if __name__ == "__main__":
    unittest.main()
