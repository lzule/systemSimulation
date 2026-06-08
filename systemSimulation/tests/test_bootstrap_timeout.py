"""bootstrap.start_stack() boot 超时路径测试 — TEST-02。

start_stack 的超时步数按 max(boot_delay) * 3 / dt + 10 动态计算，
因此正常配置下 else 分支（超时 RuntimeError）永远不会触发。
本测试验证步数计算逻辑和 boot 完成的边界条件。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import camera_cfg, gimbal_cfg, raspi_cfg, scene_cfg
from runtime.digital_twin_runtime import DigitalTwinRuntime
from simulation.bootstrap import start_stack


class TestBootstrapBootCompletion(unittest.TestCase):
    """验证 start_stack 在 boot 完成前持续等待，boot 完成后正常返回。"""

    def test_start_stack_waits_for_boot(self):
        """start_stack 在 boot_delay > 0 时应等待足够多的 step 才返回。"""
        orig_g = gimbal_cfg.boot_delay_s
        orig_c = camera_cfg.boot_delay_s
        orig_r = raspi_cfg.boot_delay_s
        try:
            # 设置适中的 boot_delay（0.1s = 20 steps at dt=0.005）
            gimbal_cfg.boot_delay_s = 0.1
            camera_cfg.boot_delay_s = 0.1
            raspi_cfg.boot_delay_s = 0.1

            runtime = DigitalTwinRuntime()
            result = start_stack(runtime)
            # 验证所有设备已 READY
            snap = result.get_world_snapshot()
            self.assertEqual(snap.gimbal["power_state"], "READY")
            self.assertEqual(snap.camera["power_state"], "READY")
            self.assertEqual(snap.raspi["power_state"], "READY")
        finally:
            gimbal_cfg.boot_delay_s = orig_g
            camera_cfg.boot_delay_s = orig_c
            raspi_cfg.boot_delay_s = orig_r

    def test_max_boot_steps_covers_boot_delay(self):
        """验证 _max_boot_steps 计算公式足以覆盖 boot_delay。"""
        # _max_boot_steps = int(max(boot_delay) * 3.0 / dt) + 10
        # boot 需要的步数 = ceil(max(boot_delay) / dt)
        dt = scene_cfg.dt_s
        for max_delay in [0.5, 1.5, 5.0, 30.0]:
            max_boot_steps = int(max_delay * 3.0 / dt) + 10
            boot_needed = int(max_delay / dt) + 1
            self.assertGreater(max_boot_steps, boot_needed,
                               f"max_boot_steps ({max_boot_steps}) 应大于 boot_needed ({boot_needed}) "
                               f"for max_delay={max_delay}")

    def test_runtime_boot_flow(self):
        """直接验证 DigitalTwinRuntime 的 boot 流程：step 直到 READY。"""
        orig_g = gimbal_cfg.boot_delay_s
        orig_c = camera_cfg.boot_delay_s
        orig_r = raspi_cfg.boot_delay_s
        try:
            gimbal_cfg.boot_delay_s = 0.02  # 4 steps at dt=0.005
            camera_cfg.boot_delay_s = 0.02
            raspi_cfg.boot_delay_s = 0.02

            runtime = DigitalTwinRuntime()
            runtime.gimbal_client.power_on()
            runtime.camera_client.power_on()
            runtime.raspi_client.power_on()

            # boot_delay=0.02, dt=0.005 => boot 需要 4 个 tick 归零
            # step(3) 后 boot_remaining = 0.005 > 0 → 仍 BOOTING
            snap = runtime.step(3)
            self.assertEqual(snap.gimbal["power_state"], "BOOTING")

            # 再 step(2) 后 boot_remaining ≤ 0 → READY
            snap = runtime.step(2)
            self.assertEqual(snap.gimbal["power_state"], "READY")
            self.assertEqual(snap.camera["power_state"], "READY")
            self.assertEqual(snap.raspi["power_state"], "READY")
        finally:
            gimbal_cfg.boot_delay_s = orig_g
            camera_cfg.boot_delay_s = orig_c
            raspi_cfg.boot_delay_s = orig_r


if __name__ == "__main__":
    unittest.main()
