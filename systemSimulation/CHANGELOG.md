# 修改历史

---

## 011-20260514-211752 ATP 开发进度追踪机制

**目的**：为 ATP 开发文档增加结构化的阶段状态标记和闸门 checkbox，使模型能直接读取并判断当前开发进度。

**修改者**：Claude Code

**修改内容**：

1. **docs/低空场景无线光通信ATP开发文档.md** — 总路线表增加"状态"列（🔴 未开始 / 🟡 进行中 / 🟢 已完成）；每个阶段标题增加状态标签；闸门条件从编号列表改为 checkbox 格式；增加"当前活跃阶段"指针和状态说明
2. **CLAUDE.md** — 新增 ATP 开发进度追踪规则：每次开始工作时先读开发文档确认当前活跃阶段，完成闸门后更新状态
3. **AGENTS.md** — 同步更新相同规则

**验证**：仅文档修改，无需运行测试。

---

## 010-20260514-205300 ATP开发文档标准化收紧

**目的**：检查 ATP 开发文档是否达到可执行的计划标准，并补齐阶段闸门、范围边界和结构断层。

**修改者**：Codex

**修改内容**：

1. **docs/低空场景无线光通信ATP开发文档.md** — 为阶段 0 到阶段 5 补充“阶段闸门”，明确每阶段进入下一阶段前必须满足的条件
2. **docs/低空场景无线光通信ATP开发文档.md** — 修正后半段缺失“阶段 5”标题的问题，补齐平台固化阶段的结构
3. **docs/低空场景无线光通信ATP开发文档.md** — 新增“本轮边界与后续衔接”，明确本轮先聚焦 ATP，本轮完成后再单独立项做 ATP+通信联合仿真

**验证**：

1. 开发文档结构连续，无阶段断层
2. 每阶段均包含明确的阶段闸门
3. 已明确本轮范围边界与下一轮通信链路衔接条件

---

## 009-20260514-204511 CHANGELOG 规则更新：增加修改者身份标识

**目的**：在 AGENTS.md 和 CLAUDE.md 的 CHANGELOG 维护规则中增加"必须标明修改者身份"的要求，方便追溯每次修改是由谁（Claude Code / Codex / 手工）完成的。

**修改者**：Claude Code

**修改内容**：

1. **AGENTS.md** — CHANGELOG 规则新增：每条记录必须标明修改者身份
2. **CLAUDE.md** — 同步更新相同规则

**验证**：仅文档规则修改，无需运行测试。

---

## 008-20260514-204057 ATP 开发文档审阅与修正

**目的**：对 Codex 制定的 ATP 开发文档进行独立技术审阅，修正与代码现状不符的描述，补充遗漏的技术风险和依赖关系。

**修改者**：Claude Code

**修改内容**：

1. **docs/低空场景无线光通信ATP开发文档.md** — 新增 §1.1 技术现状核实表（9 项，附代码依据）；修正 §3 现状描述（云台已支持双轴、参数已集中到 config.py、延时已用单槽模型）；重写阶段 2 任务（坐标系定义优先、3D 升级影响面说明、预计破坏全部 224 个测试）；拆分阶段 3 为轮 A/B 交付；增加阶段 4 前置条件（轮 A 必须先完成）和 ATP 状态机风险；新增 §9 关键技术依赖关系图；新增 §11 审阅修改记录
2. **docs/doc-structure.md** — 已由 Codex 更新

**验证**：仅文档修改，无需运行测试。

---

## 007-20260514-202900 ATP开发文档补充

**目的**：将前面的高层路线图落成一份可以直接用于后续排期、拆任务和阶段验收的开发文档，明确开发顺序、阶段任务、阶段产出和验收标准。

**修改者**：Codex

**修改内容**：

1. **docs/低空场景无线光通信ATP开发文档.md** — 新增 ATP 开发文档，面向低空场景无线光通信任务，按阶段给出开发目标、具体任务、阶段产出、完成标准、阶段风险和验收口径
2. **docs/doc-structure.md** — 新增该开发文档的导航入口，方便后续从 docs 体系中直接查找

**验证**：

1. 开发文档已写入 docs 目录
2. 文档导航已更新，能在文档体系中找到该文档

---

## 006-20260514-200958 深度技术审阅与代码修复

**目的**：对 Codex 审阅进行逐节评估并补充遗漏的技术问题，修复发现的 4 个代码缺陷。

**修改者**：Claude Code

**修改内容**：

1. **docs/仿真系统深度技术审阅.md** — 新增独立深度审阅文档：对 Codex 审阅逐节评估（指出 7 处遗漏），独立审阅代码工程、模型真实性、系统配合、科研价值、物理世界对照，给出 10 条优先级排序的建议
2. **entities/raspi/tracker_program.py** — 修复 Kp 双重默认值 bug：`TrackerTuning.yaw_rate_kp_dps_per_px` 从 0.08 修正为 1.1（与 config.py 中 TrackerTuningConfig 一致）
3. **entities/raspi/entity.py** — 修正 jitter 分布偏差：`max(0, gauss)` 改为 `abs(gauss)`，消除正偏
4. **config.py** — 参数化硬编码值：GimbalConfig 增加 `boot_delay_s=1.5`，CameraConfig 增加 `boot_delay_s=0.5`、`beacon_sigma_px=3.2`、`detection_threshold=180`
5. **entities/gimbal/entity.py** — boot_delay 从 config 读取
6. **entities/camera/entity.py** — boot_delay 和 detection_threshold 从 config 读取
7. **entities/camera/model.py** — beacon sigma 从 config 读取
8. **entities/raspi/__init__.py** — 移除无引用的 DelayPipeline 导出
9. **docs/doc-structure.md** — 新增深度技术审阅导航入口

**验证**：224 单元 + 8 集成 = 232 测试全部通过，冒烟测试通过。

---

## 005-20260514-195312 项目系统审阅文档补充

**目的**：对当前仿真系统做一次面向代码、模型、科研价值、物理真实性和后续研究方向的系统审阅，并将结果沉淀到 docs 文档中，方便后续统一认识和规划。

**修改者**：Codex

**修改内容**：

1. **docs/仿真系统项目审阅与优化建议.md** — 新增系统审阅文档，按代码工程、系统原理、目标/云台/相机/树莓派模型、方法论、科研意义、真实性、风险点、优化优先级、研究题目和后续路线进行分点审阅
2. **docs/doc-structure.md** — 新增该审阅文档的导航入口，方便在现有文档体系中查找

**验证**：

1. `conda run -n simulation python app.py --no-gui --mode offline --duration 1.0` 通过
2. `conda run -n simulation python -m unittest discover -v` 通过（224 个实体/模块级测试）
3. `conda run -n simulation python -m unittest discover -s tests -v` 通过（8 个集成级测试）

---

## 004-20260513-235800 延时链路可视化 + Kp 最优值更新 + 时间窗口配置修复

**目的**：在控制栏中嵌入延时链路信息条，实时显示各级延时和观测延迟；Raspi 面板标题显示帧延时差；修正 Kp 为大范围扫参后的最优值 1.1；修复时间窗口硬编码为 15s 的问题。

**修改者**：Claude Code

**修改内容**：

1. **simulation/gui/window.py** — 控制栏新增 `lbl_delay_chain` 标签显示各级延时；`_render_tick()` 实时刷新观测延迟；Raspi 面板标题动态显示"滞后 xx.xms"；两个面板信息区显示帧时间戳；修复 `plot_window_s` 硬编码 15s 改为读取 `scene_cfg.plot_window_s`
2. **config.py** — `TrackerTuningConfig.yaw_rate_kp_dps_per_px` 从 0.29 更新为 1.1（大范围扫参 0.5~3.0 确认最优）

**验证**：冒烟测试通过。

---

## 003-20260513 TrackerTuning 配置集成、Kp 自动扫参工具与 GUI 时间轴优化

**目的**：将 TrackerTuning 参数集成到 config.py 使 config_editor 可调，新增 Kp 自动扫参工具确定最优增益，优化 GUI 时间轴为双子图双 Y 轴布局。

**修改者**：Claude Code

**修改内容**：

1. **config.py** — 新增 `TrackerTuningConfig` dataclass 及 `tracker_tuning_cfg` 单例，包含 yaw_rate_kp、max_yaw_rate、deadband、变焦控制等全部参数；Kp 经扫参调优至 1.1（原 0.08）
2. **entities/raspi/tracker_program.py** — `BaselineTrackerProgram.__init__()` 默认从 `tracker_tuning_cfg` 读取参数，无需手动传参
3. **tools/config_editor.py** — 将 `tracker_tuning_cfg` 加入 Raspi 参数组，可在 GUI 中直接编辑跟踪参数
4. **tools/tune_tracker_kp.py** — 新建 Kp 自动扫参工具，支持 `--kp-min/max/step/duration` 参数，输出排序对比表和最优值
5. **simulation/gui/window.py** — 时间轴从单 PlotWidget 改为 `GraphicsLayoutWidget` 双子图布局：上图双 Y 轴（像素误差 + 角度误差），下图角速度，共享 X 轴

**验证**：Kp 扫参 0.5~3.0 确认最优 Kp=1.1（角度 RMS=0.80°），Kp>1.7 后误差显著增大。

---

## 002-20260512-224700 树莓派延迟模型重构：队列→单槽忙/闲状态机

**目的**：修复树莓派未因处理而被阻塞的 bug。原实现每个 tick（5ms）都把观测推入 3 阶段 FIFO 队列管线，导致积压无限增长、处理旧帧、控制频率虚高到 200Hz，不符合真实硬件行为。

**修改者**：Claude Code

**修改内容**：

1. **entities/raspi/model.py** — `RaspiDelayModel` 内部从 `DelayPipeline` 队列改为 IDLE→READING→PROCESSING→SENDING→IDLE 单槽状态机：空闲时抓最新帧，忙时不接受新帧，不排队旧帧
2. **entities/raspi/entity.py** — `update()` 调用 `try_start()` + `tick()` 替代旧的 push/pop 队列操作；`pipeline_backlog_len` 语义变为 0（空闲）或 1（忙碌）
3. **entities/raspi/tests/test_raspi_entity.py** — 适配 backlog 0/1 语义，新增 `TestSingleSlotBusyIdle` 验证忙时不接受新帧、空闲时拿最新帧

**验证**：28 个 raspi 单元测试通过，8 个集成测试通过，端到端离线运行正常，backlog 始终为 0 或 1。

---

## 001-20260512-212558 代码审查修复与平台完善

**目的**：审查代码 bug，修复延时配置缺陷，暴露目标速度信息，完善平台以支撑后续追踪/预测算法测试。

**修改者**：Claude Code

**修改内容**：

1. **entities/target/entity.py** — `TargetState` 增加 `vx_mps`/`vy_mps` 字段，`update()` 和 `get_state()` 填充速度；初始 bearing/distance 改为计算值（原硬编码为 0）
2. **entities/target/model.py** — `np.random.seed()` 改为 `np.random.default_rng()`，消除全局随机状态污染；修正 `__init__` 类型标注
3. **simulation/bootstrap.py** — `apply_delay_profile()` 延时分配逻辑重写：`--delay-ms` 作为总预算按硬件比例分配（25%/50%/25%），修复原先每阶段都分配全额导致实际延迟 3.25 倍的 bug；callable 检测逻辑拆为清晰的 if-elif-else
4. **simulation/headless.py** — 合并重复的 `from config import target_cfg`
5. **config.py** — `RaspiDelayConfig` 默认值调整为真实硬件典型值（image_read 5ms, process 15ms, state_read 3ms, cmd_tx 3ms, jitter 1ms）；`pixel_noise_std` 从 0.5 调整为 2.0
6. **entities/raspi/tests/test_raspi_entity.py** — 更新 `test_default_delay_profile` 断言匹配新默认值

**验证**：228 个测试全部通过（220 单元 + 8 集成），端到端冒烟正常。

---

## 000-20260511-235200 初始提交

**目的**：云台数字孪生仿真系统 v1.0 初始版本。

**修改者**：手工

**包含**：四实体闭环（Target/Gimbal/Camera/Raspi）、DigitalTwinRuntime 调度器、DelayPipeline 延时链路、5 种目标运动模式、BaselineTrackerProgram、GUI 仪表盘、PID 调参工具、录制/回放工具、226 个测试。
