"""无 GUI 联调入口。"""

from __future__ import annotations

import re
import time

from simulation.bootstrap import build_runtime, load_control_program_from_path
from simulation.types import AppConfig


def apply_target_overrides(cfg: AppConfig) -> None:
    """根据 AppConfig 覆盖目标运动配置（公共接口，GUI 和 headless 共用）。"""
    if cfg.target_type or cfg.waypoints:
        from config import target_cfg
        if cfg.target_type:
            target_cfg.motion_type = cfg.target_type
        if cfg.waypoints:
            target_cfg.motion_type = "waypoint"
            target_cfg.waypoints = _parse_waypoints(cfg.waypoints)


def _parse_waypoints(waypoints_str: str) -> list[tuple[float, ...]]:
    """解析航点字符串，格式: "(x1,y1,z1,s1)" 或 "(x1,y1,s1)"（z 缺省为 0）。"""
    points = []
    for match in re.finditer(r'\(\s*([\d.\-]+)\s*,\s*([\d.\-]+)\s*(?:,\s*([\d.\-]+)\s*)?(?:,\s*([\d.\-]+)\s*)?\)', waypoints_str):
        vals = [float(match.group(i)) for i in range(1, 5) if match.group(i) is not None]
        if len(vals) == 3:
            # 旧格式 (x, y, speed)
            points.append((vals[0], vals[1], vals[2]))
        elif len(vals) == 4:
            # 新格式 (x, y, z, speed)
            points.append((vals[0], vals[1], vals[2], vals[3]))
        else:
            raise ValueError(f"航点格式错误，需要 (x,y,speed) 或 (x,y,z,speed)，得到 {len(vals)} 个值: {match.group(0)}")
    if not points:
        raise ValueError(f"无法解析航点字符串: {waypoints_str}")
    return points


def _resolve_control_program(cfg: AppConfig):
    """根据 AppConfig 解析控制程序实例。"""
    if not cfg.control_program_path:
        return None
    return load_control_program_from_path(cfg.control_program_path)


def run_headless_session(cfg: AppConfig) -> None:
    """无 GUI 模式：用于自动化验证。"""
    apply_target_overrides(cfg)
    control_program = _resolve_control_program(cfg)
    runtime = build_runtime(delay_ms=cfg.delay_ms, control_program=control_program, obs_mode=cfg.obs_mode)
    n_steps = max(1, int(cfg.duration_s / runtime.dt_s))
    print(f"[app/headless] mode={cfg.mode}, duration={cfg.duration_s:.2f}s, dt={runtime.dt_s:.4f}, steps={n_steps}")

    if cfg.mode == "offline":
        for idx in range(n_steps):
            snapshot = runtime.step(1)
            if idx % max(1, int(0.2 / runtime.dt_s)) == 0:
                print(
                    f"t={snapshot.timestamp:6.2f}s yaw={snapshot.gimbal['yaw_deg_display']:7.2f} "
                    f"pitch={snapshot.gimbal['pitch_deg']:6.2f} u={snapshot.camera['u_px']:8.2f} "
                    f"in_fov={int(bool(snapshot.camera['in_fov']))} backlog={snapshot.raspi['pipeline_backlog_len']}"
                )
        return

    t_end = time.time() + cfg.duration_s
    while time.time() < t_end:
        snapshot = runtime.step(1)
        print(
            f"\rt={snapshot.timestamp:6.2f}s yaw={snapshot.gimbal['yaw_deg_display']:7.2f} "
            f"pitch={snapshot.gimbal['pitch_deg']:6.2f} frame={snapshot.camera['frame_id']:5d} "
            f"in_fov={int(bool(snapshot.camera['in_fov']))}",
            end="",
            flush=True,
        )
        time.sleep(runtime.dt_s)
    print()
