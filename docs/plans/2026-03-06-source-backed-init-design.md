# Source-Backed Init TUI Design

**Date:** 2026-03-06

**Status:** Approved for implementation

## Goal

把 Codex 版本的初始化体验改成“以上游 `webnovel-init` 真源驱动”的确定性交互：

- 不再把自然语言对话当成主入口
- 不再手抄一套并行的初始化流程
- 尽量从上游已有源文件读取步骤、字段、候选项与约束
- 在终端里提供接近 Claude Code `AskUserQuestion` 的逐步选择体验

## Source of Truth

初始化链路分成两层真源：

1. `webnovel-writer/skills/webnovel-init/SKILL.md`
   - 决定交互阶段、字段顺序、候选项文本、充分性闸门、最终确认结构
   - 这是 Claude Code 里“问什么、怎么问、按什么阶段问”的主真源
2. `webnovel-writer/scripts/init_project.py`
   - 决定最终生成哪些文件、接收哪些参数、如何写入项目骨架
   - 这是“最终落盘”的主真源

因此 Codex 适配层不能再自己硬编码另一套 init 流程；它必须：

- 从 `SKILL.md` 读取交互定义
- 从 `init_project.py` 读取或对齐落盘参数
- 只在“字段键名映射”和“终端 UI 渲染”层做最小适配

## Why Not Use Codex Chat as the Primary Init Surface

现状已经验证：

- Codex 聊天框会拦截未知 `/command`
- 纯自然语言会被 Codex 自己的技能调度和自由理解干扰
- 用户期望的是接近 Claude Code 的确定性步骤流，而不是开放式聊天

因此主入口应调整为：

- **主入口**：终端 TUI / shell interactive flow
- **辅入口**：Codex chat 只做帮助、说明、或把用户导向终端 init

## UX Contract

### Main Path

用户在普通终端中运行：

```bash
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-init" --mode shell
```

预期行为：

- 直接进入初始化向导
- 按 `SKILL.md` 的 Step 0 → Step 6 顺序推进
- 对可枚举字段使用选择菜单
- 对开放字段使用文本输入
- 在 Step 6 显示完整初始化摘要，并要求明确确认
- 只有确认后才调用 `init_project.py`

### Determinism

- 步骤标题、字段名称、候选项文本优先来自 `SKILL.md`
- 创意约束与反套路候选优先来自 `references/creativity/*.md`
- 不依赖大模型自由发挥来“发明”步骤或改写字段

## Architecture

### 1. `init_source_loader.py`

职责：

- 读取 `skills/webnovel-init/SKILL.md`
- 解析 Step 1 ~ Step 6 的标题、字段、候选项、确认规则
- 解析内嵌 JSON 数据模型与充分性闸门说明
- 读取创意参考资料，提供给 Step 5 使用

原则：

- 展示文案来自上游源文件
- 只做“结构提取”，不重新发明内容

### 2. `init_terminal_ui.py`

职责：

- 提供终端交互层
- 对枚举字段显示菜单
- 对文本字段读取输入
- 支持逐步确认、返回上一步、最终确认

原则：

- UI 是新的，但数据不是新的
- 行为尽量模拟 Claude Code 的“单轮一个关键选择”节奏

### 3. `codex_cli.py` integration

当命令是 `webnovel-init` 且运行在 `shell` 模式时：

- 默认启动 source-backed init wizard
- `--json` 仍保留机器可读输出，便于测试和诊断

### 4. Backend handoff

Wizard 收集完成后：

- 把答案转成 `init_project.py` 的参数
- 调用唯一允许的生成入口 `init_project.py`
- 执行最小生成后验证

## Scope for This Iteration

### Included

- 读取 `SKILL.md` 的 Step 结构
- 读取题材集合与基础选项
- 终端交互式 init 向导
- Step 6 最终确认
- 调用 `init_project.py`
- 更新文档，把 shell init 作为推荐路径

### Deferred

- 在 Codex chat 内复刻真正的箭头选择 UI
- 完整复刻 Claude Code 的 `AskUserQuestion` 宿主能力
- 对所有开放文本字段做智能补全

## Risk Notes

1. `SKILL.md` 是 Markdown 文档，不是正式 DSL
   - 解决方式：优先使用稳定的标题与 bullet 结构解析
2. Step 5 创意包包含生成性内容
   - 解决方式：优先从 `references/creativity/*.md` 组合出确定性候选包，而不是凭空生成
3. `init_project.py` 的参数是英文长选项，而 `SKILL.md` 字段是中文
   - 解决方式：仅维护一层最小字段映射，不复制流程文本
