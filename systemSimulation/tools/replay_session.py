"""离线回放工具：用预录制 CSV 数据驱动控制程序测试。

用法:
    python -m tools.replay_session --input output/record.csv --control-program my_tracker:MyTracker
    python -m tools.replay_session --input output/record.csv --control-program my_tracker:MyTracker --output output/replay.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _row_to_obs(row: dict) -> dict:
    """将 CSV 行还原为 obs 字典（control_program.on_tick 的输入格式）。"""
    obs = {"timestamp": float(row["timestamp"])}
    # target
    obs["target"] = {}
    for k in ("x_m", "y_m", "bearing_deg", "distance_m"):
        key = f"target.{k}"
        if key in row and row[key] != "":
            obs["target"][k] = float(row[key])
    # gimbal
    obs["gimbal"] = {}
    for k in ("power_state", "mode", "yaw_deg_internal", "yaw_deg_display",
              "pitch_deg", "yaw_rate_dps", "pitch_rate_dps"):
        key = f"gimbal.{k}"
        if key in row:
            v = row[key]
            if k in ("power_state", "mode"):
                obs["gimbal"][k] = v
            elif v != "":
                obs["gimbal"][k] = float(v)
    # camera
    obs["camera"] = {}
    for k in ("power_state", "f_current_mm", "f_target_mm", "frame_id",
              "in_fov", "u_px", "v_px"):
        key = f"camera.{k}"
        if key in row:
            v = row[key]
            if k == "power_state":
                obs["camera"][k] = v
            elif k == "in_fov":
                obs["camera"][k] = v == "True"
            elif v != "":
                obs["camera"][k] = float(v)
    # frame 不从 CSV 恢复（图像数据无法存 CSV）
    obs["frame"] = None
    return obs


def replay_session(input_path: str, control_program_path: str = "",
                   output_path: str = "") -> dict:
    """用 CSV 中的 obs 数据驱动控制程序，收集命令并统计。

    返回统计 dict: {total_rows, total_commands, avg_commands_per_tick}
    """
    from runtime.types import Command
    from simulation.bootstrap import load_control_program_from_path
    from entities.raspi.control_program import NoopControlProgram

    # 读取 CSV
    with open(input_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("[replay] CSV 为空，无数据可回放")
        return {"total_rows": 0, "total_commands": 0}

    # 加载控制程序
    if control_program_path:
        program = load_control_program_from_path(control_program_path)
    else:
        program = NoopControlProgram()
    if callable(program) and not hasattr(program, "on_tick"):
        program = program()

    # 回放
    all_commands = []
    output_rows = []

    for row in rows:
        obs = _row_to_obs(row)
        cmds = program.on_tick(obs)
        all_commands.extend(cmds)

        if output_path:
            out_row = dict(row)
            out_row["replay_commands"] = len(cmds)
            for i, cmd in enumerate(cmds):
                out_row[f"replay_cmd{i}_target"] = cmd.target
                out_row[f"replay_cmd{i}_action"] = cmd.action
                out_row[f"replay_cmd{i}_payload"] = str(cmd.payload)
            output_rows.append(out_row)

    # 写输出
    if output_path and output_rows:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fieldnames = list(output_rows[0].keys())
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(output_rows)
        print(f"[replay] {len(output_rows)} rows → {output_path}")

    stats = {
        "total_rows": len(rows),
        "total_commands": len(all_commands),
        "avg_commands_per_tick": len(all_commands) / max(1, len(rows)),
    }
    print(f"[replay] rows={stats['total_rows']}, cmds={stats['total_commands']}, "
          f"avg_cmds/tick={stats['avg_commands_per_tick']:.2f}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="离线回放 CSV 数据驱动控制程序")
    parser.add_argument("--input", type=str, required=True, help="输入 CSV 路径")
    parser.add_argument("--control-program", type=str, default="", help="控制程序 module:Class")
    parser.add_argument("--output", type=str, default="", help="输出 CSV 路径（可选）")
    args = parser.parse_args()

    replay_session(
        input_path=args.input,
        control_program_path=args.control_program,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
