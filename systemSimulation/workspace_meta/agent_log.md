# AI Agent 协作日志

本文件记录 Claude Code 与 Codex 对项目的所有修改、建议与决策。
两个 agent 每次操作后必须追加记录，防止记忆冲突和修改分歧。

## 使用约定

- 每条记录包含：时间戳、Agent 标识、操作类型、涉及文件、变更说明、影响范围、验证方式
- 按时间倒序排列（最新记录在最上方）
- 操作类型：修改 / 新增 / 删除 / 建议 / 决策 / Bug修复
- 两个 agent（Claude Code、Codex）均有写义务

---

## 2026-04-24 清理旧链路 + 重设计 Config Editor

**Agent**: Claude Code
**操作类型**: 删除 + 修改 + 重写
**涉及文件**:
- 删除: models/ 整个目录（8 个文件）、workspace_meta/tmp_scripts/
- 修改: config.py（删除 PIDConfig、pid_cfg、DelayConfig、delay_cfg）
- 修改: tools/target_preview.py（models.target → entities.target.model）
- 修改: tools/camera_3d_viewer.py（models.camera_model → entities.camera.model）
- 重写: tools/config_editor.py（扁平表格 → 实体导航式 UI：左侧实体列表 + 右侧参数卡片）
- 修改: README.md（移除 models/ 目录，更新维护约定）
**变更说明**:
- 旧链路（models/、PIDConfig、DelayConfig）已完全清除，所有代码统一使用 entities/ 体系
- Config Editor 重设计为实体导航式：左侧 5 个实体按钮，右侧按配置组分卡片展示参数
- 每参数行内联显示名称+值+单位+一句话说明，点击展开完整详情（取值建议/影响范围）
**影响范围**: 向后不兼容（删除了 models/），但主线不依赖旧链路
**验证方式**: 220 个单元测试 + 6 个集成测试全通过，两个迁移工具编译通过

## 2026-04-24 README 更新 + 可视化测试命令

**Agent**: Claude Code
**操作类型**: 修改
**涉及文件**: README.md
**变更说明**:
- Section 2 快速开始：补充 `--control-program`、`--waypoints`、`--target-type` 三个新 CLI 参数示例
- Section 4.3 多种运行场景：补充航点轨迹 + 自定义控制程序 + 随机运动场景
- Section 5.3 新增"从命令行加载"小节
- Section 7 新增"可视化工具"（target_preview / camera_3d_viewer / record_session / replay_session）
- Section 9 运行与测试：更新为 220 个单元测试 + 6 个集成测试，补充各实体测试数量
- Section 11 目录结构：更新 tools/ 和 runtime/types.py 描述，标注测试数量
- Section 章节重编号：7→8→9→10→11→12
**影响范围**: 仅文档，不影响代码逻辑

## 2026-04-23 Phase 4: 数据录制 + 离线回放工具

**Agent**: Claude Code
**操作类型**: 新增
**涉及文件**:
- 新增: tools/record_session.py（仿真数据录制 → CSV）
- 新增: tools/replay_session.py（CSV 回放驱动控制程序测试）
**变更说明**:
- record_session: 运行仿真并将每个 tick 的 WorldSnapshot 展平为 CSV 行（支持 --control-program、--waypoints、--target-type 等参数）
- replay_session: 读取 CSV 还原 obs 字典，驱动控制程序 on_tick()，统计命令数并可选输出回放结果
- 两个工具配合使用：先录制参考数据，再用不同控制程序回放对比
**影响范围**: 仅新增工具，不影响现有代码
**验证方式**:
- record_session --duration 2 录制 400 行 CSV
- replay_session 无控制程序 → 0 cmds；用 BaselineTrackerProgram → 产生命令

## 2026-04-23 Phase 3: 配置系统清理

**Agent**: Claude Code
**操作类型**: 修改
**涉及文件**:
- 修改: runtime/types.py（新增 POWER_OFF/BOOTING/READY/FAULT 常量 + wrap_pm180 函数）
- 修改: simulation/types.py（wrap_pm180 改为从 runtime.types 导入）
- 修改: entities/gimbal/entity.py、entities/camera/entity.py、entities/raspi/entity.py（电源常量改为从 runtime.types 导入）
- 修改: entities/gimbal/control.py（wrap_pm180 改为从 runtime.types 导入，删除本地 _wrap_pm180 静态方法）
- 修改: entities/gimbal/__init__.py、entities/raspi/__init__.py（POWER_* 改从 runtime.types re-export）
- 修改: 3 个测试文件的 POWER_* 导入路径
- 修改: models/cascaded_controller_2axis.py、models/gimbal_plant_2axis.py（加 DeprecationWarning）
**变更说明**:
- 电源状态常量统一到 runtime/types.py，消除 3 个实体的重复定义
- wrap_pm180 统一到 runtime/types.py，gimbal/control.py 和 simulation/types.py 不再各自定义
- models/ 兼容层加 DeprecationWarning，引导用户迁移到 entities/ 模块
**影响范围**: 向后兼容，仅改导入路径；__init__.py 仍然 re-export POWER_* 常量
**验证方式**: 220 个单元测试 + 6 个集成测试全部通过

## 2026-04-23 Phase 2: 补全实体单元测试

**Agent**: Claude Code
**操作类型**: 修改
**涉及文件**:
- 重写: entities/target/tests/test_target_entity.py（1→64 测试）
- 重写: entities/gimbal/tests/test_gimbal_entity.py（1→63 测试）
- 重写: entities/camera/tests/test_camera_entity.py（1→67 测试）
- 重写: entities/raspi/tests/test_raspi_entity.py（1→26 测试）
**变更说明**:
- Target: 覆盖 5 种运动模式（constant_velocity/constant_accel/sinusoidal/random_walk/waypoint）+ bearing/distance + Entity 包装 + 边界条件
- Gimbal: 覆盖电源状态机 + NOT_READY 拒绝 + ANGLE_MODE/RATE_MODE 跟踪 + pitch 限位 + yaw wrap + 一阶响应 + 模式切换
- Camera: 覆盖电源状态机 + zoom target/rate/continuity + 成像模型(FOV/像素映射) + detect_beacon_centroid + Frame 生成
- Raspi: 覆盖电源状态机 + 控制程序加载 + 零延迟/有延迟 pipeline + Noop/自定义程序 + backlog + delay profile
**影响范围**: 仅测试代码，不影响任何生产逻辑
**验证方式**: 220 个单元测试全部通过 + 6 个集成测试全部通过，无回归

## 2026-04-23 Phase 1: 控制程序注入 + 航点轨迹 + 类型定义

**Agent**: Claude Code
**操作类型**: 修改 + 新增
**涉及文件**:
- 修改: simulation/bootstrap.py（`build_runtime`/`start_stack` 增加 `control_program` 参数，新增 `load_control_program_from_path()`）
- 修改: simulation/cli.py（增加 `--control-program`、`--target-type`、`--waypoints` CLI 参数）
- 修改: simulation/types.py（AppConfig 增加 control_program_path、target_type、waypoints 字段）
- 修改: simulation/headless.py（全量改写：公开 `apply_target_overrides()`、航点解析、控制程序注入）
- 修改: simulation/gui/runner.py（调用 `apply_target_overrides()`）
- 修改: simulation/gui/window.py（传递 control_program 到 build_runtime）
- 修改: config.py（TargetConfig 增加 waypoints、waypoint_arrival_radius_m）
- 修改: entities/target/model.py（增加 waypoint 运动模式；sinusoidal 模式补算 vx/vy）
- 修改: runtime/types.py（新增 GIMBAL_COMMANDS/CAMERA_COMMANDS/RASPI_COMMANDS/ALL_COMMANDS 命令目录）
- 修改: entities/raspi/control_program.py（Protocol docstring 补全完整 obs 结构和合法 Command 文档）
**变更说明**:
- 控制程序现在可以通过 CLI `--control-program module:Class` 或 `build_runtime(control_program=...)` 注入，无需修改 bootstrap 源码
- 目标轨迹支持 waypoint 航点导航模式，CLI `--waypoints "(x1,y1,s1),(x2,y2,s2)"` 可直接使用
- runtime/types.py 提供完整命令目录 ALL_COMMANDS，control_program.py 有完整 obs 字段文档
**影响范围**: 所有修改向后兼容——不传新参数时行为与改动前完全一致
**验证方式**:
- 8 个修改文件全部 py_compile 通过
- 6 个现有单元测试全部 OK
- build_runtime() 默认行为正常
- NoopControlProgram 注入验证通过
- waypoint 轨迹运行正常（200步后目标位置符合预期）

## 2026-04-22 实体文档体系 + README 重组

**Agent**: Claude Code
**操作类型**: 新增 + 修改
**涉及文件**:
- 新增: runtime/README.md, entities/target/README.md, entities/gimbal/README.md, entities/camera/README.md, entities/raspi/README.md, docs/doc-structure.md
- 修改: README.md（全量改写，聚焦实体间组合使用）, docs/使用手册.md（精简，删除与 README 重复的组装内容，加导航块）
**变更说明**: 建立完整的实体文档体系。每个实体有独立 README 讲透内部机制（状态机、配置参数表、模型原理、数据流、Client API、调试排错、扩展点）。主 README 改为侧重实体间数据流和组合联调。新增 docs/doc-structure.md 作为导航页。精简使用手册，避免重复。
**影响范围**: 仅文档，不影响任何代码逻辑
**验证方式**: 所有文档间相对路径链接有效，参数表与 config.py 实际默认值一致

## 2026-04-22 创建协作日志文件

**Agent**: Claude Code
**操作类型**: 新增
**涉及文件**: workspace_meta/agent_log.md, workspace_meta/README.md
**变更说明**: 创建 AI Agent 协作日志文件，建立 Claude Code 与 Codex 的共享变更记录机制。同时更新 workspace_meta/README.md 添加 agent_log 说明。
**影响范围**: 仅文档，不影响任何代码逻辑
**验证方式**: 文件存在且格式正确
