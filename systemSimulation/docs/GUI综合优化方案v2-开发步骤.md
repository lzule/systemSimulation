# GUI 综合优化方案 v2 — 详细开发步骤

> 配套文档：`docs/GUI综合优化方案v2.md`（设计目标与决策）
> 用途：实施期间的逐步操作指南，每个子任务可独立验证

---

## 总体执行约定

- **环境**：所有 Python 命令必须用 `conda run -n simulation python ...`
- **顺序**：严格按 Step 1 → 2 → 3 → 4，每步完成后做 1 次验证再进入下一步
- **回滚**：每步独立可回退（git stash / 注释代码）
- **CHANGELOG**：每完成一个完整 Step 追加一条记录（用 `Get-Date -Format yyyyMMdd-HHmmss` 取真实时间戳）
- **测试基线**：当前 160 tests，每步后必须保持通过

---

## Step 1：光源显示 + 双视角信息精简

**目标**：让用户能看见光斑随距离变化、消除红点遮挡、精简信息冗余。

### 1.1 修改 CameraConfig 默认值

**文件**：`config.py`

**位置**：`@dataclass class CameraConfig` 内，已有字段更新：

```python
beacon_sigma_px: float = 6.0              # 由 3.2 改为 6.0
detection_threshold: int = 100            # 由 180 改为 100
sigma_ref_distance_m: float = 80.0        # 由 0.0 改为 80.0
brightness_ref_distance_m: float = 80.0   # 由 0.0 改为 80.0
```

**注意点**：
- `beacon_sigma_px` 和 `sigma_ref_distance_m` 配合使用：`sigma = sigma_base / (1 + d/sigma_ref)`
- `detection_threshold` 降到 100 是为了让光斑外围（~1.5σ 处）也能被检出，避免远距离时光斑全部低于阈值
- 不要改 `brightness_base = 1.0`（保持峰值满量程）

### 1.2 改造相机面板红点

**文件**：`simulation/gui/panels/camera_panel.py`

**位置**：`CameraImageView.__init__` 中关于 `target_item` 的代码（约 L35-46）

**操作**：
1. **删除** `self.target_item` 的实心红点定义（包括 setBrush 实色填充）
2. **保留** `self.target_outline_item` 虚线轮廓圈定义（已有，不动）
3. **新增** 1px 小十字标记 `self.target_cross_item_h`（横线）和 `self.target_cross_item_v`（竖线）：
```python
cross_pen = QtGui.QPen(QtGui.QColor(COLOR["target"]), 1.0)
self.target_cross_item_h = QtWidgets.QGraphicsLineItem(-3.0, 0.0, 3.0, 0.0)
self.target_cross_item_h.setPen(cross_pen)
self.scene().addItem(self.target_cross_item_h)
self.target_cross_item_v = QtWidgets.QGraphicsLineItem(0.0, -3.0, 0.0, 3.0)
self.target_cross_item_v.setPen(cross_pen)
self.scene().addItem(self.target_cross_item_v)
```

**位置**：`CameraImageView.update_frame` 中检测点定位逻辑

**操作**：把原 `target_item.setVisible / setPos` 替换为对两条十字线 + 轮廓圈的 setPos，统一以 `(det.cx, det.cy)` 为中心。

### 1.3 简化 info_label 文本

**文件**：`simulation/gui/window.py`

**位置**：`_camera_info_text` 方法（约 L731-757）

**操作**：将拼接字符串改为：
```python
text = f"du={du:.1f}, dv={dv:.1f} | sigma={sigma_px:.1f}px"
return text, in_fov
```

注意：原方法返回 `(text, ok)`，调用处依赖此 ok 决定颜色，保留这部分逻辑。

### 1.4 调整 test_runtime_api.py 默认值断言

**文件**：`tests/test_runtime_api.py`

**操作**：
- `test_camera_snapshot_exposes_imaging_physics`：原断言 `sigma_px ≈ 3.2`，现在默认配置 sigma_ref=80m、距离 100m 时应为 `6.0/(1+100/80) ≈ 2.67`
- 改为：
```python
# 默认 beacon_sigma_px=6.0, sigma_ref=80m, 距离 100m 时 sigma ≈ 2.67
self.assertAlmostEqual(snap.camera["sigma_px"], 6.0 / (1.0 + 100.0 / 80.0), places=2)
```
- `test_camera_sigma_decreases_with_distance`：仍可用，但需要把 `original_ref` 在 finally 中恢复为 80（不是 0）

### 1.5 验证

```bash
# 冒烟
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0

# 单测
conda run -n simulation python -m unittest tests.test_runtime_api -v

# 全量测试
conda run -n simulation python -m unittest discover -s tests
```

**人工验证（启动 GUI 看）**：
- 启动后双视角光斑应明显比之前大且亮（默认 100m 处 σ ≈ 2.7px，但峰值 0.44 × 255 ≈ 112 灰度足够可见）
- 没有红色实心点，只有黑色十字 + 虚线轮廓圈
- info_label 简化为 `du=... dv=... sigma=...`

### 1.6 CHANGELOG 追加

格式参考：
```markdown
## 070-<时间戳> Step 1: 光源距离模型默认启用 + 双视角信息精简

**目的**：解决"相机视角光源还是个红点看不出物理模型"的问题。
**修改者**：Claude Code

**修改内容**：
1. config.py — CameraConfig 默认值调整（beacon_sigma_px=6.0、threshold=100、sigma_ref=80、brightness_ref=80）
2. simulation/gui/panels/camera_panel.py — 移除 target_item 实心红点，新增十字标记
3. simulation/gui/window.py — _camera_info_text 简化为 du/dv/sigma 三项
4. tests/test_runtime_api.py — 适配新默认值

**验证**：冒烟通过、全量 160 tests 通过、GUI 手动确认光斑随距离可见变化
```

---

## Step 2：时间轴重构 + 诊断面板重构

**目标**：把 ATP 状态从独立子图改为角速度图背景；诊断面板用树状结构带单位显示。

### 2.1 时间轴：移除 plot_atp，改为 LinearRegionItem 背景

**文件**：`simulation/gui/window.py`

#### 2.1.1 修改 `_build_timeline`（约 L450-475）

**操作**：
1. **删除** `plot_atp` 子图的全部初始化代码（包括 `self.atp_bar_item`、图例 TextItem、`row=2`）
2. **新增** 标题区当前 ATP 状态显示：在 `plot_rate` 上方添加一个 QLabel `self.lbl_current_atp`，作为时间轴 GroupBox 的副标题
3. **新增** 用于跟踪 ATP 区域的列表：
```python
self.atp_regions: list[pg.LinearRegionItem] = []
self._last_atp_state_for_region: Optional[str] = None
```

#### 2.1.2 修改 `_draw_timeline`（约 L596-720）

**操作**：
1. 把签名从 7 元组解包改回 7 元组（保持兼容），但 atp_state_list 改用方式不同
2. 删除原 `plot_atp` 的 BarGraphItem 更新逻辑（约 L692-711）
3. 新增 LinearRegionItem 增量更新：
```python
# 解析 ATP 状态变迁，每段连续状态生成一个 LinearRegionItem
atp_colors = {
    "SEARCH": "#e74c3c", "ACQUIRE": "#f39c12",
    "TRACK_COARSE": "#3498db", "TRACK_FINE": "#27ae60",
    "LOST": "#e74c3c", "REACQUIRE": "#f39c12",
}

# 清除已有区域（每次重绘）
for region in self.atp_regions:
    self.plot_rate.removeItem(region)
self.atp_regions.clear()

# 扫描 atp_windowed 找出连续段
if atp_windowed:
    seg_start_idx = 0
    seg_state = atp_windowed[0]
    for i in range(1, len(atp_windowed)):
        if atp_windowed[i] != seg_state:
            # 状态切换，结束上一段
            if seg_state in atp_colors:
                color = QtGui.QColor(atp_colors[seg_state])
                color.setAlpha(40)
                region = pg.LinearRegionItem(
                    values=(t_np[seg_start_idx], t_np[i-1]),
                    brush=pg.mkBrush(color),
                    movable=False,
                )
                region.setZValue(-10)
                self.plot_rate.addItem(region)
                self.atp_regions.append(region)
            seg_start_idx = i
            seg_state = atp_windowed[i]
    # 处理最后一段（持续到当前）
    if seg_state in atp_colors:
        color = QtGui.QColor(atp_colors[seg_state])
        color.setAlpha(40)
        region = pg.LinearRegionItem(
            values=(t_np[seg_start_idx], t_np[-1]),
            brush=pg.mkBrush(color),
            movable=False,
        )
        region.setZValue(-10)
        self.plot_rate.addItem(region)
        self.atp_regions.append(region)
```

4. 更新当前 ATP 状态标签：
```python
current_atp = atp_windowed[-1] if atp_windowed else "--"
self.lbl_current_atp.setText(f"当前 ATP: {current_atp}")
self.lbl_current_atp.setStyleSheet(f"color: {atp_colors.get(current_atp, COLOR['text_main'])}; font-weight: 700;")
```

### 2.2 诊断面板：QTabWidget+QTableWidget → QTreeWidget

**文件**：`simulation/gui/window.py`

#### 2.2.1 重写 `_build_diag_section`（约 L307-364）

**新结构**：
```python
def _build_diag_section(self, parent_layout: QtWidgets.QVBoxLayout) -> None:
    diag_box = QtWidgets.QGroupBox("诊断信息")
    layout = QtWidgets.QVBoxLayout(diag_box)
    layout.setContentsMargins(8, 8, 8, 8)

    self.diag_tree = QtWidgets.QTreeWidget()
    self.diag_tree.setHeaderLabels(["字段", "值"])
    self.diag_tree.setRootIsDecorated(True)
    self.diag_tree.setAlternatingRowColors(True)
    self.diag_tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
    self.diag_tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)

    # 4 个顶级节点 + 子节点，先创建空子节点占位
    self.diag_items: dict[str, dict[str, QtWidgets.QTreeWidgetItem]] = {}
    for entity_key, entity_label, fields in DIAG_FIELDS_SCHEMA:
        parent = QtWidgets.QTreeWidgetItem(self.diag_tree, [entity_label, ""])
        parent.setExpanded(True)
        self.diag_items[entity_key] = {}
        for field_key, field_label in fields:
            child = QtWidgets.QTreeWidgetItem(parent, [field_label, "--"])
            self.diag_items[entity_key][field_key] = child

    layout.addWidget(self.diag_tree)
    parent_layout.addWidget(diag_box, 6)
```

**`DIAG_FIELDS_SCHEMA` 定义**（放模块顶部）：
```python
DIAG_FIELDS_SCHEMA = [
    ("gimbal", "云台", [
        ("mode", "模式"),
        ("yaw_deg", "yaw"),
        ("pitch_deg", "pitch"),
        ("yaw_rate_dps", "yaw 速率"),
        ("pitch_rate_dps", "pitch 速率"),
        ("power_state", "电源"),
    ]),
    ("camera", "相机", [
        ("f_current_mm", "焦距"),
        ("frame_id", "帧序号"),
        ("u_px", "u"),
        ("v_px", "v"),
        ("distance_m", "距离"),
        ("sigma_px", "光斑σ"),
        ("brightness", "亮度"),
        ("in_fov", "在视野内"),
    ]),
    ("raspi", "树莓派", [
        ("control_program_name", "控制程序"),
        ("atp_state", "ATP 状态"),
        ("pipeline_backlog_len", "管线积压"),
        ("last_process_latency_s", "观测延迟"),
        ("effective_obs_timestamp", "有效观测时刻"),
        ("power_state", "电源"),
    ]),
    ("target", "目标", [
        ("x_m", "x"),
        ("y_m", "y"),
        ("z_m", "z"),
        ("vx_mps", "vx"),
        ("vy_mps", "vy"),
        ("vz_mps", "vz"),
    ]),
]
```

#### 2.2.2 重写 `_update_diag_tab`（约 L795-845）

**新逻辑**：
```python
def _update_diag_tab(self, snapshot: Any, raw_frame, raspi_frame) -> None:
    g, c, r, t = snapshot.gimbal, snapshot.camera, snapshot.raspi, snapshot.target

    formatters = {
        "yaw_deg": lambda v: f"{float(v):.2f}°",
        "pitch_deg": lambda v: f"{float(v):.2f}°",
        "yaw_rate_dps": lambda v: f"{float(v):.2f} dps",
        "pitch_rate_dps": lambda v: f"{float(v):.2f} dps",
        "f_current_mm": lambda v: f"{float(v):.2f} mm",
        "u_px": lambda v: f"{float(v):.0f} px",
        "v_px": lambda v: f"{float(v):.0f} px",
        "distance_m": lambda v: f"{float(v):.1f} m",
        "sigma_px": lambda v: f"{float(v):.2f} px",
        "brightness": lambda v: f"{float(v):.2f}",
        "in_fov": lambda v: "是" if bool(v) else "否",
        "frame_id": lambda v: f"{int(v)}",
        "x_m": lambda v: f"{float(v):.2f} m",
        "y_m": lambda v: f"{float(v):.2f} m",
        "z_m": lambda v: f"{float(v):.2f} m",
        "vx_mps": lambda v: f"{float(v):.2f} m/s",
        "vy_mps": lambda v: f"{float(v):.2f} m/s",
        "vz_mps": lambda v: f"{float(v):.2f} m/s",
        "pipeline_backlog_len": lambda v: f"{int(v)}",
        "last_process_latency_s": lambda v: f"{float(v)*1000:.1f} ms",
        "effective_obs_timestamp": lambda v: f"{float(v):.3f} s" if v == v else "--",  # NaN check
    }

    # 注意 gimbal 的 yaw_deg 字段需要从 yaw_deg_display 取
    g_view = dict(g)
    g_view["yaw_deg"] = g.get("yaw_deg_display", g.get("yaw_deg_internal", 0.0))
    
    sources = {"gimbal": g_view, "camera": c, "raspi": r, "target": t}
    for entity_key, entity_data in sources.items():
        for field_key, item in self.diag_items[entity_key].items():
            value = entity_data.get(field_key, "--")
            formatter = formatters.get(field_key, lambda v: str(v))
            try:
                item.setText(1, formatter(value))
            except (ValueError, TypeError):
                item.setText(1, str(value))
```

注意 ATP 状态可加色块装饰：
```python
if field_key == "atp_state":
    color_map = {"SEARCH": "#e74c3c", ...}
    color = color_map.get(value, "#000000")
    item.setForeground(1, QtGui.QBrush(QtGui.QColor(color)))
```

### 2.3 验证

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0
conda run -n simulation python -m unittest discover -s tests
```

**人工验证**：
- 时间轴只剩 2 个子图：误差 + 角速度
- 角速度图背景按 ATP 状态变色
- 时间轴 GroupBox 标题旁显示"当前 ATP: TRACK_FINE"（带颜色）
- 诊断面板树状结构，4 个实体全部展开
- 字段值带单位（如 `5.20°`、`125.3 m`、`325 px`）

### 2.4 CHANGELOG 追加（071）

---

## Step 3：顶部下拉 + 删应用延时按钮 + 重命名 τ

**目标**：算法/模式/目标变成下拉可选；操作条更简洁；延时链路标签更清楚。

### 3.1 增加 3 个 QComboBox

**文件**：`simulation/gui/window.py`

#### 3.1.1 在操作条 toolbar 中添加下拉

**位置**：`_build_ui` 内"顶部操作条"区域（约 L146-196）

**操作**：
1. 在按钮之后、延时区域之前插入：
```python
# ── 算法 / 观测模式 / 目标运动 下拉 ──
ALGORITHM_OPTIONS = [
    "baseline_rate_p", "atp_search_track_baseline", "rate_pi",
    "alpha_beta_tracker", "linear_kf_tracker", "angle_mode_realistic",
]
OBS_MODE_OPTIONS = ["debug", "research", "realistic"]
TARGET_TYPE_OPTIONS = ["sinusoidal", "constant_velocity", "constant_accel", "random_walk", "waypoint"]

self.cbo_algorithm = QtWidgets.QComboBox()
self.cbo_algorithm.addItems(ALGORITHM_OPTIONS)
self.cbo_obs_mode = QtWidgets.QComboBox()
self.cbo_obs_mode.addItems(OBS_MODE_OPTIONS)
self.cbo_obs_mode.setCurrentText(self.cfg.obs_mode or "debug")
self.cbo_target_type = QtWidgets.QComboBox()
self.cbo_target_type.addItems(TARGET_TYPE_OPTIONS)
self.cbo_target_type.setCurrentText(
    self.cfg.target_type if self.cfg.target_type else self._get_target_motion_type()
)

toolbar_layout.addWidget(QtWidgets.QLabel("算法"))
toolbar_layout.addWidget(self.cbo_algorithm)
toolbar_layout.addWidget(QtWidgets.QLabel("观测"))
toolbar_layout.addWidget(self.cbo_obs_mode)
toolbar_layout.addWidget(QtWidgets.QLabel("目标"))
toolbar_layout.addWidget(self.cbo_target_type)
```

2. 在 `_build_ui` 末尾的事件绑定区域（约 L271-275）增加：
```python
self.cbo_algorithm.currentTextChanged.connect(self._on_algorithm_changed)
self.cbo_obs_mode.currentTextChanged.connect(self._on_obs_mode_changed)
self.cbo_target_type.currentTextChanged.connect(self._on_target_type_changed)
```

#### 3.1.2 实现切换处理函数

**新增方法**：
```python
def _on_algorithm_changed(self, name: str) -> None:
    """切换算法 → 立即重置 runtime"""
    # 通过 ALGORITHM_REGISTRY 构造控制程序
    from tools.run_benchmark import ALGORITHM_REGISTRY
    if name in ALGORITHM_REGISTRY:
        # 注入到 cfg.control_program_path（特殊形式，标识使用 registry）
        self.cfg.control_program_path = f"@registry:{name}"
    self._on_reset()
    self.statusBar().showMessage(f"已切换算法为 {name}，已重置", 2000)

def _on_obs_mode_changed(self, mode: str) -> None:
    self.cfg.obs_mode = mode
    self._on_reset()
    self.statusBar().showMessage(f"已切换观测模式为 {mode}，已重置", 2000)

def _on_target_type_changed(self, target_type: str) -> None:
    self.cfg.target_type = target_type
    # 注意 _on_reset 会调 apply_target_overrides 应用 cfg.target_type
    self._on_reset()
    self.statusBar().showMessage(f"已切换目标运动为 {target_type}，已重置", 2000)
```

#### 3.1.3 让 `load_control_program_from_path` 支持 `@registry:` 前缀

**文件**：`simulation/bootstrap.py`

**位置**：`load_control_program_from_path` 方法

**操作**：
```python
def load_control_program_from_path(path: str):
    if not path:
        return None
    if path.startswith("@registry:"):
        algo_name = path[len("@registry:"):]
        from tools.run_benchmark import ALGORITHM_REGISTRY
        factory = ALGORITHM_REGISTRY.get(algo_name)
        if factory is None:
            raise ValueError(f"未知算法 {algo_name}")
        return factory()
    # 原有 module:Class 解析逻辑保持不变
    module_name, class_name = path.split(":")
    ...
```

注意：`tools/run_benchmark.py` 的 `ALGORITHM_REGISTRY` 中工厂函数返回的是控制程序实例，不是类。验证一下确认。

### 3.2 删除"应用延时"按钮

**文件**：`simulation/gui/window.py`

**操作**：
1. 在 `_build_ui` 的"顶部操作条"区域删除：
   - `self.delay_label = QtWidgets.QLabel(UI_TEXT["delay_label"])`
   - `self.delay_spin = QtWidgets.QDoubleSpinBox()` 及其配置
   - `self.btn_apply_delay = QtWidgets.QPushButton(UI_TEXT["apply_delay"])`
   - `for w in (... self.delay_label, self.delay_spin, self.btn_apply_delay)` 中删除这三项
2. 删除事件绑定 `self.btn_apply_delay.clicked.connect(self._on_apply_delay)`
3. 删除方法 `_on_apply_delay`
4. `_on_reset` 中如果用了 `self.delay_spin.value()`，改为 `self.cfg.delay_ms`

注意 `worker.py` 的 `request_delay_ms` 接口保留不动。

### 3.3 重命名云台τ标签

**文件**：`simulation/gui/window.py`

**位置**：`_build_ui` 中 `self.lbl_delay_chain` 初始化（约 L185-188）

**操作**：
```python
self.lbl_delay_chain = QtWidgets.QLabel(
    f"  链路延时: 读取{read_ms:.0f}ms → 处理{proc_ms:.0f}ms → 发送{send_ms:.0f}ms │ "
    f"云台响应τ: {tau_ms:.0f}ms（一阶惯性，非通信延时）│ 观测延迟: --ms"
)
```

`_render_tick` 中刷新 `lbl_delay_chain` 的代码（约 L840-844）也同步更新格式。

### 3.4 验证

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0
conda run -n simulation python -m unittest discover -s tests
```

**人工验证**：
- 顶部操作条左侧多了 3 个下拉
- 切换下拉后，状态栏提示"已切换 ... 已重置"，仿真重置
- 按 ALGORITHM_REGISTRY 中的不同算法运行，看 ATP 状态变化
- "应用延时"按钮已不见
- 延时链路标签清楚显示"云台响应τ"和说明

### 3.5 CHANGELOG 追加（072）

---

## Step 4：自动保存 + 世界视图 3D 信息

**目标**：仿真跑完后自动产出实验结果文件夹；俯视图能反映 z 信息。

### 4.1 扩展 state_buffer 缓冲

**文件**：`simulation/state_buffer.py`

**位置**：`UiStateBuffer.__init__`、`push`、新增方法

**操作**：

#### 4.1.1 新增字段

```python
def __init__(self, max_curve_len: int = 5000, max_frame_len: int = 240):
    # ...原有字段...
    self.metrics_log: list[dict] = []  # 不限长，保存全部
    self.event_log: list[dict] = []    # ATP 状态变迁
    self._last_atp_state_for_event: Optional[str] = None
    self._keyframe_buffers: list[dict] = []  # 存放 ATP 切换附近的帧
```

#### 4.1.2 修改 `push` 方法

在已有逻辑后追加：
```python
# 记录 metrics（每帧）
metrics_row = {
    "timestamp": t_s,
    "u_px": float(snapshot.camera.get("u_px", float("nan"))),
    "v_px": float(snapshot.camera.get("v_px", float("nan"))),
    "yaw_deg": float(snapshot.gimbal.get("yaw_deg_display", 0.0)),
    "pitch_deg": float(snapshot.gimbal.get("pitch_deg", 0.0)),
    "yaw_rate_dps": float(snapshot.gimbal.get("yaw_rate_dps", 0.0)),
    "pitch_rate_dps": float(snapshot.gimbal.get("pitch_rate_dps", 0.0)),
    "atp_state": str(snapshot.raspi.get("atp_state", "")),
    "distance_m": float(snapshot.camera.get("distance_m", 0.0)),
    "sigma_px": float(snapshot.camera.get("sigma_px", 0.0)),
    "brightness": float(snapshot.camera.get("brightness", 0.0)),
    "in_fov": bool(snapshot.camera.get("in_fov", False)),
    "backlog": int(snapshot.raspi.get("pipeline_backlog_len", 0)),
}
self.metrics_log.append(metrics_row)

# 检测 ATP 状态变迁
current_atp = str(snapshot.raspi.get("atp_state", ""))
if current_atp and current_atp != self._last_atp_state_for_event:
    if self._last_atp_state_for_event is not None:
        self.event_log.append({
            "timestamp": t_s,
            "from": self._last_atp_state_for_event,
            "to": current_atp,
        })
    self._last_atp_state_for_event = current_atp
```

#### 4.1.3 新增导出读取方法

```python
def read_full_logs(self) -> tuple[list[dict], list[dict]]:
    with self._lock:
        return list(self.metrics_log), list(self.event_log)
```

### 4.2 在 window 中实现自动保存

**文件**：`simulation/gui/window.py`

#### 4.2.1 修改 `_on_worker_finished`

```python
def _on_worker_finished(self) -> None:
    self.worker.set_paused(True)
    self._set_runtime_state(UI_TEXT["finished"], False)
    try:
        out_dir = self._export_session_results()
        self.statusBar().showMessage(f"运行完成，已自动保存到 {out_dir}", 5000)
    except Exception as e:
        self.statusBar().showMessage(f"自动保存失败: {e}", 5000)
```

#### 4.2.2 新增 `_export_session_results` 方法

```python
def _export_session_results(self) -> str:
    import json, csv
    from datetime import datetime
    from config import camera_cfg, gimbal_cfg, raspi_delay_cfg, target_cfg

    ts = int(time.time())
    out_dir = os.path.join("output", f"session_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "keyframes"), exist_ok=True)

    # 1) dashboard.png
    self.grab().save(os.path.join(out_dir, "dashboard.png"))

    # 2) metrics.csv
    metrics_log, event_log = self.state_buf.read_full_logs()
    if metrics_log:
        with open(os.path.join(out_dir, "metrics.csv"), "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(metrics_log[0].keys()))
            writer.writeheader()
            writer.writerows(metrics_log)

    # 3) event_log.json
    with open(os.path.join(out_dir, "event_log.json"), "w", encoding="utf-8") as f:
        json.dump(event_log, f, indent=2, ensure_ascii=False)

    # 4) summary.json
    summary = self._build_session_summary(ts, metrics_log, event_log)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # 5) timeline.png（截取时间轴 GroupBox）
    if hasattr(self, "timeline_container") and self.timeline_container is not None:
        pixmap = self.timeline_container.grab()
        pixmap.save(os.path.join(out_dir, "timeline.png"))

    # 6) scene_config.json
    scene_config = {
        "camera": {k: v for k, v in vars(camera_cfg).items() if not k.startswith("_")},
        "gimbal": {k: v for k, v in vars(gimbal_cfg).items() if not k.startswith("_")},
        "raspi_delay": {k: v for k, v in vars(raspi_delay_cfg).items() if not k.startswith("_")},
        "target": {k: v for k, v in vars(target_cfg).items() if not k.startswith("_")},
    }
    with open(os.path.join(out_dir, "scene_config.json"), "w", encoding="utf-8") as f:
        json.dump(scene_config, f, indent=2, ensure_ascii=False, default=str)

    # 7) keyframes/
    self._export_keyframes(os.path.join(out_dir, "keyframes"), event_log)

    return out_dir

def _build_session_summary(self, ts: int, metrics_log: list, event_log: list) -> dict:
    from datetime import datetime
    if not metrics_log:
        return {"session_id": f"session_{ts}", "duration_s": 0.0, "metrics": {}}
    
    distances = [m["distance_m"] for m in metrics_log if m["distance_m"] > 0]
    in_fov_count = sum(1 for m in metrics_log if m["in_fov"])
    pixel_errors = [
        ((m["u_px"] - 320.0)**2 + (m["v_px"] - 240.0)**2)**0.5
        for m in metrics_log
        if m["in_fov"] and m["u_px"] == m["u_px"]  # NaN guard
    ]
    
    atp_states = [m["atp_state"] for m in metrics_log if m["atp_state"]]
    state_dist = {}
    for s in atp_states:
        state_dist[s] = state_dist.get(s, 0) + 1
    total = len(atp_states) if atp_states else 1
    state_dist = {k: v/total for k, v in state_dist.items()}

    return {
        "session_id": f"session_{ts}",
        "started_at": datetime.fromtimestamp(ts).isoformat(),
        "duration_s": metrics_log[-1]["timestamp"] - metrics_log[0]["timestamp"],
        "config": {
            "control_program": self.cfg.control_program_path or "default",
            "obs_mode": self.cfg.obs_mode,
            "target_type": self.cfg.target_type or "default",
            "delay_ms": self.cfg.delay_ms,
        },
        "metrics": {
            "frame_count": len(metrics_log),
            "mean_pixel_error_px": sum(pixel_errors)/len(pixel_errors) if pixel_errors else None,
            "max_pixel_error_px": max(pixel_errors) if pixel_errors else None,
            "mean_distance_m": sum(distances)/len(distances) if distances else None,
            "in_fov_ratio": in_fov_count / len(metrics_log),
            "atp_state_distribution": state_dist,
            "atp_event_count": len(event_log),
        }
    }

def _export_keyframes(self, out_dir: str, event_log: list) -> None:
    """ATP 状态切换 ±0.5s 内每 0.1s 一帧"""
    if not event_log:
        return
    metrics_log, _ = self.state_buf.read_full_logs()
    if not metrics_log:
        return
    
    # 收集帧历史中的所有可用图像（state_buf.frame_hist）
    with self.state_buf._lock:
        frame_history = list(self.state_buf.frame_hist)
    
    if not frame_history:
        return
    
    for evt_idx, evt in enumerate(event_log):
        evt_t = evt["timestamp"]
        for offset_idx in range(-5, 6):  # ±0.5s, 步长 0.1s
            target_t = evt_t + offset_idx * 0.1
            # 找最接近的帧
            best_frame = min(frame_history, key=lambda f: abs(f.timestamp - target_t))
            if abs(best_frame.timestamp - target_t) > 0.05:  # 容忍 ±0.05s
                continue
            # 保存灰度图
            from PIL import Image
            img = Image.fromarray(best_frame.image)
            offset_str = f"{offset_idx*0.1:+.1f}".replace(".", "p").replace("+", "p").replace("-", "n")
            fname = f"event{evt_idx:02d}_{evt['from']}_to_{evt['to']}_{offset_str}.png"
            img.save(os.path.join(out_dir, fname))
```

注意 PIL 是项目可能没装的依赖。如果没有，改为 `cv2` 或 `numpy + Qt` 保存：
```python
# 不依赖 PIL 的方式
qimage = QtGui.QImage(best_frame.image.data, w, h, best_frame.image.strides[0], QtGui.QImage.Format_Grayscale8)
qimage.save(filepath)
```

### 4.3 世界视图 z 信息

**文件**：`simulation/gui/window.py`

#### 4.3.1 在 `_draw_world` 中修改目标颜色和大小

**位置**：约 L583-636

**操作**：
```python
def _draw_world(self, snapshot, x_hist: list[float], y_hist: list[float]) -> None:
    # ...原有 traj 绘制...
    
    x_m = float(snapshot.target["x_m"])
    y_m = float(snapshot.target["y_m"])
    z_m = float(snapshot.target.get("z_m", 0.0))
    
    # 按 z 编码颜色：z=0 红、z>0 偏蓝、z<0 偏黄
    z_clip = max(-30.0, min(30.0, z_m))  # 限制范围
    if z_clip >= 0:
        # 0 → 红 (#c62828), +30 → 蓝 (#1565c0)
        r = int(0xc6 + (0x15 - 0xc6) * z_clip / 30.0)
        g = int(0x28 + (0x65 - 0x28) * z_clip / 30.0)
        b = int(0x28 + (0xc0 - 0x28) * z_clip / 30.0)
    else:
        # 0 → 红, -30 → 黄 (#f9a825)
        ratio = abs(z_clip) / 30.0
        r = int(0xc6 + (0xf9 - 0xc6) * ratio)
        g = int(0x28 + (0xa8 - 0x28) * ratio)
        b = int(0x28 + (0x25 - 0x28) * ratio)
    target_color = QtGui.QColor(r, g, b)
    self.world_target_item.setPen(QtGui.QPen(target_color, 1.2))
    self.world_target_item.setBrush(QtGui.QBrush(target_color))
    
    # 按 z 编码大小：z=0 标准 5.6m，每 ±10m 增减 1m
    base_size = 5.6
    size_mult = 1.0 + 0.1 * (z_m / 10.0)
    size_mult = max(0.5, min(2.0, size_mult))
    target_size = base_size * size_mult
    self.world_target_item.setRect(-target_size/2, -target_size/2, target_size, target_size)
    self.world_target_item.setPos(x_m, y_m)
    
    # 标注 z 值（用 QGraphicsTextItem，预先在 _build_world_items 创建）
    if hasattr(self, "world_target_z_label"):
        self.world_target_z_label.setText(f"z={z_m:.1f}m")
        self.world_target_z_label.setPos(x_m + target_size, y_m)
```

#### 4.3.2 在 `_build_world_items` 中创建 z label

```python
self.world_target_z_label = QtWidgets.QGraphicsSimpleTextItem("z=0.0m")
self.world_target_z_label.setFont(QtGui.QFont("Microsoft YaHei UI", 7))
self.world_target_z_label.setBrush(QtGui.QBrush(QtGui.QColor(COLOR["text_sub"])))
scene.addItem(self.world_target_z_label)
```

#### 4.3.3 修改世界视图标题

```python
world_box = QtWidgets.QGroupBox("世界视图（俯视图 - z 编码: 高=蓝，低=黄）")
```

### 4.4 验证

```bash
# 跑一个短时仿真，确认自动保存
conda run -n simulation python app.py --mode offline --duration 5.0
ls output/session_*  # 应该有最新目录

# 检查目录内容
ls output/session_<最新>/

# 全量测试
conda run -n simulation python -m unittest discover -s tests
```

**人工验证**：
- 启动 GUI，duration 跑完后状态栏提示"已自动保存到 output/session_..."
- 检查目录有 7 类文件：dashboard.png / summary.json / metrics.csv / event_log.json / timeline.png / scene_config.json / keyframes/
- 启动 GUI，目标位置非 z=0 时，世界视图能看到颜色变化（蓝/黄）
- 目标右侧有 `z=12.3m` 之类标注

### 4.5 CHANGELOG 追加（073）

---

## 整体验证清单（4 个 Step 全部完成后）

```bash
# 1. 冒烟
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0

# 2. 全量测试
conda run -n simulation python -m unittest discover -s tests

# 3. 手动验证 GUI
conda run -n simulation python app.py --mode realtime --duration 30

# 4. 自动保存验证
conda run -n simulation python app.py --mode offline --duration 5
ls -lt output/session_* | head -1
```

**最终验收**：
- [ ] 全量 160+ tests 全部通过
- [ ] 启动 GUI 看到光斑随距离变化
- [ ] 时间轴只剩 2 子图，背景按 ATP 状态变色
- [ ] 诊断面板树状结构带单位
- [ ] 顶部 3 个下拉切换正常
- [ ] 应用延时按钮不见，延时标签解释清楚 τ
- [ ] duration 跑完后自动保存到 `output/session_*/`
- [ ] 世界视图能看到 z 信息（颜色 + 标注）

---

## 回退方案

每个 Step 完成后做 git stash 或 commit。如某 Step 验证失败：

- **Step 1 失败**：恢复 `config.py` 默认值，恢复 `camera_panel.py` 红点定义
- **Step 2 失败**：保留 `plot_atp` 子图，恢复 `QTabWidget` 诊断
- **Step 3 失败**：恢复应用延时按钮，移除下拉
- **Step 4 失败**：注释 `_export_session_results` 调用，世界视图改回固定颜色

---

*开发文档完毕。建议每个 Step 用 1 个独立的 git commit 提交，便于追溯。*
