# Gimbal 实体文档

> 本文档讲述 Gimbal 实体的内部机制。如需了解与其他实体的组合使用，参见 [主 README](../../README.md)。

## 1. 概述与角色定位

两轴云台实体，模拟真实云台的机电行为。特点：

- 有电源状态机（OFF → BOOTING → READY）
- 两种控制模式：角度模式（串级 PID）和角速度模式（单环 PI）
- Yaw 轴连续旋转无硬限位，Pitch 轴受物理限位约束 `[-135°, +90°]`
- 一阶惯性执行器模型（时间常数 `tau_s`）

其他实体对 Gimbal 的依赖：
- **Camera** 需要 `gimbal_state["yaw_deg_internal"]` 计算光轴偏差角 alpha
- **Raspi** 通过命令（`set_rate_target`、`set_mode`）控制云台运动

## 2. 文件结构

```
entities/gimbal/
├─ entity.py      # GimbalEntity + GimbalState + 电源状态机
├─ model.py       # GimbalPlant2Axis + Gimbal2AxisState（一阶惯性被控对象）
├─ control.py     # CascadedController2Axis（串级 PID 控制器）
├─ client.py      # GimbalClient
└─ tests/
    └─ test_gimbal_entity.py
```

## 3. 状态机

```
OFF ──power_on()──> BOOTING (1.5s) ──boot_remaining<=0──> READY
                                                        │
BOOTING ──power_off()──> OFF                            │
READY ──power_off()──> OFF (同时重置被控对象和控制器)
```

**关键约束**：BOOTING 期间不接受 `set_mode` / `set_angle_target` / `set_rate_target`，返回 `CommandResult(False, "NOT_READY", ...)`。

## 4. 配置参数

### GimbalConfig

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `response_tau_s` | float | `0.03` | 一阶惯性时间常数（秒），越小响应越快 |
| `initial_angle_deg` | float | `0.0` | Yaw 初始内部角度（度） |
| `encoder_resolution_deg` | float | `0.0` | 编码器量化分辨率（阶段3新增，0=无量化） |
| `static_friction_threshold_dps` | float | `0.0` | 静摩擦死区阈值（阶段3新增，0=无死区） |
| `tau_deviation_ratio` | float | `0.0` | 时间常数随机偏差比（阶段3新增，0=无偏差） |

### AxisLimitConfig

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `pitch_min_deg` | float | `-135.0` | Pitch 下限（度） |
| `pitch_max_deg` | float | `90.0` | Pitch 上限（度） |
| `max_rate_dps` | float | `60.0` | 最大角速度（度/秒） |

### LoopConfig

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `angle_loop_hz` | float | `50.0` | 角度外环频率（Hz） |
| `rate_loop_hz` | float | `200.0` | 角速度内环频率（Hz） |

### ControlPreset

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `angle_kp_yaw` | float | `14.0` | Yaw 角度环 P 增益 |
| `angle_kp_pitch` | float | `14.0` | Pitch 角度环 P 增益 |
| `rate_kp_yaw` | float | `1.6` | Yaw 速率环 P 增益 |
| `rate_ki_yaw` | float | `5.0` | Yaw 速率环 I 增益 |
| `rate_kp_pitch` | float | `1.6` | Pitch 速率环 P 增益 |
| `rate_ki_pitch` | float | `5.0` | Pitch 速率环 I 增益 |
| `rate_integral_limit` | float | `30.0` | 积分项限幅 |
| `actuator_cmd_limit_dps` | float | `60.0` | 执行器指令限幅（度/秒） |

## 5. 内部模型详解

### 5.1 被控对象 GimbalPlant2Axis

一阶惯性模型，模拟执行器响应延迟：

```python
alpha = dt / (tau_s + dt)
actual_rate = (1 - alpha) * current_rate + alpha * cmd_rate
```

- `tau_s` 越小 → alpha 越大 → 响应越快（`tau_s=0` 时直接跟踪指令）
- Yaw 轴：`yaw_deg_internal += yaw_rate * dt`，无硬限位，可无限累加
- Pitch 轴：碰到 `[-135°, +90°]` 限位时速度归零，角度钳位
- 显示值 `yaw_deg_display = yaw_deg_internal % 360`（归一化到 [0, 360)）

> **阶段3升级**：被控对象新增三项非理想行为：
> - **静摩擦死区**：静止时低于阈值的速率命令被吸收（`static_friction_threshold_dps`）
> - **参数偏差**：`tau_s` 在初始化时添加随机偏差（`tau_deviation_ratio`），偏差运行中不变
> - **编码器量化**：通过 `get_measured_state()` 输出量化后的角度值，不影响 `get_state()` 的连续值

### 5.2 串级控制器 CascadedController2Axis

**ANGLE_MODE（角度模式）：**
```
外环 50Hz P 控制: angle_error ──[×Kp]──> rate_ref
内环 200Hz PI 控制: rate_error ──[×Kp + ∫Ki]──> actuator_cmd
```

外环输出 `rate_ref` 作为内环的设定值，内环输出 `actuator_cmd` 驱动被控对象。

**RATE_MODE（角速度模式）：**
```
外环旁路: rate_ref = 用户设定值
内环 200Hz PI 控制: 同上
```

Yaw 角度误差使用 `_wrap_pm180` 处理跨 360° 边界的最短路径。

**双环 tick 定时器**：外环和内环各自维护一个累加器 `_angle_accum_s` / `_rate_accum_s`。只有累加到对应周期时才执行计算，非 tick 帧复用上一次输出。

## 6. 数据流

```
Command ──> entity.set_rate_target(yaw, pitch, ts)
                    │
              _latest_rate_cmd
                    │
          CascadedController2Axis.step()
           ├─ 外环(ANGLE_MODE): angle_error → rate_ref
           └─ 内环: rate_error → [PI] → actuator_cmd
                    │
         (yaw_rate_cmd_dps, pitch_rate_cmd_dps)
                    │
          GimbalPlant2Axis.step()
           ├─ 一阶惯性: actual_rate = (1-α)*cur + α*cmd
           └─ 限位/限幅
                    │
              Gimbal2AxisState ──> GimbalState ──> get_state()
```

## 7. Client API

`GimbalClient`（`entities/gimbal/client.py`）：

| 方法 | 参数 | 说明 |
|------|------|------|
| `power_on(timestamp?)` | — | 上电，进入 BOOTING |
| `power_off(timestamp?)` | — | 关机，重置被控对象和控制器 |
| `set_mode(mode, timestamp?)` | `"ANGLE_MODE"` 或 `"RATE_MODE"` | 切换控制模式 |
| `set_angle_target(yaw, pitch, timestamp?)` | 度 | 设置角度目标（仅 ANGLE_MODE 有效） |
| `set_rate_target(yaw_rate, pitch_rate, timestamp?)` | 度/秒 | 设置角速度目标 |
| `get_state() -> dict` | — | 读取完整状态 |
| `get_device_status() -> dict` | — | 仅 `{power_state, mode}` |

代码示例：

```python
from runtime.digital_twin_runtime import DigitalTwinRuntime

rt = DigitalTwinRuntime()
gc = rt.gimbal_client

gc.power_on()
# 等待 READY...
gc.set_mode("RATE_MODE")
gc.set_rate_target(yaw_rate=30.0, pitch_rate=0.0)

# 切换角度模式
gc.set_mode("ANGLE_MODE")
gc.set_angle_target(yaw=45.0, pitch=-10.0)

state = gc.get_state()
print(f"yaw={state['yaw_deg_display']:.1f} pitch={state['pitch_deg']:.1f}")
```

## 8. 调试与排错

| 问题 | 排查 |
|------|------|
| 命令被拒绝 (`NOT_READY`) | 检查 `power_state` 是否为 `READY`，BOOTING 需 1.5s |
| Pitch 不响应 | 检查是否超过 `[-135°, +90°]` 限位 |
| Yaw 显示值跳变 | 内部角连续累加，显示值取模 360°，属正常行为 |
| 角度模式振荡 | 检查 `angle_kp` 是否过大，建议从默认值微调 |
| 内环积分饱和 | 检查 `rate_integral_limit`（默认 30）和 `actuator_cmd_limit_dps`（默认 60） |
| rate_tick 始终为 True | 正常，内环 200Hz 远高于仿真步频 200Hz |

## 9. 扩展点

- **添加前馈控制**：在 `CascadedController2Axis` 中增加前馈通道，将目标角速度直接加到内环输出
- **自定义被控对象**：继承或替换 `GimbalPlant2Axis`，例如加入二阶模型或死区
- **PID 参数自整定**：使用 `tools/pid_tuner.py` 扫描参数空间

## 10. 测试

```bash
conda run -n simulation python -m unittest discover -s entities\gimbal\tests -p "test_*.py" -v
conda run -n simulation python -m unittest tests.test_gimbal_2axis_core -v
```
