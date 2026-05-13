# 修改历史

---

## 004-20260513-235800 延时链路可视化 + Kp 最优值更新 + 时间窗口配置修复

**目的**：在控制栏中嵌入延时链路信息条，实时显示各级延时和观测延迟；Raspi 面板标题显示帧延时差；修正 Kp 为大范围扫参后的最优值 1.1；修复时间窗口硬编码为 15s 的问题。

**修改内容**：

1. **simulation/gui/window.py** — 控制栏新增 `lbl_delay_chain` 标签显示各级延时；`_render_tick()` 实时刷新观测延迟；Raspi 面板标题动态显示"滞后 xx.xms"；两个面板信息区显示帧时间戳；修复 `plot_window_s` 硬编码 15s 改为读取 `scene_cfg.plot_window_s`
2. **config.py** — `TrackerTuningConfig.yaw_rate_kp_dps_per_px` 从 0.29 更新为 1.1（大范围扫参 0.5~3.0 确认最优）

**验证**：冒烟测试通过。 TrackerTuning 配置集成、Kp 自动扫参工具与 GUI 时间轴优化

**目的**：将 TrackerTuning 参数集成到 config.py 使 config_editor 可调，新增 Kp 自动扫参工具确定最优增益，优化 GUI 时间轴为双子图双 Y 轴布局。

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

**修改内容**：

1. **entities/raspi/model.py** — `RaspiDelayModel` 内部从 `DelayPipeline` 队列改为 IDLE→READING→PROCESSING→SENDING→IDLE 单槽状态机：空闲时抓最新帧，忙时不接受新帧，不排队旧帧
2. **entities/raspi/entity.py** — `update()` 调用 `try_start()` + `tick()` 替代旧的 push/pop 队列操作；`pipeline_backlog_len` 语义变为 0（空闲）或 1（忙碌）
3. **entities/raspi/tests/test_raspi_entity.py** — 适配 backlog 0/1 语义，新增 `TestSingleSlotBusyIdle` 验证忙时不接受新帧、空闲时拿最新帧

**验证**：28 个 raspi 单元测试通过，8 个集成测试通过，端到端离线运行正常，backlog 始终为 0 或 1。

---

## 001-20260512-212558 代码审查修复与平台完善

**目的**：审查代码 bug，修复延时配置缺陷，暴露目标速度信息，完善平台以支撑后续追踪/预测算法测试。

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

**包含**：四实体闭环（Target/Gimbal/Camera/Raspi）、DigitalTwinRuntime 调度器、DelayPipeline 延时链路、5 种目标运动模式、BaselineTrackerProgram、GUI 仪表盘、PID 调参工具、录制/回放工具、226 个测试。
