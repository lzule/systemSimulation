## 2026-04-19 Iteration Batch

### Added
- models/gimbal_plant_2axis.py
  - Added two-axis plant state and step/update logic.
  - Enforced yaw continuous accumulation.
  - Enforced pitch limits [-135, +90].
  - Enforced axis rate saturation 60 deg/s.
- models/cascaded_controller_2axis.py
  - Added ANGLE_MODE and RATE_MODE.
  - Added 50 Hz angle outer loop (P).
  - Added 200 Hz rate inner loop (PI).
  - Added latest-wins command cache for angle/rate targets.

### Modified
- config.py
  - Rewritten as UTF-8 clean config definitions.
  - Added AxisLimitConfig, LoopConfig, ControlPreset, YawDisplayConfig.
  - Added corresponding default singleton configs.
- simulation/sim_core.py
  - Replaced old single-axis PID+gimbal chain with new two-axis cascaded stack.
  - Added set_mode / set_angle_target / set_rate_target APIs.
  - Added get_state() API with timestamp and wrapped yaw display.
  - Extended SimState with new fields (yaw/pitch/rates/refs/mode/tick flags/timestamp).
  - Kept legacy fields (gimbal_angle_deg, gimbal_velocity_dps, pid_output_dps) for compatibility.
- models/__init__.py
  - Exported new plant/controller classes and mode constants.

### Verification
- simulation env compile check passed:
  - config.py
  - models/gimbal_plant_2axis.py
  - models/cascaded_controller_2axis.py
  - simulation/sim_core.py
- Runtime checks blocked in simulation env:
  - ModuleNotFoundError: numpy

### Open Issues
- `simulation` env currently lacks numpy, preventing runtime validation of full sim flow.
- camera_3d_viewer and GUI-path issues are out-of-scope in this batch and untouched.

## 2026-04-19 Iteration Batch (Follow-up Validation)

### Verification Updates
- Confirmed activation behavior in current terminal session:
  - `conda` marks `simulation` as active, but Python resolves to `C:\\Python314\\python.exe`.
  - `numpy` remains non-importable in that interpreter for this session.
- Added and executed runtime core validation script:
  - output/tmp_core_validate.py
  - Result: `core_validation_ok -140.0 -135.0 57.971 50`
  - Covered checks: yaw continuity, pitch hard limits, max rate saturation, latest-wins, loop tick cadence.
- Re-ran compile checks in activated simulation context:
  - config.py, models/gimbal_plant_2axis.py, models/cascaded_controller_2axis.py, simulation/sim_core.py
  - Result: pass.

### Open Issues
- Full `simulation.sim_core` import/runtime path remains blocked by numpy visibility in current activated Python process.
- Need one consistent interpreter binding where `simulation` activation resolves to the intended Python + site-packages.

## 2026-04-19 Iteration Batch (Full Runtime Closure)

### Verification Updates
- Verified activated simulation interpreter and numpy availability:
  - `python` -> `C:\\Users\\20163\\miniconda3\\envs\\simulation\\python.exe`
  - `numpy` -> `2.4.4`
- Executed full sim runtime validation:
  - script: `output/tmp_simcore_validate.py`
  - result: `simcore_runtime_ok 90.747 -94.411 51 0`
  - checks passed:
    - `get_state()` contract fields
    - RATE_MODE motion and latest-wins behavior
    - pitch clamp behavior
    - ANGLE_MODE 50Hz tick cadence (~51/200)
    - RATE_MODE angle-tick bypass (0)

### Open Issues
- None for planned two-axis core/control/state implementation.

## 2026-04-19 Iteration Batch (Formal Testization)

### Added
- tests/test_gimbal_2axis_core.py
  - Covers plant/controller core behavior:
    - rate saturation
    - pitch hard limits
    - latest-wins semantics
    - ANGLE/RATE tick behavior
- tests/test_simcore_runtime.py
  - Covers simulator integration behavior:
    - `get_state()` contract fields
    - RATE mode yaw drive
    - pitch clamp in full sim path
    - latest-wins in full sim path
    - ANGLE 50Hz tick cadence and RATE bypass

### Verification
- Executed in simulation environment:
  - `python -m unittest discover -s tests -v`
- Result:
  - Ran 3 tests, all passed.

### Open Issues
- None.

## 2026-04-19 Iteration Batch (Controller Parameter Optimization)

### Modified
- config.py
  - Updated `ControlPreset` defaults from conservative values to optimized fast-response values:
    - angle_kp_yaw/pitch: `4.0 -> 14.0`
    - rate_kp_yaw/pitch: `0.9 -> 1.6`
    - rate_ki_yaw/pitch: `2.0 -> 5.0`

### Added (temporary analysis)
- output/tmp_param_search.py
  - Performed grid search over controller gains and scored rise/settle/overshoot/error metrics.
  - Top result selected: `akp=14`, `rkp=1.6`, `rki=5.0`.

### Verification
- Executed in simulation env:
  - `python output/tmp_param_search.py`
  - `python -m unittest discover -s tests -v`
- Result:
  - Parameter search completed.
  - All 3 tests passed after applying optimized defaults.

### Open Issues
- None.

## 2026-04-19 Iteration Batch (Directory Reorganization)

### Modified
- Reorganized workspace directories for clarity:
  - moved plan logs: `output/plan_logs/* -> workspace_meta/plan_logs/*`
  - moved temporary scripts: `output/tmp_*.py -> workspace_meta/tmp_scripts/*`
- Added `workspace_meta/README.md` with directory usage conventions.

### Output Folder Policy
- `output/` should contain runtime artifacts only (gif/png/etc).
- process logs and temporary scripts should not be placed under `output/`.

### Notes
- `output/tmp_pip/` still exists due filesystem permission restrictions on temporary lock directories.

## 2026-04-19 Iteration Batch (中文文档与可读性治理)

### Modified
- README.md
  - 全量重写为中文说明，覆盖当前两轴云台架构、运行方式、测试方式、目录职责、维护约定。
- workspace_meta/README.md
  - 全量改为中文目录规范说明。
- models/gimbal_plant_2axis.py
  - 增加中文类/方法注释与关键流程注释。
- models/cascaded_controller_2axis.py
  - 增加中文类/方法注释与控制流程注释（外环/内环/模式语义）。
- simulation/sim_core.py
  - 增加中文模块说明、接口说明、主循环流程注释与兼容字段说明。

### Verification
- Executed in simulation env:
  - `python -m unittest discover -s tests -v`
- Result:
  - Ran 3 tests, all passed.

### Open Issues
- None.

## 2026-04-19 Iteration Batch (Digital Twin Runtime + Raspi Delay Isolation)

### Added
- entities/__init__.py
- entities/camera/__init__.py
- entities/gimbal/__init__.py
- entities/raspi/__init__.py
- entities/target/__init__.py
- runtime/__init__.py
- tests/test_digital_twin_runtime.py

### Modified
- config.py
  - Added `RaspiConfig` and `RaspiDelayConfig` dataclasses.
  - Added singleton instances `raspi_cfg` and `raspi_delay_cfg`.
- entities/raspi/entity.py
  - Added `delay_metrics` in `RaspiState` and `get_state()` payload.
  - Exposed runtime-visible delay profile metrics for diagnostics.
- tools/config_editor.py
  - Rewritten as clean UTF-8 implementation.
  - Auto-discovers dataclass config instances and renders grouped editor tabs.
  - Supports typed validation and write-back to `config.py`.

### Verification
- Executed in simulation env:
  - `C:\Users\20163\miniconda3\envs\simulation\python.exe -m py_compile config.py runtime\digital_twin_runtime.py entities\raspi\entity.py tools\config_editor.py tests\test_digital_twin_runtime.py`
  - `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s tests -v`
- Result:
  - 5 tests passed, including new runtime delay/isolation tests.

### Open Issues
- None in this batch.

## 2026-04-19 Iteration Batch (Entity-oriented Modular Refactor + Runtime Entry Switch)

### Added
- entities/gimbal/model.py
- entities/gimbal/control.py
- entities/gimbal/client.py
- entities/camera/model.py
- entities/camera/control.py
- entities/camera/client.py
- entities/target/model.py
- entities/target/control.py
- entities/target/client.py
- entities/raspi/model.py
- entities/raspi/client.py
- entities/*/tests/test_*.py (camera/gimbal/target/raspi)
- tests/test_runtime_api.py

### Modified
- entities/gimbal/entity.py
  - Internal dependencies switched from `models/*` to local `entities/gimbal/*`.
- entities/camera/entity.py
  - Imaging/zoom logic switched to local `entities/camera/model.py` + `control.py`.
- entities/target/entity.py
  - Kinematics switched to local `entities/target/model.py`.
- entities/raspi/entity.py
  - Delay pipeline wrapped by local `RaspiDelayModel`.
- runtime/digital_twin_runtime.py
  - Client dependencies switched to entity-local client modules.
- runtime/clients.py
  - Reduced to re-export layer.
- runtime/__init__.py
  - Simplified to avoid circular imports.
- app.py
  - Replaced old sim_core-based app with runtime-based demo entry.
- simulation/__init__.py
  - Marked as legacy package; no longer imports sim_core by default.
- tests/test_gimbal_2axis_core.py
  - Import path switched to entities gimbal modules.

### Removed
- tests/test_simcore_runtime.py (old sim_core mainline test)

### Verification
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s tests -v` => pass
- entity-level tests in `entities/*/tests` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe app.py --duration 0.5 --mode offline` => pass

### Open Issues
- None blocking in this batch.

## 2026-04-19 Iteration Batch (Legacy Core Dedup + README Refresh)

### Modified
- models/gimbal_plant_2axis.py
  - Replaced duplicated implementation with compatibility wrapper to `entities.gimbal.model`.
- models/cascaded_controller_2axis.py
  - Replaced duplicated implementation with compatibility wrapper to `entities.gimbal.control`.
- models/__init__.py
  - Updated package export to document legacy role and import two-axis core from `entities.gimbal`.
- README.md
  - Rewritten to reflect current entity-oriented architecture and runtime-first entry.

### Verification
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s tests -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe app.py --duration 0.5 --mode offline` => pass

### Open Issues
- None.

## 2026-04-19 Iteration Batch (Remove simulation Legacy Path + Migrate PID Tuner)

### Added
- tests/test_pid_tuner_smoke.py
  - Smoke validates tuner run, output image generation, and non-zero yaw motion.

### Modified
- tools/pid_tuner.py
  - Reimplemented on top of `DigitalTwinRuntime` + `WorldSnapshot` stream.
  - Preserved CLI entry and output report generation (`output/pid_tuner.png`).
- README.md
  - Removed `simulation/` references; documented runtime-only mainline.

### Removed
- simulation/sim_core.py
- simulation/__init__.py
- workspace_meta/tmp_scripts/tmp_simcore_validate.py

### Verification
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s tests -v` => pass (6 tests)
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s entities\camera\tests -p 'test_*.py' -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s entities\gimbal\tests -p 'test_*.py' -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s entities\target\tests -p 'test_*.py' -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s entities\raspi\tests -p 'test_*.py' -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe tools\pid_tuner.py` => pass

### Open Issues
- None.

## 2026-04-19 Iteration Batch (PyQt5 Config Editor + Chinese Explanations)

### Modified
- tools/config_editor.py
  - Replaced tkinter implementation with PyQt5 GUI.
  - Added grouped parameter editor with columns: field/value/unit/chinese explanation.
  - Added derived-preview panel (FOV, f_px, px/deg, delay summary).
  - Kept dataclass auto-discovery and type-safe write-back to config.py.

### Verification
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m py_compile tools\config_editor.py` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -c "import tools.config_editor"` => pass

### Open Issues
- None.

## 2026-04-19 Iteration Batch (Config Editor 中文文案修复与可读性增强)

### Modified
- tools/config_editor.py
  - 全量重写为 UTF-8 中文文案，修复乱码字符串。
  - 维持 PyQt5 实现，统一字段/值/单位/中文解释四列表格。
  - 保留类型校验、派生参数预览、回写 config.py。

### Verification
- C:\Users\20163\miniconda3\envs\simulation\python.exe -m py_compile tools\config_editor.py => pass
- C:\Users\20163\miniconda3\envs\simulation\python.exe -c "import tools.config_editor" => pass

### Open Issues
- None.

## 2026-04-20 Iteration Batch (Config Editor 左表格右详情 + 兼容参数弱化)

### Modified
- tools/config_editor.py
  - 重构为左侧 QTableView 参数表 + 右侧参数详情/派生预览布局。
  - 新增筛选条（分组/关键词/仅看主线），默认隐藏兼容参数。
  - 引入分组与字段元数据（lifecycle/editable/used_by/risk_note），兼容参数默认弱化展示。
  - 兼容参数改动时增加二次确认（支持本会话不再提醒）。
  - 统一紧凑视觉规范（11pt 主字体、固定行高、列宽对齐、按钮右对齐）。
  - 清理并集中中文文案常量，避免界面乱码与散落文案。

### Verification
- C:\Users\20163\miniconda3\envs\simulation\python.exe -m py_compile tools\config_editor.py => pass
- C:\Users\20163\miniconda3\envs\simulation\python.exe -c "import tools.config_editor as ce; w=ce.ConfigEditorWindow; print('import_ok', bool(w))" => pass

### Open Issues
- 终端查看源码时仍可能因 PowerShell 代码页显示为乱码；文件本身已按 UTF-8 写入，GUI 内文案正常。

## 2026-04-20 Iteration Batch (Config Editor 表格居中微调)

### Modified
- tools/config_editor.py
  - 表格表头默认对齐改为居中。
  - 表格单元格（参数名/值/单位/分组/状态）统一居中显示。

### Verification
- C:\Users\20163\miniconda3\envs\simulation\python.exe -m py_compile tools\config_editor.py => pass

### Open Issues
- None.

## 2026-04-20 Iteration Batch (Raspi 跟踪模板 + 多实例联调脚本 + 中文说明)

### Added
- entities/raspi/tracker_program.py
  - 新增 BaselineTrackerProgram 与 TrackerTuning。
  - 实现观测帧检测 -> 像素误差 -> yaw 角速度命令（限幅）的基线控制模板。
  - 支持可选变焦控制与中文注释说明（时序、符号、latest-wins语义）。
- tools/run_raspi_tracking_demo.py
  - 新增端到端联调入口：创建 runtime、上电、等待 READY、加载 Raspi 程序、运行并输出指标。
- entities/raspi/tests/test_tracker_program.py
  - 新增跟踪模板单测，覆盖目标检测命令输出与丢失目标行为。

### Modified
- entities/raspi/control_program.py
  - 增加中文协议说明与 on_tick 输入输出契约注释。
- entities/raspi/__init__.py
  - 导出 BaselineTrackerProgram / TrackerTuning。
- README.md
  - 增加“如何串联各实例运行（Raspi 控制相机+云台）”中文章节。
  - 增加常见错误排查与推荐调试顺序。

### Verification
- C:\Users\20163\miniconda3\envs\simulation\python.exe -m py_compile entities\raspi\control_program.py entities\raspi\tracker_program.py tools\run_raspi_tracking_demo.py => pass
- C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s entities\raspi\tests -p "test_*.py" -v => pass
- C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s tests -v => pass
- C:\Users\20163\miniconda3\envs\simulation\python.exe tools\run_raspi_tracking_demo.py --duration 0.8 --mode offline => pass

### Open Issues
- None.

## 2026-04-20 Iteration Batch (恢复 app.py 主入口 + PyQt5 实时仪表盘)

### Added
- app.py
  - 恢复主入口并重建为完整实时仿真启动器。
  - 默认 realtime + GUI，支持 `--duration` / `--mode` / `--delay-ms` / `--no-gui`。
  - 默认使用 Raspi 闭环控制链路（加载 BaselineTrackerProgram）。
  - GUI 单大画布仪表盘：世界视图、相机画面、状态面板、性能曲线。
  - 提供 Start/Pause/Reset/保存快照/延时参数应用。

### Modified
- README.md
  - 增加“实时仪表盘（PyQt5）”章节与使用命令。
  - 增加常见问题与排查建议（黑屏、未READY、帧率、延时）。

### Verification
- C:\Users\20163\miniconda3\envs\simulation\python.exe -m py_compile app.py tools\run_raspi_tracking_demo.py entities\raspi\tracker_program.py => pass
- C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s entities\raspi\tests -p "test_*.py" -v => pass
- C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s tests -v => pass
- C:\Users\20163\miniconda3\envs\simulation\python.exe app.py --no-gui --mode offline --duration 0.8 => pass

### Open Issues
- GUI 长稳（5分钟）与 DPI 观感需你本机窗口环境实测确认。

## 2026-04-20 Iteration Batch (PyQtGraph 实时仪表盘收敛 + 中文乱码修复)

### Modified
- app.py
  - 重写为 `PyQt5 + pyqtgraph` 实时主入口，保留 `--mode / --duration / --delay-ms / --no-gui`。
  - 新增 `SimWorker(QThread) + UiStateBuffer`，将仿真推进与 UI 渲染解耦。
  - 实现双图像视角（相机原始帧 + Raspi 延时观测帧）并保留世界视图/曲线/状态面板。
  - 统一中文文案常量与字体回退链，修复 UI 中文乱码。
  - 增加快照保存、延时动态应用、Start/Pause/Reset 状态切换。
- entities/raspi/tracker_program.py
  - 修复中文 docstring 乱码，保留控制逻辑不变。
- README.md
  - 更新“实时仪表盘”章节为 `PyQt5 + pyqtgraph` 描述，补充双图像视角说明。

### Added
- None.

### Verification
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m py_compile app.py tools\run_raspi_tracking_demo.py entities\raspi\tracker_program.py` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s entities\raspi\tests -p "test_*.py" -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s tests -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe app.py --no-gui --mode offline --duration 1.0` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe app.py --no-gui --mode realtime --duration 2.0 --delay-ms 20` => pass

### Open Issues
- GUI 窗口模式（含 Start/Pause/Reset 手感、DPI 字体观感）仍需你本机图形桌面实测确认。

## 2026-04-20 Iteration Batch (Qt 原生实时仪表盘重构 + 学术风信息架构)

### Modified
- app.py
  - 重构为 Qt 原生仪表盘：中央主画布 + 右侧双视角 + 底部时间轴 + 诊断抽屉。
  - 保留 `SimWorker(QThread)` 与 UI 解耦刷新（约 30FPS）。
  - 世界视图加入角度误差显式标注与状态颜色提示。
  - 相机视角加入分辨率、主点、`u/v` 与 `du/dv` 叠加信息。
  - 核心状态卡改为键值网格，默认一屏显示关键字段（含 `angle_err`）。
  - 新增底部诊断抽屉（可展开）显示全量诊断文本。
  - 处理环境兼容：当无 `QtChart` 模块时仍可运行（时间轴改用 `QGraphicsView/QGraphicsScene` 实现）。
- README.md
  - 更新“实时仪表盘”章节为 Qt 原生布局说明与依赖说明。

### Added
- None.

### Verification
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m py_compile app.py` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s entities\raspi\tests -p "test_*.py" -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s tests -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe app.py --no-gui --mode offline --duration 1.0` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe app.py --no-gui --mode realtime --duration 2.0 --delay-ms 20` => pass

### Open Issues
- GUI 可视化交互体验（Start/Pause/Reset 手感、DPI 字体观感）仍需你本机窗口实测确认。

## 2026-04-20 Iteration Batch (布局二次优化 + Tab 信息区 + 稳定时间轴)

### Modified
- app.py
  - 取消诊断抽屉，右侧下方改为 `QTabWidget`（核心状态/诊断信息）。
  - 右侧上方改为双视角并排（原始相机 / Raspi 延时），放大单视角有效显示尺寸。
  - 核心状态改为两列合并行展示（姿态、像素、偏差、误差、链路），并统一居中对齐。
  - 核心状态字段统一固定精度显示（t3位、角度/角速2位、像素/偏差1位、延时2位）。
  - 时间轴改回 pyqtgraph，增加固定窗口、降采样、自动 y 轴范围，修复曲线糊块问题。
  - 分栏比例调整为 60/40，并保存会话拖拽结果。
- README.md
  - 更新实时仪表盘说明为“左主右辅 + 双视角并排 + Tab”，同步依赖说明为 `PyQt5 + pyqtgraph`。

### Added
- None.

### Verification
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m py_compile app.py` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s entities\raspi\tests -p "test_*.py" -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe -m unittest discover -s tests -v` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe app.py --no-gui --mode offline --duration 1.0` => pass
- `C:\Users\20163\miniconda3\envs\simulation\python.exe app.py --no-gui --mode realtime --duration 2.0 --delay-ms 20` => pass

### Open Issues
- GUI 视觉细节（字体层级与间距）仍可继续精修，但当前功能与布局问题已闭环。

## [2026-04-20 14:28:47] 修复 config_editor 保存报错
- Modified: tools/config_editor.py
- Root cause: 正则替换使用 ""\1"" + replacement，当 replacement 以数字开头（如 0.02）时被误解析为分组引用，触发 invalid group reference。
- Fix: 改为函数式替换，按匹配分组拼接字符串，避免反向引用歧义。
- Verification: python -m py_compile tools/config_editor.py；最小复现替换用例通过。

## [2026-04-20 15:04:40] app.py 分层重构（simulation 目录）
- Modified:
  - app.py（改为薄入口，仅透传到 simulation.cli.main）
  - README.md（目录结构与“单实体测试->组装联调”流程更新）
- Added:
  - simulation 启动编排层（bootstrap/state_buffer/worker/headless/gui/cli）
- Result:
  - 保持 python app.py --mode ... --duration ... --delay-ms ... --no-gui 用法不变。
  - 将参数解析、runtime 启动、线程、缓存、GUI 拆到独立模块，便于单测与组装。
- Verification:
  - 单实体测试、主线 tests、headless 联调、offscreen GUI 冒烟全部通过。

## [2026-04-22 10:04:28] 新增实例组装使用手册（原理+实操）
- Added: docs/使用手册.md
- Modified: README.md（新增手册入口链接）
- 内容覆盖: 架构、快速开始、单体测试、组装联调、控制模板、规范、排错、验收清单。
- 验证: 按手册命令执行通过（单体 tests、主线 tests、headless 冒烟）。
