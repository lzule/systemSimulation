# 实例体系说明

> 本文档分类整理了平台的所有标准实例，让不同目标用户都有"从哪开始"的入口。
> 场景模板的参数说明和适合验证的问题，请参见[场景模板目录](scenarios_catalog.md)。

---

## 1. 快速启动实例

**目的**：30 秒内验证平台能正常工作。

```bash
# 冒烟测试
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0
```

**预期结果**：控制台输出 `t=... yaw=... u=... in_fov=1`，无异常堆栈。

**输出位置**：控制台（无文件输出）。

---

## 2. 2D 平面基础实例

### 2.1 正弦横移

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --target-type sinusoidal
```

**关键参数**：默认振幅 15m、频率 0.2Hz（可在 `config.py` 中修改）。

### 2.2 匀速直线

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --target-type constant_velocity
```

**关键参数**：默认速度 2 m/s。

### 2.3 随机游走

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 10 --target-type random_walk
```

**关键参数**：默认 sigma 0.5m、均值回归率 0.1。

### 2.4 平面航点巡航

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 20 \
    --waypoints "(100,0,0),(80,30,0),(60,0,0)"
```

**关键参数**：航点格式 `(x,y,z)` 或 `(x,y,z,speed)`。

---

## 3. 3D 空间基础实例

### 3.1 匀速穿越（含 z 分量）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5 \
    --target-type constant_velocity
```

**说明**：默认 constant_velocity 在 3D 空间中运动，z 分量由 `velocity_z_mps` 参数控制。

### 3.2 含垂直起伏的振荡

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 10 \
    --target-type sinusoidal
```

**说明**：sinusoidal 模式支持 z 方向振幅和频率独立配置。

### 3.3 三维航点巡航

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 20 \
    --waypoints "(100,0,20,2),(80,30,10,1.5),(60,0,0,0)"
```

**关键参数**：航点含 z 分量和可选速度。

### 3.4 匀加速运动

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5 \
    --target-type constant_accel
```

**关键参数**：默认加速度 0.5 m/s²。

---

## 4. 延时退化实例

**目的**：对比不同链路延时对跟踪性能的影响。

### 4.1 无延时基线

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5
```

### 4.2 轻延时（26ms，对应场景 B2）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --delay-ms 26
```

### 4.3 中延时（52ms，对应场景 B3）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --delay-ms 52
```

### 4.4 重延时（100ms）

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --delay-ms 100
```

**预期结果**：延时越大，控制程序看到的观测越陈旧，像素误差和角度误差越大，backlog 增多。

---

## 5. Benchmark 对比实例

**目的**：完整研究流程，从跑实验到出图。

```bash
# 1. 运行 benchmark（指定两个算法对比）
conda run -n simulation python tools/run_benchmark.py \
    --algorithms atp_search_track_baseline linear_kf_tracker \
    --scenarios B1 B2 B3 --duration 20

# 2. 汇总结果
conda run -n simulation python tools/summarize_results.py

# 3. 对比
conda run -n simulation python tools/compare_results.py \
    --baseline output/experiments --new output/experiments \
    --baseline-algorithms atp_search_track_baseline --new-algorithms linear_kf_tracker

# 4. 诊断（如发现退化）
conda run -n simulation python tools/diagnose_algorithm.py \
    --algorithm linear_kf_tracker --scenario B3

# 5. 出图
conda run -n simulation python tools/plot_comparison.py \
    --algorithms atp_search_track_baseline linear_kf_tracker --plots all
```

**输出位置**：`output/experiments/` 下，含 result.json、metrics.csv、comparison.md、plots/*.png。

---

## 6. 自定义控制程序实例

### 6.1 加载内置基线控制程序

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 5 \
    --control-program entities.raspi.tracker_program:BaselineTrackerProgram
```

### 6.2 加载自定义控制程序

```bash
# 假设你写了 my_tracker.py（放在 systemSimulation/ 下）
conda run -n simulation python app.py --no-gui --mode offline --duration 5 \
    --control-program my_tracker:MyTracker
```

### 6.3 自定义控制程序 + 延时 + research 模式

```bash
conda run -n simulation python app.py --no-gui --mode offline --duration 10 \
    --control-program my_tracker:MyTracker --delay-ms 26 --obs-mode research
```

---

## 7. 观测模式对比实例

**目的**：对比三种观测模式下控制程序能获取的信息差异。

```bash
# debug 模式（全量信息，含目标真值）
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --obs-mode debug

# research 模式（不含目标真值，研究推荐）
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --obs-mode research

# realistic 模式（含传感器噪声，近真实验证）
conda run -n simulation python app.py --no-gui --mode offline --duration 5 --obs-mode realistic
```

---

## 实例之间如何配合使用

典型研究路径：

1. **先用快速启动**确认环境正常
2. **选一个 2D 实例**理解基本跟踪行为
3. **用延时实例**观察延时对性能的影响
4. **写自己的控制程序**，用自定义控制程序实例调试
5. **跑 benchmark 对比实例**做系统性评测
6. **研究工作流手册**指导后续分析

---

*实例体系完毕。详细场景模板请参见[场景模板目录](scenarios_catalog.md)。*
