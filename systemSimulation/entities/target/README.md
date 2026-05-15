# Target 实体文档

> 本文档讲述 Target 实体的内部机制。如需了解与其他实体的组合使用，参见 [主 README](../../README.md)。

## 1. 概述与角色定位

Target 代表被跟踪目标在世界坐标系中的运动。它是**只读的被动实体**——不接受任何命令，从创建起即活跃。

> **阶段2升级**：目标模型已从 2D（x, y）升级为 3D（x, y, z），支持高度维度的运动。方位角 `bearing_deg` 保留为 `azimuth_deg` 的别名，新增 `elevation_deg`（俯仰角）和 `z_m`（高度）状态字段。距离计算已从 2D（`hypot(x, y)`）升级为 3D（`sqrt(x^2+y^2+z^2)`）。

其他实体对 Target 的依赖：
- **Camera** 需要 `target_state` 中的 `x_m, y_m, z_m` 计算目标方位角 alpha 和俯仰角 beta
- **Raspi** 通过 `world_obs["target"]` 获取完整目标状态（含 `azimuth_deg`、`elevation_deg`、`z_m`、`vz_mps`）

## 2. 文件结构

```
entities/target/
├─ entity.py      # TargetEntity + TargetState（含 z_m/azimuth_deg/elevation_deg/vz_mps 字段）
├─ model.py       # TargetKinematics3D（5 种运动模式，3D 坐标）
├─ control.py     # PassiveTargetController（空占位，统一目录结构）
├─ client.py      # TargetClient（仅 get_state，无命令提交）
├─ __init__.py    # 导出 TargetKinematics3D，保留 TargetKinematics2D 别名
└─ tests/
    └─ test_target_entity.py
```

## 3. 状态机

**Target 没有电源状态机。** 与 Gimbal/Camera/Raspi 的 OFF → BOOTING → READY 不同，Target 从创建起就处于活跃状态，每个 tick 都会推进运动模型。

## 4. 配置参数

配置类 `TargetConfig`（定义在 `config.py`）：

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `motion_type` | `Literal["sinusoidal", "constant_velocity", "constant_accel", "random_walk", "waypoint"]` | `"sinusoidal"` | 运动模式，下拉选择 |
| `initial_x_m` | float | `100.0` | 初始 X 坐标（米） |
| `initial_y_m` | float | `0.0` | 初始 Y 坐标（米） |
| `initial_z_m` | float | `0.0` | 初始 Z 坐标（米），阶段2新增 |
| `velocity_x_mps` | float | `0.0` | X 方向初速度（m/s），constant_velocity / constant_accel 使用 |
| `velocity_y_mps` | float | `1.5` | Y 方向初速度（m/s），constant_velocity / constant_accel 使用 |
| `velocity_z_mps` | float | `0.0` | Z 方向初速度（m/s），阶段2新增 |
| `accel_x_mps2` | float | `0.0` | X 方向加速度（m/s²），constant_accel 使用 |
| `accel_y_mps2` | float | `0.3` | Y 方向加速度（m/s²），constant_accel 使用 |
| `accel_z_mps2` | float | `0.0` | Z 方向加速度（m/s²），阶段2新增 |
| `sin_amplitude_m` | float | `15.0` | 正弦振幅（米），sinusoidal 使用 |
| `sin_frequency_hz` | float | `0.2` | 正弦频率（Hz），sinusoidal 使用 |
| `random_max_accel_mps2` | float | `1.0` | 随机最大加速度（m/s²），random_walk 使用 |
| `random_damping` | float | `0.98` | 速度阻尼系数，random_walk 使用 |
| `random_seed` | int | `42` | 随机种子（可复现），random_walk 使用 |
| `waypoints` | list | `None` | 航点列表 `[(x, y, z, speed), ...]`，speed=0 悬停，waypoint 使用，阶段2扩展支持 z |
| `waypoint_arrival_radius_m` | float | `1.0` | 到达航点判定半径（米），waypoint 使用 |

## 5. 内部模型详解

### 5.1 TargetKinematics3D

> **阶段2升级**：运动学模型从 2D（`TargetKinematics2D`）升级为 3D（`TargetKinematics3D`），新增 z 坐标和 vz 速度。旧名 `TargetKinematics2D` 保留为别名。

核心方法 `step(dt) -> (x, y, z)`，根据 `motion_type` 分支（共 5 种模式）：

**constant_velocity（匀速直线）**
```
x += vx * dt
y += vy * dt
z += vz * dt
```

**constant_accel（匀加速）**
```
vx += ax * dt
vy += ay * dt
vz += az * dt
x += vx * dt
y += vy * dt
z += vz * dt
```

**sinusoidal（正弦摆动）**
```
x = initial_x_m                          # X 固定
y = sin_amplitude * sin(2π * sin_frequency * t)
z = initial_z_m                          # Z 固定（默认 0）
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

**waypoint（航点导航）**
```
朝当前航点以指定速度飞行（支持 3D 航点 (x, y, z, speed)）
到达（3D 距离 < arrival_radius）后切换下一航点
speed=0 时悬停，最后一个航点后停止
```

### 5.2 派生属性

```python
azimuth_deg = atan2(y, x) 转角度     # 目标方位角（= bearing_deg，保留别名）
elevation_deg = atan2(z, hypot(x, y)) 转角度  # 目标俯仰角（阶段2新增）
distance_m = sqrt(x^2 + y^2 + z^2)   # 3D 目标距离（阶段2从 2D 升级为 3D）
bearing_deg = azimuth_deg             # 保留别名，向后兼容
```

## 6. 数据流

```
TargetConfig ──> TargetKinematics3D.step(dt)
                        │
                   (x_m, y_m, z_m)
                        │
                   azimuth_deg, elevation_deg, distance_m
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
| `get_state() -> dict` | `{timestamp, x_m, y_m, z_m, azimuth_deg, bearing_deg, elevation_deg, distance_m, vx_mps, vy_mps, vz_mps}` | 只读，无命令提交 |

## 8. 调试与排错

| 问题 | 排查 |
|------|------|
| 轨迹不对 | 检查 `motion_type` 是否匹配预期 |
| 初始位置偏移 | 检查 `initial_x_m` / `initial_y_m` |
| constant_accel 速度越来越快 | 预期行为，检查 `accel_x/y_mps2` 是否过大 |
| random_walk 不可复现 | 确保 `random_seed` 一致 |
| 目标跑出视野 | 调整 `sin_amplitude_m` 或 `random_max_accel_mps2` |

## 9. 扩展点

添加新运动模式只需改 `config.py` 一个文件，UI 自动生效：

1. 在 `TargetConfig.motion_type` 的 `Literal[...]` 中加模式名
2. 在 `MOTION_MODE_PARAMS` 中加模式→字段映射（控制 UI 显隐）
3. 在 `TargetConfig` 中加新参数字段
4. 在 `TargetKinematics2D.step()` 中加 `elif` 分支实现物理逻辑

Config Editor 自动读取 `Literal` 类型生成下拉选项，并根据 `MOTION_MODE_PARAMS` 过滤显示对应参数。

## 10. 测试

```bash
conda run -n simulation python -m unittest discover -s entities\target\tests -p "test_*.py" -v
```
