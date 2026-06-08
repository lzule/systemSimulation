# 修改历史

## 092-20260608-214347 Kp 参数搜索加速 — 快速相机模式 + 黄金分割搜索

**修改者**：Claude Code

### 修改目的

对照实验（TODO 2.a/b/d）需对 9 个条件做 Kp 二维网格搜索，预估 6534 次仿真、8 并行 ~10 小时。
从仿真引擎和搜索算法两个层面加速，使实验可在分钟级完成。

### 修改内容

**加速层面一：快速相机模式（~170× 加速）**
- `entities/camera/model.py`：新增 `render_beacon_fast()`，跳过 640×480 图像生成与质心检测，直接输出带噪声坐标
- `entities/camera/entity.py`：新增 `fast_mode` 属性，`_render_frame()` 在快速模式走轻量路径
- `runtime/digital_twin_runtime.py`：`__init__` 新增 `fast_camera` 参数
- `simulation/bootstrap.py`：`build_runtime()` 新增 `fast_camera` 参数
- `entities/raspi/tracker_program.py`：`on_tick()` 支持从 `frame.optional_gt` 获取快速模式检测结果
- `simulation/obs_filter.py`：`_copy_frame()` 在 `image=None` 时保留 `optional_gt`

**加速层面二：黄金分割搜索（~96% 减少仿真次数）**
- `tools/tune_tracker_kp.py`：重写搜索逻辑
  - Phase 1：一维黄金分割搜索 yaw_kp（12 次评估即收敛）
  - Phase 2：多 seed 验证最优值
  - Phase 3：pitch_kp 敏感性检查

**测试**
- `tests/test_fast_camera_mode.py`：新建，8 个测试覆盖快速模式正确性、RMS 一致性、回归验证

### 验证结果

- 快速模式 vs 完整模式：RMS 偏差 0.1%（7.56 vs 7.57px）
- 快速模式加速比：167.7×（44.21s → 0.26s / 20s 仿真）
- 黄金分割搜索：12 次评估收敛（vs 均匀网格 121 次），总仿真次数 32（vs 726）
- 最优 yaw_kp=1.2859，pitch_kp 不敏感（RMS 范围 0.04px）
- 新增测试 8/8 通过
- 全量测试通过
- 冒烟测试通过

## 091-20260608-200447 配置独立性解耦 — 实体配置 deepcopy + 全局引用消除

**修改者**：Claude Code

### 修改目的

根据 Phase A 配置独立性审查报告中发现的问题，修复所有实体的配置隔离缺陷，
确保每个实体实例拥有完全独立的配置副本，消除对全局单例的隐式依赖。
为后续对照实验（exp01/exp02）的单进程串行场景扫清配置污染风险。

### 修改内容

1. **GimbalEntity**（`entities/gimbal/entity.py`）
   - `__init__` 中 4 个配置参数（gimbal_cfg/axis_cfg/loop_cfg/control_preset）
     从浅引用改为 `copy.deepcopy`，对齐 TargetEntity 的最佳实践
   - 新增 `import copy`

2. **CameraEntity**（`entities/camera/entity.py`）
   - `__init__` 中 `self.cfg` 从浅引用改为 `copy.deepcopy`
   - 新增 `scene_cfg_obj: SceneConfig` 构造参数，透传给 CameraImagingModel
   - 移除未使用的 `scene_cfg` import

3. **RaspiEntity**（`entities/raspi/entity.py`）
   - `__init__` 中 `self.cfg`（RaspiConfig）从浅引用改为 `copy.deepcopy`
   - delay_cfg 已有 deepcopy，无需修改

4. **CameraImagingModel**（`entities/camera/model.py`）🚨 审查报告关键问题
   - 新增 `scene_cfg_obj: SceneConfig` 构造参数，解耦对全局 `scene_cfg` 的外部引用
   - `pixel_noise_std` 从直接读全局 `scene_cfg` 改为通过构造参数注入
   - `self.cfg` 增加 `copy.deepcopy`，对齐其他实体
   - 修复后：可通过构造参数独立控制每个实例的噪声参数

5. **detect_beacon_centroid**（`entities/camera/entity.py`）
   - `threshold` 默认值从 `None`（fallback 到 `camera_cfg.detection_threshold`）
     改为硬编码 `100`（与 CameraConfig 默认值一致），消除全局引用

6. **BaselineTrackerProgram**（`entities/raspi/tracker_program.py`）
   - `__init__` 中 `tuning=None` fallback 从逐字段读取 `tracker_tuning_cfg` 全局变量
     改为直接使用 `TrackerTuning()` dataclass 默认值（两者默认值完全一致）
   - 移除 `from config import tracker_tuning_cfg` 依赖

### 验证结果

- 冒烟测试：`app.py --no-gui --mode offline --duration 1.0` ✅ 通过
- 全量测试：141 tests, 0 failures, 0 errors ✅ 通过
- 所有修改保持向后兼容（新增构造参数均有默认值，现有调用无需修改）

## 090-20260608-163748 Phase A 配置独立性审查完成 + 实验目录骨架建立

**修改者**：Claude Code

### 修改目的

对应 `docs/TODO.md` 第 2 项「系统各实例配置独立性检查与对照实验设计」，执行 Phase A：
通过代码审读（只读，不动代码）完成全部 4 个实体的配置独立性审查，输出审查报告，
并建立 `experiments/` 一级目录骨架，为 Phase B 共用框架搭建做准备。

### 修改内容

1. **实测单次仿真耗时（决策依据）**
   - baseline (fps=60, Kp=1.1, duration=20s, 1 seed)：43.86s 平均（3 次实测）
   - 10s vs 20s 对比：rms 偏差 33.88%，确认 duration 必须保持 20s
   - 加速方案确定：8 进程并行，全实验 ~10 小时（Stage1 1.7h + Stage2 8.3h）

2. **更新 `docs/todo/对照实验设计-配置独立性与参数扫描.md`**
   - 新增 §12 执行细节决策记录（二阶段Kp扫参/Phase A 只读/rms 目标/exp01-02 解耦）
   - §12.2 写入实测数据 §12.3 duration 验证结果 §12.4 最终预算表 §12.5 Phase B 并行约束
   - 状态从"已确认设计，待启动 Phase A"改为"进行中 — Phase A 准备启动"

3. **建立 `experiments/` 目录骨架**
   - `experiments/README.md`：目录索引、命名规范、复用规范、Phase 进度
   - `experiments/docs/`、`experiments/common/`、`experiments/exp01_camera_fps/data/report/`、`experiments/exp02_raspi_process_delay/data/report/`

4. **`experiments/docs/配置独立性审查报告.md`（Phase A 核心产出）**
   - 总体对照表：4 个实体 + 2 个模型组件的隔离等级
   - 逐实体审查详情（含代码引用与风险评级）：
     - TargetEntity ✅ 隔离（deepcopy）
     - GimbalEntity ⚠️ 浅引用（不阻塞）
     - CameraEntity ⚠️ 浅引用（不阻塞）
     - RaspiEntity ✅/⚠️ 混合（delay_cfg 已 deepcopy）
     - CameraImagingModel 🚨 `scene_cfg.pixel_noise_std` 外部引用（记录待解耦，exp04 前需处理）
     - BaselineTrackerProgram ✅ 实验脚本可绕过
   - 结论：当前耦合不影响串行控制变量实验，多进程并行天然隔离
   - 不处理但记录的解耦项清单（含建议时机）

5. **`docs/TODO.md`**
   - 第 2 项状态改为"🟡 进行中（Phase A 已完成，输出配置独立性审查报告；待启动 Phase B）"

### 验证

- 实测脚本 `_smoke_bench_single.py` 和 `_smoke_duration_compare.py` 已按 CLAUDE.md §5.3 清理
- 文档/目录结构验证：`find experiments/ -type d` 返回 8 个目录，结构完整
- 审查报告基于真实代码 codegraph 探查（4 次 codegraph_explore + 1 次 Read），全部引用了代码行号

### 不涉及

- 任何 Python 源码修改（Phase A 严格只读）
- 任何测试新增（Phase A 只产出文档）
- `config.py` / 各 entity 源码 / runtime / bootstrap 均未触碰

---

## 089-20260608-151255 对照实验设计文档落地 + TODO.md 第 2 项维护

**修改者**：Claude Code

**目的**：响应 TODO.md 第 2 项需求 — 检查系统各实例配置独立性、设计相机帧率/树莓派图像处理延时对跟踪性能的对照实验、为每条件单独调优 Kp 并展示与系统参数的关系。

**修改内容**：

1. **新建详细设计文档**：`docs/todo/对照实验设计-配置独立性与参数扫描.md`
   - 5 个 Phase 拆分（A 配置审查 / B 框架搭建 / C 帧率实验 / D 延时实验 / E Kp 趋势分析）
   - 规划独立 `experiments/` 一级目录，建立 `common/` 共用框架 + `expNN_*/` 实验子目录的命名规范
   - 确认关键决策：延时实验仅改 `image_process_delay_s`、Kp 调优仅针对 `TrackerTuning`、yaw/pitch 二维独立扫参、不纳入 TODO 2.c
   - 包含涉及文件、依赖顺序、验证方案、后续扩展指引

2. **更新 `docs/TODO.md` 第 2 项**：
   - 添加文档引用 `[详细计划](todo/对照实验设计-配置独立性与参数扫描.md)`
   - 状态标记为 🟡 已确认设计，待启动 Phase A
   - 子项 a/b/d 分别注明对应的 `experiments/exp01_camera_fps/` 与 `experiments/exp02_raspi_process_delay/` 目录、Kp 调优方法

**验证**：

- 文档已写入指定路径，符合 `docs/todo/` 既有命名风格
- TODO.md 编辑无误，未破坏其他条目
- 实施性代码（experiments/ 目录、common/ 框架等）暂未开始，等待用户审阅文档后启动 Phase A

**后续**：用户审阅 `docs/todo/对照实验设计-配置独立性与参数扫描.md` 后，按 CLAUDE.md 4.5 阶段闸门规则，进入 Phase A 配置独立性审查（只读分析，产出 `experiments/docs/配置独立性审查报告.md`）。

---

## 088-20260607-221211 代码审阅报告维护：BUG修复+设计改进+测试补充

**修改者**：Claude Code

**目的**：针对 `docs/todo/代码审阅报告-20260607.md` 的审阅报告，对全量活跃代码进行维护。

**修改内容**：

阶段1（高优先级Bug）：
1. **BUG-01**：`TargetEntity.__init__()` 改为 `copy.deepcopy(cfg or target_cfg)`，防止全局配置被原地修改后影响已有实例（`entities/target/entity.py`）
2. **BUG-05**：`RaspiDelayModel` 新增 `reconfigure()` 方法，`set_delay_profile()` 改为调用 `reconfigure()` 而非重建模型，保留正在处理的观测（`entities/raspi/model.py`、`entities/raspi/entity.py`）

阶段2（中优先级Bug+设计问题）：
3. **BUG-03**：`GimbalEntity.get_state()` 首次调用时直接构造零值 `GimbalState`，不再触发 `update()` 产生控制器积分偏移（`entities/gimbal/entity.py`）
4. **BUG-04**：`CascadedController2Axis.step()` 新增 `_last_rate_cmd` 缓存，非 rate_tick 时复用上次输出，删除用 dt 替代 rate_dt 的错误分支（`entities/gimbal/control.py`）
5. **FUNC-01**：定义 `COMMAND_PAYLOAD_SCHEMA`，在 `_dispatch()` 入口校验 payload 字段完整性和类型（`runtime/types.py`、`runtime/digital_twin_runtime.py`）
6. **DESIGN-01/02/STYLE-01**：更新 `baseline.py` 冻结值使其与当前 config.py 默认值（6.0/100）一致，并注释偏离原因（距离相关亮度衰减引入后的必要调整）（`baseline.py`）
7. **DESIGN-08**：在 `GimbalConfig` 的 `angle_min_deg`/`angle_max_deg` 加注释说明当前仅对 pitch 轴生效（`config.py`）

阶段3（低优先级清理）：
8. **BUG-02**：`tracker_program.py` 中 `frame.intrinsics` 访问加防御检查（`entities/raspi/tracker_program.py`）
9. **BUG-06**：realtime 模式改用 `time.perf_counter()` 补偿式 sleep，消除时间漂移（`simulation/headless.py`）
10. **DESIGN-03**：`waypoints` 类型改为 `list[...] | None = None`（`config.py`）
11. **DESIGN-04**：删除残留 `TargetKinematics2D = TargetKinematics3D` 别名（`entities/target/model.py`）
12. **DESIGN-06**：`apply_delay_profile()` docstring 补充说明 image_read 和 state_read 并行执行（`simulation/bootstrap.py`）
13. **FUNC-02**：`POWER_FAULT` 加注释标注为预留状态（`runtime/types.py`）
14. **FUNC-05**：两个 `CLAUDE.md` 删除过时的 "Config Editor 自动读取" 和 `TargetKinematics2D` 引用
15. **STYLE-03**：`wrap_pm180` 直接从 `runtime.types` 导入，消除 `simulation/types.py` 中的间接导入链（`simulation/state_buffer.py`、`simulation/gui/window.py`、`simulation/types.py`）

阶段4（测试覆盖补充）：
16. 新增 `tests/test_code_review_fixes.py`：BUG-01 深拷贝测试、BUG-03 无副作用测试、BUG-04 rate_tick 缓存测试、FUNC-01 命令校验测试（13 tests）
17. 扩展 `tests/test_obs_filter.py`：research/realistic 边界条件测试（4 tests）
18. 新增 `tests/test_bootstrap_timeout.py`：boot 流程验证和步数计算测试（3 tests）

**验证**：
- 全量测试 141 tests 全部通过（原 124 + 新增 17）
- 冒烟测试 `app.py --no-gui --mode offline --duration 1.0` 通过
- `baseline.py` 校验通过，config 与冻结基线一致

## 087-20260604-141411 CLAUDE.md 融合开发规范：TODO驱动+测试诚信+代码质量

**修改者**：Claude Code

**目的**：将参考项目（不便签）的成熟开发规范融合到本项目 CLAUDE.md 中，提升后续开发质量。

**修改内容**：
1. 新增「4.1 TODO 驱动开发」章节：任务状态实时同步、标记 `[x]` 前的强制检查清单、禁止无测试标记完成
2. 原「4.1 代码规范」调整为「4.2」，新增：命名必须表达意图、不留重复代码、不保留注释掉的代码和未使用导入、错误处理只在边界做
3. 原「4.2 测试规范」调整为「4.3」，新增：新增功能必须同步编写测试且保留、修改/删除功能须同步更新/删除测试、测试运行时机指引、测试文件命名对应规范
4. 新增「测试诚信（红线）」子章节：禁止篡改断言、硬编码预期、跳过失败测试、修改测试数据适配 bug
5. 原 CHANGELOG 和 ATP 规范拆为独立章节「4.4」「4.5」，内容不变
6. 原「4.3 多 Agent 协作」调整为「4.6」，新增垂直功能切片拆分和合并冲突立即解决
7. 两个 CLAUDE.md（项目根 + systemSimulation）同步更新

**验证**：内容审阅确认无遗漏，原有规范完整保留

**修改者**：Claude Code

**目的**：统一 docs 目录文件命名为中文，归档过时文档，删除冗余导航文档。

**修改内容**：
1. 归档 `docs/低空场景无线光通信ATP开发文档.md` → `archive/docs/`（ATP 代码已删除，路线图过时）
2. 删除 `docs/doc-structure.md`（与 README.md 高度重复，README 作为唯一导航入口）
3. 重命名 5 个英文文件为中文：
   - `algorithm_integration_guide.md` → `算法接入指南.md`
   - `maintenance_guide.md` → `维护规则.md`
   - `research_workflow.md` → `研究工作流手册.md`
   - `system_manual.md` → `系统主手册.md`
   - `tools_guide.md` → `工具手册.md`
4. 更新 `README.md` 中所有文档链接，移除 doc-structure 和 ATP 引用
5. 更新 `docs/` 下各文档内部交叉引用链接
6. 更新 `CLAUDE.md` 中 ATP 开发文档路径（指向 archive/docs/）

**验证**：docs/ 目录下只剩 6 个中文命名 .md 文件，README.md 和各文档链接指向正确

## 085-20260604-112941 系统瘦身：删除ATP状态机 + 归档非核心文件 + 清理过时代码

**修改者**：Claude Code

**目的**：系统简化，删除不再需要的ATP状态机框架，归档阶段文档和研究产出，清理过时构建产物。

**修改内容**：
1. 删除ATP状态机核心：`atp_state_machine.py`、`atp_control_program.py`、`trackers/` 目录
2. 删除 `config.py` 中的 `ATPStateMachineConfig` 配置类
3. 清理 `entities/raspi/entity.py`、`entities/raspi/__init__.py` 中所有ATP引用
4. 清理 `simulation/state_buffer.py` 中ATP状态记录
5. 清理 `simulation/gui/window.py` 中ATP相关UI和算法选项
6. 清理 `tools/run_benchmark.py`：移除ATP算法注册、FrameRecord.atp_state、ATP指标计算、状态时间线图
7. 清理 `tests/test_phase4_algorithm_baselines.py`：移除ATP相关测试，保留SummarizeResults测试
8. 清理 `tests/test_runtime_api.py`：移除ATP相关测试
9. 删除过时代码：`delay_pipeline.py`、`run_raspi_tracking_demo.py`、`_analyze_tracking.py`
10. 删除docs构建产物：`node_modules/`、`generate_doc.js`、`package.json`、`package-lock.json`、`.npm-cache/`
11. 归档阶段文档（阶段0-6）→ `archive/docs/`
12. 归档研究产出（tracking_truth_analysis等）→ `archive/research/`
13. 归档非核心GUI工具 → `archive/gui-tools/`
14. 更新 `docs/doc-structure.md` 导航

**验证结果**：124个测试全部通过，冒烟测试正常。

## 084-20260604-101408 新增30fps vs 60fps相机帧率对比实验

**修改者**：Claude Code

**目的**：研究相机帧率对云台跟踪性能的影响，对比30fps和60fps在各自最优Kp下的跟踪误差差异。

**修改内容**：
1. `config.py`：CameraConfig新增 `frame_rate_hz` 参数（默认0=无限制，>0=指定帧率）
2. `entities/camera/entity.py`：CameraEntity实现帧率门控，未到帧间隔时保持上一帧不变
3. 新增 `tools/frame_rate_experiment.py`：三阶段对比实验脚本（Kp扫描→多seed对比→可视化报告）

**验证结果**：
- 160个单元测试全部通过，无回归
- 冒烟测试通过（默认帧率=0时行为不变）
- 帧率验证：30fps设置→实际28.6fps，60fps设置→实际50.0fps（受延迟管线~23ms限制）
- 实验结论：60fps在B1场景RMS比30fps降低9.3%（7.68 vs 8.47px），60fps最优Kp(1.1)高于30fps(1.0)
- 输出：`output/frame_rate_experiment/`（Kp曲线图、对比表、报告）

## 083-20260520-114202 新增 Kp+角度预测对比实验（Kalman + FFT）

**修改者**：Claude Code

**目的**：在角度域实现 Kalman 滤波预测和 FFT 正弦预测，与纯 Kp 基线对比，验证轨迹预测对跟踪性能的提升。

**修改内容**：
1. 新增 `research/kp_predictor_compare/predictors.py`：角度域预测器实现
   - `KalmanAnglePredictor`：四时段管道（像素→角度→KF预测→角度误差），恒速模型
   - `FFTSineAnglePredictor`：FFT 频率检测 + 正弦+线性自适应拟合，无主频时退化为线性外推
   - 关键设计：时段 4 不做 gimbal 积分，误差 = predicted_target_angle - gimbal_angle_from_obs
   - horizon 从 obs_dt 自动估算，不预设系统延时
2. 新增 `research/kp_predictor_compare/run_experiment.py`：3方法 × 3运动 × 2延时 全量对比实验

**实验结果**（12s, realistic, seed=42）：
- 26ms 延时：Kalman 降低 25-52%，FFT 降低 4-52%。匀加速 Kalman 最优，正弦 FFT 最优。
- 50ms 延时：预测收益 < 3%。P 控制器本身在高延时下增益不足是瓶颈。
- 全部 18 组实验检出率 100%，无目标丢失。

**验证**：冒烟测试通过 + 全量实验 18 组完成。

---

## 082-20260520-095709 修复世界视图底部文字被裁切的问题

**修改者**：Claude Code

**目的**：世界视图（WorldView）底部的状态文字（yaw、目标方位、角度误差等）因 Y 轴翻转导致 QGraphicsSimpleTextItem 被裁切显示不全。

**修改内容**：
1. 将世界视图底部状态文字从 QGraphicsSimpleTextItem（场景内图元）改为 QLabel（布局组件），放置在 world_view 下方
2. 移除 `_build_world_items()` 中的 `self.world_title` 图元创建
3. 更新 `_draw_world()` 中的文字更新逻辑，改为设置 QLabel 的 text 和 stylesheet

**验证**：冒烟测试通过 `python app.py --no-gui --mode offline --duration 1.0`。

## 081-20260520-084113 新增预测器建模原理文档

**修改者**：Claude Code

**目的**：为 `research/predictor_motion_compare/` 研究补充完整的数学建模文档，说明三种预测方法的原理、公式、适用场景与已知问题，便于后续修复和对比分析。

**修改内容**：
1. 新增 `research/predictor_motion_compare/预测器建模原理.md`，内容包括：
   - 系统延时链路说明（31 ms 端到端延时分解）
   - 方法 0（无预测）的滞后误差分析
   - Alpha-Beta 滤波器完整预测/更新公式
   - LinearKF 状态转移矩阵、卡尔曼方程、与 Alpha-Beta 的关系
   - 正弦分解预测器设计矩阵、频率搜索、外推公式
   - 当前实现的四个已知问题（t² 项过拟合、无退化路径、n_steps 不足、延时未传入 obs）
   - 三种方法能力对比表

**验证**：文档为纯 Markdown，无代码改动，无需运行验证。

---

## 080-20260520-010640 三方法三运动对比研究目录落地与验证
**修改者**：Codex

**目的**：在 `systemSimulation/research/predictor_motion_compare/` 下完成三种预测方法与三种运动模式的旁路研究，并跑通脚本、图表和汇总输出。

**修改内容**：
1. 新增研究目录说明、实施方案、运行脚本和正弦分解预测器。
2. 在 `realistic` 模式下完成三方法三运动对比，输出全程图和中间 3 秒放大图。
3. 修复脚本里 `--duration` / `--delay-ms` 只写不生效的问题。
4. 完成单组烟雾测试和完整 9 组实验验证。

## 079-20260520-001002 研究曲线补充中间3秒局部放大图
**修改者**：Codex

**目的**：在不动正式源码的前提下，为 `research/tracking_truth_analysis` 实验额外输出中间 3 秒的局部放大图，方便看细节。
**修改内容**：
1. **`research/tracking_truth_analysis/run_motion_compare.py`**：新增 `mid3s` 放大图输出，每个场景同时生成全程图和局部图。
2. **`research/tracking_truth_analysis/output/20260520-000807_motion_compare/`**：本次验证结果已包含 `sinusoidal`、`constant_velocity`、`constant_accel` 三种场景的全程图和放大图。
3. **`research/tracking_truth_analysis/run_motion_compare.py`**：在 `summary.txt` 里补了说明，提醒周期轨迹的全局峰值时间差容易误导，主看 `mid3s` 局部图。

---

## 078-20260519-235702 代码审查报告问题修复（批次1+批次2）

**修改者**：Claude Code

**目的**：根据代码审查报告（docs/代码审查报告-20260519.md）修复已确认的严重和中等问题。

**修改内容**：

### 批次1（数据隔离与命名）

1. **`entities/camera/entity.py`**（问题3.2）  
   `get_frame()` 改为返回轻量副本（`image.copy()` + `deepcopy(intrinsics)`），防止外部修改污染内部帧数据。新增 `import copy` 和 `from dataclasses import replace`。

2. **`simulation/obs_filter.py`**（问题6.1 + 4.7）  
   - debug 模式不再直接返回 `world_obs` 原始引用，改为浅拷贝顶层字典并对 `frame` 字段单独隔离复制  
   - `_copy_frame()` fallback 分支从原样返回改为 `copy.deepcopy(frame)`

3. **`entities/raspi/atp_state_machine.py`**（问题3.3）  
   `get_next_search_rate()` 重命名为 `advance_search_step()`，docstring 明确说明每 tick 只能调用一次且有副作用。

4. **`entities/raspi/atp_control_program.py`**（配套）  
   同步更新两处调用为 `advance_search_step()`。

5. **`entities/target/model.py`**（问题4.5）  
   - 删除 `_step_waypoint()` 开头死代码（错误的三元表达式赋值）  
   - 提取 `_parse_waypoint()` 静态辅助方法，消除两处重复的航点格式解析逻辑

6. **`entities/gimbal/entity.py`**（问题4.4）  
   - `__init__` 新增 `_last_state` 缓存  
   - `update()` 末尾缓存返回值  
   - `get_state()` 改为直接读缓存，不再调用 `update(0.0, ...)`，消除 getter 副作用

### 批次2（稳定性与维护）

7. **`entities/raspi/entity.py`**（问题10.3.6）  
   `__init__` 中对 `delay_cfg` 做 `deepcopy`，防止 `set_delay_profile()` 修改全局单例配置。

8. **`runtime/digital_twin_runtime.py`**（问题4.3）  
   引入 `logging`，`_apply_due_commands()` 对被拒绝的命令记录 debug 日志。

9. **`simulation/bootstrap.py`**（问题5.3）  
   等待 READY 的循环上限从魔法数字 3200 改为基于配置计算（最长启动延时 × 3 / dt_s + 10），加注释说明。

10. **`simulation/state_buffer.py`**（问题3.1 + 4.2 + 5.1）  
    - 新增 `read_all()` 原子读取方法，单次加锁返回 snapshot + frame + 全部曲线  
    - `metrics_log` 改为 `deque(maxlen=12000)`，`event_log` 改为 `deque(maxlen=1000)`  
    - `_extract_detection()` 阈值从硬编码 180 改为 `camera_cfg.detection_threshold`

11. **`simulation/gui/window.py`**（问题3.1 + 10.3.1 + 10.3.5 + 10.3.7 + 4.6）  
    - `_render_tick()` 改用 `read_all()` 原子读取，消除跨 tick 混读  
    - `_on_reset()` 新增 `isRunning()` 检查，旧线程未退出时跳过 reset  
    - `_draw_world()` 中 `sensor_w_mm` 从硬编码 4.8 改为 `camera_cfg.sensor_w_mm`  
    - `_on_save()` 导出摘要算法名优先使用 `_algo_key_override`  
    - 删除死代码 `_on_apply_delay()` 方法  
    - 顶部 import 补充 `camera_cfg`

### 测试适配

12. **`tests/test_phase4_algorithm_baselines.py`**  
    `TestRasterScan` 中三处 `get_next_search_rate()` 调用同步更新为 `advance_search_step()`，类 docstring 同步更新。

13. **`tests/test_obs_filter.py`**  
    `TestDebugMode` 两个测试用例更新断言：debug 模式现在返回隔离副本而非原始引用，改用内容相等断言替代 `assertIs`。

**验证结果**：  
- 冒烟测试通过（`app.py --no-gui --mode offline --duration 1.0`）  
- 全量测试 160/160 通过（`python -m unittest discover -s tests`）

---

## 077-20260519-230042 上帝视角跟踪分析修正真值对齐与角速度口径
**目的**：修正 `research/tracking_truth_analysis/run_truth_analysis.py` 中的两处计算问题，避免把线速度当成目标角速度，并让真值按观测时间正确对齐到同一拍世界快照。

**修改者**：Codex

**修改内容**：
1. **research/tracking_truth_analysis/run_truth_analysis.py** - 将真值对齐基准改为观测包自身时间戳
2. **research/tracking_truth_analysis/run_truth_analysis.py** - 将目标角速度改为由目标位置与速度计算方位角角速度
3. **research/tracking_truth_analysis/run_truth_analysis.py** - 增加时间戳精确匹配与越界保护

**验证**：
1. 重新运行 `conda run -n simulation python research/tracking_truth_analysis/run_truth_analysis.py --duration 12 --delay-ms 26 --obs-mode realistic --zoom-seconds 3`
2. `truth_err_mean_abs` 从原先的 2.6359 降至约 0.3721，`obs_truth_err_mean_abs` 也同步回到约 0.3715
3. 复看 `truth_yaw_mid3s.png`，目标角与云台角已基本贴合，误差曲线回到零附近小幅摆动
---

## 076-20260519-224701 上帝视角跟踪分析脚本首版跑通并补充诊断图

**目的**：完成 `research/tracking_truth_analysis/` 下第一版上帝视角分析脚本，打通观测视角与真值视角的对照导出，并补充误差与速度关系诊断图，验证基础跟踪方法的真实行为。

**修改者**：Codex

**修改内容**：

1. **research/tracking_truth_analysis/run_truth_analysis.py** — 新增上帝视角分析脚本，支持在 `realistic` 模式下运行 base 跟踪，并同步导出观测视角图、真值视角图、原始 CSV 和摘要文本
2. **research/tracking_truth_analysis/run_truth_analysis.py** — 将观测数据与仿真快照按时间戳配对，避免用样本序号硬对齐导致真值失真
3. **research/tracking_truth_analysis/run_truth_analysis.py** — 新增三张诊断图：`truth_error_vs_target_rate.png`、`truth_error_vs_gimbal_rate.png`、`obs_error_vs_truth_error.png`

**验证**：

1. 运行 `conda run -n simulation python -m py_compile research/tracking_truth_analysis/run_truth_analysis.py` 通过
2. 运行 `conda run -n simulation python research/tracking_truth_analysis/run_truth_analysis.py --duration 4.0` 成功生成输出目录
3. 抽查 `summary.txt` 与图像，确认真值误差与目标真实角速度存在明显相关，观测误差和真值误差并不完全一致

---

## 075-20260519-222704 上帝视角跟踪分析专题：补充详细实施方案与计划文档

**目的**：在既有研究目录基础上，补齐“上帝视角验证”专题的正式实施方案，明确研究目标、分析步骤、图表计划、输出物和验收标准，便于后续按同一口径推进。

**修改者**：Codex

**修改内容**：

1. **research/tracking_truth_analysis/上帝视角验证实施方案与计划.md** — 新增本地研究计划文档，明确背景、总目标、研究边界、数据视角、实施步骤、图表计划、输出计划、风险点和验收标准

**验证**：

1. 已按 `systemSimulation/research/tracking_truth_analysis/` 目录落盘
2. 已核对文档内容与当前研究边界一致：允许新增研究脚本和分析产物，但不修改项目现有源码
3. 已确认本次仅新增研究计划文档，不涉及 `simulation/`、`entities/`、`runtime/` 等正式实现

---

## 074-20260519-221233 新增上帝视角跟踪分析研究目录与专题说明

**目的**：为“基础跟踪方法在 realistic 模式下的上帝视角验证”建立独立研究目录，后续在不修改项目现有源码的前提下，开展观测视角与真值视角对照分析。

**修改者**：Codex

**修改内容**：

1. **research/tracking_truth_analysis/README.md** — 新增专题说明文档，明确研究目的、边界、双视角分析思路、建议输出和当前阶段结论
2. **research/tracking_truth_analysis/output/.gitkeep** — 预留研究输出目录，后续用于存放脚本产物、图表和数据

**验证**：

1. 已核对当前仓库规则、默认工作目录与 Python 执行口径
2. 已确认本次工作仅新增研究目录与说明，不修改 `simulation/`、`entities/`、`runtime/` 等现有源码
3. 已检查专题目录成功创建，后续可直接在该目录下继续开展旁路研究

---

## 073-20260519-221226 审查报告三次复核补充：确认第十节新增问题并补录导出摘要口径缺陷

**目的**：继续核对 `docs/代码审查报告-20260519.md` 第十节中新补的二次复核内容，确认哪些结论已经被代码直接支撑，并补录这轮新增发现的真实问题，保证审查报告和当前仓库状态一致。

**修改者**：Codex

**修改内容**：

1. **docs/代码审查报告-20260519.md** — 复核并保留第十节中关于 reset 线程退出、ATP 时间轴重建、ATP 窗口索引脆弱、算法下拉硬编码、FOV 传感器宽度硬编码、`set_delay_profile` 污染全局配置的判断
2. **docs/代码审查报告-20260519.md** — 新增“手动导出摘要时算法名称可能写错”问题，指出 `_on_save()` 与实际算法选择优先级不一致，可能把运行中的非基线算法导出成 `BaselineTrackerProgram`
3. **docs/代码审查报告-20260519.md** — 在第十节末尾同步更新优先级列表，把导出摘要口径问题纳入后续修复清单

**验证**：

1. 回读 `simulation/gui/window.py`，确认 `_on_reset()` 在 `wait(2000)` 后未检查 `isRunning()`，存在超时后继续创建新 worker 的窗口
2. 回读 `simulation/gui/window.py`，确认 `_draw_timeline()` 每帧都会清空并重建 ATP 区域对象，且 `atp_windowed` 通过位置索引与曲线窗口绑定，和原子读取问题叠加后确有脆弱性
3. 回读 `simulation/gui/window.py`，确认 `_on_save()` 使用 `self.cfg.control_program_path or "BaselineTrackerProgram"` 写摘要，与下拉切换后的实际运行算法口径不一致

## 072-20260519-220221 代码审查报告复核修订：剔除误报并补充新发现

**目的**：复核 `docs/代码审查报告-20260519.md` 与当前仓库实际代码是否一致，移除已失效或判断不准确的结论，补充这次实测确认的新问题，避免后续修复工作被错误优先级误导。

**修改者**：Codex

**修改内容**：

1. **docs/代码审查报告-20260519.md** — 结合项目真实功能、当前实现、现有测试和实际运行结果，重写审查结论结构，区分“确认成立”“已失效/不准确”“新增发现”三类问题
2. **docs/代码审查报告-20260519.md** — 移除“延时预算超过100%”和“ATP搜索off-by-one”两条误报；说明当前延时模型按并行观测阶段计算，总延时与用户预算一致
3. **docs/代码审查报告-20260519.md** — 新增“相机帧对象直接暴露，外部可修改内部数据”“debug观测模式直接透传原始对象”“快照与帧读取边界不严”等本次复核实测确认的问题
4. **docs/代码审查报告-20260519.md** — 重新排序优先级，突出 GUI 原子读取、帧数据隔离、状态推进命名、全局配置污染四项更应优先处理的问题

**验证**：

1. 运行 `conda run -n simulation python -m unittest tests.test_phase4_algorithm_baselines tests.test_delay_strategies tests.test_digital_twin_runtime -v`，61 项测试全部通过
2. 运行 `conda run -n simulation python -c "from simulation.bootstrap import build_runtime; rt=build_runtime(delay_ms=100.0, obs_mode='debug'); print(rt.raspi.get_delay_profile())"`，确认 `delay_ms=100` 时配置为 `25/50/25/25ms`，按并行观测模型总延时为 100ms
3. 运行 `conda run -n simulation python -c "from simulation.bootstrap import build_runtime; rt=build_runtime(delay_ms=0.0, obs_mode='debug'); rt.step(1); f=rt.camera.get_frame(); arr_before=f.image.copy(); f.image[0,0]=123; f2=rt.camera.get_frame(); print(int(f2.image[0,0]), int(arr_before[0,0]))"`，确认外部修改返回帧会污染内部帧数据

## 071-20260519-152049 角度曲线额外实验方案补充：加入轨迹预测算法曲线设计

**目的**：在已有额外实验方案基础上，补齐“启用轨迹预测算法后”该如何画角度曲线、如何区分控制用曲线和预测评估曲线，避免后续实验口径混乱。

**修改者**：Codex

**修改内容**：

1. **docs/额外实验-角度曲线/角度曲线实验方案.md** — 新增“使用轨迹预测算法后的扩展方案”章节，明确控制用曲线与预测效果评估曲线分开设计
2. **docs/额外实验-角度曲线/角度曲线实验方案.md** — 补充 `pred_target_pitch`、`pred_err_pitch`、`pred_true_err_pitch` 等曲线定义
3. **docs/额外实验-角度曲线/角度曲线实验方案.md** — 补充预测实验输出项与 `predictor_samples.csv` 建议字段
4. **docs/doc-structure.md** — 增加角度曲线额外实验方案入口，便于后续查找

**验证**：
- 文档已落盘并可索引
- 方案口径已补齐：基础版与预测版分离

---

## 070-20260519-112637 GUI 综合优化方案 v2（Step 1-4）全量实施

**目的**：针对 GUI 10 项问题做综合优化，含光斑显示、时间轴重构、诊断面板重构、顶部下拉、自动保存、世界视图 z 编码。
**修改者**：Claude Code

**修改内容**：

**Step 1 — 光斑显示 + 双视角信息精简**
1. **config.py** — `CameraConfig` 默认值：`beacon_sigma_px` 3.2→6.0，`detection_threshold` 180→100，`sigma_ref_distance_m` 0→80.0，`brightness_ref_distance_m` 0→80.0（启用距离衰减）
2. **simulation/gui/panels/camera_panel.py** — 移除实心红点，改为 1px 小十字标记；保留虚线轮廓圈（sigma 同步）
3. **simulation/gui/window.py** — `_camera_info_text` 简化为 `du/dv | sigma=xx.xpx`

**Step 2 — 时间轴重构 + 诊断面板重构**
4. **simulation/gui/window.py** — `_build_timeline`：移除独立 `plot_atp` 行，改用 `LinearRegionItem` 叠加在 `plot_rate` 上显示 ATP 状态背景色；新增 `lbl_current_atp` 标签
5. **simulation/gui/window.py** — `_draw_timeline`：按 ATP 状态段生成半透明色区域（SEARCH红/ACQUIRE橙/TRACK_COARSE蓝/TRACK_FINE绿）
6. **simulation/gui/window.py** — `_build_diag_section`：`QTabWidget+QTableWidget` 改为 `QTreeWidget`，4 个顶级节点全部展开，字段名带中文和单位
7. **simulation/gui/window.py** — `_update_diag_tab` / `_fill_diag_tree`：字段值带单位格式化

**Step 3 — 顶部下拉 + 删除应用延时按钮 + 重命名 τ**
8. **simulation/gui/window.py** — 工具栏新增 3 个 `QComboBox`（算法/观测模式/目标运动），切换时立即 reset
9. **simulation/gui/window.py** — 删除"应用延时"按钮（`btn_apply_delay`）
10. **simulation/gui/window.py** — 延时标签改为"链路延时…│云台响应τ: 30ms（一阶惯性，非通信延时）"
11. **simulation/gui/window.py** — 新增 `_build_control_program()` / `_on_combo_changed()` 方法

**Step 4 — 自动保存 + 世界视图 z 编码**
12. **simulation/state_buffer.py** — 新增 `metrics_log`（每帧指标）和 `event_log`（ATP 状态变迁）缓冲；`push()` 同步写入；新增 `read_logs()` 接口
13. **simulation/gui/window.py** — `_on_worker_finished` 触发 `_export_session_results()`，自动输出 `output/session_<ts>/`：dashboard.png / summary.json / metrics.csv / event_log.json / scene_config.json
14. **simulation/gui/window.py** — `_draw_world`：目标颜色按 z 编码（z>0 偏蓝，z<0 偏黄），尺寸随 z 变化，标题显示 z 值和图例说明
15. **tools/pid_tuner.py** — `detect_beacon_centroid` 阈值从硬编码 160 改为 `camera_cfg.detection_threshold`（修复因亮度衰减导致的检测失败）

**验证**：
- 冒烟测试通过
- 全量 160 个测试全部通过

## 069-20260519-075053 相机模型物理量打通到 UI：距离/sigma/亮度暴露并显示

**目的**：相机模型已实现"目标越远越小、越远越暗"的距离相关 sigma 和亮度，但物理量没有暴露到快照与 UI，用户看不到验证。本次把链路打通。
**修改者**：Claude Code

**修改内容**：

1. **entities/camera/model.py** — `render_beacon_frame()` 返回值从 4 元组扩展为 6 元组，新增 `sigma_px` 与 `brightness`
2. **entities/camera/entity.py** — `CameraState` 新增 `distance_m` / `sigma_px` / `brightness` 三字段；`update()` 写入；`get_state()` 暴露；`FramePacket.intrinsics` 携带 `sigma_px`
3. **simulation/gui/window.py** — 顶部摘要条新增"距离: xx.xm"；状态卡片把 backlog 换成"距离 xx.xm"；诊断面板 camera 标签页新增 distance_m / sigma_px / brightness
4. **simulation/gui/panels/camera_panel.py** — 双视角新增空心轮廓圈，半径 = 3×sigma_px，跟随光斑大小动态变化
5. **tests/test_runtime_api.py** — 新增 2 个测试：`snap.camera` 包含三项物理量；启用 `sigma_ref_distance_m` 后 sigma 与 distance 反比关系成立
6. **tests/test_2axis_geometry.py** / **tests/test_near_real_imaging.py** — 解包语法适配 6 元组返回值

**验证**：
- 冒烟测试通过
- 全量测试 160 tests 全部通过
- `snap.camera` 包含 distance_m=100.7 / sigma_px=3.2 / brightness=1.0（默认配置）
- 启用 `sigma_ref_distance_m=50.0` 后，远距离 sigma 严格小于 base，与公式吻合

---

## 068-20260518-225025 GUI 增量升级：摘要条+状态卡片+ATP状态带+导出增强

**目的**：按 GUI 重设计方案执行4步增量升级，提升仪表盘可用性。
**修改者**：Claude Code

**修改内容**：

1. **simulation/gui/window.py** — 控制栏拆为两层：顶部状态摘要条（ATP/算法/obs_mode/目标/延时/backlog 实时刷新）+ 操作按钮条
2. **simulation/gui/window.py** — 核心状态从 GridLayout 文本表改为 2×3 卡片网格（误差/姿态/uv/in_fov/backlog），带颜色语义
3. **simulation/gui/window.py** — 右侧信息区从 Tab 改为卡片+诊断区平铺，stretch 调整为 5:2:3
4. **simulation/state_buffer.py** — 新增 `atp_state_hist` 存储，`read_curves()` 返回 7 元组
5. **simulation/gui/window.py** — 时间轴新增 ATP 状态带（第3行窄条形图，按状态着色）
6. **simulation/gui/window.py** — 截图导出增强：输出到 `output/ui_export_<ts>/` 目录，含 `dashboard.png` + `summary.json`

**验证**：
- 冒烟测试通过
- 全量测试 158 tests 全部通过

---

## 067-20260518-135704 GUI 设计文档归档整理与重复初始化去重

**目的**：把 GUI 重设计方案归入阶段6文档目录，统一文档位置，顺手去掉 GUI 路径里重复的 `apply_target_overrides()` 调用，让文档口径和代码现状保持一致。  
**修改者**：Codex

**修改内容**：
1. **docs/阶段6-系统手册与维护/GUI重设计方案.md** — 将 GUI 设计方案移入阶段6目录，和同阶段材料归档到一起
2. **docs/doc-structure.md** — 更新 GUI 设计方案入口路径，避免后续查找混乱
3. **simulation/gui/runner.py** — 删除 GUI 启动时多余的 `apply_target_overrides(cfg)` 调用，保留窗口内部那次
4. **docs/阶段6-系统手册与维护/GUI重设计方案.md** — 同步修正文档内的实现说明，反映当前实际状态

**验证**：
- 文档已归档到阶段6目录
- `apply_target_overrides` 的 GUI 路径调用已去重

## 066-20260518-131448 GUI 设计方案复核修订：补齐边界约束、兼容性和可视化示意

**目的**：在 Claude 对 GUI 方案的二次审阅基础上，继续补齐遗漏点，使设计文档更贴近当前工程边界，也更方便后续直接拆开发。  
**修改者**：Codex

**修改内容**：
1. **docs/阶段6-系统手册与维护/GUI重设计方案.md** — 重写并补强 GUI 设计方案，明确本次不做的范围、增量改造边界和非 ATP 兼容要求
2. **docs/阶段6-系统手册与维护/GUI重设计方案.md** — 增加更直观的 ASCII 布局图，包括当前布局、目标布局、时间轴增强和状态卡片示意
3. **docs/阶段6-系统手册与维护/GUI重设计方案.md** — 补充导出定义、尺寸适配、涉及文件边界和风险评估
4. **docs/doc-structure.md** — 新增 GUI 设计方案入口，方便后续查阅

**验证**：
- 设计文档已更新并落盘
- 文档索引已补充 GUI 设计方案入口

---

## 065-20260518-003058 阶段6收口补修：ATP 状态打通到运行快照，盘点口径与实际一致

**目的**：修复阶段6收口中剩余的真实链路问题，确保 GUI 读取的 ATP 状态来自实际运行快照，而不是仅停留在 `get_state()` 层；同时清理盘点清单中的前后矛盾口径。  
**修改者**：Codex

**修改内容**：
1. **entities/raspi/entity.py** — `RaspiState` 新增 `atp_state` 和 `control_program_name`，并在 `update()` 中同步写入，确保 `snapshot.raspi` 真正携带 ATP 状态
2. **tests/test_runtime_api.py** — 新增运行时验证，确认 `build_runtime()` 后的真实快照包含 `atp_state` 和 `control_program_name`
3. **docs/阶段6-系统手册与维护/阶段6盘点清单.md** — 修正 ATP 状态描述与 CLI/GUI 对照表，使文档口径与当前实际行为一致

**验证**：
- `conda run -n simulation python -m unittest tests.test_runtime_api`
- `conda run -n simulation python app.py --no-gui --mode offline --duration 1.0`
- `conda run --no-capture-output -n simulation python -m unittest discover -s tests`

---

## 064-20260517-163000 Codex 二轮审阅修复：GUI 显示补齐 + 完成口径修正 + README 行数去除

**目的**：修正 Codex 二轮审阅指出的 P1-P3 问题：GUI 显示层补齐、完成口径修正、行数硬指标去除。
**修改者**：Claude Code

**修改内容**：

1. **entities/raspi/entity.py** — `get_state()` 新增 `atp_state`（从控制程序的 state_machine 读取）和 `control_program_name` 字段
2. **simulation/gui/window.py** — 核心面板新增 ATP 状态（带颜色）、观测模式、目标运动类型三行显示；诊断面板树莓派标签页新增 atp_state/control_program 字段
3. **CHANGELOG.md** — 062 条目标题从"阶段6全部交付"改为"主体交付"，口径不再超前
4. **README.md** — 文档导航表移除固定行数写法
5. **docs/阶段6-系统手册与维护/阶段6详细开发计划.md** — 移除行数硬指标
6. **docs/阶段6-系统手册与维护/阶段6盘点清单.md** — GUI 缺口项标记为已修复

**验证**：
- 冒烟测试通过
- 全量测试 156 tests 全部通过
- 8 个场景模板全部真实运行验证（constant_velocity/sinusoidal/random_walk/waypoint-2D/waypoint-3D/constant_accel/delay-52ms/default-sinusoidal）

---

## 063-20260517-154655 Codex 审阅修复：4 项问题全部修正（代码 bug + 文档不一致）

**目的**：修正 Codex 审阅阶段6产出时发现的 4 项问题，确保文档与代码一致。
**修改者**：Claude Code

**修改内容**：

1. **tools/record_session.py**（bug 修复）— `--obs-mode` CLI 参数未传递给 `build_runtime()`，现已添加 `obs_mode=cfg.obs_mode`
2. **docs/tools_guide.md** — replay_session 章节新增限制说明：`obs["frame"]` 始终为 None，依赖帧数据的控制程序无法回放
3. **runtime/README.md** — 延时拆分规则从旧的 1:1:0.5:1 修正为当前代码的 25%/50%/25%/25% 比例分配
4. **entities/target/README.md** — 扩展点章节中 `TargetKinematics2D.step()` 引用修正为 `TargetKinematics3D.step()`
5. **simulation/gui/window.py**（bug 修复）— `__init__` 和 `_on_reset` 中添加 `apply_target_overrides(self.cfg)` 调用，使 `--target-type` 和 `--waypoints` 在 GUI 模式下生效
6. **docs/system_manual.md** — FAQ 中 `--target-type` 在 GUI 模式不生效的条目更新为已修复

**验证**：
- 冒烟测试通过
- 全量测试 156 tests 全部通过

---

## 062-20260517-154018 阶段6C+6D完成：实例体系+场景模板+维护规则，主体交付

**目的**：完成子阶段6C（实例体系与场景模板）和6D（维护规则），主体交付。
**修改者**：Claude Code

**修改内容**：

1. **docs/examples_guide.md**（新增 ~180 行）— 实例体系说明
   - 7 类实例：快速启动/2D基础/3D基础/延时退化/benchmark对比/自定义控制程序/观测模式对比
   - 每个实例含可运行命令和预期结果

2. **docs/scenarios_catalog.md**（新增 ~200 行）— 典型场景模板
   - 4 个 2D 模板（匀速/正弦/随机/航点）+ 4 个 3D 模板（穿越/振荡/巡航/加速）+ 延时对比模板
   - 每个模板含目的/参数/适合验证的问题/预期现象，全部经过真实运行验证

3. **docs/maintenance_guide.md**（新增 ~150 行）— 维护规则
   - 维护检查清单（7 种变更类型 × 必须同步/可选同步）
   - 新增工具/算法/场景模板规则
   - 文档边界规则（README vs 主手册 vs 阶段文档）
   - GUI 修改同步规则 + CHANGELOG 规则

**验证**：
- 6 种场景模板真实运行验证通过（constant_velocity/random_walk/constant_accel/waypoints/delay-ms/obs-mode），完整 8 模板验证见 064
- 全量测试 156 tests 全部通过
- 冒烟测试通过

---

## 061-20260517-133905 阶段6B主手册+工具手册+工作流手册+接入指南+README收敛+导航重构

**目的**：执行子阶段6B，交付完整的文档体系。
**修改者**：Claude Code

**修改内容**：

1. **docs/system_manual.md**（新增 ~300 行）— 系统主手册
   - 平台架构、数据流、快速启动、7 种运行方式、研究流程概览、输出解读、常见问题、目录结构、参数速查表

2. **docs/tools_guide.md**（新增 ~280 行）— 工具手册
   - 16 个工具按 7 类分组，每个含用途/命令/参数/输入输出/衔接关系

3. **docs/research_workflow.md**（新增 ~200 行）— 研究工作流手册
   - 6 步完整链路：benchmark → 汇总 → 对比 → 诊断 → 出图 → 沉淀

4. **docs/algorithm_integration_guide.md**（新增 ~250 行）— 算法接入指南
   - 4 种接入方式（临时加载/正式注册/tracker-predictor组合/角度模式）
   - 最小示例代码、Tracker/Predictor 协议、常见错误

5. **README.md**（从 512 行收敛到 ~100 行）— 改为入口索引
   - 仅保留快速启动、文档导航（按角色/按任务）、架构概要、实体文档索引

6. **docs/doc-structure.md**（从 74 行扩展到 ~120 行）— 改为导航页
   - 新增按角色导航和按任务导航
   - 补齐阶段3-6 文档条目
   - 更新知识点归属（5 种运动模式、ATP 状态机、benchmark 等）

**验证**：冒烟测试通过；全量文档交叉引用一致。

---

## 060-20260517-132515 阶段6A盘点执行：文档/工具/GUI三维盘点完成，产出盘点清单

**目的**：执行阶段6A（现状盘点与收口定稿），形成阶段6后续工作的共同基线。
**修改者**：Claude Code

**修改内容**：

1. **docs/阶段6-系统手册与维护/阶段6盘点清单.md**（新增）
   - 文档角色矩阵：10 篇核心文档逐篇盘点，明确受众、过时程度、重叠关系和推荐定位
   - 工具矩阵：16 个工具逐个分类（5 主流程 + 9 辅助 + 2 待评估），确认主研究链路已完整闭环
   - GUI 差距表：已具备 12 项 / 已具备但未表达 7 项 / 仍缺失 2 项（含 ATP 状态暴露链路和 GUI 路径 target_type 不生效 bug）
   - 盘点结论：优先修复 doc-structure 导航过时、README 收敛、工具手册缺失三项 P0

2. **docs/阶段6-系统手册与维护/阶段6需求分析文档.md**（修订）
   - 补充精确现状数据（行数、GUI 字段清单、工具预分类）
   - 增加 GUI 差距的代码行号级定位
   - 新增量化验收指标（9.1 节）

3. **docs/阶段6-系统手册与维护/阶段6详细开发计划.md**（修订）
   - 新增任务依赖关系图
   - 工具矩阵预分类表、GUI 修改范围表
   - 总工作量预估：文档 1750-2500 行 + GUI 代码小到中等规模

**验证**：盘点清单已覆盖全部文档、工具和 GUI 三维盘点，结论可直接支撑后续子阶段 6B-6D 实施。

---

## 059-20260517-131117 阶段6文档二次审阅修正与口径收紧

**目的**：对 Claude 在阶段6文档上的二次细化结果继续复审，修正“现状精确数字已过时”“GUI 改动量估计过轻”“任务依赖写得过死”等会误导后续实施判断的问题。
**修改者**：Codex

**修改内容**：

1. **docs/阶段6-系统手册与维护/阶段6需求分析文档.md**
   - 将文中的文件行数口径改为“当前快照记录”，避免把易变数字写成长期稳定事实
   - 按当前仓库真实状态修正现状数据：
     - `README.md`：504 → 当前 512 行
     - `docs/树莓派控制程序开发手册.md`：459 → 当前 458 行
     - `docs/doc-structure.md`：75 → 当前 74 行
   - 收紧 GUI 相关需求表述：明确 ATP 状态当前尚未进入 `snapshot.raspi`，若纳入本轮 GUI 适配，需先补齐状态暴露链路，不能只按界面加标签估算
   - 将 README 目标从“硬性 150 行以内”收紧为“显著收敛为轻入口页”，避免把版式数字当成核心验收目标

2. **docs/阶段6-系统手册与维护/阶段6详细开发计划.md**
   - 修正盘点表中的现状数字，与当前仓库真实行数一致
   - 将 GUI 改造描述从“`window.py` +15-25 行”改为更真实的“小到中等改动，可能跨 3-5 个文件”
   - 在任务 J 中补充说明：ATP 状态显示不仅涉及 GUI，还可能涉及 `entities/raspi/entity.py`、状态输出链路和相关测试
   - 在验收标准和风险控制中去掉对单文件行数的刚性承诺，改为以“范围小、链路清楚、不引入额外框架改造”为控制目标
   - 补充说明：GUI 任务 J 的严格前置是 6A 的差距盘点与边界决策；只有在需要把场景/实例标签直接带入界面时，才参考 6C 输出

**校对与验证**：

1. 已按 `AGENTS.md` 要求使用 `Get-Date -Format yyyyMMdd-HHmmss` 获取真实时间戳 `20260517-131117`
2. 已再次核对当前仓库真实文件行数：
   - `README.md`：512
   - `docs/使用手册.md`：153
   - `docs/树莓派控制程序开发手册.md`：458
   - `docs/doc-structure.md`：74
   - `app.py`：7
3. 已核对当前实现链路：
   - GUI 已显示 yaw、pitch、u、v、backlog、obs_lag
   - ATP 状态机存在于控制程序侧，但当前 `snapshot.raspi` 尚未暴露 ATP 状态
   - 因此“GUI 只加少量标签即可显示 ATP 状态”的估计不成立，已在文档中收紧

---

## 058-20260517-122041 阶段6文档审阅修订与计划收口

**目的**：针对 Claude 产出的阶段6需求文档与详细开发计划进行复审，修正与当前仓库现状不一致、范围定义偏轻或前置条件缺失的问题，使阶段6后续实施建立在准确盘点和稳定口径之上。
**修改者**：Codex

**修改内容**：

1. **docs/阶段6-系统手册与维护/阶段6需求分析文档.md**
   - 将阶段6定位从单纯“手册整理与维护更新”收紧为“系统手册、实例体系与维护治理”
   - 新增“阶段6前置盘点与差距清单”作为 P0 前置要求，明确文档、工具、实例、GUI、维护规则必须先盘点再实施
   - 修正 GUI 现状表述，避免将当前已具备的双轴与链路信息误写成“一维旧界面”
   - 明确 `app.py` 只是薄入口，阶段6重点应放在 CLI、GUI 和主入口口径统一，而不是把修改 `app.py` 本身当作主目标
   - 补强“树莓派控制程序编写”“新算法接入平台”“标准实例体系”“维护治理规则”等核心需求
   - 将 GUI 工作拆分为“适配方案定义”和“增量实现”两层优先级，避免范围失控

2. **docs/阶段6-系统手册与维护/阶段6详细开发计划.md**
   - 重写实施顺序，新增 6A“现状盘点与收口定稿”作为正式开工前的第一子阶段
   - 将阶段6拆分为 6A 盘点、6B 手册与接入指南、6C 实例体系、6D GUI 与治理收口四个子阶段
   - 明确工具盘点、实例盘点、GUI 差距表、文档角色矩阵等具体产物，而不是直接进入写文档或改界面
   - 将“工具手册”“研究工作流手册”“实例体系说明”“维护规则文档”纳入明确交付物
   - 收紧 GUI 修改范围为增量适配，不承诺推翻式重构
   - 增加风险控制：防止只补文档、不做实例；防止把已存在能力误判为缺口；防止未经盘点就判定旧工具废弃

**校对与验证**：

1. 已按 `AGENTS.md` 要求使用 `Get-Date -Format yyyyMMdd-HHmmss` 获取真实时间戳 `20260517-122041`
2. 已核对 `CHANGELOG.md` 当前最新条目为 `057-20260517-003449`，本次新增条目编号顺延为 `058`
3. 已结合当前仓库现状完成交叉校对：
   - `tools/` 当前真实清单为 16 个脚本
   - 当前 GUI 已显示 yaw、pitch、u、v、backlog、obs_lag 等信息
   - `app.py` 当前仅为薄入口，主逻辑位于 `simulation/cli.py` 与 `simulation/gui/window.py`
   - 目标运动模型已处于 3D 状态，不应再按早期 2D 平台口径规划阶段6

---

## 057-20260517-003449 阶段5复审优化与口径收紧

**目的**：对阶段5交付物做二次复审，修正回归对比遗漏指标与 0 值丢失问题，收紧算法诊断对“预测行为”的表述口径，并优化对比图的可读性。
**修改者**：Codex

**修改内容**：

1. **tools/compare_results.py**
   - 修复聚合时使用 `or` 导致 `0 / 0.0` 指标被误判为缺失值的问题
   - 将 `reacquire_success_rate`、`time_to_acquire_s`、`time_to_fine_track_s` 纳入正式对比指标集合
   - 保持旧结果目录兼容，不要求重跑阶段4/阶段5已有实验

2. **tools/diagnose_algorithm.py**
   - 将“预测行为分析”改为“预测相关代理分析”，明确当前结论基于误差趋势间接推断，不冒充“预测量 vs 真值”的直接分析
   - 诊断报告新增代表样本 seed 说明，避免把单 seed 详细诊断误写成“全场景全种子平均结论”

3. **tools/plot_comparison.py**
   - 重构排名柱状图：不同量纲指标分开成独立子图，不再共用同一 y 轴
   - 修复分时段箱线图 x 轴仅显示数字位置的问题，改为明确展示 ATP 阶段标签，并优先将基线算法放在前面

4. **tests/test_phase5_research_support.py**
   - 新增阶段5专项测试，覆盖回归对比 0 值保留、ATP 指标纳入、排名图出图、分时段箱线图出图

5. **docs/阶段5-研究支撑与结果固化/data_inventory.md**
   - 修正文档口径：前 3 个诊断维度属于直接分析，第 4 个预测维度属于代理分析

**验证**：

1. 阶段5专项测试 `tests.test_phase5_research_support` 4 项全部通过
2. `tools/compare_results.py`、`tools/diagnose_algorithm.py`、`tools/plot_comparison.py` 已基于真实 `output/experiments` 目录完成抽查运行
3. 全量 unittest 重新执行，156 个测试全部通过

---

## 056-20260517-001835 阶段5研究支撑与结果固化完成

**目的**：实施阶段5全部任务，将阶段4的 benchmark 能力升级为可对比、可诊断、可追溯、可持续扩展的研究工作流。
**修改者**：Claude Code

**修改内容**：

1. 数据盘点（Section 6.0）：系统性检查 benchmark 输出数据结构，确认 metrics.csv 已包含全部 4 个诊断维度所需数据（atp_state、yaw_rate_cmd、pitch_rate_cmd、pixel_error），无需补充记录字段。输出 `docs/阶段5-研究支撑与结果固化/data_inventory.md`。

2. 子任务 A1 — 回归对比工具 `tools/compare_results.py`：
   - 支持两组实验目录自动对比（baseline vs new）
   - 支持同算法回归对比和跨算法对比（--baseline-algorithms / --new-algorithms）
   - 自动识别提升项、退化项、超阈值报警
   - 输出 comparison.csv / comparison.json / comparison.md

3. 子任务 A2 — 算法诊断工具 `tools/diagnose_algorithm.py`：
   - 4 个诊断维度全部实现：误差分时段分解、ATP 状态转换分析、控制行为分析、预测行为分析
   - 支持目标算法 vs 基线算法的对比诊断
   - 自动生成初步解释方向（如"始终未进入精跟踪"、"误差发散"）
   - 输出 diagnosis.md / diagnosis.json

4. 子任务 C1+C2 — 实验记录模板与自动生成：
   - run_benchmark.py 新增 --experiment-note 参数
   - benchmark 运行完成后自动生成 experiment_log.md 骨架（含运行命令、算法列表、RMS 排名表）
   - 保留人工补充"改动内容"、"结论"、"下一步"的空间

5. 子任务 B1+B2 — 对比可视化 `tools/plot_comparison.py`：
   - 同场景多算法误差曲线叠加图
   - 算法×场景 RMS 热力图
   - 多指标算法排名分组柱状图
   - 分时段误差箱线图
   - 支持 matplotlib 中文字体

6. ATP 开发文档更新：阶段5状态改为"进行中"，名称改为"研究支撑与结果固化"

**验证结果**：

- 冒烟测试通过（app.py --no-gui --duration 1.0）
- 全量测试 152 个全部通过（unittest discover -s tests -v）
- 阶段5闸门 5 项全部 PASS：
  - [x] 数据盘点完成
  - [x] 回归对比工具可用
  - [x] 算法诊断工具可用，对 linear_kf_tracker 成功诊断出"始终未进入精跟踪"等退化原因
  - [x] 实验记录模板可自动生成
  - [x] 跨算法对比图可稳定生成（热力图、叠加图、箱线图、柱状图）

---

## 055-20260516-231906 阶段5需求与计划按审核意见修订

**目的**：根据《审核意见-需求文档与详细计划》修正阶段5两份文档，补齐数据盘点前置、诊断维度分层、验收分层与优先级一致性，避免后续实施时边界和承诺失真。
**修改者**：Codex

**修改内容**：
1. **docs/阶段5-研究支撑与结果固化/阶段5需求分析文档.md** — 升级为 v2，补充算法诊断的数据可用性前提与向后兼容原则；将“初步结论”拆成“必须的数值判断”和“可选的原因方向”；补充工作流自动化边界；统一优先级口径，将对比可视化调整为 P2
2. **docs/阶段5-研究支撑与结果固化/阶段5详细开发计划.md** — 升级为审核版 v2，新增 benchmark 输出数据盘点前置步骤；将算法诊断拆为“必须交付”和“视数据可用性决定”两层；明确阶段5不纳入增量实验支持；补充兼容性验收与阶段闸门前置项

**验证**：
1. 已逐条对照 `docs/阶段5-研究支撑与结果固化/审核意见-需求文档与详细计划.md` 的高优先级与中优先级意见完成修订
2. 已确认《阶段5需求分析文档》和《阶段5详细开发计划》在对比可视化优先级上统一为 P2
3. 已确认详细计划不再把增量实验支持作为阶段5交付项，且诊断验收已区分必须项与可选项

---

## 054-20260516-224636 阶段5需求分析文档建档

**目的**：在阶段5正式进入详细计划前，先把需求层锁定，单独形成《阶段5需求分析文档》，明确阶段5服务目标、核心需求、默认工作流、输出形态、边界和优先级，避免后续计划直接替需求做决定。
**修改者**：Codex

**修改内容**：
1. **docs/阶段5-研究支撑与结果固化/阶段5需求分析文档.md** — 新建阶段5需求文档，覆盖背景与现状、阶段5总体定位、主要受众、核心研究目标、算法比较/回归判断/算法诊断/对比可视化/实验记录/结果表达/未来扩展等需求，以及默认工作流、输出形态、边界与非目标、需求优先级和结论

**验证**：
1. 已基于本轮对话中确认的需求选项整理正式文档，包括：算法研究优先、兼顾论文、默认按“算法×场景”比较、默认输出“表+图+记录”、记录载体为 Markdown、诊断优先为分阶段误差、一键全流程目标、结果输出为“事实+初步结论”
2. 已确认该文档独立建档于阶段5目录，未与《阶段5详细开发计划》混写
3. 已确认需求文档内容不进入实现细节，符合“先锁需求、再写计划”的顺序

---

## 053-20260516-213530 阶段5改造后详细开发计划建档

**目的**：在阶段4完成后，基于用户研究目标和对《阶段5改造方向建议稿》的审核意见，正式形成阶段5的单独计划文档，明确阶段5不是原样启用旧定义，而是改造为“研究支撑与结果固化”阶段后再实施。
**修改者**：Codex

**修改内容**：
1. **docs/阶段5-研究支撑与结果固化/阶段5详细开发计划.md** — 新建阶段5计划文档，明确阶段5改造理由、阶段4与阶段5边界、优先级 A > C > B、算法诊断能力、实验记录模板、对比可视化、增量实验支持、涉及文件、验收标准和阶段闸门

**验证**：
1. 已核对 `docs/阶段5改造方向建议稿-审核意见.md` 中的三项核心修正意见，并全部吸收进阶段5计划
2. 已核对阶段4正式结果链路与现有输出文件（`result.json / metrics.csv / summary.csv / summary_grouped.csv / summary.json`），确保计划中的新增能力基于现有结果体系增量建设
3. 已确认阶段5计划文件独立建档，未并入开发手册

---

## 052-20260516-185115 树莓派控制程序开发手册补充

**目的**：补一份专门面向“自定义树莓派控制程序”的开发手册，帮助后续直接照文档完成编写、接入和测试，不再只靠分散的 README 和源码入口自己拼。
**修改者**：Codex

**修改内容**：
1. **docs/树莓派控制程序开发手册.md** — 新增专门手册，整理控制程序职责、输入输出、最小模板、文件放置方式、加载命令、阶段4自定义控制结构、测试路径和常见问题
2. **docs/使用手册.md** — 在文档导航和“自定义控制程序”章节中补入新手册入口
3. **docs/doc-structure.md** — 将新手册加入文档总导航、阅读建议和知识点归属

**验证**：
1. `conda run -n simulation python -m unittest discover -s entities/raspi/tests -p "test_*.py" -v` 通过
2. `conda run -n simulation python -m unittest tests.test_digital_twin_runtime -v` 通过
3. `conda run -n simulation python app.py --no-gui --mode offline --duration 1.0` 通过

---

## 051-20260516-182529 阶段4收尾优化：收紧算法模式校验并拆分总体汇总口径

**目的**：复审阶段4完成结果时，继续消除“算法支持模式”和“总体汇总口径”两处残留歧义，避免后续误跑和误读。

**执行者**：Codex

**修改内容**：
1. `tools/run_benchmark.py` —— 新增 `is_obs_mode_allowed()`；在 `run_experiment` 入口直接拒绝不兼容的算法/模式组合；在 `run_suite` 中补充“无有效实验组合”直接报错。
2. `tools/summarize_results.py` —— `by_algorithm` 改为按“算法 + observation_mode”分别汇总，避免导出的结构化结果混合 `research` 与 `realistic`。
3. `tests/test_phase4_algorithm_baselines.py` —— 补充算法模式兼容性测试，以及 `by_algorithm` 按模式拆分的测试。

**验证结果**：
1. 阶段4专项测试通过。
2. 全量 `unittest` 通过。
3. `angle_mode_realistic + research` 会被入口拒绝。
4. 汇总结果会按模式分别输出总体统计。

---

## 050-20260516-180354 阶段4正式benchmark完成+闸门验证通过+阶段4标记已完成

**目的**：完成75组research正式benchmark，验证闸门条件，标记阶段4完成。

**修改者**：Claude Code

**修改内容**：
1. 运行75组正式benchmark（5算法×3场景×5种子×research模式），全部成功
2. 运行 summarize_results 汇总工具，产出 summary.csv、summary_grouped.csv、summary.json 及排名表
3. `docs/低空场景无线光通信ATP开发文档.md` — 阶段4状态改为 🟢 已完成，4个闸门 checkbox 全部勾选，活跃阶段指向阶段5

**Benchmark结果摘要（research模式，跨场景RMS均值）**：
| 排名 | 算法 | RMS均值(px) |
|------|------|-------------|
| 1 | atp_search_track_baseline | 20.31 |
| 2 | baseline_rate_p | 20.33 |
| 3 | rate_pi | 20.63 |
| 4 | alpha_beta_tracker | 56.85 |
| 5 | linear_kf_tracker | 142.47 |

**验证结果**：
1. 75组实验全部成功，无失败
2. 汇总排名正确按 obs_mode 分组
3. 闸门4项全部满足

---

## 049-20260516-134201 阶段4 Codex二轮评审修复（模式拦截+排名分组）

**目的**：根据 Codex 二轮评审修复 angle_mode 模式拦截缺失和算法总体排名混合 obs_mode 问题。

**修改者**：Claude Code

**修改内容**：
1. `tools/run_benchmark.py` — 在 `run_suite` 循环中增加算法-模式兼容性校验，不允许的组合直接跳过并打印提示；修复 `total` 变量名改为 `valid_count`；确保输出目录存在
2. `tools/summarize_results.py` — 算法总体排名改为按 obs_mode 分组输出，每个模式独立出一份排名表

**验证结果**：
1. `angle_mode_realistic + research` 被正确拦截（跳过），`angle_mode_realistic + realistic` 正常运行
2. 149 个测试全部通过，无回归

---

## 048-20260516-124934 阶段4 Codex评审修复（6项问题全部修复+39个新测试）

**目的**：根据 Codex 评审意见修复阶段4代码问题，提升数据可信度和测试覆盖。

**修改者**：Claude Code

**修改内容**：
1. `entities/raspi/atp_state_machine.py` — 修复光栅扫描 pitch_rate 始终为 0 的缺陷，引入 `_search_pitch_stepping` 状态，yaw 到达边界时输出 pitch_rate 脉冲完成分层步进
2. `entities/raspi/atp_control_program.py` — 新增 `last_yaw_rate_cmd_dps`、`last_pitch_rate_cmd_dps`、`last_detection_found` 属性，在 `on_tick` 返回前记录最后发送的速率命令值
3. `tools/run_benchmark.py` — 实现 `reacquire_time_s` 和 `reacquire_success_rate` 指标的真实计算（从 ATP 状态序列提取 LOST/REACQUIRE→ACQUIRE/TRACK 的耗时和成功率）；注册 `angle_mode_realistic` 算法（独立 ControlProgram 包装，仅 realistic/debug 可用）；新增 `ALGORITHM_OBS_MODES` 注册表
4. `tools/summarize_results.py` — 汇总分组 key 增加 `observation_mode` 维度，排名表和分组 CSV 增加 obs_mode 列
5. `tests/test_phase4_algorithm_baselines.py` — 新增 39 个专项测试覆盖 ATP 状态机转换、光栅扫描、控制程序属性、预测器、跟踪器、汇总工具分组

**验证结果**：
1. 全量 149 个测试通过（原有 110 + 新增 39），无回归
2. 冒烟测试通过（`app.py --no-gui --mode offline --duration 1.0`）
3. Benchmark 小规模验证：metrics.csv 中 yaw_rate_cmd/pitch_rate_cmd 正确记录非零值，ATP 指标基于真实状态计算

---

## 047-20260516-103702 阶段4算法基线建设实施（多Agent并行开发）

**目的**：实施阶段4「算法基线建设」，完成ATP状态机、5个算法基线、Benchmark工具全链路。

**修改者**：Claude Code

**修改内容**：
1. `config.py` — 新增 `ATPStateMachineConfig` dataclass（14个可配置参数）+ 模块级单例 `atp_sm_cfg`
2. `entities/raspi/atp_state_machine.py` — 新增ATP状态机（6状态：SEARCH/ACQUIRE/TRACK_COARSE/TRACK_FINE/LOST/REACQUIRE，光栅扫描策略，超时重捕获）
3. `entities/raspi/atp_control_program.py` — 新增 `AtpControlProgram`（持有状态机+可插拔tracker/predictor，实现ControlProgram协议）
4. `entities/raspi/trackers/rate_p_tracker.py` — 新增 `RatePTracker`（速率P控制，支持prediction替代）
5. `entities/raspi/trackers/rate_pi_tracker.py` — 新增 `RatePITracker`（速率PI控制，积分限幅）
6. `entities/raspi/trackers/angle_mode_tracker.py` — 新增 `AngleModeTracker`（角度模式，仅realistic可用）
7. `entities/raspi/predictors/alpha_beta.py` — 新增 `AlphaBetaFilter`（alpha-beta滤波器）
8. `entities/raspi/predictors/linear_kf.py` — 新增 `LinearKF`（线性卡尔曼滤波器）
9. `tools/run_benchmark.py` — 新增Benchmark运行工具（5算法×3场景×5种子，标准输出文件）
10. `tools/summarize_results.py` — 新增结果汇总工具（排名表+CSV+JSON）
11. `entities/raspi/__init__.py` — 更新导出

**验证结果**：
1. 全量测试通过：110个测试，无回归
2. 冒烟测试通过：`app.py --no-gui --mode offline --duration 1.0` 闭环正常
3. 5个算法全部可在Benchmark中独立运行并生成标准结果文件
4. summarize_results 正确产出排名表

---

## 047-20260516-104047 规范整理 CLAUDE 与 AGENTS 文档

**目的**：消除 `CLAUDE.md` 与 `AGENTS.md` 的重复和冲突，使一份作为主规则文档，另一份作为精简补充文档，降低后续维护成本。

**修改者**：Codex

**修改内容**：
1. `CLAUDE.md` — 将全量测试通过标准改为“运行 tests/ 下全量 unittest 并全部通过”，移除易过时的固定测试数量
2. `CLAUDE.md` — 将 CHANGELOG 时间戳获取方式从 bash 风格 `date +%Y%m%d-%H%M%S` 调整为当前环境可执行的 PowerShell 命令 `Get-Date -Format yyyyMMdd-HHmmss`
3. `AGENTS.md` — 重写为精简补充版，明确 `CLAUDE.md` 为主规则文档，只保留所有 Agent 通用的补充规则、当前环境下的时间戳规则和命令执行口径

**验证结果**：
1. 静态核对两份文档，确认不再存在整份重复复制
2. 静态核对两份文档，确认 CHANGELOG 时间戳规则与当前 PowerShell 环境一致
3. 静态核对两份文档，确认主次关系和维护边界已明确

---

## 046-20260516-033500 阶段4计划 v5 口径补齐

**目的**：补齐阶段 4 计划文档中两处会直接影响实现落地的一致性问题，避免实现阶段再次因口径不清出现分叉。

**修改者**：Codex

**修改内容**：
1. `docs/阶段4-算法基线建设/阶段4详细开发计划.md` — 文档版本升级为 v5，补充修订记录
2. `docs/阶段4-算法基线建设/阶段4详细开发计划.md` — 清理任务 A 架构图中已删除的 `reactive_baseline` 残留，改为“无预测，对应 baseline_rate_p 对照组”
3. `docs/阶段4-算法基线建设/阶段4详细开发计划.md` — 在 ATPStateMachineConfig 中新增 `search_rate_dps` 与 `reacquire_search_rate_dps`，冻结 SEARCH / REACQUIRE 扫描速率口径
4. `docs/阶段4-算法基线建设/阶段4详细开发计划.md` — 明确 research 模式开环扫描如何由步进、速率、停留时长换算执行，并补充 ACQUIRE 阶段“像素误差有限”的判定定义

**验证结果**：
1. 静态核对阶段 4 计划文档，确认已无 `reactive_baseline` 作为独立首轮算法的残留表述
2. 静态核对阶段 4 计划文档，确认 SEARCH / REACQUIRE 扫描速率和 ACQUIRE 有效检测判定已明确写入

---

## 045-20260516-031500 阶段4计划 v4 评审修正

**目的**：修正 Codex v3 版本中残留的 3 处问题。

**修改者**：Claude Code

**修改内容**：
1. `docs/阶段4-算法基线建设/阶段4详细开发计划.md` — 文档版本升级为 v4，补充修订记录
2. 任务 C：移除 `reactive_baseline`（与任务 B 的 `baseline_rate_p` 概念重叠），明确 `baseline_rate_p` 同时充当"无预测"对照组；预测算法基线改为 alpha_beta_tracker 和 linear_kf_tracker 两种
3. 任务 D 状态切换条件 2：将模糊的"目标连续可见且检测稳定"量化为"连续 `n_acquire_confirm` 帧检出且像素误差有限"
4. 任务 D 配置参数表：新增 `n_acquire_confirm`（int, 默认 5）
5. 任务 D 搜索策略：新增 research 模式下开环定时扫描说明（research 白名单无 gimbal 角度反馈，SEARCH 无法做闭环角度定位）
6. §8.3 验收结果：调整为 4 算法 + 1 ATP 组合基线的结构，明确 baseline_rate_p 兼任无预测对照

**验证结果**：
1. 静态核对任务 C 与任务 B 无概念重叠
2. 静态核对所有 ATP 状态切换条件均含量化参数
3. 静态核对 research 模式下 SEARCH 策略可行性已说明

---

## 044-20260516-020500 阶段4计划文档一致性修订

**目的**：修正阶段 4 计划文档中首轮 benchmark 覆盖范围和工况维度定义的两处前后不一致问题，避免后续实施时按错口径推进。

**修改者**：Codex

**修改内容**：
1. `docs/阶段4-算法基线建设/阶段4详细开发计划.md` — 文档版本升级为 v3，补充修订记录
2. `docs/阶段4-算法基线建设/阶段4详细开发计划.md` — 将 benchmark 维度中的“延时档位”改为“延时定义说明”，明确首轮正式 benchmark 直接使用 B1/B2/B3 完整工况组合，不再与独立 L0/L1/L2 交叉展开
3. `docs/阶段4-算法基线建设/阶段4详细开发计划.md` — 将首轮 research 验收结果由 60 组调整为 75 组，并补入 `atp_search_track_baseline`，使其与“至少交付 1 个带 ATP 状态机的搜索-跟踪组合基线”保持一致

**验证结果**：
1. 静态核对阶段 4 计划文档，确认首轮 benchmark 已覆盖 ATP 组合基线
2. 静态核对阶段 4 计划文档，确认 B1/B2/B3 与独立延时维度的重复定义已消除

---

## 043-20260516-011500 阶段4计划文档落地

**目的**：按项目流程先产出阶段 4 的执行前详细开发计划文档，明确树莓派程序层主导、ATP 状态机放在树莓派侧、默认不改底层模型的实施边界。

**修改者**：Codex

**修改内容**：
1. `docs/阶段4-算法基线建设/阶段4详细开发计划.md` — 新增阶段 4 详细开发计划，完整写明目标、范围、默认决策、任务拆分、涉及模块、风险点、验收标准和实施顺序
2. `docs/阶段4-算法基线建设/README.md` — 新增阶段 4 目录说明，明确当前目录用途与核心文档
3. `docs/低空场景无线光通信ATP开发文档.md` — 在阶段 4 标题下补充实施前详细计划文档路径，和前面阶段的文档入口保持一致

**验证**：静态核对阶段 1 实验输出规范、阶段 4 主文档定义和当前代码接口，确认计划文档内容与项目现状一致，且未越过“计划确认前不实施代码”的阶段边界。

---

## 042-20260516-005500 阶段3总评审收口

**目的**：对阶段3完整交付做总体评审，修复剩余实现风险并统一当前项目文档口径，为阶段4启动提供可信基线。

**修改者**：Codex

**修改内容**：
1. `entities/raspi/model.py` — 为 `buffer_policy` 增加合法值校验，非法策略明确报错，避免静默退化
2. `entities/raspi/entity.py` — `set_delay_profile()` 对 `queue_capacity` 和 `control_rate_hz` 做归一化处理，避免负值配置进入运行链路
3. `tests/test_delay_strategies.py` — 新增 2 个回归测试：非法 `buffer_policy` 报错、`set_delay_profile()` 对容量/采样率做归一化
4. `docs/低空场景无线光通信ATP开发文档.md` — 将“当前系统技术现状”从阶段2前旧口径更新为阶段3完成后的真实状态，避免后续阶段被旧描述误导
5. `README.md`、`entities/raspi/README.md`、`entities/camera/README.md`、`entities/raspi/control_program.py` — 同步更新阶段3后的观测模式、延时策略、航点示例和 `optional_gt` 可见性说明

**验证**：
1. `conda run -n simulation python -m unittest tests.test_delay_strategies tests.test_digital_twin_runtime tests.test_obs_filter -v` 通过（40/40）
2. `conda run -n simulation python -m unittest discover -s tests -v` 通过（110/110）
3. `conda run -n simulation python app.py --no-gui --mode offline --duration 1.0` 通过
4. `conda run -n simulation python app.py --no-gui --mode offline --duration 2.0 --obs-mode research` 通过
5. `conda run -n simulation python app.py --no-gui --mode offline --duration 2.0 --obs-mode realistic` 通过

---

## 041-20260515-224800 轮B审阅修复：近真实测量值接线与延时策略更新

**目的**：审阅阶段3轮B落地结果时，修复近真实模式未真正使用量化测量值的问题，并修复延时配置更新对新增策略字段支持不完整的问题。

**修改者**：Codex

**修改内容**：
1. `runtime/digital_twin_runtime.py` — realistic 模式下，runtime 在传给 `ObsFilter` 前显式获取 `gimbal.get_measured_state()`，并补上 `mode` 字段，确保近真实模式真正读取量化后的云台角度而不是连续内部值
2. `entities/raspi/entity.py` — `set_delay_profile()` 按字段实际类型更新配置，支持 `buffer_policy`（字符串）、`queue_capacity`（整数）、`control_rate_hz`（浮点）；更新后重建 `RaspiDelayModel` 并重置控制节拍
3. `tests/test_digital_twin_runtime.py` — 新增回归测试，验证 realistic 模式下控制程序收到的是量化测量值
4. `tests/test_delay_strategies.py` — 新增回归测试，验证 `set_delay_profile()` 可以正确切换 `buffer_policy/queue_capacity/control_rate_hz`

**验证**：`conda run -n simulation python -m unittest tests.test_digital_twin_runtime tests.test_delay_strategies -v` 通过（17/17）。

---

## 040-20260516-001500 阶段3轮B实施：执行器真实性+延时策略

**目的**：实现阶段3轮B，为云台添加编码器量化、静摩擦死区、参数偏差三项非理想行为，并扩展延时模型支持有限队列和多速率采样。

**修改者**：Claude Code

**修改内容**：
1. `config.py` — GimbalConfig新增3个参数（encoder_resolution_deg, static_friction_threshold_dps, tau_deviation_ratio）；RaspiDelayConfig新增3个参数（buffer_policy, queue_capacity, control_rate_hz）
2. `entities/gimbal/model.py` — 静摩擦死区（静止时低速率命令被吸收）+ 参数偏差（tau初始化时随机偏差，运行中不变）
3. `entities/gimbal/entity.py` — 新增get_measured_state()方法，返回编码器量化后的角度值，不影响get_state()的连续值
4. `entities/raspi/model.py` — 改造RaspiDelayModel支持latest/fifo两种缓冲策略；fifo模式维护有限队列，队列满时丢弃最旧帧
5. `entities/raspi/entity.py` — 多速率控制：control_rate_hz>0时只在控制tick接受新观测；pipeline_backlog_len包含队列长度
6. `tests/test_gimbal_nonideal.py` — 新增13个测试（编码器量化 4+静摩擦 5+参数偏差 4）
7. `tests/test_delay_strategies.py` — 新增13个测试（latest策略 4+fifo策略 5+多速率 4）

**验证**：全量106个测试通过（原80+新增26），冒烟测试通过，默认参数下行为不变（向后兼容）。

---

## 039-20260515-223800 轮A审阅修复：obs_filter 真值泄漏与空帧兼容

**目的**：审阅阶段3轮A落地结果时，修复 obs_filter 在研究/近真实模式下仍可能透出 `frame.optional_gt` 的问题，并修复空帧被错误替换为 `{}` 的兼容性问题。

**修改者**：Codex

**修改内容**：
1. `simulation/obs_filter.py` — research / realistic 模式下复制 `FramePacket` 时显式清空 `optional_gt`，避免通过 `frame` 继续泄漏真值投影；同时保留 `image` 和 `intrinsics` 的独立副本
2. `simulation/obs_filter.py` — `frame is None` 时保持返回 `None`，不再替换为空字典，避免下游把“无帧”误当成“有对象但缺字段”
3. `tests/test_obs_filter.py` — 新增 3 个回归测试：research 去除 `frame.optional_gt`、realistic 去除 `frame.optional_gt`、realistic 保持 `frame=None`

**验证**：`conda run -n simulation python -m unittest tests.test_obs_filter -v` 通过（21/21）。

---

## 038-20260515-233000 阶段3轮A实施：感知真实性+obs_filter

**目的**：实现阶段3轮A，为平台增加距离相关成像、亮度变化、偶发丢检三项感知真实性因素，以及obs_filter三模式控制器输入分离。

**修改者**：Claude Code

**修改内容**：
1. `config.py` — CameraConfig新增6个近真实参数（sigma_ref_distance_m, brightness_base, brightness_ref_distance_m, brightness_jitter_std, miss_detection_base_rate, miss_sigma_gain_px）；新增ObsConfig（obs_mode, encoder_noise_std_deg, gyro_noise_std_dps）+ obs_cfg单例
2. `entities/camera/model.py` — render_beacon_frame增加distance_m参数，实现距离相关sigma（sigma_base/(1+d/ref)）、亮度衰减（brightness_base/(1+d/ref) + jitter）、偶发丢检（跳过blob渲染，输出低于检测阈值的背景帧）
3. `entities/camera/entity.py` — _render_frame传递distance_m；update()中计算3D距离sqrt(x²+y²+z²)
4. `simulation/obs_filter.py` — 新建ObsFilter类，实现debug（透传）/research（白名单过滤）/realistic（噪声注入+白名单）三种观测模式
5. `runtime/digital_twin_runtime.py` — __init__接受obs_filter参数；step()中world_obs经obs_filter过滤后再传给raspi
6. `simulation/bootstrap.py` — build_runtime()接受obs_mode参数，创建ObsFilter传给Runtime
7. `simulation/types.py` — AppConfig增加obs_mode字段
8. `simulation/cli.py` — CLI增加--obs-mode参数（debug/research/realistic）
9. `simulation/headless.py` — 传递obs_mode给build_runtime()
10. `simulation/gui/window.py` — GUI透传obs_mode
11. `tools/record_session.py` — 录制工具兼容obs_mode
12. `tests/test_near_real_imaging.py` — 新增12个测试（距离sigma 3+亮度变化 4+丢检 5）
13. `tests/test_obs_filter.py` — 新增18个测试（debug 2+research 5+realistic 9+校验 2）

**验证**：全量77个测试通过（原47+新增30），三种obs_mode冒烟测试通过（debug/research/realistic），默认参数下行为不变（向后兼容）。

---

## 037-20260515-220200 阶段3计划落地边界补严

**目的**：对阶段 3 计划做进一步落地性检查，补上两处实施时容易踩坑的边界约束。

**修改者**：Codex

**修改内容**：
1. `docs/阶段3-近真实建模/阶段3详细开发计划.md` — 明确 realistic 模式若要读取量化后的云台测量值，必须由 runtime 单独提供 measured state 或让 obs_filter 显式取用，不能把普通 `world_obs` 过滤一遍就“变出”量化测量值；同时给出推荐做法：由 runtime 额外传入 measured state，保持 obs_filter 只做观测整形
2. `docs/阶段3-近真实建模/阶段3详细开发计划.md` — 收紧丢检帧定义：跳过 blob 渲染后输出的应是低于检测阈值的背景帧，而不是任意纯噪声帧，避免把“漏检模拟”误做成随机误检；同步补充测试和风险控制要求

**验证**：静态复核计划文本与现有 runtime / gimbal / camera 结构，确认新增约束能消除实现歧义，且未改变阶段边界。

---

## 036-20260515-223000 阶段3计划二次优化

**目的**：对 Codex 审阅后的阶段 3 计划进行二次审阅，补充实施细节。

**修改者**：Claude Code

**修改内容**：
1. `docs/阶段3-近真实建模/阶段3详细开发计划.md` — 明确丢检实现为"跳过 blob 渲染输出纯噪声帧"，而非在检测层伪造结果
2. `docs/阶段3-近真实建模/阶段3详细开发计划.md` — 新增 `get_measured_state()` 模式：编码器量化作用于独立输出路径，debug 模式保持连续值不变，realistic 模式读量化值再叠加噪声
3. `docs/阶段3-近真实建模/阶段3详细开发计划.md` — 更新 realistic 模式字段描述，明确量化值来源

**验证**：静态审阅，确认与 Codex 修订内容无冲突，且解决了 debug/research/realistic 三模式对 gimbal 状态的分层读取问题。

---

## 035-20260515-214500 阶段3计划评审修订

**目的**：审阅阶段 3 详细开发计划，修正其中会误导后续实施的设计问题，保证计划可直接作为实施依据。

**修改者**：Codex

**修改内容**：
1. `docs/阶段3-近真实建模/阶段3详细开发计划.md` — 修正丢检方案：不再在相机层伪造检测结果，改为把丢检落到图像不可检出这一层；同时修正原草案里“sigma 越小却按 sigma 正比增加概率”的方向错误
2. `docs/阶段3-近真实建模/阶段3详细开发计划.md` — 调整配置归属：成像相关参数改归 `CameraConfig`，观测过滤相关参数改为独立配置块，避免混塞进 `SceneConfig`
3. `docs/阶段3-近真实建模/阶段3详细开发计划.md` — 补齐 `obs_mode` 启动链路与兼容性要求，明确 CLI、headless、GUI、录制工具都需要同步打通
4. `docs/阶段3-近真实建模/阶段3详细开发计划.md` — 修正轮 B 若干不稳妥点：区分缓存策略与容量、明确 `control_rate_hz` 默认语义、强调观测噪声与编码器量化不要重复叠加

**验证**：静态复核阶段 1 冻结文档、当前代码结构和阶段 3 计划内容，确认修订后前后口径一致，且未越过“计划确认前不实施代码”的阶段边界。

---

## 034-20260515-211050 阶段2文档全面收口

**目的**：更新 README.md 和 generate_doc.js 中残留的 2D/单轴描述，与阶段2实际代码一致。

**修改者**：Claude Code

**修改内容**：
1. `README.md` — 架构图更新为 3D 双轴描述（TargetState 含 z_m/azimuth_deg/elevation_deg，Gimbal 含 pitch_deg），数据流补充 beta/v 投影公式，闭环路径改为双轴，自定义模板改为双轴控制，维护约定中 TargetKinematics2D→TargetKinematics3D
2. `docs/generate_doc.js` — TargetKinematics2D→TargetKinematics3D，step() 返回 (x,y,z)，运动模式公式增加 z 维度，派生属性增加 elevation_deg/bearing_deg 别名/3D distance

**验证**：纯文档更新

---

## 033-20260515-204839 阶段2航点帮助文案收口

**目的**：修复阶段 2 完成后仍残留的旧航点帮助文案，避免用户继续按 2D/3 元组提示输入参数。

**修改者**：Codex

**修改内容**：
1. `simulation/cli.py` — `--waypoints` 帮助文案更新为 4 元组主格式 `(x,y,z,speed)`，同时明确仍兼容旧 3 元组格式 `(x,y,speed)`
2. `tools/record_session.py` — `--waypoints` 帮助文案同步更新，和 headless 解析逻辑保持一致

**验证**：静态核对帮助文案与 `simulation/headless.py` 当前解析规则一致；后续通过 `--help` 命令确认用户可见提示已更新。

---

## 032-20260515-203744 阶段2 Codex二次审阅收尾

**目的**：修复 Codex 二次审阅发现的 3 处问题。

**修改者**：Claude Code

**修改内容**：
1. `tools/target_preview.py` — 升级为 3D 双轴预览：新增俯仰角曲线、3D 距离、双轴 FOV 判断、z/vz 显示
2. `simulation/types.py` + `tools/record_session.py` — 航点提示文案从 `(x,y,speed)` 更新为 `(x,y,z,speed)`
3. `entities/raspi/tests/test_tracker_program.py` — 新增 6 个纵向控制测试（pitch_rate 正负号、deadband、限幅、丢目标 hold、yaw/pitch 独立性）

**验证**：230 实体测试 + 冒烟测试通过

---

## 031-20260515-195735 阶段2 Codex审阅收尾修正

**目的**：修复 Codex 审阅发现的3处问题。

**修改者**：Claude Code

**修改内容**：
1. `entities/target/entity.py` — 初始 TargetState 的 bearing_deg 和速度字段现在从 model 读取，不再使用默认值 0.0
2. `tests/test_e2e_2axis.py` — 增加 setUpClass/tearDownClass 保存并恢复全局 target_cfg，消除测试顺序依赖
3. `simulation/headless.py` — 2 元组航点格式不再静默接受，改为明确报错

**验证**：64 target 测试 + 6 e2e 2axis 测试 + 冒烟测试全部通过

---

## 030-20260515-192726 阶段2双轴ATP升级实施

**目的**：将系统从 2D 单轴原型升级为 3D 双轴 ATP 几何与控制底座。

**修改者**：Claude Code

**修改内容**：
1. `entities/target/model.py` — TargetKinematics2D→TargetKinematics3D，新增 z/vz 状态、elevation_deg 属性、3D distance、bearing_deg 别名
2. `entities/target/entity.py` — TargetState 增加 z_m/azimuth_deg/elevation_deg/vz_mps 字段
3. `entities/target/__init__.py` — 导出 TargetKinematics3D，保留 TargetKinematics2D 别名
4. `entities/camera/model.py` — render_beacon_frame 签名扩展（alpha+beta），v=cy-f_px*tan(beta)，双轴 FOV 判断
5. `entities/camera/entity.py` — beta 角计算，真实 v_px 投影
6. `entities/raspi/tracker_program.py` — 双轴控制输出，pitch_rate 由像素误差驱动
7. `config.py` — TargetConfig 增加 z 参数，CameraConfig 增加 fov_v_deg，TrackerTuningConfig 增加 pitch 参数
8. `simulation/headless.py` — 航点解析支持 (x,y,z,speed) 格式
9. `runtime/types.py` — WorldSnapshot.target 字段注释更新
10. `entities/raspi/control_program.py` — Protocol 文档更新
11. `tools/target_preview.py` — 导入更新
12. `tools/replay_session.py` — CSV 字段扩展
13. 新增 `docs/阶段2-双轴ATP升级/坐标系定义.md`
14. 新增 `tests/test_2axis_geometry.py`（25个双轴几何测试）
15. 新增 `tests/test_e2e_2axis.py`（6个双轴闭环测试）

**验证**：224 单元测试 + 16 集成测试 + 25 双轴几何测试 + 6 双轴闭环测试全部通过，冒烟测试闭环正常

---

## 029-20260515-200000 阶段2工具文件适配修复

**目的**：修复阶段2核心代码改动（TargetKinematics3D重命名、target新增z_m/azimuth_deg/elevation_deg/vz_mps字段、camera真实v_px、TrackerTuning新增pitch字段）后受影响的工具文件和测试。

**修改者**：Claude Code

**修改内容**：
1. `entities/raspi/control_program.py` — Protocol文档字符串补充 target 新字段（z_m, azimuth_deg, elevation_deg, vz_mps）
2. `runtime/types.py` — WorldSnapshot target 注释补充 z_m, azimuth_deg, elevation_deg, vz_mps
3. `tools/target_preview.py` — 导入从 TargetKinematics2D 更新为 TargetKinematics3D
4. `tools/replay_session.py` — CSV回放时补充读取 target 新字段（z_m, azimuth_deg, elevation_deg, vz_mps）
5. `entities/raspi/tests/test_tracker_program.py` — _Frame 模拟类补充 cy 参数，修复 pitch 轴跟踪代码读取 intrinsics["cy"] 的 KeyError

**验证**：
- 冒烟测试通过：`python app.py --no-gui --mode offline --duration 1.0`
- 224 单元测试全部通过
- 16 集成测试全部通过

---

## 028-20260515-183223 阶段2计划Codex二次修订同步修正

**目的**：同步修正 Codex 027 修订后的残留不一致。

**修改者**：Claude Code

**修改内容**：
1. `docs/阶段2-双轴ATP升级/阶段2详细开发计划.md` §5.1 文件总览表中 camera/model.py 说明从旧公式 `v = f_px*tan(beta)+cy` 修正为 `v = cy - f_px*tan(beta)`，与任务3和任务5中的公式一致
2. 补充二次修订记录

**验证**：纯文档修订，公式符号与任务3:110、任务5:170 保持一致

---

## 027-20260515-182416 阶段2计划方向口径统一修订

**目的**：修复阶段 2 计划文档里“上下投影公式”和“前后方向命名”两处仍会引发误解的口径冲突，避免后续实施时把俯仰方向或主方向测试写反。

**修改者**：Codex

**修改内容**：

1. **systemSimulation/docs/阶段2-双轴ATP升级/阶段2详细开发计划.md** —
   - 将垂直投影公式统一为 `v = cy - f×tan(beta)`，使其与“beta>0 表示目标在上方、pitch 向上为正”的文字规则完全一致
   - 补充“文档、公式、测试三处必须一致”的约束语句，减少后续实现歧义
   - 将“正前方/正后方”等带主观含义的命名改为 `+x/-x/+y/-y` 与“上仰/下俯”方向命名
   - 将坐标示例改为 4 个水平主方向数值示例，避免继续把“前向”与 azimuth 零位混用
   - 同步更新几何测试和纵向专项测试中的方向描述与公式表述

**验证**：已逐段静态复核阶段 2 计划文档，确认投影公式、图像坐标规则、pitch 正负关系、方向命名和验收条件前后一致；本次仅文档修订，未运行程序。

---

## 026-20260515-135650 阶段2计划Codex审阅修订

**目的**：根据 Codex 审阅反馈修订阶段2详细开发计划，修正坐标角定义冲突、补全受影响文件范围、加硬验收命令。

**修改者**：Claude Code

**修改内容**：
1. 修正 azimuth 公式：从 `atan2(x,y)` 改为 `atan2(y,x)`，与现有代码 `bearing_deg = atan2(y,x)` 一致
2. 补全受影响文件范围：新增三档分类清单（必须改7个、大概率要改10个、只需核对7个）
3. 补全纵向方向规则：图像 v 向下增、目标在上方时 pitch 应向上、补 3 个纵向专项测试
4. 统一文件路径：所有任务中路径改为仓库真实路径（entities/、simulation/、tools/）
5. 补 CameraConfig 垂直 FOV 说明：`fov_v_deg` 计算公式写入任务 3
6. 统一方位测试：基础六类（前/后/左/右/上/下）+ 斜向补充类
7. 加硬验收命令清单：新增 §8.3 必跑验收清单
8. 补 2D 别名保留策略：`TargetKinematics2D` 别名保留至阶段4结束
9. 补 CHANGELOG 收尾任务写入任务 6
10. 修正实验输出影响说明：`v_px` 含义变化、旧脚本需复核

**涉及文件**：
- `docs/阶段2-双轴ATP升级/阶段2详细开发计划.md`（主要修订）

**验证**：纯文档修订，无需代码验证

---

## 025-20260515-131523 阶段2详细开发计划建档

**目的**：根据阶段执行前置闸门规则，在阶段2实施前先产出详细开发计划文档。

**修改者**：Claude Code

**修改内容**：

1. **docs/阶段2-双轴ATP升级/阶段2详细开发计划.md** — 新增阶段2执行前计划文档，明确6个任务（坐标系文档→3D目标→双轴相机→双轴控制→测试→文档更新）、涉及文件总览、风险控制、兼容策略和闸门条件

**验证**：仅新增计划文档，未开始阶段2实施。

---

## 024-20260515-130821 阶段1 Codex审阅修正

**目的**：修正 Codex 对阶段1收口文档审阅发现的3处不一致。

**修改者**：Claude Code

**修改内容**：

1. **阶段1场景矩阵与工况定义.md** — B1标准组合的机动强度从M1修正为M2（sinusoidal=M2，与§7.4定义一致）
2. **低空场景无线光通信ATP开发文档.md** — dataclass数量从"9个"修正为"11个"，与阶段0研究基线配置和阶段1实验输出规范一致
3. **阶段1详细开发计划.md** — 文档头部状态从"已确认，执行中"改为"阶段已完成，已冻结"，与正文§10结论一致

**验证**：纯文档一致性修正，无代码变更。

---

## 023-20260515-113239 阶段1评审通过并冻结

**目的**：完成阶段1「问题定义冻结」的全部评审验证，勾选闸门，冻结文档状态，更新主开发文档。

**修改者**：Claude Code

**修改内容**：

1. **阶段1评审清单.md** — 全部34项checkbox勾选通过（§2.1-2.8共28项 + §3.1闸门4项 + §3.2加固项3项 - 1重复 = 实际28检查项+7判定项），状态更新为"已冻结（2026-05-15 评审通过）"
2. **阶段1问题定义文档.md** — 状态从"执行中"更新为"正式冻结文档（2026-05-15 评审通过）"
3. **阶段1场景矩阵与工况定义.md** — 同上
4. **阶段1指标体系与判定规则.md** — 同上
5. **阶段1观测模式与输入边界.md** — 同上
6. **阶段1实验输出规范.md** — 同上
7. **阶段1详细开发计划.md** — 执行状态更新为"阶段 1 已完成，全部闸门已通过，状态已冻结"
8. **低空场景无线光通信ATP开发文档.md** — 阶段1状态改为🟢已完成，闸门4项全部勾选，当前活跃阶段指向阶段2

**验证**：

1. 双Agent并行验证评审清单全部34项，结果全部通过
2. 6份产出文档状态已统一为"正式冻结文档"
3. ATP主文档阶段1状态、闸门、活跃阶段指针已同步更新

---

## 022-20260515-100016 阶段1 Codex二轮修改审阅修正

**目的**：审阅 Codex CHANGELOG 021 的修改，修正3处遗漏。

**修改者**：Claude Code

**修改内容**：

1. **阶段1详细开发计划.md** — 任务1任务链补"通信保持（本轮仅接口预留）"，与问题定义文档和ATP主文档对齐
2. **阶段1观测模式与输入边界.md** — §5.5增加第4条：若阶段3实现时发现研究模式过严，可通过修订流程适当放宽个别字段，预留修订后路
3. **阶段1评审清单.md** — §2.4增加支持性指标（跟踪率、收敛时间、不发散判定）检查项

**验证**：

1. 计划文档、问题定义文档、ATP主文档三处任务链口径一致（6项含通信保持）
2. 观测模式研究模式白名单保持Codex收紧版本，同时预留了修订后路
3. 评审清单覆盖了核心指标和支持性指标两类

---

## 021-20260515-151500 阶段1文档边界与状态口径再收口

**目的**：根据最新复核结果，修正阶段 1 文档中仍然存在的输入边界放宽、任务链口径不一致、文档状态偏早和少量格式残留问题。

**修改者**：Codex

**修改内容**：

1. **docs/阶段1-问题定义冻结/阶段1观测模式与输入边界.md** — 收紧 `research` 模式白名单，改为与 ATP 主开发文档一致的 `frame + gimbal.mode + camera.f_current_mm`；其余 `gimbal` / `camera` 状态统一列入黑名单；补充与主开发文档一致性的说明
2. **docs/低空场景无线光通信ATP开发文档.md** — 阶段 1 任务链补入“通信保持（接口预留，不纳入本轮正式实验）”，与阶段 1 问题定义文档保持一致
3. **docs/阶段1-问题定义冻结/*.md（6 份正式产出文档）** — 文档状态统一从“正式冻结文档”调整为“阶段产出文档（执行中，待阶段评审后正式冻结）”，避免与阶段 1 当前“进行中”状态冲突
4. **docs/阶段1-问题定义冻结/阶段1详细开发计划.md** — 修正当前执行状态引号格式，清理审阅记录表格行尾格式残留
5. **docs/doc-structure.md** — 将“阶段1：详细开发计划”职责描述从“执行前”更新为“执行中”

**验证**：

1. `research` 模式白名单已与 ATP 主开发文档阶段 3 的目标口径对齐
2. 主开发文档与阶段 1 问题定义文档的任务链均包含“通信保持（接口预留）”
3. 阶段 1 产出文档状态已统一为“执行中待评审冻结”，不再与主开发文档的“进行中”状态冲突
4. 阶段 1 计划文档中的格式残留已清理

---

## 020-20260515-094708 阶段1文档审阅优化

**目的**：对 Codex 生成的 6 份阶段 1 文档进行全面审阅，修正不一致和遗漏问题。

**修改者**：Claude Code

**修改内容**：

1. **阶段1问题定义文档.md** — 补全任务链"通信保持"项（5.5节），与ATP主文档阶段1任务1保持一致
2. **阶段1场景矩阵与工况定义.md** — 新增§5编号体系说明（S/C/D/V/W/M/O/L/P/B五套编号的格式和引用规则）；B1组合补充阶段0基线配置对照说明
3. **阶段1指标体系与判定规则.md** — 稳态误差和峰值误差补全"计算窗口"参数（默认t≥3s）；通信指标§7增加ATP主文档§8.1引用依据，明确"下一轮实现"而非"阶段4"
4. **阶段1观测模式与输入边界.md** — 研究模式白名单补全具体gimbal/camera字段名（从WorldSnapshot类型定义提取）；黑名单增加`yaw_deg_internal`和`yaw_rate_ref_dps`
5. **阶段1实验输出规范.md** — CSV字段表增加指标编号列（A1-A6），与指标体系文档对齐
6. **阶段1评审清单.md** — 增加任务链完整性检查项
7. **阶段1详细开发计划.md** — 补充§11审阅与修订记录

**验证**：

1. 6份文档之间交叉引用一致（任务链、指标编号、字段名）
2. 通信指标边界与ATP主文档§8.1严格对齐（接口预留，本轮不验收）
3. 观测模式字段名与runtime/types.py中WorldSnapshot定义对齐

---

## 019-20260515-003500 阶段1正式执行与文档落地

**目的**：开始执行阶段 1「问题定义冻结」计划，把阶段 1 的正式产出文档全部落地，并统一主开发文档、导航文档和阶段计划文档的状态口径。

**修改者**：Codex

**修改内容**：

1. **docs/阶段1-问题定义冻结/阶段1详细开发计划.md** — 将阶段 1 计划文档更新为已确认、执行中版本，并补入依赖、风险、闸门与加固项口径
2. **docs/阶段1-问题定义冻结/阶段1问题定义文档.md** — 新增阶段 1 问题定义文档，固定平台定位、研究对象、任务链和本轮边界
3. **docs/阶段1-问题定义冻结/阶段1场景矩阵与工况定义.md** — 新增标准场景矩阵、工况分档、2D/3D 边界和配置映射文档
4. **docs/阶段1-问题定义冻结/阶段1指标体系与判定规则.md** — 新增 ATP 核心指标、通信接口指标、可计算性和阶段 0 基线锚点文档
5. **docs/阶段1-问题定义冻结/阶段1观测模式与输入边界.md** — 新增三种观测模式边界文档，明确阶段 1 只定义、不实现 `obs_filter`
6. **docs/阶段1-问题定义冻结/阶段1实验输出规范.md** — 新增统一输出字段、参数命名、目录结构和图表要求文档
7. **docs/阶段1-问题定义冻结/阶段1评审清单.md** — 新增阶段 1 收口检查与冻结后修订流程文档
8. **docs/低空场景无线光通信ATP开发文档.md** — 将阶段 1 状态从“计划已提交，待确认”更新为“进行中”
9. **docs/doc-structure.md** — 将阶段 1 的 6 份正式文档全部接入文档导航

**验证**：

1. 阶段 1 目录下已存在 7 份文档（1 份执行文档 + 6 份正式产出文档）
2. 主开发文档、阶段 1 执行文档、文档导航三者的阶段 1 状态与引用关系保持一致
3. 文档内容已覆盖：阶段 0 基线锚点、2D/3D 场景边界、通信指标接口预留、观测模式实现边界、统一输出规范

---

## 018-20260514-234418 阶段0补充整改（全仓文档一致性收口）

**目的**：根据 Codex 补充整改清单，对全仓库文档做一次性统一收口，消除代码现状与文档之间的所有历史差异。

**修改者**：Claude Code

**修改内容**：

1. **entities/raspi/README.md** — 全面重写延时管线描述（三级堆→单槽忙/闲状态机），修正 RaspiDelayConfig 默认值（5个参数），修正 Kp（0.08→1.1），修正 tick 处理流程，标记 DelayPipeline 为遗留代码，测试命令加 conda 前缀
2. **CLAUDE.md** — 延时模型描述改为单槽忙/闲模型，测试命令加 conda 前缀
3. **AGENTS.md** — 同 CLAUDE.md 修改
4. **README.md** — 延时模型描述改为单槽模型，测试计数改为 240（224+16），全部 python 命令加 conda 前缀，目录结构测试数修正
5. **docs/generate_doc.js** — 延时模型、Kp（0.08→1.1）、测试计数（232→240）、dataclass 数（10→11）、噪声 std（0.5→2.0）、延时默认值（0.02→0.015）、全部命令加 conda 前缀
6. **docs/使用手册.md** — 全部 python 命令加 conda 前缀
7. **docs/doc-structure.md** — Raspi 文档描述改为单槽忙/闲延时管线
8. **runtime/README.md** — 测试命令加 conda 前缀
9. **entities/target/README.md** — 测试命令加 conda 前缀
10. **entities/camera/README.md** — 测试命令加 conda 前缀
11. **entities/gimbal/README.md** — 测试命令加 conda 前缀

**验证**：

1. 全仓 grep 确认：活跃文档中无残留的"三级延时管线"描述
2. 全仓 grep 确认：活跃文档中无残留的 Kp=0.08 描述
3. 全仓 grep 确认：活跃文档中无残留的旧测试计数
4. 全部 `python` 命令已加 `conda run -n simulation` 前缀
5. 240 测试全部通过

---

## 017-20260514-234800 阶段1计划文档建档

**目的**：根据仓库当前的阶段执行前置规则，在不启动阶段 1 实施的前提下，先单独产出阶段 1 的详细开发计划文档，并完成归档与导航接入。

**修改者**：Codex

**修改内容**：

1. **docs/阶段1-问题定义冻结/阶段1详细开发计划.md** — 新增阶段 1 执行前计划文档，明确本阶段目标、不做事项、任务拆分、产物清单、风险点、完成标准和实施入口
2. **docs/doc-structure.md** — 新增阶段 1 详细计划文档导航，纳入阶段归档体系
3. **docs/低空场景无线光通信ATP开发文档.md** — 将阶段 1 状态更新为“计划已提交，待确认”，并加入详细计划文档引用

**验证**：

1. 文档新增路径符合阶段归档规范：`docs/阶段1-问题定义冻结/`
2. 当前仅新增阶段 1 计划文档与导航信息，未开始阶段 1 实施
3. 变更内容符合“执行前先出详细计划并等待确认”的仓库约束

---

## 016-20260514-231908 阶段0收尾修订（Codex问题修复）

**目的**：根据 Codex 对阶段 0 产出的复核问题（docs/阶段0-基线收口/阶段0问题与修订建议.md），完成 5 项收尾修订，确保文档口径一致、基线冻结完整、验证链稳定。

**修改者**：Claude Code

**修改内容**：

1. **docs/低空场景无线光通信ATP开发文档.md** — §1.1 测试覆盖率行更新为"已有基线 e2e 闭环测试"，§3 边界描述删除"无端到端闭环测试"旧表述
2. **docs/阶段0-基线收口/基线平台能力清单.md** — 测试数更新为 240（224+16），延时模型描述改为单槽忙/闲模型，删除所有"补齐中"旧状态
3. **baseline.py** — 补齐 YawDisplayConfig.default_mode 和 4 个 zoom 参数冻结字段，validate_baseline() 覆盖全部 11 个 dataclass
4. **docs/阶段0-基线收口/研究基线配置.md** — 新增 YawDisplayConfig 章节，补齐 zoom 参数行
5. **README.md** — 运行命令统一为 `conda run -n simulation`，延时模型描述同步为单槽模型
6. **baseline.py / tools/run_baseline.py** — 输出改为英文 + `sys.stdout.reconfigure(encoding="utf-8")` 修复 conda run GBK 编码异常
7. **CLAUDE.md** — 测试计数更新为 240（224+16）

**验证**：

1. `conda run -n simulation python baseline.py` — OK，无偏离，无编码错误
2. `conda run -n simulation python tools/run_baseline.py --duration 5` — OK，tracking_ratio=100%，无编码错误
3. `conda run -n simulation python -m unittest discover -s entities -v` — 224 tests OK
4. `conda run -n simulation python -m unittest discover -s tests -v` — 16 tests OK
5. 总计 240 测试全部通过

---

## 015-20260514-224800 阶段0文档归档整理

**目的**：将阶段 0 生成的文档统一收纳到 `docs` 下独立目录，作为后续阶段按目录归档的规范起点，方便管理与交接。

**修改者**：Codex

**修改内容**：

1. **docs/阶段0-基线收口/基线平台能力清单.md** — 将阶段 0 的能力清单文档移入独立归档目录
2. **docs/阶段0-基线收口/研究基线配置.md** — 将阶段 0 的基线配置文档移入独立归档目录
3. **docs/阶段0-基线收口/阶段0问题与修订建议.md** — 将阶段 0 的问题与建议文档移入独立归档目录
4. **docs/doc-structure.md** — 新增阶段文档归档约定，并更新阶段 0 三份文档的导航路径

**验证**：

1. 阶段 0 三份文档均已归档到 `docs/阶段0-基线收口/`
2. 文档导航路径已同步更新
3. 文档内部引用已同步到新路径

---

## 014-20260514-223300 阶段0问题清单文档补充

**目的**：将对阶段 0 完整性的复核结果整理成独立文档，供 Claude Code 后续二次审查并据此收尾实施。

**修改者**：Codex

**修改内容**：

1. **docs/阶段0问题与修订建议.md** — 新增阶段 0 问题清单文档，汇总当前存在的问题、影响、修订建议、建议处理顺序和后续交付标准
2. **docs/doc-structure.md** — 新增该文档的导航入口，方便后续从 docs 中直接查找

**验证**：

1. 阶段 0 问题文档已写入 docs 目录
2. 文档导航已更新，可从文档体系中找到该文档

---

## 013-20260514-221400 阶段执行前置闸门规则补充

**目的**：在仓库级协作规则中增加“阶段执行前必须先提交详细阶段计划并等待用户确认”的约束，避免在 ATP 开发过程中跳过阶段计划直接进入实施。

**修改者**：Codex

**修改内容**：

1. **AGENTS.md** — 新增“阶段执行前置闸门”规则，要求进入某个开发阶段前，必须先单独产出该阶段的详细开发计划文档并等待用户确认
2. **CLAUDE.md** — 同步新增相同规则，约束 Claude Code 在阶段执行前先提交详细阶段计划

**验证**：

1. 已确认 AGENTS.md 与 CLAUDE.md 均写入相同规则
2. 规则文本已明确“未确认前不得开始代码、配置、测试和结构修改”

---

## 012-20260514-220918 Phase 0 基线收口

**目的**：将当前系统整理成可复现的研究基线，完成 ATP 开发阶段 0 的全部闸门条件。

**修改者**：Claude Code

**修改内容**：

1. **docs/基线平台能力清单.md** — 新增当前平台真实能力文档：已具备能力（逐实体）、当前限制（10 项）、已修复问题（7 项）、待修复问题（7 项）、结构性限制（5 项）、测试现状
2. **docs/研究基线配置.md** — 新增研究基线配置冻结文档：11 个 config dataclass 的全部默认值、基线实验条件
3. **baseline.py** — 新增基线配置快照模块：BaselineConfig frozen dataclass + get_baseline_config() + validate_baseline()
4. **tests/test_e2e_baseline.py** — 新增端到端闭环基线测试（8 个测试用例）：验证跟踪率 ≥90%、角度 RMS <2.0°、峰值 <5.0°、无发散、像素 RMS <50px、宏观指标可复现；含 20ms 延时闭环测试
5. **tools/run_baseline.py** — 新增基线实验运行工具：输出 JSON 格式的基线结果（含配置快照、指标、时间序列）
6. **output/baseline_results.json** — 基线实验结果归档（跟踪率 100%、角度 RMS 0.276°、像素 RMS 7.7px、无发散）
7. **docs/doc-structure.md** — 新增"基线平台能力清单"和"研究基线配置"两个导航条目和知识归属
8. **README.md** — 更新测试章节：新增 §9.3 端到端闭环基线测试说明；更新测试计数和目录结构
9. **docs/低空场景无线光通信ATP开发文档.md** — 阶段 0 状态更新为 🟢 已完成；4 项闸门全部勾选；当前活跃阶段指向阶段 1

**验证**：
1. 224 单元测试全部通过（conda run -n simulation）
2. 16 集成测试（含 8 个新 e2e 测试）全部通过（conda run -n simulation）
3. `conda run -n simulation python tools/run_baseline.py` 输出确定性 JSON 结果
4. `conda run -n simulation python baseline.py` 确认无配置偏离
5. ATP 阶段 0 四项闸门全部满足
6. 发现并修复了 raspi_delay_cfg 模块级单例被前置测试污染导致 e2e 测试不稳定的问题

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
