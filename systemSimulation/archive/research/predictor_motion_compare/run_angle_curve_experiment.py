from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


REPO_ROOT = Path(r"k:\ustc-lizl\Liuwj2Lizl\ALL-Auto\8-simulation\System-APT\systemSimulation")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import target_cfg, tracker_tuning_cfg
from entities.camera.entity import detect_beacon_centroid
from entities.raspi.atp_state_machine import AtpState
from entities.raspi.trackers.rate_p_tracker import RatePTracker
from runtime.types import wrap_pm180
from simulation.bootstrap import build_runtime


@dataclass
class AngleSample:
    """单个采样点的完整记录。

    这里把画图、写 CSV、做统计时可能会用到的字段一次性都存下来。
    其中真正用于主图的是：
    - target_yaw_abs_deg：目标角
    - gimbal_yaw_deg：云台角
    - tracking_err_yaw_deg：跟踪误差
    """
    sample_idx: int
    obs_ts: float
    frame_ts: float
    gimbal_yaw_deg: float
    target_yaw_abs_deg: float
    tracking_err_yaw_deg: float
    detected: int
    u_px: float
    v_px: float
    cx_px: float
    cy_px: float
    f_px: float
    yaw_rate_cmd_dps: float
    pred_omega_dps: float
    pred_method: str
    imu_yaw_deg: float
    cam_target_yaw_deg: float
    err_yaw_deg: float


class OmegaEstimator:
    """角速度估计器基类。

    所有方法都遵守同一套接口：
    - update(obs, det)：喂入当前一帧观测，更新内部状态
    - predict()：输出当前估计到的目标角速度，单位是 deg/s
    """
    def update(self, obs: dict, det) -> None:
        raise NotImplementedError

    def predict(self) -> float:
        raise NotImplementedError


def _finite(value: float) -> bool:
    """判断数值是否有效。

    这里单独封装，是为了让后面的估计器逻辑更好读。
    """
    return math.isfinite(float(value))


def _measure_target_yaw(obs: dict, det) -> Optional[float]:
    """把当前观测换算成“目标绝对角”。

    这一步不是在猜未来，而是在用同一拍观测里的：
    - 云台当前角
    - 图像里检测到的目标偏移

    反推出“当前这一拍里，目标相对世界的 yaw 角”。
    """
    frame = obs.get("frame")
    gimbal = obs.get("gimbal") or {}
    if frame is None or det is None or not det.found or det.cx is None or det.cy is None:
        return None
    intrinsics = getattr(frame, "intrinsics", {}) or {}
    cx = float(intrinsics.get("cx", float("nan")))
    f_px = float(intrinsics.get("f_px", float("nan")))
    if not (_finite(cx) and _finite(f_px) and f_px > 0.0):
        return None
    gimbal_yaw = float(gimbal.get("yaw_deg_internal", float("nan")))
    if not _finite(gimbal_yaw):
        return None
    rel_yaw = math.degrees(math.atan2(float(det.cx) - cx, f_px))
    return wrap_pm180(gimbal_yaw + rel_yaw)


class DiffEMAEstimator(OmegaEstimator):
    """差分 + 指数滑动平均。

    思路很简单：
    1. 先算相邻两帧目标角的差分，得到瞬时角速度
    2. 再对角速度做 EMA 平滑，减小抖动
    """
    def __init__(self, alpha: float = 0.35):
        self.alpha = alpha
        self._last_angle: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._ema_omega = 0.0

    def update(self, obs: dict, det) -> None:
        # 先把当前帧换算成目标角，再和上一帧做差分。
        angle = _measure_target_yaw(obs, det)
        ts = float(obs.get("timestamp", float("nan")))
        if angle is None or not _finite(ts):
            return
        if self._last_angle is not None and self._last_ts is not None and ts > self._last_ts:
            # 角度差要先做 wrap，避免 179° 和 -179° 被误判成巨大跳变。
            delta = wrap_pm180(angle - self._last_angle)
            # 差分角速度，再用 EMA 平滑。
            raw_omega = delta / (ts - self._last_ts)
            self._ema_omega = self.alpha * raw_omega + (1.0 - self.alpha) * self._ema_omega
        self._last_angle = angle
        self._last_ts = ts

    def predict(self) -> float:
        # 输出当前平滑后的角速度估计值，单位 deg/s。
        return float(self._ema_omega)


class AlphaBetaOmegaEstimator(OmegaEstimator):
    """Alpha-Beta 估计器。

    可以把它理解成一个很轻量的“带速度状态的跟踪器”：
    - alpha 负责修正角度
    - beta 负责修正角速度
    """
    def __init__(self, alpha: float = 0.85, beta: float = 0.12):
        self.alpha = alpha
        self.beta = beta
        self._angle: Optional[float] = None
        self._omega = 0.0
        self._last_ts: Optional[float] = None

    def update(self, obs: dict, det) -> None:
        # 先拿到当前测量角，再和“上一时刻预测值”比较。
        meas = _measure_target_yaw(obs, det)
        ts = float(obs.get("timestamp", float("nan")))
        if meas is None or not _finite(ts):
            return
        if self._angle is None or self._last_ts is None:
            self._angle = meas
            self._omega = 0.0
            self._last_ts = ts
            return
        dt = ts - self._last_ts
        if dt <= 0.0:
            return
        # 用当前速度先外推一步，再看测量值和预测值差多少。
        pred_angle = wrap_pm180(self._angle + self._omega * dt)
        resid = wrap_pm180(meas - pred_angle)
        # alpha 修正角度，beta 修正速度。
        self._angle = wrap_pm180(pred_angle + self.alpha * resid)
        self._omega = self._omega + (self.beta / dt) * resid
        self._last_ts = ts

    def predict(self) -> float:
        # 直接输出当前速度状态。
        return float(self._omega)


class LinearKFOmegaEstimator(OmegaEstimator):
    """线性卡尔曼滤波版本。

    状态只保留两项：
    - 当前角度
    - 当前角速度

    这类方法更像“标准状态估计器”，比差分平滑一点，但参数也更敏感。
    """
    def __init__(self):
        self._x = np.zeros(2, dtype=float)
        self._P = np.eye(2, dtype=float) * 1000.0
        self._last_ts: Optional[float] = None
        self._initialized = False

    def update(self, obs: dict, det) -> None:
        # 先拿到观测角。
        meas = _measure_target_yaw(obs, det)
        ts = float(obs.get("timestamp", float("nan")))
        if meas is None or not _finite(ts):
            return
        if self._last_ts is None:
            self._last_ts = ts
            self._x[0] = meas
            self._x[1] = 0.0
            self._initialized = True
            return
        dt = ts - self._last_ts
        self._last_ts = ts
        if dt <= 0.0:
            return

        f_mat = np.array([[1.0, dt], [0.0, 1.0]], dtype=float)
        q_mat = np.array([[0.05, 0.0], [0.0, 0.20]], dtype=float) * dt
        h_mat = np.array([[1.0, 0.0]], dtype=float)
        r_mat = np.array([[2.0]], dtype=float)

        # 预测：角度按角速度往前走。
        self._x = f_mat @ self._x
        self._x[0] = wrap_pm180(self._x[0])
        self._P = f_mat @ self._P @ f_mat.T + q_mat

        # 更新：用当前测量值修正预测误差。
        innovation = np.array([wrap_pm180(meas - self._x[0])], dtype=float)
        s_mat = h_mat @ self._P @ h_mat.T + r_mat
        k_mat = self._P @ h_mat.T @ np.linalg.inv(s_mat)
        self._x = self._x + (k_mat @ innovation).reshape(-1)
        self._x[0] = wrap_pm180(self._x[0])
        self._P = (np.eye(2) - k_mat @ h_mat) @ self._P
        self._initialized = True

    def predict(self) -> float:
        # 第二个状态量就是角速度。
        return float(self._x[1]) if self._initialized else 0.0


class SinusoidalFitOmegaEstimator(OmegaEstimator):
    """正弦拟合版本。

    这次实验目标本身就是确定的正弦运动，所以这个方法会：
    1. 收集最近一段目标角
    2. 先从这段观测里自己估一个最像的频率
    3. 再按拟合出来的正弦曲线求导，直接得到角速度

    注意：这里不读取 target_cfg.sin_frequency_hz，也不把目标频率当已知量。
    它只看相机和云台给出的观测历史，自己从数据里找规律。
    """
    def __init__(self):
        self._samples: list[tuple[float, float]] = []
        self._last_freq_hz = 0.0

    def update(self, obs: dict, det) -> None:
        # 只保存最近一段观测，避免窗口无限增长。
        meas = _measure_target_yaw(obs, det)
        ts = float(obs.get("timestamp", float("nan")))
        if meas is None or not _finite(ts):
            return
        self._samples.append((ts, meas))
        if len(self._samples) > 200:
            self._samples.pop(0)

    def _estimate_frequency_and_fit(self) -> tuple[float, Optional[np.ndarray], Optional[np.ndarray]]:
        """先粗估频率，再用最小二乘拟合该频率下的正弦模型。

        返回值：
        - 频率（Hz）
        - 拟合系数 [a, b, c]
        - 相对时间轴
        """
        if len(self._samples) < 8:
            return 0.0, None, None

        ts = np.array([s[0] for s in self._samples], dtype=float)
        ys = np.unwrap(np.deg2rad(np.array([s[1] for s in self._samples], dtype=float)))
        rel_t = ts - ts[0]
        if len(rel_t) < 2:
            return 0.0, None, None

        dt = float(np.median(np.diff(rel_t)))
        if not _finite(dt) or dt <= 0.0:
            return 0.0, None, None

        # 先用 FFT 找一个大致频率，只用观测数据本身，不看任何配置里的真值。
        centered = ys - float(np.mean(ys))
        spectrum = np.abs(np.fft.rfft(centered))
        freqs = np.fft.rfftfreq(len(centered), d=dt)
        if len(freqs) <= 1:
            return 0.0, None, None

        peak_idx = int(np.argmax(spectrum[1:])) + 1
        peak_freq = float(freqs[peak_idx])
        if not _finite(peak_freq) or peak_freq <= 0.0:
            return 0.0, None, None

        # 在粗估频率附近做一小段网格搜索，选残差最小的那一个。
        lo = max(0.02, peak_freq * 0.5)
        hi = max(lo * 1.2, peak_freq * 1.5)
        grid = np.linspace(lo, hi, 25)

        best_loss = float("inf")
        best_freq = peak_freq
        best_coeffs: Optional[np.ndarray] = None

        for freq_hz in grid:
            w = 2.0 * math.pi * freq_hz
            a_mat = np.column_stack([np.sin(w * rel_t), np.cos(w * rel_t), np.ones_like(rel_t)])
            coeffs, *_ = np.linalg.lstsq(a_mat, ys, rcond=None)
            resid = a_mat @ coeffs - ys
            loss = float(np.mean(resid ** 2))
            if loss < best_loss:
                best_loss = loss
                best_freq = float(freq_hz)
                best_coeffs = coeffs

        self._last_freq_hz = best_freq
        return best_freq, best_coeffs, rel_t

    def predict(self) -> float:
        # 样本太少或者频率估不出来时，先不做拟合，直接返回 0。
        freq_hz, coeffs, rel_t = self._estimate_frequency_and_fit()
        if coeffs is None or rel_t is None or freq_hz <= 0.0:
            return 0.0
        # 这里的模型是 y(t)=a*sin(wt)+b*cos(wt)+c。
        w = 2.0 * math.pi * freq_hz
        a_coef, b_coef, _ = coeffs
        t_now = float(rel_t[-1])
        # 对拟合曲线求导，得到当前角速度。
        omega_rad = a_coef * w * math.cos(w * t_now) - b_coef * w * math.sin(w * t_now)
        return float(math.degrees(omega_rad))


def build_omega_estimator(name: str) -> OmegaEstimator:
    """按名字选择角速度估计器。"""
    if name == "diff_ema":
        return DiffEMAEstimator()
    if name == "alpha_beta":
        return AlphaBetaOmegaEstimator()
    if name == "linear_kf":
        return LinearKFOmegaEstimator()
    if name == "sin_fit":
        return SinusoidalFitOmegaEstimator()
    raise ValueError(f"unknown omega estimator: {name}")


class LoggingRatePProgram:
    """外置实验控制程序。

    它的职责很单纯：
    - 先跑仓库里的基础 Kp 跟踪
    - 再根据选定的方法估计目标角速度
    - 如果不是 base，就把这个角速度补进控制命令里
    - 同时把每一帧需要画图的数据记录下来
    """

    def __init__(self, omega_method: str = "base"):
        self.tracker = RatePTracker()
        self.omega_method = omega_method
        self.omega_estimator = build_omega_estimator(omega_method) if omega_method != "base" else None
        self.samples: list[AngleSample] = []
        self._sample_idx = 0

    @staticmethod
    def _angle_from_pixels(delta_px: float, f_px: float) -> float:
        """把像素偏移换成角度。

        这里用的是最直接的针孔模型近似：
        - 像素偏移越大，角度越大
        - 焦距越大，同样像素偏移对应的角度越小
        """
        return math.degrees(math.atan2(delta_px, f_px))

    def _extract_sample(self, obs: dict, det, yaw_rate_cmd_dps: float, pred_omega_dps: float) -> AngleSample:
        # 从当前观测里整理出一条可画图、可导出的记录。
        frame = obs.get("frame")
        gimbal = obs.get("gimbal") or {}
        frame_ts = float(getattr(frame, "timestamp", obs.get("timestamp", float("nan"))))
        intrinsics = getattr(frame, "intrinsics", {}) or {}
        cx = float(intrinsics.get("cx", float("nan")))
        cy = float(intrinsics.get("cy", float("nan")))
        f_px = float(intrinsics.get("f_px", float("nan")))
        gimbal_yaw = float(gimbal.get("yaw_deg_internal", float("nan")))

        detected = bool(det is not None and det.found and det.cx is not None and det.cy is not None)
        u_px = float(det.cx) if detected else float("nan")
        v_px = float(det.cy) if detected else float("nan")

        if detected and _finite(gimbal_yaw) and _finite(cx) and _finite(f_px) and f_px > 0.0:
            # 目标绝对角 = 云台角 + 目标在画面里的相对角。
            target_yaw_abs = wrap_pm180(gimbal_yaw + self._angle_from_pixels(u_px - cx, f_px))
            # 跟踪误差就是目标角减云台角。
            tracking_err_yaw = wrap_pm180(target_yaw_abs - gimbal_yaw)
        else:
            target_yaw_abs = float("nan")
            tracking_err_yaw = float("nan")

        return AngleSample(
            sample_idx=self._sample_idx,
            obs_ts=float(obs.get("timestamp", float("nan"))),
            frame_ts=frame_ts,
            gimbal_yaw_deg=gimbal_yaw,
            target_yaw_abs_deg=target_yaw_abs,
            tracking_err_yaw_deg=tracking_err_yaw,
            detected=1 if detected else 0,
            u_px=u_px,
            v_px=v_px,
            cx_px=cx,
            cy_px=cy,
            f_px=f_px,
            yaw_rate_cmd_dps=yaw_rate_cmd_dps,
            pred_omega_dps=pred_omega_dps,
            pred_method=self.omega_method,
            imu_yaw_deg=gimbal_yaw,
            cam_target_yaw_deg=target_yaw_abs,
            err_yaw_deg=tracking_err_yaw,
        )

    def on_tick(self, obs: dict):
        # 每次仿真推进一拍，就做一次检测、估计和控制。
        frame = obs.get("frame")
        det = detect_beacon_centroid(frame.image) if frame is not None else None

        # 先更新角速度估计器，再拿出当前估计值。
        pred_omega_dps = 0.0
        if self.omega_estimator is not None:
            self.omega_estimator.update(obs, det)
            pred_omega_dps = float(self.omega_estimator.predict())

        # 先执行仓库里的基础 Kp 控制，作为真正的控制基线。
        commands = self.tracker.compute_commands(obs, AtpState.TRACK_COARSE, None)
        yaw_rate_cmd_dps = 0.0
        for cmd in reversed(commands):
            if cmd.target == "gimbal" and cmd.action == "set_rate_target":
                yaw_rate_cmd_dps = float(cmd.payload.get("yaw_rate", 0.0))
                break

        # 非 base 方法就在基础控制上再补一段角速度。
        if self.omega_estimator is not None and commands and _finite(pred_omega_dps):
            for cmd in commands:
                if cmd.target == "gimbal" and cmd.action == "set_rate_target":
                    base_rate = float(cmd.payload.get("yaw_rate", 0.0))
                    mixed_rate = max(
                        -tracker_tuning_cfg.max_yaw_rate_dps,
                        min(tracker_tuning_cfg.max_yaw_rate_dps, base_rate + pred_omega_dps),
                    )
                    cmd.payload["yaw_rate"] = float(mixed_rate)
                    yaw_rate_cmd_dps = float(mixed_rate)
                    break

        # 记录这一拍的数据，后面用来导 CSV 和画图。
        self.samples.append(self._extract_sample(obs, det, yaw_rate_cmd_dps, pred_omega_dps))
        self._sample_idx += 1
        return commands


def write_csv(path: Path, samples: list[AngleSample]) -> None:
    """把采样结果写成 CSV，方便后处理和人工检查。"""
    if not samples:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(samples[0]).keys()))
        writer.writeheader()
        for sample in samples:
            writer.writerow(asdict(sample))


def compute_zoom_bounds(samples: list[AngleSample], zoom_seconds: float) -> tuple[float, float]:
    """计算中间放大窗口。

    这里不看开头那段启动波动，而是直接取有效观测时间的中间 3 秒，
    这样更适合看稳定跟踪细节。
    """
    valid_ts = [s.obs_ts for s in samples if _finite(s.target_yaw_abs_deg)]
    if not valid_ts:
        valid_ts = [s.obs_ts for s in samples if _finite(s.obs_ts)]
    if not valid_ts:
        return (0.0, zoom_seconds)
    start = min(valid_ts)
    end = max(valid_ts)
    if end - start <= zoom_seconds:
        return (start, end)
    center = 0.5 * (start + end)
    left = center - zoom_seconds / 2.0
    right = center + zoom_seconds / 2.0
    if left < start:
        right += start - left
        left = start
    if right > end:
        left -= right - end
        right = end
    return (left, right)


def plot_curve(
    samples: list[AngleSample],
    path: Path,
    title: str,
    time_window: Optional[tuple[float, float]] = None,
) -> None:
    """画出目标角、云台角和跟踪误差的两层图。

    上半部分看“目标角 vs 云台角”，下半部分看“误差”。
    如果传入 time_window，就只显示指定时间段。
    """
    ts = np.array([s.obs_ts for s in samples], dtype=float)
    target = np.array([s.target_yaw_abs_deg for s in samples], dtype=float)
    gimbal = np.array([s.gimbal_yaw_deg for s in samples], dtype=float)
    err = np.array([s.tracking_err_yaw_deg for s in samples], dtype=float)

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, constrained_layout=True)
    axes[0].plot(ts, target, label="target yaw", color="#cc0000", linewidth=1.7)
    axes[0].plot(ts, gimbal, label="gimbal yaw", color="#204a87", linewidth=1.7)
    axes[0].set_ylabel("angle (deg)")
    axes[0].set_title(title)
    axes[0].grid(True, alpha=0.25)
    axes[0].legend(loc="best")

    axes[1].plot(ts, err, label="tracking error", color="#f57900", linewidth=1.6)
    axes[1].axhline(0.0, color="#888a85", linestyle="--", linewidth=1.0)
    axes[1].set_xlabel("time (s)")
    axes[1].set_ylabel("error (deg)")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend(loc="best")

    if time_window is not None:
        for ax in axes:
            ax.set_xlim(time_window[0], time_window[1])

    fig.savefig(path, dpi=160)
    plt.close(fig)


def summarize_samples(samples: list[AngleSample]) -> dict[str, float]:
    """统计一些最基础的结果指标。

    这里主要是给 summary.txt 用，方便快速看每种方法的误差大小。
    """
    err = np.array([s.tracking_err_yaw_deg for s in samples], dtype=float)
    finite_err = err[np.isfinite(err)]
    if finite_err.size == 0:
        return {
            "samples": float(len(samples)),
            "detected_ratio": float(sum(s.detected for s in samples) / max(1, len(samples))),
            "tracking_err_mean_abs": float("nan"),
            "tracking_err_rms": float("nan"),
        }
    return {
        "samples": float(len(samples)),
        "detected_ratio": float(sum(s.detected for s in samples) / max(1, len(samples))),
        "tracking_err_mean_abs": float(np.mean(np.abs(finite_err))),
        "tracking_err_rms": float(np.sqrt(np.mean(finite_err ** 2))),
    }


def run_one_case(
    output_dir: Path,
    omega_method: str,
    duration_s: float,
    delay_ms: float,
    obs_mode: str,
    seed: int,
    zoom_seconds: float,
) -> dict[str, float]:
    """跑一整组方法，并把该方法的图和 CSV 写到输出目录里。"""
    np.random.seed(seed)
    program = LoggingRatePProgram(omega_method=omega_method)
    runtime = build_runtime(delay_ms=delay_ms, control_program=program, obs_mode=obs_mode)
    steps = max(1, int(duration_s / runtime.dt_s))
    for _ in range(steps):
        runtime.step(1)

    samples = program.samples
    write_csv(output_dir / f"{omega_method}_raw_samples.csv", samples)

    zoom_bounds = compute_zoom_bounds(samples, zoom_seconds)
    plot_curve(
        samples,
        output_dir / f"{omega_method}_yaw_overview.png",
        f"{omega_method} | target yaw vs gimbal yaw",
    )
    plot_curve(
        samples,
        output_dir / f"{omega_method}_yaw_mid{int(zoom_seconds)}s.png",
        f"{omega_method} | target yaw vs gimbal yaw (mid {zoom_seconds:.0f}s)",
        time_window=zoom_bounds,
    )
    return summarize_samples(samples)


def write_summary(
    output_dir: Path,
    duration_s: float,
    delay_ms: float,
    obs_mode: str,
    seed: int,
    metrics: dict[str, dict[str, float]],
    zoom_seconds: float,
) -> None:
    """把这一轮实验的关键信息写成可读文本。"""
    lines = [
        "角速度对比实验结果",
        "",
        f"输出目录: {output_dir}",
        f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"仿真时长: {duration_s:.1f}s",
        f"链路延时: {delay_ms:.1f}ms",
        f"观测模式: {obs_mode}",
        f"随机种子: {seed}",
        f"局部放大窗口: 中间 {zoom_seconds:.1f}s",
        "",
        "说明:",
        "- 图里只看三条关系: 目标角、云台角、跟踪误差。",
        "- 目标角来自同一拍观测里的图像和云台角反算，不用系统隐藏真值。",
        "- 预测器只参与控制，不单独画预测角或未来真实值。",
        "- base 表示纯 Kp 基线，其它方法表示 Kp 加角速度预测。",
        "",
    ]
    for name, item in metrics.items():
        lines.append(f"[{name}]")
        lines.append(
            f"- samples={int(item['samples'])}, detected_ratio={item['detected_ratio']:.3f}, "
            f"mean_abs_err={item['tracking_err_mean_abs']:.3f}, rms_err={item['tracking_err_rms']:.3f}"
        )
        lines.append("")
    (output_dir / "summary.txt").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    """命令行入口。

    默认会跑 base + 4 种角速度估计方法，并把结果写到独立时间戳目录里。
    """
    parser = argparse.ArgumentParser(description="角速度预测对比实验")
    parser.add_argument("--output-root", default=r"S:\tmp\angle_curve_experiment")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--delay-ms", type=float, default=26.0)
    parser.add_argument("--obs-mode", default="realistic", choices=["debug", "research", "realistic"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--zoom-seconds", type=float, default=3.0)
    parser.add_argument(
        "--predictors",
        nargs="+",
        default=["base", "diff_ema", "alpha_beta", "linear_kf", "sin_fit"],
        choices=["base", "diff_ema", "alpha_beta", "linear_kf", "sin_fit"],
    )
    args = parser.parse_args()

    # 固定为确定性的正弦目标，方便直接比较不同控制方法。
    # 这里的目标配置只是给仿真生成轨迹用，不会被任何估计器直接读取。
    target_cfg.motion_type = "sinusoidal"
    target_cfg.sin_amplitude_m = 15.0
    target_cfg.sin_frequency_hz = 0.2

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = output_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics: dict[str, dict[str, float]] = {}
    for name in args.predictors:
        metrics[name] = run_one_case(
            output_dir=output_dir,
            omega_method=name,
            duration_s=args.duration,
            delay_ms=args.delay_ms,
            obs_mode=args.obs_mode,
            seed=args.seed,
            zoom_seconds=args.zoom_seconds,
        )

    write_summary(
        output_dir=output_dir,
        duration_s=args.duration,
        delay_ms=args.delay_ms,
        obs_mode=args.obs_mode,
        seed=args.seed,
        metrics=metrics,
        zoom_seconds=args.zoom_seconds,
    )
    print(output_dir)


if __name__ == "__main__":
    main()
