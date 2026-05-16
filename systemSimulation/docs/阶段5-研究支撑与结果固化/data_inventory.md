# 阶段5数据盘点结论

> 盘点日期：2026-05-16
> 盘点目的：确认 benchmark 输出中实际记录了哪些数据，诊断工具可直接使用什么

---

## 1. 数据源结构

### 1.1 结果目录

```
output/experiments/
  └── {scenario_id}/{condition_id}/{algorithm_name}/seed_{seed}/
        ├── result.json        # 汇总指标
        ├── metrics.csv        # 逐 tick 帧级数据（~4000行/实验）
        ├── notes.md           # 实验元信息
        ├── error_curve.png    # 误差曲线图
        └── state_timeline.png # ATP 状态时间线图
```

### 1.2 汇总文件

```
output/experiments/
  ├── summary.csv          # 逐条实验汇总（每行一个 seed × algorithm × scenario）
  ├── summary_grouped.csv  # 按算法×场景分组的均值/标准差
  └── summary.json         # 结构化汇总
```

---

## 2. result.json 字段清单

```json
{
  "scenario_id": "S2",
  "condition_id": "B1",
  "algorithm_name": "atp_search_track_baseline",
  "algorithm_version": "1.0",
  "observation_mode": "research",
  "seed": 42,
  "duration_s": 20.0,
  "metrics": {
    "capture_success_rate": 1.0,
    "mean_tracking_error_px": 6.8,
    "max_tracking_error_px": 11.18,
    "lock_loss_count": 0,
    "lock_loss_rate": 0.0,
    "reacquire_time_s": null,
    "mean_settling_time_s": null,
    "tracking_efficiency": 1.0,
    "rms_pixel_error": 7.55
  },
  "atp_metrics": {
    "time_to_acquire_s": 1.6,
    "time_to_fine_track_s": 2.33,
    "state_distribution": { "TRACK_FINE": 1.0 },
    "reacquire_success_rate": null
  },
  "failure_reason": null,
  "metadata": {
    "git_hash": "00ca486",
    "generated_at": "2026-05-16T05:49:01...",
    "total_frames": 4000,
    "delay_ms": 0.0,
    "target_config": { "motion_type": "sinusoidal", ... }
  }
}
```

### 2.1 可直接用于诊断的字段

| 字段 | 用途 |
|------|------|
| `metrics.rms_pixel_error` | 回归对比核心指标 |
| `metrics.capture_success_rate` | 回归对比核心指标 |
| `metrics.tracking_efficiency` | 回归对比核心指标 |
| `metrics.lock_loss_count / lock_loss_rate` | 丢锁诊断 |
| `metrics.reacquire_time_s` | 重捕获诊断 |
| `atp_metrics.time_to_acquire_s` | 捕获速度对比 |
| `atp_metrics.time_to_fine_track_s` | 收敛速度对比 |
| `atp_metrics.state_distribution` | 状态分布对比（直接反映算法在哪个阶段） |
| `atp_metrics.reacquire_success_rate` | 重捕获成功率 |

### 2.2 关键发现：state_distribution 已可做 ATP 状态对比

例如 linear_kf_tracker 在 B3 场景的 state_distribution：
```json
{ "TRACK_COARSE": 0.1994, "REACQUIRE": 0.5267, "SEARCH": 0.2669, "ACQUIRE": 0.007 }
```
而 atp_search_track_baseline 在 B1 场景：
```json
{ "TRACK_FINE": 1.0 }
```
这种差异直接说明问题所在。

---

## 3. metrics.csv 字段清单

```
timestamp, pixel_error_x, pixel_error_y, pixel_error_total, detection_found, atp_state, yaw_rate_cmd, pitch_rate_cmd
```

| 列名 | 类型 | 用途 |
|------|------|------|
| `timestamp` | float | 时间轴（用于分段、画图） |
| `pixel_error_x` | float | 水平像素误差（可分解轴向） |
| `pixel_error_y` | float | 垂直像素误差 |
| `pixel_error_total` | float | 总像素误差（核心诊断指标） |
| `detection_found` | bool | 是否检测到目标（丢锁判断） |
| `atp_state` | str | ATP 当前状态（SEARCH/ACQUIRE/TRACK_COARSE/TRACK_FINE/LOST/REACQUIRE） |
| `yaw_rate_cmd` | float | yaw 控制命令（deg/s） |
| `pitch_rate_cmd` | float | pitch 控制命令（deg/s） |

每实验约 4000 行（对应 4000 frames × 20s × 200fps）。

### 3.1 关键发现：metrics.csv 已覆盖 4 个诊断维度中的 3 个直接数据源，并为第 4 个维度提供了可用代理信号

这是一个**比预期好得多**的结果。盘点前原以为控制命令和 ATP 状态序列可能没有记录，但实际上：

- **维度1：误差分时段分解** — `pixel_error_total + atp_state + timestamp` 完全覆盖
- **维度2：ATP 状态转换对比** — `atp_state` 逐 tick 记录，可直接提取转换序列、驻留时长
- **维度3：控制行为对比** — `yaw_rate_cmd + pitch_rate_cmd` 逐 tick 记录，可分析振荡/饱和
- **维度4：预测相关分析** — `pixel_error_total` 结合 `atp_state` 可推断预测偏差趋势；但**当前没有预测量 vs 真值的直接对比数据**，因此这一维度属于**代理分析**，不是直接预测误差分析

---

## 4. 汇总文件可用性

### summary.csv
- 每行：一个 seed × algorithm × scenario 的关键指标
- 列：algorithm_name, condition_id, seed, obs_mode, capture_success_rate, mean_tracking_error_px, max_tracking_error_px, rms_pixel_error, lock_loss_count, lock_loss_rate, tracking_efficiency, mean_settling_time_s, time_to_acquire_s, time_to_fine_track_s, failure_reason
- **可直接用于回归对比**：按 algorithm + condition_id 分组对比即可

### summary_grouped.csv
- 每行：一个 algorithm × scenario 的均值和标准差
- 包含 rms_pixel_error_mean/std, capture_success_rate_mean, tracking_efficiency_mean 等
- **可直接用于跨算法排名和热力图**

---

## 5. 盘点结论

### 5.1 各诊断维度可行性判定

| 诊断维度 | 数据是否充足 | 数据来源 | 额外工作 |
|----------|------------|----------|----------|
| 误差分时段分解 | **充足** | metrics.csv: atp_state + pixel_error_total + timestamp | 无需改动 |
| ATP 状态转换对比 | **充足** | metrics.csv: atp_state 逐 tick；result.json: state_distribution | 无需改动 |
| 控制行为对比 | **充足** | metrics.csv: yaw_rate_cmd + pitch_rate_cmd | 无需改动 |
| 预测相关分析 | **部分充足** | metrics.csv: pixel_error 趋势可间接推断；无预测量 vs 真值直接对比 | 无需补充字段，但对外表述应明确为“代理分析” |

### 5.2 回归对比可行性

| 需求 | 数据是否充足 | 数据来源 |
|------|------------|----------|
| 指标差异表 | **充足** | summary.csv |
| 提升项/退化项标注 | **充足** | summary.csv 对比 |
| 超阈值报警 | **充足** | summary.csv + 阈值配置 |
| 按 algorithm × scenario 对比 | **充足** | summary_grouped.csv |

### 5.3 是否需要补充 benchmark 记录字段

**不需要。**

当前 `metrics.csv` 已逐 tick 记录了 ATP 状态和控制命令，`result.json` 已记录了汇总指标和状态分布。阶段5所需能力均可基于现有数据实现，其中预测相关维度应明确采用“代理分析”口径。

无需修改 `run_benchmark.py`，无需新增记录字段，无需重跑已有实验。

### 5.4 对阶段5实施的影响

1. **A1 回归对比**：直接基于 summary.csv 和 result.json 实现，零改动
2. **A2 算法诊断**：4 个维度均可落地，其中预测维度采用误差趋势代理分析
3. **C 实验记录**：无需依赖数据盘点结论
4. **B 对比可视化**：metrics.csv 和 summary_grouped.csv 均可作为数据源

**结论：所有 4 个诊断维度均可落地；其中前 3 个属于直接分析，第 4 个属于代理分析。无需新增字段，但对文档和报告表述应保持这一口径。**

---

*盘点完毕。本文件为阶段5数据盘点的正式结论。*
