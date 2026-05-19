# 相机模型与 UI 同步问题方案

## 问题背景

用户反馈：相机模型中存在"目标光源距离越近越大、越远越小"的物理模型，但当前 UI 没有体现这一点。

## 现状盘点

### 1. 物理模型（已实现）

`entities/camera/model.py:25-78` 的 `render_beacon_frame()` 实现了距离相关的光斑成像：

**距离相关 sigma**（光斑大小）`model.py:28-34`：
```python
sigma_base = self.cfg.beacon_sigma_px  # 默认 3.2 px
if self.cfg.sigma_ref_distance_m > 0.0 and distance_m > 0.0:
    sigma = sigma_base / (1.0 + distance_m / self.cfg.sigma_ref_distance_m)
else:
    sigma = sigma_base
```
- 距离越远，sigma 越小（光斑越小）
- 距离越近，sigma 越接近 base（光斑越大）
- 当 `sigma_ref_distance_m=0`（默认）时，sigma 固定为 `beacon_sigma_px`

**距离相关亮度** `model.py:60-64`：
```python
if self.cfg.brightness_ref_distance_m > 0.0 and distance_m > 0.0:
    brightness = self.cfg.brightness_base / (1.0 + distance_m / self.cfg.brightness_ref_distance_m)
else:
    brightness = self.cfg.brightness_base
```
- 距离越远，亮度越低；距离越近，亮度越高

**距离相关丢检概率** `model.py:50-57`：
- sigma 越小，丢检概率越高（远处目标更容易丢失）

**最终成像** `model.py:69-74`：
```python
gx = np.exp(-0.5 * ((xs - u) / sigma) ** 2)
gy = np.exp(-0.5 * ((ys - v) / sigma) ** 2)
blob = np.outer(gy, gx)
frame = np.clip(blob * brightness * 255.0, 0.0, 255.0).astype(np.uint8)
```

光斑是真实绘制到 `frame: numpy uint8` 数组中的 2D 高斯，相机图像（`CameraImageView.update_frame`）就是这个数组的可视化。

### 2. UI 渲染层（部分缺失同步）

| 组件 | 文件 | 现状 | 评估 |
|------|------|------|------|
| 相机图像本身 | `panels/camera_panel.py` | 显示完整 numpy 帧 | **正确** — 高斯光斑随距离变化自然显现 |
| 相机视角 target_item | `panels/camera_panel.py:35-38` | 硬编码 `6×6` px 圆圈 | **错误** — 不随 sigma/距离变化 |
| 世界视图 target_item | `window.py` 世界视图 | 硬编码 `5.6×5.6` m 圆圈 | 可接受 — 世界视图是俯视图，目标物理大小本就不大 |
| `WorldSnapshot.camera` | `entities/camera/entity.py:165-177` | 仅暴露 `u_px/v_px/in_fov/f_current_mm/frame_id` | **缺失** — 没有 `sigma_px`、`distance_m`、`brightness` |
| 诊断面板 camera | `window.py` `_update_diag_tab` | 仅显示 `f_current_mm/frame_id/u_px/v_px/in_fov/raw_frame_ts/raspi_frame_ts` | **缺失** — 没有距离、sigma、亮度 |
| 状态卡片 / 摘要条 | `window.py` `_build_cards/_build_summary` | 没有距离 | **缺失** — 距离是关键物理量，应能一眼看到 |

### 3. 关键问题：`target_item` 覆盖层

`camera_panel.py:35-38`：
```python
self.target_item = QtWidgets.QGraphicsEllipseItem(-3.0, -3.0, 6.0, 6.0)
```

这个红色圆圈叠加在相机图像之上，标记检测中心位置。它的作用本是"标识目标位置"，但目前是固定 6 px。

**两种解读视角：**
- **如果它是"检测标记"**：固定大小是合理的（标识中心位置即可），但用户看的是"光源大小"，不是这个 marker。**真实光源大小由 numpy 帧本身的高斯亮斑表达**，已经随距离变化了。
- **如果它是"光源轮廓"**：那它就该和 sigma 同步缩放，反映真实物理大小。

**实际验证**：让相机图像本身（numpy 帧）来表达光斑大小，这是物理正确的。`target_item` 应该作为辅助检测标记保留小尺寸，或者改为 sigma 缩放的"轮廓圈"。

## 解决方案

### 改动一：暴露物理量到 snapshot（核心修复）

**目的**：让 UI 能拿到真实的物理量（距离、sigma、亮度），而不是只能看到 `u_px/v_px`。

**修改文件**：
- `entities/camera/model.py` — `render_beacon_frame()` 返回值扩展为带 `sigma_px/brightness/distance_m`
- `entities/camera/entity.py` — `CameraState` dataclass 扩展，`update()` 写入新字段，`get_state()` 暴露
- `runtime/digital_twin_runtime.py` — 通过 `__dict__.copy()` 自动传播（无需改）

**新增字段**：
```python
@dataclass
class CameraState:
    # ... 已有字段 ...
    distance_m: float       # 目标到原点的 3D 距离
    sigma_px: float         # 当前帧实际渲染使用的 sigma
    brightness: float       # 当前帧实际亮度（0-1）
```

### 改动二：UI 显示距离与光斑大小

**目的**：让用户能在 UI 里直观看到"目标越远越小"这一物理现象的具体数值。

**修改文件**：`simulation/gui/window.py`

**A. 状态摘要条（顶部）** — 新增 `distance` 字段
```
顶部摘要: ▶运行中  t=12.5s  距离=125.3m  ATP=TRACK_FINE  ...
```

**B. 状态卡片（右侧）** — 新增第 4 张卡片
```
[像素误差 12.3] [角度误差 5.2°] [距离 125.3m] [backlog 1]
```
（用户之前说一行三列太小要去掉 in_fov，现在距离比 backlog 更重要，但保留 backlog 也合理。建议：一行四列或者把 backlog 换成 距离）

**C. 诊断面板 camera 标签页** — 新增 3 个字段
```
distance_m: 125.3
sigma_px: 1.42      （越远越小，与物理模型一致）
brightness: 0.73    （越远越暗）
```

### 改动三：相机视角的 target_item 改为 sigma 同步

**目的**：让相机视图上的红色 marker 真实反映光斑大小，与底层成像保持一致。

**修改文件**：`simulation/gui/panels/camera_panel.py`

**方案**：
- `target_item` 改为外径 = 3×sigma 的圆圈（覆盖高斯光斑的 99.7% 强度区域）
- 颜色保持红色，但改为 1px 描边、空心，不遮挡底层光斑
- 在 `update_frame()` 中接收 `sigma_px` 参数，动态更新半径

**简化方案**（如果不想改接口）：
- 保留 `target_item` 不变（继续作为固定大小的检测中心标记）
- 加一个独立的 `target_outline_item`（空心圆，半径 = 3×sigma），作为"光斑轮廓圈"
- 用户能同时看到中心点和光斑大小

### 改动四：state_buffer 历史记录（可选）

**目的**：如果想在时间轴上看距离/sigma 的变化趋势。

**评估**：当前需求是"在 UI 上显示"，不是"画曲线"。距离已经能从 target.x/y/z 推算，画曲线不是当前痛点。**本次不做**。

## 用户决策点

实施前需要确认的几个选择：

### Q1: 状态卡片要不要把 backlog 换成距离？

- **A1**：把 backlog 换成"距离"（距离更直观，backlog 已在顶部摘要条显示）
- **A2**：保留 backlog，把指标条改回 4 列（像素误差 / 角度误差 / 距离 / backlog）
- **A3**：保留 3 列，加距离作为新摘要条字段

### Q2: 相机视角的红色 marker 怎么处理？

- **B1**：保留固定大小（继续作为"检测中心标记"），不动它
- **B2**：改为 sigma 同步（外径 = 3×sigma，颜色变浅、空心），真实反映光斑大小
- **B3**：保留固定 marker + 新增空心轮廓圈（双重标记）

### Q3: 距离格式

- **C1**：`125.3m`（一位小数）
- **C2**：`125m`（整数，更紧凑）
- **C3**：`125.3 m / sigma=1.4px`（一起显示）

## 验证方案

1. 单元测试：在 `tests/test_runtime_api.py` 增加测试 — `snap.camera` 包含 `distance_m/sigma_px/brightness`
2. 手动验证：启动 GUI，用 sinusoidal 目标观察距离变化时光斑大小的视觉变化
3. 配置测试：把 `sigma_ref_distance_m` 改为非零（比如 50.0），运行后观察 sigma_px 随 distance_m 的变化关系是否符合公式
4. 全量测试：158 tests 通过

## 涉及文件汇总

| 文件 | 改动类型 |
|------|---------|
| `entities/camera/model.py` | `render_beacon_frame()` 返回值扩展 |
| `entities/camera/entity.py` | `CameraState` dataclass + `get_state()` 扩展 |
| `simulation/gui/window.py` | 摘要条/卡片/诊断面板新增字段 |
| `simulation/gui/panels/camera_panel.py` | target_item 大小同步（取决于 Q2） |
| `tests/test_runtime_api.py` | 新增 snap.camera 字段验证 |
| `CHANGELOG.md` | 记录本次改动 |

---

*等待用户确认 Q1/Q2/Q3 后开始实施。*
