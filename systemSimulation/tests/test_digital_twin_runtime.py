import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.digital_twin_runtime import DigitalTwinRuntime
from runtime.types import Command


class _RateProgram:
    def on_tick(self, obs):
        ts = float(obs["timestamp"])
        return [
            Command(target="gimbal", action="set_mode", payload={"mode": "RATE_MODE"}, timestamp=ts, source="raspi"),
            Command(
                target="gimbal",
                action="set_rate_target",
                payload={"yaw_rate": 20.0, "pitch_rate": 0.0},
                timestamp=ts,
                source="raspi",
            ),
        ]


class TestDigitalTwinRuntime(unittest.TestCase):
    def _ready_runtime(self, dt=0.01):
        rt = DigitalTwinRuntime(dt_s=dt)
        rt.gimbal_client.power_on()
        rt.camera_client.power_on()
        rt.raspi_client.power_on()
        rt.step(260)
        return rt

    def test_raspi_delay_pipeline_semantics(self):
        rt = self._ready_runtime()
        rt.raspi_client.set_delay_profile(
            image_read_delay_s=0.10,
            image_process_delay_s=0.04,
            state_read_delay_s=0.02,
            command_tx_delay_s=0.05,
            jitter_std_s=0.0,
        )
        rt.raspi_client.load_control_program(_RateProgram())

        rt.step(250)
        s = rt.get_world_snapshot().raspi

        self.assertFalse(math.isnan(s["effective_obs_timestamp"]))
        delay_obs = rt.t - s["effective_obs_timestamp"]
        self.assertGreaterEqual(delay_obs, 0.09)
        self.assertGreaterEqual(s["last_process_latency_s"], 0.13)
        self.assertFalse(math.isnan(s["last_command_apply_timestamp"]))
        self.assertGreaterEqual(s["pipeline_backlog_len"], 0)
        self.assertIn("delay_metrics", s)

    def test_raspi_delay_does_not_slow_other_entities(self):
        rt_fast = self._ready_runtime()
        rt_slow = self._ready_runtime()

        rt_slow.raspi_client.set_delay_profile(
            image_read_delay_s=0.40,
            image_process_delay_s=0.30,
            state_read_delay_s=0.25,
            command_tx_delay_s=0.20,
            jitter_std_s=0.01,
        )

        for _ in range(300):
            rt_fast.step(1)
            rt_slow.step(1)

        snap_fast = rt_fast.get_world_snapshot()
        snap_slow = rt_slow.get_world_snapshot()

        self.assertAlmostEqual(snap_fast.timestamp, snap_slow.timestamp, places=9)
        self.assertAlmostEqual(snap_fast.target["x_m"], snap_slow.target["x_m"], places=6)
        self.assertAlmostEqual(snap_fast.target["y_m"], snap_slow.target["y_m"], places=6)
        self.assertAlmostEqual(snap_fast.gimbal["yaw_deg_internal"], snap_slow.gimbal["yaw_deg_internal"], places=6)
        self.assertEqual(snap_fast.camera["frame_id"], snap_slow.camera["frame_id"])


if __name__ == "__main__":
    unittest.main()

