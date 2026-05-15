# Raspi 实体文档

> 本文档讲述 Raspi 实体的内部机制。如需了解与其他实体的组合使用，参见 [主 README](../../README.md)。

## 1. 概述与角色定位

树莓派控制侧实体，模拟真实嵌入式硬件的完整控制链路：

- 有电源状态机（OFF → BOOTING → READY）
- **可配置延时状态机**：统一状态机 IDLE → READING → PROCESSING → SENDING → IDLE，支持 `latest`（默认单槽抓最新）和 `fifo`（有限队列）两种缓冲策略
- **可插拔控制程序**：通过 `ControlProgram` 协议实现控制逻辑与运行时解耦
- **唯一通过回调提交命令的实体**：控制程序输出的命令通过 `submit_cmd` 回调注入 Runtime

> **阶段2升级**：基线跟踪控制程序（BaselineTrackerProgram）已从单轴（仅 yaw）升级为双轴（yaw + pitch）。pitch_rate 不再恒为 0，而是由 v 方向像素误差驱动，与 yaw 轴采用相同的比例控制结构。TrackerTuning 新增 pitch 相关参数。

核心职责：接收全量 `world_obs`，经过延时处理后调用控制程序，将产出的命令注入 Runtime 命令总线。

> **阶段3升级**：Runtime 在将 `world_obs` 传递给 Raspi 之前，先经过 `ObsFilter`（`simulation/obs_filter.py`）按观测模式过滤。三种模式：`debug`（透传全部字段）、`research`（白名单过滤，无 target 真值）、`realistic`（含传感器噪声和量化测量值，无 target）。通过 `--obs-mode` CLI 参数控制。

## 2. 文件结构

```
entities/raspi/
├─ entity.py            # RaspiEntity + RaspiState（含延时状态机调度）
├─ model.py             # RaspiDelayModel（latest/fifo 缓冲策略 + IDLE→READING→PROCESSING→SENDING）
├─ delay_pipeline.py    # [遗留] DelayPipeline 三级堆队列（当前未使用，活跃实现在 model.py）
├─ control_program.py   # ControlProgram 协议 + NoopControlProgram
├─ tracker_program.py   # BaselineTrackerProgram + TrackerTuning
├─ client.py            # RaspiClient
└─ tests/
    ├─ test_raspi_entity.py
    └─ test_tracker_program.py
```

## 3. 状态机

```
OFF ──power_on()──> BOOTING (1.0s) ──boot_remaining<=0──> READY
                                                        │
BOOTING/READY ──power_off()──> OFF (同时重置 RaspiDelayModel)
```

## 4. 配置参数

### RaspiConfig

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `boot_delay_s` | float | `1.0` | 启动延时（秒） |
| `enabled` | bool | `True` | 是否启用 |

### RaspiDelayConfig

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `image_read_delay_s` | float | `0.005` | 图像读取延时（秒） |
| `image_process_delay_s` | float | `0.015` | 图像处理延时（秒） |
| `state_read_delay_s` | float | `0.003` | 状态读取延时（秒） |
| `command_tx_delay_s` | float | `0.003` | 命令发送延时（秒） |
| `jitter_std_s` | float | `0.001` | 各级延时的抖动标准差（秒） |
| `buffer_policy` | str | `"latest"` | 缓冲策略：latest=单槽抓最新，fifo=有限队列（阶段3新增） |
| `queue_capacity` | int | `1` | fifo 队列容量（阶段3新增，1+latest=当前行为） |
| `control_rate_hz` | float | `0.0` | 控制采样率（阶段3新增，0=每tick，>0=指定频率） |

### TrackerTuning（基线跟踪参数）

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `yaw_rate_kp_dps_per_px` | float | `1.1` | 像素误差→角速度的比例增益（yaw 轴） |
| `max_yaw_rate_dps` | float | `60.0` | 最大 Yaw 角速度 |
| `pitch_rate_kp_dps_per_px` | float | `1.1` | 像素误差→角速度的比例增益（pitch 轴，阶段2新增） |
| `max_pitch_rate_dps` | float | `60.0` | 最大 Pitch 角速度（阶段2新增） |
| `deadband_px` | float | `2.0` | 死区（像素），小于此值归零 |
| `lost_target_hold_rate_dps` | float | `0.0` | 目标丢失时的保持角速度 |
| `enable_zoom_control` | bool | `False` | 是否启用自动变焦 |
| `zoom_in_error_px` | float | `40.0` | 误差小于此值时放大 |
| `zoom_out_error_px` | float | `120.0` | 误差大于此值时缩小 |
| `zoom_step_mm` | float | `1.0` | 每次变焦步长（毫米） |
| `zoom_cooldown_s` | float | `0.15` | 变焦冷却时间（秒） |

## 5. 内部模型详解

### 5.1 延时模型 RaspiDelayModel

`RaspiDelayModel`（`model.py`）是当前活跃的延时实现，采用统一状态机并支持两种缓冲策略：

- `latest`：默认策略，保持单槽忙/闲行为
- `fifo`：有限队列策略，忙时缓存观测，队列满时丢弃最旧帧

```
IDLE ──try_start()──> READING ──delay到期──> PROCESSING ──delay到期──> SENDING ──delay到期──> IDLE
 │                        │                       │                        │
 └─ 空闲，可接受新帧      └─ 正在读取观测         └─ 正在处理图像          └─ 正在发送命令
```

核心设计：
- **latest**：任意时刻最多处理一帧观测，忙时跳过新帧，空闲时抓取最新帧
- **fifo**：忙时将观测放入有限队列，队列满时丢弃最旧帧，空闲后优先处理积压
- **多速率控制**：`control_rate_hz > 0` 时限制新观测进入处理链路的频率
- **jitter**：由 `abs(random.gauss(0, jitter_std_s))` 生成，确保非负

状态说明：
- `try_start(timestamp, world_obs, obs_read_delay)` — 仅在 IDLE 时有效，记录观测并进入 READING
- `tick(timestamp, process_delay, cmd_tx_delay, control_program, jitter_fn)` — 推进状态机，返回 `[(obs_capture_ts, cmds)]` 列表
- `is_busy()` — 返回是否处于非 IDLE 状态

> **注意**：`delay_pipeline.py` 中的 `DelayPipeline` 类是早期基于最小堆的三级队列实现，当前未被引用（遗留代码）。活跃延时逻辑在 `model.py` 的 `RaspiDelayModel` 中。

### 5.2 一个 tick 的完整处理流程

RaspiEntity 在 READY 状态下每个 tick 的执行步骤：

```
1. 计算观测延时: obs_delay = max(image_read, state_read) + jitter
   delay_model.try_start(timestamp, world_obs, obs_delay)
   → 仅当状态机为 IDLE 时抓取最新 world_obs，进入 READING 状态
   → 如果状态机忙（READING/PROCESSING/SENDING），本帧被跳过

2. delay_model.tick(timestamp, process_delay, cmd_tx_delay, control_program, jitter_fn)
   → 内部状态机推进：

   a) READING 阶段到期:
      → 转入 PROCESSING，设置 ready_at = timestamp + image_process_delay + jitter

   b) PROCESSING 阶段到期:
      → 调用 control_program.on_tick(obs) → cmds
      → 记录 effective_obs_timestamp = obs_capture_ts
      → 转入 SENDING，设置 ready_at = timestamp + command_tx_delay + jitter
      → 返回 (obs_capture_ts, cmds) 给 entity

   c) SENDING 阶段到期:
      → 转回 IDLE，释放观测槽位

3. 对 tick 返回的每条命令:
   submit_cmd(cmd, timestamp + runtime_dt)   -- 注入 Runtime 命令总线
```

**关键特性**：
- **latest 模式**：忙时新帧被丢弃，行为与阶段 2 单槽模型兼容
- **fifo 模式**：`pipeline_backlog_len` 反映“当前处理中 + 队列积压”的总量
- **观测陈旧度**：`last_process_latency_s` 反映从观测抓取到命令产出的实际耗时

### 5.3 ControlProgram 协议

```python
class ControlProgram(Protocol):
    def on_tick(self, obs: dict) -> list[Command]: ...
```

**输入 `obs` 的字段结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | float | 观测的原始仿真时间 |
| `target` | dict | TargetState：`x_m, y_m, bearing_deg, distance_m` |
| `gimbal` | dict | GimbalState：`yaw_deg_internal, pitch_deg, mode, power_state, ...` |
| `camera` | dict | CameraState：`f_current_mm, frame_id, in_fov, u_px, v_px, ...` |
| `frame` | FramePacket | 渲染帧：`image(ndarray), intrinsics(dict)`；`optional_gt` 仅在 debug 模式下可见 |

**输出**：`list[Command]`，可控制 gimbal 和 camera。

### 5.4 BaselineTrackerProgram

默认装载的基线跟踪控制程序，处理流程：

> **阶段2升级**：跟踪控制已从单轴升级为双轴，pitch_rate 不再恒为 0，而是由 v 方向像素误差驱动。

```
1. 确保云台处于 RATE_MODE（如不是则发送 set_mode 命令）
2. 从 frame.image 中检测光斑质心（detect_beacon_centroid）
3. 计算双轴像素误差:
   - pixel_error_x = det.cx - cx（水平方向，cx 来自相机内参）
   - pixel_error_y = det.cy - cy（垂直方向，cy 来自相机内参，阶段2新增）
4. 死区处理: |error| < deadband_px 时归零（双轴独立判断）
5. 比例映射:
   - yaw_rate_cmd = kp * pixel_error_x，限幅到 [-max_yaw_rate, +max_yaw_rate]
   - pitch_rate_cmd = kp * pixel_error_y，限幅到 [-max_pitch_rate, +max_pitch_rate]
6. 输出 set_rate_target(yaw_rate_cmd, pitch_rate_cmd) 命令
7. [可选] 根据误差大小自动变焦
```

**丢失目标处理**：检测不到目标时，输出 `lost_target_hold_rate_dps` 作为两轴的维持角速度（默认 0，即停止跟踪）。

## 6. 数据流

```
Runtime 组装 world_obs
  ├─ target state
  ├─ gimbal state
  ├─ camera state
  └─ frame (FramePacket)
        │
        v
RaspiEntity.update(ts, world_obs, submit_cmd, dt)
        │
   RaspiDelayModel（latest/fifo 状态机）
   ├─ IDLE: try_start() 抓取观测（latest 取当前帧，fifo 优先取队列）→ READING
   ├─ READING: 延时到期 → PROCESSING
   ├─ PROCESSING: control_program.on_tick(obs) → cmds → SENDING
   └─ SENDING: 延时到期 → 回到 IDLE
        │
   submit_cmd(cmd, apply_at) ──> Runtime._submit_command_at
        │
   Runtime._apply_due_commands() ──> 实体方法调用
```

## 7. Client API

`RaspiClient`（`entities/raspi/client.py`）：

| 方法 | 参数 | 说明 |
|------|------|------|
| `power_on(timestamp?)` | — | 上电，1.0s 后 READY |
| `power_off(timestamp?)` | — | 关机，重置延时模型 |
| `load_control_program(program)` | 实现 `on_tick` 的对象 | 装载控制程序 |
| `set_delay_profile(**kwargs)` | 同 RaspiDelayConfig 字段名 | 动态修改延时参数 |
| `get_delay_profile() -> dict` | — | 查询当前延时配置 |
| `get_state() -> dict` | — | 完整状态字典 |

代码示例：

```python
from runtime.digital_twin_runtime import DigitalTwinRuntime
from entities.raspi.tracker_program import BaselineTrackerProgram, TrackerTuning

rt = DigitalTwinRuntime()
rc = rt.raspi_client

rc.power_on()
# 等待 READY...

# 加载自定义参数的跟踪程序
tuning = TrackerTuning(
    yaw_rate_kp_dps_per_px=0.1,
    max_yaw_rate_dps=40.0,
    deadband_px=3.0,
)
rc.load_control_program(BaselineTrackerProgram(tuning))

# 设置延时链路
rc.set_delay_profile(
    image_read_delay_s=0.01,
    image_process_delay_s=0.02,
    command_tx_delay_s=0.005,
    jitter_std_s=0.002,
)

# 查看状态
state = rc.get_state()
print(f"busy={state['pipeline_backlog_len']} "
      f"latency={state['last_process_latency_s']*1000:.1f}ms")
```

## 8. 调试与排错

| 问题 | 排查 |
|------|------|
| 命令发不出去 | 检查延时配置是否过大（总延时超过 tick 间隔时帧被跳过），查看 `pipeline_backlog_len` 是否始终为 1 |
| 控制程序收不到帧 | 检查 `obs["frame"]` 是否为 None（不应该，Camera 始终渲染帧） |
| 帧是全黑的 | 目标不在视场内时帧全黑但 frame 不为 None；质心检测返回 `found=False` |
| 延时太大导致跟踪失效 | 先用 0 延时跑通闭环，再逐步增加 |
| `effective_obs_timestamp` 远小于当前时间 | 正常，表示观测陈旧（延时链路的效果） |
| backlog 始终为 1 不归零 | 延时总和 > tick 间隔，状态机永远来不及回到 IDLE；减小延时或增大 dt |
| 控制程序报错 | 检查 `on_tick` 返回类型是否为 `list[Command]` |

## 9. 扩展点

### 9.1 自定义控制程序

实现 `ControlProgram` 协议：

```python
from runtime.types import Command

class MyController:
    def __init__(self):
        self.last_error = 0.0

    def on_tick(self, obs: dict) -> list[Command]:
        ts = float(obs["timestamp"])
        cmds = []

        # 你的控制逻辑
        frame = obs.get("frame")
        if frame is not None:
            from entities.camera.entity import detect_beacon_centroid
            det = detect_beacon_centroid(frame.image)
            if det.found and det.cx is not None:
                cx = float(frame.intrinsics["cx"])
                err = det.cx - cx
                # PD 控制
                d_err = err - self.last_error
                self.last_error = err
                cmd_rate = 1.1 * err + 0.01 * d_err

                cmds.append(Command(
                    target="gimbal",
                    action="set_rate_target",
                    payload={"yaw_rate": cmd_rate, "pitch_rate": 0.0},
                    timestamp=ts,
                    source="my_controller",
                ))
        return cmds
```

### 9.2 自定义延时行为

如需更复杂的延时行为（如多帧排队、优先级调度），可替换 `RaspiDelayModel` 的实现。注意 `delay_pipeline.py` 中的 `DelayPipeline` 是遗留代码，如需多级队列行为需重新实现。

### 9.3 替换检测算法

在控制程序中使用自己的检测算法替代 `detect_beacon_centroid`。

## 10. 测试

```bash
conda run -n simulation python -m unittest discover -s entities/raspi/tests -p "test_*.py" -v
```
