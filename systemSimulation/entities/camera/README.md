# Camera 实体文档

> 本文档讲述 Camera 实体的内部机制。如需了解与其他实体的组合使用，参见 [主 README](../../README.md)。

## 1. 概述与角色定位

相机实体，挂载在云台上，模拟成像过程。特点：

- 有电源状态机（OFF → BOOTING → READY）
- **需要 target_state 和 gimbal_state 作为输入**（Runtime tick 中唯一有此依赖的实体）
- 内部采用针孔相机模型 + 高斯光斑渲染
- 支持变焦控制（一阶惯性执行器）

> **阶段2升级**：相机投影模型已从单轴（仅 u 坐标有效，v 硬编码为 h/2）升级为双轴投影。v 坐标现在通过俯仰角 beta 真实计算：`v = cy - f_px * tan(beta)`。FOV 判断也升级为双轴（水平 fov_h_deg + 垂直 fov_v_deg），目标需同时在两个方向上处于视场内才判定为 in_fov。

输出：
- `CameraState`：状态字典（焦距、帧号、目标像素位置 u_px/v_px 等）
- `FramePacket`：渲染帧（灰度图 + 内参 + 可选 ground truth）

## 2. 文件结构

```
entities/camera/
├─ entity.py      # CameraEntity + CameraState + detect_beacon_centroid
├─ model.py       # CameraImagingModel（针孔模型 + 光斑渲染）
├─ control.py     # ZoomController（一阶惯性变焦）
├─ client.py      # CameraClient
└─ tests/
    └─ test_camera_entity.py
```

## 3. 状态机

```
OFF ──power_on()──> BOOTING (0.5s) ──boot_remaining<=0──> READY
                                                        │
BOOTING/READY ──power_off()──> OFF (清空帧缓冲和变焦速率)
```

启动时间仅 0.5s，是四个实体中最短的。

## 4. 配置参数

### CameraConfig

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `resolution_w` | int | `640` | 图像宽度（像素） |
| `resolution_h` | int | `480` | 图像高度（像素） |
| `sensor_w_mm` | float | `4.8` | 传感器宽度（毫米） |
| `sensor_h_mm` | float | `3.6` | 传感器高度（毫米） |
| `focal_length_mm` | float | `12.0` | 初始焦距（毫米） |
| `focal_min_mm` | float | `4.4` | 最短焦距 |
| `focal_max_mm` | float | `200.0` | 最长焦距 |
| `fov_v_deg` | float | `0.0` | 垂直视场角（度），0 表示自动从焦距和传感器尺寸计算（阶段2新增） |

### ZoomController 内部参数

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `tau_s` | `0.2` | 一阶惯性时间常数（秒） |
| `max_rate_mmps` | `120.0` | 最大变焦速率（毫米/秒） |

### SceneConfig（成像相关）

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `pixel_noise_std` | `0.5` | 帧噪声标准差（灰度值） |

## 5. 内部模型详解

### 5.1 针孔成像模型 CameraImagingModel

核心公式链：

```
pixel_size_mm = sensor_w_mm / resolution_w
f_px = f_mm / pixel_size_mm
fov_h_half_rad = atan(sensor_w_mm / (2 * f_mm))
fov_v_half_rad = atan(sensor_h_mm / (2 * f_mm))
```

> **阶段2升级**：投影模型已从单轴升级为双轴。

目标成像条件（双轴）：
- 水平：`|alpha_rad| <= fov_h_half_rad`（alpha = azimuth - yaw）
- 垂直：`|beta_rad| <= fov_v_half_rad`（beta = elevation - pitch）

像素位置（双轴）：
- `u = f_px * tan(alpha) + cx`（水平方向，cx = w/2）
- `v = cy - f_px * tan(beta)`（垂直方向，cy = h/2，beta>0 表示目标在上方）

### 5.2 高斯光斑渲染

当目标在视场内时，渲染一个 2D 高斯光斑模拟点目标：

```python
sigma = 3.2 像素
blob[y, x] = exp(-0.5 * ((x - u)/sigma)²) * exp(-0.5 * ((y - v)/sigma)²)
frame = clip(blob * 255, 0, 255).astype(uint8)
frame += N(0, pixel_noise_std)   # 叠加高斯噪声
```

### 5.3 变焦控制器 ZoomController

两种模式：

**有速率指令时**（`set_zoom_rate_mmps`）：
```python
f_current += clip(rate_cmd, -max_rate, +max_rate) * dt
```

**无速率指令时**（`set_zoom_target_mm`）：
```python
alpha = dt / (tau_s + dt)
f_current = (1 - alpha) * f_current + alpha * f_target   # 一阶惯性趋近目标
```

### 5.4 质心检测 detect_beacon_centroid

对帧做阈值分割（`threshold=180`），返回 `Detection(found, cx, cy, confidence)`。

## 6. 数据流

```
target_state (x_m, y_m, z_m) ──┐
                                ├──> CameraEntity.update(dt, ts, target_state, gimbal_state)
gimbal_state (yaw_deg, pitch_deg) ──┘         │
                                     ├─ _update_zoom(dt)          -- 变焦推进
                                     ├─ azimuth = atan2(y, x)
                                     ├─ elevation = atan2(z, hypot(x, y))
                                     ├─ alpha = (azimuth - yaw + π) % 2π - π
                                     ├─ beta = (elevation - pitch + π) % 2π - π
                                     ├─ render_beacon_frame(alpha, beta, f_mm)
                                     │       │
                                     │   FramePacket(image, intrinsics, optional_gt)
                                     │       ├─ intrinsics: f_mm, f_px, cx, cy, width, height
                                     │       └─ optional_gt: u_px, v_px, in_fov (精确值)
                                     │
                                CameraState ──> get_state() ──> dict
```

**关键说明**：Camera.update() 是唯一需要其他两个实体状态作为参数的实体。这是因为在 tick 顺序中 Camera 排在 Target 和 Gimbal 之后，可以直接使用它们的状态。

## 7. Client API

`CameraClient`（`entities/camera/client.py`）：

| 方法 | 参数 | 说明 |
|------|------|------|
| `power_on(timestamp?)` | — | 上电，0.5s 后 READY |
| `power_off(timestamp?)` | — | 关机，清空帧 |
| `set_zoom_target_mm(f_mm, timestamp?)` | 毫米 | 设置目标焦距，限幅到 `[4.4, 200]` |
| `zoom_by(delta_mm, timestamp?)` | 毫米 | 相对变焦（等价于 `set_zoom_target_mm(current + delta)`） |
| `set_zoom_rate_mmps(rate, timestamp?)` | mm/s | 恒速变焦，覆盖目标跟踪模式 |
| `get_camera_state() -> dict` | — | 完整状态字典 |
| `get_frame() -> FramePacket` | — | 最新渲染帧（含图像、内参、可选 GT） |

代码示例：

```python
from runtime.digital_twin_runtime import DigitalTwinRuntime

rt = DigitalTwinRuntime()
cc = rt.camera_client

cc.power_on()
# 等待 READY...

# 设置目标焦距
cc.set_zoom_target_mm(f_mm=50.0)

# 相对变焦
cc.zoom_by(delta_mm=5.0)

# 按速率变焦
cc.set_zoom_rate_mmps(rate_mmps=30.0)

# 获取帧
frame = cc.get_frame()
if frame is not None:
    print(f"帧大小: {frame.image.shape}")
    print(f"内参: {frame.intrinsics}")
```

## 8. 调试与排错

| 问题 | 排查 |
|------|------|
| 全黑帧 | 检查 `in_fov` 是否为 True；目标可能不在视场内 |
| `u_px` 为 NaN | 目标不在视场内，正常行为 |
| 焦距不变化 | 检查目标值是否在 `[focal_min, focal_max]` 范围内 |
| 帧无目标但 in_fov=True | 检查光斑是否落在图像边界外（u 坐标在 [0, w) 之外时光斑不渲染但 in_fov 仍为 True） |
| NOT_READY | Camera boot 仅 0.5s；如持续不 READY 检查是否调用了 power_on |
| 噪声过大 | 调整 `SceneConfig.pixel_noise_std`（默认 0.5） |

## 9. 扩展点

- **替换成像模型**：修改 `CameraImagingModel.render_beacon_frame()`，例如加入畸变模型
- **多目标渲染**：修改渲染函数支持多个光斑
- **自动对焦**：实现新的控制程序，根据像素误差自动调整焦距
- **彩色成像**：将灰度渲染改为 RGB，修改 `FramePacket.image` 的维度

## 10. 测试

```bash
conda run -n simulation python -m unittest discover -s entities\camera\tests -p "test_*.py" -v
```
