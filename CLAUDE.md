# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此仓库中工作时提供指引。

---

## 1. 项目概述

云台数字孪生仿真系统 — 基于 Python 的云台-相机-目标跟踪闭环仿真，含树莓派控制器。四个实体由 `DigitalTwinRuntime` 按固定 tick 顺序调度：Target → Gimbal → Camera → Raspi → 发布快照。

## 2. 环境与运行

### 2.1 环境准备

- Python 虚拟环境：conda `simulation`
- 依赖：numpy、PyQt5、pyqtgraph（无 requirements.txt，需手动安装）

```bash
conda activate simulation
```

**环境强制约束**：所有 Python 命令必须通过 `conda run -n simulation` 前缀执行，确保使用正确的虚拟环境。禁止直接调用 `python`，因为 shell 环境无法保持 `conda activate` 状态。

```bash
# 正确
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0
conda run -n simulation python -m unittest discover -s tests -v

# 错误（可能用到系统 Python）
python app.py --no-gui --mode offline --duration 1.0
```

### 2.2 运行命令

所有命令在 `systemSimulation/` 目录下执行，使用 `conda run -n simulation`：

```bash
# 冒烟测试（无 GUI，快速验证闭环）
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0

# GUI 实时仿真
conda run -n simulation python app.py --mode realtime --duration 60

# 带延时仿真
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --delay-ms 20

# 自定义控制程序
conda run -n simulation python app.py --no-gui --control-program module:ClassName --duration 10

# 航点轨迹
conda run -n simulation python app.py --no-gui --waypoints "(100,0,2),(80,30,1.5),(60,0,0)" --duration 20

# 切换目标运动类型
conda run -n simulation python app.py --no-gui --target-type constant_velocity --duration 5
```

### 2.3 测试命令

```bash
# 全部测试
conda run -n simulation python -m unittest discover -s tests -v

# 单实体测试
conda run -n simulation python -m unittest entities.target.tests.test_target_entity -v    # 64 tests
conda run -n simulation python -m unittest entities.gimbal.tests.test_gimbal_entity -v    # 63 tests
conda run -n simulation python -m unittest entities.camera.tests.test_camera_entity -v    # 67 tests
conda run -n simulation python -m unittest entities.raspi.tests.test_raspi_entity -v      # 26 tests

# 单测试文件
conda run -n simulation python -m unittest tests.test_gimbal_2axis_core -v
```

**通过标准**：240 个测试（224 单元 + 16 集成，含 8 个 e2e 基线测试）全部通过，无异常终止，关键字段（yaw/pitch/u/v/in_fov）正常刷新。

## 3. 系统架构

### 3.1 数据流（单 tick）

```
_apply_due_commands() → Target.update() → Gimbal.update() → Camera.update(target, gimbal) → Raspi.update(world_obs) → WorldSnapshot
                                                                                            ↑                              │
                                                                                            └──── Command (通过回调注入) ──┘
```

Raspi 命令经单槽忙/闲延时管线（IDLE → READING → PROCESSING → SENDING → IDLE）延迟后，在下一个 tick 的 `_apply_due_commands()` 中生效。命令仲裁采用 latest-wins；未 READY 设备的命令被拒绝。

### 3.2 关键文件

| 路径 | 职责 |
|------|------|
| `app.py` | 主入口，透传到 `simulation.cli` |
| `config.py` | 全部 dataclass 配置 + `MOTION_MODE_PARAMS` 模式注册表 |
| `runtime/digital_twin_runtime.py` | 世界时钟、命令总线、tick 调度器 |
| `runtime/types.py` | `Command`、`CommandResult`、`WorldSnapshot`、`FramePacket`、`Detection`、`ALL_COMMANDS` |
| `simulation/bootstrap.py` | `build_runtime()`、`start_stack()`、`load_control_program_from_path()` |
| `simulation/cli.py` | 参数解析 + 入口分发 |
| `simulation/headless.py` | 无 GUI 运行入口，含航点解析 |

### 3.3 实体结构

`entities/<name>/` 下各实体遵循统一结构：

| 文件 | 职责 |
|------|------|
| `entity.py` | 状态机 + update 循环 |
| `model.py` | 物理/运动学模型 |
| `control.py` | 控制器（PID 等） |
| `client.py` | 面向 Runtime 的 API |
| `tests/` | 单元测试 |

Raspi 实体额外包含 `delay_pipeline.py`（延时管线）和 `tracker_program.py`（基线 `ControlProgram` 实现）。

### 3.4 ControlProgram 协议

```python
class ControlProgram(Protocol):
    def on_tick(self, obs: dict) -> list[Command]: ...
```

`obs` 包含 `timestamp, target, gimbal, camera, frame`。通过 `--control-program module:Class` 加载自定义控制程序。

## 4. 开发约定

### 4.1 代码规范

- 配置集中在 `config.py`，以模块级单例 dataclass 实例提供（如 `camera_cfg`、`gimbal_cfg`）。不要新建配置文件。
- 项目语言为中文（注释、文档、UI 标签），保持已有中文内容不变。
- 添加新目标运动类型：在 `TargetConfig.motion_type` 的 `Literal` 中加模式名 → 在 `MOTION_MODE_PARAMS` 加字段映射 → 在 `TargetConfig` 加参数 → 在 `TargetKinematics2D` 实现逻辑。Config Editor 自动读取。
- 修改实体代码时，同步更新对应 `entities/<name>/README.md`。
- **每次修改代码后，必须在 `systemSimulation/CHANGELOG.md` 中追加一条记录**，格式为 `序号-年月日-时分秒`，注明修改目的、修改内容和验证结果。无论改动大小（包括配置调整、参数调优），都必须追加。遗漏 CHANGELOG 是一个需要纠正的问题。**每条记录必须标明修改者身份**（如 `修改者：Claude Code`、`修改者：Codex`、`修改者：手工`），放在条目开头或验证之前，方便追溯是谁做的修改。
- **CHANGELOG 时间戳必须使用真实时间**：写入 CHANGELOG 条目前，**必须先执行 `date +%Y%m%d-%H%M%S` 获取当前真实时间**，将返回值直接填入条目标题。**禁止编造或猜测时间**。如果无法获取时间，使用 `00000000-000000` 作为占位。序号从上一条目的序号递增 1。
- **ATP 开发进度追踪**：开发计划在 `docs/低空场景无线光通信ATP开发文档.md`。每个阶段有状态标记（🔴 未开始 / 🟡 进行中 / 🟢 已完成）和闸门 checkbox。完成某个阶段的所有闸门条件后，将 checkbox 勾选为 `[x]`，将阶段标题的状态改为 `🟢 已完成`，将总路线表的状态同步更新，并将"当前活跃阶段"指向下一个阶段。**每次开始工作时先读这份文档确认当前活跃阶段。**
- **阶段执行前置闸门**：当准备进入某个开发阶段的实际执行时，**必须先单独产出该阶段的详细开发计划文档，再等待用户确认**。这份文档至少要写清：本阶段目标、任务拆分、涉及文件/模块、依赖关系、风险点、验收标准和计划验证项。**在用户明确确认这份阶段计划之前，禁止开始该阶段的代码修改、配置修改、测试补写、参数调整和结构重构。** 如果用户只要求“先看计划”或“先细化阶段任务”，则只能继续完善文档，不能直接进入实施。

### 4.2 测试规范

- 修改代码后**必须**测试验证，不能仅对修改的单个文件做单元测试。
- 必须运行端到端验证，确保整体闭环正常：

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0
```

- 功能性变更需同时跑全量测试：`conda run -n simulation python -m unittest discover -s tests -v`

### 4.3 多 Agent 协作规范

- 任务拆分应尽量**解耦、彼此独立**，避免 Agent 间存在隐式依赖导致冲突或死锁。
- 每个 Agent 的任务应有明确的输入和预期输出，不依赖其他 Agent 的中间状态。
- 多 Agent 并行修改时，避免操作同一文件；如有必要，需在任务描述中明确协调机制。
