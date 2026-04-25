import unittest
import math

import numpy as np

from runtime.types import POWER_BOOTING, POWER_OFF, POWER_READY

from entities.camera.entity import CameraEntity, detect_beacon_centroid
from entities.camera.model import CameraImagingModel
from entities.camera.control import ZoomController
from config import CameraConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_target():
    return {"x_m": 100.0, "y_m": 0.0}


def _default_gimbal():
    return {"yaw_deg_internal": 0.0}


def _boot_camera(cam: CameraEntity, ts: float = 0.0, dt: float = 0.01) -> None:
    """Power on and run update loop until the camera reaches READY state."""
    cam.power_on(ts)
    t = ts
    while cam.power_state != POWER_READY:
        t += dt
        cam.update(dt, t, _default_target(), _default_gimbal())


# ===================================================================
# 1. Power state machine
# ===================================================================

class TestPowerStateMachine(unittest.TestCase):

    def test_initial_state_is_off(self):
        cam = CameraEntity()
        self.assertEqual(cam.power_state, POWER_OFF)

    def test_power_on_transitions_to_booting(self):
        cam = CameraEntity()
        result = cam.power_on(0.0)
        self.assertTrue(result.accepted)
        self.assertEqual(cam.power_state, POWER_BOOTING)

    def test_booting_to_ready_after_boot_delay(self):
        cam = CameraEntity()
        cam.power_on(0.0)
        # boot_delay_s = 0.5; run enough steps to cross it
        t = 0.0
        dt = 0.01
        for _ in range(60):  # 0.6 s total
            t += dt
            cam.update(dt, t, _default_target(), _default_gimbal())
        self.assertEqual(cam.power_state, POWER_READY)

    def test_booting_not_ready_before_delay(self):
        cam = CameraEntity()
        cam.power_on(0.0)
        # Only 0.3 s of updates -- not enough for 0.5 s boot delay
        t = 0.0
        dt = 0.01
        for _ in range(30):
            t += dt
            cam.update(dt, t, _default_target(), _default_gimbal())
        self.assertEqual(cam.power_state, POWER_BOOTING)

    def test_power_on_while_booting_returns_already_on(self):
        cam = CameraEntity()
        cam.power_on(0.0)
        result = cam.power_on(0.1)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "ALREADY_ON")

    def test_power_on_while_ready_returns_already_on(self):
        cam = CameraEntity()
        _boot_camera(cam)
        result = cam.power_on(1.0)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "ALREADY_ON")

    def test_power_off_sets_state_to_off(self):
        cam = CameraEntity()
        _boot_camera(cam)
        result = cam.power_off(1.0)
        self.assertTrue(result.accepted)
        self.assertEqual(cam.power_state, POWER_OFF)

    def test_power_off_clears_frame(self):
        cam = CameraEntity()
        _boot_camera(cam)
        cam.update(0.01, 1.0, _default_target(), _default_gimbal())
        self.assertIsNotNone(cam.get_frame())
        cam.power_off(1.0)
        self.assertIsNone(cam.get_frame())

    def test_power_off_zeros_zoom_rate(self):
        cam = CameraEntity()
        _boot_camera(cam)
        cam.set_zoom_rate_mmps(50.0, 1.0)
        self.assertEqual(cam.zoom_rate_cmd_mmps, 50.0)
        cam.power_off(1.0)
        self.assertEqual(cam.zoom_rate_cmd_mmps, 0.0)

    def test_set_zoom_target_rejected_when_off(self):
        cam = CameraEntity()
        result = cam.set_zoom_target_mm(50.0, 0.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "NOT_READY")

    def test_set_zoom_target_rejected_when_booting(self):
        cam = CameraEntity()
        cam.power_on(0.0)
        result = cam.set_zoom_target_mm(50.0, 0.1)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "NOT_READY")

    def test_set_zoom_rate_rejected_when_off(self):
        cam = CameraEntity()
        result = cam.set_zoom_rate_mmps(30.0, 0.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "NOT_READY")

    def test_zoom_by_rejected_when_off(self):
        cam = CameraEntity()
        result = cam.zoom_by(10.0, 0.0)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "NOT_READY")


# ===================================================================
# 2. Zoom target
# ===================================================================

class TestZoomTarget(unittest.TestCase):

    def setUp(self):
        self.cam = CameraEntity()
        _boot_camera(self.cam)

    def test_set_zoom_target_accepted_when_ready(self):
        result = self.cam.set_zoom_target_mm(50.0, 1.0)
        self.assertTrue(result.accepted)
        self.assertEqual(self.cam.f_target_mm, 50.0)

    def test_set_zoom_target_clamps_to_min(self):
        self.cam.set_zoom_target_mm(1.0, 1.0)
        self.assertAlmostEqual(self.cam.f_target_mm, 4.4)

    def test_set_zoom_target_clamps_to_max(self):
        self.cam.set_zoom_target_mm(500.0, 1.0)
        self.assertAlmostEqual(self.cam.f_target_mm, 200.0)

    def test_set_zoom_target_within_range_unchanged(self):
        self.cam.set_zoom_target_mm(100.0, 1.0)
        self.assertAlmostEqual(self.cam.f_target_mm, 100.0)

    def test_set_zoom_target_clears_zoom_rate_cmd(self):
        self.cam.set_zoom_rate_mmps(30.0, 1.0)
        self.assertEqual(self.cam.zoom_rate_cmd_mmps, 30.0)
        self.cam.set_zoom_target_mm(50.0, 1.0)
        self.assertEqual(self.cam.zoom_rate_cmd_mmps, 0.0)

    def test_zoom_by_adds_to_target(self):
        initial_target = self.cam.f_target_mm
        self.cam.zoom_by(10.0, 1.0)
        self.assertAlmostEqual(self.cam.f_target_mm, initial_target + 10.0)

    def test_zoom_by_clamps_result(self):
        self.cam.zoom_by(500.0, 1.0)
        self.assertAlmostEqual(self.cam.f_target_mm, 200.0)

    def test_zoom_by_negative(self):
        self.cam.zoom_by(-5.0, 1.0)
        expected = 12.0 - 5.0  # default focal_length_mm is 12
        self.assertAlmostEqual(self.cam.f_target_mm, expected)


# ===================================================================
# 3. Zoom rate
# ===================================================================

class TestZoomRate(unittest.TestCase):

    def setUp(self):
        self.cam = CameraEntity()
        _boot_camera(self.cam)

    def test_set_zoom_rate_accepted_when_ready(self):
        result = self.cam.set_zoom_rate_mmps(50.0, 1.0)
        self.assertTrue(result.accepted)
        self.assertEqual(self.cam.zoom_rate_cmd_mmps, 50.0)

    def test_set_zoom_rate_clamps_positive(self):
        self.cam.set_zoom_rate_mmps(999.0, 1.0)
        self.assertAlmostEqual(self.cam.zoom_rate_cmd_mmps, 120.0)

    def test_set_zoom_rate_clamps_negative(self):
        self.cam.set_zoom_rate_mmps(-999.0, 1.0)
        self.assertAlmostEqual(self.cam.zoom_rate_cmd_mmps, -120.0)

    def test_zoom_rate_linear_change(self):
        """With rate set, focal length changes linearly each update."""
        self.cam.set_zoom_rate_mmps(50.0, 1.0)
        f_before = self.cam.f_current_mm
        dt = 0.01
        self.cam.update(dt, 1.01, _default_target(), _default_gimbal())
        f_after = self.cam.f_current_mm
        expected_change = 50.0 * dt
        self.assertAlmostEqual(f_after - f_before, expected_change, places=5)

    def test_zoom_rate_accumulates_over_multiple_steps(self):
        """Accumulated linear zoom over several steps matches rate * total_dt."""
        self.cam.set_zoom_rate_mmps(40.0, 1.0)
        f_start = self.cam.f_current_mm
        dt = 0.005
        t = 1.0
        for _ in range(20):
            t += dt
            self.cam.update(dt, t, _default_target(), _default_gimbal())
        total_dt = 20 * dt  # 0.1 s
        expected = f_start + 40.0 * total_dt
        self.assertAlmostEqual(self.cam.f_current_mm, expected, places=3)

    def test_zoom_rate_clamps_focal_to_limits(self):
        """Rate-driven zoom must not exceed focal bounds."""
        self.cam.f_current_mm = 199.0
        self.cam.set_zoom_rate_mmps(120.0, 1.0)
        self.cam.update(0.1, 1.01, _default_target(), _default_gimbal())
        self.assertLessEqual(self.cam.f_current_mm, 200.0)


# ===================================================================
# 4. Zoom continuity
# ===================================================================

class TestZoomContinuity(unittest.TestCase):

    def test_exponential_approach_no_jump(self):
        """Focal length moves toward target smoothly (no sudden jumps)."""
        cam = CameraEntity()
        _boot_camera(cam)
        cam.set_zoom_target_mm(50.0, 1.0)
        dt = 0.01
        t = 1.0
        prev_f = cam.f_current_mm
        for _ in range(50):
            t += dt
            cam.update(dt, t, _default_target(), _default_gimbal())
            cur_f = cam.f_current_mm
            # focal length should increase monotonically toward 50 from 12
            self.assertGreaterEqual(cur_f, prev_f - 1e-9,
                                    "Focal length should not decrease when approaching a higher target")
            prev_f = cur_f

    def test_focal_converges_toward_target(self):
        """After many steps focal length gets close to target."""
        cam = CameraEntity()
        _boot_camera(cam)
        cam.set_zoom_target_mm(50.0, 1.0)
        dt = 0.01
        t = 1.0
        for _ in range(300):
            t += dt
            cam.update(dt, t, _default_target(), _default_gimbal())
        self.assertAlmostEqual(cam.f_current_mm, 50.0, places=1)

    def test_rate_mode_then_target_mode_smooth(self):
        """Switching from rate mode to target mode does not cause a jump."""
        cam = CameraEntity()
        _boot_camera(cam)
        cam.set_zoom_rate_mmps(50.0, 1.0)
        dt = 0.01
        t = 1.0
        for _ in range(20):
            t += dt
            cam.update(dt, t, _default_target(), _default_gimbal())
        # Now switch to target mode — set target to current position
        f_at_switch = cam.f_current_mm
        cam.set_zoom_target_mm(f_at_switch, t)
        f_after = cam.f_current_mm
        # Next step should barely move since target = current
        cam.update(dt, t + dt, _default_target(), _default_gimbal())
        f_after = cam.f_current_mm
        self.assertLess(abs(f_after - f_at_switch), 1.0)


# ===================================================================
# 5. Imaging model
# ===================================================================

class TestImagingModel(unittest.TestCase):

    def setUp(self):
        self.cfg = CameraConfig()
        self.model = CameraImagingModel(self.cfg)

    def test_focal_px_at_default(self):
        """focal_px = f_mm / pixel_size_mm where pixel_size_mm = sensor_w / res_w."""
        pixel_size = self.cfg.sensor_w_mm / self.cfg.resolution_w  # 4.8/640 = 0.0075
        expected = self.cfg.focal_length_mm / pixel_size  # 12/0.0075 = 1600
        self.assertAlmostEqual(self.model.focal_px(12.0), expected, places=3)

    def test_focal_px_at_50mm(self):
        pixel_size = self.cfg.sensor_w_mm / self.cfg.resolution_w
        expected = 50.0 / pixel_size
        self.assertAlmostEqual(self.model.focal_px(50.0), expected, places=3)

    def test_fov_half_rad_at_default(self):
        """fov_half = atan(sensor_w / (2 * f_mm))."""
        expected = math.atan(self.cfg.sensor_w_mm / (2.0 * 12.0))
        self.assertAlmostEqual(self.model.fov_half_rad(12.0), expected, places=6)

    def test_fov_half_rad_at_200mm(self):
        expected = math.atan(self.cfg.sensor_w_mm / (2.0 * 200.0))
        self.assertAlmostEqual(self.model.fov_half_rad(200.0), expected, places=6)

    def test_fov_shrinks_with_longer_focal(self):
        fov_short = self.model.fov_half_rad(4.4)
        fov_long = self.model.fov_half_rad(200.0)
        self.assertGreater(fov_short, fov_long)


# ===================================================================
# 6. FOV check
# ===================================================================

class TestFOVCheck(unittest.TestCase):

    def setUp(self):
        self.cfg = CameraConfig()
        self.model = CameraImagingModel(self.cfg)

    def test_target_inside_fov(self):
        """Small alpha within fov_half should be in FOV."""
        fov_half = self.model.fov_half_rad(12.0)
        _, in_fov, _, _ = self.model.render_beacon_frame(fov_half * 0.5, 12.0, 0.0)
        self.assertTrue(in_fov)

    def test_target_at_fov_edge(self):
        """Target at exactly fov_half_rad is still in FOV (<=)."""
        fov_half = self.model.fov_half_rad(12.0)
        _, in_fov, _, _ = self.model.render_beacon_frame(fov_half, 12.0, 0.0)
        self.assertTrue(in_fov)

    def test_target_outside_fov(self):
        """Alpha beyond fov_half means out of FOV."""
        fov_half = self.model.fov_half_rad(12.0)
        _, in_fov, u_px, v_px = self.model.render_beacon_frame(fov_half * 2.0, 12.0, 0.0)
        self.assertFalse(in_fov)
        self.assertTrue(math.isnan(u_px))
        self.assertTrue(math.isnan(v_px))

    def test_negative_alpha_outside_fov(self):
        fov_half = self.model.fov_half_rad(12.0)
        _, in_fov, _, _ = self.model.render_beacon_frame(-fov_half * 2.0, 12.0, 0.0)
        self.assertFalse(in_fov)


# ===================================================================
# 7. Pixel coordinate mapping
# ===================================================================

class TestPixelCoordinateMapping(unittest.TestCase):

    def setUp(self):
        self.cfg = CameraConfig()
        self.model = CameraImagingModel(self.cfg)

    def test_u_px_for_zero_alpha(self):
        """At alpha=0, u_px should be at image center (w/2)."""
        _, in_fov, u_px, v_px = self.model.render_beacon_frame(0.0, 12.0, 0.0)
        self.assertTrue(in_fov)
        self.assertAlmostEqual(u_px, self.cfg.resolution_w / 2.0, places=2)
        self.assertAlmostEqual(v_px, self.cfg.resolution_h / 2.0, places=2)

    def test_u_px_for_known_alpha(self):
        """u_px = focal_px * tan(alpha) + w/2 for a target in FOV."""
        alpha = 0.05  # small angle, well within FOV at 12mm
        f_mm = 12.0
        focal_px = self.model.focal_px(f_mm)
        expected_u = focal_px * math.tan(alpha) + self.cfg.resolution_w / 2.0
        _, in_fov, u_px, _ = self.model.render_beacon_frame(alpha, f_mm, 0.0)
        self.assertTrue(in_fov)
        self.assertAlmostEqual(u_px, expected_u, places=2)

    def test_v_px_always_center(self):
        """v_px is always h/2 (1D beacon on the horizontal axis)."""
        for alpha in [0.0, 0.02, -0.03, 0.1]:
            fov_half = self.model.fov_half_rad(12.0)
            if abs(alpha) <= fov_half:
                _, in_fov, _, v_px = self.model.render_beacon_frame(alpha, 12.0, 0.0)
                self.assertAlmostEqual(v_px, self.cfg.resolution_h / 2.0, places=2)

    def test_u_px_for_negative_alpha(self):
        alpha = -0.03
        f_mm = 12.0
        focal_px = self.model.focal_px(f_mm)
        expected_u = focal_px * math.tan(alpha) + self.cfg.resolution_w / 2.0
        _, in_fov, u_px, _ = self.model.render_beacon_frame(alpha, f_mm, 0.0)
        self.assertTrue(in_fov)
        self.assertAlmostEqual(u_px, expected_u, places=2)


# ===================================================================
# 8. detect_beacon_centroid
# ===================================================================

class TestDetectBeaconCentroid(unittest.TestCase):

    def test_finds_centroid_of_rendered_beacon(self):
        """Render a frame with beacon in FOV and detect its centroid."""
        model = CameraImagingModel(CameraConfig())
        alpha = 0.0  # centered
        image, in_fov, u_gt, v_gt = model.render_beacon_frame(alpha, 12.0, 0.0)
        self.assertTrue(in_fov)
        det = detect_beacon_centroid(image, threshold=100)
        self.assertTrue(det.found)
        # Beacon is at center, centroid should be near w/2, h/2
        self.assertAlmostEqual(det.cx, 320.0, delta=5.0)
        self.assertAlmostEqual(det.cy, 240.0, delta=5.0)
        self.assertGreater(det.confidence, 0.0)

    def test_returns_nan_when_not_found(self):
        """All-zero image should return found=False with no cx/cy."""
        image = np.zeros((480, 640), dtype=np.uint8)
        det = detect_beacon_centroid(image, threshold=180)
        self.assertFalse(det.found)
        self.assertIsNone(det.cx)
        self.assertIsNone(det.cy)
        self.assertEqual(det.confidence, 0.0)

    def test_returns_nan_when_below_threshold(self):
        """Image with values just below threshold should not be found."""
        image = np.full((480, 640), 179, dtype=np.uint8)
        det = detect_beacon_centroid(image, threshold=180)
        self.assertFalse(det.found)

    def test_detects_with_low_threshold(self):
        """Values above a low threshold should be found."""
        image = np.full((480, 640), 50, dtype=np.uint8)
        det = detect_beacon_centroid(image, threshold=40)
        self.assertTrue(det.found)

    def test_off_center_beacon(self):
        """Beacon at non-zero alpha should have off-center cx."""
        model = CameraImagingModel(CameraConfig())
        alpha = 0.1  # non-trivial angle
        fov_half = model.fov_half_rad(12.0)
        if abs(alpha) > fov_half:
            self.skipTest("alpha outside FOV for this config")
        image, in_fov, u_gt, v_gt = model.render_beacon_frame(alpha, 12.0, 0.0)
        if not in_fov:
            self.skipTest("alpha not in FOV")
        det = detect_beacon_centroid(image, threshold=100)
        self.assertTrue(det.found)
        self.assertAlmostEqual(det.cx, u_gt, delta=5.0)


# ===================================================================
# 9. Frame generation
# ===================================================================

class TestFrameGeneration(unittest.TestCase):

    def setUp(self):
        self.cam = CameraEntity()
        _boot_camera(self.cam)

    def test_frame_packet_has_correct_fields(self):
        self.cam.update(0.01, 1.0, _default_target(), _default_gimbal())
        frame = self.cam.get_frame()
        self.assertIsNotNone(frame)
        self.assertIsInstance(frame.timestamp, float)
        self.assertIsInstance(frame.image, np.ndarray)
        self.assertEqual(frame.image.shape, (480, 640))
        self.assertIsInstance(frame.intrinsics, dict)
        self.assertIn("f_mm", frame.intrinsics)
        self.assertIn("f_px", frame.intrinsics)
        self.assertIn("cx", frame.intrinsics)
        self.assertIn("cy", frame.intrinsics)
        self.assertIn("width", frame.intrinsics)
        self.assertIn("height", frame.intrinsics)

    def test_frame_id_increments(self):
        fid0 = self.cam.frame_id
        self.cam.update(0.01, 1.0, _default_target(), _default_gimbal())
        self.assertEqual(self.cam.frame_id, fid0 + 1)
        self.cam.update(0.01, 1.01, _default_target(), _default_gimbal())
        self.assertEqual(self.cam.frame_id, fid0 + 2)

    def test_frame_id_does_not_increment_when_booting(self):
        cam = CameraEntity()
        cam.power_on(0.0)
        cam.update(0.01, 0.01, _default_target(), _default_gimbal())
        self.assertEqual(cam.frame_id, 0)

    def test_frame_id_does_not_increment_when_off(self):
        cam = CameraEntity()
        cam.update(0.01, 0.01, _default_target(), _default_gimbal())
        self.assertEqual(cam.frame_id, 0)

    def test_frame_timestamp_matches_update(self):
        ts = 1.5
        self.cam.update(0.01, ts, _default_target(), _default_gimbal())
        frame = self.cam.get_frame()
        self.assertAlmostEqual(frame.timestamp, ts)

    def test_optional_gt_present_when_in_fov(self):
        """When target is in FOV, optional_gt should be populated."""
        # target at (100, 0), gimbal yaw = 0 → alpha = 0, well within FOV
        self.cam.update(0.01, 1.0, _default_target(), _default_gimbal())
        frame = self.cam.get_frame()
        self.assertIsNotNone(frame.optional_gt)
        self.assertIn("u_px", frame.optional_gt)
        self.assertIn("v_px", frame.optional_gt)
        self.assertIn("in_fov", frame.optional_gt)

    def test_optional_gt_absent_when_not_in_fov(self):
        """When target is outside FOV, optional_gt should be None."""
        # Use extreme gimbal yaw to push alpha out of FOV
        self.cam.update(0.01, 1.0, _default_target(), {"yaw_deg_internal": 180.0})
        frame = self.cam.get_frame()
        # gimbal pointing at 180 deg, target at 0 deg → alpha ~ pi → way outside FOV
        self.assertIsNone(frame.optional_gt)

    def test_intrinsics_f_mm_matches_current(self):
        self.cam.set_zoom_target_mm(50.0, 1.0)
        # Run enough updates to let zoom converge
        dt = 0.01
        t = 1.0
        for _ in range(300):
            t += dt
            self.cam.update(dt, t, _default_target(), _default_gimbal())
        frame = self.cam.get_frame()
        self.assertAlmostEqual(frame.intrinsics["f_mm"], self.cam.f_current_mm, places=3)


# ===================================================================
# 10. get_state() returns expected dict keys
# ===================================================================

class TestGetState(unittest.TestCase):

    def test_state_has_all_expected_keys(self):
        cam = CameraEntity()
        state = cam.get_state()
        expected_keys = {
            "timestamp", "power_state", "f_current_mm", "f_target_mm",
            "zoom_rate_cmd_mmps", "frame_id", "in_fov", "u_px", "v_px"
        }
        self.assertEqual(set(state.keys()), expected_keys)

    def test_initial_state_values(self):
        cam = CameraEntity()
        state = cam.get_state()
        self.assertEqual(state["power_state"], POWER_OFF)
        self.assertAlmostEqual(state["f_current_mm"], 12.0)
        self.assertAlmostEqual(state["f_target_mm"], 12.0)
        self.assertEqual(state["zoom_rate_cmd_mmps"], 0.0)
        self.assertEqual(state["frame_id"], 0)

    def test_state_reflects_after_update(self):
        cam = CameraEntity()
        _boot_camera(cam)
        fid_before = cam.frame_id
        cam.set_zoom_target_mm(50.0, 1.0)
        cam.update(0.01, 1.0, _default_target(), _default_gimbal())
        state = cam.get_state()
        self.assertEqual(state["power_state"], POWER_READY)
        self.assertEqual(state["frame_id"], fid_before + 1)
        # f_target should be 50, f_current moving toward it (started at 12)
        self.assertAlmostEqual(state["f_target_mm"], 50.0)
        self.assertGreater(state["f_current_mm"], 12.0)


# ===================================================================
# ZoomController unit tests
# ===================================================================

class TestZoomController(unittest.TestCase):

    def test_exponential_approach(self):
        """Without rate, focal approaches target via exponential filter."""
        ctrl = ZoomController(tau_s=0.2)
        f = 12.0
        f_target = 50.0
        dt = 0.01
        alpha = dt / (0.2 + dt)
        expected = (1.0 - alpha) * 12.0 + alpha * 50.0
        result = ctrl.update(f, f_target, 0.0, dt)
        self.assertAlmostEqual(result, expected, places=6)

    def test_rate_mode(self):
        """With rate set, focal changes by rate * dt."""
        ctrl = ZoomController(tau_s=0.2, max_rate_mmps=120.0)
        f = 12.0
        dt = 0.01
        rate = 50.0
        result = ctrl.update(f, 12.0, rate, dt)
        self.assertAlmostEqual(result, 12.0 + rate * dt, places=6)

    def test_rate_clamped(self):
        """Rate command is clamped to max_rate_mmps."""
        ctrl = ZoomController(tau_s=0.2, max_rate_mmps=120.0)
        f = 12.0
        dt = 0.01
        result = ctrl.update(f, 12.0, 200.0, dt)
        expected = 12.0 + 120.0 * dt
        self.assertAlmostEqual(result, expected, places=6)

    def test_zero_rate_uses_exponential(self):
        """Rate of exactly 0 should trigger exponential approach."""
        ctrl = ZoomController(tau_s=0.2)
        f = 10.0
        f_target = 100.0
        dt = 0.01
        alpha = dt / (0.2 + dt)
        expected = (1.0 - alpha) * f + alpha * f_target
        result = ctrl.update(f, f_target, 0.0, dt)
        self.assertAlmostEqual(result, expected, places=6)


# ===================================================================
# Alpha computation in update()
# ===================================================================

class TestAlphaComputation(unittest.TestCase):

    def _run_single_update(self, target_state, gimbal_state):
        cam = CameraEntity()
        _boot_camera(cam)
        cam.update(0.01, 1.0, target_state, gimbal_state)
        return cam.get_state()

    def test_alpha_zero_when_aligned(self):
        """Target along x-axis with gimbal yaw=0 → alpha ~0, target in FOV."""
        state = self._run_single_update({"x_m": 100.0, "y_m": 0.0}, {"yaw_deg_internal": 0.0})
        self.assertTrue(state["in_fov"])

    def test_alpha_positive_when_target_right(self):
        """Target at positive y with gimbal at yaw=0 → positive bearing."""
        state = self._run_single_update({"x_m": 100.0, "y_m": 10.0}, {"yaw_deg_internal": 0.0})
        self.assertTrue(state["in_fov"])
        # u_px should be > center (target is to the right)
        self.assertGreater(state["u_px"], 320.0)

    def test_alpha_negative_when_target_left(self):
        """Target at negative y with gimbal at yaw=0 → negative bearing."""
        state = self._run_single_update({"x_m": 100.0, "y_m": -10.0}, {"yaw_deg_internal": 0.0})
        self.assertTrue(state["in_fov"])
        # u_px should be < center (target is to the left)
        self.assertLess(state["u_px"], 320.0)

    def test_gimbal_offset_compensates(self):
        """If gimbal points at target bearing, alpha ~0 and target is centered."""
        # Target bearing = atan2(10, 100) ~ 5.71 deg
        target = {"x_m": 100.0, "y_m": 10.0}
        bearing_deg = math.degrees(math.atan2(10.0, 100.0))
        state = self._run_single_update(target, {"yaw_deg_internal": bearing_deg})
        self.assertTrue(state["in_fov"])
        self.assertAlmostEqual(state["u_px"], 320.0, delta=2.0)


if __name__ == "__main__":
    unittest.main()
