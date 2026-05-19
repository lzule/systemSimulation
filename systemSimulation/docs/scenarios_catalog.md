# 典型场景模板目录

> 每个模板都经过真实运行验证，可直接复制命令执行。
> 实例分类说明请参见[实例体系说明](examples_guide.md)。

---

## 2D 模板

### 模板 1：匀速直线（constant_velocity）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5 \
    --target-type constant_velocity
```

| 项目 | 说明 |
|------|------|
| 运动类型 | `constant_velocity` |
| 默认参数 | 速度 2 m/s，方向 0° |
| 适合验证 | 基础跟踪能力、稳态误差、P 控制器调参 |
| 预期现象 | 目标匀速移动，控制程序应能持续跟踪，像素误差收敛并保持稳定 |
| 输出 | 控制台输出 yaw/u/in_fov |

### 模板 2：正弦横移（sinusoidal）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 10 \
    --target-type sinusoidal
```

| 项目 | 说明 |
|------|------|
| 运动类型 | `sinusoidal` |
| 默认参数 | 振幅 15m，频率 0.2Hz |
| 适合验证 | 动态响应、跟踪器延迟补偿、PI 控制器效果 |
| 预期现象 | 目标周期性横移，跟踪误差呈周期性波动；PI 控制器应比 P 控制器更好地跟随 |
| 输出 | 控制台输出 |

### 模板 3：随机游走（random_walk）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 10 \
    --target-type random_walk
```

| 项目 | 说明 |
|------|------|
| 运动类型 | `random_walk` |
| 默认参数 | sigma 0.5m，均值回归率 0.1 |
| 适合验证 | 不确定性处理、预测器效果（α-β vs 卡尔曼）、鲁棒性 |
| 预期现象 | 目标随机运动，纯 P 控制器会有稳态误差；加入预测器后误差应减小 |
| 输出 | 控制台输出 |

### 模板 4：平面航点巡航（waypoint）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 20 \
    --waypoints "(100,0,0),(80,30,0),(60,0,0),(100,0,0)"
```

| 项目 | 说明 |
|------|------|
| 运动类型 | `waypoint` |
| 关键参数 | 航点序列 `(x,y,z)` 或 `(x,y,z,speed)` |
| 适合验证 | 路径跟踪、转弯处理、航点切换瞬态 |
| 预期现象 | 目标按航点移动，转弯时跟踪误差短暂增大，直线路段收敛 |
| 输出 | 控制台输出 |

---

## 3D 模板

### 模板 5：匀速穿越（constant_velocity，含 z 分量）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5 \
    --target-type constant_velocity
```

| 项目 | 说明 |
|------|------|
| 运动类型 | `constant_velocity`（3D 空间） |
| 关键参数 | `velocity_z_mps`（在 config.py 中设置） |
| 适合验证 | 3D 跟踪基础、双轴协调（yaw+pitch 同时响应） |
| 预期现象 | pitch 轴开始参与跟踪，u 和 v 像素误差同时变化 |
| 输出 | 控制台输出 |

### 模板 6：含垂直起伏的振荡（sinusoidal，3D）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 10 \
    --target-type sinusoidal
```

| 项目 | 说明 |
|------|------|
| 运动类型 | `sinusoidal`（3D 空间） |
| 关键参数 | z 方向振幅/频率在 config.py 中独立配置 |
| 适合验证 | 双轴协调、pitch 控制器调参、3D 动态响应 |
| 预期现象 | yaw 和 pitch 同时呈周期性波动，双轴控制器应协调工作 |
| 输出 | 控制台输出 |

### 模板 7：三维航点巡航（waypoint，3D）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 20 \
    --waypoints "(100,0,20,2),(80,30,10,1.5),(60,0,0,0),(100,0,20,2)"
```

| 项目 | 说明 |
|------|------|
| 运动类型 | `waypoint`（3D 航点） |
| 关键参数 | 航点含 x/y/z 和速度 |
| 适合验证 | 3D 路径跟踪、高度变化适应性、预测器在变高度场景的效果 |
| 预期现象 | 目标在不同高度间切换，pitch 轴在高度变化时产生较大误差 |
| 输出 | 控制台输出 |

### 模板 8：接近/远离类运动（constant_accel）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 10 \
    --target-type constant_accel
```

| 项目 | 说明 |
|------|------|
| 运动类型 | `constant_accel` |
| 关键参数 | 加速度、初始速度 |
| 适合验证 | 距离变化适应性、变焦控制、预测器在加速场景的效果 |
| 预期现象 | 目标加速远离或接近，像素误差随距离变化（远距离误差大、近距离误差小） |
| 输出 | 控制台输出 |

---

## 延时对比模板

### 无延时基线 → 轻延时 → 中延时

```bash
# 基线（0ms）
conda run -n simulation python app.py --no-gui --mode offline --duration 5

# 轻延时（26ms，对应 benchmark 场景 B2）
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --delay-ms 26

# 中延时（52ms，对应 benchmark 场景 B3）
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --delay-ms 52
```

**适合验证**：延时对跟踪性能的影响、不同算法的延时鲁棒性。

---

## Benchmark 标准场景

平台内置 3 个标准 benchmark 场景：

| 场景 | 运动类型 | 初始距离 | 振幅 | 延时 | 说明 |
|------|---------|---------|------|------|------|
| B1 | sinusoidal | 100m | 15m | 0ms | 基线对照 |
| B2 | sinusoidal | 100m | 15m | 26ms | 轻非理想验证 |
| B3 | sinusoidal | 80m | 20m | 52ms | 中难度比较 |

```bash
# 跑全部场景
conda run -n simulation python tools/run_benchmark.py --scenarios B1 B2 B3

# 只跑基线对照
conda run -n simulation python tools/run_benchmark.py --scenarios B1
```

---

*场景模板目录完毕。以上所有模板均已验证可运行。*
