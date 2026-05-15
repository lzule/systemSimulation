# 云台数字孪生仿真系统

> **文档导航**
> - 使用手册（快速入门+验收）：[docs/使用手册.md](docs/使用手册.md)
> - 文档体系总览：[docs/doc-structure.md](docs/doc-structure.md)
> - 实体内部文档：[Target](entities/target/README.md) | [Gimbal](entities/gimbal/README.md) | [Camera](entities/camera/README.md) | [Raspi](entities/raspi/README.md)
> - Runtime 调度机制：[runtime/README.md](runtime/README.md)

---

## 1. 系统架构概览

### 1.1 四实体关系

```
Target ──── target_state (x_m, y_m, z_m) ────┐
                                             v
Gimbal ─── gimbal_state (yaw_deg, pitch_deg) ──> Camera ── frame + world_obs ──> Raspi
   ^                                                                   │
   └──────────── Command (set_rate_target, set_mode) ──────────────────┘
                     通过 Runtime 命令总线
```

- **Target**：目标运动体，输出世界坐标 `(x, y, z)`
- **Gimbal**：两轴云台，执行 yaw/pitch 角速度/角度控制，输出姿态
- **Camera**：挂载在云台上的相机，根据目标方位和云台姿态成像
- **Raspi**：树莓派控制器，从帧中检测目标，输出控制命令

### 1.2 统一调度

所有实体由 `DigitalTwinRuntime` 统一调度，每个 tick 按固定顺序推进：

```
收命令 -> Target -> Gimbal -> Camera -> Raspi -> 发布快照
```

命令仲裁采用 `latest-wins`，设备未 READY 时命令被拒绝。

详细机制参见 [runtime/README.md](runtime/README.md)。

### 1.3 一个 tick 的完整数据流

```
                      ┌─────────────── Target.update(dt, t) ──────────────┐
                      │ 输出: TargetState {x_m, y_m, z_m, azimuth_deg, elevation_deg, distance_m}
                      │
                      │    ┌────────── Gimbal.update(dt, t) ──────────────┐
                      │    │ 输入: Command (来自上 tick 的命令)
                      │    │ 输出: GimbalState {yaw_deg, pitch_deg, mode, ...}
                      │    │
┌─────────────────────┼────┼──────── Camera.update(dt, t, target, gimbal) ┐
│ Camera 需要:         │    │    │ 输入: target_state + gimbal_state
│ target.x/y → bearing│    │    │ 输出: CameraState + FramePacket
│ gimbal.yaw → alpha   │    │    │
│                      │    │    │   ┌──── Raspi.update(t, world_obs, ...) ┐
│ world_obs 包含:      ┘    │    │   │ 输入: {timestamp, target, gimbal,
│ target, gimbal,           │    │   │        camera, frame}
│ camera, frame             │    │   │ 输出: Command (通过回调注入)
│                           │    │   │
└───────────────────────────┘    │   └───────────> Runtime 命令总线 ──> Gimbal/Camera
                                 │
                                 └──> WorldSnapshot 发布
```

## 2. 快速开始

```bash
# 无 GUI 快速验证
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0

# GUI 实时仿真
conda run -n simulation python app.py --mode realtime --duration 60

# 带延时链路
conda run -n simulation python app.py --mode realtime --duration 30 --delay-ms 20

# 自定义控制程序
conda run -n simulation python app.py --no-gui --control-program my_tracker:MyTracker --duration 5

# 航点轨迹
conda run -n simulation python app.py --no-gui --waypoints "(100,0,20,2),(80,30,10,1.5),(60,0,0,0)" --duration 20

# 切换目标运动类型
conda run -n simulation python app.py --no-gui --target-type constant_velocity --duration 5

# 观测模式切换（阶段3新增）
conda run -n simulation python app.py --no-gui --obs-mode research --duration 5     # 研究模式（无target真值）
conda run -n simulation python app.py --no-gui --obs-mode realistic --duration 5    # 近真实模式（含传感器噪声）
```

成功判据：出现 `t=... yaw=... u=... in_fov=...` 周期输出，无异常堆栈。

## 3. 实体间数据流详解

### 3.1 Target → Camera：方位角传递

Camera 在 `update()` 中用 target 的 `(x_m, y_m)` 计算目标方位角，用 `(z_m, 水平距离)` 计算俯仰角：

```python
bearing = math.atan2(target_state["y_m"], target_state["x_m"])
```

这个 bearing 是目标相对于原点（云台位置）的方向角。

### 3.2 Gimbal → Camera：姿态传递

Camera 用 gimbal 的 `yaw_deg_internal` 计算光轴偏差角：

```python
yaw = math.radians(gimbal_state["yaw_deg_internal"])
alpha = (bearing - yaw + π) % (2π) - π   # 归一化到 [-π, π]
```

alpha 决定目标在图像中的水平像素位置：`u = f_px * tan(alpha) + w/2`。

同样地，垂直偏差角 `beta = elevation - pitch` 决定垂直像素位置：`v = cy - f_px * tan(beta)`。

### 3.3 Camera → Raspi：帧与观测传递

Runtime 在每个 tick 组装 `world_obs` 字典传给 Raspi：

```python
world_obs = {
    "timestamp": self._time,
    "target": target_state.__dict__,
    "gimbal": gimbal_state.__dict__,
    "camera": camera_state.__dict__,
    "frame": self.camera.get_frame(),   # FramePacket
}
# obs_filter 按 obs_mode 过滤控制器可见字段（阶段3新增）
raspi_obs = obs_filter.filter_obs(world_obs) if obs_filter else world_obs
raspi_state = self.raspi.update(self._time, raspi_obs, submit_cmd, dt)
```

Raspi 内部的延时管线决定观测何时被控制程序处理。

### 3.4 Raspi → Runtime → Gimbal/Camera：命令闭环

Raspi 的控制程序 `on_tick(obs)` 返回 `list[Command]`，经过延时管线后通过回调注入 Runtime：

```
Raspi.on_tick(obs) → cmds → 延时管线(IDLE→READING→PROCESSING→SENDING) → submit_cmd → Runtime._pending_commands
```

下一个 tick 的 `_apply_due_commands()` 将到期命令分派到对应实体。

典型的闭环路径（基线跟踪）：

```
帧中检测目标质心 → 计算像素误差 (u - cx, cy - v)
    → 比例映射 yaw_rate/pitch_rate = Kp * pixel_error
    → Command(gimbal, set_rate_target, yaw_rate, pitch_rate)
    → Gimbal 转动 → Camera 帧变化 → 循环
```

## 4. 组装联调

### 4.1 标准组装流程

使用 `build_runtime()` 一键完成：

```python
from simulation.bootstrap import build_runtime

runtime = build_runtime(delay_ms=0.0)
# 内部完成：创建实体 → 上电 → 等待 READY → 加载 BaselineTrackerProgram

for _ in range(4000):
    snapshot = runtime.step(1)
    print(f"t={snapshot.timestamp:.2f} yaw={snapshot.gimbal['yaw_deg_display']:.1f}")
```

### 4.2 自定义组装

```python
from runtime.digital_twin_runtime import DigitalTwinRuntime
from entities.raspi.tracker_program import BaselineTrackerProgram, TrackerTuning

runtime = DigitalTwinRuntime()

# 手动上电
runtime.gimbal_client.power_on()
runtime.camera_client.power_on()
runtime.raspi_client.power_on()

# 等待 READY
for _ in range(3200):
    snap = runtime.step(1)
    if (snap.gimbal["power_state"] == "READY"
        and snap.camera["power_state"] == "READY"
        and snap.raspi["power_state"] == "READY"):
        break

# 加载自定义控制程序
tuning = TrackerTuning(yaw_rate_kp_dps_per_px=0.1, deadband_px=1.0)
runtime.raspi_client.load_control_program(BaselineTrackerProgram(tuning))

# 设置延时
runtime.raspi_client.set_delay_profile(
    image_process_delay_s=0.03, command_tx_delay_s=0.01,
)

# 运行
for _ in range(4000):
    snapshot = runtime.step(1)
```

### 4.3 多种运行场景

```bash
# 基线：无延时，快速验证闭环
conda run -n simulation python app.py --no-gui --mode offline --duration 5

# 加延时，观察性能退化
conda run -n simulation python app.py --no-gui --mode offline --duration 10 --delay-ms 20

# GUI 实时观察
conda run -n simulation python app.py --mode realtime --duration 60 --delay-ms 10

# 长时间稳定性
conda run -n simulation python app.py --no-gui --mode offline --duration 120 --delay-ms 30

# 航点轨迹 + 自定义控制程序
conda run -n simulation python app.py --no-gui --waypoints "(100,0,5,2),(50,30,8,3),(80,-20,4,1.5)" \
    --control-program my_tracker:MyTracker --duration 30

# 随机运动 + 延时
conda run -n simulation python app.py --no-gui --target-type random_walk --delay-ms 15 --duration 20
```

## 5. 控制程序开发

### 5.1 ControlProgram 协议

```python
from runtime.types import Command

class ControlProgram(Protocol):
    def on_tick(self, obs: dict) -> list[Command]: ...
```

`obs` 包含 `timestamp, target, gimbal, camera, frame`，但具体可见字段受 `obs_mode` 影响：`debug` 全量、`research` 白名单、`realistic` 为受限测量值。返回 `list[Command]` 控制设备。

### 5.2 自定义模板

```python
from runtime.types import Command
from entities.camera.entity import detect_beacon_centroid

class MyTracker:
    def __init__(self, kp=0.1):
        self.kp = kp

    def on_tick(self, obs: dict) -> list[Command]:
        ts = float(obs["timestamp"])
        cmds = []

        # 确保 RATE_MODE
        if obs.get("gimbal", {}).get("mode") != "RATE_MODE":
            cmds.append(Command(target="gimbal", action="set_mode",
                                payload={"mode": "RATE_MODE"}, timestamp=ts))

        frame = obs.get("frame")
        if frame is None:
            return cmds

        det = detect_beacon_centroid(frame.image)
        if not det.found or det.cx is None:
            cmds.append(Command(target="gimbal", action="set_rate_target",
                                payload={"yaw_rate": 0.0, "pitch_rate": 0.0}, timestamp=ts))
            return cmds

        cx = float(frame.intrinsics["cx"])
        cy = float(frame.intrinsics["cy"])
        err_x = det.cx - cx
        err_y = cy - det.cy
        yaw_rate = max(-60.0, min(60.0, self.kp * err_x))
        pitch_rate = max(-60.0, min(60.0, self.kp * err_y))

        cmds.append(Command(target="gimbal", action="set_rate_target",
                            payload={"yaw_rate": yaw_rate, "pitch_rate": pitch_rate}, timestamp=ts))
        return cmds
```

更多扩展点参见 [Raspi 实体文档](entities/raspi/README.md#9-扩展点)。

### 5.3 从命令行加载

写好控制程序后，无需修改任何源码，直接通过 CLI 注入：

```bash
# 格式: module:Class（模块路径:类名）
conda run -n simulation python app.py --control-program my_tracker:MyTracker --duration 10

# 也可以在代码中直接传入
from simulation.bootstrap import build_runtime
from my_tracker import MyTracker

runtime = build_runtime(control_program=MyTracker())
```

## 6. 延时仿真

### 6.1 延时链路

Raspi 的延时管线模拟真实硬件延迟，目前支持两种缓冲策略：

- `latest`：默认策略，保持原有单槽忙/闲行为，忙时不接受新帧，空闲时抓最新帧
- `fifo`：有限队列策略，忙时缓存观测，队列满时丢弃最旧帧

两种策略共用同一状态机：

```
IDLE → READING → PROCESSING → SENDING → IDLE
```

延时越大，控制程序看到的观测越陈旧，跟踪性能越差；切换为 `fifo` 后，还可以显式观察有限队列带来的积压效应。

### 6.2 如何设置

```bash
# 命令行（统一延时）
conda run -n simulation python app.py --delay-ms 20

# 代码（精细控制）
runtime.raspi_client.set_delay_profile(
    image_read_delay_s=0.01,
    image_process_delay_s=0.02,
    command_tx_delay_s=0.005,
    jitter_std_s=0.001,
)
```

### 6.3 推荐调参顺序

1. **0 延时跑通闭环** — 确认目标能被持续跟踪
2. **固定目标速度，观察像素误差收敛**
3. **逐步叠加延时** — 先 5ms，再 10ms、20ms，观察收敛速度与稳定性变化
4. **替换成自己的检测与控制算法**

## 7. 可视化工具

### 7.1 目标轨迹预览（3D 动画）

```bash
conda run -n simulation python tools/target_preview.py                  # 交互式预览
conda run -n simulation python tools/target_preview.py --save-gif       # 结束时保存 GIF
conda run -n simulation python tools/target_preview.py --no-display     # 无头模式，自动保存 GIF
```

显示目标在世界坐标中的运动轨迹（XY 平面）、速度矢量、方位角/俯仰角和 3D 距离曲线。

### 7.2 3D 针孔相机投影可视化

```bash
conda run -n simulation python tools/camera_3d_viewer.py
```

交互式 PyQt5 窗口，左侧 3D 场景（光轴、FOV 锥体、目标点），右侧 2D 传感器平面投影。
可通过滑块调整焦距、目标距离和位置，实时观察投影变化。

### 7.3 数据录制

```bash
conda run -n simulation python -m tools.record_session --duration 10 --output output/data.csv
conda run -n simulation python -m tools.record_session --duration 20 --output output/data.csv \
    --control-program my_tracker:MyTracker --waypoints "(100,0,20,2),(50,30,10,1)"
```

运行仿真并导出每个 tick 的 WorldSnapshot 为 CSV（含 target/gimbal/camera/raspi 全部字段）。

### 7.4 离线回放

```bash
conda run -n simulation python -m tools.replay_session --input output/data.csv                                    # Noop（统计）
conda run -n simulation python -m tools.replay_session --input output/data.csv --control-program my_tracker:MyTracker  # 测试自定义控制程序
conda run -n simulation python -m tools.replay_session --input output/data.csv --control-program my_tracker:MyTracker --output output/replay.csv
```

用预录制 CSV 数据驱动控制程序，无需跑完整仿真。输出每 tick 的命令数统计和详细回放结果。

## 8. 实体文档索引

| 实体 | 文档 | 核心内容 |
|------|------|----------|
| Target | [entities/target/README.md](entities/target/README.md) | 5 种运动模式（含 waypoint）、参数表、运动学模型 |
| Gimbal | [entities/gimbal/README.md](entities/gimbal/README.md) | 串级 PID、状态机、参数调优、被控对象模型 |
| Camera | [entities/camera/README.md](entities/camera/README.md) | 针孔成像模型、变焦控制、质心检测 |
| Raspi | [entities/raspi/README.md](entities/raspi/README.md) | 延时管线、控制程序协议、基线跟踪模板 |
| Runtime | [runtime/README.md](runtime/README.md) | tick 顺序、命令调度、Client 绑定、Bootstrap |

## 9. 运行与测试

### 9.1 实体单元测试（224 个）

```bash
# 单独运行某个实体
conda run -n simulation python -m unittest entities.target.tests.test_target_entity -v    # 64 tests
conda run -n simulation python -m unittest entities.gimbal.tests.test_gimbal_entity -v    # 63 tests
conda run -n simulation python -m unittest entities.camera.tests.test_camera_entity -v    # 67 tests
conda run -n simulation python -m unittest entities.raspi.tests.test_raspi_entity -v      # 26 tests

# 全部实体测试
conda run -n simulation python -m unittest entities.target.tests.test_target_entity \
    entities.gimbal.tests.test_gimbal_entity \
    entities.camera.tests.test_camera_entity \
    entities.raspi.tests.test_raspi_entity -v
```

### 9.2 主线回归

```bash
conda run -n simulation python -m unittest discover -s tests -v
```

### 9.3 端到端闭环基线测试

```bash
conda run -n simulation python -m unittest tests.test_e2e_baseline -v
```

验证完整跟踪回路（Target → Gimbal → Camera → Raspi → Command → Gimbal）的稳态性能：
- 跟踪率 ≥ 90%
- 角度误差 RMS < 2.0°
- 角度误差峰值 < 5.0°
- 无发散（最后 10s 回归斜率 < 0.1 deg/s）
- 含 20ms 延时闭环测试

### 9.4 组装冒烟

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0
```

### 9.5 通过标准

- 所有测试通过（224 单元 + 16 集成 + 56 近真实/obs_filter/非理想/延时策略，含 8 个 e2e 基线测试）
- 端到端闭环基线测试通过（跟踪率、角度误差、无发散）
- 无 GUI 冒烟输出连续、无异常终止
- 关键字段（yaw/pitch/u/v/in_fov/backlog）正常刷新

## 10. 实时仪表盘

```bash
conda run -n simulation python app.py                                    # 默认 60 秒实时仿真
conda run -n simulation python app.py --mode realtime --duration 120     # 2 分钟
conda run -n simulation python app.py --delay-ms 20                      # 带 20ms 延时
```

界面布局：
- **左侧上方**：世界视图（轨迹、云台指向、FOV 扇形）
- **左侧下方**：时间轴曲线（像素误差、角速度参考、角度误差）
- **右侧上方**：双视角对比（相机原始帧 vs Raspi 延时观测帧）
- **右侧下方**：Tab 信息区（核心状态 / 诊断信息）
- **控制栏**：开始、暂停，重置，保存快照，链路延时设置

常见问题：
- 黑屏/无窗口：本机图形环境运行（远程用 `--no-gui`）
- 未 READY：脚本自动等待，超时检查配置
- 帧率偏低：确认 PyQt5 + pyqtgraph 已安装

## 11. 目录结构

```
zoom_pid/
├─ app.py                          # 主入口（透传到 simulation.cli）
├─ config.py                       # 统一配置（*_cfg dataclass 单例 + MOTION_MODE_PARAMS 模式注册表）
├─ baseline.py                     # 研究基线配置快照 + validate_baseline()
├─ simulation/                     # 应用编排层
│  ├─ bootstrap.py                 # build_runtime / start_stack / load_control_program
│  ├─ state_buffer.py              # UI 线程安全缓冲
│  ├─ worker.py                    # 仿真推进 QThread
│  ├─ headless.py                  # 无 GUI 运行入口 + 航点解析
│  ├─ cli.py                       # 参数解析 + 入口分发（支持 --control-program / --waypoints / --target-type）
│  └─ gui/
│     ├─ window.py                 # 仪表盘主窗口
│     ├─ runner.py                 # create_dashboard / run_gui
│     └─ panels/                   # 世界视图 / 相机视图组件
├─ runtime/
│  ├─ digital_twin_runtime.py      # 世界时钟 / 命令总线 / 调度器
│  ├─ types.py                     # Command / WorldSnapshot / POWER_* / wrap_pm180 / ALL_COMMANDS
│  └─ clients.py                   # Client 导出
├─ entities/
│  ├─ gimbal/                      # entity / model / control / client / tests（63 tests）
│  ├─ camera/                      # entity / model / control / client / tests（67 tests）
│  ├─ target/                      # entity / model / client / tests（64 tests, 3D 运动学, 含 waypoint 模式）
│  └─ raspi/                       # entity / model / pipeline / control_program / tracker / client / tests（26 tests）
├─ tests/                          # 主线回归测试（16 tests，含 8 个端到端闭环基线测试）
├─ tools/
│  ├─ target_preview.py            # 目标轨迹 2D 动画预览
│  ├─ camera_3d_viewer.py          # 3D 针孔相机投影可视化
│  ├─ record_session.py            # 仿真数据录制 → CSV
│  ├─ replay_session.py            # CSV 离线回放驱动控制程序
│  ├─ pid_tuner.py                 # PID 参数自动调优
│  ├─ run_baseline.py              # 基线实验运行工具（输出 JSON）
│  └─ config_editor.py             # 配置编辑器 GUI（实体导航式）
├─ docs/                           # 文档
│  ├─ 使用手册.md
│  └─ doc-structure.md             # 文档体系导航
├─ output/                         # 运行产物（gif/png/csv）
└─ workspace_meta/
   ├─ plan_logs/                   # 计划与迭代日志
   └─ agent_log.md                 # AI Agent 协作日志
```

## 12. 维护约定

- 新功能优先落在 `entities/*` 与 `runtime/*`
- `config.py` 仅保留主线配置，旧链路配置已清除
- 添加新运动模式：在 `motion_type` 的 `Literal` 中加模式名 → 在 `MOTION_MODE_PARAMS` 加字段映射 → 在 `TargetConfig` 加参数 → 在 `TargetKinematics3D` 实现。Config Editor 自动读取。
- 每次迭代必须更新 `workspace_meta/plan_logs/latest_plan.md` 与 `history.md`
- 修改实体代码时，同步更新对应实体的 README.md
