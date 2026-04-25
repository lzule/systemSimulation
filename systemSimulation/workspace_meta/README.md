# 工作区目录说明（中文）

## output/
仅用于保存运行产物，例如：
- 仿真 GIF/PNG
- 可视化导出图

不应放入：
- 临时测试脚本
- 过程记录日志

## workspace_meta/plan_logs/
用于保存迭代过程文档：
- `latest_plan.md`：当前迭代状态快照
- `history.md`：逐次追加的历史记录

## workspace_meta/tmp_scripts/
用于保存临时验证脚本（探索/排查/一次性检查）。

当临时验证逻辑稳定后，应迁移到 `tests/` 形成正式测试。

## tests/
用于保存正式自动化回归测试，要求可重复执行。

## workspace_meta/agent_log.md
AI Agent 协作日志，记录 Claude Code 与 Codex 的所有修改、建议与决策。
两个 agent 每次操作后必须追加记录。

## 约定
- 产物去 `output/`
- 计划与过程文档去 `workspace_meta/plan_logs/`
- 临时脚本去 `workspace_meta/tmp_scripts/`
- 可复用验证去 `tests/`
- Agent 操作记录去 `workspace_meta/agent_log.md`
