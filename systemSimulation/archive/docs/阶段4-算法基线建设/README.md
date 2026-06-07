# 阶段4-算法基线建设

本目录用于存放阶段 4「算法基线建设」的实施前计划、技术说明、benchmark 结果说明和阶段总结。

当前文件：

- `阶段4详细开发计划.md`：阶段 4 执行前详细开发计划文档

## 已实现模块

### 算法框架
- `entities/raspi/atp_state_machine.py` — ATP状态机（6状态，光栅扫描）
- `entities/raspi/atp_control_program.py` — ATP控制程序（状态机+可插拔tracker/predictor）
- `config.py` — 新增 `ATPStateMachineConfig`

### 跟踪策略（entities/raspi/trackers/）
- `rate_p_tracker.py` — 速率P控制器（baseline_rate_p）
- `rate_pi_tracker.py` — 速率PI控制器
- `angle_mode_tracker.py` — 角度模式控制器（仅realistic）

### 预测策略（entities/raspi/predictors/）
- `alpha_beta.py` — Alpha-Beta滤波器
- `linear_kf.py` — 线性卡尔曼滤波器

### Benchmark工具（tools/）
- `run_benchmark.py` — 标准化benchmark运行工具
- `summarize_results.py` — 结果汇总与排名工具
