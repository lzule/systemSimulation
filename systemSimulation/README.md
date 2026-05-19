# 云台数字孪生仿真系统

基于 Python 的云台-相机-目标跟踪闭环仿真平台，含树莓派控制器。四个实体由 `DigitalTwinRuntime` 按固定 tick 顺序调度：Target → Gimbal → Camera → Raspi → 发布快照。

---

## 快速启动

```bash
conda activate simulation
cd systemSimulation

# 冒烟测试（30 秒内完成）
conda run -n simulation python app.py --no-gui --mode offline --duration 1.0

# GUI 实时仿真
conda run -n simulation python app.py --mode realtime --duration 60
```

成功判据：出现 `t=... yaw=... u=... in_fov=...` 周期输出，无异常堆栈。

---

## 文档导航

### 按角色

| 角色 | 推荐阅读 |
|------|---------|
| 研究使用者 | [系统主手册](docs/system_manual.md) → [研究工作流手册](docs/research_workflow.md) → [工具手册](docs/tools_guide.md) |
| 新接手人员 | [系统主手册](docs/system_manual.md) → 各实体 README → [ATP 开发文档](docs/低空场景无线光通信ATP开发文档.md) |
| 算法开发者 | [系统主手册](docs/system_manual.md) → [树莓派控制程序开发手册](docs/树莓派控制程序开发手册.md) → [算法接入指南](docs/algorithm_integration_guide.md) |
| 项目维护者 | [系统主手册](docs/system_manual.md) → [维护规则](docs/maintenance_guide.md) → [文档导航](docs/doc-structure.md) |

### 按任务

| 任务 | 推荐阅读 |
|------|---------|
| 第一次运行 | [系统主手册 §3](docs/system_manual.md) |
| 跑 benchmark | [研究工作流手册](docs/research_workflow.md) |
| 对比两个算法 | [研究工作流手册 §3](docs/research_workflow.md) + [工具手册 §3](docs/tools_guide.md) |
| 诊断算法退化 | [研究工作流手册 §4](docs/research_workflow.md) + [工具手册 §4](docs/tools_guide.md) |
| 写自己的控制程序 | [树莓派控制程序开发手册](docs/树莓派控制程序开发手册.md) |
| 把算法注册到 benchmark | [算法接入指南](docs/algorithm_integration_guide.md) |
| 修改实体参数 | [工具手册 §6.4](docs/tools_guide.md)（config_editor） + 对应实体 README |

### 全部文档

| 文档 | 说明 |
|------|------|
| [系统主手册](docs/system_manual.md) | 平台完整使用说明 |
| [研究工作流手册](docs/research_workflow.md) | benchmark → 对比 → 诊断 → 出图 |
| [工具手册](docs/tools_guide.md) | 16 个工具详细说明 |
| [算法接入指南](docs/algorithm_integration_guide.md) | 4 种算法接入方式 |
| [树莓派控制程序开发手册](docs/树莓派控制程序开发手册.md) | 控制程序编写教程 |
| [文档导航](docs/doc-structure.md) | 文档体系总览 |
| [ATP 开发文档](docs/低空场景无线光通信ATP开发文档.md) | ATP 总路线图 |
| [维护规则](docs/maintenance_guide.md) | 后续维护检查清单 |

---

## 系统架构概要

```
Target → Gimbal → Camera → Raspi → Command → Gimbal
```

- **Target**：5 种运动类型（正弦/匀速/匀加速/随机游走/航点），3D 空间
- **Gimbal**：双轴云台，串级 PID，支持速率/角度两种控制模式
- **Camera**：双轴针孔成像，含变焦和近真实渲染
- **Raspi**：延时管线（latest/fifo），可插拔控制程序 + ATP 状态机
- **Runtime**：统一 tick 调度，命令总线，WorldSnapshot 发布

详细架构和数据流说明请参见[系统主手册 §1](docs/system_manual.md)。

---

## 实体文档

| 实体 | 文档 | 核心内容 |
|------|------|---------|
| [Target](entities/target/README.md) | 5 种运动模型、3D 运动学、参数表 |
| [Gimbal](entities/gimbal/README.md) | 串级 PID、双轴状态机、非理想参数 |
| [Camera](entities/camera/README.md) | 双轴针孔成像、变焦控制、近真实渲染 |
| [Raspi](entities/raspi/README.md) | 延时模型、ControlProgram 协议、基线跟踪 |
| [Runtime](runtime/README.md) | tick 调度、命令总线、Client 绑定 |

---

## 开发约定

详细开发规范请参见 [CLAUDE.md](../CLAUDE.md)。要点：

- 所有 Python 命令使用 `conda run -n simulation python ...`
- 配置集中在 `config.py`，不要新建配置文件
- 修改代码后必须更新 [CHANGELOG.md](CHANGELOG.md)
- 修改实体代码时同步更新对应实体 README
- 新功能优先落在 `entities/*` 与 `runtime/*`

---

## 维护约定

- 改功能后要同步哪些文档 → 参见[维护规则](docs/maintenance_guide.md)
- 新增工具如何补说明 → 参见[维护规则](docs/maintenance_guide.md)
- 新增算法如何补实例 → 参见[算法接入指南](docs/algorithm_integration_guide.md)
