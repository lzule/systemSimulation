# Runtime 调度器文档

> 本文档讲述 `DigitalTwinRuntime` 的内部机制。如需了解实体间组合使用，参见 [主 README](../README.md)。

## 1. 概述与角色定位

`DigitalTwinRuntime` 是整个仿真的统一调度器，职责：

- 创建并持有 4 个实体实例（Target、Gimbal、Camera、Raspi）
- 管理世界时钟（单调递增）
- 管理命令总线（提交、调度、分派）
- 为每个设备创建 Client 对象，供外部控制
- 每个 tick 按固定顺序推进所有实体，输出 `WorldSnapshot`

文件位置：`runtime/digital_twin_runtime.py`

## 2. 文件结构

```
runtime/
├─ digital_twin_runtime.py   # DigitalTwinRuntime 类
├─ types.py                  # Command, CommandResult, WorldSnapshot, FramePacket, Detection
├─ clients.py                # 导出 GimbalClient, CameraClient, RaspiClient
└─ __init__.py
```

## 3. tick 内固定顺序

每个 `step(n=1)` 的单步执行顺序：

```
1. _apply_due_commands()         -- 分发到期命令到 gimbal/camera/raspi
2. _time += dt_s                 -- 推进世界时钟
3. target.update(dt, time)       -- Target 运动学推进
4. gimbal.update(dt, time)       -- Gimbal 控制器+执行器闭环
5. camera.update(dt, time,       -- Camera 成像（需要 target + gimbal 状态）
         target_state, gimbal_state)
6. 组装 world_obs 字典           -- timestamp + target + gimbal + camera + frame
7. raspi.update(time, world_obs, -- Raspi 延时管线 + 控制程序
         submit_cmd, dt)
8. 发布 WorldSnapshot            -- 全实体状态浅拷贝
```

**为什么是这个顺序？**

- Target 先推进，因为 Camera 需要 target_state 计算 bearing 角
- Gimbal 先于 Camera，因为 Camera 需要 gimbal_state 计算 alpha 偏差角
- Raspi 在最后，因为它需要全量 world_obs（包含 frame）

## 4. 命令调度机制

### 4.1 命令提交

```python
submit_command(command: Command) -> None
```

外部通过 Client 调用。命令的生效时间：
```
apply_at = max(current_time + dt, command.timestamp)
```
保证命令最早在下一 tick 生效。

### 4.2 命令分派

`_dispatch(command)` 按 `command.target` 和 `command.action` 路由到对应实体方法：

| target  | action | 实体方法 |
|---------|--------|----------|
| gimbal  | power_on / power_off | gimbal.power_on / power_off |
| gimbal  | set_mode | gimbal.set_mode(payload["mode"]) |
| gimbal  | set_angle_target | gimbal.set_angle_target(payload["yaw"], payload["pitch"]) |
| gimbal  | set_rate_target | gimbal.set_rate_target(payload["yaw_rate"], payload["pitch_rate"]) |
| camera  | power_on / power_off | camera.power_on / power_off |
| camera  | set_zoom_target_mm | camera.set_zoom_target_mm(payload["f_mm"]) |
| camera  | zoom_by | camera.zoom_by(payload["delta_mm"]) |
| camera  | set_zoom_rate_mmps | camera.set_zoom_rate_mmps(payload["rate_mmps"]) |
| raspi   | power_on / power_off | raspi.power_on / power_off |

### 4.3 latest-wins 语义

同一 tick 内如果对同一设备发了多条命令，所有命令都会执行（后执行的覆盖先执行的效果）。例如先 `set_rate_target(30)` 再 `set_rate_target(-10)`，最终生效 `-10`。

### 4.4 Raspi 内部命令

Raspi 的控制程序通过 `on_tick()` 产出的命令使用 `_submit_command_at(cmd, apply_at)`，可以精确指定生效时间，不经过 `max(now+dt, ts)` 的延迟。

## 5. Client 创建与绑定

Runtime 构造函数中为每个设备创建 Client，通过闭包绑定：

```python
self.gimbal_client = GimbalClient(
    submit_command=self.submit_command,     # 提交命令
    get_state=self._get_gimbal_state,       # 读取状态
    get_status=self._get_gimbal_status,     # 读取 power_state + mode
)
self.camera_client = CameraClient(
    submit_command=self.submit_command,
    get_state=self._get_camera_state,
    get_frame=self._get_camera_frame,
)
self.raspi_client = RaspiClient(
    submit_command=self.submit_command,
    get_state=self._get_raspi_state,
    set_delay=self.raspi.set_delay_profile,
    get_delay=self.raspi.get_delay_profile,
    load_program=self.raspi.load_control_program,
)
```

注意：**没有 TargetClient**。Target 是只读的被动实体，不接受命令。

## 6. Bootstrap 启动流程

`simulation/bootstrap.py` 提供两个函数：

### 6.1 build_runtime(delay_ms)

```
1. 创建 DigitalTwinRuntime()
2. 调用 start_stack(runtime, delay_ms)
3. 返回 runtime
```

### 6.2 start_stack(runtime, delay_ms, tuning)

```
1. 三设备上电：gimbal_client.power_on() / camera_client.power_on() / raspi_client.power_on()
2. 循环 step(1) 最多 3200 步，等待三者全部进入 READY
   - Gimbal boot: 1.5s
   - Camera boot: 0.5s
   - Raspi boot: 1.0s
   - 默认 dt=0.005s，3200 步 = 16s，足够覆盖
   - 超时抛 RuntimeError
3. 加载控制程序：raspi_client.load_control_program(BaselineTrackerProgram)
4. 设置延时链路：apply_delay_profile(runtime, delay_ms)
```

### 6.3 apply_delay_profile 的延时拆分

```python
delay_s = delay_ms / 1000
image_read_delay_s = delay_s
image_process_delay_s = delay_s
state_read_delay_s = delay_s * 0.5    # 状态读取减半
command_tx_delay_s = delay_s
jitter_std_s = 0.0
```

## 7. WorldSnapshot 结构

`WorldSnapshot` 是每个 tick 的输出，包含四个实体的状态字典（浅拷贝）：

```python
@dataclass
class WorldSnapshot:
    timestamp: float
    target: Dict[str, Any]   # x_m, y_m, bearing_deg, distance_m
    gimbal: Dict[str, Any]   # power_state, mode, yaw_deg_internal, yaw_deg_display,
                             # pitch_deg, yaw_rate_dps, pitch_rate_dps,
                             # yaw_rate_ref_dps, pitch_rate_ref_dps,
                             # angle_tick, rate_tick, last_command_apply_timestamp
    camera: Dict[str, Any]   # power_state, f_current_mm, f_target_mm,
                             # zoom_rate_cmd_mmps, frame_id, in_fov, u_px, v_px
    raspi: Dict[str, Any]    # power_state, effective_obs_timestamp,
                             # pipeline_backlog_len, last_process_latency_s,
                             # last_command_apply_timestamp, delay_metrics
```

## 8. 运行模式

### 8.1 realtime 模式

启动守护线程，循环 `step(1)` + `sleep` 补齐到 `dt_s`：

```python
def _loop():
    while self._running:
        t0 = time.perf_counter()
        self.step(1)
        elapsed = time.perf_counter() - t0
        time.sleep(max(0, self.dt_s - elapsed))
```

### 8.2 offline 模式

不启动线程。由调用方手动调用 `step(n)`：

```python
runtime = DigitalTwinRuntime()
for _ in range(4000):
    snapshot = runtime.step(1)
```

## 9. 线程安全

Runtime 内部使用 `threading.RLock`（可重入锁）保护：

- `step()` 方法在锁内执行
- `get_world_snapshot()` 在锁内执行（浅拷贝快照）
- `submit_command()` 在锁内追加命令

Client 的 `get_state()` / `get_frame()` 最终也走锁内路径。

## 10. 调试与排错

| 问题 | 排查方法 |
|------|----------|
| READY 超时 | 检查 boot_delay 配置：Gimbal 1.5s, Camera 0.5s, Raspi 1.0s；dt=5ms 时最多 3200 步 |
| 命令不生效 | 检查实体是否 READY；检查 command.timestamp 是否在未来 |
| 命令延迟生效 | 正常行为，apply_at = max(now+dt, cmd.timestamp)，最早下 tick |
| 线程竞争 | Runtime 使用 RLock，不应出现竞争；如遇问题检查是否有绕过 Client 直接操作实体的代码 |
| snapshot 数据被意外修改 | WorldSnapshot 中各 dict 是浅拷贝，嵌套对象仍可能被修改——只读使用即可 |

## 11. 测试

主线测试：`tests/test_runtime_api.py`、`tests/test_digital_twin_runtime.py`

```bash
conda run -n simulation python -m unittest discover -s tests -v
```
