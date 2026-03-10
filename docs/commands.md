# 命令详解

## 兼容入口

本仓库对外只维护 **Codex 入口**：

- **shell interactive / fallback**：使用 `webnovel-codex`
- **Codex 对话入口**：使用自然语言触发

推荐优先级：

1. 结构化初始化：优先走终端 `webnovel-codex`
2. 日常规划 / 写作 / 审查：可以在 Codex 对话里输入自然语言
3. 需要保留原 slash 契约时：继续用终端 fallback

重要说明：

- 当前 Codex 会先拦截未知的 `/命令`
- 因此 **不要在 Codex 对话框里直接输入** `/webnovel-writer:*`
- 如果你要保留原 slash 契约，请在终端 fallback 中使用，例如：

```bash
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-write 1"
```

## `webnovel-init`

用途：初始化小说项目（目录、设定模板、状态文件）。

推荐入口：

```bash
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-init" --mode shell
```

说明：

- 这是当前推荐的 **确定性初始化入口**
- 终端交互层使用 `prompt_toolkit` 全屏 TUI
- 会按上游 `webnovel-init/SKILL.md` 的 Step 1 ~ Step 6 顺序走
- 可枚举字段优先显示选择项，支持 `↑/↓` + `Enter/Space` 直接确认
- Step 5 会保留动态推荐方案，并追加 `系统推荐` / `自定义` 两个入口
- 手动输入字段会附带 source-backed 提示/示例；若书名对应目录已存在，会拦截并要求重输
- 最终确认前不会调用 `init_project.py`

产出：

- `.webnovel/state.json`
- `设定集/`
- `大纲/总纲.md`

Codex 对话里的处理：

```text
请使用 webnovel-writer 初始化一个小说项目。
```

这时 Codex 不会在对话里继续 init 采集，而是会提示你改走外部 `prompt_toolkit` TUI：

```bash
webnovel-codex --mode shell "/webnovel-writer:webnovel-init"
```

纯 shell fallback：

```bash
webnovel-codex --mode codex --json "/webnovel-writer:webnovel-init"
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

Codex 审查说明：

- Step 3 不再允许对话内手写“自审总结”
- `webnovel-write` 当前仍由技能主流程编排，但其审查 Step 会通过 source-backed runner 落盘
- runner 会并行拉起多个 `codex exec` checker 子进程，并写出：
  - `.webnovel/reviews/chNNNN/checkers/*.json`
  - `.webnovel/reviews/chNNNN/aggregate.json`
  - `审查报告/第N-N章审查报告.md`

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

Codex 审查说明：

- `webnovel-review` 不再走对话内 `follow_skill`，而是由 helper 直接分发到 `webnovel-writer/scripts/codex_review_workflow.py`
- `codex_review_workflow.py` 会按上游拓扑依次执行：
  - `workflow start-task`
  - Step 1/2 workflow 记录
  - `review_agents_runner.py`
  - `index get-recent-review-metrics`
  - `update-state --add-review`
  - workflow 收尾
- 区间审查会逐章执行 checker 子进程，再写一份区间汇总
- 关键产物：
  - `.webnovel/reviews/chNNNN/aggregate.json`
  - `.webnovel/reviews/range-XXXX-YYYY/aggregate.json`
  - `审查报告/第X-Y章审查报告.md`
- 如果这些产物不存在，说明审查没有真正完成

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

默认监听地址：`http://127.0.0.1:18765`

默认行为：尝试自动打开默认浏览器，避免和 Claude 版常见的 `8765` 端口冲突。
