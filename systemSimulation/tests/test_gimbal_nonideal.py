"""云台非理想项回归测试（阶段3轮B任务B3）。

覆盖三方面非理想行为：
  1. 编码器量化 — GimbalEntity.get_measured_state()
  2. 静摩擦死区 — GimbalPlant2Axis.step()
  3. 时间常数偏差 — GimbalPlant2Axis.__init__()
"""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import AxisLimitConfig, GimbalConfig
from entities.gimbal.control import ANGLE_MODE, RATE_MODE
from entities.gimbal.entity import GimbalEntity
from entities.gimbal.model import GimbalPlant2Axis


# ---------------------------------------------------------------------------
# 辅助：构造已就绪的 GimbalEntity
# ---------------------------------------------------------------------------
def _make_ready_entity(gimbal_cfg: GimbalConfig | None = None) -> GimbalEntity:
    """创建一个已就绪（POWER_READY）的 GimbalEntity。"""
    cfg = gimbal_cfg or GimbalConfig(boot_delay_s=0.0)
    if cfg.boot_delay_s != 0.0:
        cfg = GimbalConfig(
            boot_delay_s=0.0,
            encoder_resolution_deg=cfg.encoder_resolution_deg,
            static_friction_threshold_dps=cfg.static_friction_threshold_dps,
            tau_deviation_ratio=cfg.tau_deviation_ratio,
            response_tau_s=cfg.response_tau_s,
        )
    entity = GimbalEntity(gimbal_config=cfg)
    entity.power_on(0.0)
    # boot_delay_s=0，一次 update 即进入 READY
    entity.update(0.001, 0.001)
    return entity


# ===================================================================
# 1. 编码器量化
# ===================================================================
class TestEncoderQuantization(unittest.TestCase):
    """测试 get_measured_state() 的编码器量化行为。"""

    def test_zero_resolution_no_quantization(self):
        """encoder_resolution_deg=0 时量化关闭，measured_state == 连续值。"""
        entity = _make_ready_entity(GimbalConfig(
            boot_delay_s=0.0,
            encoder_resolution_deg=0.0,
        ))
        # 施加一个速率命令，让角度偏离 0
        entity.set_mode(RATE_MODE, 0.001)
        entity.set_rate_target(10.0, 5.0, 0.001)
        entity.update(0.1, 0.101)

        raw = entity.get_state(0.101)
        measured = entity.get_measured_state(0.101)

        self.assertEqual(measured["yaw_deg_internal"], raw["yaw_deg_internal"])
        self.assertEqual(measured["pitch_deg"], raw["pitch_deg"])

    def test_quantized_values_are_resolution_multiples(self):
        """encoder_resolution_deg=0.5 时量化后角度是 0.5 的整数倍。"""
        entity = _make_ready_entity(GimbalConfig(
            boot_delay_s=0.0,
            encoder_resolution_deg=0.5,
        ))
        # 驱动角度到非整数倍位置
        entity.set_mode(RATE_MODE, 0.001)
        entity.set_rate_target(13.7, 7.3, 0.001)
        for i in range(200):
            entity.update(0.01, 0.001 + (i + 1) * 0.01)

        measured = entity.get_measured_state(2.001)
        res = 0.5
        yaw_q = measured["yaw_deg_internal"]
        pitch_q = measured["pitch_deg"]

        # 量化值应为 res 的整数倍（允许浮点误差）
        self.assertAlmostEqual(yaw_q / res, round(yaw_q / res), places=9)
        self.assertAlmostEqual(pitch_q / res, round(pitch_q / res), places=9)

    def test_quantization_does_not_modify_internal_state(self):
        """调用 get_measured_state() 不影响 get_state() 的连续值。"""
        entity = _make_ready_entity(GimbalConfig(
            boot_delay_s=0.0,
            encoder_resolution_deg=0.5,
        ))
        # 驱动到非整数倍位置
        entity.set_mode(RATE_MODE, 0.001)
        entity.set_rate_target(13.7, 7.3, 0.001)
        for i in range(100):
            entity.update(0.01, 0.001 + (i + 1) * 0.01)

        ts = 1.001
        raw_before = entity.get_state(ts)
        _ = entity.get_measured_state(ts)
        raw_after = entity.get_state(ts)

        self.assertEqual(raw_before["yaw_deg_internal"], raw_after["yaw_deg_internal"])
        self.assertEqual(raw_before["pitch_deg"], raw_after["pitch_deg"])

    def test_quantization_rounds_correctly(self):
        """验证具体值的量化结果（如 1.3 → 1.5，0.1 → 0.0）。"""
        res = 0.5
        # 1.3 → round(1.3/0.5)*0.5 = round(2.6)*0.5 = 3*0.5 = 1.5
        self.assertAlmostEqual(round(1.3 / res) * res, 1.5, places=9)
        # 0.1 → round(0.1/0.5)*0.5 = round(0.2)*0.5 = 0.0
        self.assertAlmostEqual(round(0.1 / res) * res, 0.0, places=9)
        # 1.25 → round(1.25/0.5)*0.5 = round(2.5)*0.5 = 2*0.5 = 1.0  (Python round half-to-even)
        self.assertAlmostEqual(round(1.25 / res) * res, 1.0, places=9)
        # -0.8 → round(-0.8/0.5)*0.5 = round(-1.6)*0.5 = -2*0.5 = -1.0
        self.assertAlmostEqual(round(-0.8 / res) * res, -1.0, places=9)


# ===================================================================
# 2. 静摩擦死区
# ===================================================================
class TestStaticFriction(unittest.TestCase):
    """测试 step() 中静摩擦死区逻辑。"""

    def test_zero_threshold_no_deadzone(self):
        """static_friction_threshold_dps=0 时无死区，低速率命令正常执行。"""
        cfg = GimbalConfig(
            response_tau_s=0.001,  # 极小 tau，使速率快速跟踪命令
            static_friction_threshold_dps=0.0,
        )
        plant = GimbalPlant2Axis(axis_cfg=AxisLimitConfig(), legacy_gimbal_cfg=cfg)

        # 静止状态下施加微小速率命令
        plant.step((0.01, 0.01), 0.01)
        # tau 极小，速率应快速跟踪到命令值
        self.assertGreater(abs(plant.yaw_rate_dps), 1e-6)
        self.assertGreater(abs(plant.pitch_rate_dps), 1e-6)

    def test_low_rate_absorbed_when_stationary(self):
        """静止时低于阈值的命令被吸收为 0。"""
        threshold = 2.0
        cfg = GimbalConfig(
            response_tau_s=0.001,
            static_friction_threshold_dps=threshold,
        )
        plant = GimbalPlant2Axis(axis_cfg=AxisLimitConfig(), legacy_gimbal_cfg=cfg)

        # 初始静止，施加低于阈值的命令
        self.assertAlmostEqual(plant.yaw_rate_dps, 0.0, places=12)
        self.assertAlmostEqual(plant.pitch_rate_dps, 0.0, places=12)

        plant.step((1.0, 1.5), 0.01)  # 均低于 threshold=2.0

        # 命令被吸收为 0，速率应保持为 0（tau 极小）
        self.assertAlmostEqual(plant.yaw_rate_dps, 0.0, places=9)
        self.assertAlmostEqual(plant.pitch_rate_dps, 0.0, places=9)

    def test_high_rate_passes_when_stationary(self):
        """静止时高于阈值的命令正常执行。"""
        threshold = 2.0
        cfg = GimbalConfig(
            response_tau_s=0.001,
            static_friction_threshold_dps=threshold,
        )
        plant = GimbalPlant2Axis(axis_cfg=AxisLimitConfig(), legacy_gimbal_cfg=cfg)

        # 初始静止，施加高于阈值的命令
        plant.step((5.0, 3.0), 0.01)

        # 命令不被吸收，速率应非零
        self.assertGreater(abs(plant.yaw_rate_dps), 0.1)
        self.assertGreater(abs(plant.pitch_rate_dps), 0.1)

    def test_friction_not_applied_when_moving(self):
        """已在运动时，低速率命令正常执行（动摩擦，非静摩擦）。"""
        threshold = 2.0
        cfg = GimbalConfig(
            response_tau_s=0.001,
            static_friction_threshold_dps=threshold,
        )
        plant = GimbalPlant2Axis(axis_cfg=AxisLimitConfig(), legacy_gimbal_cfg=cfg)

        # 先用高命令驱动到运动状态
        plant.step((10.0, 10.0), 0.01)
        self.assertGreater(abs(plant.yaw_rate_dps), 1.0)

        # 现在施加低于阈值的命令 — 此时已在运动，不应被吸收
        plant.step((1.0, 1.0), 0.01)
        # 速率应能继续变化（不会被锁为 0）
        self.assertNotAlmostEqual(plant.yaw_rate_dps, 0.0, places=2)
        self.assertNotAlmostEqual(plant.pitch_rate_dps, 0.0, places=2)

    def test_friction_does_not_affect_default_config(self):
        """默认参数 (static_friction_threshold_dps=0) 下行为不变。"""
        cfg = GimbalConfig()  # 默认 threshold=0
        plant = GimbalPlant2Axis(axis_cfg=AxisLimitConfig(), legacy_gimbal_cfg=cfg)

        # 静止状态下施加任意低速率命令
        plant.step((0.001, 0.001), 0.01)
        # 默认无死区，速率应非零
        self.assertNotAlmostEqual(plant.yaw_rate_dps, 0.0, places=6)
        self.assertNotAlmostEqual(plant.pitch_rate_dps, 0.0, places=6)


# ===================================================================
# 3. 时间常数偏差
# ===================================================================
class TestTauDeviation(unittest.TestCase):
    """测试 __init__() 中 tau 随机偏差行为。"""

    def test_zero_ratio_no_deviation(self):
        """tau_deviation_ratio=0 时 tau 不变。"""
        tau_nominal = 0.05
        cfg = GimbalConfig(
            response_tau_s=tau_nominal,
            tau_deviation_ratio=0.0,
        )
        plant = GimbalPlant2Axis(axis_cfg=AxisLimitConfig(), legacy_gimbal_cfg=cfg)
        self.assertAlmostEqual(plant.response_tau_s, tau_nominal, places=12)

    def test_nonzero_ratio_changes_tau(self):
        """tau_deviation_ratio>0 时 tau 有偏差（多数情况不等于标称值）。"""
        tau_nominal = 0.05
        ratio = 0.3  # 较大偏差比
        cfg = GimbalConfig(
            response_tau_s=tau_nominal,
            tau_deviation_ratio=ratio,
        )

        # 创建大量实例，统计 tau 是否有变化
        taus = []
        for _ in range(200):
            plant = GimbalPlant2Axis(axis_cfg=AxisLimitConfig(), legacy_gimbal_cfg=cfg)
            taus.append(plant.response_tau_s)

        # 至少应有一些 tau 不等于标称值
        n_different = sum(1 for t in taus if abs(t - tau_nominal) > 1e-9)
        self.assertGreater(n_different, 0, "至少部分实例的 tau 应偏离标称值")

        # tau 应全部为正数
        for t in taus:
            self.assertGreater(t, 0.0)

    def test_deviation_fixed_after_init(self):
        """偏差在初始化时确定，多次 reset() 不改变 tau。"""
        np.random.seed(42)
        cfg = GimbalConfig(
            response_tau_s=0.05,
            tau_deviation_ratio=0.2,
        )
        plant = GimbalPlant2Axis(axis_cfg=AxisLimitConfig(), legacy_gimbal_cfg=cfg)
        tau_after_init = plant.response_tau_s

        plant.reset()
        self.assertAlmostEqual(plant.response_tau_s, tau_after_init, places=15)

        plant.reset()
        self.assertAlmostEqual(plant.response_tau_s, tau_after_init, places=15)

        # 再运行一些 step 后 reset
        plant.step((10.0, 5.0), 0.01)
        plant.reset()
        self.assertAlmostEqual(plant.response_tau_s, tau_after_init, places=15)

    def test_default_config_no_deviation(self):
        """默认参数 (tau_deviation_ratio=0) 下 tau 等于配置值。"""
        cfg = GimbalConfig()  # 默认 tau=0.03, ratio=0
        plant = GimbalPlant2Axis(axis_cfg=AxisLimitConfig(), legacy_gimbal_cfg=cfg)
        self.assertAlmostEqual(plant.response_tau_s, cfg.response_tau_s, places=12)


if __name__ == "__main__":
    unittest.main()
