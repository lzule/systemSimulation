"""Comprehensive unit tests for the Gimbal entity, plant, and controller."""

import math
import unittest

from runtime.types import POWER_BOOTING, POWER_FAULT, POWER_OFF, POWER_READY

from entities.gimbal.entity import (
    GimbalEntity,
    GimbalState,
)
from entities.gimbal.model import GimbalPlant2Axis, Gimbal2AxisState
from entities.gimbal.control import (
    ANGLE_MODE,
    RATE_MODE,
    CascadedController2Axis,
)
from config import AxisLimitConfig, GimbalConfig, LoopConfig, ControlPreset
from runtime.types import CommandResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _boot_to_ready(g: GimbalEntity, start_ts: float = 0.0) -> float:
    """Power on and advance time past the boot delay (1.5 s).

    Returns the timestamp right after the entity becomes READY.
    """
    g.power_on(start_ts)
    dt = 0.01
    t = start_ts
    for _ in range(200):          # 2.0 s should be plenty
        t += dt
        st = g.update(dt, t)
        if st.power_state == POWER_READY:
            return t
    raise RuntimeError("Gimbal never reached READY state")


# ===================================================================
# 1. Power state machine
# ===================================================================

class TestPowerStateMachine(unittest.TestCase):
    """OFF -> power_on -> BOOTING -> (boot_delay) -> READY; power_off -> OFF."""

    def test_initial_state_is_off(self):
        g = GimbalEntity()
        self.assertEqual(g.power_state, POWER_OFF)

    def test_power_on_returns_ok_and_enters_booting(self):
        g = GimbalEntity()
        result = g.power_on(0.0)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "OK")
        self.assertEqual(g.power_state, POWER_BOOTING)
        self.assertAlmostEqual(g.boot_remaining_s, g.boot_delay_s)

    def test_power_on_while_booting_returns_already_on(self):
        g = GimbalEntity()
        g.power_on(0.0)
        result = g.power_on(1.0)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "ALREADY_ON")
        self.assertEqual(g.power_state, POWER_BOOTING)

    def test_power_on_while_ready_returns_already_on(self):
        g = GimbalEntity()
        t = _boot_to_ready(g)
        result = g.power_on(t)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "ALREADY_ON")
        self.assertEqual(g.power_state, POWER_READY)

    def test_booting_transitions_to_ready_after_delay(self):
        g = GimbalEntity()
        g.power_on(0.0)
        dt = 0.01
        t = 0.0
        ready_t = None
        for _ in range(200):
            t += dt
            st = g.update(dt, t)
            if st.power_state == POWER_READY:
                ready_t = t
                break
        self.assertIsNotNone(ready_t, "Never reached READY")
        # Should transition at or shortly after boot_delay_s = 1.5 s
        self.assertGreaterEqual(ready_t, g.boot_delay_s)

    def test_power_off_returns_to_off(self):
        g = GimbalEntity()
        t = _boot_to_ready(g)
        result = g.power_off(t)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "OK")
        self.assertEqual(g.power_state, POWER_OFF)

    def test_power_off_resets_plant(self):
        g = GimbalEntity()
        t = _boot_to_ready(g)
        # Run some updates so the plant moves away from initial state
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(10.0, 10.0, t)
        for i in range(50):
            t += 0.01
            g.update(0.01, t)
        # Now power off
        g.power_off(t)
        # Plant should be reset
        ps = g.plant.get_state()
        self.assertAlmostEqual(ps.yaw_deg_internal, g.gimbal_cfg.initial_angle_deg)
        self.assertAlmostEqual(ps.pitch_deg, 0.0)
        self.assertAlmostEqual(ps.yaw_rate_dps, 0.0)
        self.assertAlmostEqual(ps.pitch_rate_dps, 0.0)

    def test_power_off_resets_controller(self):
        g = GimbalEntity()
        t = _boot_to_ready(g)
        g.set_mode(RATE_MODE, t)
        g.power_off(t)
        self.assertEqual(g.controller.mode, ANGLE_MODE)

    def test_power_off_during_booting(self):
        g = GimbalEntity()
        g.power_on(0.0)
        # Advance partway through boot
        g.update(0.5, 0.5)
        self.assertEqual(g.power_state, POWER_BOOTING)
        result = g.power_off(0.5)
        self.assertEqual(g.power_state, POWER_OFF)
        self.assertTrue(result.accepted)

    def test_power_cycle_resets_everything(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        # Move gimbal
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(30.0, -30.0, t)
        for i in range(100):
            t += 0.01
            g.update(0.01, t)
        # Power cycle
        g.power_off(t)
        t = _boot_to_ready(g, t)
        st = g.get_state(t)
        # After a fresh boot with dt=0 update in get_state, rates should be 0
        self.assertAlmostEqual(st["yaw_rate_dps"], 0.0, places=5)
        self.assertAlmostEqual(st["pitch_rate_dps"], 0.0, places=5)


# ===================================================================
# 2. NOT_READY rejection
# ===================================================================

class TestNotReadyRejection(unittest.TestCase):
    """Commands should be rejected when gimbal is not in READY state."""

    def _make_off_entity(self):
        return GimbalEntity()

    def _make_booting_entity(self):
        g = GimbalEntity()
        g.power_on(0.0)
        return g

    def test_set_mode_rejected_when_off(self):
        g = self._make_off_entity()
        result = g.set_mode(ANGLE_MODE, 0.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "NOT_READY")

    def test_set_mode_rejected_when_booting(self):
        g = self._make_booting_entity()
        result = g.set_mode(ANGLE_MODE, 0.5)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "NOT_READY")

    def test_set_angle_target_rejected_when_off(self):
        g = self._make_off_entity()
        result = g.set_angle_target(45.0, 30.0, 0.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "NOT_READY")

    def test_set_angle_target_rejected_when_booting(self):
        g = self._make_booting_entity()
        result = g.set_angle_target(45.0, 30.0, 0.5)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "NOT_READY")

    def test_set_rate_target_rejected_when_off(self):
        g = self._make_off_entity()
        result = g.set_rate_target(10.0, -10.0, 0.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "NOT_READY")

    def test_set_rate_target_rejected_when_booting(self):
        g = self._make_booting_entity()
        result = g.set_rate_target(10.0, -10.0, 0.5)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "NOT_READY")

    def test_commands_accepted_when_ready(self):
        g = GimbalEntity()
        t = _boot_to_ready(g)
        r1 = g.set_mode(RATE_MODE, t)
        self.assertTrue(r1.accepted)
        r2 = g.set_rate_target(10.0, -10.0, t)
        self.assertTrue(r2.accepted)
        g.set_mode(ANGLE_MODE, t)
        r3 = g.set_angle_target(45.0, 30.0, t)
        self.assertTrue(r3.accepted)


# ===================================================================
# 3. ANGLE_MODE tracking
# ===================================================================

class TestAngleModeTracking(unittest.TestCase):
    """Set an angle target and verify the gimbal converges toward it."""

    def test_yaw_converges_to_angle_target(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        # Default mode is ANGLE_MODE; set target
        target_yaw = 30.0
        target_pitch = 0.0
        result = g.set_angle_target(target_yaw, target_pitch, t)
        self.assertTrue(result.accepted)

        dt = 0.005
        for _ in range(600):  # 3 seconds
            t += dt
            st = g.update(dt, t)

        # Should have moved toward 30 deg yaw
        self.assertGreater(st.yaw_deg_internal, 5.0,
                           "Yaw should have moved toward the 30 deg target")

    def test_pitch_converges_to_angle_target(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        target_pitch = 45.0
        g.set_angle_target(0.0, target_pitch, t)

        dt = 0.005
        for _ in range(800):
            t += dt
            st = g.update(dt, t)

        self.assertGreater(st.pitch_deg, 10.0,
                           "Pitch should have moved toward 45 deg target")

    def test_negative_angle_target(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_angle_target(-20.0, -30.0, t)

        dt = 0.005
        for _ in range(600):
            t += dt
            st = g.update(dt, t)

        self.assertLess(st.yaw_deg_internal, -5.0)
        self.assertLess(st.pitch_deg, -5.0)

    def test_angle_target_clamps_pitch_to_limits(self):
        """Controller internally clamps pitch target to [-135, 90]."""
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        # Request pitch beyond limits
        result = g.set_angle_target(0.0, 200.0, t)
        self.assertTrue(result.accepted)
        # The controller should have clamped the stored target
        self.assertAlmostEqual(g.controller._latest_angle_cmd["pitch_deg"], 90.0)


# ===================================================================
# 4. RATE_MODE response
# ===================================================================

class TestRateModeResponse(unittest.TestCase):
    """Set rate target and verify angular velocity changes."""

    def test_positive_yaw_rate(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(20.0, 0.0, t)

        dt = 0.005
        for _ in range(200):  # 1 second
            t += dt
            st = g.update(dt, t)

        # Yaw should have moved in positive direction
        self.assertGreater(st.yaw_deg_internal, 0.0)

    def test_negative_pitch_rate(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(0.0, -20.0, t)

        dt = 0.005
        for _ in range(200):
            t += dt
            st = g.update(dt, t)

        self.assertLess(st.pitch_deg, 0.0)

    def test_zero_rate_stops_motion(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(30.0, 30.0, t)

        dt = 0.005
        for _ in range(100):
            t += dt
            g.update(dt, t)

        # Now command zero rate
        g.set_rate_target(0.0, 0.0, t)
        for _ in range(2000):
            t += dt
            st = g.update(dt, t)

        # Rate should decay toward zero due to first-order dynamics
        self.assertAlmostEqual(st.yaw_rate_dps, 0.0, places=1)
        self.assertAlmostEqual(st.pitch_rate_dps, 0.0, places=1)

    def test_rate_target_clamped_to_max(self):
        """Rate commands beyond max_rate_dps should be clamped."""
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_mode(RATE_MODE, t)
        # Request rate beyond max (60 dps)
        g.set_rate_target(200.0, -200.0, t)
        # The controller should clamp to max_rate
        self.assertAlmostEqual(
            g.controller._latest_rate_cmd["yaw_rate_dps"], 60.0
        )
        self.assertAlmostEqual(
            g.controller._latest_rate_cmd["pitch_rate_dps"], -60.0
        )


# ===================================================================
# 5. Pitch limits
# ===================================================================

class TestPitchLimits(unittest.TestCase):
    """Pitch must be clamped to [pitch_min_deg, pitch_max_deg] = [-135, 90]."""

    def test_pitch_clamped_at_upper_limit(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(0.0, 60.0, t)  # max upward rate

        dt = 0.005
        for _ in range(1000):  # 5 seconds
            t += dt
            st = g.update(dt, t)

        self.assertLessEqual(st.pitch_deg, 90.0 + 1e-6)
        # Pitch should have hit the limit and stopped
        self.assertAlmostEqual(st.pitch_deg, 90.0, places=1)

    def test_pitch_clamped_at_lower_limit(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(0.0, -60.0, t)  # max downward rate

        dt = 0.005
        for _ in range(3000):  # 15 seconds
            t += dt
            st = g.update(dt, t)

        self.assertGreaterEqual(st.pitch_deg, -135.0 - 1e-6)
        self.assertAlmostEqual(st.pitch_deg, -135.0, places=1)

    def test_pitch_rate_zeroed_at_upper_limit(self):
        """When pitch hits the upper limit, pitch_rate should be zeroed."""
        plant = GimbalPlant2Axis()
        # Drive pitch up until it hits the limit
        dt = 0.01
        for _ in range(500):
            plant.step({"yaw_rate_cmd_dps": 0.0, "pitch_rate_cmd_dps": 60.0}, dt)
        self.assertAlmostEqual(plant.pitch_deg, 90.0, places=1)
        self.assertAlmostEqual(plant.pitch_rate_dps, 0.0, places=3)

    def test_pitch_rate_zeroed_at_lower_limit(self):
        """When pitch hits the lower limit, pitch_rate should be zeroed."""
        plant = GimbalPlant2Axis()
        dt = 0.01
        for _ in range(2000):
            plant.step({"yaw_rate_cmd_dps": 0.0, "pitch_rate_cmd_dps": -60.0}, dt)
        self.assertAlmostEqual(plant.pitch_deg, -135.0, places=1)
        self.assertAlmostEqual(plant.pitch_rate_dps, 0.0, places=3)

    def test_pitch_does_not_overshoot_limits(self):
        """At every intermediate step, pitch stays within bounds."""
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(0.0, 60.0, t)

        dt = 0.005
        for _ in range(2000):
            t += dt
            st = g.update(dt, t)
            self.assertLessEqual(
                st.pitch_deg, 90.0 + 0.01,
                f"Pitch {st.pitch_deg} exceeded upper limit"
            )
            self.assertGreaterEqual(
                st.pitch_deg, -135.0 - 0.01,
                f"Pitch {st.pitch_deg} went below lower limit"
            )


# ===================================================================
# 6. Yaw wrap (wrap_0_360)
# ===================================================================

class TestYawWrap(unittest.TestCase):
    """yaw_deg_display must always be in [0, 360)."""

    def test_wrap_0_360_static_method(self):
        self.assertAlmostEqual(GimbalEntity.wrap_0_360(0.0), 0.0)
        self.assertAlmostEqual(GimbalEntity.wrap_0_360(45.0), 45.0)
        self.assertAlmostEqual(GimbalEntity.wrap_0_360(359.9), 359.9)
        self.assertAlmostEqual(GimbalEntity.wrap_0_360(360.0), 0.0)
        self.assertAlmostEqual(GimbalEntity.wrap_0_360(-90.0), 270.0)
        self.assertAlmostEqual(GimbalEntity.wrap_0_360(-180.0), 180.0)
        self.assertAlmostEqual(GimbalEntity.wrap_0_360(720.0), 0.0)
        self.assertAlmostEqual(GimbalEntity.wrap_0_360(-720.0), 0.0)

    def test_yaw_display_always_in_range(self):
        """Run gimbal for a while in rate mode and check yaw_deg_display."""
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(60.0, 0.0, t)  # full speed yaw

        dt = 0.005
        for _ in range(5000):  # 25 seconds -> many full rotations
            t += dt
            st = g.update(dt, t)
            self.assertGreaterEqual(st.yaw_deg_display, 0.0)
            self.assertLess(st.yaw_deg_display, 360.0)

    def test_yaw_display_negative_internal(self):
        """Negative internal yaw should wrap correctly in display."""
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(-60.0, 0.0, t)

        dt = 0.005
        for _ in range(100):  # get negative internal yaw
            t += dt
            st = g.update(dt, t)

        if st.yaw_deg_internal < 0:
            self.assertAlmostEqual(
                st.yaw_deg_display,
                st.yaw_deg_internal % 360.0,
                places=5,
            )


# ===================================================================
# 7. Plant first-order response
# ===================================================================

class TestPlantFirstOrderResponse(unittest.TestCase):
    """Rate should approach commanded rate following first-order dynamics."""

    def test_alpha_formula(self):
        """Verify alpha = dt / (tau + dt)."""
        tau = 0.03
        dt = 0.01
        expected_alpha = dt / (tau + dt)
        plant = GimbalPlant2Axis()
        # The plant uses response_tau_s from GimbalConfig (default 0.03)
        self.assertAlmostEqual(plant.response_tau_s, tau)

        # Apply a step command
        plant.step({"yaw_rate_cmd_dps": 60.0, "pitch_rate_cmd_dps": 0.0}, dt)
        # After one step: rate = (1 - alpha) * 0 + alpha * 60
        expected_rate = expected_alpha * 60.0
        self.assertAlmostEqual(plant.yaw_rate_dps, expected_rate, places=5)

    def test_rate_converges_to_command(self):
        """After many steps, rate should approach the commanded rate."""
        plant = GimbalPlant2Axis()
        dt = 0.005
        for _ in range(1000):  # 5 seconds
            plant.step({"yaw_rate_cmd_dps": 30.0, "pitch_rate_cmd_dps": 0.0}, dt)
        self.assertAlmostEqual(plant.yaw_rate_dps, 30.0, places=2)

    def test_yaw_accumulation(self):
        """Yaw should accumulate as rate * dt over time."""
        plant = GimbalPlant2Axis()
        dt = 0.01
        # Use tau=0 to get instant rate response
        plant.response_tau_s = 0.0
        plant.step({"yaw_rate_cmd_dps": 10.0, "pitch_rate_cmd_dps": 0.0}, dt)
        # With tau=0, rate should be exactly 10 dps
        self.assertAlmostEqual(plant.yaw_rate_dps, 10.0)
        self.assertAlmostEqual(plant.yaw_deg_internal,
                               plant.legacy_gimbal_cfg.initial_angle_deg + 10.0 * dt,
                               places=5)

    def test_plant_reset(self):
        """Reset should return plant to initial state."""
        plant = GimbalPlant2Axis()
        dt = 0.01
        for _ in range(100):
            plant.step({"yaw_rate_cmd_dps": 30.0, "pitch_rate_cmd_dps": 20.0}, dt)
        plant.reset()
        state = plant.get_state()
        self.assertAlmostEqual(state.yaw_deg_internal,
                               plant.legacy_gimbal_cfg.initial_angle_deg)
        self.assertAlmostEqual(state.pitch_deg, 0.0)
        self.assertAlmostEqual(state.yaw_rate_dps, 0.0)
        self.assertAlmostEqual(state.pitch_rate_dps, 0.0)

    def test_zero_tau_gives_instant_response(self):
        plant = GimbalPlant2Axis()
        plant.response_tau_s = 0.0
        plant.step({"yaw_rate_cmd_dps": 50.0, "pitch_rate_cmd_dps": -40.0}, 0.01)
        self.assertAlmostEqual(plant.yaw_rate_dps, 50.0)
        self.assertAlmostEqual(plant.pitch_rate_dps, -40.0)

    def test_rate_cmd_clamped_to_max(self):
        """Plant should clamp rate commands to max_rate_dps."""
        plant = GimbalPlant2Axis()
        max_rate = plant.axis_cfg.max_rate_dps  # 60.0
        plant.response_tau_s = 0.0  # instant
        plant.step({"yaw_rate_cmd_dps": 200.0, "pitch_rate_cmd_dps": -200.0}, 0.01)
        self.assertAlmostEqual(plant.yaw_rate_dps, max_rate)
        self.assertAlmostEqual(plant.pitch_rate_dps, -max_rate)


# ===================================================================
# 8. Controller mode switching
# ===================================================================

class TestControllerModeSwitching(unittest.TestCase):
    """Switch between ANGLE_MODE and RATE_MODE; verify integrator reset."""

    def test_initial_mode_is_angle(self):
        ctrl = CascadedController2Axis()
        self.assertEqual(ctrl.mode, ANGLE_MODE)

    def test_switch_to_rate_mode(self):
        ctrl = CascadedController2Axis()
        ctrl.set_mode(RATE_MODE)
        self.assertEqual(ctrl.mode, RATE_MODE)

    def test_switch_to_angle_mode(self):
        ctrl = CascadedController2Axis()
        ctrl.set_mode(RATE_MODE)
        ctrl.set_mode(ANGLE_MODE)
        self.assertEqual(ctrl.mode, ANGLE_MODE)

    def test_invalid_mode_raises(self):
        ctrl = CascadedController2Axis()
        with self.assertRaises(ValueError):
            ctrl.set_mode("INVALID_MODE")

    def test_mode_switch_resets_integrator(self):
        ctrl = CascadedController2Axis()
        ctrl.set_mode(RATE_MODE)
        ctrl.set_rate_target(10.0, 10.0, 0.0)
        # Run several steps to build up integral
        for _ in range(50):
            ctrl.step(yaw_deg=0.0, pitch_deg=0.0,
                      yaw_rate_dps=0.0, pitch_rate_dps=0.0, dt=0.005)
        # There should be some integral accumulated
        self.assertNotAlmostEqual(ctrl._yaw_rate_i, 0.0)
        # Switch back to ANGLE_MODE should reset integral
        ctrl.set_mode(ANGLE_MODE)
        self.assertAlmostEqual(ctrl._yaw_rate_i, 0.0)
        self.assertAlmostEqual(ctrl._pitch_rate_i, 0.0)

    def test_same_mode_switch_does_not_reset_integrator(self):
        ctrl = CascadedController2Axis()
        ctrl.set_mode(RATE_MODE)
        ctrl.set_rate_target(10.0, 10.0, 0.0)
        for _ in range(50):
            ctrl.step(yaw_deg=0.0, pitch_deg=0.0,
                      yaw_rate_dps=0.0, pitch_rate_dps=0.0, dt=0.005)
        integral_before = ctrl._yaw_rate_i
        # Setting same mode should not reset
        ctrl.set_mode(RATE_MODE)
        self.assertAlmostEqual(ctrl._yaw_rate_i, integral_before)

    def test_entity_mode_switch(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        # Default is ANGLE_MODE
        st = g.get_state(t)
        self.assertEqual(st["mode"], ANGLE_MODE)

        r = g.set_mode(RATE_MODE, t)
        self.assertTrue(r.accepted)
        st = g.get_state(t)
        self.assertEqual(st["mode"], RATE_MODE)

    def test_entity_switch_angle_to_rate_and_back(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)

        # Start in ANGLE_MODE, set a target
        g.set_angle_target(30.0, 0.0, t)
        dt = 0.005
        for _ in range(100):
            t += dt
            g.update(dt, t)

        # Switch to RATE_MODE
        g.set_mode(RATE_MODE, t)
        g.set_rate_target(-20.0, 0.0, t)
        for _ in range(100):
            t += dt
            st = g.update(dt, t)

        # Yaw should be moving in negative direction now
        self.assertLess(st.yaw_rate_dps, 0.0)

        # Switch back to ANGLE_MODE
        g.set_mode(ANGLE_MODE, t)
        g.set_angle_target(0.0, 0.0, t)
        for _ in range(200):
            t += dt
            st = g.update(dt, t)

        self.assertEqual(st.mode, ANGLE_MODE)


# ===================================================================
# 9. get_state() returns expected dict keys and types
# ===================================================================

class TestGetState(unittest.TestCase):
    """get_state() should return a dict with all expected keys and types."""

    EXPECTED_KEYS = {
        "timestamp",
        "power_state",
        "mode",
        "yaw_deg_internal",
        "yaw_deg_display",
        "pitch_deg",
        "yaw_rate_dps",
        "pitch_rate_dps",
        "yaw_rate_ref_dps",
        "pitch_rate_ref_dps",
        "angle_tick",
        "rate_tick",
        "last_command_apply_timestamp",
    }

    def test_get_state_keys_when_off(self):
        g = GimbalEntity()
        state = g.get_state(0.0)
        self.assertEqual(set(state.keys()), self.EXPECTED_KEYS)

    def test_get_state_keys_when_ready(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        state = g.get_state(t)
        self.assertEqual(set(state.keys()), self.EXPECTED_KEYS)

    def test_get_state_types(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        g.set_angle_target(10.0, 5.0, t)
        state = g.get_state(t)

        self.assertIsInstance(state["timestamp"], float)
        self.assertIsInstance(state["power_state"], str)
        self.assertIsInstance(state["mode"], str)
        self.assertIsInstance(state["yaw_deg_internal"], float)
        self.assertIsInstance(state["yaw_deg_display"], float)
        self.assertIsInstance(state["pitch_deg"], float)
        self.assertIsInstance(state["yaw_rate_dps"], float)
        self.assertIsInstance(state["pitch_rate_dps"], float)
        self.assertIsInstance(state["yaw_rate_ref_dps"], float)
        self.assertIsInstance(state["pitch_rate_ref_dps"], float)
        self.assertIsInstance(state["angle_tick"], bool)
        self.assertIsInstance(state["rate_tick"], bool)
        # last_command_apply_timestamp can be None or float
        self.assertTrue(
            state["last_command_apply_timestamp"] is None
            or isinstance(state["last_command_apply_timestamp"], float)
        )

    def test_get_state_off_values(self):
        g = GimbalEntity()
        state = g.get_state(5.0)
        self.assertEqual(state["power_state"], POWER_OFF)
        self.assertEqual(state["mode"], ANGLE_MODE)
        self.assertAlmostEqual(state["timestamp"], 5.0)

    def test_get_state_ready_values(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        state = g.get_state(t)
        self.assertEqual(state["power_state"], POWER_READY)
        self.assertAlmostEqual(state["timestamp"], t)

    def test_last_command_apply_timestamp_updated(self):
        g = GimbalEntity()
        t = _boot_to_ready(g, 0.0)
        # last_command_apply_timestamp is set during boot, so it won't be None
        # Verify it updates when a new command is issued
        g.set_angle_target(10.0, 5.0, t)
        state = g.get_state(t)
        self.assertAlmostEqual(state["last_command_apply_timestamp"], t)


# ===================================================================
# Additional: Controller internals
# ===================================================================

class TestControllerInternals(unittest.TestCase):
    """Test controller helper methods and internal behavior."""

    def test_wrap_pm180(self):
        from runtime.types import wrap_pm180
        self.assertAlmostEqual(wrap_pm180(0.0), 0.0)
        self.assertAlmostEqual(wrap_pm180(180.0), -180.0)
        self.assertAlmostEqual(wrap_pm180(-180.0), -180.0)
        self.assertAlmostEqual(wrap_pm180(90.0), 90.0)
        self.assertAlmostEqual(wrap_pm180(270.0), -90.0)
        self.assertAlmostEqual(wrap_pm180(-90.0), -90.0)
        self.assertAlmostEqual(wrap_pm180(360.0), 0.0)
        self.assertAlmostEqual(wrap_pm180(450.0), 90.0)
        self.assertAlmostEqual(wrap_pm180(-270.0), 90.0)

    def test_angle_loop_rate(self):
        """Outer loop should tick at angle_loop_hz (50 Hz = every 0.02 s)."""
        ctrl = CascadedController2Axis()
        ctrl.set_angle_target(10.0, 0.0, 0.0)
        result = ctrl.step(yaw_deg=0.0, pitch_deg=0.0,
                           yaw_rate_dps=0.0, pitch_rate_dps=0.0, dt=0.025)
        self.assertTrue(result["angle_tick"])

    def test_rate_loop_rate(self):
        """Inner loop should tick at rate_loop_hz (200 Hz = every 0.005 s)."""
        ctrl = CascadedController2Axis()
        result = ctrl.step(yaw_deg=0.0, pitch_deg=0.0,
                           yaw_rate_dps=0.0, pitch_rate_dps=0.0, dt=0.006)
        self.assertTrue(result["rate_tick"])

    def test_integral_clamped(self):
        """Integral should be clamped to rate_integral_limit."""
        ctrl = CascadedController2Axis()
        i_lim = ctrl.preset.rate_integral_limit  # 30.0

        ctrl.set_mode(RATE_MODE)
        ctrl.set_rate_target(1000.0, 1000.0, 0.0)  # large target
        for _ in range(5000):
            ctrl.step(yaw_deg=0.0, pitch_deg=0.0,
                      yaw_rate_dps=0.0, pitch_rate_dps=0.0, dt=0.005)

        self.assertLessEqual(abs(ctrl._yaw_rate_i), i_lim + 0.01)
        self.assertLessEqual(abs(ctrl._pitch_rate_i), i_lim + 0.01)

    def test_output_clamped_to_actuator_limit(self):
        """Controller output should be clamped to actuator_cmd_limit_dps."""
        ctrl = CascadedController2Axis()
        cmd_lim = ctrl.preset.actuator_cmd_limit_dps  # 60.0

        ctrl.set_mode(RATE_MODE)
        ctrl.set_rate_target(1000.0, 1000.0, 0.0)
        result = ctrl.step(yaw_deg=0.0, pitch_deg=0.0,
                           yaw_rate_dps=0.0, pitch_rate_dps=0.0, dt=0.005)

        self.assertLessEqual(abs(result["yaw_rate_cmd_dps"]), cmd_lim)
        self.assertLessEqual(abs(result["pitch_rate_cmd_dps"]), cmd_lim)


# ===================================================================
# Additional: GimbalState dataclass
# ===================================================================

class TestGimbalStateDataclass(unittest.TestCase):
    """Verify GimbalState is returned by update()."""

    def test_update_returns_gimbal_state(self):
        g = GimbalEntity()
        g.power_on(0.0)
        st = g.update(0.01, 0.01)
        self.assertIsInstance(st, GimbalState)

    def test_gimbal_state_has_all_fields(self):
        g = GimbalEntity()
        st = g.update(0.0, 0.0)
        fields = [
            "timestamp", "power_state", "mode",
            "yaw_deg_internal", "yaw_deg_display", "pitch_deg",
            "yaw_rate_dps", "pitch_rate_dps",
            "yaw_rate_ref_dps", "pitch_rate_ref_dps",
            "angle_tick", "rate_tick",
            "last_command_apply_timestamp",
        ]
        for f in fields:
            self.assertTrue(hasattr(st, f), f"Missing field: {f}")


# ===================================================================
# Additional: Plant Gimbal2AxisState
# ===================================================================

class TestPlantState(unittest.TestCase):
    """Verify Gimbal2AxisState is returned by plant.get_state()."""

    def test_get_state_returns_dataclass(self):
        plant = GimbalPlant2Axis()
        state = plant.get_state()
        self.assertIsInstance(state, Gimbal2AxisState)

    def test_step_returns_dataclass(self):
        plant = GimbalPlant2Axis()
        state = plant.step({"yaw_rate_cmd_dps": 0.0, "pitch_rate_cmd_dps": 0.0}, 0.01)
        self.assertIsInstance(state, Gimbal2AxisState)

    def test_state_fields(self):
        plant = GimbalPlant2Axis()
        state = plant.get_state()
        self.assertTrue(hasattr(state, "yaw_deg_internal"))
        self.assertTrue(hasattr(state, "pitch_deg"))
        self.assertTrue(hasattr(state, "yaw_rate_dps"))
        self.assertTrue(hasattr(state, "pitch_rate_dps"))


if __name__ == "__main__":
    unittest.main()
