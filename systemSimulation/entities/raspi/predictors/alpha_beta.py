"""Alpha-Beta 滤波器预测器。

状态模型：像素空间的位置 (x, y) + 速度 (vx, vy)。
适用于目标近似匀速运动的场景，计算量极小。

Predictor 协议:
    update(obs: dict, detection: Detection|None) -> None
    predict(n_steps: int) -> tuple[float, float] | None
"""

from __future__ import annotations

from typing import Optional

from runtime.types import Detection


class AlphaBetaFilter:
    """Alpha-Beta 滤波器，在像素空间跟踪目标位置和速度。

    Args:
        alpha: 位置平滑因子，越大越信任测量值（默认 0.8）。
        beta: 速度平滑因子，越大越信任测量值推导的速度（默认 0.3）。
        max_history: 最大历史帧数（用于判断是否有足够数据）。
    """

    def __init__(
        self,
        alpha: float = 0.8,
        beta: float = 0.3,
        max_history: int = 30,
    ):
        self.alpha = alpha
        self.beta = beta
        self.max_history = max_history

        # 状态：像素位置 + 像素速度
        self._x: float = 0.0
        self._y: float = 0.0
        self._vx: float = 0.0
        self._vy: float = 0.0

        # 上一次时间戳，用于计算 dt
        self._last_timestamp: Optional[float] = None

        # 最近一次的 dt，用于 predict 外推
        self._dt: float = 0.0

        # 是否已初始化（首次收到有效检测时置 True）
        self._initialized: bool = False

    def update(self, obs: dict, detection: Optional[Detection]) -> None:
        """接收观测和检测结果，更新滤波器状态。

        处理流程：
        1. 从 obs["timestamp"] 计算dt。
        2. 如果没有有效检测，仅推进预测（不修正状态）。
        3. 如果有有效检测：
           a. 首次检测时直接初始化位置，速度置零。
           b. 后续检测执行标准 alpha-beta 预测+更新。

        Args:
            obs: 观测字典，需包含 "timestamp" 键。
            detection: 检测结果，None 或 not found 时跳过更新。
        """
        timestamp = float(obs.get("timestamp", 0.0))

        # 计算 dt
        if self._last_timestamp is None:
            dt = 0.0
        else:
            dt = timestamp - self._last_timestamp
        self._last_timestamp = timestamp

        # 记录最近的 dt（用于 predict 外推）
        if dt > 0.0:
            self._dt = dt

        # 没有有效检测时，仅用当前速度做预测推进
        if detection is None or not detection.found:
            if self._initialized and self._dt > 0.0:
                self._x += self._vx * self._dt
                self._y += self._vy * self._dt
            return

        # 有效检测
        measured_x = float(detection.cx)
        measured_y = float(detection.cy)

        if not self._initialized:
            # 首次检测：直接用测量值初始化位置，速度置零
            self._x = measured_x
            self._y = measured_y
            self._vx = 0.0
            self._vy = 0.0
            self._initialized = True
            return

        # 标准预测步骤
        x_pred = self._x + self._vx * self._dt
        y_pred = self._y + self._vy * self._dt

        # 更新步骤
        residual_x = measured_x - x_pred
        residual_y = measured_y - y_pred

        self._x = x_pred + self.alpha * residual_x
        self._y = y_pred + self.alpha * residual_y

        if self._dt > 0.0:
            self._vx = self._vx + (self.beta / self._dt) * residual_x
            self._vy = self._vy + (self.beta / self._dt) * residual_y

    def predict(self, n_steps: int) -> Optional[tuple[float, float]]:
        """预测 n_steps 后的像素位置。

        使用当前速度线性外推：pos + vel * dt * n_steps。

        Args:
            n_steps: 向前预测的步数。

        Returns:
            (px_x, px_y) 预测像素坐标，未初始化时返回 None。
        """
        if not self._initialized:
            return None

        pred_x = self._x + self._vx * self._dt * n_steps
        pred_y = self._y + self._vy * self._dt * n_steps
        return (pred_x, pred_y)
