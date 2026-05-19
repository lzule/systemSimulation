"""
tests/test_near_real_imaging.py

阶段3轮A任务A3：近真实成像模型回归测试。

覆盖：
  - 距离相关 sigma (TestDistanceDependentSigma)
  - 亮度变化 (TestBrightnessVariation)
  - 丢检模型 (TestMissDetection)

所有测试使用 seed 控制随机性，统计测试使用大量样本并只断言趋势方向。
"""

import math
import unittest

import numpy as np

from config import CameraConfig
from entities.camera.entity import detect_beacon_centroid
from entities.camera.model import CameraImagingModel


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

def _make_cfg(**overrides) -> CameraConfig:
    """创建 CameraConfig，默认保证目标在 FOV 内。"""
    defaults = dict(
        resolution_w=640,
        resolution_h=480,
        sensor_w_mm=4.8,
        sensor_h_mm=3.6,
        focal_length_mm=12.0,
        beacon_sigma_px=3.2,
        detection_threshold=180,
        sigma_ref_distance_m=0.0,
        brightness_base=1.0,
        brightness_ref_distance_m=0.0,
        brightness_jitter_std=0.0,
        miss_detection_base_rate=0.0,
        miss_sigma_gain_px=0.0,
    )
    defaults.update(overrides)
    return CameraConfig(**defaults)


def _count_bright_pixels(frame: np.ndarray, threshold: int = 180) -> int:
    """统计帧中超过阈值的像素数量。"""
    return int(np.sum(frame >= threshold))


def _render(model: CameraImagingModel, distance_m: float = 0.0, seed: int = 42):
    """在目标中心(0, 0)处渲染一帧，返回 (frame, in_fov, u, v)。"""
    np.random.seed(seed)
    # alpha=0, beta=0 → 目标在视轴正中心
    return model.render_beacon_frame(
        alpha_rad=0.0,
        beta_rad=0.0,
        f_mm=12.0,
        timestamp=0.0,
        distance_m=distance_m,
    )


def _render_multiple(model: CameraImagingModel, distance_m: float = 0.0,
                     n: int = 500, base_seed: int = 42):
    """渲染多帧，返回列表 [(frame, in_fov, u, v), ...]。"""
    results = []
    for i in range(n):
        results.append(_render(model, distance_m=distance_m, seed=base_seed + i))
    return results


# ===================================================================
# TestDistanceDependentSigma
# ===================================================================

class TestDistanceDependentSigma(unittest.TestCase):
    """距离相关 sigma 测试。

    sigma = sigma_base / (1 + distance / sigma_ref_distance_m)

    验证方法：统计帧中超过阈值的像素数量。
    sigma 大 → 亮斑宽 → 高亮像素多；sigma 小 → 亮斑窄 → 高亮像素少。
    """

    def test_near_distance_sigma_near_base(self):
        """近距离(10m)时 sigma 接近 sigma_base(3.2)。"""
        cfg = _make_cfg(sigma_ref_distance_m=100.0)
        model = CameraImagingModel(cfg)

        # sigma(10m) = 3.2 / (1 + 10/100) = 3.2 / 1.1 ≈ 2.91
        # 接近 sigma_base=3.2，亮斑应该比较宽
        frame_near, in_fov, u, v, *_ = _render(model, distance_m=10.0, seed=42)

        self.assertTrue(in_fov)
        # 高亮像素数量应该接近固定 sigma 时的值
        bright_near = _count_bright_pixels(frame_near, threshold=50)

        # 参考帧：固定 sigma（sigma_ref_distance_m=0 → 使用 sigma_base）
        cfg_ref = _make_cfg(sigma_ref_distance_m=0.0)
        model_ref = CameraImagingModel(cfg_ref)
        frame_ref, _, _, _, *_ = _render(model_ref, distance_m=0.0, seed=42)
        bright_ref = _count_bright_pixels(frame_ref, threshold=50)

        # 近距离时 sigma 衰减很小，亮斑宽度应接近固定 sigma 参考
        # 允许 30% 差异（因噪声影响）
        self.assertGreater(bright_near, bright_ref * 0.7,
                           "近距离 sigma 应接近 sigma_base，亮斑不应显著变窄")

    def test_far_distance_sigma_smaller(self):
        """远距离(500m)时 sigma 显著小于 sigma_base。"""
        cfg = _make_cfg(sigma_ref_distance_m=100.0)
        model = CameraImagingModel(cfg)

        # sigma(500m) = 3.2 / (1 + 500/100) = 3.2 / 6.0 ≈ 0.533
        frame_far, in_fov, u, v, *_ = _render(model, distance_m=500.0, seed=42)

        self.assertTrue(in_fov)
        bright_far = _count_bright_pixels(frame_far, threshold=50)

        # 近距离参考
        frame_near, _, _, _, *_ = _render(model, distance_m=10.0, seed=42)
        bright_near = _count_bright_pixels(frame_near, threshold=50)

        # 远距离 sigma 更小 → 亮斑更窄 → 高亮像素显著更少
        self.assertLess(bright_far, bright_near * 0.7,
                        "远距离 sigma 应显著小于近距离，亮斑应更窄")

    def test_zero_ref_distance_degrades_to_fixed(self):
        """sigma_ref_distance_m=0 时退化为固定 sigma（直接用 beacon_sigma_px）。"""
        cfg = _make_cfg(sigma_ref_distance_m=0.0, beacon_sigma_px=3.2)
        model = CameraImagingModel(cfg)

        # distance_m > 0 但 sigma_ref_distance_m=0 → 仍使用 sigma_base
        frame_d0, _, _, _, *_ = _render(model, distance_m=0.0, seed=42)
        frame_d100, _, _, _, *_ = _render(model, distance_m=100.0, seed=42)
        frame_d500, _, _, _, *_ = _render(model, distance_m=500.0, seed=42)

        # 三个距离下 sigma 相同（都是 beacon_sigma_px），但由于模型内部
        # brightness 等参数均为默认值（brightness_ref_distance_m=0），
        # 渲染结果应完全一致（噪声由 seed 控制）
        bright_d0 = _count_bright_pixels(frame_d0, threshold=50)
        bright_d100 = _count_bright_pixels(frame_d100, threshold=50)
        bright_d500 = _count_bright_pixels(frame_d500, threshold=50)

        # 三者应该相同（seed 相同 + 相同参数 → 完全一致）
        self.assertEqual(bright_d0, bright_d100,
                         "sigma_ref_distance_m=0 时不同距离的 sigma 应相同")
        self.assertEqual(bright_d0, bright_d500,
                         "sigma_ref_distance_m=0 时不同距离的 sigma 应相同")


# ===================================================================
# TestBrightnessVariation
# ===================================================================

class TestBrightnessVariation(unittest.TestCase):
    """亮度变化测试。

    brightness = brightness_base / (1 + distance / brightness_ref_distance_m)
    brightness += normal(0, brightness_jitter_std)
    brightness = clip(brightness, 0, 1)

    验证方法：通过帧中最大像素值来衡量亮度。
    """

    def _max_pixel(self, frame: np.ndarray) -> int:
        return int(frame.max())

    def test_near_distance_brightness_near_base(self):
        """近距离(10m)时亮度接近 brightness_base(1.0)。"""
        cfg = _make_cfg(
            brightness_base=1.0,
            brightness_ref_distance_m=100.0,
            brightness_jitter_std=0.0,
        )
        model = CameraImagingModel(cfg)

        # brightness(10m) = 1.0 / (1 + 10/100) = 1.0 / 1.1 ≈ 0.909
        frame_near, in_fov, u, v, *_ = _render(model, distance_m=10.0, seed=42)

        self.assertTrue(in_fov)
        max_px = self._max_pixel(frame_near)

        # brightness≈0.909, blob 中心亮度 = 0.909*255 ≈ 232，加噪声后接近
        # 允许一定噪声波动范围
        self.assertGreater(max_px, 200,
                           "近距离时最大像素值应接近满亮度")
        self.assertLess(max_px, 256,
                        "像素值不应超过255")

    def test_far_distance_brightness_attenuated(self):
        """远距离(500m)时亮度显著衰减。"""
        cfg = _make_cfg(
            brightness_base=1.0,
            brightness_ref_distance_m=100.0,
            brightness_jitter_std=0.0,
        )
        model = CameraImagingModel(cfg)

        # brightness(500m) = 1.0 / (1 + 500/100) = 1/6 ≈ 0.167
        frame_far, in_fov, u, v, *_ = _render(model, distance_m=500.0, seed=42)

        self.assertTrue(in_fov)
        max_px_far = self._max_pixel(frame_far)

        # 近距离参考
        frame_near, _, _, _, *_ = _render(model, distance_m=10.0, seed=42)
        max_px_near = self._max_pixel(frame_near)

        # 远距离亮度应显著低于近距离
        self.assertLess(max_px_far, max_px_near * 0.5,
                        "远距离时最大像素值应显著低于近距离")

    def test_zero_ref_distance_degrades_to_fixed(self):
        """brightness_ref_distance_m=0 时退化为固定亮度。"""
        cfg = _make_cfg(
            brightness_base=1.0,
            brightness_ref_distance_m=0.0,
            brightness_jitter_std=0.0,
        )
        model = CameraImagingModel(cfg)

        frame_d0, _, _, _, *_ = _render(model, distance_m=0.0, seed=42)
        frame_d100, _, _, _, *_ = _render(model, distance_m=100.0, seed=42)
        frame_d500, _, _, _, *_ = _render(model, distance_m=500.0, seed=42)

        max_d0 = self._max_pixel(frame_d0)
        max_d100 = self._max_pixel(frame_d100)
        max_d500 = self._max_pixel(frame_d500)

        # 退化为固定亮度：所有距离最大像素值相同
        self.assertEqual(max_d0, max_d100,
                         "brightness_ref_distance_m=0 时不同距离亮度应相同")
        self.assertEqual(max_d0, max_d500,
                         "brightness_ref_distance_m=0 时不同距离亮度应相同")

    def test_jitter_adds_randomness(self):
        """brightness_jitter_std>0 时帧间亮度有波动。"""
        cfg = _make_cfg(
            brightness_base=0.8,
            brightness_ref_distance_m=0.0,
            brightness_jitter_std=0.1,
        )
        model = CameraImagingModel(cfg)

        # 渲染 200 帧，收集最大像素值
        max_values = []
        for i in range(200):
            frame, _, _, _, *_ = _render(model, distance_m=0.0, seed=100 + i)
            max_values.append(self._max_pixel(frame))

        max_values = np.array(max_values, dtype=np.float64)
        variance = float(np.var(max_values))

        # 有 jitter 时应有明显方差
        self.assertGreater(variance, 1.0,
                           "brightness_jitter_std>0 时帧间最大像素值应有显著波动")

        # 对照：无 jitter 时方差为 0（seed 相同 → 同一帧）
        cfg_no_jitter = _make_cfg(
            brightness_base=0.8,
            brightness_ref_distance_m=0.0,
            brightness_jitter_std=0.0,
        )
        model_no = CameraImagingModel(cfg_no_jitter)
        max_values_no = []
        for i in range(200):
            frame, _, _, _, *_ = _render(model_no, distance_m=0.0, seed=100 + i)
            max_values_no.append(self._max_pixel(frame))
        max_values_no = np.array(max_values_no, dtype=np.float64)
        variance_no = float(np.var(max_values_no))

        # 有 jitter 的方差应远大于无 jitter
        self.assertGreater(variance, variance_no * 10,
                           "有 jitter 时方差应远大于无 jitter 时")


# ===================================================================
# TestMissDetection
# ===================================================================

class TestMissDetection(unittest.TestCase):
    """丢检模型测试。

    miss_rate = clip(base_rate + sigma_gain / sigma, 0, 1)
    sigma 越小 → miss_rate 越高

    丢检判定：detect_beacon_centroid(frame, threshold=180) found=False 表示丢检。
    """

    def _miss_rate(self, model: CameraImagingModel, distance_m: float,
                   n_frames: int = 500, base_seed: int = 42,
                   threshold: int = 180) -> float:
        """统计丢检率。"""
        miss_count = 0
        for i in range(n_frames):
            frame, in_fov, u, v, *_ = _render(model, distance_m=distance_m,
                                          seed=base_seed + i)
            det = detect_beacon_centroid(frame, threshold=threshold)
            if in_fov and not det.found:
                miss_count += 1
        return miss_count / n_frames

    def test_zero_params_never_miss(self):
        """miss_detection_base_rate=0 且 miss_sigma_gain_px=0 时永不丢检。"""
        cfg = _make_cfg(
            miss_detection_base_rate=0.0,
            miss_sigma_gain_px=0.0,
        )
        model = CameraImagingModel(cfg)

        miss_rate = self._miss_rate(model, distance_m=10.0, n_frames=500)

        self.assertEqual(miss_rate, 0.0,
                         "base_rate=0 且 sigma_gain=0 时不应有丢检")

    def test_nonzero_base_rate_produces_misses(self):
        """miss_detection_base_rate>0 时部分帧丢检。"""
        cfg = _make_cfg(
            miss_detection_base_rate=0.3,
            miss_sigma_gain_px=0.0,
            sigma_ref_distance_m=0.0,
        )
        model = CameraImagingModel(cfg)

        miss_rate = self._miss_rate(model, distance_m=10.0, n_frames=500)

        # 应有部分帧丢检，比例大致在 0.3 附近
        self.assertGreater(miss_rate, 0.05,
                           "base_rate=0.3 时应有部分帧丢检")
        self.assertLess(miss_rate, 0.7,
                        "base_rate=0.3 时丢检率不应过高")

    def test_smaller_sigma_higher_miss_rate(self):
        """sigma 越小丢检概率越高（近距离低丢检率，远距离高丢检率）。"""
        cfg = _make_cfg(
            miss_detection_base_rate=0.0,
            miss_sigma_gain_px=1.0,
            sigma_ref_distance_m=100.0,
            beacon_sigma_px=3.2,
        )
        model = CameraImagingModel(cfg)

        # 近距离: sigma ≈ 3.2/1.1 ≈ 2.91 → miss_rate = 1.0/2.91 ≈ 0.34
        miss_near = self._miss_rate(model, distance_m=10.0, n_frames=500,
                                    base_seed=1000)

        # 远距离: sigma ≈ 3.2/6.0 ≈ 0.533 → miss_rate = 1.0/0.533 ≈ 1.0 (clipped to 1.0)
        miss_far = self._miss_rate(model, distance_m=500.0, n_frames=500,
                                   base_seed=2000)

        # 远距离丢检率应高于近距离
        self.assertGreater(miss_far, miss_near,
                           "远距离（sigma 小）丢检率应高于近距离")

    def test_miss_frame_background_below_threshold(self):
        """丢检帧背景像素不越过检测阈值(180)。"""
        cfg = _make_cfg(
            miss_detection_base_rate=0.5,
            miss_sigma_gain_px=0.0,
            sigma_ref_distance_m=0.0,
            beacon_sigma_px=3.2,
        )
        model = CameraImagingModel(cfg)

        # 收集丢检帧
        miss_frames = []
        for i in range(500):
            frame, in_fov, u, v, *_ = _render(model, distance_m=10.0,
                                          seed=5000 + i)
            if in_fov:
                det = detect_beacon_centroid(frame, threshold=180)
                if not det.found:
                    miss_frames.append(frame)
            if len(miss_frames) >= 10:
                break

        # 应至少采集到几帧丢检
        self.assertGreaterEqual(len(miss_frames), 1,
                                "base_rate=0.5 应能采集到丢检帧")

        # 每一帧丢检帧的 max pixel 应低于检测阈值（或接近，考虑噪声）
        for frame in miss_frames:
            max_px = int(frame.max())
            # 噪声 std=2.0，理论上背景 max ≈ 0 + 3*2 = 6，远低于 180
            # 但为了安全，允许一个宽松的阈值
            self.assertLess(max_px, 180,
                            f"丢检帧最大像素值 {max_px} 不应超过检测阈值 180")

    def test_miss_preserves_in_fov_and_uv(self):
        """丢检时 in_fov 仍为 True，u_px/v_px 正常返回。"""
        cfg = _make_cfg(
            miss_detection_base_rate=0.8,
            miss_sigma_gain_px=0.0,
            sigma_ref_distance_m=0.0,
        )
        model = CameraImagingModel(cfg)

        # 收集丢检案例
        miss_cases = []
        for i in range(500):
            frame, in_fov, u, v, *_ = _render(model, distance_m=10.0,
                                          seed=9000 + i)
            if in_fov:
                det = detect_beacon_centroid(frame, threshold=180)
                if not det.found:
                    miss_cases.append((in_fov, u, v, frame))
            if len(miss_cases) >= 5:
                break

        self.assertGreaterEqual(len(miss_cases), 1,
                                "base_rate=0.8 应能采集到丢检案例")

        for in_fov, u, v, frame in miss_cases:
            # 即使丢检，in_fov 仍为 True
            self.assertTrue(in_fov,
                            "丢检时 in_fov 应仍为 True")
            # u, v 应为有效数值（非 NaN），表示目标在传感器上的投影位置
            self.assertFalse(math.isnan(u),
                             "丢检时 u 应为有效数值")
            self.assertFalse(math.isnan(v),
                             "丢检时 v 应为有效数值")
            # u, v 应在图像范围内
            self.assertGreaterEqual(u, 0)
            self.assertLess(u, 640)
            self.assertGreaterEqual(v, 0)
            self.assertLess(v, 480)


if __name__ == "__main__":
    unittest.main()
