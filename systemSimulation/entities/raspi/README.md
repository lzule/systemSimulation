# Raspi 实体文档

> 本文档讲述 Raspi 实体的内部机制。如需了解与其他实体的组合使用，参见 [主 README](../../README.md)。

## 1. 概述与角色定位

树莓派控制侧实体，模拟真实嵌入式硬件的完整控制链路：

- 有电源状态机（OFF → BOOTING → READY）
- **三级延时管线**：观测读取 → 图像处理 → 命令发送，每级可配延时和抖动
- **可插拔控制程序**：通过 `ControlProgram` 协议实现控制逻辑与运行时解耦
- **唯一通过回调提交命令的实体**：控制程序输出的命令通过 `submit_cmd` 回调注入 Runtime

核心职责：接收全量 `world_obs`，经过延时处理后调用控制程序，将产出的命令注入 Runtime 命令总线。

## 2. 文件结构

```
entities/raspi/
├─ entity.py            # RaspiEntity + RaspiState
├─ model.py             # RaspiDelayModel（封装 DelayPipeline）
├─ delay_pipeline.py    # DelayPipeline（最小堆三级延时队列）
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
BOOTING/READY ──power_off()──> OFF (同时重置 DelayPipeline)
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
| `image_read_delay_s` | float | `0.0` | 图像读取延时（秒） |
| `image_process_delay_s` | float | `0.02` | 图像处理延时（秒） |
| `state_read_delay_s` | float | `0.0` | 状态读取延时（秒） |
| `command_tx_delay_s` | float | `0.0` | 命令发送延时（秒） |
| `jitter_std_s` | float | `0.0` | 各级延时的抖动标准差（秒） |

### TrackerTuning（基线跟踪参数）

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `yaw_rate_kp_dps_per_px` | float | `0.08` | 像素误差→角速度的比例增益 |
| `max_yaw_rate_dps` | float | `60.0` | 最大 Yaw 角速度 |
| `deadband_px` | float | `2.0` | 死区（像素），小于此值归零 |
| `lost_target_hold_rate_dps` | float | `0.0` | 目标丢失时的保持角速度 |
| `enable_zoom_control` | bool | `False` | 是否启用自动变焦 |
| `zoom_in_error_px` | float | `40.0` | 误差小于此值时放大 |
| `zoom_out_error_px` | float | `120.0` | 误差大于此值时缩小 |
| `zoom_step_mm` | float | `1.0` | 每次变焦步长（毫米） |
| `zoom_cooldown_s` | float | `0.15` | 变焦冷却时间（秒） |

## 5. 内部模型详解

### 5.1 延时管线 DelayPipeline

基于最小堆的三级延时队列，模拟真实嵌入式系统的处理链路：

```
_obs_heap (观测队列)  ──>  _proc_heap (处理队列)  ──>  _cmd_heap (命令队列)
```

每级提供：
- `push_*(available_at, payload)` — 压入，`available_at = 当前时间 + 该级延时 + jitter`
- `pop_ready_*(now)` — 弹出所有 `available_at <= now` 的项
- `backlog_len()` — 三级队列总积压数

jitter 由 `random.gauss(0, jitter_std_s)` 生成（`jitter_std_s=0` 时无抖动）。

### 5.2 一个 tick 的完整处理流程

RaspiEntity 在 READY 状态下每个 tick 的执行步骤：

```
1. 计算观测延时: obs_delay = max(image_read, state_read) + jitter
   push_obs(now + obs_delay, world_obs)

2. pop_ready_obs(now) -> 对每条到期观测:
   计算 process_available = now + image_process_delay + jitter
   push_proc(process_available, {obs, ready_at})

3. pop_ready_proc(now) -> 对每条到期处理结果:
   记录 effective_obs_timestamp = obs.timestamp
   调用 control_program.on_tick(obs) -> cmds
   对每条 cmd: push_cmd(now + command_tx_delay + jitter, cmd)

4. pop_ready_cmd(now) -> 对每条到期命令:
   submit_cmd(cmd, now + runtime_dt)   -- 注入 Runtime 命令总线
```

**关键**：观测从进入到命令生效，经过三级延时。如果总延时 > 帧间隔，管线中会积累积压（`pipeline_backlog_len` 增大）。

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
| `frame` | FramePacket | 渲染帧：`image(ndarray), intrinsics(dict), optional_gt(dict)` |

**输出**：`list[Command]`，可控制 gimbal 和 camera。

### 5.4 BaselineTrackerProgram

默认装载的基线跟踪控制程序，处理流程：

```
1. 确保云台处于 RATE_MODE（如不是则发送 set_mode 命令）
2. 从 frame.image 中检测光斑质心（detect_beacon_centroid）
3. 计算像素误差: pixel_error_x = det.cx - cx（cx 来自相机内参）
4. 死区处理: |error| < deadband_px 时归零
5. 比例映射: yaw_rate_cmd = kp * pixel_error_x，限幅到 [-max, +max]
6. 输出 set_rate_target(yaw_rate_cmd, 0) 命令
7. [可选] 根据误差大小自动变焦
```

**丢失目标处理**：检测不到目标时，输出 `lost_target_hold_rate_dps` 作为维持角速度（默认 0，即停止跟踪）。

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
   DelayPipeline
   ├─ obs_heap (观测延时)
   ├─ proc_heap (处理延时)
   └─ cmd_heap (命令发送延时)
        │
   control_program.on_tick(obs) ──> list[Command]
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
| `power_off(timestamp?)` | — | 关机，重置管线 |
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
print(f"backlog={state['pipeline_backlog_len']} "
      f"latency={state['last_process_latency_s']*1000:.1f}ms")
```

## 8. 调试与排错

| 问题 | 排查 |
|------|------|
| 命令发不出去 | 检查延时配置是否过大（管线积压），查看 `pipeline_backlog_len` |
| 控制程序收不到帧 | 检查 `obs["frame"]` 是否为 None（不应该，Camera 始终渲染帧） |
| 帧是全黑的 | 目标不在视场内时帧全黑但 frame 不为 None；质心检测返回 `found=False` |
| 延时太大导致跟踪失效 | 先用 0 延时跑通闭环，再逐步增加 |
| `effective_obs_timestamp` 远小于当前时间 | 正常，表示观测陈旧（延时链路的效果） |
| backlog 持续增长 | 延时总和 > tick 间隔，管线无法消化；减小延时或增大 dt |
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
                cmd_rate = 0.08 * err + 0.01 * d_err

                cmds.append(Command(
                    target="gimbal",
                    action="set_rate_target",
                    payload={"yaw_rate": cmd_rate, "pitch_rate": 0.0},
                    timestamp=ts,
                    source="my_controller",
                ))
        return cmds
```

### 9.2 添加延时级别

修改 `DelayPipeline` 增加第四级队列（例如网络传输延时）。

### 9.3 替换检测算法

在控制程序中使用自己的检测算法替代 `detect_beacon_centroid`。

## 10. 测试

```bash
python -m unittest discover -s entities\raspi\tests -p "test_*.py" -v
```
