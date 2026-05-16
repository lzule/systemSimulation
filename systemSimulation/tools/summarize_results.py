"""结果汇总工具 — 扫描实验输出目录，生成对比表格。

用法:
    # 使用默认目录
    conda run -n simulation python tools/summarize_results.py

    # 指定目录
    conda run -n simulation python tools/summarize_results.py --input-dir output/experiments

    # 指定排序字段
    conda run -n simulation python tools/summarize_results.py --sort-by rms_pixel_error

    # 只输出 JSON（不生成 CSV）
    conda run -n simulation python tools/summarize_results.py --format json

输出:
    summary.csv — 所有实验的汇总表格
    summary.json — 结构化汇总数据（按算法、场景分组）
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 结果扫描
# ============================================================

def scan_results(input_dir: str) -> list[dict]:
    """扫描实验输出目录，收集所有 result.json。

    Args:
        input_dir: 实验输出根目录。

    Returns:
        所有 result.json 内容的列表。
    """
    results = []

    for root, dirs, files in os.walk(input_dir):
        if "result.json" in files:
            path = os.path.join(root, "result.json")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 补充文件路径信息
                data["_source_path"] = os.path.relpath(path, input_dir)
                results.append(data)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[警告] 无法读取 {path}: {e}")

    return results


# ============================================================
# 汇总计算
# ============================================================

def compute_summary(results: list[dict]) -> dict:
    """从 result.json 列表计算汇总统计。

    按 (algorithm_name, condition_id) 分组，计算各指标的均值和标准差。

    Args:
        results: result.json 内容列表。

    Returns:
        结构化汇总字典。
    """
    # 按 (algorithm, scenario, obs_mode) 分组
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in results:
        if r.get("failure_reason"):
            continue  # 跳过失败实验
        alg = r.get("algorithm_name", "unknown")
        cond = r.get("condition_id", "unknown")
        obs = r.get("observation_mode", "unknown")
        groups[(alg, cond, obs)].append(r)

    summary_groups = []
    for (alg, cond, obs), group_results in sorted(groups.items()):
        summary_groups.append(_aggregate_group(alg, cond, obs, group_results))

    # 按算法+模式单独汇总，避免混合不同观测模式
    algorithm_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in results:
        if r.get("failure_reason"):
            continue
        alg = r.get("algorithm_name", "unknown")
        obs = r.get("observation_mode", "unknown")
        algorithm_groups[(alg, obs)].append(r)

    algorithm_summaries = []
    for (alg, obs), alg_results in sorted(algorithm_groups.items()):
        algorithm_summaries.append(_aggregate_algorithm(alg, obs, alg_results))

    # 按场景单独汇总
    scenario_groups: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        if r.get("failure_reason"):
            continue
        scenario_groups[r.get("condition_id", "unknown")].append(r)

    scenario_summaries = []
    for cond, cond_results in sorted(scenario_groups.items()):
        scenario_summaries.append(_aggregate_scenario(cond, cond_results))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_experiments": len(results),
        "successful_experiments": sum(1 for r in results if not r.get("failure_reason")),
        "failed_experiments": sum(1 for r in results if r.get("failure_reason")),
        "groups": summary_groups,
        "by_algorithm": algorithm_summaries,
        "by_scenario": scenario_summaries,
    }


def _aggregate_group(algorithm_name: str, condition_id: str, obs_mode: str,
                     results: list[dict]) -> dict:
    """对同一 (算法, 场景, 观测模式) 组合的多 seed 结果求统计量。"""
    n = len(results)
    seeds = [r.get("seed", -1) for r in results]

    # 提取关键指标
    metric_keys = [
        "capture_success_rate",
        "mean_tracking_error_px",
        "max_tracking_error_px",
        "rms_pixel_error",
        "lock_loss_count",
        "lock_loss_rate",
        "tracking_efficiency",
        "mean_settling_time_s",
    ]

    stats = {}
    for key in metric_keys:
        values = [r.get("metrics", {}).get(key) for r in results]
        values = [v for v in values if v is not None and (isinstance(v, (int, float)) and math.isfinite(v))]
        if values:
            stats[key] = {
                "mean": round(sum(values) / len(values), 4),
                "std": round(_std(values), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "n": len(values),
            }
        else:
            stats[key] = {"mean": None, "std": None, "min": None, "max": None, "n": 0}

    return {
        "algorithm_name": algorithm_name,
        "condition_id": condition_id,
        "obs_mode": obs_mode,
        "n_seeds": n,
        "seeds": seeds,
        "stats": stats,
    }


def _aggregate_algorithm(algorithm_name: str, obs_mode: str, results: list[dict]) -> dict:
    """对同一算法在单一模式下跨所有场景的结果求统计量。"""
    metric_keys = ["capture_success_rate", "rms_pixel_error", "tracking_efficiency"]
    stats = {}
    for key in metric_keys:
        values = [r.get("metrics", {}).get(key) for r in results]
        values = [v for v in values if v is not None and (isinstance(v, (int, float)) and math.isfinite(v))]
        if values:
            stats[key] = {
                "mean": round(sum(values) / len(values), 4),
                "std": round(_std(values), 4),
                "n": len(values),
            }
        else:
            stats[key] = {"mean": None, "std": None, "n": 0}

    return {
        "algorithm_name": algorithm_name,
        "obs_mode": obs_mode,
        "n_experiments": len(results),
        "stats": stats,
    }


def _aggregate_scenario(condition_id: str, results: list[dict]) -> dict:
    """对同一场景跨所有算法的结果求统计量。"""
    metric_keys = ["capture_success_rate", "rms_pixel_error"]
    stats = {}
    for key in metric_keys:
        values = [r.get("metrics", {}).get(key) for r in results]
        values = [v for v in values if v is not None and (isinstance(v, (int, float)) and math.isfinite(v))]
        if values:
            stats[key] = {
                "mean": round(sum(values) / len(values), 4),
                "std": round(_std(values), 4),
                "n": len(values),
            }
        else:
            stats[key] = {"mean": None, "std": None, "n": 0}

    return {
        "condition_id": condition_id,
        "n_experiments": len(results),
        "stats": stats,
    }


def _std(values: list[float]) -> float:
    """计算样本标准差。"""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return variance ** 0.5


# ============================================================
# 输出
# ============================================================

# CSV 列定义
CSV_COLUMNS = [
    "algorithm_name",
    "condition_id",
    "seed",
    "obs_mode",
    "capture_success_rate",
    "mean_tracking_error_px",
    "max_tracking_error_px",
    "rms_pixel_error",
    "lock_loss_count",
    "lock_loss_rate",
    "tracking_efficiency",
    "mean_settling_time_s",
    "time_to_acquire_s",
    "time_to_fine_track_s",
    "failure_reason",
]


def write_summary_csv(output_path: str, results: list[dict],
                      sort_by: str = "rms_pixel_error") -> None:
    """写入 summary.csv。

    每行一个实验，按指定指标排序。

    Args:
        output_path: 输出文件路径。
        results: result.json 列表。
        sort_by: 排序字段名。
    """
    # 准备行数据
    rows = []
    for r in results:
        metrics = r.get("metrics", {})
        atp_metrics = r.get("atp_metrics", {})
        row = {
            "algorithm_name": r.get("algorithm_name", ""),
            "condition_id": r.get("condition_id", ""),
            "seed": r.get("seed", ""),
            "obs_mode": r.get("observation_mode", ""),
            "capture_success_rate": metrics.get("capture_success_rate", ""),
            "mean_tracking_error_px": metrics.get("mean_tracking_error_px", ""),
            "max_tracking_error_px": metrics.get("max_tracking_error_px", ""),
            "rms_pixel_error": metrics.get("rms_pixel_error", ""),
            "lock_loss_count": metrics.get("lock_loss_count", ""),
            "lock_loss_rate": metrics.get("lock_loss_rate", ""),
            "tracking_efficiency": metrics.get("tracking_efficiency", ""),
            "mean_settling_time_s": metrics.get("mean_settling_time_s", ""),
            "time_to_acquire_s": atp_metrics.get("time_to_acquire_s", ""),
            "time_to_fine_track_s": atp_metrics.get("time_to_fine_track_s", ""),
            "failure_reason": r.get("failure_reason") or "",
        }
        rows.append(row)

    # 排序：按指定字段升序，失败实验排最后
    def sort_key(row):
        val = row.get(sort_by, "")
        if val == "" or val is None:
            return (1, float("inf"))  # 失败实验排后面
        return (0, float(val))

    rows.sort(key=sort_key)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[汇总] CSV 已写入: {output_path} ({len(rows)} 行)")


def write_summary_json(output_path: str, summary: dict) -> None:
    """写入 summary.json。"""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[汇总] JSON 已写入: {output_path}")


def write_ranking_table(summary: dict) -> None:
    """打印算法排名表到控制台。"""
    groups = summary.get("groups", [])
    if not groups:
        print("[汇总] 无有效数据，跳过排名表")
        return

    # 按 rms_pixel_error 均值排序（默认只显示 research）
    ranked = []
    for g in groups:
        rms = g.get("stats", {}).get("rms_pixel_error", {})
        mean_rms = rms.get("mean")
        if mean_rms is not None:
            ranked.append((g["algorithm_name"], g["condition_id"], g.get("obs_mode", ""), mean_rms, rms.get("std", 0.0)))

    ranked.sort(key=lambda x: x[3])

    print()
    print("=" * 95)
    print(f"{'排名':<4} {'算法':<30} {'场景':<6} {'模式':<10} {'RMS误差(px)':<15} {'Std':<10}")
    print("-" * 95)
    for i, (alg, cond, obs, rms, std) in enumerate(ranked, 1):
        print(f"{i:<4} {alg:<30} {cond:<6} {obs:<10} {rms:<15.2f} {std:<10.2f}")
    print("=" * 80)
    print()

    # 打印按算法的总体排名（按 obs_mode 分组）
    by_alg = summary.get("by_algorithm", [])
    if by_alg:
        # 从 groups 中提取每个算法的 obs_mode 信息，按模式分组输出
        obs_modes_seen = sorted(set(g.get("obs_mode", "") for g in groups if g.get("obs_mode")))
        for mode in obs_modes_seen:
            # 从 groups 中筛选该模式的数据，按算法聚合
            mode_groups = [g for g in groups if g.get("obs_mode") == mode]
            alg_data = {}
            for g in mode_groups:
                alg = g["algorithm_name"]
                rms_stat = g.get("stats", {}).get("rms_pixel_error", {})
                mean_rms = rms_stat.get("mean")
                if mean_rms is not None:
                    if alg not in alg_data:
                        alg_data[alg] = []
                    alg_data[alg].append(mean_rms)
            alg_ranked = []
            for alg, rms_values in alg_data.items():
                overall_mean = sum(rms_values) / len(rms_values)
                alg_ranked.append((alg, overall_mean, len(rms_values)))
            alg_ranked.sort(key=lambda x: x[1])

            print(f"算法总体排名（{mode} 模式，跨场景均值）:")
            print(f"  {'排名':<4} {'算法':<30} {'RMS均值':<12} {'场景数':<8}")
            print("  " + "-" * 54)
            for i, (alg, rms, n) in enumerate(alg_ranked, 1):
                print(f"  {i:<4} {alg:<30} {rms:<12.2f} {n:<8}")
            print()


def write_grouped_csv(output_dir: str, summary: dict) -> None:
    """写入分组汇总 CSV（按算法×场景分组的统计量）。

    Args:
        output_dir: 输出目录。
        summary: 汇总数据。
    """
    path = os.path.join(output_dir, "summary_grouped.csv")
    groups = summary.get("groups", [])

    columns = [
        "algorithm_name",
        "condition_id",
        "obs_mode",
        "n_seeds",
        "rms_pixel_error_mean",
        "rms_pixel_error_std",
        "capture_success_rate_mean",
        "tracking_efficiency_mean",
        "mean_tracking_error_px_mean",
        "max_tracking_error_px_mean",
        "lock_loss_count_mean",
    ]

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for g in groups:
            stats = g.get("stats", {})
            row = {
                "algorithm_name": g.get("algorithm_name", ""),
                "condition_id": g.get("condition_id", ""),
                "obs_mode": g.get("obs_mode", ""),
                "n_seeds": g.get("n_seeds", 0),
            }
            for metric_key in ["rms_pixel_error", "capture_success_rate", "tracking_efficiency",
                               "mean_tracking_error_px", "max_tracking_error_px", "lock_loss_count"]:
                s = stats.get(metric_key, {})
                col_mean = f"{metric_key}_mean"
                row[col_mean] = s.get("mean", "")
            # 单独处理 std
            row["rms_pixel_error_std"] = stats.get("rms_pixel_error", {}).get("std", "")
            writer.writerow(row)

    print(f"[汇总] 分组 CSV 已写入: {path} ({len(groups)} 行)")


# ============================================================
# 命令行入口
# ============================================================

def main() -> None:
    """命令行入口。"""
    # 修复 Windows 控制台编码
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="结果汇总工具 — 扫描实验输出，生成对比表格",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/summarize_results.py
  python tools/summarize_results.py --input-dir output/experiments
  python tools/summarize_results.py --sort-by mean_tracking_error_px
  python tools/summarize_results.py --format json
        """,
    )
    parser.add_argument(
        "--input-dir", default="output/experiments",
        help="实验输出根目录（默认: output/experiments）",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="汇总输出目录（默认: 与 input-dir 相同）",
    )
    parser.add_argument(
        "--sort-by", default="rms_pixel_error",
        help="CSV 排序字段（默认: rms_pixel_error）",
    )
    parser.add_argument(
        "--format", choices=["all", "csv", "json"], default="all",
        help="输出格式（默认: all）",
    )

    args = parser.parse_args()

    input_dir = os.path.abspath(args.input_dir)
    output_dir = os.path.abspath(args.output_dir) if args.output_dir else input_dir

    if not os.path.isdir(input_dir):
        print(f"[错误] 输入目录不存在: {input_dir}")
        sys.exit(1)

    print(f"[汇总] 扫描目录: {input_dir}")
    results = scan_results(input_dir)
    print(f"[汇总] 找到 {len(results)} 个实验结果")

    if not results:
        print("[汇总] 无实验数据，退出")
        sys.exit(0)

    # 统计失败数
    failed = sum(1 for r in results if r.get("failure_reason"))
    if failed:
        print(f"[汇总] 其中 {failed} 个实验失败")
        for r in results:
            if r.get("failure_reason"):
                print(f"  - {r.get('algorithm_name', '?')}/{r.get('condition_id', '?')}/"
                      f"seed_{r.get('seed', '?')}: {r['failure_reason']}")

    # 计算汇总
    summary = compute_summary(results)

    # 输出
    if args.format in ("all", "csv"):
        write_summary_csv(
            os.path.join(output_dir, "summary.csv"),
            results,
            sort_by=args.sort_by,
        )
        write_grouped_csv(output_dir, summary)

    if args.format in ("all", "json"):
        write_summary_json(
            os.path.join(output_dir, "summary.json"),
            summary,
        )

    # 打印排名表
    write_ranking_table(summary)


if __name__ == "__main__":
    main()
