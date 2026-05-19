# 文档体系导航

本项目的文档分为四层：入口索引（README）、系统主手册（docs/system_manual.md）、专项手册、实体原理（各实体 README）。

阶段性开发文档统一按 `docs/阶段N-阶段名/` 归档，不再承担当前主手册职责。

---

## 按角色导航

| 角色 | 推荐阅读顺序 |
|------|------------|
| 研究使用者 | [系统主手册](system_manual.md) → [研究工作流手册](research_workflow.md) → [工具手册](tools_guide.md) |
| 新接手人员 | [系统主手册](system_manual.md) → 各实体 README → [ATP 开发文档](低空场景无线光通信ATP开发文档.md) |
| 算法开发者 | [系统主手册](system_manual.md) → [树莓派控制程序开发手册](树莓派控制程序开发手册.md) → [算法接入指南](algorithm_integration_guide.md) |
| 项目维护者 | [系统主手册](system_manual.md) → [维护规则](maintenance_guide.md) → 本文档 |

## 按任务导航

| 任务 | 推荐阅读 |
|------|---------|
| 第一次运行 | [系统主手册 §3 快速启动](system_manual.md) |
| 跑 benchmark | [研究工作流手册](research_workflow.md) |
| 对比两个算法 | [研究工作流手册 §3](research_workflow.md) |
| 诊断算法退化 | [研究工作流手册 §4](research_workflow.md) |
| 做角度曲线实验 | [额外实验-角度曲线实验方案](额外实验-角度曲线/角度曲线实验方案.md) |
| 写自己的控制程序 | [树莓派控制程序开发手册](树莓派控制程序开发手册.md) |
| 把算法注册到 benchmark | [算法接入指南](algorithm_integration_guide.md) |
| 新增工具或场景 | [维护规则](maintenance_guide.md) |

---

## 核心文档

| 文档 | 路径 | 职责 |
|------|------|------|
| **主 README** | [README.md](../README.md) | 入口索引 + 快速启动 |
| **系统主手册** | [docs/system_manual.md](system_manual.md) | 平台完整使用说明 |
| **研究工作流手册** | [docs/research_workflow.md](research_workflow.md) | benchmark → 对比 → 诊断 → 出图完整链路 |
| **工具手册** | [docs/tools_guide.md](tools_guide.md) | 16 个工具详细说明 |
| **算法接入指南** | [docs/algorithm_integration_guide.md](algorithm_integration_guide.md) | 4 种算法接入方式 |
| **树莓派控制程序开发手册** | [docs/树莓派控制程序开发手册.md](树莓派控制程序开发手册.md) | 控制程序编写、接入、调试、测试完整教程 |
| **ATP 开发文档** | [docs/低空场景无线光通信ATP开发文档.md](低空场景无线光通信ATP开发文档.md) | ATP 总路线图、6 阶段任务、验收闸门 |
| **维护规则** | [docs/maintenance_guide.md](maintenance_guide.md) | 后续维护检查清单 |
| **阶段6 盘点清单** | [docs/阶段6-系统手册与维护/阶段6盘点清单.md](阶段6-系统手册与维护/阶段6盘点清单.md) | 文档/工具/GUI 真实现状盘点 |

## 实体文档

| 文档 | 路径 | 核心内容 |
|------|------|---------|
| **Target** | [entities/target/README.md](../entities/target/README.md) | 5 种运动模式、3D 运动学、参数表 |
| **Gimbal** | [entities/gimbal/README.md](../entities/gimbal/README.md) | 串级 PID、双轴状态机、非理想参数 |
| **Camera** | [entities/camera/README.md](../entities/camera/README.md) | 双轴针孔成像、变焦控制、近真实渲染 |
| **Raspi** | [entities/raspi/README.md](../entities/raspi/README.md) | 延时管线、ControlProgram 协议、基线跟踪 |
| **Runtime** | [runtime/README.md](../runtime/README.md) | tick 调度、命令总线、Client 绑定 |

## 阶段文档（归档）

| 阶段 | 文档 | 说明 |
|------|------|------|
| 阶段0 | [基线收口](阶段0-基线收口/) | 基线能力清单、研究基线配置、问题与建议 |
| 阶段1 | [问题定义冻结](阶段1-问题定义冻结/) | 场景矩阵、指标体系、观测模式、实验输出规范等 7 篇 |
| 阶段2 | [双轴ATP升级](阶段2-双轴ATP升级/) | 详细开发计划、坐标系定义 |
| 阶段3 | [近真实建模](阶段3-近真实建模/) | 详细开发计划 |
| 阶段4 | [算法基线建设](阶段4-算法基线建设/) | README、详细开发计划 |
| 阶段5 | [研究支撑与结果固化](阶段5-研究支撑与结果固化/) | 需求文档、详细计划、数据盘点、审核意见 |
| 阶段6 | [系统手册与维护](阶段6-系统手册与维护/) | 需求文档、详细计划、盘点清单 |

## 审阅文档

| 文档 | 说明 |
|------|------|
| [仿真系统项目审阅与优化建议.md](仿真系统项目审阅与优化建议.md) | Codex 高层概览审阅 |
| [仿真系统深度技术审阅.md](仿真系统深度技术审阅.md) | 逐节评估 + 深度技术审阅 |

---

## 知识点归属

| 知识点 | 唯一归属文档 |
|--------|-------------|
| 平台整体使用 | docs/system_manual.md |
| 研究工作流 | docs/research_workflow.md |
| 工具使用说明 | docs/tools_guide.md |
| 算法接入 | docs/algorithm_integration_guide.md |
| 控制程序编写 | docs/树莓派控制程序开发手册.md |
| Target 5 种运动模式 | entities/target/README.md |
| Gimbal 串级 PID | entities/gimbal/README.md |
| Camera 双轴针孔模型 | entities/camera/README.md |
| Raspi 延时管线 + ATP | entities/raspi/README.md |
| tick 调度 / 命令总线 | runtime/README.md |
| ATP 阶段开发路线 | docs/低空场景无线光通信ATP开发文档.md |
| 维护规则 | docs/maintenance_guide.md |
| 阶段0-5 开发记录 | docs/阶段N-*/*.md |

---

## 阅读建议

## 补充文档

| 文档 | 说明 |
|------|------|
| [GUI重设计方案.md](阶段6-系统手册与维护/GUI重设计方案.md) | GUI 重构正式设计文档，包含布局示意、约束边界、开发拆分和验收标准 |

**新成员入门**：
1. [README](../README.md) — 了解系统是什么
2. [系统主手册](system_manual.md) — 跑通第一次运行
3. 按角色找到对应专项手册

**修改代码时**：
1. 先看对应实体的 README 了解内部机制
2. 修改后更新该实体 README
3. 按[维护规则](maintenance_guide.md)同步相关文档
