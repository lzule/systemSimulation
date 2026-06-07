"""ObsFilter 回归测试 — 阶段3轮A任务A3。

覆盖 debug / research / realistic 三种模式的字段过滤与噪声注入行为。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from runtime.types import FramePacket
from simulation.obs_filter import ObsFilter


# ---------------------------------------------------------------------------
# 辅助：构建 mock world_obs
# ---------------------------------------------------------------------------

def _make_world_obs():
    """构建一份包含完整字段的 mock world_obs 字典。"""
    return {
        "timestamp": 1.0,
        "target": {
            "x_m": 100.0,
            "y_m": 0.0,
            "z_m": 0.0,
            "vx_mps": 0.0,
            "vy_mps": 1.5,
            "bearing_deg": 90.0,
            "distance_m": 100.0,
        },
        "gimbal": {
            "power_state": "READY",
            "mode": "ANGLE_MODE",
            "yaw_deg_internal": 5.0,
            "yaw_deg_display": 5.0,
            "pitch_deg": 0.0,
            "yaw_rate_dps": 0.1,
            "pitch_rate_dps": 0.0,
        },
        "camera": {
            "power_state": "READY",
            "f_current_mm": 12.0,
            "f_target_mm": 12.0,
            "frame_id": 100,
            "in_fov": True,
            "u_px": 320.0,
            "v_px": 240.0,
        },
        "frame": FramePacket(
            timestamp=1.0,
            image=np.zeros((480, 640), dtype=np.uint8),
            intrinsics={
                "cx": 320.0,
                "cy": 240.0,
                "f_px": 1600.0,
                "f_mm": 12.0,
                "width": 640.0,
                "height": 480.0,
            },
            optional_gt=None,
        ),
    }


def _make_world_obs_with_gt():
    obs = _make_world_obs()
    obs["frame"] = FramePacket(
        timestamp=1.0,
        image=np.zeros((480, 640), dtype=np.uint8),
        intrinsics={
            "cx": 320.0,
            "cy": 240.0,
            "f_px": 1600.0,
            "f_mm": 12.0,
            "width": 640.0,
            "height": 480.0,
        },
        optional_gt={"u_px": 320.0, "v_px": 240.0, "in_fov": 1.0},
    )
    return obs


# ===================================================================
# TestDebugMode
# ===================================================================

class TestDebugMode(unittest.TestCase):
    """debug 模式：透传全部字段，不做任何过滤。"""

    def test_debug_passes_all_fields(self):
        """debug 模式透传全部字段，不丢失任何信息。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="debug")
        result = f.filter_obs(obs)

        # 顶层四个 key 全部存在
        for key in ("timestamp", "target", "gimbal", "camera", "frame"):
            self.assertIn(key, result, f"debug 模式结果缺少 key: {key}")

        # target 完整
        self.assertEqual(result["target"], obs["target"])
        # gimbal 完整
        self.assertEqual(result["gimbal"], obs["gimbal"])
        # camera 完整
        self.assertEqual(result["camera"], obs["camera"])
        # frame 完整（内容相同，但为隔离副本，不要求同一对象）
        self.assertEqual(result["frame"].timestamp, obs["frame"].timestamp)
        self.assertEqual(result["frame"].intrinsics, obs["frame"].intrinsics)

    def test_debug_returns_same_reference_or_equal(self):
        """debug 模式返回值字段内容与输入一致（frame 为隔离副本，顶层为新字典）。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="debug")
        result = f.filter_obs(obs)
        # debug 模式现在返回浅拷贝字典（frame 单独隔离），不再是同一引用
        self.assertEqual(result["timestamp"], obs["timestamp"])
        self.assertEqual(result["target"], obs["target"])
        self.assertEqual(result["gimbal"], obs["gimbal"])
        self.assertEqual(result["camera"], obs["camera"])


# ===================================================================
# TestResearchMode
# ===================================================================

class TestResearchMode(unittest.TestCase):
    """research 模式：白名单过滤，无 target，无噪声。"""

    def test_research_keeps_whitelist_fields(self):
        """只保留白名单字段（timestamp, gimbal.mode, camera.f_current_mm, frame）。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="research")
        result = f.filter_obs(obs)

        # 顶层 key 齐全
        for key in ("timestamp", "target", "gimbal", "camera", "frame"):
            self.assertIn(key, result)

        # timestamp 正确
        self.assertEqual(result["timestamp"], 1.0)

    def test_research_removes_target(self):
        """target 真值被过滤。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="research")
        result = f.filter_obs(obs)
        self.assertEqual(result["target"], {})

    def test_research_removes_gimbal_details(self):
        """gimbal 只保留 mode，不包含 yaw_deg_internal, pitch_deg 等。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="research")
        result = f.filter_obs(obs)

        gimbal = result["gimbal"]
        self.assertIn("mode", gimbal)
        self.assertEqual(gimbal["mode"], "ANGLE_MODE")

        # 不应包含的 gimbal 字段
        for key in ("power_state", "yaw_deg_internal", "yaw_deg_display",
                     "pitch_deg", "yaw_rate_dps", "pitch_rate_dps"):
            self.assertNotIn(key, gimbal, f"gimbal 不应包含 {key}")

    def test_research_removes_camera_details(self):
        """camera 只保留 f_current_mm。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="research")
        result = f.filter_obs(obs)

        camera = result["camera"]
        self.assertIn("f_current_mm", camera)
        self.assertEqual(camera["f_current_mm"], 12.0)

        for key in ("power_state", "f_target_mm", "frame_id", "in_fov", "u_px", "v_px"):
            self.assertNotIn(key, camera, f"camera 不应包含 {key}")

    def test_research_keeps_frame_intrinsics(self):
        """frame.image 和 frame.intrinsics 被保留。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="research")
        result = f.filter_obs(obs)

        frame = result["frame"]
        self.assertIsInstance(frame, FramePacket)
        self.assertEqual(frame.image.shape, (480, 640))
        self.assertIn("f_mm", frame.intrinsics)
        self.assertIn("cx", frame.intrinsics)

    def test_research_removes_frame_optional_gt(self):
        """research 模式必须剥离 frame.optional_gt，避免真值投影泄漏。"""
        obs = _make_world_obs_with_gt()
        f = ObsFilter(mode="research")
        result = f.filter_obs(obs)

        self.assertIsInstance(result["frame"], FramePacket)
        self.assertIsNone(result["frame"].optional_gt)
        self.assertIsNot(result["frame"], obs["frame"], "research 模式不应直接复用原始 FramePacket")


# ===================================================================
# TestRealisticMode
# ===================================================================

class TestRealisticMode(unittest.TestCase):
    """realistic 模式：有噪声 gimbal 测量值，无 target。"""

    def test_realistic_removes_target(self):
        """target 完全被过滤。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="realistic")
        result = f.filter_obs(obs)
        self.assertEqual(result["target"], {})

    def test_realistic_keeps_gimbal_whitelist(self):
        """gimbal 保留 mode, yaw_deg_internal, pitch_deg, yaw_rate_dps, pitch_rate_dps。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="realistic", encoder_noise_std_deg=0.0, gyro_noise_std_dps=0.0)
        result = f.filter_obs(obs)

        gimbal = result["gimbal"]
        expected_keys = {"mode", "yaw_deg_internal", "pitch_deg", "yaw_rate_dps", "pitch_rate_dps"}
        self.assertEqual(set(gimbal.keys()), expected_keys)

    def test_realistic_no_noise_when_std_zero(self):
        """encoder_noise_std_deg=0 且 gyro_noise_std_dps=0 时，值无变化。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="realistic", encoder_noise_std_deg=0.0, gyro_noise_std_dps=0.0)
        result = f.filter_obs(obs)

        gimbal = result["gimbal"]
        self.assertEqual(gimbal["mode"], "ANGLE_MODE")
        self.assertAlmostEqual(gimbal["yaw_deg_internal"], 5.0)
        self.assertAlmostEqual(gimbal["pitch_deg"], 0.0)
        self.assertAlmostEqual(gimbal["yaw_rate_dps"], 0.1)
        self.assertAlmostEqual(gimbal["pitch_rate_dps"], 0.0)

    def test_realistic_noise_reproducible_with_seed(self):
        """设置 np.random.seed 后噪声可重复。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="realistic", encoder_noise_std_deg=0.5, gyro_noise_std_dps=1.0)

        np.random.seed(42)
        r1 = f.filter_obs(obs)

        np.random.seed(42)
        r2 = f.filter_obs(obs)

        self.assertEqual(r1["gimbal"]["yaw_deg_internal"], r2["gimbal"]["yaw_deg_internal"])
        self.assertEqual(r1["gimbal"]["pitch_deg"], r2["gimbal"]["pitch_deg"])
        self.assertEqual(r1["gimbal"]["yaw_rate_dps"], r2["gimbal"]["yaw_rate_dps"])
        self.assertEqual(r1["gimbal"]["pitch_rate_dps"], r2["gimbal"]["pitch_rate_dps"])

    def test_realistic_encoder_noise_present(self):
        """encoder_noise_std_deg>0 时角度有噪声。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="realistic", encoder_noise_std_deg=5.0, gyro_noise_std_dps=0.0)

        # 多次采样，至少有一次角度偏离原始值
        raw_yaw = obs["gimbal"]["yaw_deg_internal"]  # 5.0
        raw_pitch = obs["gimbal"]["pitch_deg"]  # 0.0

        noisy_yaw_count = 0
        noisy_pitch_count = 0
        for _ in range(50):
            result = f.filter_obs(obs)
            if result["gimbal"]["yaw_deg_internal"] != raw_yaw:
                noisy_yaw_count += 1
            if result["gimbal"]["pitch_deg"] != raw_pitch:
                noisy_pitch_count += 1

        self.assertGreater(noisy_yaw_count, 0, "编码器噪声应在多次采样中使 yaw 偏离原始值")
        self.assertGreater(noisy_pitch_count, 0, "编码器噪声应在多次采样中使 pitch 偏离原始值")

    def test_realistic_gyro_noise_present(self):
        """gyro_noise_std_dps>0 时角速度有噪声。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="realistic", encoder_noise_std_deg=0.0, gyro_noise_std_dps=5.0)

        raw_yaw_rate = obs["gimbal"]["yaw_rate_dps"]  # 0.1
        raw_pitch_rate = obs["gimbal"]["pitch_rate_dps"]  # 0.0

        noisy_yaw_rate_count = 0
        noisy_pitch_rate_count = 0
        for _ in range(50):
            result = f.filter_obs(obs)
            if result["gimbal"]["yaw_rate_dps"] != raw_yaw_rate:
                noisy_yaw_rate_count += 1
            if result["gimbal"]["pitch_rate_dps"] != raw_pitch_rate:
                noisy_pitch_rate_count += 1

        self.assertGreater(noisy_yaw_rate_count, 0, "陀螺仪噪声应在多次采样中使 yaw_rate 偏离原始值")
        self.assertGreater(noisy_pitch_rate_count, 0, "陀螺仪噪声应在多次采样中使 pitch_rate 偏离原始值")

    def test_realistic_uses_gimbal_measured(self):
        """当 gimbal_measured 不为 None 时使用其值而非 world_obs['gimbal']。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="realistic", encoder_noise_std_deg=0.0, gyro_noise_std_dps=0.0)

        measured = {
            "mode": "RATE_MODE",
            "yaw_deg_internal": 99.0,
            "pitch_deg": -10.0,
            "yaw_rate_dps": 5.0,
            "pitch_rate_dps": -3.0,
        }
        result = f.filter_obs(obs, gimbal_measured=measured)

        gimbal = result["gimbal"]
        self.assertEqual(gimbal["mode"], "RATE_MODE")
        self.assertAlmostEqual(gimbal["yaw_deg_internal"], 99.0)
        self.assertAlmostEqual(gimbal["pitch_deg"], -10.0)
        self.assertAlmostEqual(gimbal["yaw_rate_dps"], 5.0)
        self.assertAlmostEqual(gimbal["pitch_rate_dps"], -3.0)

    def test_realistic_keeps_camera_f_current_mm(self):
        """camera 保留 f_current_mm。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="realistic")
        result = f.filter_obs(obs)

        camera = result["camera"]
        self.assertIn("f_current_mm", camera)
        self.assertEqual(camera["f_current_mm"], 12.0)

        # 不应包含的 camera 字段
        for key in ("power_state", "f_target_mm", "frame_id", "in_fov", "u_px", "v_px"):
            self.assertNotIn(key, camera, f"camera 不应包含 {key}")

    def test_realistic_keeps_frame(self):
        """frame 被保留。"""
        obs = _make_world_obs()
        f = ObsFilter(mode="realistic")
        result = f.filter_obs(obs)

        frame = result["frame"]
        self.assertIsInstance(frame, FramePacket)
        self.assertEqual(frame.image.shape, (480, 640))
        self.assertIn("f_mm", frame.intrinsics)

    def test_realistic_removes_frame_optional_gt(self):
        """realistic 模式必须剥离 frame.optional_gt，避免真值投影泄漏。"""
        obs = _make_world_obs_with_gt()
        f = ObsFilter(mode="realistic")
        result = f.filter_obs(obs)

        self.assertIsInstance(result["frame"], FramePacket)
        self.assertIsNone(result["frame"].optional_gt)
        self.assertIsNot(result["frame"], obs["frame"], "realistic 模式不应直接复用原始 FramePacket")

    def test_realistic_preserves_none_frame(self):
        """frame=None 时应保持 None，不能替换成空 dict。"""
        obs = _make_world_obs()
        obs["frame"] = None
        f = ObsFilter(mode="realistic")
        result = f.filter_obs(obs)
        self.assertIsNone(result["frame"])


# ===================================================================
# TestObsFilterValidation
# ===================================================================

class TestObsFilterValidation(unittest.TestCase):
    """ObsFilter 构造参数校验。"""

    def test_invalid_mode_raises(self):
        """传入非法 mode 字符串时 __init__ 应抛 ValueError。"""
        with self.assertRaises(ValueError):
            ObsFilter(mode="unknown_mode")

    def test_invalid_mode_error_message(self):
        """错误信息包含非法 mode 值。"""
        with self.assertRaises(ValueError) as ctx:
            ObsFilter(mode="foo")
        self.assertIn("foo", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
