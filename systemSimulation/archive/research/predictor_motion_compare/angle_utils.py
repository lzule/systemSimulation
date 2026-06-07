"""角度域预测的共用工具。

提供像素 ↔ 世界角度的转换、yaw 解卷绕、yaw wrap 等基础函数。
仅供 research/predictor_motion_compare/ 下的角度域预测器使用，不影响正式源码。
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from runtime.types import wrap_pm180


def pixel_to_world_angle(
    cx_det: float,
    cy_det: float,
    cx_center: float,
    cy_center: float,
    f_px: float,
    gimbal_yaw_deg: float,
    gimbal_pitch_deg: float,
) -> tuple[float, float]:
    """像素坐标 + 当时云台角度 → 目标世界角度。

    时段 2 的核心计算。

    Args:
        cx_det, cy_det: 检测到的目标像素坐标。
        cx_center, cy_center: 主点（光轴投影点）像素坐标。
        f_px: 焦距（像素）。
        gimbal_yaw_deg: 拍图瞬间云台 yaw（含编码器噪声）。
        gimbal_pitch_deg: 拍图瞬间云台 pitch。

    Returns:
        (target_yaw_world_deg, target_pitch_world_deg)
        yaw 已经 wrap_pm180。
    """
    delta_yaw_in_image = math.degrees(math.atan2(cx_det - cx_center, f_px))
    delta_pitch_in_image = math.degrees(math.atan2(-(cy_det - cy_center), f_px))
    target_yaw_world = wrap_pm180(gimbal_yaw_deg + delta_yaw_in_image)
    target_pitch_world = gimbal_pitch_deg + delta_pitch_in_image
    return target_yaw_world, target_pitch_world


def world_angle_to_pixel(
    target_yaw_world_deg: float,
    target_pitch_world_deg: float,
    gimbal_yaw_deg: float,
    gimbal_pitch_deg: float,
    cx_center: float,
    cy_center: float,
    f_px: float,
) -> tuple[float, float]:
    """世界角度 + 云台角度 → 该云台坐标系下的像素位置。

    时段 4 的反投影。
    误差被压到 ±90° 之间，避免 tan 在边界附近爆炸。

    Args:
        target_yaw_world_deg, target_pitch_world_deg: 预测的目标世界角度。
        gimbal_yaw_deg, gimbal_pitch_deg: 云台角度（命令生效时刻的预估值）。
        cx_center, cy_center: 主点像素。
        f_px: 焦距像素。

    Returns:
        (pred_cx, pred_cy)
    """
    err_yaw_deg = wrap_pm180(target_yaw_world_deg - gimbal_yaw_deg)
    err_pitch_deg = target_pitch_world_deg - gimbal_pitch_deg

    err_yaw_clamped = max(-89.0, min(89.0, err_yaw_deg))
    err_pitch_clamped = max(-89.0, min(89.0, err_pitch_deg))

    pred_cx = cx_center + f_px * math.tan(math.radians(err_yaw_clamped))
    pred_cy = cy_center - f_px * math.tan(math.radians(err_pitch_clamped))
    return pred_cx, pred_cy


def gimbal_integrate(
    gimbal_yaw_deg: float,
    gimbal_pitch_deg: float,
    gimbal_yaw_rate_dps: float,
    gimbal_pitch_rate_dps: float,
    horizon_s: float,
) -> tuple[float, float]:
    """根据当前云台角度和角速度，匀速积分到 horizon_s 后的角度。

    时段 4 的云台外推：旧速率命令在 horizon_s 内未变，云台匀速运动。
    """
    yaw = wrap_pm180(gimbal_yaw_deg + gimbal_yaw_rate_dps * horizon_s)
    pitch = gimbal_pitch_deg + gimbal_pitch_rate_dps * horizon_s
    return yaw, pitch


def unwrap_yaw_series(yaw_deg_series: np.ndarray) -> np.ndarray:
    """对 yaw 角序列做解卷绕，避免 ±180 跳变破坏拟合。"""
    if yaw_deg_series.size == 0:
        return yaw_deg_series
    return np.degrees(np.unwrap(np.radians(yaw_deg_series)))
