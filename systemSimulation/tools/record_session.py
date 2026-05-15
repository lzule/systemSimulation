"""数据录制工具：运行仿真并导出 CSV。

用法:
    python -m tools.record_session --duration 10 --output output/record.csv
    python -m tools.record_session --duration 10 --output output/record.csv --control-program my_tracker:MyTracker
    python -m tools.record_session --duration 10 --output output/record.csv --waypoints "(100,0,50,2),(80,30,30,1.5)"
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import os

# 确保项目根目录在 path 上
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _build_csv_row(snap) -> dict:
    """将 WorldSnapshot 展平为一行 CSV-compatible dict。"""
    row = {"timestamp": snap.timestamp}
    for prefix, data in [("target", snap.target), ("gimbal", snap.gimbal),
                         ("camera", snap.camera), ("raspi", snap.raspi)]:
        for k, v in data.items():
            if isinstance(v, dict):
                for k2, v2 in v.items():
                    row[f"{prefix}.{k}.{k2}"] = v2
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                row[f"{prefix}.{k}"] = ""
            else:
                row[f"{prefix}.{k}"] = v
    return row


def record_session(duration_s: float, output_path: str,
                   delay_ms: float = 0.0, control_program_path: str = "",
                   target_type: str = "", waypoints: str = "") -> int:
    """运行仿真并录制数据到 CSV。返回写入的行数。"""
    from simulation.bootstrap import build_runtime, load_control_program_from_path
    from simulation.headless import apply_target_overrides
    from simulation.types import AppConfig

    cfg = AppConfig(
        duration_s=duration_s, mode="offline", delay_ms=delay_ms, no_gui=True,
        control_program_path=control_program_path,
        target_type=target_type, waypoints=waypoints,
    )
    apply_target_overrides(cfg)

    control_program = None
    if cfg.control_program_path:
        control_program = load_control_program_from_path(cfg.control_program_path)

    runtime = build_runtime(delay_ms=cfg.delay_ms, control_program=control_program)
    n_steps = max(1, int(duration_s / runtime.dt_s))

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    rows = []
    fieldnames = None
    for _ in range(n_steps):
        snap = runtime.step(1)
        row = _build_csv_row(snap)
        if fieldnames is None:
            fieldnames = list(row.keys())
        rows.append(row)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[record] {len(rows)} rows → {output_path}")
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="录制仿真数据到 CSV")
    parser.add_argument("--duration", type=float, default=10.0, help="仿真时长（秒）")
    parser.add_argument("--output", type=str, default="output/record.csv", help="输出 CSV 路径")
    parser.add_argument("--delay-ms", type=float, default=0.0, help="链路延时（毫秒）")
    parser.add_argument("--control-program", type=str, default="", help="控制程序 module:Class")
    parser.add_argument("--target-type", type=str, default="", help="目标运动类型")
    parser.add_argument(
        "--waypoints",
        type=str,
        default="",
        help='航点 "(x1,y1,z1,s1),(x2,y2,z2,s2)"；兼容旧格式 "(x1,y1,s1)"（z 缺省为 0）',
    )
    args = parser.parse_args()

    record_session(
        duration_s=args.duration, output_path=args.output,
        delay_ms=args.delay_ms, control_program_path=args.control_program,
        target_type=args.target_type, waypoints=args.waypoints,
    )


if __name__ == "__main__":
    main()
