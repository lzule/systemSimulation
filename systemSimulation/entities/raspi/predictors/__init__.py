"""预测器包。

Predictor 协议（鸭子类型）:
    update(obs: dict, detection: Detection|None) -> None
    predict(n_steps: int) -> tuple[float, float] | None

可用预测器:
    AlphaBetaFilter — Alpha-Beta 滤波器
    LinearKF — 线性卡尔曼滤波器
"""

from entities.raspi.predictors.alpha_beta import AlphaBetaFilter
from entities.raspi.predictors.linear_kf import LinearKF

__all__ = ["AlphaBetaFilter", "LinearKF"]
