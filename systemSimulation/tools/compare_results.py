"""结果回归对比工具 — 比较两组实验结果，识别提升项与退化项。

用法:
    # 比较两个结果目录（baseline vs new）
    conda run -n simulation python tools/compare_results.py \\
        --baseline output/experiments --new output/experiments_v2

    # 指定算法和场景过滤
    conda run -n simulation python tools/compare_results.py \\
        --baseline output/experiments --new output/experiments_v2 \\
        --algorithms atp_search_track_baseline rate_pi \\
        --scenarios B1 B2

    # 自定义阈值
    conda run -n simulation python tools/compare_results.py \\
        --baseline output/experiments --new output/experiments_v2 \\
        --rms-threshold 0.10 --capture-threshold 0.02

    # 同目录内比较（新算法 vs 基线算法）
    conda run -n simulation python tools/compare_results.py \\
        --baseline output/experiments --new output/experiments \\
        --baseline-algorithms atp_search_track_baseline \\
        --new-algorithms my_new_algorithm

输出:
    comparison.csv   — 逐项差异对比表
    comparison.json  — 结构化对比结果（含退化/提升标注）
    comparison.md    — 可读的 Markdown 对比报告
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 复用 summarize_results 的扫描逻辑
from tools.summarize_results import scan_results


# ============================================================
# 默认阈值配置
# ============================================================

DEFAULT_THRESHOLDS = {
    "rms_pixel_error": 0.10,        # RMS 误差恶化超过 10% 报警
    "capture_success_rate": 0.02,   # 捕获成功率下降超过 2% 报警
    "tracking_efficiency": 0.05,    # 跟踪效率下降超过 5% 报警
    "reacquire_success_rate": 0.05, # 重捕获成功率下降超过 5% 报警
    "lock_loss_rate": 0.02,         # 丢锁率上升超过 2% 报警
}

# 用于对比的关键指标
COMPARE_METRICS = [
    "rms_pixel_error",
    "capture_success_rate",
    "tracking_efficiency",
    "mean_tracking_error_px",
    "max_tracking_error_px",
    "lock_loss_count",
    "lock_loss_rate",
    "reacquire_time_s",
    "reacquire_success_rate",
    "time_to_acquire_s",
    "time_to_fine_track_s",
]

# 指标方向：True = 越小越好，False = 越大越好
LOWER_IS_BETTER = {
    "rms_pixel_error": True,
    "capture_success_rate": False,
    "tracking_efficiency": False,
    "mean_tracking_error_px": True,
    "max_tracking_error_px": True,
    "lock_loss_count": True,
    "lock_loss_rate": True,
    "reacquire_time_s": True,
    "reacquire_success_rate": False,
    "time_to_acquire_s": True,
    "time_to_fine_track_s": True,
}


def _extract_metric_value(result: dict, metric_key: str):
    """从 result.json 结构中提取指标值，保留合法的 0 值。"""
    metrics = result.get("metrics", {})
    atp_metrics = result.get("atp_metrics", {})

    if metric_key in metrics:
        return metrics.get(metric_key)
    if metric_key in atp_metrics:
        return atp_metrics.get(metric_key)
    return None


# ============================================================
# 数据加载与聚合
# ============================================================

def load_grouped_results(input_dir: str,
                         algorithms: list[str] | None = None,
                         scenarios: list[str] | None = None,
                         obs_mode: str = "research") -> dict:
    """加载结果并按 (algorithm, scenario) 分组聚合。

    Returns:
        {(algorithm, scenario): {"metrics": {key: mean_value}, "n": count, "seeds": [...]}}
    """
    results = scan_results(input_dir)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for r in results:
        if r.get("failure_reason"):
            continue
        alg = r.get("algorithm_name", "")
        cond = r.get("condition_id", "")
        obs = r.get("observation_mode", "")

        if obs_mode and obs != obs_mode:
            continue
        if algorithms and alg not in algorithms:
            continue
        if scenarios and cond not in scenarios:
            continue

        groups[(alg, cond)].append(r)

    aggregated = {}
    for (alg, cond), group_results in sorted(groups.items()):
        metrics_agg = {}
        for key in COMPARE_METRICS:
            values = [_extract_metric_value(r, key) for r in group_results]
            values = [v for v in values if v is not None and isinstance(v, (int, float)) and math.isfinite(v)]
            if values:
                metrics_agg[key] = sum(values) / len(values)

        aggregated[(alg, cond)] = {
            "metrics": metrics_agg,
            "n": len(group_results),
            "seeds": sorted(r.get("seed", -1) for r in group_results),
        }

    return aggregated


# ============================================================
# 对比计算
# ============================================================

def _compare_single(baseline_alg: str, new_alg: str, scenario: str,
                    b_data: dict, n_data: dict, thresholds: dict) -> dict:
    """对比单组数据。baseline_alg 和 new_alg 可以不同（跨算法对比）。"""
    b_metrics = b_data["metrics"]
    n_metrics = n_data["metrics"]

    metric_diffs = []
    for mk in COMPARE_METRICS:
        b_val = b_metrics.get(mk)
        n_val = n_metrics.get(mk)

        if b_val is None and n_val is None:
            continue

        diff = None
        rel_change = None
        verdict = "neutral"

        if b_val is not None and n_val is not None:
            diff = n_val - b_val
            if abs(b_val) > 1e-9:
                rel_change = diff / abs(b_val)
            lower_better = LOWER_IS_BETTER.get(mk, True)
            threshold = thresholds.get(mk)

            if lower_better:
                improved = diff < -1e-9
                regressed = diff > 1e-9
            else:
                improved = diff > 1e-9
                regressed = diff < -1e-9

            if improved:
                verdict = "improved"
            elif regressed and threshold is not None and rel_change is not None:
                if lower_better and rel_change > threshold:
                    verdict = "regression_warning"
                elif not lower_better and abs(rel_change) > threshold:
                    verdict = "regression_warning"
                else:
                    verdict = "regressed"
            elif regressed:
                verdict = "regressed"

        metric_diffs.append({
            "metric": mk,
            "baseline": b_val,
            "new": n_val,
            "diff": round(diff, 4) if diff is not None else None,
            "rel_change": round(rel_change, 4) if rel_change is not None else None,
            "verdict": verdict,
        })

    # 跨算法时显示 "alg_a vs alg_b"
    if baseline_alg == new_alg:
        alg_label = baseline_alg
    else:
        alg_label = f"{baseline_alg} vs {new_alg}"

    return {
        "algorithm": alg_label,
        "baseline_algorithm": baseline_alg,
        "new_algorithm": new_alg,
        "scenario": scenario,
        "baseline_n": b_data["n"],
        "new_n": n_data["n"],
        "metrics": metric_diffs,
    }


def _collect_verdicts(comp: dict, improvements: list, regressions: list, warnings: list) -> None:
    """从单个对比结果中收集提升/退化项。"""
    for m in comp["metrics"]:
        if m["verdict"] == "improved":
            improvements.append({"algorithm": comp["algorithm"], "scenario": comp["scenario"], **m})
        elif m["verdict"] in ("regressed", "regression_warning"):
            regressions.append({"algorithm": comp["algorithm"], "scenario": comp["scenario"], **m})
            if m["verdict"] == "regression_warning":
                warnings.append({"algorithm": comp["algorithm"], "scenario": comp["scenario"], **m})

def compare_groups(baseline: dict, new: dict,
                   thresholds: dict | None = None,
                   cross_algorithm: bool = False) -> dict:
    """对比两组聚合结果。

    Args:
        baseline: {(alg, cond): {"metrics": {...}, "n": int}} 基线数据
        new: 同上，新数据
        thresholds: 指标报警阈值 {metric_key: relative_change_threshold}
        cross_algorithm: 是否跨算法对比（只按场景匹配）

    Returns:
        结构化对比结果
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    comparisons = []
    improvements = []
    regressions = []
    warnings = []
    only_in_baseline = []
    only_in_new = []

    if cross_algorithm:
        # 跨算法模式：按场景匹配
        baseline_by_scenario: dict[str, list] = defaultdict(list)
        new_by_scenario: dict[str, list] = defaultdict(list)
        for (alg, cond), data in baseline.items():
            baseline_by_scenario[cond].append((alg, data))
        for (alg, cond), data in new.items():
            new_by_scenario[cond].append((alg, data))

        all_scenarios = sorted(set(list(baseline_by_scenario.keys()) + list(new_by_scenario.keys())))

        for cond in all_scenarios:
            b_entries = baseline_by_scenario.get(cond, [])
            n_entries = new_by_scenario.get(cond, [])

            if b_entries and not n_entries:
                for alg, _ in b_entries:
                    only_in_baseline.append({"algorithm": alg, "scenario": cond})
                continue
            if n_entries and not b_entries:
                for alg, _ in n_entries:
                    only_in_new.append({"algorithm": alg, "scenario": cond})
                continue

            # 每对 (baseline_alg, new_alg) 都做对比
            for b_alg, b_data in b_entries:
                for n_alg, n_data in n_entries:
                    comp = _compare_single(b_alg, n_alg, cond, b_data, n_data, thresholds)
                    comparisons.append(comp)
                    _collect_verdicts(comp, improvements, regressions, warnings)
    else:
        # 同算法模式：按 (algorithm, scenario) 匹配
        all_keys = sorted(set(list(baseline.keys()) + list(new.keys())))

        for key in all_keys:
            alg, cond = key
            b_data = baseline.get(key)
            n_data = new.get(key)

            if b_data and not n_data:
                only_in_baseline.append({"algorithm": alg, "scenario": cond})
                continue
            if n_data and not b_data:
                only_in_new.append({"algorithm": alg, "scenario": cond})
                continue

            comp = _compare_single(alg, alg, cond, b_data, n_data, thresholds)
            comparisons.append(comp)
            _collect_verdicts(comp, improvements, regressions, warnings)

    # 按算法汇总
    by_algorithm = _summarize_by_algorithm(comparisons)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_comparisons": len(comparisons),
        "n_improvements": len(improvements),
        "n_regressions": len(regressions),
        "n_warnings": len(warnings),
        "improvements": improvements,
        "regressions": regressions,
        "warnings": warnings,
        "only_in_baseline": only_in_baseline,
        "only_in_new": only_in_new,
        "by_algorithm": by_algorithm,
        "comparisons": comparisons,
    }


def _summarize_by_algorithm(comparisons: list[dict]) -> list[dict]:
    """按算法汇总对比结果。"""
    alg_data: dict[str, dict] = defaultdict(lambda: {"improved": 0, "regressed": 0, "neutral": 0, "warnings": 0})

    for comp in comparisons:
        alg = comp["algorithm"]
        for m in comp["metrics"]:
            v = m["verdict"]
            if v == "improved":
                alg_data[alg]["improved"] += 1
            elif v in ("regressed", "regression_warning"):
                alg_data[alg]["regressed"] += 1
                if v == "regression_warning":
                    alg_data[alg]["warnings"] += 1
            else:
                alg_data[alg]["neutral"] += 1

    result = []
    for alg, data in sorted(alg_data.items()):
        result.append({"algorithm": alg, **data})
    return result


# ============================================================
# 输出
# ============================================================

def write_comparison_csv(output_path: str, comparison: dict) -> None:
    """写入逐项差异对比 CSV。"""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    columns = [
        "algorithm", "scenario", "metric",
        "baseline", "new", "diff", "rel_change_pct", "verdict",
    ]

    rows = []
    for comp in comparison["comparisons"]:
        for m in comp["metrics"]:
            rows.append({
                "algorithm": comp["algorithm"],
                "scenario": comp["scenario"],
                "metric": m["metric"],
                "baseline": _fmt_val(m["baseline"]),
                "new": _fmt_val(m["new"]),
                "diff": _fmt_val(m["diff"]),
                "rel_change_pct": _fmt_pct(m["rel_change"]),
                "verdict": m["verdict"],
            })

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[对比] CSV 已写入: {output_path} ({len(rows)} 行)")


def write_comparison_json(output_path: str, comparison: dict) -> None:
    """写入结构化对比 JSON。"""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=2, ensure_ascii=False, default=str)
    print(f"[对比] JSON 已写入: {output_path}")


def write_comparison_md(output_path: str, comparison: dict,
                        baseline_dir: str, new_dir: str) -> None:
    """写入可读的 Markdown 对比报告。"""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    lines = []
    lines.append("# 实验结果回归对比报告\n")
    lines.append(f"- 基线目录: `{baseline_dir}`")
    lines.append(f"- 新结果目录: `{new_dir}`")
    lines.append(f"- 生成时间: {comparison['generated_at']}")
    lines.append("")

    # 摘要
    lines.append("## 摘要\n")
    lines.append(f"| 项目 | 数量 |")
    lines.append(f"|------|------|")
    lines.append(f"| 对比组合数 | {comparison['total_comparisons']} |")
    lines.append(f"| 提升项 | {comparison['n_improvements']} |")
    lines.append(f"| 退化项 | {comparison['n_regressions']} |")
    lines.append(f"| 超阈值报警 | {comparison['n_warnings']} |")
    lines.append("")

    # 报警项
    if comparison["warnings"]:
        lines.append("## 超阈值报警\n")
        lines.append("| 算法 | 场景 | 指标 | 基线 | 新值 | 变化 | 判定 |")
        lines.append("|------|------|------|------|------|------|------|")
        for w in comparison["warnings"]:
            lines.append(
                f"| {w['algorithm']} | {w['scenario']} | {w['metric']} "
                f"| {_fmt_val(w['baseline'])} | {_fmt_val(w['new'])} "
                f"| {_fmt_pct(w['rel_change'])} | {w['verdict']} |"
            )
        lines.append("")

    # 退化项
    if comparison["regressions"]:
        lines.append("## 退化项\n")
        lines.append("| 算法 | 场景 | 指标 | 基线 | 新值 | 变化 | 判定 |")
        lines.append("|------|------|------|------|------|------|------|")
        for r in comparison["regressions"]:
            lines.append(
                f"| {r['algorithm']} | {r['scenario']} | {r['metric']} "
                f"| {_fmt_val(r['baseline'])} | {_fmt_val(r['new'])} "
                f"| {_fmt_pct(r['rel_change'])} | {r['verdict']} |"
            )
        lines.append("")

    # 提升项
    if comparison["improvements"]:
        lines.append("## 提升项\n")
        lines.append("| 算法 | 场景 | 指标 | 基线 | 新值 | 变化 |")
        lines.append("|------|------|------|------|------|------|")
        for imp in comparison["improvements"]:
            lines.append(
                f"| {imp['algorithm']} | {imp['scenario']} | {imp['metric']} "
                f"| {_fmt_val(imp['baseline'])} | {_fmt_val(imp['new'])} "
                f"| {_fmt_pct(imp['rel_change'])} |"
            )
        lines.append("")

    # 逐算法汇总
    if comparison["by_algorithm"]:
        lines.append("## 按算法汇总\n")
        lines.append("| 算法 | 提升项数 | 退化项数 | 中性项数 | 超阈值报警 |")
        lines.append("|------|----------|----------|----------|------------|")
        for a in comparison["by_algorithm"]:
            lines.append(
                f"| {a['algorithm']} | {a['improved']} | {a['regressed']} "
                f"| {a['neutral']} | {a['warnings']} |"
            )
        lines.append("")

    # 仅在基线 / 仅在新结果中
    if comparison["only_in_baseline"]:
        lines.append("## 仅在基线中存在的组合\n")
        for item in comparison["only_in_baseline"]:
            lines.append(f"- {item['algorithm']} / {item['scenario']}")
        lines.append("")

    if comparison["only_in_new"]:
        lines.append("## 仅在新结果中存在的组合\n")
        for item in comparison["only_in_new"]:
            lines.append(f"- {item['algorithm']} / {item['scenario']}")
        lines.append("")

    # 完整对比表
    lines.append("## 完整对比表\n")
    lines.append("| 算法 | 场景 | 指标 | 基线 | 新值 | 差异 | 变化率 | 判定 |")
    lines.append("|------|------|------|------|------|------|--------|------|")
    for comp in comparison["comparisons"]:
        for m in comp["metrics"]:
            lines.append(
                f"| {comp['algorithm']} | {comp['scenario']} | {m['metric']} "
                f"| {_fmt_val(m['baseline'])} | {_fmt_val(m['new'])} "
                f"| {_fmt_val(m['diff'])} | {_fmt_pct(m['rel_change'])} "
                f"| {m['verdict']} |"
            )
    lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[对比] Markdown 报告已写入: {output_path}")


def _fmt_val(v) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _fmt_pct(v) -> str:
    if v is None:
        return "N/A"
    return f"{v * 100:+.2f}%"


# ============================================================
# 命令行入口
# ============================================================

def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="结果回归对比工具 — 比较两组实验结果，识别提升项与退化项",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/compare_results.py --baseline output/experiments --new output/experiments_v2
  python tools/compare_results.py --baseline output/experiments --new output/experiments \\
      --baseline-algorithms atp_search_track_baseline --new-algorithms my_algo
  python tools/compare_results.py --baseline output/experiments --new output/experiments \\
      --algorithms atp_search_track_baseline rate_pi --scenarios B1 B2
        """,
    )
    parser.add_argument("--baseline", required=True, help="基线结果目录")
    parser.add_argument("--new", required=True, help="新结果目录")
    parser.add_argument("--output-dir", default=None, help="对比结果输出目录（默认: 新结果目录）")
    parser.add_argument("--algorithms", nargs="+", default=None, help="只对比指定算法")
    parser.add_argument("--scenarios", nargs="+", default=None, help="只对比指定场景")
    parser.add_argument("--obs-mode", default="research", help="观测模式过滤（默认: research）")
    parser.add_argument("--baseline-algorithms", nargs="+", default=None,
                        help="基线侧只取这些算法（用于同目录内不同算法对比）")
    parser.add_argument("--new-algorithms", nargs="+", default=None,
                        help="新侧只取这些算法（用于同目录内不同算法对比）")
    parser.add_argument("--rms-threshold", type=float, default=0.10,
                        help="RMS 误差退化报警阈值（相对变化，默认 0.10）")
    parser.add_argument("--capture-threshold", type=float, default=0.02,
                        help="捕获成功率退化报警阈值（默认 0.02）")
    parser.add_argument("--efficiency-threshold", type=float, default=0.05,
                        help="跟踪效率退化报警阈值（默认 0.05）")

    args = parser.parse_args()

    baseline_dir = os.path.abspath(args.baseline)
    new_dir = os.path.abspath(args.new)
    output_dir = os.path.abspath(args.output_dir) if args.output_dir else new_dir

    if not os.path.isdir(baseline_dir):
        print(f"[错误] 基线目录不存在: {baseline_dir}")
        sys.exit(1)
    if not os.path.isdir(new_dir):
        print(f"[错误] 新结果目录不存在: {new_dir}")
        sys.exit(1)

    # 确定对比的算法集合
    baseline_algs = args.baseline_algorithms or args.algorithms
    new_algs = args.new_algorithms or args.algorithms

    # 检测跨算法模式
    cross_algorithm = (baseline_algs is not None and new_algs is not None
                       and set(baseline_algs) != set(new_algs))

    thresholds = {
        **DEFAULT_THRESHOLDS,
        "rms_pixel_error": args.rms_threshold,
        "capture_success_rate": args.capture_threshold,
        "tracking_efficiency": args.efficiency_threshold,
    }

    print(f"[对比] 基线目录: {baseline_dir}")
    print(f"[对比] 新结果目录: {new_dir}")

    # 加载并聚合
    baseline_data = load_grouped_results(baseline_dir, baseline_algs, args.scenarios, args.obs_mode)
    new_data = load_grouped_results(new_dir, new_algs, args.scenarios, args.obs_mode)

    print(f"[对比] 基线组合数: {len(baseline_data)}")
    print(f"[对比] 新结果组合数: {len(new_data)}")

    if not baseline_data and not new_data:
        print("[对比] 无有效数据，退出")
        sys.exit(0)

    # 执行对比
    comparison = compare_groups(baseline_data, new_data, thresholds, cross_algorithm=cross_algorithm)

    # 输出
    write_comparison_csv(os.path.join(output_dir, "comparison.csv"), comparison)
    write_comparison_json(os.path.join(output_dir, "comparison.json"), comparison)
    write_comparison_md(os.path.join(output_dir, "comparison.md"), comparison, baseline_dir, new_dir)

    # 打印摘要
    print()
    print("=" * 60)
    print(f"  对比组合: {comparison['total_comparisons']}")
    print(f"  提升项:   {comparison['n_improvements']}")
    print(f"  退化项:   {comparison['n_regressions']}")
    print(f"  超阈值:   {comparison['n_warnings']}")
    print("=" * 60)

    if comparison["warnings"]:
        print("\n超阈值报警:")
        for w in comparison["warnings"]:
            print(f"  [!] {w['algorithm']}/{w['scenario']} {w['metric']}: "
                  f"{_fmt_val(w['baseline'])} -> {_fmt_val(w['new'])} ({_fmt_pct(w['rel_change'])})")

    if comparison["regressions"]:
        print(f"\n退化项详情:")
        for r in comparison["regressions"]:
            print(f"  [-] {r['algorithm']}/{r['scenario']} {r['metric']}: "
                  f"{_fmt_val(r['baseline'])} -> {_fmt_val(r['new'])} ({_fmt_pct(r['rel_change'])})")


if __name__ == "__main__":
    main()
