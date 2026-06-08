# experiments/ — 对照实验目录

本目录承载系统对照实验，对应 `docs/TODO.md` 第 2 项「系统各实例配置独立性检查与对照实验设计」。

详细设计文档：[docs/todo/对照实验设计-配置独立性与参数扫描.md](../docs/todo/对照实验设计-配置独立性与参数扫描.md)

---

## 目录结构

```
experiments/
├── README.md                              # 本文件
├── common/                                # 共用框架（Phase B 实现）
├── docs/
│   └── 配置独立性审查报告.md              # Phase A 产出
├── exp01_camera_fps/                      # 实验1：相机帧率（Phase C）
│   ├── README.md
│   ├── run.py
│   ├── config.yaml
│   └── data/
└── exp02_raspi_process_delay/             # 实验2：图像处理延时（Phase D）
    ├── README.md
    ├── run.py
    ├── config.yaml
    └── data/
```

---

## 命名规范

- 实验目录：`expNN_<实验主题>` — 数字编号 + 主题描述，后续新实验自然递增（exp03、exp04 …）
- 数据严格放在 `expNN_*/data/`，**不再使用** `systemSimulation/output/`
- 每个实验独立包含：`README.md` + `run.py` + `config.yaml` + `data/`

## 复用规范

- `common/` 是所有实验共用代码（实验框架、Kp 网格搜索、指标计算、画图工具），**禁止**在 `expNN_*/` 内复制粘贴
- 每个实验只写自己独有的逻辑：参数空间定义、特殊处理
- 新实验按 `experiments/docs/实验目录使用规范.md`（Phase B 完成后产出）开发

---

## 阶段进度

| Phase | 内容 | 状态 |
|-------|------|------|
| A | 配置独立性审查（只读） | 🟡 进行中（已产出报告） |
| B | `common/` 框架搭建（含多进程并行） | 🔴 未开始 |
| C | exp01_camera_fps 帧率扫参 | 🔴 未开始 |
| D | exp02_raspi_process_delay 延时扫参 | 🔴 未开始 |
| E | 跨实验 Kp 趋势分析与可视化 | 🔴 未开始 |
