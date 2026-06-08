"""命令 payload schema 校验测试 — FUNC-01。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.types import Command
from simulation.bootstrap import build_runtime


class TestCommandPayloadValidation(unittest.TestCase):
    """_dispatch 入口对 Command.payload 的 schema 校验。"""

    @classmethod
    def setUpClass(cls):
        cls.runtime = build_runtime(delay_ms=0.0)

    def test_missing_yaw_field_rejected(self):
        """set_angle_target 缺少 yaw 字段应返回 INVALID_PAYLOAD。"""
        cmd = Command(target="gimbal", action="set_angle_target", payload={"pitch": 5.0})
        result = self.runtime._dispatch(cmd)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "INVALID_PAYLOAD")
        self.assertIn("yaw", result.message)

    def test_missing_mode_field_rejected(self):
        """set_mode 缺少 mode 字段应返回 INVALID_PAYLOAD。"""
        cmd = Command(target="gimbal", action="set_mode", payload={})
        result = self.runtime._dispatch(cmd)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "INVALID_PAYLOAD")

    def test_wrong_type_rejected(self):
        """set_mode 的 mode 不是 str 时应返回 INVALID_PAYLOAD。"""
        cmd = Command(target="gimbal", action="set_mode", payload={"mode": 123})
        result = self.runtime._dispatch(cmd)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "INVALID_PAYLOAD")

    def test_valid_command_accepted(self):
        """有效 payload 应正常执行。"""
        cmd = Command(target="gimbal", action="set_angle_target", payload={"yaw": 10.0, "pitch": 5.0})
        result = self.runtime._dispatch(cmd)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "OK")

    def test_camera_missing_f_mm_rejected(self):
        """set_zoom_target_mm 缺少 f_mm 字段应返回 INVALID_PAYLOAD。"""
        cmd = Command(target="camera", action="set_zoom_target_mm", payload={})
        result = self.runtime._dispatch(cmd)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "INVALID_PAYLOAD")

    def test_power_on_no_payload_required(self):
        """power_on 不需要 payload，空 payload 应正常执行。"""
        cmd = Command(target="gimbal", action="power_on", payload={})
        result = self.runtime._dispatch(cmd)
        # power_on 对已上电的 gimbal 返回 ALREADY_ON，不是 INVALID_PAYLOAD
        self.assertNotEqual(result.code, "INVALID_PAYLOAD")


class TestTargetEntityDeepCopy(unittest.TestCase):
    """BUG-01 修复验证：TargetEntity 深拷贝配置，互不影响。"""

    def test_two_entities_have_independent_config(self):
        from config import target_cfg
        from entities.target.entity import TargetEntity

        t1 = TargetEntity()
        t2 = TargetEntity()

        # 修改 t1 的配置不应影响 t2
        t1.cfg.motion_type = "constant_velocity"
        self.assertEqual(t2.cfg.motion_type, target_cfg.motion_type,
                         "修改一个 TargetEntity 的配置不应影响另一个")

    def test_entity_config_independent_from_global(self):
        from config import target_cfg
        from entities.target.entity import TargetEntity

        original = target_cfg.motion_type
        t = TargetEntity()

        # 修改全局配置不应影响已创建的 entity
        target_cfg.motion_type = "waypoint"
        self.assertEqual(t.cfg.motion_type, original,
                         "修改全局 target_cfg 不应影响已创建的 TargetEntity")
        # 恢复
        target_cfg.motion_type = original


class TestGimbalGetStateNoSideEffect(unittest.TestCase):
    """BUG-03 修复验证：get_state() 首次调用不产生控制器副作用。"""

    def test_get_state_does_not_modify_integral(self):
        from entities.gimbal.entity import GimbalEntity

        g = GimbalEntity()
        # 首次 get_state 不应修改积分器
        g.get_state(0.0)
        self.assertEqual(g.controller._yaw_rate_i, 0.0,
                         "get_state() 不应修改 yaw_rate 积分器")
        self.assertEqual(g.controller._pitch_rate_i, 0.0,
                         "get_state() 不应修改 pitch_rate 积分器")


class TestControllerRateTickCaching(unittest.TestCase):
    """BUG-04 修复验证：非 rate_tick 时复用上次输出。"""

    def test_non_rate_tick_reuses_last_output(self):
        from entities.gimbal.control import CascadedController2Axis, RATE_MODE

        ctrl = CascadedController2Axis()
        ctrl.set_mode(RATE_MODE)
        ctrl.set_rate_target(10.0, 0.0, timestamp=0.0)

        # 第一步：rate_tick 正常触发
        r1 = ctrl.step(0.0, 0.0, 0.0, 0.0, dt=0.005)
        self.assertTrue(r1["rate_tick"])

        # 第二步：rate_tick 也应触发（rate_loop_hz=200, dt=0.005 => 每 step 都触发）
        r2 = ctrl.step(0.0, 0.0, 0.0, 0.0, dt=0.005)
        self.assertTrue(r2["rate_tick"])

        # 构造非 rate_tick 场景：rate_loop_hz=100, dt=0.005 => 每 2 步触发一次
        from config import LoopConfig
        slow_loop_cfg = LoopConfig(angle_loop_hz=50.0, rate_loop_hz=100.0)
        ctrl2 = CascadedController2Axis(loop_config=slow_loop_cfg)
        ctrl2.set_mode(RATE_MODE)
        ctrl2.set_rate_target(10.0, 0.0, timestamp=0.0)

        r_a = ctrl2.step(0.0, 0.0, 0.0, 0.0, dt=0.005)
        # 第一步 rate_dt=0.01, accum=0.005, 不触发 rate_tick
        if not r_a["rate_tick"]:
            # 非 rate_tick 时输出应等于初始零值
            self.assertEqual(r_a["yaw_rate_cmd_dps"], 0.0)
            self.assertEqual(r_a["pitch_rate_cmd_dps"], 0.0)

        r_b = ctrl2.step(0.0, 0.0, 0.0, 0.0, dt=0.005)
        # 第二步 accum=0.01, 触发 rate_tick
        self.assertTrue(r_b["rate_tick"])

        r_c = ctrl2.step(0.0, 0.0, 0.0, 0.0, dt=0.005)
        # 第三步 accum=0.005, 不触发 rate_tick, 输出应与 r_b 一致
        if not r_c["rate_tick"]:
            self.assertAlmostEqual(r_c["yaw_rate_cmd_dps"], r_b["yaw_rate_cmd_dps"])
            self.assertAlmostEqual(r_c["pitch_rate_cmd_dps"], r_b["pitch_rate_cmd_dps"])


if __name__ == "__main__":
    unittest.main()
