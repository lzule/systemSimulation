"""Comprehensive unit tests for the Target entity (model, entity, config)."""

import math
import unittest

from config import TargetConfig
from entities.target.model import TargetKinematics2D
from entities.target.entity import TargetEntity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_steps(model: TargetKinematics2D, dt: float, n: int):
    """Advance *model* by *n* steps of *dt* and return list of (x, y)."""
    positions = []
    for _ in range(n):
        positions.append(model.step(dt))
    return positions


# ===================================================================
# 1. Initial state for every motion_type
# ===================================================================

class TestInitialState(unittest.TestCase):
    """Verify x, y, vx, vy, t immediately after construction."""

    def test_sinusoidal_initial_state(self):
        cfg = TargetConfig(motion_type="sinusoidal", initial_x_m=50.0,
                           initial_y_m=0.0)
        m = TargetKinematics2D(cfg)
        self.assertEqual(m.x, 50.0)
        self.assertEqual(m.y, 0.0)
        self.assertEqual(m.vx, 0.0)
        self.assertEqual(m.vy, 0.0)
        self.assertEqual(m.t, 0.0)

    def test_constant_velocity_initial_state(self):
        cfg = TargetConfig(motion_type="constant_velocity",
                           initial_x_m=10.0, initial_y_m=-5.0,
                           velocity_x_mps=2.0, velocity_y_mps=3.0)
        m = TargetKinematics2D(cfg)
        self.assertEqual(m.x, 10.0)
        self.assertEqual(m.y, -5.0)
        self.assertEqual(m.vx, 2.0)
        self.assertEqual(m.vy, 3.0)

    def test_constant_accel_initial_state(self):
        cfg = TargetConfig(motion_type="constant_accel",
                           velocity_x_mps=1.0, velocity_y_mps=0.5,
                           accel_x_mps2=0.1, accel_y_mps2=0.2)
        m = TargetKinematics2D(cfg)
        self.assertEqual(m.vx, 1.0)
        self.assertEqual(m.vy, 0.5)

    def test_random_walk_initial_state(self):
        cfg = TargetConfig(motion_type="random_walk", initial_x_m=20.0,
                           initial_y_m=30.0, random_seed=123)
        m = TargetKinematics2D(cfg)
        self.assertEqual(m.x, 20.0)
        self.assertEqual(m.y, 30.0)
        self.assertEqual(m.vx, 0.0)
        self.assertEqual(m.vy, 0.0)

    def test_waypoint_initial_state(self):
        cfg = TargetConfig(motion_type="waypoint",
                           waypoints=[(10.0, 20.0, 5.0)])
        m = TargetKinematics2D(cfg)
        self.assertEqual(m.x, cfg.initial_x_m)
        self.assertEqual(m.y, cfg.initial_y_m)
        self.assertEqual(m.vx, 0.0)
        self.assertEqual(m.vy, 0.0)

    def test_unknown_motion_type_raises(self):
        with self.assertRaises(ValueError):
            TargetKinematics2D(TargetConfig(motion_type="nonexistent"))


# ===================================================================
# 2. constant_velocity mode
# ===================================================================

class TestConstantVelocity(unittest.TestCase):

    def setUp(self):
        self.cfg = TargetConfig(
            motion_type="constant_velocity",
            initial_x_m=0.0, initial_y_m=0.0,
            velocity_x_mps=3.0, velocity_y_mps=4.0,
        )
        self.model = TargetKinematics2D(self.cfg)

    def test_linear_position_after_one_step(self):
        x, y = self.model.step(2.0)
        self.assertAlmostEqual(x, 6.0)
        self.assertAlmostEqual(y, 8.0)

    def test_linear_position_after_many_steps(self):
        dt = 0.1
        n = 50  # total time = 5 s
        _run_steps(self.model, dt, n)
        # x = vx * total_t = 3 * 5 = 15
        self.assertAlmostEqual(self.model.x, 15.0, places=5)
        self.assertAlmostEqual(self.model.y, 20.0, places=5)

    def test_velocity_unchanged(self):
        _run_steps(self.model, 0.05, 100)
        self.assertEqual(self.model.vx, 3.0)
        self.assertEqual(self.model.vy, 4.0)

    def test_time_accumulates(self):
        _run_steps(self.model, 0.1, 10)
        self.assertAlmostEqual(self.model.t, 1.0)

    def test_bearing_deg_positive_quadrant(self):
        """At (3, 4) the bearing is atan2(4,3) ~ 53.13 deg."""
        self.model.step(1.0)  # arrives at (3, 4)
        expected = math.degrees(math.atan2(4.0, 3.0))
        self.assertAlmostEqual(self.model.bearing_deg, expected, places=4)

    def test_distance_m(self):
        self.model.step(1.0)
        self.assertAlmostEqual(self.model.distance_m, 5.0, places=4)


# ===================================================================
# 3. constant_accel mode
# ===================================================================

class TestConstantAccel(unittest.TestCase):

    def setUp(self):
        self.cfg = TargetConfig(
            motion_type="constant_accel",
            initial_x_m=0.0, initial_y_m=0.0,
            velocity_x_mps=0.0, velocity_y_mps=0.0,
            accel_x_mps2=2.0, accel_y_mps2=0.0,
        )
        self.model = TargetKinematics2D(self.cfg)

    def test_velocity_updates_each_step(self):
        self.model.step(1.0)
        self.assertAlmostEqual(self.model.vx, 2.0)
        self.assertAlmostEqual(self.model.vy, 0.0)

    def test_position_after_two_steps(self):
        # step 1: vx=2, x=2; step 2: vx=4, x=2+4=6
        self.model.step(1.0)
        self.model.step(1.0)
        self.assertAlmostEqual(self.model.x, 6.0, places=5)

    def test_kinematic_formula_match(self):
        """After t seconds: x = v0*t + 0.5*a*t^2 (Euler approximation)."""
        dt = 0.001
        n = 1000  # total t = 1 s, a_x = 2
        _run_steps(self.model, dt, n)
        # Euler: sum of (v0 + a*k*dt)*dt for k=0..999
        # Exact: 0.5*2*1^2 = 1.0  but Euler adds tiny error
        self.assertAlmostEqual(self.model.x, 1.0, places=2)

    def test_both_axes_accelerate(self):
        cfg = TargetConfig(
            motion_type="constant_accel",
            initial_x_m=0.0, initial_y_m=0.0,
            velocity_x_mps=1.0, velocity_y_mps=1.0,
            accel_x_mps2=1.0, accel_y_mps2=1.0,
        )
        m = TargetKinematics2D(cfg)
        m.step(1.0)
        self.assertAlmostEqual(m.vx, 2.0)
        self.assertAlmostEqual(m.vy, 2.0)
        # x = 1*1 + 1*1 = ~2 (Euler)
        self.assertAlmostEqual(m.x, 2.0, places=5)
        self.assertAlmostEqual(m.y, 2.0, places=5)


# ===================================================================
# 4. sinusoidal mode
# ===================================================================

class TestSinusoidal(unittest.TestCase):

    def setUp(self):
        self.cfg = TargetConfig(
            motion_type="sinusoidal",
            initial_x_m=100.0, initial_y_m=0.0,
            sin_amplitude_m=15.0, sin_frequency_hz=0.2,
        )
        self.model = TargetKinematics2D(self.cfg)

    def test_x_constant(self):
        for _ in range(20):
            x, _ = self.model.step(0.1)
            self.assertAlmostEqual(x, 100.0)

    def test_y_at_quarter_period(self):
        """At t = T/4 = 1.25 s, y should be A = 15 m."""
        dt = 0.001
        n = 1250  # 1.25 s
        for _ in range(n):
            self.model.step(dt)
        self.assertAlmostEqual(self.model.y, 15.0, places=1)

    def test_y_at_half_period(self):
        """At t = T/2 = 2.5 s, y should be 0."""
        dt = 0.001
        n = 2500
        for _ in range(n):
            self.model.step(dt)
        self.assertAlmostEqual(self.model.y, 0.0, places=1)

    def test_y_at_three_quarter_period(self):
        """At t = 3T/4 = 3.75 s, y should be -A = -15 m."""
        dt = 0.001
        n = 3750
        for _ in range(n):
            self.model.step(dt)
        self.assertAlmostEqual(self.model.y, -15.0, places=1)

    def test_y_at_full_period(self):
        """After one full period (5 s), y returns to 0."""
        dt = 0.001
        n = 5000
        for _ in range(n):
            self.model.step(dt)
        self.assertAlmostEqual(self.model.y, 0.0, places=1)

    def test_vx_always_zero(self):
        for _ in range(10):
            self.model.step(0.1)
            self.assertEqual(self.model.vx, 0.0)

    def test_vy_at_t_zero(self):
        """vy = A * omega * cos(0) = A * omega at t=0+, after one small step."""
        omega = 2 * math.pi * 0.2
        expected = 15.0 * omega  # ~18.85
        self.model.step(0.0001)
        self.assertAlmostEqual(self.model.vy, expected, places=2)

    def test_vy_zero_at_quarter_period(self):
        """vy should be ~0 at t=T/4 where cos(omega*t)=0."""
        dt = 0.001
        n = 1250  # 1.25 s
        for _ in range(n):
            self.model.step(dt)
        self.assertAlmostEqual(self.model.vy, 0.0, places=1)

    def test_exact_formula_one_step(self):
        """After one step of dt=0.5 s, compare with closed-form."""
        dt = 0.5
        self.model.step(dt)
        omega = 2 * math.pi * 0.2
        expected_y = 15.0 * math.sin(omega * dt)
        expected_vy = 15.0 * omega * math.cos(omega * dt)
        self.assertAlmostEqual(self.model.y, expected_y, places=10)
        self.assertAlmostEqual(self.model.vy, expected_vy, places=10)

    def test_step_returns_position(self):
        pos = self.model.step(0.1)
        self.assertIsInstance(pos, tuple)
        self.assertEqual(len(pos), 2)
        self.assertAlmostEqual(pos[0], 100.0)


# ===================================================================
# 5. random_walk mode
# ===================================================================

class TestRandomWalk(unittest.TestCase):

    def test_reproducible_with_same_seed(self):
        """Same seed produces same trajectory within a single model instance."""
        cfg = TargetConfig(motion_type="random_walk", random_seed=42,
                           initial_x_m=0.0, initial_y_m=0.0)
        m = TargetKinematics2D(cfg)
        dt = 0.01
        positions = [m.step(dt) for _ in range(100)]
        # Verify position actually moved (non-trivial trajectory)
        self.assertNotAlmostEqual(positions[-1][0], 0.0, places=3)

    def test_different_seed_different_trajectory(self):
        cfg_a = TargetConfig(motion_type="random_walk", random_seed=1)
        cfg_b = TargetConfig(motion_type="random_walk", random_seed=2)
        m1 = TargetKinematics2D(cfg_a)
        m2 = TargetKinematics2D(cfg_b)
        dt = 0.01
        for _ in range(50):
            m1.step(dt)
            m2.step(dt)
        # Extremely unlikely to end up at same position
        self.assertNotAlmostEqual(m1.x, m2.x, places=5)

    def test_velocity_stays_bounded(self):
        """With damping=0.98 and max_accel=1, velocity should not explode."""
        cfg = TargetConfig(motion_type="random_walk", random_seed=0,
                           random_max_accel_mps2=1.0, random_damping=0.98)
        m = TargetKinematics2D(cfg)
        dt = 0.01
        for _ in range(5000):
            m.step(dt)
        max_v = max(abs(m.vx), abs(m.vy))
        # Theoretical steady-state max is roughly a_max*dt / (1-damp) = 0.01/0.02 = 0.5
        # Give generous margin
        self.assertLess(max_v, 50.0)

    def test_position_moves(self):
        cfg = TargetConfig(motion_type="random_walk", random_seed=42)
        m = TargetKinematics2D(cfg)
        x0, y0 = m.x, m.y
        for _ in range(100):
            m.step(0.01)
        # Should have moved somewhere
        moved = (m.x != x0) or (m.y != y0)
        self.assertTrue(moved)


# ===================================================================
# 6. waypoint mode
# ===================================================================

class TestWaypoint(unittest.TestCase):

    def test_navigates_to_single_waypoint(self):
        cfg = TargetConfig(
            motion_type="waypoint",
            initial_x_m=0.0, initial_y_m=0.0,
            waypoints=[(10.0, 0.0, 5.0)],  # 10 m away at 5 m/s -> 2 s
            waypoint_arrival_radius_m=1.0,
        )
        m = TargetKinematics2D(cfg)
        _run_steps(m, 0.01, 300)  # 3 seconds
        # Should have arrived near (10, 0)
        self.assertAlmostEqual(m.x, 10.0, places=1)
        self.assertAlmostEqual(m.y, 0.0, places=1)

    def test_switches_to_next_waypoint(self):
        cfg = TargetConfig(
            motion_type="waypoint",
            initial_x_m=0.0, initial_y_m=0.0,
            waypoints=[(5.0, 0.0, 10.0), (5.0, 5.0, 10.0)],
            waypoint_arrival_radius_m=1.0,
        )
        m = TargetKinematics2D(cfg)
        # 1 s to reach first wp at 10 m/s (distance 5), then move to second
        _run_steps(m, 0.01, 300)  # 3 seconds total
        self.assertAlmostEqual(m.x, 5.0, places=1)
        self.assertAlmostEqual(m.y, 5.0, places=1)

    def test_stops_at_last_waypoint(self):
        cfg = TargetConfig(
            motion_type="waypoint",
            initial_x_m=0.0, initial_y_m=0.0,
            waypoints=[(2.0, 0.0, 5.0)],
            waypoint_arrival_radius_m=1.0,
        )
        m = TargetKinematics2D(cfg)
        # Run well past arrival time
        _run_steps(m, 0.01, 500)
        # Should be stopped at the waypoint
        self.assertAlmostEqual(m.x, 2.0, places=5)
        self.assertAlmostEqual(m.y, 0.0, places=5)
        self.assertEqual(m.vx, 0.0)
        self.assertEqual(m.vy, 0.0)

    def test_velocity_points_toward_waypoint(self):
        cfg = TargetConfig(
            motion_type="waypoint",
            initial_x_m=0.0, initial_y_m=0.0,
            waypoints=[(0.0, 10.0, 3.0)],
            waypoint_arrival_radius_m=0.1,
        )
        m = TargetKinematics2D(cfg)
        m.step(0.01)
        # Moving in +y direction at speed 3
        self.assertAlmostEqual(m.vx, 0.0, places=5)
        self.assertAlmostEqual(m.vy, 3.0, places=5)

    def test_diagonal_waypoint_speed(self):
        """Diagonal motion should maintain the specified speed."""
        cfg = TargetConfig(
            motion_type="waypoint",
            initial_x_m=0.0, initial_y_m=0.0,
            waypoints=[(10.0, 10.0, 10.0)],
            waypoint_arrival_radius_m=0.5,
        )
        m = TargetKinematics2D(cfg)
        m.step(0.001)
        speed = math.hypot(m.vx, m.vy)
        self.assertAlmostEqual(speed, 10.0, places=5)

    def test_three_sequential_waypoints(self):
        cfg = TargetConfig(
            motion_type="waypoint",
            initial_x_m=0.0, initial_y_m=0.0,
            waypoints=[
                (3.0, 0.0, 10.0),
                (3.0, 3.0, 10.0),
                (0.0, 3.0, 10.0),
            ],
            waypoint_arrival_radius_m=0.5,
        )
        m = TargetKinematics2D(cfg)
        _run_steps(m, 0.01, 500)  # 5 s
        # Should end at the last waypoint
        self.assertAlmostEqual(m.x, 0.0, places=0)
        self.assertAlmostEqual(m.y, 3.0, places=0)


# ===================================================================
# 7. bearing_deg and distance_m properties
# ===================================================================

class TestBearingAndDistance(unittest.TestCase):

    def _make_model_at(self, x: float, y: float):
        """Create a constant_velocity model and step it to (x, y)."""
        # Choose vx/vy so that stepping dt=1 lands at (x,y) from origin.
        cfg = TargetConfig(
            motion_type="constant_velocity",
            initial_x_m=0.0, initial_y_m=0.0,
            velocity_x_mps=x, velocity_y_mps=y,
        )
        m = TargetKinematics2D(cfg)
        m.step(1.0)
        return m

    def test_bearing_45_deg(self):
        m = self._make_model_at(1.0, 1.0)
        self.assertAlmostEqual(m.bearing_deg, 45.0, places=4)

    def test_bearing_90_deg(self):
        m = self._make_model_at(0.0, 1.0)
        self.assertAlmostEqual(m.bearing_deg, 90.0, places=4)

    def test_bearing_negative_90_deg(self):
        m = self._make_model_at(0.0, -1.0)
        self.assertAlmostEqual(m.bearing_deg, -90.0, places=4)

    def test_bearing_180_deg(self):
        m = self._make_model_at(-1.0, 0.0)
        self.assertAlmostEqual(m.bearing_deg, 180.0, places=4)

    def test_bearing_second_quadrant(self):
        m = self._make_model_at(-1.0, 1.0)
        expected = math.degrees(math.atan2(1.0, -1.0))  # 135 deg
        self.assertAlmostEqual(m.bearing_deg, expected, places=4)

    def test_bearing_third_quadrant(self):
        m = self._make_model_at(-1.0, -1.0)
        expected = math.degrees(math.atan2(-1.0, -1.0))  # -135 deg
        self.assertAlmostEqual(m.bearing_deg, expected, places=4)

    def test_distance_3_4_5_triangle(self):
        m = self._make_model_at(3.0, 4.0)
        self.assertAlmostEqual(m.distance_m, 5.0, places=4)

    def test_distance_origin(self):
        """Distance from origin when at origin is 0."""
        m = self._make_model_at(0.0, 0.0)
        self.assertAlmostEqual(m.distance_m, 0.0, places=4)

    def test_distance_negative_coords(self):
        m = self._make_model_at(-3.0, -4.0)
        self.assertAlmostEqual(m.distance_m, 5.0, places=4)


# ===================================================================
# 8. TargetEntity wrapper
# ===================================================================

class TestTargetEntity(unittest.TestCase):

    def test_default_construction_creates_state(self):
        e = TargetEntity()
        self.assertEqual(e.state.timestamp, 0.0)
        self.assertEqual(e.state.x_m, 100.0)
        self.assertEqual(e.state.y_m, 0.0)

    def test_custom_config(self):
        cfg = TargetConfig(motion_type="constant_velocity",
                           initial_x_m=10.0, initial_y_m=20.0,
                           velocity_x_mps=1.0, velocity_y_mps=0.0)
        e = TargetEntity(cfg)
        self.assertEqual(e.state.x_m, 10.0)
        self.assertEqual(e.state.y_m, 20.0)

    def test_update_returns_target_state(self):
        from entities.target.entity import TargetState
        e = TargetEntity(TargetConfig(motion_type="constant_velocity",
                                      velocity_x_mps=1.0, velocity_y_mps=0.0))
        state = e.update(1.0, 1.0)
        self.assertIsInstance(state, TargetState)
        self.assertEqual(state.timestamp, 1.0)
        self.assertAlmostEqual(state.x_m, 101.0, places=5)

    def test_update_accumulates_timestamp(self):
        e = TargetEntity(TargetConfig(motion_type="constant_velocity",
                                      velocity_x_mps=0.0, velocity_y_mps=0.0))
        s0 = e.update(0.5, 0.5)
        s1 = e.update(0.5, 1.0)
        self.assertAlmostEqual(s0.timestamp, 0.5)
        self.assertAlmostEqual(s1.timestamp, 1.0)

    def test_update_sets_bearing_and_distance(self):
        cfg = TargetConfig(motion_type="constant_velocity",
                           initial_x_m=0.0, initial_y_m=0.0,
                           velocity_x_mps=3.0, velocity_y_mps=4.0)
        e = TargetEntity(cfg)
        state = e.update(1.0, 1.0)
        expected_bearing = math.degrees(math.atan2(4.0, 3.0))
        self.assertAlmostEqual(state.bearing_deg, expected_bearing, places=4)
        self.assertAlmostEqual(state.distance_m, 5.0, places=4)

    def test_get_state_returns_dict(self):
        e = TargetEntity()
        d = e.get_state()
        self.assertIsInstance(d, dict)
        self.assertIn("timestamp", d)
        self.assertIn("x_m", d)
        self.assertIn("y_m", d)
        self.assertIn("bearing_deg", d)
        self.assertIn("distance_m", d)

    def test_get_state_matches_internal_state(self):
        e = TargetEntity(TargetConfig(motion_type="constant_velocity",
                                      velocity_x_mps=1.0, velocity_y_mps=1.0))
        e.update(0.5, 0.5)
        d = e.get_state()
        self.assertAlmostEqual(d["timestamp"], e.state.timestamp)
        self.assertAlmostEqual(d["x_m"], e.state.x_m)
        self.assertAlmostEqual(d["y_m"], e.state.y_m)
        self.assertAlmostEqual(d["bearing_deg"], e.state.bearing_deg)
        self.assertAlmostEqual(d["distance_m"], e.state.distance_m)

    def test_multiple_updates_sinusoidal(self):
        e = TargetEntity()  # default sinusoidal
        states = [e.update(0.01, (i + 1) * 0.01) for i in range(10)]
        # Timestamps must be strictly increasing
        for i in range(1, len(states)):
            self.assertGreater(states[i].timestamp, states[i - 1].timestamp)
        # x must remain constant at initial_x_m = 100
        for s in states:
            self.assertAlmostEqual(s.x_m, 100.0)

    def test_entity_sinusoidal_bearing_and_distance(self):
        e = TargetEntity()  # default: sinusoidal, initial_x=100, y=0
        # At t=0 with a very small dt, bearing ~0 and distance ~100
        state = e.update(0.001, 0.001)
        self.assertAlmostEqual(state.bearing_deg, 0.0, places=1)
        self.assertAlmostEqual(state.distance_m, 100.0, places=1)


# ===================================================================
# 9. Edge cases
# ===================================================================

class TestEdgeCases(unittest.TestCase):

    def test_waypoint_empty_list_no_movement(self):
        """Empty waypoints list => target stays put."""
        cfg = TargetConfig(
            motion_type="waypoint",
            initial_x_m=42.0, initial_y_m=-7.0,
            waypoints=[],
        )
        m = TargetKinematics2D(cfg)
        for _ in range(100):
            m.step(0.1)
        self.assertAlmostEqual(m.x, 42.0)
        self.assertAlmostEqual(m.y, -7.0)
        self.assertEqual(m.vx, 0.0)
        self.assertEqual(m.vy, 0.0)

    def test_waypoint_none_no_movement(self):
        """waypoints=None => no movement."""
        cfg = TargetConfig(
            motion_type="waypoint",
            initial_x_m=5.0, initial_y_m=5.0,
            waypoints=None,
        )
        m = TargetKinematics2D(cfg)
        for _ in range(50):
            m.step(0.1)
        self.assertAlmostEqual(m.x, 5.0)
        self.assertAlmostEqual(m.y, 5.0)

    def test_waypoint_speed_zero_hover(self):
        """Speed=0 at a waypoint means hover (no movement)."""
        cfg = TargetConfig(
            motion_type="waypoint",
            initial_x_m=0.0, initial_y_m=0.0,
            waypoints=[(100.0, 100.0, 0.0)],
        )
        m = TargetKinematics2D(cfg)
        m.step(1.0)
        self.assertAlmostEqual(m.x, 0.0)
        self.assertAlmostEqual(m.y, 0.0)
        self.assertEqual(m.vx, 0.0)
        self.assertEqual(m.vy, 0.0)

    def test_constant_velocity_zero_velocity(self):
        """Zero velocity means target stays at initial position."""
        cfg = TargetConfig(
            motion_type="constant_velocity",
            initial_x_m=10.0, initial_y_m=20.0,
            velocity_x_mps=0.0, velocity_y_mps=0.0,
        )
        m = TargetKinematics2D(cfg)
        for _ in range(200):
            m.step(0.05)
        self.assertAlmostEqual(m.x, 10.0)
        self.assertAlmostEqual(m.y, 20.0)

    def test_zero_dt(self):
        """dt=0 should not change position for constant_velocity."""
        cfg = TargetConfig(motion_type="constant_velocity",
                           velocity_x_mps=5.0, velocity_y_mps=5.0)
        m = TargetKinematics2D(cfg)
        x, y = m.step(0.0)
        self.assertAlmostEqual(x, cfg.initial_x_m)
        self.assertAlmostEqual(y, cfg.initial_y_m)
        # t still increments by 0
        self.assertAlmostEqual(m.t, 0.0)

    def test_large_dt_sinusoidal(self):
        """Large dt in sinusoidal should still evaluate the closed-form formula."""
        cfg = TargetConfig(
            motion_type="sinusoidal",
            initial_x_m=50.0,
            sin_amplitude_m=10.0, sin_frequency_hz=0.1,
        )
        m = TargetKinematics2D(cfg)
        # One step of 5.0 s = full period where T=10 s for f=0.1
        m.step(5.0)
        self.assertAlmostEqual(m.x, 50.0)
        # sin(2*pi) = 0 (at full period)
        self.assertAlmostEqual(m.y, 0.0, places=5)

    def test_negative_initial_position_bearing(self):
        """Bearing for negative-x, positive-y should be in (90, 180]."""
        cfg = TargetConfig(
            motion_type="constant_velocity",
            initial_x_m=-10.0, initial_y_m=10.0,
            velocity_x_mps=0.0, velocity_y_mps=0.0,
        )
        m = TargetKinematics2D(cfg)
        m.step(1.0)  # stays at (-10, 10) since v=0
        self.assertAlmostEqual(m.bearing_deg, 135.0, places=4)

    def test_constant_accel_zero_initial_velocity(self):
        """Starting from rest with constant accel, position = 0.5*a*t^2."""
        cfg = TargetConfig(
            motion_type="constant_accel",
            initial_x_m=0.0, initial_y_m=0.0,
            velocity_x_mps=0.0, velocity_y_mps=0.0,
            accel_x_mps2=0.0, accel_y_mps2=4.0,
        )
        m = TargetKinematics2D(cfg)
        dt = 0.001
        for _ in range(1000):  # 1 second
            m.step(dt)
        # Euler: y ~ 0.5 * 4 * 1^2 = 2.0 (with small error)
        self.assertAlmostEqual(m.y, 2.0, places=1)
        self.assertAlmostEqual(m.vy, 4.0, places=3)

    def test_waypoint_arrival_radius_snap(self):
        """When within arrival radius, position snaps to waypoint."""
        cfg = TargetConfig(
            motion_type="waypoint",
            initial_x_m=0.0, initial_y_m=0.0,
            waypoints=[(0.5, 0.0, 10.0)],
            waypoint_arrival_radius_m=1.0,
        )
        m = TargetKinematics2D(cfg)
        m.step(0.01)
        # Already within arrival radius from the start (0.5 < 1.0)
        # so it should snap immediately
        self.assertAlmostEqual(m.x, 0.5)
        self.assertAlmostEqual(m.y, 0.0)
        self.assertEqual(m.vx, 0.0)
        self.assertEqual(m.vy, 0.0)

    def test_sinusoidal_amplitude_zero(self):
        """Zero amplitude => no oscillation, y stays at 0."""
        cfg = TargetConfig(
            motion_type="sinusoidal",
            initial_x_m=50.0,
            sin_amplitude_m=0.0, sin_frequency_hz=1.0,
        )
        m = TargetKinematics2D(cfg)
        for _ in range(50):
            x, y = m.step(0.1)
            self.assertAlmostEqual(x, 50.0)
            self.assertAlmostEqual(y, 0.0)
            self.assertAlmostEqual(m.vy, 0.0)


if __name__ == "__main__":
    unittest.main()
