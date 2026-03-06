# 命令详解

## 兼容入口

本项目现在同时支持两种入口：

- **Claude / Codex 对话入口**：优先使用原 slash 命令
- **shell fallback**：使用 `webnovel-codex`

推荐优先级：

1. `/webnovel-writer:*`
2. `webnovel-codex ...`

## `/webnovel-init`

用途：初始化小说项目（目录、设定模板、状态文件）。

产出：

- `.webnovel/state.json`
- `设定集/`
- `大纲/总纲.md`

shell fallback：

```bash
webnovel-codex webnovel-init
```

## `/webnovel-plan [卷号]`

用途：生成卷级规划与节拍。

示例：

```bash
/webnovel-plan 1
/webnovel-plan 2-3
```

shell fallback：

```bash
webnovel-codex webnovel-plan 1
```

## `/webnovel-write [章号]`

用途：执行完整章节创作流水线（上下文 → 草稿 → 审查 → 数据落盘）。

示例：

```bash
/webnovel-write 1
/webnovel-write 45
```

Codex 兼容写法：

```text
/webnovel-writer:webnovel-write 1
```

shell fallback：

```bash
webnovel-codex webnovel-write 1
```

常见模式：

- 标准模式：全流程
- 快速模式：`--fast`
- 极简模式：`--minimal`

## `/webnovel-review [范围]`

用途：对历史章节做多维质量审查。

示例：

```bash
/webnovel-review 1-5
/webnovel-review 45
```

shell fallback：

```bash
webnovel-codex webnovel-review 1-5
```

## `/webnovel-query [关键词]`

用途：查询角色、伏笔、节奏、状态等运行时信息。

示例：

```bash
/webnovel-query 萧炎
/webnovel-query 伏笔
/webnovel-query 紧急
```

shell fallback：

```bash
webnovel-codex webnovel-query 紧急
```

## `/webnovel-resume`

用途：任务中断后自动识别断点并恢复。

示例：

```bash
/webnovel-resume
```

shell fallback：

```bash
webnovel-codex webnovel-resume
```

## `/webnovel-dashboard`

用途：启动只读可视化面板。

Claude / Codex：

```text
/webnovel-writer:webnovel-dashboard
```

shell fallback：

```bash
webnovel-codex "/webnovel-writer:webnovel-dashboard" --execute-dashboard
```
