"""算法诊断工具 — 分析算法性能，定位退化原因。

基于 metrics.csv 中的逐 tick 数据，完成：
  1. 误差分时段分解（按 ATP 状态分段统计）
  2. ATP 状态转换对比（状态驻留时间、转换次数）
  3. 控制行为分析（命令振荡、饱和检测）
  4. 预测相关代理分析（基于误差趋势、发散检测做间接判断）

用法:
    # 诊断单个算法在指定场景的表现
    conda run -n simulation python tools/diagnose_algorithm.py \\
        --algorithm linear_kf_tracker --scenario B1 \\
        --baseline-algorithm atp_search_track_baseline

    # 诊断所有退化算法（与基线比较）
    conda run -n simulation python tools/diagnose_algorithm.py \\
        --baseline-algorithm atp_search_track_baseline \\
        --input-dir output/experiments

    # 输出到指定目录
    conda run -n simulation python tools/diagnose_algorithm.py \\
        --algorithm alpha_beta_tracker --scenario B3 \\
        --output-dir output/diagnosis

输出:
    diagnosis.md    — 可读诊断报告
    diagnosis.json  — 结构化诊断数据
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.summarize_results import scan_results


# ============================================================
# 数据加载
# ============================================================

def load_metrics_csv(csv_path: str) -> list[dict]:
    """加载 metrics.csv 为字典列表。"""
    records = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record = {
                "timestamp": float(row["timestamp"]),
                "pixel_error_x": _safe_float(row.get("pixel_error_x")),
                "pixel_error_y": _safe_float(row.get("pixel_error_y")),
                "pixel_error_total": _safe_float(row.get("pixel_error_total")),
                "detection_found": row.get("detection_found", "False").strip().lower() == "true",
                "atp_state": row.get("atp_state", "N/A").strip(),
                "yaw_rate_cmd": _safe_float(row.get("yaw_rate_cmd")),
                "pitch_rate_cmd": _safe_float(row.get("pitch_rate_cmd")),
            }
            records.append(record)
    return records


def find_metrics_paths(input_dir: str,
                       algorithm: str | None = None,
                       scenario: str | None = None,
                       obs_mode: str = "research") -> list[dict]:
    """查找匹配的 metrics.csv 文件路径。

    Returns:
        [{"path": ..., "algorithm": ..., "scenario": ..., "seed": ...}, ...]
    """
    results = scan_results(input_dir)
    paths = []

    for r in results:
        if r.get("failure_reason"):
            continue
        alg = r.get("algorithm_name", "")
        cond = r.get("condition_id", "")
        obs = r.get("observation_mode", "")
        seed = r.get("seed", -1)

        if obs_mode and obs != obs_mode:
            continue
        if algorithm and alg != algorithm:
            continue
        if scenario and cond != scenario:
            continue

        source = r.get("_source_path", "")
        metrics_path = os.path.join(input_dir, os.path.dirname(source), "metrics.csv")
        if os.path.isfile(metrics_path):
            paths.append({
                "path": metrics_path,
                "algorithm": alg,
                "scenario": cond,
                "seed": seed,
            })

    return paths


# ============================================================
# 诊断分析
# ============================================================

def diagnose_phase_errors(records: list[dict]) -> dict:
    """误差分时段分解：按 ATP 状态分段统计。

    Returns:
        {state: {"mean": ..., "std": ..., "max": ..., "rms": ..., "duration_s": ..., "n_ticks": ...}}
    """
    by_state: dict[str, list[float]] = defaultdict(list)
    by_state_time: dict[str, list[float]] = defaultdict(list)

    for r in records:
        err = r["pixel_error_total"]
        state = r["atp_state"]
        if math.isfinite(err) and state != "N/A":
            by_state[state].append(err)
            by_state_time[state].append(r["timestamp"])

    result = {}
    dt = 0.005  # 200 fps
    for state in ["SEARCH", "ACQUIRE", "TRACK_COARSE", "TRACK_FINE", "LOST", "REACQUIRE"]:
        errors = by_state.get(state, [])
        if not errors:
            result[state] = None
            continue
        result[state] = {
            "mean": round(sum(errors) / len(errors), 2),
            "std": round(_std(errors), 2),
            "max": round(max(errors), 2),
            "rms": round(math.sqrt(sum(e ** 2 for e in errors) / len(errors)), 2),
            "n_ticks": len(errors),
            "duration_s": round(len(errors) * dt, 2),
            "pct_time": 0.0,  # 后面统一计算
        }

    total_ticks = sum((v["n_ticks"] for v in result.values() if v), 0)
    if total_ticks > 0:
        for v in result.values():
            if v:
                v["pct_time"] = round(v["n_ticks"] / total_ticks * 100, 1)

    return result


def diagnose_atp_transitions(records: list[dict]) -> dict:
    """ATP 状态转换分析。

    Returns:
        {"transitions": [(from, to, count)], "state_durations": {state: [duration_s]},
         "transition_timeline": [(time, from, to)], "summary": {...}}
    """
    transitions = []
    transition_counts: dict[tuple[str, str], int] = Counter()
    state_segments: dict[str, list[float]] = defaultdict(list)

    prev_state = None
    seg_start = None

    for r in records:
        state = r["atp_state"]
        ts = r["timestamp"]

        if state != prev_state:
            if prev_state is not None and seg_start is not None:
                transitions.append((ts, prev_state, state))
                transition_counts[(prev_state, state)] += 1
                duration = ts - seg_start
                state_segments[prev_state].append(round(duration, 4))
            prev_state = state
            seg_start = ts

    # 最后一段
    if prev_state is not None and seg_start is not None and records:
        final_ts = records[-1]["timestamp"]
        state_segments[prev_state].append(round(final_ts - seg_start, 4))

    # 汇总
    state_durations = {}
    for state, durations in state_segments.items():
        state_durations[state] = {
            "count": len(durations),
            "mean_s": round(sum(durations) / len(durations), 4) if durations else 0,
            "total_s": round(sum(durations), 4),
            "max_s": round(max(durations), 4) if durations else 0,
        }

    summary = {
        "total_transitions": sum(transition_counts.values()),
        "lost_events": transition_counts.get(("TRACK_FINE", "LOST"), 0)
                     + transition_counts.get(("TRACK_COARSE", "LOST"), 0),
        "reacquire_events": transition_counts.get(("LOST", "REACQUIRE"), 0),
        "reacquire_to_search": transition_counts.get(("REACQUIRE", "SEARCH"), 0),
        "reacquire_to_acquire": transition_counts.get(("REACQUIRE", "ACQUIRE"), 0),
    }

    return {
        "transition_counts": [{"from": f, "to": t, "count": c}
                              for (f, t), c in sorted(transition_counts.items())],
        "state_durations": state_durations,
        "summary": summary,
        "transition_timeline": [(round(t, 4), f, to) for t, f, to in transitions[:50]],  # 限制输出长度
    }


def diagnose_control_behavior(records: list[dict]) -> dict:
    """控制行为分析：振荡、饱和、命令变化幅度。"""
    yaw_cmds = [r["yaw_rate_cmd"] for r in records if math.isfinite(r["yaw_rate_cmd"])]
    pitch_cmds = [r["pitch_rate_cmd"] for r in records if math.isfinite(r["pitch_rate_cmd"])]

    def _analyze_cmds(cmds: list[float], name: str) -> dict:
        if not cmds:
            return {"axis": name, "available": False}

        mean_cmd = sum(cmds) / len(cmds)
        max_abs = max(abs(c) for c in cmds)

        # 命令变化频率（相邻 tick 方向翻转 = 一次振荡）
        reversals = sum(1 for i in range(1, len(cmds)) if cmds[i] * cmds[i - 1] < 0)
        reversal_rate = reversals / max(len(cmds) - 1, 1)

        # 命令幅度标准差
        cmd_std = _std(cmds)

        # 饱和检测：连续超过 80% 最大幅度的 tick 占比
        saturation_threshold = max_abs * 0.8 if max_abs > 0 else 0
        saturated_ticks = sum(1 for c in cmds if abs(c) > saturation_threshold and saturation_threshold > 0)
        saturation_pct = saturated_ticks / len(cmds) * 100

        # 零命令占比（控制未介入）
        zero_ticks = sum(1 for c in cmds if abs(c) < 0.01)
        zero_pct = zero_ticks / len(cmds) * 100

        return {
            "axis": name,
            "available": True,
            "mean": round(mean_cmd, 2),
            "std": round(cmd_std, 2),
            "max_abs": round(max_abs, 2),
            "reversal_rate": round(reversal_rate, 4),
            "reversal_count": reversals,
            "saturation_pct": round(saturation_pct, 1),
            "zero_cmd_pct": round(zero_pct, 1),
        }

    return {
        "yaw": _analyze_cmds(yaw_cmds, "yaw"),
        "pitch": _analyze_cmds(pitch_cmds, "pitch"),
    }


def diagnose_prediction_behavior(records: list[dict]) -> dict:
    """预测相关代理分析：基于误差趋势间接推断预测质量。

    虽然 metrics.csv 没有直接记录预测量 vs 真值，但误差趋势可以间接反映预测质量：
    - 稳态跟踪段的误差方差 → 预测精度
    - 突变段的误差恢复速度 → 预测响应
    - 误差发散 → 预测失效
    """
    # 按跟踪阶段分析
    track_fine_errors = [r["pixel_error_total"] for r in records
                         if r["atp_state"] == "TRACK_FINE" and math.isfinite(r["pixel_error_total"])]
    track_coarse_errors = [r["pixel_error_total"] for r in records
                           if r["atp_state"] == "TRACK_COARSE" and math.isfinite(r["pixel_error_total"])]
    reacquire_errors = [r["pixel_error_total"] for r in records
                        if r["atp_state"] == "REACQUIRE" and math.isfinite(r["pixel_error_total"])]

    # 误差趋势分析：连续增长段检测
    divergence_events = 0
    max_divergence_len = 0
    current_div = 0
    prev_err = None
    for r in records:
        err = r["pixel_error_total"]
        if not math.isfinite(err):
            current_div = 0
            prev_err = None
            continue
        if prev_err is not None and err > prev_err:
            current_div += 1
            max_divergence_len = max(max_divergence_len, current_div)
            if current_div >= 50:  # 连续 50 tick 以上误差增长视为发散
                divergence_events += 1
                current_div = 0
        else:
            current_div = 0
        prev_err = err

    result = {"divergence": {
        "events": divergence_events,
        "max_consecutive_growth_ticks": max_divergence_len,
    }}

    if track_fine_errors:
        result["steady_state"] = {
            "error_mean": round(sum(track_fine_errors) / len(track_fine_errors), 2),
            "error_std": round(_std(track_fine_errors), 2),
            "error_max": round(max(track_fine_errors), 2),
            "n_ticks": len(track_fine_errors),
        }

    if track_coarse_errors:
        result["coarse_track"] = {
            "error_mean": round(sum(track_coarse_errors) / len(track_coarse_errors), 2),
            "error_std": round(_std(track_coarse_errors), 2),
            "n_ticks": len(track_coarse_errors),
        }

    if reacquire_errors:
        result["reacquire"] = {
            "error_mean": round(sum(reacquire_errors) / len(reacquire_errors), 2),
            "n_ticks": len(reacquire_errors),
        }

    return result


def generate_interpretation(phase_errors: dict, transitions: dict,
                            control: dict, prediction: dict) -> list[str]:
    """基于诊断数据生成初步解释方向。"""
    notes = []

    # 1. 检查是否始终停留在粗跟踪
    if phase_errors.get("TRACK_FINE") is None and phase_errors.get("TRACK_COARSE") is not None:
        notes.append("算法始终未进入精跟踪状态（TRACK_FINE），误差收敛目标未达成")
        coarse = phase_errors["TRACK_COARSE"]
        if coarse and coarse["mean"] > 20:
            notes.append(f"  粗跟踪段平均误差 {coarse['mean']:.1f}px，距精跟踪门槛较远")

    # 2. 检查丢锁和重捕获
    summary = transitions.get("summary", {})
    lost = summary.get("lost_events", 0)
    if lost > 0:
        reacq_to_search = summary.get("reacquire_to_search", 0)
        reacq_to_acquire = summary.get("reacquire_to_acquire", 0)
        notes.append(f"发生 {lost} 次丢锁事件")
        if reacq_to_search > 0:
            notes.append(f"  其中 {reacq_to_search} 次重捕获失败退回搜索状态，重捕获成功率低")
        if reacq_to_acquire > 0:
            notes.append(f"  {reacq_to_acquire} 次重捕获成功进入捕获状态")

    # 3. 检查控制振荡
    for axis_name in ["yaw", "pitch"]:
        axis_data = control.get(axis_name, {})
        if axis_data.get("available"):
            rev_rate = axis_data.get("reversal_rate", 0)
            if rev_rate > 0.3:
                notes.append(f"{axis_name} 轴命令频繁翻转（翻转率 {rev_rate:.1%}），可能存在振荡")

    # 4. 检查预测发散
    div = prediction.get("divergence", {})
    if div.get("events", 0) > 0:
        notes.append(f"检测到 {div['events']} 次误差持续发散（连续增长 ≥50 ticks）")
    max_growth = div.get("max_consecutive_growth_ticks", 0)
    if max_growth > 100:
        notes.append(f"最大连续误差增长 {max_growth} ticks，预测器可能存在发散风险")

    # 5. 检查搜索阶段效率
    search = phase_errors.get("SEARCH")
    if search and search["duration_s"] > 3.0:
        notes.append(f"搜索阶段耗时 {search['duration_s']:.1f}s 较长，初始捕获效率偏低")

    # 6. 检查跟踪效率极低
    fine = phase_errors.get("TRACK_FINE")
    if fine and fine["mean"] > 10:
        notes.append(f"精跟踪段平均误差 {fine['mean']:.1f}px，仍有优化空间")

    if not notes:
        notes.append("算法表现正常，未检测到明显异常模式")

    return notes


# ============================================================
# 完整诊断流程
# ============================================================

def diagnose_algorithm(metrics_path: str, algorithm: str, scenario: str, seed: int) -> dict:
    """对单个实验做完整诊断。"""
    records = load_metrics_csv(metrics_path)

    phase_errors = diagnose_phase_errors(records)
    transitions = diagnose_atp_transitions(records)
    control = diagnose_control_behavior(records)
    prediction = diagnose_prediction_behavior(records)
    interpretation = generate_interpretation(phase_errors, transitions, control, prediction)

    return {
        "algorithm": algorithm,
        "scenario": scenario,
        "seed": seed,
        "phase_errors": phase_errors,
        "atp_transitions": transitions,
        "control_behavior": control,
        "prediction_proxy": prediction,
        "interpretation": interpretation,
    }


def diagnose_vs_baseline(input_dir: str, target_alg: str, baseline_alg: str,
                         scenario: str | None = None, obs_mode: str = "research") -> dict:
    """对比诊断：目标算法 vs 基线算法。"""
    target_paths = find_metrics_paths(input_dir, target_alg, scenario, obs_mode)
    baseline_paths = find_metrics_paths(input_dir, baseline_alg, scenario, obs_mode)

    if not target_paths:
        return {"error": f"未找到算法 {target_alg} 的实验数据"}
    if not baseline_paths:
        return {"error": f"未找到基线算法 {baseline_alg} 的实验数据"}

    # 按场景分组
    target_by_scenario: dict[str, list] = defaultdict(list)
    baseline_by_scenario: dict[str, list] = defaultdict(list)

    for p in target_paths:
        target_by_scenario[p["scenario"]].append(p)
    for p in baseline_paths:
        baseline_by_scenario[p["scenario"]].append(p)

    diagnosis_results = []
    all_scenarios = sorted(set(list(target_by_scenario.keys()) + list(baseline_by_scenario.keys())))

    for sc in all_scenarios:
        t_paths = target_by_scenario.get(sc, [])
        b_paths = baseline_by_scenario.get(sc, [])

        if not t_paths:
            continue

        # 选择可对齐的代表样本 seed 做详细诊断，避免场景级结论混淆为“全种子平均”
        target_seeds = sorted(p["seed"] for p in t_paths)
        baseline_seeds = sorted(p["seed"] for p in b_paths)
        shared_seeds = sorted(set(target_seeds) & set(baseline_seeds))

        if shared_seeds:
            representative_seed = shared_seeds[0]
        else:
            representative_seed = target_seeds[0]

        t_path = next((p for p in t_paths if p["seed"] == representative_seed), t_paths[0])
        t_diag = diagnose_algorithm(t_path["path"], target_alg, sc, t_path["seed"])

        if b_paths:
            b_path = next((p for p in b_paths if p["seed"] == representative_seed), b_paths[0])
            b_diag = diagnose_algorithm(b_path["path"], baseline_alg, sc, b_path["seed"])
        else:
            b_diag = {"phase_errors": {}, "atp_transitions": {}, "control_behavior": {}, "prediction_proxy": {}}

        diagnosis_results.append({
            "scenario": sc,
            "representative_seed": representative_seed,
            "target_seeds": target_seeds,
            "baseline_seeds": baseline_seeds,
            "target": t_diag,
            "baseline": b_diag,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_algorithm": target_alg,
        "baseline_algorithm": baseline_alg,
        "scenarios": diagnosis_results,
    }


# ============================================================
# 输出
# ============================================================

def write_diagnosis_md(output_path: str, diagnosis: dict) -> None:
    """写入可读的 Markdown 诊断报告。"""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    lines = []

    if "error" in diagnosis:
        lines.append(f"# 诊断错误\n\n{diagnosis['error']}\n")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return

    target = diagnosis.get("target_algorithm", "")
    baseline = diagnosis.get("baseline_algorithm", "")
    lines.append(f"# 算法诊断报告: {target} vs {baseline}\n")
    lines.append(f"- 生成时间: {diagnosis.get('generated_at', '')}\n")

    for sc_result in diagnosis.get("scenarios", []):
        sc = sc_result["scenario"]
        t = sc_result["target"]
        b = sc_result.get("baseline", {})
        rep_seed = sc_result.get("representative_seed")
        t_seeds = sc_result.get("target_seeds", [])
        b_seeds = sc_result.get("baseline_seeds", [])

        lines.append(f"## 场景 {sc}\n")
        lines.append(
            f"- 代表样本 seed: `{rep_seed}`（目标算法可用 seeds: {t_seeds}；基线可用 seeds: {b_seeds}）\n"
        )

        # 误差分时段对比
        lines.append("### 误差分时段分解\n")
        lines.append("| 状态 | 算法 | 平均误差 | RMS | 最大误差 | 占比 | 时长(s) |")
        lines.append("|------|------|----------|-----|----------|------|---------|")

        for state in ["SEARCH", "ACQUIRE", "TRACK_COARSE", "TRACK_FINE", "LOST", "REACQUIRE"]:
            for label, data in [(target, t), (baseline, b)]:
                pe = data.get("phase_errors", {}).get(state)
                if pe:
                    lines.append(
                        f"| {state} | {label} | {pe['mean']:.1f} | {pe['rms']:.1f} "
                        f"| {pe['max']:.1f} | {pe['pct_time']:.1f}% | {pe['duration_s']:.2f} |"
                    )

        lines.append("")

        # ATP 状态转换
        lines.append("### ATP 状态转换分析\n")
        t_summary = t.get("atp_transitions", {}).get("summary", {})
        b_summary = b.get("atp_transitions", {}).get("summary", {})
        lines.append(f"| 事件 | {target} | {baseline} |")
        lines.append(f"|------|----------|----------|")
        lines.append(f"| 总转换次数 | {t_summary.get('total_transitions', 0)} | {b_summary.get('total_transitions', 0)} |")
        lines.append(f"| 丢锁次数 | {t_summary.get('lost_events', 0)} | {b_summary.get('lost_events', 0)} |")
        lines.append(f"| 重捕获次数 | {t_summary.get('reacquire_events', 0)} | {b_summary.get('reacquire_events', 0)} |")
        lines.append(f"| 重捕获→搜索 | {t_summary.get('reacquire_to_search', 0)} | {b_summary.get('reacquire_to_search', 0)} |")
        lines.append(f"| 重捕获→捕获 | {t_summary.get('reacquire_to_acquire', 0)} | {b_summary.get('reacquire_to_acquire', 0)} |")
        lines.append("")

        # 控制行为
        lines.append("### 控制行为分析\n")
        for label, data in [(target, t), (baseline, b)]:
            ctrl = data.get("control_behavior", {})
            lines.append(f"**{label}**:")
            for axis in ["yaw", "pitch"]:
                ad = ctrl.get(axis, {})
                if ad.get("available"):
                    lines.append(
                        f"  - {axis}: 均值={ad['mean']:.2f}, 标准差={ad['std']:.2f}, "
                        f"最大={ad['max_abs']:.2f}, 翻转率={ad['reversal_rate']:.2%}, "
                        f"零命令占比={ad['zero_cmd_pct']:.1f}%"
                    )
            lines.append("")

        # 预测相关代理分析
        lines.append("### 预测相关代理分析\n")
        for label, data in [(target, t), (baseline, b)]:
            pred = data.get("prediction_proxy", {})
            div = pred.get("divergence", {})
            ss = pred.get("steady_state", {})
            lines.append(f"**{label}**:")
            if div:
                lines.append(f"  - 发散事件: {div.get('events', 0)}")
                lines.append(f"  - 最大连续增长: {div.get('max_consecutive_growth_ticks', 0)} ticks")
            if ss:
                lines.append(f"  - 稳态误差均值: {ss.get('error_mean', 'N/A')} px, 标准差: {ss.get('error_std', 'N/A')}")
            lines.append("")
        lines.append("> 注：本节基于误差趋势做间接判断，不等同于“预测量 vs 真值”的直接误差分析。\n")

        # 初步解释
        lines.append("### 初步解释方向\n")
        for note in t.get("interpretation", []):
            lines.append(f"- {note}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[诊断] Markdown 报告已写入: {output_path}")


def write_diagnosis_json(output_path: str, diagnosis: dict) -> None:
    """写入结构化诊断 JSON。"""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(diagnosis, f, indent=2, ensure_ascii=False, default=str)
    print(f"[诊断] JSON 已写入: {output_path}")


# ============================================================
# 工具函数
# ============================================================

def _safe_float(v) -> float:
    if v is None or v == "":
        return float("nan")
    try:
        return float(v)
    except (ValueError, TypeError):
        return float("nan")


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return variance ** 0.5


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
        description="算法诊断工具 — 分析算法性能，定位退化原因",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tools/diagnose_algorithm.py --algorithm linear_kf_tracker --scenario B3
  python tools/diagnose_algorithm.py --algorithm alpha_beta_tracker --baseline-algorithm atp_search_track_baseline
  python tools/diagnose_algorithm.py --algorithm linear_kf_tracker --scenario B1 --baseline-algorithm atp_search_track_baseline
        """,
    )
    parser.add_argument("--algorithm", required=True, help="待诊断的算法名称")
    parser.add_argument("--scenario", default=None, help="指定场景（默认诊断所有场景）")
    parser.add_argument("--baseline-algorithm", default="atp_search_track_baseline",
                        help="基线算法名称（默认: atp_search_track_baseline）")
    parser.add_argument("--input-dir", default="output/experiments", help="实验结果目录")
    parser.add_argument("--output-dir", default=None, help="诊断结果输出目录（默认: input-dir/diagnosis）")
    parser.add_argument("--obs-mode", default="research", help="观测模式过滤（默认: research）")

    args = parser.parse_args()
    input_dir = os.path.abspath(args.input_dir)
    output_dir = os.path.abspath(args.output_dir) if args.output_dir else os.path.join(input_dir, "diagnosis")

    if not os.path.isdir(input_dir):
        print(f"[错误] 输入目录不存在: {input_dir}")
        sys.exit(1)

    print(f"[诊断] 输入目录: {input_dir}")
    print(f"[诊断] 待诊断算法: {args.algorithm}")
    print(f"[诊断] 基线算法: {args.baseline_algorithm}")

    diagnosis = diagnose_vs_baseline(
        input_dir, args.algorithm, args.baseline_algorithm,
        scenario=args.scenario, obs_mode=args.obs_mode,
    )

    if "error" in diagnosis:
        print(f"[错误] {diagnosis['error']}")
        sys.exit(1)

    # 统计
    n_scenarios = len(diagnosis.get("scenarios", []))
    print(f"[诊断] 完成 {n_scenarios} 个场景的诊断")

    # 输出
    write_diagnosis_json(os.path.join(output_dir, f"diagnosis_{args.algorithm}.json"), diagnosis)
    write_diagnosis_md(os.path.join(output_dir, f"diagnosis_{args.algorithm}.md"), diagnosis)


if __name__ == "__main__":
    main()
