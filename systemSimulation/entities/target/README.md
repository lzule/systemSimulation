# Target 实体文档

> 本文档讲述 Target 实体的内部机制。如需了解与其他实体的组合使用，参见 [主 README](../../README.md)。

## 1. 概述与角色定位

Target 代表被跟踪目标在世界坐标系中的运动。它是**只读的被动实体**——不接受任何命令，从创建起即活跃。

其他实体对 Target 的依赖：
- **Camera** 需要 `target_state` 中的 `x_m, y_m` 计算目标方位角 bearing
- **Raspi** 通过 `world_obs["target"]` 获取完整目标状态

## 2. 文件结构

```
entities/target/
├─ entity.py      # TargetEntity + TargetState
├─ model.py       # TargetKinematics2D（4 种运动模式）
├─ control.py     # PassiveTargetController（空占位，统一目录结构）
├─ client.py      # TargetClient（仅 get_state，无命令提交）
└─ tests/
    └─ test_target_entity.py
```

## 3. 状态机

**Target 没有电源状态机。** 与 Gimbal/Camera/Raspi 的 OFF → BOOTING → READY 不同，Target 从创建起就处于活跃状态，每个 tick 都会推进运动模型。

## 4. 配置参数

配置类 `TargetConfig`（定义在 `config.py`）：

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `motion_type` | str | `"sinusoidal"` | 运动模式，可选值见下 |
| `initial_x_m` | float | `100.0` | 初始 X 坐标（米） |
| `initial_y_m` | float | `0.0` | 初始 Y 坐标（米） |
| `velocity_x_mps` | float | `0.0` | X 方向初速度（m/s） |
| `velocity_y_mps` | float | `1.5` | Y 方向初速度（m/s） |
| `accel_x_mps2` | float | `0.0` | X 方向加速度（m/s²） |
| `accel_y_mps2` | float | `0.3` | Y 方向加速度（m/s²） |
| `sin_amplitude_m` | float | `15.0` | 正弦振幅（米） |
| `sin_frequency_hz` | float | `0.2` | 正弦频率（Hz） |
| `random_max_accel_mps2` | float | `1.0` | 随机最大加速度（m/s²） |
| `random_damping` | float | `0.98` | 速度阻尼系数 |
| `random_seed` | int | `42` | 随机种子（可复现） |

## 5. 内部模型详解

### 5.1 TargetKinematics2D

核心方法 `step(dt) -> (x, y)`，根据 `motion_type` 分支：

**constant_velocity（匀速直线）**
```
x += vx * dt
y += vy * dt
```

**constant_accel（匀加速）**
```
vx += ax * dt
vy += ay * dt
x += vx * dt
y += vy * dt
```

**sinusoidal（正弦摆动）**
```
x = initial_x_m                          # X 固定
y = sin_amplitude * sin(2π * sin_frequency * t)
```

**random_walk（随机游走）**
```
ax = uniform(-max_accel, +max_accel)
ay = uniform(-max_accel, +max_accel)
vx = vx * damping + ax * dt
vy = vy * damping + ay * dt
x += vx * dt
y += vy * dt
```

### 5.2 派生属性

```python
bearing_deg = atan2(y, x) 转角度    # 目标方位角
distance_m = hypot(x, y)            # 目标距离
```

## 6. 数据流

```
TargetConfig ──> TargetKinematics2D.step(dt)
                        │
                   (x_m, y_m)
                        │
                   bearing_deg, distance_m
                        │
                   TargetState ──> get_state() ──> dict
```

Runtime 中的调用方式：

```python
# runtime/digital_twin_runtime.py step() 内
target_state = self.target.update(self.dt_s, self._time)
# 传给 Camera
camera_state = self.camera.update(dt, time, target_state.__dict__, gimbal_state.__dict__)
# 组入 world_obs 传给 Raspi
world_obs = { "target": target_state.__dict__, ... }
```

## 7. Client API

`TargetClient`（`entities/target/client.py`）只有一个方法：

| 方法 | 返回 | 说明 |
|------|------|------|
| `get_state() -> dict` | `{timestamp, x_m, y_m, bearing_deg, distance_m}` | 只读，无命令提交 |

## 8. 调试与排错

| 问题 | 排查 |
|------|------|
| 轨迹不对 | 检查 `motion_type` 是否匹配预期 |
| 初始位置偏移 | 检查 `initial_x_m` / `initial_y_m` |
| constant_accel 速度越来越快 | 预期行为，检查 `accel_x/y_mps2` 是否过大 |
| random_walk 不可复现 | 确保 `random_seed` 一致 |
| 目标跑出视野 | 调整 `sin_amplitude_m` 或 `random_max_accel_mps2` |

## 9. 扩展点

添加新运动模式：

1. 在 `TargetConfig` 中增加对应参数
2. 在 `TargetKinematics2D.step()` 中增加 `elif self.cfg.motion_type == "your_mode":` 分支

## 10. 测试

```bash
python -m unittest discover -s entities\target\tests -p "test_*.py" -v
```
