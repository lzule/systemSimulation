# GUI 综合优化方案 v2（最终版）

> 修订时间：2026-05-19
> 状态：用户决策已收齐，方案锁定
> 配套开发文档：`docs/GUI综合优化方案v2-开发步骤.md`

---

## 1. 背景

针对当前 GUI 的 10 项问题做综合优化，涵盖光斑显示、时间轴布局、诊断面板可读性、双视角信息冗余、云台延时概念澄清、顶部交互改造、3D 可视化、算法组合架构、结果自动保存等。

| # | 用户提出的问题 | 类型 |
|---|---|---|
| 1 | 相机/树莓派视角的光源还是个红点，看不出物理光斑模型在工作 | 显示 |
| 2 | 时间轴 ATP 状态带挤占了误差曲线展示空间 | 布局 |
| 3 | 右下诊断信息可读性、展示性差 | 可读性 |
| 4 | 双视角的 info_label 信息冗余，与其他面板重复 | 信息冗余 |
| 5 | 云台 30ms 延时是否真实合理？ | 概念澄清 |
| 6 | 顶部信息冗余 + 算法/模式/目标运动应做成可选项 | 交互 |
| 7 | "应用延时"按钮必要性低 | 简化 |
| 8 | 目标运动有 z 维度但世界视图仍是 2D，需可视化 | 显示 |
| 9 | 算法应可拆为图像处理/跟踪/预测组合，但保留两条路径 | 架构 |
| 10 | 仿真结束应自动保存哪些结果 | 持久化 |

---

## 2. 关键事实澄清（来自代码探索）

### 2.1 关于"云台 30ms 延时"（问题 5）

**结论：30ms 不是通信延时，是云台的一阶响应时间常数 τ。**

代码层面：
- `config.py` `GimbalConfig.response_tau_s = 0.03`
- `entities/gimbal/model.py` `_first_order_rate_update` 用 `alpha = dt / (tau + dt)` 实现一阶滞后
- 数学含义：阶跃命令下 `t = τ` 时速率达到目标的 63.2%，`t = 3τ` 时达到 95%
- 控制循环 200Hz（dt=5ms），每步响应 14.3% 命令变化

**这是"机械/电气惯性"，物理合理**。真实云台电机执行速率命令也不可能瞬间到位。本轮不改 τ 数值，仅在 GUI 上重命名为"云台响应τ"并加注释。

### 2.2 关于"光斑还是红点"（问题 1）

**结论：底层物理光斑模型对的，但默认配置导致看不出"近大远小"。**

- 默认 `beacon_sigma_px = 3.2`、`sigma_ref_distance_m = 0.0`（距离相关禁用）
- 距离 100m 时光斑 σ 仍是 3.2 px，与 10m 时一样大
- 上方还有红色实心圆遮挡（`target_item`）

### 2.3 关于"算法可组合"（问题 9）

**结论：组合式架构已经存在，只是没暴露给 GUI。**

- `AtpControlProgram(tracker=X, predictor=Y)` 已经支持任意组合
- `tools/run_benchmark.py` 的 `ALGORITHM_REGISTRY` 已注册 6 种组合
- 缺的是 GUI 入口让用户选

### 2.4 关于 `sigma_ref_distance_m` 的含义

代码 `entities/camera/model.py` 第 28-34 行：
```python
sigma_base = self.cfg.beacon_sigma_px
if self.cfg.sigma_ref_distance_m > 0.0 and distance_m > 0.0:
    sigma = sigma_base / (1.0 + distance_m / self.cfg.sigma_ref_distance_m)
else:
    sigma = sigma_base  # 固定不变
```

**`sigma_ref_distance_m` 是参考距离**：当距离 = `sigma_ref_distance_m` 时，光斑大小衰减到基础 sigma 的 50%。

**举例（假设 `beacon_sigma_px = 6.0`）：**

| 配置 | 10m 时 σ | 50m 时 σ | 100m 时 σ | 200m 时 σ |
|------|---------|---------|----------|----------|
| `sigma_ref = 0`（当前默认）| 6.0 px | 6.0 px | 6.0 px | 6.0 px（不变）|
| `sigma_ref = 50` | 5.0 px | 3.0 px | 2.0 px | 1.2 px（变化激进）|
| `sigma_ref = 80`（**本轮选用**）| 5.3 px | 3.7 px | 2.7 px | 1.7 px（中等）|
| `sigma_ref = 200` | 5.7 px | 4.8 px | 4.0 px | 3.0 px（平缓）|

`brightness_ref_distance_m` 同理：控制亮度随距离衰减的参考距离。

---

## 3. 用户决策汇总（已锁定）

| 决策项 | 选择 |
|--------|------|
| 光斑显示 | 默认启用距离相关光斑模型 |
| ATP 状态位置 | 背景色叠加在角速度图上（去 plot_atp 独立行） |
| 顶部信息 | 算法/模式/目标做下拉选择器 |
| 自动保存 | 完整数据 + 时间轴 PNG + 场景配置快照 + 关键帧序列 |
| `sigma_ref_distance_m` | 80 m |
| 下拉切换生效方式 | 立即 reset |
| 关键帧参数 | 固定（ATP 切换 ±0.5s 内每 0.1s 一帧） |
| 本轮范围 | 只做 Step 1-4，Step 9 算法组合 UI 下一轮 |

---

## 4. 4 步实施总览

```
Step 1: 光源显示 + 双视角信息精简（问题 1, 4）
Step 2: 时间轴重构 + 诊断面板重构（问题 2, 3）
Step 3: 顶部下拉选择器 + 删除应用延时按钮 + 重命名云台τ（问题 5, 6, 7）
Step 4: 自动保存 + 世界视图 3D 信息（问题 8, 10）
        Step 9（算法组合 UI）放下一轮
```

---

## 5. Step 1：光源显示 + 双视角信息精简

### 5.1 默认启用距离相关光斑模型

修改 `config.py` 的 `CameraConfig` 默认值：

```python
beacon_sigma_px: float = 6.0              # 3.2 → 6.0（基线光斑更明显）
detection_threshold: int = 100            # 180 → 100（让更大范围像素能被检出）
sigma_ref_distance_m: float = 80.0        # 0.0 → 80.0（启用距离衰减）
brightness_ref_distance_m: float = 80.0   # 0.0 → 80.0（启用亮度衰减）
```

效果（默认场景距离 100m 上下）：
- 50m：σ=3.7 px，亮度 0.62
- 100m：σ=2.7 px，亮度 0.44
- 200m：σ=1.7 px，亮度 0.29

### 5.2 改造光斑显示

修改 `simulation/gui/panels/camera_panel.py`：
- **去掉** `target_item`（实心红点），它遮挡了底层光斑
- **保留** `target_outline_item`（虚线轮廓圈，sigma 同步），作为检测中心标识
- **新增** 1px 小十字（`+`）标识检测中心，不遮挡底层

### 5.3 双视角 info_label 精简

修改 `simulation/gui/window.py` 的 `_camera_info_text`：

**修改前**：`{w}x{h}px | t={t:.3f}s | u={u:.1f}, v={v:.1f} | du={du:.1f}, dv={dv:.1f} | sigma={sigma:.2f}px | {fov}`

**修改后**：`du={du:.1f}, dv={dv:.1f} | sigma={sigma:.1f}px`

理由：分辨率、时间戳、u/v 在其他面板中已有显示。

---

## 6. Step 2：时间轴重构 + 诊断面板重构

### 6.1 时间轴重构

修改 `simulation/gui/window.py` 的 `_build_timeline` / `_draw_timeline`：

- **移除** `plot_atp` 子图（独立第三行）
- 在 `plot_rate`（角速度图）上叠加 ATP 状态背景色：
  - 用 `pyqtgraph.LinearRegionItem` 绘制半透明彩色区域
  - 每次状态切换时新增一个 `LinearRegionItem`（长度=该状态持续时间）
  - 颜色映射：SEARCH 红 / ACQUIRE 橙 / TRACK_COARSE 蓝 / TRACK_FINE 绿 / LOST 红 / REACQUIRE 橙
  - Alpha=30/255（背景色，不抢视觉重心）
- 在 `plot_rate` 标题区显示当前 ATP 状态文字 + 颜色，作为图例

效果：误差曲线、角速度曲线获得完整高度，ATP 状态以背景色呈现，状态切换瞬间清晰可见。

### 6.2 诊断面板重构

当前问题：
- 4 个 Tab 切换繁琐
- 字段值都是 `f"{v:.4f}"`，可读性差
- 字段名没有单位

修改 `_build_diag_section` / `_update_diag_tab`：

- 用 `QTreeWidget`（树状）替代 `QTabWidget + QTableWidget`
- 4 个顶级节点（云台 / 相机 / 树莓派 / 目标）默认全部展开
- 每实体先显示 5-7 个最关键字段，"展开高级"看更多
- 字段值按类型格式化：
  | 类型 | 格式 | 示例 |
  |------|------|------|
  | 角度 | `5.20°` | yaw、pitch |
  | 像素 | `325 px` | u、v |
  | 距离 | `125.3 m` | x、y、distance |
  | 时间 | `12.345 s` | timestamp |
  | 速率 | `5.20 dps` | yaw_rate |
  | 亮度 | `0.45` | brightness |
  | 状态 | 色块 | atp_state、power_state |

---

## 7. Step 3：顶部下拉 + 删除应用延时 + 重命名 τ

### 7.1 顶部下拉选择器

修改 `simulation/gui/window.py`：

**摘要条保留运行时变量**：state、t、距离、ATP 状态、延时、backlog、FPS

**操作条增加 3 个 QComboBox**：
```
[算法 ▼] [观测模式 ▼] [目标运动 ▼]   [开始][暂停][重置][截图]
```

- **算法下拉**：从 `tools/run_benchmark.py` 的 `ALGORITHM_REGISTRY` 读 6 个：
  - baseline_rate_p / atp_search_track_baseline / rate_pi / alpha_beta_tracker / linear_kf_tracker / angle_mode_realistic
- **观测模式**：debug / research / realistic
- **目标运动**：sinusoidal / constant_velocity / constant_accel / random_walk / waypoint

切换时立即调用 `_on_reset()` 重建 runtime（用户决策："立即 reset"）。
当前选中值在初始化时从 `cfg` 读取。状态栏提示"已切换并重置"。

### 7.2 删除"应用延时"按钮

修改 `simulation/gui/window.py`：
- 移除 `btn_apply_delay`、`delay_spin`、`delay_label` 三个组件
- 移除 `_on_apply_delay` 方法
- 延时仅由 CLI `--delay-ms` 设置一次，运行期间不变

注意：worker 的 `request_delay_ms` 接口本身保留（benchmark 等场景可能用），只是 GUI 不暴露。

### 7.3 重命名"云台τ"

延时链路标签从：
```
延时链路: 读取5ms → 处理15ms → 发送3ms + 云台τ30ms │ 观测延迟: --ms
```
改为：
```
链路延时: 读取5ms → 处理15ms → 发送3ms │ 云台响应τ: 30ms（一阶惯性，非通信延时）│ 观测延迟: --ms
```

---

## 8. Step 4：自动保存 + 世界视图 3D 信息

### 8.1 仿真结束自动保存

修改 `simulation/gui/window.py` 的 `_on_worker_finished`：

- duration 跑完时，自动调用 `_export_session_results()`
- 输出目录：`output/session_<timestamp>/`
  - `dashboard.png` — 窗口截图
  - `summary.json` — 运行摘要
  - `metrics.csv` — 每帧数据
  - `event_log.json` — ATP 状态变迁事件
  - `timeline.png` — 时间轴曲线导出（含状态背景色）
  - `scene_config.json` — 场景配置完整快照
  - `keyframes/` — 关键帧序列

### 8.2 数据采集机制

修改 `simulation/state_buffer.py`：
- 新增 `metrics_log: List[Dict]` — 每帧关键指标
- 新增 `event_log: List[Dict]` — ATP 状态变迁事件（push 时检测变化）

参考 `tools/run_benchmark.py` 的 `FrameCollector` 实现，避免重复造轮子。

**summary.json 格式：**
```json
{
  "session_id": "session_1716123456",
  "started_at": "2026-05-19T09:00:00",
  "duration_s": 60.0,
  "config": {
    "control_program": "atp_search_track_baseline",
    "obs_mode": "research",
    "target_type": "sinusoidal",
    "delay_ms": 26.0
  },
  "metrics": {
    "mean_pixel_error_px": 12.3,
    "max_pixel_error_px": 45.6,
    "mean_distance_m": 105.2,
    "atp_state_distribution": {"TRACK_FINE": 0.7, "TRACK_COARSE": 0.2, ...},
    "in_fov_ratio": 0.95
  }
}
```

**metrics.csv 格式（每帧一行）：**
```csv
timestamp,u_px,v_px,du,dv,yaw,pitch,yaw_rate,pitch_rate,atp_state,distance_m,sigma_px,brightness,in_fov,backlog
```

**event_log.json 格式：**
```json
[
  {"timestamp": 0.50, "from": "SEARCH", "to": "ACQUIRE"},
  {"timestamp": 1.20, "from": "ACQUIRE", "to": "TRACK_COARSE"},
  ...
]
```

**关键帧序列**：
- 触发条件：每次 ATP 状态切换
- 采集范围：切换时刻 ±0.5s
- 采集间隔：每 0.1s 一帧
- 命名：`keyframes/<event_idx>_<offset_s>.png`（offset_s 为相对切换时刻的偏移）

### 8.3 世界视图 3D 信息

修改 `simulation/gui/window.py` 的 `_draw_world`：

不做完整 3D 改造（成本高），保留 2D 俯视图：

- **目标颜色按 z 编码**：z=0 红色，z>0 偏蓝（高），z<0 偏黄（低）
- **目标尺寸按 z 编码**：标准 2.8m，向上加大 / 向下减小
- **轨迹线按 z 渐变**：z 高时偏冷色，z 低时偏暖色
- **目标右侧标注 z 值**：`z=12.3m`（小字）
- **世界视图标题加注**：`俯视图 - z 编码: 高=蓝，低=黄`

---

## 9. 涉及文件

| 文件 | 改动 |
|------|------|
| `config.py` | CameraConfig 默认值（Step 1） |
| `simulation/gui/panels/camera_panel.py` | 去 target_item，新增小十字（Step 1） |
| `simulation/gui/window.py` | info_label 精简、时间轴、诊断、顶部下拉、删延时按钮、世界视图、自动保存（Step 1-4） |
| `simulation/state_buffer.py` | metrics_log、event_log 缓冲（Step 4） |
| `tests/test_runtime_api.py` | 验证默认 CameraConfig 改动（Step 1） |
| `CHANGELOG.md` | Step 1-4 记录追加 |

**不动**：
- `entities/camera/model.py`（已支持距离衰减）
- `entities/raspi/atp_control_program.py` 等控制程序代码
- `tools/run_benchmark.py`、`tools/record_session.py` 等工具
- `simulation/worker.py`（保留 request_delay_ms 接口，仅 GUI 不暴露）

---

## 10. 风险评估

| 风险 | 等级 | 应对 |
|------|------|------|
| 默认 CameraConfig 改动影响现有 benchmark 结果 | 中 | 用户已接受；后续如需对比可在 benchmark 显式传 sigma_ref=0 |
| 切换下拉时打断进行中的实验 | 中 | 立即 reset 是用户选择；状态栏明确提示"已切换并重置" |
| 关键帧序列占空间 | 低 | 固定参数下每个 ATP 切换约 11 帧，量可控 |
| 树状诊断面板可读性未必更好 | 中 | 写完后实地看；不行回退到表格 |
| LinearRegionItem 大量绘制影响性能 | 低 | 只在状态切换时新增；状态变化频率不高 |
| sigma 变化导致 3σ 轮廓圈太小 | 低 | 已有 `r = max(2.0, 3.0 * sigma_px)` 下限保护 |

---

## 11. 验收标准

每个 Step 完成后应能：

**Step 1**：
- [ ] 启动 GUI 看到光斑大小随距离变化（近大远小、近亮远暗）
- [ ] 双视角 info_label 只剩 du/dv/sigma
- [ ] 全量测试 160+ tests 通过

**Step 2**：
- [ ] 时间轴只剩误差和角速度两个子图
- [ ] 角速度图背景按 ATP 状态变色
- [ ] 诊断面板用树状结构呈现，字段带单位

**Step 3**：
- [ ] 顶部有 3 个下拉选择器，可切换算法/模式/目标
- [ ] 切换后立即 reset，状态栏提示"已切换并重置"
- [ ] 应用延时按钮已删除
- [ ] 延时链路标签解释了"云台τ"的含义

**Step 4**：
- [ ] duration 跑完后 `output/session_*/` 自动生成全部 7 类文件
- [ ] 世界视图能看到 z 信息（颜色或大小变化 + 数值标注）
- [ ] 全量测试通过

---

*方案文档锁定。详细开发步骤见配套文档 `GUI综合优化方案v2-开发步骤.md`。*
