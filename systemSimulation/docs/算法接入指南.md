# 算法接入指南

> 本指南说明如何将自己的控制算法接入仿真平台，从最简单的临时加载到正式纳入 benchmark。
> 控制程序的基础写法，请先阅读[树莓派控制程序开发手册](树莓派控制程序开发手册.md)。

---

## 接入方式概览

| 接入方式 | 操作 | 适用场景 | 持久性 |
|---------|------|---------|--------|
| 临时加载 | `--control-program module:Class` | 快速验证、实验 | 仅当前运行 |
| 正式注册到 benchmark | 修改 `tools/run_benchmark.py` | 长期研究、回归对比 | 永久 |
| 新 tracker/predictor 组合 | 扩展 `entities/raspi/trackers/` 或 `predictors/` | 复杂控制策略 | 永久 |
| 新角度模式算法 | 继承 `ControlProgram` 协议 | 非速率模式控制 | 永久 |

---

## 方式一：临时加载（最快上手）

### 第1步：写最小控制程序

在 `systemSimulation/` 下创建 `my_tracker.py`：

```python
from runtime.types import Command

class MyTracker:
    """最小控制程序示例：P 控制器。"""

    def on_tick(self, obs: dict) -> list[Command]:
        frame = obs.get("frame")
        if frame is None or not frame.get("detection_found"):
            return []

        u = frame["u_px"]
        v = frame["v_px"]
        cx, cy = frame["cx_px"], frame["cy_px"]
        du, dv = u - cx, v - cy

        kp = 1.0  # 调节这个参数
        yaw_rate = -kp * du
        pitch_rate = -kp * dv

        return [Command(target="gimbal", action="set_rate_target",
                        payload={"yaw_rate_dps": yaw_rate, "pitch_rate_dps": pitch_rate})]
```

### 第2步：本地调试

```bash
# 无 GUI 快速验证
conda run -n simulation python app.py --no-gui --control-program my_tracker:MyTracker --duration 5

# research 模式验证
conda run -n simulation python app.py --no-gui --control-program my_tracker:MyTracker --obs-mode research --duration 10

# 带延时验证
conda run -n simulation python app.py --no-gui --control-program my_tracker:MyTracker --delay-ms 26 --duration 10
```

### 第3步：查看结果

控制台输出中观察 `u/v/in_fov` 是否正常收敛。

---

## 方式二：正式注册到 benchmark

### 第1步：确保算法可构造为零参数工厂

benchmark 要求算法可通过工厂函数创建。如果算法需要参数，在工厂函数中硬编码：

```python
def _create_my_algorithm():
    from my_tracker import MyTracker
    return MyTracker(kp=1.5)
```

### 第2步：注册到 ALGORITHM_REGISTRY

编辑 `tools/run_benchmark.py`，在 `ALGORITHM_REGISTRY` 字典中添加：

```python
ALGORITHM_REGISTRY = {
    # ... 已有算法 ...
    "my_algorithm": _create_my_algorithm,
}

ALGORITHM_VERSIONS = {
    # ... 已有版本 ...
    "my_algorithm": "1.0",
}

ALGORITHM_OBS_MODES = {
    # ... 已有模式 ...
    "my_algorithm": ["research", "realistic", "debug"],
}
```

### 第3步：运行 benchmark

```bash
# 只跑你的算法
conda run -n simulation python tools/run_benchmark.py --algorithms my_algorithm --duration 20

# 与基线对比
conda run -n simulation python tools/run_benchmark.py \
    --algorithms atp_search_track_baseline my_algorithm --scenarios B1 B2 B3
```

### 第4步：完整研究流程

```bash
# 汇总
conda run -n simulation python tools/summarize_results.py

# 对比
conda run -n simulation python tools/compare_results.py \
    --baseline output/experiments --new output/experiments \
    --baseline-algorithms atp_search_track_baseline --new-algorithms my_algorithm

# 诊断
conda run -n simulation python tools/diagnose_algorithm.py \
    --algorithm my_algorithm --baseline-algorithm atp_search_track_baseline

# 出图
conda run -n simulation python tools/plot_comparison.py \
    --algorithms atp_search_track_baseline my_algorithm --plots all
```

---

## 方式三：新 tracker / predictor 组合

平台提供了可插拔的 ATP 控制架构，你可以只替换 tracker 或 predictor，复用 ATP 状态机。

### 架构说明

```
AtpControlProgram
  ├── AtpStateMachine  (SEARCH → ACQUIRE → TRACK_COARSE → TRACK_FINE)
  ├── Tracker          (compute_commands)  ← 你可以替换这里
  └── Predictor        (update + predict)  ← 你可以替换这里
```

### 写一个新 tracker

在 `entities/raspi/trackers/` 下创建 `my_tracker.py`：

```python
from runtime.types import Command
from entities.raspi.atp_state_machine import AtpState

class MyTracker:
    """自定义跟踪器示例。"""

    def compute_commands(self, obs: dict, atp_state: AtpState,
                         prediction: tuple[float, float] | None) -> list[Command]:
        frame = obs.get("frame")
        if frame is None or not frame.get("detection_found"):
            return []

        u = frame["u_px"]
        v = frame["v_px"]
        cx, cy = frame["cx_px"], frame["cy_px"]

        # 可使用 prediction 做前馈
        target_u = prediction[0] if prediction else cx
        target_v = prediction[1] if prediction else cy

        du = u - target_u
        dv = v - target_v

        kp = 1.2
        return [Command(target="gimbal", action="set_rate_target",
                        payload={"yaw_rate_dps": -kp * du, "pitch_rate_dps": -kp * dv})]
```

**Tracker 协议**：
```python
def compute_commands(self, obs: dict, atp_state: AtpState,
                     prediction: tuple[float, float] | None) -> list[Command]
```

### 写一个新 predictor

在 `entities/raspi/predictors/` 下创建 `my_predictor.py`：

```python
class MyPredictor:
    """自定义预测器示例。"""

    def __init__(self):
        self._initialized = False
        self._px = 0.0
        self._py = 0.0
        self._vx = 0.0
        self._vy = 0.0

    def update(self, obs: dict, detection) -> None:
        if detection is None or not detection.found:
            return
        px, py = detection.u_px, detection.v_px
        if not self._initialized:
            self._px, self._py = px, py
            self._initialized = True
            return
        dt = 0.005  # 200fps
        self._vx = (px - self._px) / dt
        self._vy = (py - self._py) / dt
        self._px, self._py = px, py

    def predict(self, n_steps: int) -> tuple[float, float] | None:
        if not self._initialized:
            return None
        dt = 0.005 * n_steps
        return (self._px + self._vx * dt, self._py + self._vy * dt)
```

**Predictor 协议**：
```python
def update(self, obs: dict, detection) -> None
def predict(self, n_steps: int) -> tuple[float, float] | None
```

### 注册组合到 benchmark

```python
def _create_my_combo():
    from entities.raspi.trackers.my_tracker import MyTracker
    from entities.raspi.predictors.my_predictor import MyPredictor
    from entities.raspi.atp_control_program import AtpControlProgram
    return AtpControlProgram(tracker=MyTracker(), predictor=MyPredictor())

ALGORITHM_REGISTRY["my_combo"] = _create_my_combo
ALGORITHM_VERSIONS["my_combo"] = "1.0"
ALGORITHM_OBS_MODES["my_combo"] = ["research", "realistic", "debug"]
```

---

## 方式四：新角度模式算法

如果你的算法不使用 ATP 状态机，而是直接使用角度模式控制：

```python
from runtime.types import Command

class MyAngleModeControl:
    """角度模式控制程序。"""

    def on_tick(self, obs: dict) -> list[Command]:
        gimbal = obs.get("gimbal", {})
        frame = obs.get("frame")

        if frame is None or not frame.get("detection_found"):
            return []

        # 需要 realistic/debug 模式才能读到 gimbal 角度
        current_yaw = gimbal.get("yaw_deg_internal", 0)
        current_pitch = gimbal.get("pitch_deg", 0)

        # 计算角度增量（需要知道相机焦距等参数）
        u = frame["u_px"]
        v = frame["v_px"]
        cx, cy = frame["cx_px"], frame["cy_px"]
        f_px = frame.get("f_current_px", 100)

        yaw_delta = -u / f_px * 180 / 3.14159  # 简化计算
        pitch_delta = v / f_px * 180 / 3.14159

        return [
            Command(target="gimbal", action="set_mode", payload={"mode": "ANGLE"}),
            Command(target="gimbal", action="set_angle_target",
                    payload={"yaw_deg": current_yaw + yaw_delta,
                             "pitch_deg": current_pitch + pitch_delta}),
        ]
```

注意：角度模式算法需要 `realistic` 或 `debug` 观测模式（需要 gimbal 角度反馈）。

---

## 已有算法架构对比

| 算法 | 架构 | Tracker | Predictor | 说明 |
|------|------|---------|-----------|------|
| `baseline_rate_p` | 直接 ControlProgram | — | — | 最简单的 P 控制器 |
| `atp_search_track_baseline` | AtpControlProgram | RatePTracker | — | ATP 状态机 + P 控制 |
| `rate_pi` | AtpControlProgram | RatePITracker | — | ATP + PI 控制 |
| `alpha_beta_tracker` | AtpControlProgram | RatePTracker | AlphaBetaFilter | ATP + P + α-β 预测 |
| `linear_kf_tracker` | AtpControlProgram | RatePTracker | LinearKF | ATP + P + 卡尔曼预测 |
| `angle_mode_realistic` | 自定义 ControlProgram | — | — | 角度模式直接控制 |

---

## 建议的算法目录组织

```
systemSimulation/
├── my_algorithm.py              # 临时实验（方式一）
├── entities/raspi/trackers/     # 正式 tracker（方式三）
│   ├── rate_p_tracker.py
│   ├── rate_pi_tracker.py
│   ├── angle_mode_tracker.py
│   └── my_tracker.py            # 你的 tracker
├── entities/raspi/predictors/   # 正式 predictor（方式三）
│   ├── alpha_beta.py
│   ├── linear_kf.py
│   └── my_predictor.py          # 你的 predictor
└── tools/run_benchmark.py       # 注册算法（方式二/三/四）
```

---

## 常见错误

### 1. 加载失败：`ModuleNotFoundError`

```
ModuleNotFoundError: No module named 'my_tracker'
```

**原因**：`.py` 文件不在 `systemSimulation/` 目录下，或模块名拼写错误。

**解决**：确认文件在正确位置，使用 `--control-program 文件名:类名`（不含 `.py`）。

### 2. 无控制效果

**原因**：控制程序返回空列表，或命令目标/动作拼写错误。

**解决**：检查 `Command(target="gimbal", action="set_rate_target", payload={...})` 的拼写。

### 3. debug 模式能跑，research 模式不能

**原因**：research 模式下 `obs["target"]` 不含真值（只有 debug 模式有）。

**解决**：控制程序不应依赖 `obs["target"]` 中的真值信息，只使用 `obs["frame"]` 中的检测结果。

### 4. 角度模式算法在 benchmark 中报错

**原因**：`angle_mode_realistic` 仅支持 `realistic`/`debug` 模式，不支持 `research`。

**解决**：在 `ALGORITHM_OBS_MODES` 中正确注册支持的观测模式。

### 5. 自定义 tracker 的 ATP 状态分布全是 SEARCH

**原因**：tracker 没有正确处理 `obs["frame"]`，导致 `detection_found` 始终为 False。

**解决**：在 tracker 中正确检测帧数据。

---

## 从开发到研究的完整端到端路径

```
1. 写控制程序（最小示例）
   ↓
2. 临时加载验证（--control-program）
   ↓
3. 注册到 benchmark（ALGORITHM_REGISTRY）
   ↓
4. 跑 benchmark（run_benchmark.py）
   ↓
5. 汇总结果（summarize_results.py）
   ↓
6. 对比基线（compare_results.py）
   ↓
7. 诊断退化（diagnose_algorithm.py）
   ↓
8. 生成图表（plot_comparison.py）
   ↓
9. 沉淀实验记录（--experiment-note + 手动补充）
   ↓
10. 迭代优化（回到第1步或第4步）
```

---

*接入指南完毕。控制程序的基础写法和测试方法论请参见[树莓派控制程序开发手册](树莓派控制程序开发手册.md)。*
