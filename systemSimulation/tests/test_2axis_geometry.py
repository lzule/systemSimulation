"""双轴几何测试：验证 azimuth/elevation → alpha/beta → u/v 的几何正确性。"""

import math
import unittest

from config import CameraConfig
from entities.camera.model import CameraImagingModel
from entities.target.model import TargetKinematics3D
from config import TargetConfig


class TestAzimuthElevation(unittest.TestCase):
    """验证 TargetKinematics3D 的 azimuth 和 elevation 计算。"""

    def _make_model(self, x, y, z=0.0):
        cfg = TargetConfig(initial_x_m=x, initial_y_m=y, initial_z_m=z, motion_type="constant_velocity")
        return TargetKinematics3D(cfg)

    def test_plus_x_azimuth_zero(self):
        """+x 方向 (100,0,0)：azimuth=0°, elevation=0°"""
        m = self._make_model(100, 0, 0)
        self.assertAlmostEqual(m.azimuth_deg, 0.0, places=5)
        self.assertAlmostEqual(m.elevation_deg, 0.0, places=5)

    def test_plus_y_azimuth_90(self):
        """+y 方向 (0,100,0)：azimuth=90°, elevation=0°"""
        m = self._make_model(0, 100, 0)
        self.assertAlmostEqual(m.azimuth_deg, 90.0, places=5)
        self.assertAlmostEqual(m.elevation_deg, 0.0, places=5)

    def test_minus_x_azimuth_180(self):
        """-x 方向 (-100,0,0)：azimuth=±180°, elevation=0°"""
        m = self._make_model(-100, 0, 0)
        self.assertAlmostEqual(abs(m.azimuth_deg), 180.0, places=5)
        self.assertAlmostEqual(m.elevation_deg, 0.0, places=5)

    def test_minus_y_azimuth_minus_90(self):
        """-y 方向 (0,-100,0)：azimuth=-90°, elevation=0°"""
        m = self._make_model(0, -100, 0)
        self.assertAlmostEqual(m.azimuth_deg, -90.0, places=5)
        self.assertAlmostEqual(m.elevation_deg, 0.0, places=5)

    def test_upward_elevation_positive(self):
        """上仰方向 (0,100,50)：elevation>0"""
        m = self._make_model(0, 100, 50)
        self.assertAlmostEqual(m.elevation_deg, math.degrees(math.atan2(50, 100)), places=5)
        self.assertAlmostEqual(m.azimuth_deg, 90.0, places=5)

    def test_downward_elevation_negative(self):
        """下俯方向 (0,100,-30)：elevation<0"""
        m = self._make_model(0, 100, -30)
        expected = math.degrees(math.atan2(-30, 100))
        self.assertAlmostEqual(m.elevation_deg, expected, places=5)

    def test_diagonal_up(self):
        """斜上方 (100,100,50)"""
        m = self._make_model(100, 100, 50)
        self.assertAlmostEqual(m.azimuth_deg, 45.0, places=5)
        h_dist = math.sqrt(100**2 + 100**2)
        self.assertAlmostEqual(m.elevation_deg, math.degrees(math.atan2(50, h_dist)), places=5)

    def test_diagonal_down(self):
        """斜下方 (-100,100,-30)"""
        m = self._make_model(-100, 100, -30)
        self.assertAlmostEqual(m.azimuth_deg, 135.0, places=5)
        h_dist = math.sqrt(100**2 + 100**2)
        self.assertAlmostEqual(m.elevation_deg, math.degrees(math.atan2(-30, h_dist)), places=5)

    def test_bearing_deg_alias(self):
        """bearing_deg 应与 azimuth_deg 完全一致"""
        m = self._make_model(50, 80, 30)
        self.assertAlmostEqual(m.bearing_deg, m.azimuth_deg, places=10)

    def test_distance_3d(self):
        """distance_m 应为 3D 距离"""
        m = self._make_model(3, 4, 12)
        self.assertAlmostEqual(m.distance_m, 13.0, places=5)

    def test_z_zero_distance_unchanged(self):
        """z=0 时 distance 应与 2D 一致"""
        m = self._make_model(3, 4, 0)
        self.assertAlmostEqual(m.distance_m, 5.0, places=5)


class TestDualAxisProjection(unittest.TestCase):
    """验证双轴像素投影的几何正确性。"""

    def setUp(self):
        self.cfg = CameraConfig()
        self.model = CameraImagingModel(self.cfg)
        self.f_mm = 12.0
        self.f_px = self.model.focal_px(self.f_mm)
        self.cx = self.cfg.resolution_w / 2.0
        self.cy = self.cfg.resolution_h / 2.0

    def test_alpha_zero_beta_zero_center(self):
        """α=0, β=0 → u=cx, v=cy"""
        _, in_fov, u, v = self.model.render_beacon_frame(0.0, 0.0, self.f_mm, 0.0)
        self.assertTrue(in_fov)
        self.assertAlmostEqual(u, self.cx, places=2)
        self.assertAlmostEqual(v, self.cy, places=2)

    def test_positive_beta_v_above_center(self):
        """β>0 → v < cy（目标在画面上方）"""
        beta = 0.05
        _, in_fov, u, v = self.model.render_beacon_frame(0.0, beta, self.f_mm, 0.0)
        self.assertTrue(in_fov)
        expected_v = self.cy - self.f_px * math.tan(beta)
        self.assertAlmostEqual(v, expected_v, places=2)
        self.assertLess(v, self.cy)

    def test_negative_beta_v_below_center(self):
        """β<0 → v > cy（目标在画面下方）"""
        beta = -0.05
        _, in_fov, u, v = self.model.render_beacon_frame(0.0, beta, self.f_mm, 0.0)
        self.assertTrue(in_fov)
        expected_v = self.cy - self.f_px * math.tan(beta)
        self.assertAlmostEqual(v, expected_v, places=2)
        self.assertGreater(v, self.cy)

    def test_positive_alpha_u_right(self):
        """α>0 → u > cx（目标偏右）"""
        alpha = 0.05
        _, in_fov, u, v = self.model.render_beacon_frame(alpha, 0.0, self.f_mm, 0.0)
        self.assertTrue(in_fov)
        expected_u = self.f_px * math.tan(alpha) + self.cx
        self.assertAlmostEqual(u, expected_u, places=2)
        self.assertGreater(u, self.cx)

    def test_negative_alpha_u_left(self):
        """α<0 → u < cx（目标偏左）"""
        alpha = -0.05
        _, in_fov, u, v = self.model.render_beacon_frame(alpha, 0.0, self.f_mm, 0.0)
        self.assertTrue(in_fov)
        expected_u = self.f_px * math.tan(alpha) + self.cx
        self.assertAlmostEqual(u, expected_u, places=2)
        self.assertLess(u, self.cx)

    def test_combined_alpha_beta(self):
        """同时有 α 和 β 偏差时 u 和 v 都正确"""
        alpha = 0.03
        beta = 0.04
        _, in_fov, u, v = self.model.render_beacon_frame(alpha, beta, self.f_mm, 0.0)
        self.assertTrue(in_fov)
        expected_u = self.f_px * math.tan(alpha) + self.cx
        expected_v = self.cy - self.f_px * math.tan(beta)
        self.assertAlmostEqual(u, expected_u, places=2)
        self.assertAlmostEqual(v, expected_v, places=2)

    def test_fov_vertical_inside(self):
        """β 在垂直 FOV 内时 in_fov=True"""
        fov_v_half = self.model.fov_v_half_rad(self.f_mm)
        _, in_fov, _, _ = self.model.render_beacon_frame(0.0, fov_v_half * 0.5, self.f_mm, 0.0)
        self.assertTrue(in_fov)

    def test_fov_vertical_outside(self):
        """β 超出垂直 FOV 时 in_fov=False"""
        fov_v_half = self.model.fov_v_half_rad(self.f_mm)
        _, in_fov, _, _ = self.model.render_beacon_frame(0.0, fov_v_half * 2.0, self.f_mm, 0.0)
        self.assertFalse(in_fov)

    def test_fov_both_axes_required(self):
        """必须水平和垂直都在 FOV 内"""
        fov_h_half = self.model.fov_h_half_rad(self.f_mm)
        fov_v_half = self.model.fov_v_half_rad(self.f_mm)
        # 水平在、垂直不在
        _, in_fov, _, _ = self.model.render_beacon_frame(0.0, fov_v_half * 2.0, self.f_mm, 0.0)
        self.assertFalse(in_fov)
        # 垂直在、水平不在
        _, in_fov, _, _ = self.model.render_beacon_frame(fov_h_half * 2.0, 0.0, self.f_mm, 0.0)
        self.assertFalse(in_fov)

    def test_fov_v_deg_property(self):
        """CameraConfig.fov_v_deg 应与传感器参数一致"""
        expected = 2.0 * math.degrees(math.atan(self.cfg.sensor_h_mm / (2.0 * self.cfg.focal_length_mm)))
        self.assertAlmostEqual(self.cfg.fov_v_deg, expected, places=5)


class TestPitchRateSignConvention(unittest.TestCase):
    """验证 pitch_rate 与 v 轴的符号关系。"""

    def test_target_above_pitch_rate_positive(self):
        """目标在画面上方 → beta>0 → pixel_error_y>0 → pitch_rate>0"""
        cy = 240.0
        det_cy = 200.0  # det.cy < cy → 目标在上方
        pixel_error_y = cy - det_cy  # = 40 > 0
        self.assertGreater(pixel_error_y, 0)

    def test_target_below_pitch_rate_negative(self):
        """目标在画面下方 → beta<0 → pixel_error_y<0 → pitch_rate<0"""
        cy = 240.0
        det_cy = 280.0  # det.cy > cy → 目标在下方
        pixel_error_y = cy - det_cy  # = -40 < 0
        self.assertLess(pixel_error_y, 0)

    def test_beta_positive_v_below_cy(self):
        """β>0 时 v < cy，几何上目标在上方"""
        cfg = CameraConfig()
        model = CameraImagingModel(cfg)
        f_mm = 12.0
        f_px = model.focal_px(f_mm)
        cy = cfg.resolution_h / 2.0
        beta = 0.1
        v = cy - f_px * math.tan(beta)
        self.assertLess(v, cy)

    def test_beta_negative_v_above_cy(self):
        """β<0 时 v > cy，几何上目标在下方"""
        cfg = CameraConfig()
        model = CameraImagingModel(cfg)
        f_mm = 12.0
        f_px = model.focal_px(f_mm)
        cy = cfg.resolution_h / 2.0
        beta = -0.1
        v = cy - f_px * math.tan(beta)
        self.assertGreater(v, cy)


if __name__ == "__main__":
    unittest.main()
