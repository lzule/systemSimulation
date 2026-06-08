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

**通过标准**：运行 `tests/` 下全量 unittest 并全部通过，无异常终止，关键字段（yaw/pitch/u/v/in_fov）正常刷新。

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

### 4.1 TODO 驱动开发

- 项目使用 `docs/TODO.md` 作为任务总索引，按类别分区，每个任务可引用 `docs/todo/` 下的详细步骤文件。
- **任务状态必须与代码状态实时同步**，文档滞后视为未完成。
- 新增功能 → 新增对应 TODO 条目或子文件；任务状态变更（开始、完成、阻塞）→ 立即更新 TODO.md。
- **将任务标记为 `[x]` 前必须逐项完成以下检查**：
  - [ ] 功能代码已实现
  - [ ] 对应测试已编写并通过
  - [ ] `docs/TODO.md` 已更新（状态标记、进度说明）
  - [ ] 相关实体 README 已同步更新
  - [ ] `CHANGELOG.md` 已追加记录
- **没有测试就将任务标记为 `[x]` 属于严重违规。**

### 4.2 代码规范

- 配置集中在 `config.py`，以模块级单例 dataclass 实例提供（如 `camera_cfg`、`gimbal_cfg`）。不要新建配置文件。
- 项目语言为中文（注释、文档、UI 标签），保持已有中文内容不变。
- 添加新目标运动类型：在 `TargetConfig.motion_type` 的 `Literal` 中加模式名 → 在 `MOTION_MODE_PARAMS` 加字段映射 → 在 `TargetConfig` 加参数 → 在 `TargetKinematics3D` 实现逻辑。
- 修改实体代码时，同步更新对应 `entities/<name>/README.md`。
- 变量和函数命名必须能表达意图，禁止使用无意义的缩写（如 `a`、`tmp2`）。
- 不留重复代码。如果同一段逻辑出现两次以上，提取为公共函数。
- 不写代码本身已经能看出来的注释。注释用于补充代码无法表达的内容：业务约束、非显而易见的边界条件、框架的坑。
- 不保留被注释掉的代码。不需要的代码直接删除，需要时通过 git 历史找回。
- 不保留未使用的导入和变量。
- 错误处理只在系统边界做（用户输入、外部 API），内部函数间的调用不需要防御性 try-catch。

### 4.3 测试规范

- 修改代码后**必须**测试验证，不能仅对修改的单个文件做单元测试。
- 必须运行端到端验证，确保整体闭环正常：

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0
```

- 功能性变更需同时跑全量测试：`conda run -n simulation python -m unittest discover -s tests -v`
- **新增功能 → 同步编写测试**，测试文件保留在项目中，方便后续开发时回归验证。
- 修改已有功能 → 更新相关测试；删除功能 → 一并删除对应测试文件。
- 测试运行时机：开发中不强制每步跑全量，但标记 TODO `[x]` 前、涉及配置或架构变更时必须跑。
- 测试文件命名与被测模块一一对应（`entities/gimbal/model.py` → `entities/gimbal/tests/test_gimbal_entity.py`）。

#### 测试诚信（红线）

测试的本质是验证功能代码的正确性。为了让测试通过而篡改测试代码属于严重违规，等同于没有测试。以下行为**严格禁止**：

- **篡改测试断言**：为了让测试通过而放宽断言（如将精确匹配改为模糊匹配、删除关键的 `assert` 语句）
- **硬编码预期结果**：在测试中写死返回值，绕过对真实逻辑的验证
- **选择性跳过测试**：使用 `@skip` 等方式跳过失败的测试，而不是修复被测代码本身
- **修改测试数据以适配 bug**：当功能代码有 bug 导致测试失败时，正确做法是修复功能代码，而非修改测试数据来绕过 bug

**正确做法**：测试失败时，首先检查功能代码是否正确，修复功能代码使测试通过。只有在需求确实变更或测试本身写错的情况下，才允许修改测试。

### 4.4 CHANGELOG 规范

- **每次修改代码后，必须在 `systemSimulation/CHANGELOG.md` 中追加一条记录**，格式为 `序号-年月日-时分秒`，注明修改目的、修改内容和验证结果。无论改动大小（包括配置调整、参数调优），都必须追加。遗漏 CHANGELOG 是一个需要纠正的问题。
- **每条记录必须标明修改者身份**（如 `修改者：Claude Code`、`修改者：Codex`、`修改者：手工`），放在条目开头或验证之前，方便追溯是谁做的修改。
- **CHANGELOG 时间戳必须使用真实时间**：写入 CHANGELOG 条目前，**必须先执行当前 shell 可用的真实时间命令获取时间戳**。当前仓库默认环境为 PowerShell，统一使用 `Get-Date -Format yyyyMMdd-HHmmss`。将返回值直接填入条目标题。**禁止编造或猜测时间**。如果无法获取时间，使用 `00000000-000000` 作为占位。序号从上一条目的序号递增 1。

### 4.5 阶段开发与进度追踪

- **ATP 开发进度追踪**：开发计划在 `docs/低空场景无线光通信ATP开发文档.md`。每个阶段有状态标记（🔴 未开始 / 🟡 进行中 / 🟢 已完成）和闸门 checkbox。完成某个阶段的所有闸门条件后，将 checkbox 勾选为 `[x]`，将阶段标题的状态改为 `🟢 已完成`，将总路线表的状态同步更新，并将"当前活跃阶段"指向下一个阶段。**每次开始工作时先读这份文档确认当前活跃阶段。**
- **阶段执行前置闸门**：当准备进入某个开发阶段的实际执行时，**必须先单独产出该阶段的详细开发计划文档，再等待用户确认**。这份文档至少要写清：本阶段目标、任务拆分、涉及文件/模块、依赖关系、风险点、验收标准和计划验证项。**在用户明确确认这份阶段计划之前，禁止开始该阶段的代码修改、配置修改、测试补写、参数调整和结构重构。** 如果用户只要求"先看计划"或"先细化阶段任务"，则只能继续完善文档，不能直接进入实施。

### 4.6 多 Agent 协作规范

- 任务拆分应尽量**解耦、彼此独立**，避免 Agent 间存在隐式依赖导致冲突或死锁。
- 每个 Agent 的任务应有明确的输入和预期输出，不依赖其他 Agent 的中间状态。
- 多 Agent 并行修改时，避免操作同一文件；如有必要，需在任务描述中明确协调机制。
- 优先按**垂直功能切片**拆分（功能代码 + 对应测试为一组），而非按技术层拆分。
- 合并时按顺序逐个处理，遇到冲突立即解决，不要堆积。

## 5. 常用命令与授权约定

本项目允许代理在以下边界内直接执行常规开发、验证和清理动作。这里的"允许"是项目约定层面的允许；若运行环境本身仍要求审批，以运行环境规则为准。

### 5.1 Python 与测试命令约定

1. 所有 Python 命令必须在 `systemSimulation/` 目录下执行。
2. 所有 Python 命令必须统一使用：
   `conda run -n simulation python ...`
3. 不要直接调用系统 `python`。
4. 允许执行以下类型命令：
   - 运行主程序冒烟验证
   - 运行 unittest
   - 运行 `tools/` 下的测试、benchmark、汇总脚本
   - 使用 `python -c` 做小规模导入检查、只读检查、快速验证
5. 若命令仅用于验证、导入检查、结果汇总、冒烟测试，可直接执行，不必先询问用户。
6. 若命令会修改项目文件、生成大量结果、覆盖已有输出，必须先确认是否会影响现有结果目录；如有风险，优先写入临时目录或新目录。

### 5.2 工作目录约定

1. 默认工作目录为：
   `k:/ustc-lizl/Liuwj2Lizl/ALL-Auto/8-simulation/System-APT/systemSimulation`
2. 允许代理在以下目录内执行只读与常规验证命令：
   - `systemSimulation/`
   - `systemSimulation/tests/`
   - `systemSimulation/tools/`
   - `systemSimulation/docs/`
3. 若命令需要跨出上述目录，先确认是否确有必要。

### 5.3 临时文件与清理约定

1. 允许代理删除自己为验证而创建的临时文件。
2. 允许删除的对象仅限以下模式：
   - `_smoke_*.py`
   - `_test_*.py`
   - `tmp_*.py`
   - `temp_*.py`
   - 明确标记为临时用途的输出文件
3. 删除动作必须满足：
   - 路径位于 `systemSimulation/` 或其明确子目录内
   - 文件名符合临时文件模式
   - 不是用户正式源码、正式文档、正式测试
4. 删除文件时优先使用 PowerShell 原生命令：
   `Remove-Item -LiteralPath ...`
5. 禁止使用宽泛删除：
   - 禁止删除整个源码目录
   - 禁止删除不带明确模式约束的批量文件
   - 禁止对未知路径做递归删除

### 5.4 编码与输出约定

1. 运行 Python 命令时，如涉及中文输出，优先显式设置 UTF-8。
2. PowerShell 下如需避免编码问题，优先使用环境变量方式或 Python 内部显式设置。
3. 允许执行导入验证命令，例如：
   - 检查模块能否导入
   - 检查场景表、算法注册表、汇总函数是否可访问

### 5.5 允许直接执行的常见操作

1. 冒烟测试：
   `conda run -n simulation python app.py --no-gui --mode offline --duration 1.0`
2. 全量测试：
   `conda run -n simulation python -m unittest discover -s tests -v`
3. 单文件测试：
   `conda run -n simulation python -m unittest tests.test_xxx -v`
4. 工具脚本验证：
   `conda run -n simulation python tools/xxx.py`
5. 小型导入检查：
   `conda run -n simulation python -c "..."`
6. 删除临时脚本：
   `Remove-Item -LiteralPath "..."`

### 5.6 仍需谨慎或单独确认的动作

以下动作即使在本项目内，也不要默认直接执行：

1. 删除非临时文件
2. 大范围递归删除
3. 覆盖已有 benchmark 结果目录
4. 改动环境本身
5. 安装依赖、联网下载、修改 conda 环境
6. 任何可能影响用户手工产物的批量清理
