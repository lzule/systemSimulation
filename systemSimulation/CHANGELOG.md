# 修改历史

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
