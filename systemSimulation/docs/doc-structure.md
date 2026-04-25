# 文档体系导航

本项目的文档分为三层：组合使用（README）、实体原理（各实体 README）、操作手册（docs/）。

## 文档列表

| 文档 | 路径 | 职责 |
|------|------|------|
| **主 README** | [README.md](../README.md) | 系统架构、实体间数据流、组装联调、控制程序开发、延时仿真 |
| **使用手册** | [docs/使用手册.md](使用手册.md) | 快速入门、单实体测试、代码规范、验收清单 |
| **Target 文档** | [entities/target/README.md](../entities/target/README.md) | 4 种运动模式、参数表、运动学模型、扩展点 |
| **Gimbal 文档** | [entities/gimbal/README.md](../entities/gimbal/README.md) | 串级 PID 控制器、状态机、参数调优、被控对象模型 |
| **Camera 文档** | [entities/camera/README.md](../entities/camera/README.md) | 针孔成像模型、变焦控制、质心检测、帧渲染 |
| **Raspi 文档** | [entities/raspi/README.md](../entities/raspi/README.md) | 三级延时管线、控制程序协议、基线跟踪模板、自定义扩展 |
| **Runtime 文档** | [runtime/README.md](../runtime/README.md) | tick 顺序、命令调度（latest-wins）、Client 绑定、Bootstrap 流程 |
| **Agent 协作日志** | [workspace_meta/agent_log.md](../workspace_meta/agent_log.md) | Claude Code 与 Codex 的操作记录 |
| **迭代历史** | [workspace_meta/plan_logs/history.md](../workspace_meta/plan_logs/history.md) | 历次迭代变更记录 |

## 阅读建议

**新成员入门顺序**：
1. [主 README](../README.md) — 理解系统架构和实体间数据流
2. [使用手册](使用手册.md) — 跑通快速验证和测试
3. 按需阅读各实体 README — 深入了解感兴趣的实体

**修改代码时**：
1. 先看对应实体的 README 了解内部机制
2. 修改后更新该实体 README 的相关章节（参数表、API、数据流等）

## 知识点归属

| 知识点 | 唯一归属文档 |
|--------|-------------|
| Target 4 种运动模式 | entities/target/README.md |
| Gimbal 串级 PID 原理 | entities/gimbal/README.md |
| Camera 针孔模型 | entities/camera/README.md |
| Raspi 延时管线 | entities/raspi/README.md |
| tick 顺序 / 命令调度 | runtime/README.md |
| 组装联调 / 控制程序 | README.md |
| 代码规范 / 验收清单 | docs/使用手册.md |
