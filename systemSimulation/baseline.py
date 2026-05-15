"""研究基线配置快照。

Phase 0 冻结的配置默认值，用于后续实验的回归对比。
当 config.py 中的默认值发生变化时，validate_baseline() 会报告偏离。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class BaselineConfig:
    """Phase 0 冻结的基线配置值。与 config.py 默认值一一对应。"""

    # TargetConfig
    target_motion_type: str = "sinusoidal"
    target_initial_x_m: float = 100.0
    target_initial_y_m: float = 0.0
    target_velocity_x_mps: float = 0.0
    target_velocity_y_mps: float = 1.5
    target_accel_x_mps2: float = 0.0
    target_accel_y_mps2: float = 0.3
    target_sin_amplitude_m: float = 15.0
    target_sin_frequency_hz: float = 0.2
    target_random_max_accel_mps2: float = 1.0
    target_random_damping: float = 0.98
    target_random_seed: int = 42
    target_waypoint_arrival_radius_m: float = 1.0

    # GimbalConfig
    gimbal_angle_min_deg: float = -90.0
    gimbal_angle_max_deg: float = 90.0
    gimbal_max_velocity_dps: float = 60.0
    gimbal_response_tau_s: float = 0.03
    gimbal_initial_angle_deg: float = 0.0
    gimbal_boot_delay_s: float = 1.5

    # AxisLimitConfig
    axis_pitch_min_deg: float = -135.0
    axis_pitch_max_deg: float = 90.0
    axis_max_rate_dps: float = 60.0

    # LoopConfig
    loop_angle_loop_hz: float = 50.0
    loop_rate_loop_hz: float = 200.0

    # ControlPreset
    ctrl_angle_kp_yaw: float = 14.0
    ctrl_angle_kp_pitch: float = 14.0
    ctrl_rate_kp_yaw: float = 1.6
    ctrl_rate_ki_yaw: float = 5.0
    ctrl_rate_kp_pitch: float = 1.6
    ctrl_rate_ki_pitch: float = 5.0
    ctrl_rate_integral_limit: float = 30.0
    ctrl_actuator_cmd_limit_dps: float = 60.0

    # CameraConfig
    cam_resolution_w: int = 640
    cam_resolution_h: int = 480
    cam_sensor_w_mm: float = 4.8
    cam_sensor_h_mm: float = 3.6
    cam_focal_length_mm: float = 12.0
    cam_focal_min_mm: float = 4.4
    cam_focal_max_mm: float = 200.0
    cam_boot_delay_s: float = 0.5
    cam_beacon_sigma_px: float = 3.2
    cam_detection_threshold: int = 180

    # RaspiConfig
    raspi_boot_delay_s: float = 1.0

    # RaspiDelayConfig
    raspi_image_read_delay_s: float = 0.005
    raspi_image_process_delay_s: float = 0.015
    raspi_state_read_delay_s: float = 0.003
    raspi_command_tx_delay_s: float = 0.003
    raspi_jitter_std_s: float = 0.001

    # TrackerTuningConfig
    tracker_yaw_rate_kp: float = 1.1
    tracker_max_yaw_rate_dps: float = 60.0
    tracker_deadband_px: float = 2.0
    tracker_lost_target_hold_rate_dps: float = 0.0
    tracker_enable_zoom_control: bool = False
    tracker_zoom_in_error_px: float = 40.0
    tracker_zoom_out_error_px: float = 120.0
    tracker_zoom_step_mm: float = 1.0
    tracker_zoom_cooldown_s: float = 0.15

    # YawDisplayConfig
    yaw_display_default_mode: str = "0_360"

    # SceneConfig
    scene_duration_s: float = 20.0
    scene_dt_s: float = 0.005
    scene_pixel_noise_std: float = 2.0

    # 基线实验条件
    baseline_delay_ms: float = 0.0
    baseline_duration_s: float = 20.0
    baseline_seed: int = 42


_BASELINE = BaselineConfig()


def get_baseline_config() -> BaselineConfig:
    """返回冻结的基线配置。"""
    return _BASELINE


def validate_baseline() -> list[str]:
    """对比当前 config.py 默认值与冻结基线，返回偏离项列表。

    Returns:
        偏离描述列表。空列表表示无偏离。
    """
    from config import (
        AxisLimitConfig,
        CameraConfig,
        ControlPreset,
        GimbalConfig,
        LoopConfig,
        RaspiConfig,
        RaspiDelayConfig,
        SceneConfig,
        TargetConfig,
        TrackerTuningConfig,
        YawDisplayConfig,
    )

    deviations: list[str] = []

    cfg_map = {
        "target": (TargetConfig(), {
            "motion_type": "target_motion_type",
            "initial_x_m": "target_initial_x_m",
            "initial_y_m": "target_initial_y_m",
            "velocity_x_mps": "target_velocity_x_mps",
            "velocity_y_mps": "target_velocity_y_mps",
            "accel_x_mps2": "target_accel_x_mps2",
            "accel_y_mps2": "target_accel_y_mps2",
            "sin_amplitude_m": "target_sin_amplitude_m",
            "sin_frequency_hz": "target_sin_frequency_hz",
            "random_max_accel_mps2": "target_random_max_accel_mps2",
            "random_damping": "target_random_damping",
            "random_seed": "target_random_seed",
            "waypoint_arrival_radius_m": "target_waypoint_arrival_radius_m",
        }),
        "gimbal": (GimbalConfig(), {
            "angle_min_deg": "gimbal_angle_min_deg",
            "angle_max_deg": "gimbal_angle_max_deg",
            "max_velocity_dps": "gimbal_max_velocity_dps",
            "response_tau_s": "gimbal_response_tau_s",
            "initial_angle_deg": "gimbal_initial_angle_deg",
            "boot_delay_s": "gimbal_boot_delay_s",
        }),
        "axis": (AxisLimitConfig(), {
            "pitch_min_deg": "axis_pitch_min_deg",
            "pitch_max_deg": "axis_pitch_max_deg",
            "max_rate_dps": "axis_max_rate_dps",
        }),
        "loop": (LoopConfig(), {
            "angle_loop_hz": "loop_angle_loop_hz",
            "rate_loop_hz": "loop_rate_loop_hz",
        }),
        "ctrl": (ControlPreset(), {
            "angle_kp_yaw": "ctrl_angle_kp_yaw",
            "angle_kp_pitch": "ctrl_angle_kp_pitch",
            "rate_kp_yaw": "ctrl_rate_kp_yaw",
            "rate_ki_yaw": "ctrl_rate_ki_yaw",
            "rate_kp_pitch": "ctrl_rate_kp_pitch",
            "rate_ki_pitch": "ctrl_rate_ki_pitch",
            "rate_integral_limit": "ctrl_rate_integral_limit",
            "actuator_cmd_limit_dps": "ctrl_actuator_cmd_limit_dps",
        }),
        "camera": (CameraConfig(), {
            "resolution_w": "cam_resolution_w",
            "resolution_h": "cam_resolution_h",
            "sensor_w_mm": "cam_sensor_w_mm",
            "sensor_h_mm": "cam_sensor_h_mm",
            "focal_length_mm": "cam_focal_length_mm",
            "focal_min_mm": "cam_focal_min_mm",
            "focal_max_mm": "cam_focal_max_mm",
            "boot_delay_s": "cam_boot_delay_s",
            "beacon_sigma_px": "cam_beacon_sigma_px",
            "detection_threshold": "cam_detection_threshold",
        }),
        "raspi": (RaspiConfig(), {
            "boot_delay_s": "raspi_boot_delay_s",
        }),
        "raspi_delay": (RaspiDelayConfig(), {
            "image_read_delay_s": "raspi_image_read_delay_s",
            "image_process_delay_s": "raspi_image_process_delay_s",
            "state_read_delay_s": "raspi_state_read_delay_s",
            "command_tx_delay_s": "raspi_command_tx_delay_s",
            "jitter_std_s": "raspi_jitter_std_s",
        }),
        "tracker": (TrackerTuningConfig(), {
            "yaw_rate_kp_dps_per_px": "tracker_yaw_rate_kp",
            "max_yaw_rate_dps": "tracker_max_yaw_rate_dps",
            "deadband_px": "tracker_deadband_px",
            "lost_target_hold_rate_dps": "tracker_lost_target_hold_rate_dps",
            "enable_zoom_control": "tracker_enable_zoom_control",
            "zoom_in_error_px": "tracker_zoom_in_error_px",
            "zoom_out_error_px": "tracker_zoom_out_error_px",
            "zoom_step_mm": "tracker_zoom_step_mm",
            "zoom_cooldown_s": "tracker_zoom_cooldown_s",
        }),
        "yaw_display": (YawDisplayConfig(), {
            "default_mode": "yaw_display_default_mode",
        }),
        "scene": (SceneConfig(), {
            "duration_s": "scene_duration_s",
            "dt_s": "scene_dt_s",
            "pixel_noise_std": "scene_pixel_noise_std",
        }),
    }

    for group_name, (cfg_obj, field_map) in cfg_map.items():
        for cfg_field, baseline_field in field_map.items():
            current_val = getattr(cfg_obj, cfg_field)
            baseline_val = getattr(_BASELINE, baseline_field)
            if current_val != baseline_val:
                deviations.append(
                    f"{group_name}.{cfg_field}: 当前={current_val}, 基线={baseline_val}"
                )

    return deviations


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    devs = validate_baseline()
    if devs:
        print(f"[Baseline] {len(devs)} deviation(s) detected:")
        for d in devs:
            print(f"  - {d}")
    else:
        print("[Baseline] OK - current config matches frozen baseline.")
