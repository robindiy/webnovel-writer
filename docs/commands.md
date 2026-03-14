# 命令详解

## 兼容入口

本仓库对外只维护 **Codex 入口**：

- **Codex 对话入口**：使用自然语言触发
- **shell fallback**：使用 `webnovel-codex`

推荐优先级：

1. Codex 对话里输入自然语言，例如“请使用 webnovel-writer 写第 1 章”
2. 终端里执行 `webnovel-codex ...`

重要说明：

- 当前 Codex 会先拦截未知的 `/命令`
- 因此 **不要在 Codex 对话框里直接输入** `/webnovel-writer:*`
- 如果你要保留原 slash 契约，请在终端 fallback 中使用，例如：

```bash
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-write 1"
```

## `webnovel-init`

用途：初始化小说项目（目录、设定模板、状态文件）。

Codex 对话：

```text
请使用 webnovel-writer 初始化一个小说项目。
```

产出：

- `.webnovel/state.json`
- `设定集/`
- `大纲/总纲.md`

shell fallback：

```bash
webnovel-codex webnovel-init
```

安装过 Codex 支持后，也可以直接使用快捷命令：

```bash
webnovel-init
```

终端 TUI 模式（适合字段很多、需要键盘选择时）：

```bash
./scripts/py webnovel-writer/scripts/webnovel.py init --tui
```

## `webnovel-plan [卷号]`

用途：生成卷级规划与节拍。

示例：

```text
请使用 webnovel-writer 规划第 1 卷。
请使用 webnovel-writer 规划第 2 到第 3 卷。
```

shell fallback：

```bash
webnovel-codex webnovel-plan 1
```

## `webnovel-write [章号]`

用途：执行完整章节创作流水线（上下文 → 草稿 → 审查 → 数据落盘）。

示例：

```text
请使用 webnovel-writer 写第 1 章。
请使用 webnovel-writer 写第 45 章。
```

shell fallback：

```bash
webnovel-codex webnovel-write 1
```

常见模式：

- 标准模式：全流程
- 快速模式：`--fast`
- 极简模式：`--minimal`

## `webnovel-review [范围]`

用途：对历史章节做多维质量审查。

示例：

```text
请使用 webnovel-writer 审查第 1 到 5 章。
请使用 webnovel-writer 审查第 45 章。
```

shell fallback：

```bash
webnovel-codex webnovel-review 1-5
```

## `webnovel-query [关键词]`

用途：查询角色、伏笔、节奏、状态等运行时信息。

示例：

```text
请使用 webnovel-writer 查询“萧炎”。
请使用 webnovel-writer 查询“伏笔”。
请使用 webnovel-writer 查询“紧急”。
```

shell fallback：

```bash
webnovel-codex webnovel-query 紧急
```

## `webnovel-resume`

用途：任务中断后自动识别断点并恢复。

示例：

```text
请使用 webnovel-writer 恢复上一次中断的任务。
```

shell fallback：

```bash
webnovel-codex webnovel-resume
```

## `webnovel-dashboard`

用途：启动只读可视化面板。

Codex 对话：

```text
请使用 webnovel-writer 打开 dashboard。
```

shell fallback：

```bash
webnovel-codex "/webnovel-writer:webnovel-dashboard" --execute-dashboard
```
