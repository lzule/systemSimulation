"""对比可视化工具 — 生成跨算法、跨场景的研究对比图。

生成的图:
  1. 同场景多算法误差曲线叠加图
  2. 算法×场景 RMS 热力图
  3. 多指标算法排名分组柱状图
  4. 分时段误差箱线图（需指定场景和基线算法）

用法:
    # 生成全部对比图
    conda run -n simulation python tools/plot_comparison.py

    # 指定目录和算法
    conda run -n simulation python tools/plot_comparison.py \\
        --input-dir output/experiments \\
        --algorithms atp_search_track_baseline rate_pi alpha_beta_tracker

    # 只生成指定场景的误差叠加图
    conda run -n simulation python tools/plot_comparison.py \\
        --scenarios B1 B2 --plots overlay

    # 生成分时段误差箱线图
    conda run -n simulation python tools/plot_comparison.py \\
        --plots phase-box --baseline-algorithm atp_search_track_baseline

输出:
    PNG 图到指定输出目录
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.summarize_results import scan_results

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# 中文字体设置
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

# 算法配色方案
ALGORITHM_COLORS = {
    "atp_search_track_baseline": "#2196F3",
    "baseline_rate_p": "#4CAF50",
    "rate_pi": "#FF9800",
    "alpha_beta_tracker": "#F44336",
    "linear_kf_tracker": "#9C27B0",
}

ALGORITHM_LABELS = {
    "atp_search_track_baseline": "ATP基线",
    "baseline_rate_p": "Rate-P",
    "rate_pi": "Rate-PI",
    "alpha_beta_tracker": "Alpha-Beta",
    "linear_kf_tracker": "Linear-KF",
}

SCENARIO_LABELS = {
    "B1": "B1 (sin 100m)",
    "B2": "B2 (sin 100m + delay)",
    "B3": "B3 (sin 80m + delay)",
}


def _get_color(alg: str) -> str:
    return ALGORITHM_COLORS.get(alg, "#607D8B")


def _get_label(alg: str) -> str:
    return ALGORITHM_LABELS.get(alg, alg)


# ============================================================
# 数据加载
# ============================================================

def load_metrics_for_overlay(input_dir: str, scenario: str,
                             algorithms: list[str] | None = None,
                             seed: int = 42,
                             obs_mode: str = "research") -> dict[str, list[dict]]:
    """加载指定场景下各算法的 metrics.csv（取指定 seed）。"""
    results = scan_results(input_dir)
    paths: dict[str, str] = {}

    for r in results:
        if r.get("failure_reason"):
            continue
        alg = r.get("algorithm_name", "")
        cond = r.get("condition_id", "")
        obs = r.get("observation_mode", "")
        s = r.get("seed", -1)

        if cond != scenario or obs != obs_mode or s != seed:
            continue
        if algorithms and alg not in algorithms:
            continue

        source = r.get("_source_path", "")
        paths[alg] = os.path.join(input_dir, os.path.dirname(source), "metrics.csv")

    data = {}
    for alg, csv_path in paths.items():
        records = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                err = row.get("pixel_error_total", "")
                ts = row.get("timestamp", "")
                state = row.get("atp_state", "")
                if err and ts:
                    records.append({
                        "timestamp": float(ts),
                        "pixel_error_total": float(err),
                        "atp_state": state.strip(),
                    })
        data[alg] = records

    return data


def load_summary_grouped(input_dir: str) -> list[dict]:
    """加载 summary_grouped.csv。"""
    import json
    summary_path = os.path.join(input_dir, "summary.json")
    if not os.path.isfile(summary_path):
        return []

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)
    return summary.get("groups", [])


# ============================================================
# 绘图函数
# ============================================================

def plot_error_overlay(data: dict[str, list[dict]], scenario: str,
                       output_path: str) -> None:
    """同场景多算法误差曲线叠加图。"""
    fig, ax = plt.subplots(figsize=(12, 5))

    for alg in sorted(data.keys()):
        records = data[alg]
        if not records:
            continue
        ts = [r["timestamp"] for r in records]
        errs = [r["pixel_error_total"] for r in records]
        ax.plot(ts, errs, label=_get_label(alg), color=_get_color(alg),
                alpha=0.8, linewidth=0.8)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Pixel Error (px)")
    ax.set_title(f"Algorithm Error Comparison — {SCENARIO_LABELS.get(scenario, scenario)}")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"[图] 误差叠加图已保存: {output_path}")


def plot_rms_heatmap(groups: list[dict], output_path: str) -> None:
    """算法×场景 RMS 热力图。"""
    if not groups:
        print("[图] 无数据，跳过热力图")
        return

    # 提取算法和场景列表
    algorithms = sorted(set(g["algorithm_name"] for g in groups))
    scenarios = sorted(set(g["condition_id"] for g in groups))

    matrix = np.full((len(algorithms), len(scenarios)), np.nan)
    for g in groups:
        alg = g["algorithm_name"]
        cond = g["condition_id"]
        rms = g.get("stats", {}).get("rms_pixel_error", {}).get("mean")
        if rms is not None:
            i = algorithms.index(alg)
            j = scenarios.index(cond)
            matrix[i][j] = rms

    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(matrix, cmap="RdYlGn_r", aspect="auto")

    ax.set_xticks(range(len(scenarios)))
    ax.set_xticklabels([SCENARIO_LABELS.get(s, s) for s in scenarios], fontsize=9)
    ax.set_yticks(range(len(algorithms)))
    ax.set_yticklabels([_get_label(a) for a in algorithms], fontsize=9)

    # 在格子中标注数值
    for i in range(len(algorithms)):
        for j in range(len(scenarios)):
            val = matrix[i][j]
            if not np.isnan(val):
                color = "white" if val > 50 else "black"
                ax.text(j, i, f"{val:.1f}", ha="center", va="center",
                        color=color, fontsize=10, fontweight="bold")

    ax.set_title("RMS Pixel Error by Algorithm × Scenario")
    fig.colorbar(im, ax=ax, label="RMS Error (px)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"[图] 热力图已保存: {output_path}")


def plot_ranking_bar(groups: list[dict], output_path: str) -> None:
    """多指标算法排名分组柱状图。

    每个子图只展示一个指标，避免不同量纲共用同一 y 轴造成误导。
    """
    if not groups:
        print("[图] 无数据，跳过排名图")
        return

    algorithms = sorted(set(g["algorithm_name"] for g in groups))
    scenarios = sorted(set(g["condition_id"] for g in groups))
    metrics_to_show = ["rms_pixel_error", "tracking_efficiency"]
    metric_labels = ["RMS Error (px)", "Tracking Efficiency"]

    fig, axes = plt.subplots(
        len(metrics_to_show), len(scenarios),
        figsize=(5 * len(scenarios), 4 * len(metrics_to_show)),
        squeeze=False,
        sharey="row",
    )

    for i, (mk, ml) in enumerate(zip(metrics_to_show, metric_labels)):
        for j, scenario in enumerate(scenarios):
            ax = axes[i][j]
            x = np.arange(len(algorithms))
            values = []
            colors = []

            for alg in algorithms:
                for g in groups:
                    if g["algorithm_name"] == alg and g["condition_id"] == scenario:
                        v = g.get("stats", {}).get(mk, {}).get("mean", 0)
                        values.append(v if v is not None else 0)
                        break
                else:
                    values.append(0)
                colors.append(_get_color(alg))

            bars = ax.bar(x, values, color=colors, alpha=0.85)
            for bar, val in zip(bars, values):
                if val > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_height(),
                        f"{val:.1f}",
                        ha="center",
                        va="bottom",
                        fontsize=7,
                    )

            ax.set_xticks(x)
            ax.set_xticklabels([_get_label(a) for a in algorithms], fontsize=8, rotation=30)
            ax.set_title(f"{SCENARIO_LABELS.get(scenario, scenario)}\n{ml}", fontsize=10)
            ax.grid(True, alpha=0.3, axis="y")
            if j == 0:
                ax.set_ylabel(ml)

    fig.suptitle("Algorithm Performance by Scenario", fontsize=12)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"[图] 排名柱状图已保存: {output_path}")


def plot_phase_boxplot(data: dict[str, list[dict]], scenario: str,
                       baseline_algorithm: str | None,
                       output_path: str) -> None:
    """分时段误差箱线图。"""
    states_order = ["SEARCH", "ACQUIRE", "TRACK_COARSE", "TRACK_FINE", "REACQUIRE"]
    algs = sorted(data.keys(), key=lambda alg: (alg != baseline_algorithm, alg))
    if not algs:
        return

    n_states = len(states_order)
    n_algs = len(algs)

    fig, ax = plt.subplots(figsize=(12, 5))
    box_data = []
    positions = []
    colors = []
    xtick_positions = []
    xtick_labels = []

    pos = 0
    for state in states_order:
        state_positions = []
        for i, alg in enumerate(algs):
            errors = [r["pixel_error_total"] for r in data[alg]
                      if r["atp_state"] == state and math.isfinite(r["pixel_error_total"])]
            if errors:
                box_data.append(errors)
                positions.append(pos)
                colors.append(_get_color(alg))
                state_positions.append(pos)
            pos += 1
        if state_positions:
            xtick_positions.append(sum(state_positions) / len(state_positions))
            xtick_labels.append(state)
        pos += 1  # 状态间隔

    if not box_data:
        plt.close(fig)
        return

    bp = ax.boxplot(box_data, positions=positions, patch_artist=True, showfliers=False, widths=0.6)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    # 图例
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=_get_color(alg), alpha=0.6, label=_get_label(alg))
                       for alg in algs]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=8)

    ax.set_xticks(xtick_positions)
    ax.set_xticklabels(xtick_labels, rotation=20, fontsize=9)
    ax.set_ylabel("Pixel Error (px)")
    ax.set_xlabel("ATP Phase")
    ax.set_title(f"Phase-wise Error Distribution — {SCENARIO_LABELS.get(scenario, scenario)}")
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"[图] 分时段箱线图已保存: {output_path}")


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
        description="对比可视化工具 — 生成跨算法、跨场景的研究对比图",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/plot_comparison.py
  python tools/plot_comparison.py --scenarios B1 B2
  python tools/plot_comparison.py --plots overlay heatmap
  python tools/plot_comparison.py --plots phase-box --baseline-algorithm atp_search_track_baseline
        """,
    )
    parser.add_argument("--input-dir", default="output/experiments", help="实验结果目录")
    parser.add_argument("--output-dir", default=None, help="图片输出目录（默认: input-dir/plots）")
    parser.add_argument("--algorithms", nargs="+", default=None, help="只画指定算法")
    parser.add_argument("--scenarios", nargs="+", default=None, help="只画指定场景")
    parser.add_argument("--seed", type=int, default=42, help="叠加图使用的 seed（默认: 42）")
    parser.add_argument("--baseline-algorithm", default="atp_search_track_baseline",
                        help="基线算法（默认: atp_search_track_baseline）")
    parser.add_argument("--plots", nargs="+",
                        choices=["overlay", "heatmap", "ranking", "phase-box", "all"],
                        default=["all"], help="要生成的图类型（默认: all）")

    args = parser.parse_args()
    input_dir = os.path.abspath(args.input_dir)
    output_dir = os.path.abspath(args.output_dir) if args.output_dir else os.path.join(input_dir, "plots")
    os.makedirs(output_dir, exist_ok=True)

    if not os.path.isdir(input_dir):
        print(f"[错误] 输入目录不存在: {input_dir}")
        sys.exit(1)

    plot_types = set(args.plots)
    if "all" in plot_types:
        plot_types = {"overlay", "heatmap", "ranking", "phase-box"}

    scenarios = args.scenarios or ["B1", "B2", "B3"]

    # 加载汇总数据
    groups = load_summary_grouped(input_dir)
    if args.algorithms:
        groups = [g for g in groups if g["algorithm_name"] in args.algorithms]

    # 1. 热力图
    if "heatmap" in plot_types:
        plot_rms_heatmap(groups, os.path.join(output_dir, "rms_heatmap.png"))

    # 2. 排名柱状图
    if "ranking" in plot_types:
        plot_ranking_bar(groups, os.path.join(output_dir, "ranking_bar.png"))

    # 3. 误差叠加图 + 分时段箱线图（需要 metrics.csv）
    for scenario in scenarios:
        data = load_metrics_for_overlay(input_dir, scenario, args.algorithms, args.seed)
        if not data:
            print(f"[图] 场景 {scenario} 无数据，跳过")
            continue

        if "overlay" in plot_types:
            plot_error_overlay(data, scenario,
                               os.path.join(output_dir, f"error_overlay_{scenario}.png"))

        if "phase-box" in plot_types:
            plot_phase_boxplot(data, scenario, args.baseline_algorithm,
                               os.path.join(output_dir, f"phase_boxplot_{scenario}.png"))

    print(f"\n[图] 全部图片已保存到: {output_dir}")


if __name__ == "__main__":
    main()
