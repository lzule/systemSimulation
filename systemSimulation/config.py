from dataclasses import dataclass
import math
from typing import Literal


@dataclass
class CameraConfig:
    resolution_w: int = 640
    resolution_h: int = 480
    sensor_w_mm: float = 4.8
    sensor_h_mm: float = 3.6
    focal_length_mm: float = 12.0
    focal_min_mm: float = 4.4
    focal_max_mm: float = 200.0
    boot_delay_s: float = 0.5
    beacon_sigma_px: float = 3.2
    detection_threshold: int = 180

    @property
    def pixel_size_mm(self) -> float:
        return self.sensor_w_mm / self.resolution_w

    @property
    def focal_length_px(self) -> float:
        return self.focal_length_mm / self.pixel_size_mm

    @property
    def fov_h_deg(self) -> float:
        return 2.0 * math.degrees(math.atan(self.sensor_w_mm / (2.0 * self.focal_length_mm)))

    @property
    def fov_v_deg(self) -> float:
        return 2.0 * math.degrees(math.atan(self.sensor_h_mm / (2.0 * self.focal_length_mm)))

    @property
    def cx(self) -> float:
        return self.resolution_w / 2.0

    @property
    def px_per_deg(self) -> float:
        return self.focal_length_px * (math.pi / 180.0)


@dataclass
class GimbalConfig:
    angle_min_deg: float = -90.0
    angle_max_deg: float = 90.0
    max_velocity_dps: float = 60.0
    response_tau_s: float = 0.03
    initial_angle_deg: float = 0.0
    boot_delay_s: float = 1.5


@dataclass
class AxisLimitConfig:
    pitch_min_deg: float = -135.0
    pitch_max_deg: float = 90.0
    max_rate_dps: float = 60.0


@dataclass
class LoopConfig:
    angle_loop_hz: float = 50.0
    rate_loop_hz: float = 200.0


@dataclass
class ControlPreset:
    angle_kp_yaw: float = 14.0
    angle_kp_pitch: float = 14.0
    rate_kp_yaw: float = 1.6
    rate_ki_yaw: float = 5.0
    rate_kp_pitch: float = 1.6
    rate_ki_pitch: float = 5.0
    rate_integral_limit: float = 30.0
    actuator_cmd_limit_dps: float = 60.0


@dataclass
class YawDisplayConfig:
    default_mode: Literal["0_360", "pm180"] = "0_360"


@dataclass
class RaspiConfig:
    boot_delay_s: float = 1.0
    enabled: bool = True


@dataclass
class RaspiDelayConfig:
    image_read_delay_s: float = 0.005
    image_process_delay_s: float = 0.015
    state_read_delay_s: float = 0.003
    command_tx_delay_s: float = 0.003
    jitter_std_s: float = 0.001


@dataclass
class TrackerTuningConfig:
    yaw_rate_kp_dps_per_px: float = 1.1
    max_yaw_rate_dps: float = 60.0
    deadband_px: float = 2.0
    lost_target_hold_rate_dps: float = 0.0

    pitch_rate_kp_dps_per_px: float = 1.1
    max_pitch_rate_dps: float = 60.0
    deadband_v_px: float = 2.0

    enable_zoom_control: bool = False
    zoom_in_error_px: float = 40.0
    zoom_out_error_px: float = 120.0
    zoom_step_mm: float = 1.0
    zoom_cooldown_s: float = 0.15


@dataclass
class TargetConfig:
    motion_type: Literal["sinusoidal", "constant_velocity", "constant_accel", "random_walk", "waypoint"] = "sinusoidal"
    initial_x_m: float = 100.0
    initial_y_m: float = 0.0
    initial_z_m: float = 0.0

    velocity_x_mps: float = 0.0
    velocity_y_mps: float = 1.5
    velocity_z_mps: float = 0.0

    accel_x_mps2: float = 0.0
    accel_y_mps2: float = 0.3
    accel_z_mps2: float = 0.0

    sin_amplitude_m: float = 15.0
    sin_frequency_hz: float = 0.2
    sin_z_amplitude_m: float = 0.0
    sin_z_frequency_hz: float = 0.0

    random_max_accel_mps2: float = 1.0
    random_damping: float = 0.98
    random_seed: int = 42

    waypoints: list[tuple[float, ...]] = None  # [(x, y, z, speed), ...], 兼容 (x, y, speed); speed=0 表示悬停
    waypoint_arrival_radius_m: float = 1.0


# 模式 → 该模式专属参数字段（initial_x_m/initial_y_m/initial_z_m 为公共字段，不在此列）
# 添加新运动模式：1) 在 Literal 中加模式名  2) 在此加字段映射  3) 在 TargetKinematics3D 实现逻辑
MOTION_MODE_PARAMS: dict[str, list[str]] = {
    "sinusoidal": ["sin_amplitude_m", "sin_frequency_hz", "sin_z_amplitude_m", "sin_z_frequency_hz"],
    "constant_velocity": ["velocity_x_mps", "velocity_y_mps", "velocity_z_mps"],
    "constant_accel": ["velocity_x_mps", "velocity_y_mps", "velocity_z_mps", "accel_x_mps2", "accel_y_mps2", "accel_z_mps2"],
    "random_walk": ["random_max_accel_mps2", "random_damping", "random_seed"],
    "waypoint": ["waypoints", "waypoint_arrival_radius_m"],
}


@dataclass
class SceneConfig:
    duration_s: float = 20.0
    dt_s: float = 0.005

    anim_fps: int = 30
    gif_fps: int = 15

    trail_length_s: float = 4.0
    plot_window_s: float = 5.0
    world_view_range_m: float = 150.0

    pixel_noise_std: float = 2.0


camera_cfg = CameraConfig()
gimbal_cfg = GimbalConfig()
axis_limit_cfg = AxisLimitConfig()
loop_cfg = LoopConfig()
control_preset_cfg = ControlPreset()
yaw_display_cfg = YawDisplayConfig()
raspi_cfg = RaspiConfig()
raspi_delay_cfg = RaspiDelayConfig()
tracker_tuning_cfg = TrackerTuningConfig()
target_cfg = TargetConfig()
scene_cfg = SceneConfig()
