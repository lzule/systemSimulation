"""诊断图 v4: angles / error+zoom合一 / pdf 三类独立文件夹.

用法:
    cd systemSimulation
    conda run -n simulation python research/kp_predictor_compare/_diagnostic_plots.py
"""
import sys
from pathlib import Path
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
RUN_DIR = max(d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name != ".gitkeep")

METHODS = ["kalman", "fft_sine"]
COLORS = {"base": "#204a87", "kalman": "#cc0000", "fft_sine": "#4e9a06"}
LABELS = {"base": "Kp (no prediction)", "kalman": "Kp + Kalman", "fft_sine": "Kp + FFT Sine"}


def load_csv(path):
    data = {"ts": [], "gimbal": [], "target": [], "err": [], "rate": []}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            data["ts"].append(float(row["ts"]))
            data["gimbal"].append(float(row["gimbal_yaw"]))
            data["target"].append(float(row["target_yaw"]))
            data["err"].append(float(row["err_yaw"]))
            data["rate"].append(float(row["yaw_rate_cmd"]))
    return {k: np.array(v) for k, v in data.items()}


def mean_abs(arr):
    f = arr[np.isfinite(arr)]
    return float(np.mean(np.abs(f))) if f.size > 0 else float("nan")


def mid_bounds(ts, zoom_s=3.0):
    vt = ts[np.isfinite(ts)]
    if vt.size == 0 or vt[-1] - vt[0] <= zoom_s:
        return None
    c = 0.5 * (vt[0] + vt[-1])
    return (c - zoom_s / 2, c + zoom_s / 2)


def gaussian_kde(data, x_grid):
    data = np.asarray(data, dtype=float)
    h = 1.06 * np.std(data) * len(data) ** (-0.2) if len(data) > 1 else 1.0
    x_grid = np.asarray(x_grid, dtype=float)
    pdf = np.zeros_like(x_grid)
    for d in data:
        pdf += np.exp(-0.5 * ((x_grid - d) / h) ** 2)
    pdf /= (len(data) * h * np.sqrt(2 * np.pi))
    return pdf


def save(fig, path):
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved: {path.relative_to(out)}")


# ── 加载数据 ──
motions = ["sinusoidal", "constant_velocity", "constant_accel"]
data = {}
for m in motions:
    for method in ["base", "kalman", "fft_sine"]:
        path = RUN_DIR / "delay_026ms" / m / f"{method}_raw.csv"
        if path.exists():
            data[(m, method)] = load_csv(path)

out = RUN_DIR / "plots_26ms"
out.mkdir(exist_ok=True)

# 清理旧平铺文件
for old in out.glob("*.png"):
    old.unlink()

for motion in motions:
    base_s = data.get((motion, "base"))
    if base_s is None:
        continue
    print(f"\n[{motion}]")

    for pred_method in METHODS:
        pred_s = data.get((motion, pred_method))
        if pred_s is None:
            continue

        base_err = base_s["err"]
        pred_err = pred_s["err"]
        base_mae = mean_abs(base_err)
        pred_mae = mean_abs(pred_err)
        improve_pct = (base_mae - pred_mae) / base_mae * 100 if base_mae > 0 else 0

        zb = mid_bounds(base_s["ts"], 3.0)

        # ── 1. angles: 云台 vs 目标角度 ──
        d_angles = out / "angles"
        d_angles.mkdir(exist_ok=True)
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(base_s["ts"], base_s["target"], color="#333333",
                linewidth=1.5, label="Target yaw", zorder=3)
        ax.plot(base_s["ts"], base_s["gimbal"], color=COLORS["base"],
                linewidth=1.0, alpha=0.8, label=f"Gimbal ({LABELS['base']})")
        ax.plot(pred_s["ts"], pred_s["gimbal"], color=COLORS[pred_method],
                linewidth=1.0, alpha=0.8, linestyle="--",
                label=f"Gimbal ({LABELS[pred_method]})")
        ax.set_xlabel("time (s)")
        ax.set_ylabel("yaw angle (deg)")
        ax.set_title(
            f"{motion} / delay=26ms — Angle tracking: "
            f"{LABELS[pred_method]} vs {LABELS['base']}"
        )
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.2)
        save(fig, d_angles / f"{motion}_{pred_method}.png")

        # ── 2. error: 全程误差(上) + mid-3s放大(下) 合一 ──
        d_error = out / "error"
        d_error.mkdir(exist_ok=True)
        fig, (ax_full, ax_zoom) = plt.subplots(
            2, 1, figsize=(12, 7), constrained_layout=True,
            gridspec_kw={"height_ratios": [1, 1]}
        )

        # 上: 全程误差
        ax_full.plot(base_s["ts"], base_err, color=COLORS["base"], linewidth=0.8,
                     alpha=0.8, label=f"{LABELS['base']}  MAE={base_mae:.4f} deg")
        ax_full.plot(pred_s["ts"], pred_err, color=COLORS[pred_method], linewidth=0.8,
                     alpha=0.8,
                     label=f"{LABELS[pred_method]}  MAE={pred_mae:.4f} deg")
        ax_full.axhline(0, color="#888", linestyle="--", linewidth=0.5)
        if zb:
            ax_full.axvspan(zb[0], zb[1], color="orange", alpha=0.08,
                            label="mid 3s region")
        ax_full.set_ylabel("tracking error (deg)")
        ax_full.set_title(
            f"{motion} / delay=26ms — Error: {LABELS[pred_method]} vs "
            f"{LABELS['base']}  (improve {improve_pct:.1f}%)"
        )
        ax_full.legend(fontsize=9)
        ax_full.grid(True, alpha=0.2)

        # 下: mid-3s 放大
        if zb:
            bm = (base_s["ts"] >= zb[0]) & (base_s["ts"] <= zb[1])
            pm = (pred_s["ts"] >= zb[0]) & (pred_s["ts"] <= zb[1])
            ax_zoom.plot(base_s["ts"][bm], base_err[bm], color=COLORS["base"],
                         linewidth=1.2, alpha=0.9,
                         label=f"{LABELS['base']}  MAE={mean_abs(base_err[bm]):.4f}")
            ax_zoom.plot(pred_s["ts"][pm], pred_err[pm], color=COLORS[pred_method],
                         linewidth=1.2, alpha=0.9,
                         label=f"{LABELS[pred_method]}  MAE={mean_abs(pred_err[pm]):.4f}")
            ax_zoom.axhline(0, color="#888", linestyle="--", linewidth=0.5)
            ax_zoom.set_xlim(zb)
        ax_zoom.set_xlabel("time (s)")
        ax_zoom.set_ylabel("error (deg)")
        ax_zoom.set_title("mid 3s zoom")
        ax_zoom.legend(fontsize=9)
        ax_zoom.grid(True, alpha=0.2)

        save(fig, d_error / f"{motion}_{pred_method}.png")

        # ── 3. pdf: |error| 平滑 PDF ──
        d_pdf = out / "pdf"
        d_pdf.mkdir(exist_ok=True)
        fig, ax = plt.subplots(figsize=(8, 5))
        annotations = []
        for idx, (method, err, color, mae_val) in enumerate([
            ("base", base_err, COLORS["base"], base_mae),
            (pred_method, pred_err, COLORS[pred_method], pred_mae),
        ]):
            fe = np.abs(err[np.isfinite(err)])
            if fe.size < 5:
                continue
            hi = np.percentile(fe, 99.5) * 1.3
            x_grid = np.linspace(0, hi, 300)
            pdf_vals = gaussian_kde(fe, x_grid)
            ax.plot(x_grid, pdf_vals, color=color, linewidth=2.0,
                    label=f"{LABELS[method]}")
            ax.fill_between(x_grid, pdf_vals, alpha=0.10, color=color)
            ax.axvline(mae_val, color=color, linestyle="--", linewidth=1.2,
                       alpha=0.8)
            pdf_at_mean = float(np.interp(mae_val, x_grid, pdf_vals))
            # 错开标注: base 在上方, prediction 在下方
            y_frac = 0.9 if idx == 0 else 0.55
            annotations.append({
                "xy": (mae_val, pdf_at_mean),
                "xytext": (mae_val + hi * 0.05, pdf_at_mean * y_frac + max(pdf_vals) * (1 - y_frac)),
                "text": f"MAE={mae_val:.4f} deg",
                "color": color,
            })
        for ann in annotations:
            ax.annotate(
                ann["text"],
                xy=ann["xy"],
                xytext=ann["xytext"],
                fontsize=9, color=ann["color"], fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=ann["color"], lw=0.8),
            )
        ax.set_xlabel("|error| (deg)")
        ax.set_ylabel("PDF")
        ax.set_title(
            f"{motion} / delay=26ms — |Error| PDF: "
            f"{LABELS[pred_method]} vs {LABELS['base']}"
        )
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.2)
        save(fig, d_pdf / f"{motion}_{pred_method}.png")

print("\ndone")
