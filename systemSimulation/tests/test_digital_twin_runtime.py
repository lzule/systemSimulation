import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.digital_twin_runtime import DigitalTwinRuntime
from runtime.types import Command
from simulation.obs_filter import ObsFilter
from config import GimbalConfig, gimbal_cfg


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


class _RecordObsProgram:
    def __init__(self):
        self.last_obs = None

    def on_tick(self, obs):
        self.last_obs = obs
        return []


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

    def test_realistic_obs_uses_quantized_measured_gimbal_state(self):
        old_resolution = gimbal_cfg.encoder_resolution_deg
        try:
            gimbal_cfg.encoder_resolution_deg = 5.0
            rt = DigitalTwinRuntime(
                dt_s=0.01,
                obs_filter=ObsFilter(mode="realistic", encoder_noise_std_deg=0.0, gyro_noise_std_dps=0.0),
            )
            rt.gimbal_client.power_on()
            rt.camera_client.power_on()
            rt.raspi_client.power_on()
            rt.step(260)

            rt.gimbal_client.set_mode("RATE_MODE")
            rt.gimbal_client.set_rate_target(13.7, 0.0)
            rt.step(7)

            recorder = _RecordObsProgram()
            rt.raspi.set_delay_profile(
                {
                    "image_read_delay_s": 0.0,
                    "image_process_delay_s": 0.0,
                    "state_read_delay_s": 0.0,
                    "command_tx_delay_s": 0.0,
                    "jitter_std_s": 0.0,
                }
            )
            rt.raspi.load_control_program(recorder)
            rt.step(2)

            self.assertIsNotNone(recorder.last_obs, "realistic 模式下应已向控制程序传入观测")
            raw = rt.get_world_snapshot().gimbal["yaw_deg_internal"]
            measured = rt.gimbal.get_measured_state(rt.t)["yaw_deg_internal"]
            obs_yaw = recorder.last_obs["gimbal"]["yaw_deg_internal"]

            self.assertAlmostEqual(obs_yaw, measured, places=9)
            self.assertNotAlmostEqual(raw, measured, places=9)
            self.assertEqual(recorder.last_obs["gimbal"]["mode"], "RATE_MODE")
        finally:
            gimbal_cfg.encoder_resolution_deg = old_resolution


if __name__ == "__main__":
    unittest.main()
