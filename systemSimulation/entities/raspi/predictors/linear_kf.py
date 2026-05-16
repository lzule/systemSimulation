"""线性卡尔曼滤波器预测器。

状态向量: [px, py, vx, vy]（像素位置 + 像素速度）
观测向量: [px, py]（仅位置）

标准 KF 方程，使用 numpy 实现矩阵运算，不依赖 scipy。

Predictor 协议:
    update(obs: dict, detection: Detection|None) -> None
    predict(n_steps: int) -> tuple[float, float] | None
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from runtime.types import Detection


class LinearKF:
    """线性卡尔曼滤波器，在像素空间跟踪目标位置和速度。

    状态向量 x = [px, py, vx, vy]^T
    观测向量 z = [px, py]^T

    状态转移矩阵 F:
        [[1, 0, dt, 0 ],
         [0, 1, 0,  dt],
         [0, 0, 1,  0 ],
         [0, 0, 0,  1 ]]

    观测矩阵 H:
        [[1, 0, 0, 0],
         [0, 1, 0, 0]]

    Args:
        process_noise_pos: 位置过程噪声标准差（默认 2.0 像素）。
        process_noise_vel: 速度过程噪声标准差（默认 5.0 像素/秒）。
        measurement_noise: 观测噪声标准差（默认 3.0 像素）。
    """

    def __init__(
        self,
        process_noise_pos: float = 2.0,
        process_noise_vel: float = 5.0,
        measurement_noise: float = 3.0,
    ):
        self.process_noise_pos = process_noise_pos
        self.process_noise_vel = process_noise_vel
        self.measurement_noise = measurement_noise

        # 状态向量 [px, py, vx, vy]
        self._x: np.ndarray = np.zeros(4)

        # 协方差矩阵（初始化为较大值，表示初始不确定性）
        self._P: np.ndarray = np.eye(4) * 1000.0

        # 上一次时间戳
        self._last_timestamp: Optional[float] = None

        # 最近一次的 dt
        self._dt: float = 0.0

        # 是否已初始化（首次收到有效检测时置 True）
        self._initialized: bool = False

    def _build_F(self, dt: float) -> np.ndarray:
        """构建状态转移矩阵。"""
        return np.array([
            [1.0, 0.0, dt,  0.0],
            [0.0, 1.0, 0.0, dt ],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ])

    def _build_Q(self, dt: float) -> np.ndarray:
        """构建过程噪声协方差矩阵。

        使用分段连续白噪声模型：
        Q = G * sigma^2 * G^T，其中 G = [dt^2/2, dt]^T
        简化为对角形式以便调参。
        """
        # 位置过程噪声与 dt^2 相关（加速度引起的位移）
        q_pos = (self.process_noise_pos ** 2) * dt
        # 速度过程噪声与 dt 相关
        q_vel = (self.process_noise_vel ** 2) * dt
        return np.diag([q_pos, q_pos, q_vel, q_vel])

    def _build_H(self) -> np.ndarray:
        """构建观测矩阵。"""
        return np.array([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ])

    def _build_R(self) -> np.ndarray:
        """构建观测噪声协方差矩阵。"""
        r2 = self.measurement_noise ** 2
        return np.diag([r2, r2])

    def update(self, obs: dict, detection: Optional[Detection]) -> None:
        """接收观测和检测结果，执行 KF 预测+更新。

        处理流程：
        1. 从 obs["timestamp"] 计算 dt。
        2. 执行预测步骤（x = F @ x, P = F @ P @ F.T + Q）。
        3. 如果有有效检测，执行更新步骤。
        4. 首次有效检测时直接初始化状态向量。

        Args:
            obs: 观测字典，需包含 "timestamp" 键。
            detection: 检测结果，None 或 not found 时仅预测不更新。
        """
        timestamp = float(obs.get("timestamp", 0.0))

        # 计算 dt
        if self._last_timestamp is None:
            dt = 0.0
        else:
            dt = timestamp - self._last_timestamp
        self._last_timestamp = timestamp

        # 记录最近的 dt
        if dt > 0.0:
            self._dt = dt

        H = self._build_H()

        # === 预测步骤 ===
        if self._initialized and self._dt > 0.0:
            F = self._build_F(self._dt)
            Q = self._build_Q(self._dt)
            self._x = F @ self._x
            self._P = F @ self._P @ F.T + Q

        # === 无有效检测时到此结束 ===
        if detection is None or not detection.found:
            return

        measured_x = float(detection.cx)
        measured_y = float(detection.cy)
        z = np.array([measured_x, measured_y])

        if not self._initialized:
            # 首次检测：直接用测量值初始化状态，速度置零
            self._x = np.array([measured_x, measured_y, 0.0, 0.0])
            self._P = np.eye(4) * 1000.0
            self._initialized = True
            return

        # === 更新步骤 ===
        R = self._build_R()

        # 新息（残差）
        y = z - H @ self._x

        # 新息协方差
        S = H @ self._P @ H.T + R

        # 卡尔曼增益: K = P @ H^T @ S^{-1}
        # 使用 numpy.linalg.solve 避免 inv，更数值稳定
        # K @ S = P @ H^T  =>  S^T @ K^T = H @ P^T
        # 由于 S 对称：S @ K^T = H @ P^T => K^T = solve(S, H @ P^T)
        K = (self._P @ H.T) @ np.linalg.inv(S)

        # 状态更新
        self._x = self._x + K @ y

        # 协方差更新（Joseph 形式更稳定，但这里用标准形式）
        I = np.eye(4)
        self._P = (I - K @ H) @ self._P

    def predict(self, n_steps: int) -> Optional[tuple[float, float]]:
        """预测 n_steps 后的像素位置。

        使用当前状态和速度线性外推：
        px_pred = px + vx * dt * n_steps
        py_pred = py + vy * dt * n_steps

        Args:
            n_steps: 向前预测的步数。

        Returns:
            (px_x, px_y) 预测像素坐标，未初始化时返回 None。
        """
        if not self._initialized:
            return None

        # 简化外推：用当前位置 + 速度 * dt * n_steps
        px = self._x[0] + self._x[2] * self._dt * n_steps
        py = self._x[1] + self._x[3] * self._dt * n_steps
        return (float(px), float(py))
