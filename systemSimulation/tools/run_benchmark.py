"""Benchmark 运行工具 — 支持多算法、多场景、多种子的统一评测。

用法:
    # 运行全部默认配置
    conda run -n simulation python tools/run_benchmark.py

    # 指定算法和场景
    conda run -n simulation python tools/run_benchmark.py --algorithms baseline_rate_p rate_pi --scenarios B1 B2 --seeds 42 123

    # 指定观测模式
    conda run -n simulation python tools/run_benchmark.py --obs-modes research realistic

    # 自定义时长和输出目录
    conda run -n simulation python tools/run_benchmark.py --duration 10.0 --output-dir output/my_experiments

输出目录结构:
    output/experiments/<scenario_id>/<condition_id>/<algorithm_name>/<experiment_id>/
    每个 experiment_id 目录包含: result.json, metrics.csv, notes.md, error_curve.png, state_timeline.png
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import numpy as np

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 场景参数映射
# ============================================================

@dataclass
class ScenarioConfig:
    """单个 benchmark 场景的完整参数配置。"""
    scenario_id: str          # 场景组 ID，如 S2, S3
    condition_id: str         # 条件 ID，如 B1, B2, B3
    target_type: str = "sinusoidal"
    initial_x_m: float = 100.0
    initial_y_m: float = 0.0
    initial_z_m: float = 0.0
    sin_amplitude_m: float = 15.0
    sin_frequency_hz: float = 0.2
    sin_z_amplitude_m: float = 0.0
    sin_z_frequency_hz: float = 0.0
    delay_ms: float = 0.0
    description: str = ""


# 固定场景定义
SCENARIOS: dict[str, ScenarioConfig] = {
    "B1": ScenarioConfig(
        scenario_id="S2",
        condition_id="B1",
        target_type="sinusoidal",
        initial_x_m=100.0,
        sin_amplitude_m=15.0,
        sin_frequency_hz=0.2,
        delay_ms=0.0,
        description="S2-D2-V2-W2-M2-O0-L0-P1（sinusoidal x=100m, 基线对照）",
    ),
    "B2": ScenarioConfig(
        scenario_id="S2",
        condition_id="B2",
        target_type="sinusoidal",
        initial_x_m=100.0,
        sin_amplitude_m=15.0,
        sin_frequency_hz=0.2,
        delay_ms=26.0,   # L1 延时档位：image_read=6.5ms, image_process=13ms, state_read/command_tx 各 3.25ms
        description="S2-D2-V2-W2-M2-O0-L1-P1（轻非理想验证, 延时 L1）",
    ),
    "B3": ScenarioConfig(
        scenario_id="S3",
        condition_id="B3",
        target_type="sinusoidal",
        initial_x_m=80.0,
        sin_amplitude_m=20.0,
        sin_frequency_hz=0.3,
        delay_ms=52.0,   # L2 延时档位：image_read=13ms, image_process=26ms, state_read/command_tx 各 6.5ms
        description="S3-D3-V3-W3-M2-O0-L2-P2（中难度比较）",
    ),
}


# ============================================================
# 算法注册表
# ============================================================

def _create_baseline_rate_p():
    """创建基线速率P控制器（BaselineTrackerProgram）。"""
    from entities.raspi.tracker_program import BaselineTrackerProgram
    return BaselineTrackerProgram()


def _create_atp_search_track_baseline():
    """创建 ATP 状态机 + 速率P跟踪（AtpControlProgram + RatePTracker）。"""
    from entities.raspi.atp_control_program import AtpControlProgram
    from entities.raspi.trackers.rate_p_tracker import RatePTracker
    return AtpControlProgram(tracker=RatePTracker())


def _create_rate_pi():
    """创建速率PI控制器（AtpControlProgram + RatePITracker）。

    RatePITracker 尚未由 Agent 2 实现时，退化为 RatePTracker。
    """
    try:
        from entities.raspi.atp_control_program import AtpControlProgram
        from entities.raspi.trackers.rate_pi_tracker import RatePITracker
        return AtpControlProgram(tracker=RatePITracker())
    except ImportError:
        # Agent 2 尚未实现，退化
        print("  [警告] RatePITracker 尚未实现，退化为 RatePTracker")
        return _create_atp_search_track_baseline()


def _create_alpha_beta_tracker():
    """创建 Alpha-Beta 预测器 + 速率P跟踪器。"""
    try:
        from entities.raspi.atp_control_program import AtpControlProgram
        from entities.raspi.trackers.rate_p_tracker import RatePTracker
        from entities.raspi.predictors.alpha_beta import AlphaBetaFilter
        return AtpControlProgram(tracker=RatePTracker(), predictor=AlphaBetaFilter())
    except ImportError:
        print("  [警告] AlphaBetaFilter 不可用，退化为 atp_search_track_baseline")
        return _create_atp_search_track_baseline()


def _create_linear_kf_tracker():
    """创建线性卡尔曼滤波预测器 + 速率P跟踪器。

    LinearKF 尚未由 Agent 3 实现时，退化为 Alpha-Beta。
    """
    try:
        from entities.raspi.atp_control_program import AtpControlProgram
        from entities.raspi.trackers.rate_p_tracker import RatePTracker
        from entities.raspi.predictors.linear_kf import LinearKF
        return AtpControlProgram(tracker=RatePTracker(), predictor=LinearKF())
    except ImportError:
        print("  [警告] LinearKF 尚未实现，退化为 AlphaBeta")
        return _create_alpha_beta_tracker()


class AngleModeControlProgram:
    """AngleModeTracker 的 ControlProgram 包装。

    AngleModeTracker 实现的是 Tracker 协议（compute_commands），
    不能直接通过 AtpControlProgram 使用（因为 ATP 强制 RATE_MODE）。
    本包装类直接实现 on_tick 协议，内部调用 AngleModeTracker。
    仅适用于 realistic/debug 模式。
    """

    def __init__(self):
        from entities.raspi.trackers.angle_mode_tracker import AngleModeTracker
        self._tracker = AngleModeTracker()
        self.last_detection_found: bool = False
        self.last_yaw_rate_cmd_dps: float = 0.0
        self.last_pitch_rate_cmd_dps: float = 0.0

    def on_tick(self, obs: dict) -> list:
        from entities.raspi.atp_state_machine import AtpState
        commands = self._tracker.compute_commands(obs, AtpState.TRACK_COARSE, None)
        self.last_detection_found = self._tracker.last_detection_found
        # angle mode 没有速率命令，记录角度命令对应的等效速率供采集
        for cmd in reversed(commands):
            if cmd.action == "set_angle_target" and cmd.payload:
                # 标记为特殊值以便区分
                self.last_yaw_rate_cmd_dps = float("nan")
                self.last_pitch_rate_cmd_dps = float("nan")
                break
        return commands


def _create_angle_mode_realistic():
    """创建角度模式控制器（仅 realistic/debug 模式可用）。"""
    try:
        return AngleModeControlProgram()
    except ImportError:
        print("  [警告] AngleModeTracker 不可用，退化为 baseline_rate_p")
        return _create_baseline_rate_p()


# 算法注册表：名称 -> 工厂函数
ALGORITHM_REGISTRY: dict[str, Callable[[], Any]] = {
    "baseline_rate_p": _create_baseline_rate_p,
    "rate_pi": _create_rate_pi,
    "alpha_beta_tracker": _create_alpha_beta_tracker,
    "linear_kf_tracker": _create_linear_kf_tracker,
    "atp_search_track_baseline": _create_atp_search_track_baseline,
    "angle_mode_realistic": _create_angle_mode_realistic,
}

# 算法版本号（手动维护）
ALGORITHM_VERSIONS: dict[str, str] = {
    "baseline_rate_p": "1.0",
    "rate_pi": "1.0",
    "alpha_beta_tracker": "1.0",
    "linear_kf_tracker": "1.0",
    "atp_search_track_baseline": "1.0",
    "angle_mode_realistic": "1.0",
}

# 算法适用的观测模式（用于参数校验提示）
ALGORITHM_OBS_MODES: dict[str, list[str]] = {
    "baseline_rate_p": ["research", "realistic", "debug"],
    "rate_pi": ["research", "realistic", "debug"],
    "alpha_beta_tracker": ["research", "realistic", "debug"],
    "linear_kf_tracker": ["research", "realistic", "debug"],
    "atp_search_track_baseline": ["research", "realistic", "debug"],
    "angle_mode_realistic": ["realistic", "debug"],
}


def is_obs_mode_allowed(algorithm_name: str, obs_mode: str) -> bool:
    """判断算法是否允许在指定观测模式下运行。"""
    allowed = ALGORITHM_OBS_MODES.get(algorithm_name)
    if not allowed:
        return True
    return obs_mode in allowed


# ============================================================
# 帧级数据采集器
# ============================================================

@dataclass
class FrameRecord:
    """单帧采集数据。"""
    timestamp: float
    pixel_error_x: float
    pixel_error_y: float
    pixel_error_total: float
    detection_found: bool
    atp_state: str
    yaw_rate_cmd: float
    pitch_rate_cmd: float
    in_fov: bool
    yaw_deg: float
    pitch_deg: float
    u_px: float
    v_px: float


class FrameCollector:
    """帧级数据采集器，在每个 tick 采集关键指标。"""

    def __init__(self):
        self.records: list[FrameRecord] = []

    def collect(
        self,
        snapshot,
        control_program: Any,
        cx: float,
        cy: float,
    ) -> None:
        """从 WorldSnapshot 和控制程序中采集一帧数据。

        Args:
            snapshot: WorldSnapshot 实例。
            control_program: 当前控制程序实例。
            cx: 画面中心 x 坐标。
            cy: 画面中心 y 坐标。
        """
        in_fov = bool(snapshot.camera.get("in_fov", False))
        u_px = float(snapshot.camera.get("u_px", float("nan")))
        v_px = float(snapshot.camera.get("v_px", float("nan")))

        # 从真值计算像素误差（debug/research 模式下可用）
        if in_fov and math.isfinite(u_px) and math.isfinite(v_px):
            pixel_error_x = u_px - cx
            pixel_error_y = cy - v_px
            pixel_error_total = math.sqrt(pixel_error_x ** 2 + pixel_error_y ** 2)
        else:
            pixel_error_x = float("nan")
            pixel_error_y = float("nan")
            pixel_error_total = float("nan")

        # 从控制程序提取命令信息
        detection_found = False
        yaw_rate_cmd = 0.0
        pitch_rate_cmd = 0.0
        atp_state = "N/A"

        if hasattr(control_program, "last_detection_found"):
            detection_found = control_program.last_detection_found
        if hasattr(control_program, "last_yaw_rate_cmd_dps"):
            yaw_rate_cmd = control_program.last_yaw_rate_cmd_dps
        if hasattr(control_program, "last_pitch_rate_cmd_dps"):
            pitch_rate_cmd = control_program.last_pitch_rate_cmd_dps
        if hasattr(control_program, "state_machine"):
            atp_state = str(control_program.state_machine.state.value)
        elif hasattr(control_program, "tracker") and hasattr(control_program.tracker, "last_detection_found"):
            detection_found = control_program.tracker.last_detection_found

        self.records.append(FrameRecord(
            timestamp=float(snapshot.timestamp),
            pixel_error_x=pixel_error_x,
            pixel_error_y=pixel_error_y,
            pixel_error_total=pixel_error_total,
            detection_found=detection_found,
            atp_state=atp_state,
            yaw_rate_cmd=yaw_rate_cmd,
            pitch_rate_cmd=pitch_rate_cmd,
            in_fov=in_fov,
            yaw_deg=float(snapshot.gimbal.get("yaw_deg_internal", 0.0)),
            pitch_deg=float(snapshot.gimbal.get("pitch_deg", 0.0)),
            u_px=u_px,
            v_px=v_px,
        ))


# ============================================================
# 指标计算
# ============================================================

def compute_metrics(records: list[FrameRecord], duration_s: float) -> dict:
    """从帧级数据计算汇总指标。

    Args:
        records: 帧级数据列表。
        duration_s: 仿真总时长。

    Returns:
        指标字典，包含 metrics 和 atp_metrics。
    """
    if not records:
        return {
            "metrics": _empty_metrics(),
            "atp_metrics": _empty_atp_metrics(),
        }

    n_total = len(records)
    timestamps = np.array([r.timestamp for r in records])
    in_fov_flags = np.array([r.in_fov for r in records])
    detection_flags = np.array([r.detection_found for r in records])
    pixel_errors = np.array([r.pixel_error_total for r in records], dtype=float)
    pixel_error_x = np.array([r.pixel_error_x for r in records], dtype=float)
    pixel_error_y = np.array([r.pixel_error_y for r in records], dtype=float)

    # 丢弃 boot 阶段（前 3 秒）后计算稳态指标
    stable_mask = (timestamps >= 3.0) & in_fov_flags & np.isfinite(pixel_errors)
    stable_errors = pixel_errors[stable_mask]
    stable_err_x = pixel_error_x[stable_mask]
    stable_err_y = pixel_error_y[stable_mask]

    # 捕获成功率：稳态期间 in_fov 的比例
    stable_in_fov = in_fov_flags[timestamps >= 3.0]
    capture_success_rate = float(stable_in_fov.sum() / max(1, len(stable_in_fov)))

    # 平均/最大像素误差
    mean_tracking_error_px = float(np.nanmean(stable_errors)) if len(stable_errors) > 0 else float("nan")
    max_tracking_error_px = float(np.nanmax(stable_errors)) if len(stable_errors) > 0 else float("nan")
    rms_pixel_error = float(np.sqrt(np.nanmean(stable_errors ** 2))) if len(stable_errors) > 0 else float("nan")

    # 丢锁统计：连续 in_fov=True 后出现 in_fov=False 的次数
    lock_loss_count = 0
    was_tracking = False
    for i in range(n_total):
        if timestamps[i] < 3.0:
            continue
        if in_fov_flags[i] and not was_tracking:
            was_tracking = True
        elif not in_fov_flags[i] and was_tracking:
            lock_loss_count += 1
            was_tracking = False

    # ATP 状态序列（供重捕获指标使用）
    atp_states = [r.atp_state for r in records]

    # 丢锁率：丢锁次数 / 仿真时长
    lock_loss_rate = lock_loss_count / max(duration_s, 1e-6)

    # 平均收敛时间：从 in_fov=False 到 in_fov=True 且 pixel_error < 50px 的平均耗时
    settling_times = []
    search_start = None
    for i in range(n_total):
        if timestamps[i] < 3.0:
            continue
        if not in_fov_flags[i] and search_start is None:
            search_start = timestamps[i]
        elif in_fov_flags[i] and search_start is not None:
            if np.isfinite(pixel_errors[i]) and pixel_errors[i] < 50.0:
                settling_times.append(timestamps[i] - search_start)
                search_start = None
    mean_settling_time_s = float(np.mean(settling_times)) if settling_times else float("nan")

    # 跟踪效率：稳态期间误差 < 30px 的帧比例
    if len(stable_errors) > 0:
        tracking_efficiency = float((stable_errors < 30.0).sum() / len(stable_errors))
    else:
        tracking_efficiency = 0.0

    # 重捕获时间：LOST/REACQUIRE→ACQUIRE/TRACK 的平均耗时
    reacquire_times = []
    reacquire_attempts = 0
    reacquire_successes = 0
    reacquire_start = None
    for i in range(n_total):
        if timestamps[i] < 3.0:
            continue
        s = atp_states[i] if i < len(atp_states) else "N/A"
        if s in ("LOST", "REACQUIRE") and reacquire_start is None:
            reacquire_start = timestamps[i]
            reacquire_attempts += 1
        elif s in ("ACQUIRE", "TRACK_COARSE", "TRACK_FINE") and reacquire_start is not None:
            reacquire_times.append(timestamps[i] - reacquire_start)
            reacquire_successes += 1
            reacquire_start = None
    reacquire_time_s = float(np.mean(reacquire_times)) if reacquire_times else float("nan")
    reacquire_success_rate = reacquire_successes / max(reacquire_attempts, 1)

    metrics = {
        "capture_success_rate": round(capture_success_rate, 4),
        "mean_tracking_error_px": round(mean_tracking_error_px, 2) if math.isfinite(mean_tracking_error_px) else None,
        "max_tracking_error_px": round(max_tracking_error_px, 2) if math.isfinite(max_tracking_error_px) else None,
        "lock_loss_count": lock_loss_count,
        "lock_loss_rate": round(lock_loss_rate, 4),
        "reacquire_time_s": round(reacquire_time_s, 2) if math.isfinite(reacquire_time_s) else None,
        "mean_settling_time_s": round(mean_settling_time_s, 2) if math.isfinite(mean_settling_time_s) else None,
        "tracking_efficiency": round(tracking_efficiency, 4),
        "rms_pixel_error": round(rms_pixel_error, 2) if math.isfinite(rms_pixel_error) else None,
    }

    # ATP 相关指标
    atp_metrics = _compute_atp_metrics(records, timestamps)
    atp_metrics["reacquire_success_rate"] = round(reacquire_success_rate, 4) if reacquire_attempts > 0 else None

    return {"metrics": metrics, "atp_metrics": atp_metrics}


def _compute_atp_metrics(records: list[FrameRecord], timestamps: np.ndarray) -> dict:
    """计算 ATP 状态机相关指标。"""
    atp_states = [r.atp_state for r in records]

    # 首次进入 TRACK_COARSE 的时间
    time_to_acquire_s = None
    time_to_fine_track_s = None
    for r in records:
        if r.atp_state in ("ACQUIRE", "TRACK_COARSE", "TRACK_FINE") and time_to_acquire_s is None:
            time_to_acquire_s = r.timestamp
        if r.atp_state == "TRACK_FINE" and time_to_fine_track_s is None:
            time_to_fine_track_s = r.timestamp

    # 状态分布（稳态期间，t >= 3s）
    state_counts: dict[str, int] = {}
    for r in records:
        if r.timestamp < 3.0:
            continue
        state_counts[r.atp_state] = state_counts.get(r.atp_state, 0) + 1

    total_stable_frames = sum(state_counts.values())
    if total_stable_frames > 0:
        state_distribution = {k: round(v / total_stable_frames, 4) for k, v in state_counts.items()}
    else:
        state_distribution = None

    return {
        "time_to_acquire_s": round(time_to_acquire_s, 2) if time_to_acquire_s is not None else None,
        "time_to_fine_track_s": round(time_to_fine_track_s, 2) if time_to_fine_track_s is not None else None,
        "state_distribution": state_distribution,
    }


def _empty_metrics() -> dict:
    """返回空指标字典。"""
    return {
        "capture_success_rate": None,
        "mean_tracking_error_px": None,
        "max_tracking_error_px": None,
        "lock_loss_count": None,
        "lock_loss_rate": None,
        "reacquire_time_s": None,
        "mean_settling_time_s": None,
        "tracking_efficiency": None,
        "rms_pixel_error": None,
    }


def _empty_atp_metrics() -> dict:
    """返回空 ATP 指标字典。"""
    return {
        "time_to_acquire_s": None,
        "time_to_fine_track_s": None,
        "state_distribution": None,
        "reacquire_success_rate": None,
    }


# ============================================================
# 文件输出
# ============================================================

def write_result_json(output_dir: str, result: dict) -> None:
    """写入 result.json。"""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


def write_metrics_csv(output_dir: str, records: list[FrameRecord]) -> None:
    """写入 metrics.csv 帧级指标。"""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "metrics.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "pixel_error_x", "pixel_error_y", "pixel_error_total",
            "detection_found", "atp_state", "yaw_rate_cmd", "pitch_rate_cmd",
        ])
        for r in records:
            writer.writerow([
                round(r.timestamp, 6),
                _fmt(r.pixel_error_x),
                _fmt(r.pixel_error_y),
                _fmt(r.pixel_error_total),
                r.detection_found,
                r.atp_state,
                round(r.yaw_rate_cmd, 4),
                round(r.pitch_rate_cmd, 4),
            ])


def write_notes_md(output_dir: str, scenario: ScenarioConfig, algorithm_name: str,
                   seed: int, obs_mode: str, duration_s: float) -> None:
    """写入 notes.md 简要说明。"""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "notes.md")
    content = (
        f"# Benchmark 实验记录\n\n"
        f"- 算法: `{algorithm_name}`\n"
        f"- 场景: `{scenario.condition_id}` ({scenario.description})\n"
        f"- 随机种子: {seed}\n"
        f"- 观测模式: {obs_mode}\n"
        f"- 仿真时长: {duration_s}s\n"
        f"- 目标类型: {scenario.target_type}\n"
        f"- 初始距离: {scenario.initial_x_m}m\n"
        f"- 正弦幅度: {scenario.sin_amplitude_m}m\n"
        f"- 正弦频率: {scenario.sin_frequency_hz}Hz\n"
        f"- 延时: {scenario.delay_ms}ms\n"
        f"- 生成时间: {datetime.now(timezone.utc).isoformat()}\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def write_error_curve_png(output_dir: str, records: list[FrameRecord],
                          algorithm_name: str, scenario_id: str) -> None:
    """生成像素误差曲线图。"""
    try:
        import matplotlib
        matplotlib.use("Agg")  # 无 GUI 后端
        import matplotlib.pyplot as plt
    except ImportError:
        print("  [跳过] matplotlib 不可用，跳过图表生成")
        return

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "error_curve.png")

    timestamps = [r.timestamp for r in records]
    errors = [r.pixel_error_total if math.isfinite(r.pixel_error_total) else None for r in records]
    in_fov = [r.in_fov for r in records]

    fig, ax = plt.subplots(1, 1, figsize=(12, 5))
    ax.plot(timestamps, errors, linewidth=0.5, alpha=0.8, label="pixel error")
    ax.axhline(y=30, color="orange", linestyle="--", linewidth=0.8, label="30px threshold")
    ax.axhline(y=50, color="red", linestyle="--", linewidth=0.8, label="50px threshold")
    ax.axvspan(0, 3.0, alpha=0.1, color="gray", label="boot phase")

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Pixel Error (px)")
    ax.set_title(f"Tracking Error — {algorithm_name} / {scenario_id}")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_state_timeline_png(output_dir: str, records: list[FrameRecord],
                             algorithm_name: str, scenario_id: str) -> None:
    """生成 ATP 状态时间线图。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    # 只在有 ATP 状态数据时生成
    states = [r.atp_state for r in records]
    if all(s == "N/A" for s in states):
        return

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "state_timeline.png")

    # 状态到数值的映射
    state_map = {
        "SEARCH": 0,
        "ACQUIRE": 1,
        "TRACK_COARSE": 2,
        "TRACK_FINE": 3,
        "LOST": 4,
        "REACQUIRE": 5,
        "N/A": -1,
    }
    state_values = [state_map.get(s, -1) for s in states]
    timestamps = [r.timestamp for r in records]

    fig, ax = plt.subplots(1, 1, figsize=(12, 4))

    # 绘制状态变化
    for i in range(len(timestamps) - 1):
        sv = state_values[i]
        if sv < 0:
            continue
        color = _state_color(states[i])
        ax.plot([timestamps[i], timestamps[i + 1]], [sv, sv], color=color, linewidth=1.5)

    ax.set_yticks(list(state_map.values()))
    ax.set_yticklabels(list(state_map.keys()), fontsize=8)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("ATP State")
    ax.set_title(f"ATP State Timeline — {algorithm_name} / {scenario_id}")
    ax.set_xlim(left=0)
    ax.grid(True, alpha=0.3, axis="x")

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _state_color(state: str) -> str:
    """ATP 状态对应颜色。"""
    colors = {
        "SEARCH": "#9E9E9E",
        "ACQUIRE": "#FFC107",
        "TRACK_COARSE": "#2196F3",
        "TRACK_FINE": "#4CAF50",
        "LOST": "#F44336",
        "REACQUIRE": "#FF9800",
        "N/A": "#BDBDBD",
    }
    return colors.get(state, "#BDBDBD")


def _fmt(value: float) -> str:
    """格式化浮点数，NaN 输出为空字符串。"""
    if math.isfinite(value):
        return f"{value:.2f}"
    return ""


# ============================================================
# Benchmark 运行器
# ============================================================

class BenchmarkRunner:
    """Benchmark 运行器，管理完整的评测流程。"""

    def __init__(self, output_dir: str = "output/experiments"):
        """初始化。

        Args:
            output_dir: 输出根目录。
        """
        self.output_dir = os.path.abspath(output_dir)
        self._git_hash = self._get_git_hash()

    @staticmethod
    def _get_git_hash() -> str:
        """获取当前 git commit hash。"""
        import subprocess
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            ).decode().strip()
        except Exception:
            return "unknown"

    def _experiment_dir(self, scenario: ScenarioConfig, algorithm_name: str,
                        seed: int) -> str:
        """计算实验输出目录路径。"""
        return os.path.join(
            self.output_dir,
            scenario.scenario_id,
            scenario.condition_id,
            algorithm_name,
            f"seed_{seed:03d}",
        )

    def run_experiment(
        self,
        algorithm_name: str,
        scenario_key: str,
        seed: int,
        obs_mode: str = "research",
        duration_s: float = 20.0,
    ) -> dict:
        """运行单组实验并收集数据。

        Args:
            algorithm_name: 算法名称（必须在 ALGORITHM_REGISTRY 中）。
            scenario_key: 场景键名（如 B1, B2, B3）。
            seed: 随机种子。
            obs_mode: 观测模式（debug / research / realistic）。
            duration_s: 仿真时长（秒）。

        Returns:
            result.json 的完整字典。
        """
        scenario = SCENARIOS[scenario_key]
        experiment_dir = self._experiment_dir(scenario, algorithm_name, seed)

        print(f"  [{algorithm_name}] 场景={scenario_key} 种子={seed} 模式={obs_mode} ...", end="", flush=True)
        t_start = time.perf_counter()

        failure_reason = None
        records = []
        result = {}

        try:
            if not is_obs_mode_allowed(algorithm_name, obs_mode):
                allowed = ALGORITHM_OBS_MODES.get(algorithm_name, [])
                raise ValueError(
                    f"{algorithm_name} 不支持 {obs_mode} 模式（允许: {allowed}）"
                )

            # 1. 设置随机种子
            np.random.seed(seed)

            # 2. 临时覆盖目标配置
            from config import target_cfg
            old_motion_type = target_cfg.motion_type
            old_initial_x = target_cfg.initial_x_m
            old_initial_y = target_cfg.initial_y_m
            old_initial_z = target_cfg.initial_z_m
            old_sin_amp = target_cfg.sin_amplitude_m
            old_sin_freq = target_cfg.sin_frequency_hz
            old_sin_z_amp = target_cfg.sin_z_amplitude_m
            old_sin_z_freq = target_cfg.sin_z_frequency_hz

            target_cfg.motion_type = scenario.target_type
            target_cfg.initial_x_m = scenario.initial_x_m
            target_cfg.initial_y_m = scenario.initial_y_m
            target_cfg.initial_z_m = scenario.initial_z_m
            target_cfg.sin_amplitude_m = scenario.sin_amplitude_m
            target_cfg.sin_frequency_hz = scenario.sin_frequency_hz
            target_cfg.sin_z_amplitude_m = scenario.sin_z_amplitude_m
            target_cfg.sin_z_frequency_hz = scenario.sin_z_frequency_hz

            try:
                # 3. 创建算法实例
                control_program = ALGORITHM_REGISTRY[algorithm_name]()

                # 4. 构建并启动 runtime
                from simulation.bootstrap import build_runtime
                runtime = build_runtime(
                    delay_ms=scenario.delay_ms,
                    control_program=control_program,
                    obs_mode=obs_mode,
                )

                # 5. 运行仿真，采集帧级数据
                n_steps = max(1, int(duration_s / runtime.dt_s))
                from config import camera_cfg
                cx = camera_cfg.cx
                cy = camera_cfg.resolution_h / 2.0

                collector = FrameCollector()
                for _ in range(n_steps):
                    snapshot = runtime.step(1)
                    collector.collect(snapshot, control_program, cx, cy)

                records = collector.records

                # 6. 计算指标
                metrics_result = compute_metrics(records, duration_s)

                # 7. 构建完整结果
                result = {
                    "scenario_id": scenario.scenario_id,
                    "condition_id": scenario.condition_id,
                    "algorithm_name": algorithm_name,
                    "algorithm_version": ALGORITHM_VERSIONS.get(algorithm_name, "0.0"),
                    "observation_mode": obs_mode,
                    "seed": seed,
                    "duration_s": duration_s,
                    "metrics": metrics_result["metrics"],
                    "atp_metrics": metrics_result["atp_metrics"],
                    "failure_reason": None,
                    "metadata": {
                        "git_hash": self._git_hash,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "total_frames": len(records),
                        "delay_ms": scenario.delay_ms,
                        "target_config": {
                            "motion_type": scenario.target_type,
                            "initial_x_m": scenario.initial_x_m,
                            "sin_amplitude_m": scenario.sin_amplitude_m,
                            "sin_frequency_hz": scenario.sin_frequency_hz,
                        },
                    },
                }

                # 8. 输出文件
                write_result_json(experiment_dir, result)
                write_metrics_csv(experiment_dir, records)
                write_notes_md(experiment_dir, scenario, algorithm_name, seed, obs_mode, duration_s)
                write_error_curve_png(experiment_dir, records, algorithm_name, scenario.condition_id)
                write_state_timeline_png(experiment_dir, records, algorithm_name, scenario.condition_id)

            finally:
                # 恢复目标配置
                target_cfg.motion_type = old_motion_type
                target_cfg.initial_x_m = old_initial_x
                target_cfg.initial_y_m = old_initial_y
                target_cfg.initial_z_m = old_initial_z
                target_cfg.sin_amplitude_m = old_sin_amp
                target_cfg.sin_frequency_hz = old_sin_freq
                target_cfg.sin_z_amplitude_m = old_sin_z_amp
                target_cfg.sin_z_frequency_hz = old_sin_z_freq

        except Exception as e:
            failure_reason = f"{type(e).__name__}: {str(e)}"
            traceback.print_exc()
            result = {
                "scenario_id": scenario.scenario_id,
                "condition_id": scenario.condition_id,
                "algorithm_name": algorithm_name,
                "algorithm_version": ALGORITHM_VERSIONS.get(algorithm_name, "0.0"),
                "observation_mode": obs_mode,
                "seed": seed,
                "duration_s": duration_s,
                "metrics": _empty_metrics(),
                "atp_metrics": _empty_atp_metrics(),
                "failure_reason": failure_reason,
                "metadata": {
                    "git_hash": self._git_hash,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "total_frames": len(records),
                    "delay_ms": scenario.delay_ms,
                },
            }
            # 即使失败也写入结果
            write_result_json(experiment_dir, result)

        elapsed = time.perf_counter() - t_start
        status = "失败" if failure_reason else "完成"
        m = result.get("metrics", {})
        rms = m.get("rms_pixel_error", "N/A")
        print(f" {status} ({elapsed:.1f}s) rms_px={rms}")

        return result

    def run_suite(
        self,
        algorithms: list[str] | None = None,
        scenarios: list[str] | None = None,
        seeds: list[int] | None = None,
        obs_modes: list[str] | None = None,
        duration_s: float = 20.0,
    ) -> list[dict]:
        """运行完整 benchmark 套件。

        Args:
            algorithms: 算法名称列表，None 表示全部。
            scenarios: 场景键名列表，None 表示全部。
            seeds: 随机种子列表，None 表示默认。
            obs_modes: 观测模式列表，None 表示默认。
            duration_s: 仿真时长。

        Returns:
            所有实验结果列表。
        """
        if algorithms is None:
            algorithms = list(ALGORITHM_REGISTRY.keys())
        if scenarios is None:
            scenarios = list(SCENARIOS.keys())
        if seeds is None:
            seeds = [42, 123, 456, 789, 1024]
        if obs_modes is None:
            obs_modes = ["research"]

        # 参数校验
        for alg in algorithms:
            if alg not in ALGORITHM_REGISTRY:
                print(f"[错误] 未知算法: {alg}")
                print(f"  可选算法: {', '.join(ALGORITHM_REGISTRY.keys())}")
                sys.exit(1)
        for sc in scenarios:
            if sc not in SCENARIOS:
                print(f"[错误] 未知场景: {sc}")
                print(f"  可选场景: {', '.join(SCENARIOS.keys())}")
                sys.exit(1)

        # 计算有效实验数（排除模式不兼容的组合）
        valid_count = 0
        for obs_mode in obs_modes:
            for scenario_key in scenarios:
                for algorithm_name in algorithms:
                    if not is_obs_mode_allowed(algorithm_name, obs_mode):
                        continue
                    valid_count += len(seeds)

        if valid_count == 0:
            print("[错误] 当前算法与观测模式组合没有任何可运行实验")
            sys.exit(1)

        print(f"[Benchmark] 开始运行: {valid_count} 组实验")
        print(f"  算法: {algorithms}")
        print(f"  场景: {scenarios}")
        print(f"  种子: {seeds}")
        print(f"  观测模式: {obs_modes}")
        print(f"  时长: {duration_s}s")
        print(f"  输出: {self.output_dir}")
        print()

        results = []
        completed = 0
        failed = 0

        for obs_mode in obs_modes:
            for scenario_key in scenarios:
                for algorithm_name in algorithms:
                    # 模式兼容性校验：跳过不允许的组合
                    if not is_obs_mode_allowed(algorithm_name, obs_mode):
                        allowed = ALGORITHM_OBS_MODES.get(algorithm_name, [])
                        print(f"  [跳过] {algorithm_name} 不支持 {obs_mode} 模式（允许: {allowed}）")
                        continue
                    for seed in seeds:
                        completed += 1
                        print(f"[{completed}/{valid_count}]", end="")
                        result = self.run_experiment(
                            algorithm_name=algorithm_name,
                            scenario_key=scenario_key,
                            seed=seed,
                            obs_mode=obs_mode,
                            duration_s=duration_s,
                        )
                        results.append(result)
                        if result.get("failure_reason"):
                            failed += 1

        print()
        print(f"[Benchmark] 全部完成: {valid_count - failed} 成功, {failed} 失败")
        print(f"  结果目录: {self.output_dir}")

        # 写入汇总文件
        os.makedirs(self.output_dir, exist_ok=True)
        suite_summary_path = os.path.join(self.output_dir, "_suite_summary.json")
        with open(suite_summary_path, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_experiments": valid_count,
                "successful": valid_count - failed,
                "failed": failed,
                "algorithms": algorithms,
                "scenarios": scenarios,
                "seeds": seeds,
                "obs_modes": obs_modes,
                "duration_s": duration_s,
                "results": results,
            }, f, indent=2, ensure_ascii=False)

        return results


# ============================================================
# 命令行入口
# ============================================================

def _generate_experiment_log(args, results: list[dict], output_dir: str) -> None:
    """根据 benchmark 运行结果自动生成实验记录骨架。"""
    successful = [r for r in results if not r.get("failure_reason")]
    failed = [r for r in results if r.get("failure_reason")]

    algorithms = args.algorithms or list(ALGORITHM_REGISTRY.keys())
    scenarios = args.scenarios or list(SCENARIOS.keys())
    seeds = args.seeds or [42, 123, 456, 789, 1024]
    obs_modes = args.obs_modes or ["research"]

    now = datetime.now(timezone.utc)

    lines = [
        "# 实验批次记录",
        "",
        f"- **实验时间**: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **实验说明**: {args.experiment_note}",
        f"- **运行命令**: `python tools/run_benchmark.py --algorithms {' '.join(algorithms)} --scenarios {' '.join(scenarios)} --seeds {' '.join(str(s) for s in seeds)} --obs-modes {' '.join(obs_modes)} --duration {args.duration}`",
        f"- **输出目录**: `{output_dir}`",
        f"- **算法列表**: {', '.join(algorithms)}",
        f"- **场景列表**: {', '.join(scenarios)}",
        f"- **随机种子**: {', '.join(str(s) for s in seeds)}",
        f"- **观测模式**: {', '.join(obs_modes)}",
        f"- **仿真时长**: {args.duration}s",
        f"- **总实验数**: {len(results)}（成功 {len(successful)}，失败 {len(failed)}）",
        "",
        "## 本轮改动内容",
        "",
        "<!-- 请在此填写本轮算法改动说明 -->",
        "",
        "## 关键结果摘要",
        "",
    ]

    # 自动填入每个算法的 RMS 排名
    if successful:
        from tools.summarize_results import compute_summary
        summary = compute_summary(successful)
        groups = summary.get("groups", [])
        # 按 RMS 均值排序
        ranked = []
        for g in groups:
            rms = g.get("stats", {}).get("rms_pixel_error", {})
            mean_rms = rms.get("mean")
            if mean_rms is not None:
                ranked.append((g["algorithm_name"], g["condition_id"], mean_rms, rms.get("std", 0.0)))
        ranked.sort(key=lambda x: x[2])

        lines.append("| 排名 | 算法 | 场景 | RMS误差(px) | Std |")
        lines.append("|------|------|------|-------------|-----|")
        for i, (alg, cond, rms, std) in enumerate(ranked, 1):
            lines.append(f"| {i} | {alg} | {cond} | {rms:.2f} | {std:.2f} |")
        lines.append("")

    lines.extend([
        "## 与基线对比结论",
        "",
        "<!-- 请在此填写对比结论，或使用 compare_results.py 自动生成 -->",
        "",
        "## 风险与异常",
        "",
        "<!-- 如有异常现象，请在此记录 -->",
        "",
        "## 下一步动作",
        "",
        "<!-- 请在此填写后续计划 -->",
        "",
    ])

    log_path = os.path.join(output_dir, "experiment_log.md")
    os.makedirs(output_dir, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[实验记录] 已生成: {log_path}")


def main() -> None:
    """命令行入口。"""
    # 修复 Windows 控制台编码
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Benchmark 运行工具 — 多算法、多场景、多种子统一评测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/run_benchmark.py
  python tools/run_benchmark.py --algorithms baseline_rate_p rate_pi --scenarios B1 B2 --seeds 42 123
  python tools/run_benchmark.py --obs-modes research realistic --duration 10.0
        """,
    )
    parser.add_argument(
        "--algorithms", nargs="+", default=None,
        help=f"算法列表（默认全部）。可选: {', '.join(ALGORITHM_REGISTRY.keys())}",
    )
    parser.add_argument(
        "--scenarios", nargs="+", default=None,
        help=f"场景列表（默认全部）。可选: {', '.join(SCENARIOS.keys())}",
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=None,
        help="随机种子列表（默认: 42 123 456 789 1024）",
    )
    parser.add_argument(
        "--obs-modes", nargs="+", default=None,
        help="观测模式列表（默认: research）。可选: debug, research, realistic",
    )
    parser.add_argument(
        "--duration", type=float, default=20.0,
        help="每组实验仿真时长（秒，默认: 20.0）",
    )
    parser.add_argument(
        "--output-dir", default="output/experiments",
        help="输出根目录（默认: output/experiments）",
    )
    parser.add_argument(
        "--experiment-note", default=None,
        help="实验说明（自动写入实验记录骨架）",
    )

    args = parser.parse_args()

    runner = BenchmarkRunner(output_dir=args.output_dir)
    results = runner.run_suite(
        algorithms=args.algorithms,
        scenarios=args.scenarios,
        seeds=args.seeds,
        obs_modes=args.obs_modes,
        duration_s=args.duration,
    )

    # 自动生成实验记录骨架
    if args.experiment_note is not None:
        _generate_experiment_log(args, results, runner.output_dir)


if __name__ == "__main__":
    main()
