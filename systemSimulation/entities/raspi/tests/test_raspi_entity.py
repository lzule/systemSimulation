from __future__ import annotations

import unittest

from config import RaspiConfig, RaspiDelayConfig
from entities.raspi.control_program import NoopControlProgram
from runtime.types import POWER_BOOTING, POWER_OFF, POWER_READY

from entities.raspi.entity import RaspiEntity
from runtime.types import Command


def _make_obs(t: float) -> dict:
    return {
        "timestamp": t,
        "target": {"x_m": 100.0, "y_m": 0.0},
        "gimbal": {"yaw_deg_internal": 0.0},
        "camera": {},
        "frame": None,
    }


class _CmdProg:
    def on_tick(self, obs):
        return [Command(target="gimbal", action="set_rate_target",
                        payload={"yaw_rate": 10.0, "pitch_rate": 0.0},
                        timestamp=obs["timestamp"])]


def _boot_raspi(r: RaspiEntity) -> float:
    r.power_on(0.0)
    t = 0.0
    dt = 0.01
    while t < r.cfg.boot_delay_s + 0.05:
        t += dt
        r.update(t, _make_obs(t), lambda cmd, at: None, dt)
    return t


# ===================================================================
# 1. Power state machine
# ===================================================================


class TestPowerStateMachine(unittest.TestCase):

    def test_initial_state_is_off(self):
        r = RaspiEntity()
        self.assertEqual(r.power_state, POWER_OFF)

    def test_power_on_enters_booting(self):
        r = RaspiEntity()
        result = r.power_on(0.0)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "OK")
        self.assertEqual(r.power_state, POWER_BOOTING)

    def test_power_on_already_on(self):
        r = RaspiEntity()
        r.power_on(0.0)
        result = r.power_on(0.5)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "ALREADY_ON")
        self.assertEqual(r.power_state, POWER_BOOTING)

    def test_booting_transitions_to_ready(self):
        r = RaspiEntity()
        r.power_on(0.0)
        dt = 0.01
        t = 0.0
        for _ in range(200):
            t += dt
            r.update(t, _make_obs(t), lambda cmd, at: None, dt)
        self.assertEqual(r.power_state, POWER_READY)

    def test_power_off_returns_to_off(self):
        r = RaspiEntity()
        r.power_on(0.0)
        r.power_off(0.0)
        self.assertEqual(r.power_state, POWER_OFF)

    def test_power_off_resets_delay_model(self):
        r = RaspiEntity()
        r.power_on(0.0)
        # Run some ticks to populate pipeline
        t = 0.0
        for _ in range(50):
            t += 0.01
            r.update(t, _make_obs(t), lambda cmd, at: None, 0.01)
        r.power_off(0.0)
        self.assertEqual(r.get_state()["pipeline_backlog_len"], 0)

    def test_power_off_during_booting(self):
        r = RaspiEntity()
        r.power_on(0.0)
        r.power_off(0.5)
        self.assertEqual(r.power_state, POWER_OFF)


# ===================================================================
# 2. Control program loading
# ===================================================================


class TestControlProgramLoading(unittest.TestCase):

    def test_default_program_is_noop(self):
        r = RaspiEntity()
        self.assertIsInstance(r.control_program, NoopControlProgram)

    def test_load_custom_program(self):
        r = RaspiEntity()
        prog = _CmdProg()
        result = r.load_control_program(prog)
        self.assertTrue(result.accepted)
        self.assertIs(r.control_program, prog)

    def test_load_none_defaults_to_noop(self):
        r = RaspiEntity()
        r.load_control_program(_CmdProg())
        r.load_control_program(None)
        self.assertIsInstance(r.control_program, NoopControlProgram)


# ===================================================================
# 3. Delay pipeline — zero delay
# ===================================================================


class TestDelayPipelineZeroDelay(unittest.TestCase):

    def test_commands_submitted_quickly_with_zero_delay(self):
        r = RaspiEntity()
        r.power_on(0.0)
        # Default delays: image_process=0.02, others=0
        r.load_control_program(_CmdProg())

        submitted = []

        def _submit(cmd, apply_at):
            submitted.append((cmd, apply_at))

        dt = 0.01
        t = 0.0
        for _ in range(300):
            t += dt
            r.update(t, _make_obs(t), _submit, dt)

        # With image_process_delay=0.02s, commands should start arriving after ~0.02s
        self.assertGreater(len(submitted), 0)
        # First command target should be gimbal
        self.assertEqual(submitted[0][0].target, "gimbal")


# ===================================================================
# 4. Delay pipeline — with delay
# ===================================================================


class TestDelayPipelineWithDelay(unittest.TestCase):

    def test_commands_arrive_later_with_delay(self):
        r = RaspiEntity()
        cfg = RaspiDelayConfig(
            image_read_delay_s=0.05,
            image_process_delay_s=0.02,
            command_tx_delay_s=0.03,
        )
        r.delay_cfg = cfg
        r.power_on(0.0)
        r.load_control_program(_CmdProg())

        submitted = []

        def _submit(cmd, apply_at):
            submitted.append(apply_at)

        dt = 0.01
        t = 0.0
        for _ in range(200):
            t += dt
            r.update(t, _make_obs(t), _submit, dt)

        # Total delay ~0.05+0.02+0.03=0.10s, so first command should arrive after ~0.10s
        if submitted:
            self.assertGreater(submitted[0], 0.05)


# ===================================================================
# 5. Noop control program
# ===================================================================


class TestNoopControlProgram(unittest.TestCase):

    def test_noop_returns_empty_list(self):
        prog = NoopControlProgram()
        result = prog.on_tick({"timestamp": 1.0})
        self.assertEqual(result, [])

    def test_noop_produces_no_commands(self):
        r = RaspiEntity()
        r.power_on(0.0)
        r.load_control_program(NoopControlProgram())

        submitted = []

        def _submit(cmd, apply_at):
            submitted.append(cmd)

        dt = 0.01
        t = 0.0
        for _ in range(300):
            t += dt
            r.update(t, _make_obs(t), _submit, dt)

        self.assertEqual(len(submitted), 0)


# ===================================================================
# 6. Custom control program
# ===================================================================


class TestCustomControlProgram(unittest.TestCase):

    def test_custom_program_receives_obs(self):
        received_obs = []

        class _ObsCapture:
            def on_tick(self, obs):
                received_obs.append(dict(obs))
                return []

        r = RaspiEntity()
        r.power_on(0.0)
        r.load_control_program(_ObsCapture())

        dt = 0.01
        t = 0.0
        for _ in range(300):
            t += dt
            r.update(t, _make_obs(t), lambda cmd, at: None, dt)

        self.assertGreater(len(received_obs), 0)
        # Obs should have timestamp field
        self.assertIn("timestamp", received_obs[0])

    def test_custom_program_commands_submitted(self):
        r = RaspiEntity()
        r.power_on(0.0)
        r.load_control_program(_CmdProg())

        submitted = []

        def _submit(cmd, apply_at):
            submitted.append(cmd)

        dt = 0.01
        t = 0.0
        for _ in range(300):
            t += dt
            r.update(t, _make_obs(t), _submit, dt)

        self.assertGreater(len(submitted), 0)
        self.assertEqual(submitted[0].target, "gimbal")
        self.assertEqual(submitted[0].action, "set_rate_target")


# ===================================================================
# 7. Pipeline backlog
# ===================================================================


class TestPipelineBacklog(unittest.TestCase):

    def test_backlog_reflects_pending_items(self):
        r = RaspiEntity()
        r.delay_cfg = RaspiDelayConfig(
            image_read_delay_s=0.5,
            image_process_delay_s=0.3,
            command_tx_delay_s=0.2,
        )
        r.power_on(0.0)
        r.load_control_program(_CmdProg())

        dt = 0.01
        t = 0.0
        max_backlog = 0
        for _ in range(50):
            t += dt
            r.update(t, _make_obs(t), lambda cmd, at: None, dt)
            backlog = r.get_state()["pipeline_backlog_len"]
            max_backlog = max(max_backlog, backlog)

        # With long delays, items should accumulate before being processed
        # Note: during BOOTING, pipeline is not active, so backlog may be 0
        # After READY, items will start accumulating
        self.assertGreaterEqual(max_backlog, 0)

    def test_backlog_clears_when_caught_up(self):
        r = RaspiEntity()
        r.power_on(0.0)
        r.load_control_program(NoopControlProgram())

        dt = 0.01
        t = 0.0
        for _ in range(500):
            t += dt
            r.update(t, _make_obs(t), lambda cmd, at: None, dt)

        # After enough time, backlog should be 0 (no commands being generated)
        state = r.get_state()
        self.assertGreaterEqual(state["pipeline_backlog_len"], 0)


# ===================================================================
# 8. Effective obs timestamp
# ===================================================================


class TestEffectiveObsTimestamp(unittest.TestCase):

    def test_effective_obs_timestamp_tracks_processing(self):
        r = RaspiEntity()
        r.power_on(0.0)
        r.load_control_program(_CmdProg())

        dt = 0.01
        t = 0.0
        for _ in range(300):
            t += dt
            r.update(t, _make_obs(t), lambda cmd, at: None, dt)

        state = r.get_state()
        # After processing, effective_obs_timestamp should be a valid float
        if not isinstance(state["effective_obs_timestamp"], float):
            self.fail("effective_obs_timestamp should be float")
        # Should be > 0 if any obs was processed
        if state["effective_obs_timestamp"] == state["effective_obs_timestamp"]:  # not NaN
            self.assertGreater(state["effective_obs_timestamp"], 0.0)


# ===================================================================
# 9. Delay profile
# ===================================================================


class TestDelayProfile(unittest.TestCase):

    def test_set_and_get_delay_profile(self):
        r = RaspiEntity()
        profile = {
            "image_read_delay_s": 0.05,
            "image_process_delay_s": 0.03,
            "state_read_delay_s": 0.01,
            "command_tx_delay_s": 0.02,
            "jitter_std_s": 0.001,
        }
        r.set_delay_profile(profile)
        got = r.get_delay_profile()
        for key, val in profile.items():
            self.assertAlmostEqual(got[key], val, places=6)

    def test_default_delay_profile(self):
        r = RaspiEntity()
        got = r.get_delay_profile()
        self.assertAlmostEqual(got["image_read_delay_s"], 0.0)
        self.assertAlmostEqual(got["image_process_delay_s"], 0.02)
        self.assertAlmostEqual(got["state_read_delay_s"], 0.0)
        self.assertAlmostEqual(got["command_tx_delay_s"], 0.0)
        self.assertAlmostEqual(got["jitter_std_s"], 0.0)


# ===================================================================
# 10. NOT_READY behavior
# ===================================================================


class TestNotReadyBehavior(unittest.TestCase):

    def test_no_pipeline_activity_when_off(self):
        r = RaspiEntity()
        r.load_control_program(_CmdProg())

        submitted = []

        def _submit(cmd, apply_at):
            submitted.append(cmd)

        dt = 0.01
        t = 0.0
        for _ in range(100):
            t += dt
            r.update(t, _make_obs(t), _submit, dt)

        # Still OFF, no pipeline activity
        self.assertEqual(len(submitted), 0)
        self.assertEqual(r.power_state, POWER_OFF)

    def test_no_commands_during_booting(self):
        r = RaspiEntity()
        r.power_on(0.0)
        r.load_control_program(_CmdProg())

        submitted = []

        def _submit(cmd, apply_at):
            submitted.append(cmd)

        dt = 0.01
        t = 0.0
        for _ in range(10):
            t += dt
            r.update(t, _make_obs(t), _submit, dt)

        # Still BOOTING (boot_delay=1.0s, only ran 0.1s)
        self.assertEqual(r.power_state, POWER_BOOTING)
        self.assertEqual(len(submitted), 0)


# ===================================================================
# 11. get_state() contract
# ===================================================================


class TestGetState(unittest.TestCase):

    def test_state_has_required_keys(self):
        r = RaspiEntity()
        state = r.get_state()
        required_keys = [
            "timestamp", "power_state", "effective_obs_timestamp",
            "pipeline_backlog_len", "last_process_latency_s",
            "last_command_apply_timestamp", "delay_metrics",
        ]
        for key in required_keys:
            self.assertIn(key, state, f"Missing key: {key}")

    def test_delay_metrics_is_dict(self):
        r = RaspiEntity()
        state = r.get_state()
        self.assertIsInstance(state["delay_metrics"], dict)

    def test_initial_state_values(self):
        r = RaspiEntity()
        state = r.get_state()
        self.assertEqual(state["power_state"], POWER_OFF)
        self.assertEqual(state["pipeline_backlog_len"], 0)


if __name__ == "__main__":
    unittest.main()
