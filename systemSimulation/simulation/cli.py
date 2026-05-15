"""应用入口编排。"""

from __future__ import annotations

import argparse

from simulation.gui.runner import run_gui
from simulation.headless import run_headless_session
from simulation.types import AppConfig


def parse_args() -> AppConfig:
    parser = argparse.ArgumentParser(description="完整实时仿真入口（双视角并排 + Tab + 稳定时间轴）")
    parser.add_argument("--duration", type=float, default=60.0, help="运行时长（秒）")
    parser.add_argument("--mode", choices=["realtime", "offline"], default="realtime", help="运行模式")
    parser.add_argument("--delay-ms", type=float, default=0.0, help="Raspi 链路延时（毫秒）")
    parser.add_argument("--no-gui", action="store_true", help="不启用窗口，仅控制台输出")
    parser.add_argument(
        "--control-program",
        type=str,
        default="",
        help="自定义控制程序路径，格式: module:Class（如 my_tracker:MyTracker）",
    )
    parser.add_argument(
        "--target-type",
        type=str,
        default="",
        help="目标运动类型: sinusoidal / constant_velocity / constant_accel / random_walk / waypoint",
    )
    parser.add_argument(
        "--waypoints",
        type=str,
        default="",
        help='航点轨迹，格式: "(x1,y1,z1,speed1),(x2,y2,z2,speed2)"；兼容旧格式 "(x1,y1,speed1)"（z 缺省为 0，speed=0 表示悬停）',
    )
    args = parser.parse_args()
    return AppConfig(
        duration_s=args.duration,
        mode=args.mode,
        delay_ms=args.delay_ms,
        no_gui=args.no_gui,
        control_program_path=args.control_program,
        target_type=args.target_type,
        waypoints=args.waypoints,
    )


def main() -> None:
    cfg = parse_args()
    if cfg.no_gui:
        run_headless_session(cfg)
        return
    run_gui(cfg)
