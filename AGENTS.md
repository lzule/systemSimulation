# AGENTS.md

本文件为 Codex、Claude 及其他 Agent 在此仓库中工作时提供补充指引。

---

## 1. 适用范围

1. `CLAUDE.md` 是本仓库的主规则文档。
2. `AGENTS.md` 只保留“所有 Agent 通用的补充规则”和“当前环境下需要特别说明的执行口径”。
3. 若 `AGENTS.md` 与 `CLAUDE.md` 出现不一致：
   - 默认以 `CLAUDE.md` 为主
   - 除非 `AGENTS.md` 写的是更严格、且明确只针对 Agent 执行方式的补充限制

## 2. CHANGELOG 时间戳规则

写入 `systemSimulation/CHANGELOG.md` 条目前，必须先获取当前真实时间。

当前仓库默认 shell 环境是 PowerShell，统一执行：

```powershell
Get-Date -Format yyyyMMdd-HHmmss
```

将返回值直接填入条目标题，格式为 `序号-年月日-时分秒`（如 `047-20260516-143022`）。

禁止事项：

1. 禁止编造、猜测或手填一个“看起来合理”的时间戳
2. 禁止使用明显整齐但未经验证的时间，如 `120000`、`200000`
3. 禁止时间倒挂；新条目的时间戳必须大于或等于上一条
4. 若环境确实无法获取真实时间，才允许使用 `00000000-000000` 作为占位

## 3. 命令执行口径

1. Python 命令、测试命令、临时文件清理约定，以 `CLAUDE.md` 第 2 节和第 5 节为准。
2. 当前项目默认工作目录为：
   `k:/ustc-lizl/Liuwj2Lizl/ALL-Auto/8-simulation/System-APT/systemSimulation`
3. 所有 Python 命令统一使用：
   `conda run -n simulation python ...`
4. 删除临时文件时，优先使用 PowerShell 原生命令：
   `Remove-Item -LiteralPath ...`

## 4. 维护原则

1. 不要在 `AGENTS.md` 中整段复制 `CLAUDE.md` 内容。
2. 若项目主规则发生变化，优先修改 `CLAUDE.md`。
3. 只有当某条规则需要专门说明给“所有 Agent 的执行方式”时，才补入 `AGENTS.md`。
