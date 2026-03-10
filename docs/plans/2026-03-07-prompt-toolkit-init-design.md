# Prompt Toolkit Init TUI Design

**Date:** 2026-03-07

**Status:** User approved

## Goal

把 `webnovel-init` 的 shell 交互层从“手写 ANSI 菜单”升级为基于 `prompt_toolkit` 的真正全屏 TUI，做到：

- 固定尺寸的选择区域
- 超长选项滚动而不是整屏重打
- 候选选择与手动输入的状态切换稳定
- 支持上一步 / 下一步 / 取消
- 保持上游 source-backed 逻辑不变

## Why the Current Approach Must Be Replaced

用户的真实终端反馈已经说明，当前手写菜单层存在架构级问题：

1. 菜单会重复打印到主终端输出，而不是稳定驻留在固定视图内
2. 长列表没有真正的“窗口化滚动”
3. 输入态与选择态切换时存在状态丢失或误取消
4. 即使修掉一处换行/清屏问题，也会在另一种终端尺寸或回显模式下继续出错

这不再是“补几个 ANSI 控制符”的问题，而是交互宿主选型不对。

## Source of Truth

这次改造只替换 **UI 宿主层**，不替换数据来源和落盘逻辑。

保留：

- `webnovel-writer/skills/webnovel-init/SKILL.md`
- `webnovel-writer/scripts/init_source_loader.py`
- `webnovel-writer/scripts/init_project.py`

替换：

- `webnovel-writer/scripts/init_terminal_ui.py` 中的手写 ANSI / raw mode 交互实现

## Chosen Approach

### A. Python `prompt_toolkit` Full-Screen App

这是本次选定方案。

#### Why

- 与当前 Python 主链路一致，不引入 Node 运行时
- 原生支持全屏布局、键盘绑定、输入框、滚动容器、按钮、焦点管理
- 比手写 ANSI 更可控，也更接近 Claude Code / `ccman` 的交互稳定性

#### Rejected Alternatives

- 继续修手写 ANSI：已验证边界问题太多，不值得
- Node `inquirer` sidecar：体验可行，但会把仓库变成 Python + Node 双栈

## Architecture

### 1. `InitWizard` 保留业务状态机

`InitWizard` 继续负责：

- Step 1 ~ Step 6 的顺序
- source-backed 候选项选择逻辑
- payload 构建
- `init_project.py` 参数映射

也就是说：

- **流程和数据仍由 Python 业务层控制**
- **TUI 只负责把字段交互展示出来**

### 2. 引入 `PromptToolkitIO`

在 `init_terminal_ui.py` 中新增一个面向 `prompt_toolkit` 的 IO 适配层：

- `show_step`
- `ask_text`
- `choose`
- `confirm`
- `show_summary`

但它的实现不再是“打印 + 读 stdin”，而是基于 `prompt_toolkit` `Application` / `Layout` / `KeyBindings` 驱动。

### 3. 固定视图区模型

每个交互界面采用固定结构：

- 顶部：当前 Step / 标题
- 中部：字段说明 / 提示 / 候选项
- 主区：固定高度列表或输入框
- 底部：操作提示（上下移动、回车确认、Esc 返回、Ctrl+C 取消）

对超长选项：

- 使用固定高度的滚动列表
- 当前焦点始终在视口中
- 上下移动时只更新当前视图，不把整个菜单重新打印到 shell 历史里

### 4. “候选 + 手动输入”统一交互

对以下字段统一改为两段式交互：

- 一句话故事
- 核心冲突
- 主角欲望
- 主角缺陷
- 主角原型
- 反派镜像
- 不可逆代价
- 力量体系类型
- 势力格局
- 目标读者
- 平台

交互规则：

1. 先显示候选列表
2. 第一项固定为 `手动输入`
3. 若用户选 `手动输入`，切到文本输入视图
4. 文本输入视图保留：
   - 当前字段标题
   - 来自上游 source 的候选提示
   - 返回上一步操作

### 5. Back / Next / Cancel

这次不再把每个问题当作“只进不退”的线性 stdin 流。

TUI 层需要支持：

- `Esc`：返回当前字段的上一界面
- `Alt-Left` 或底部按钮：返回上一个字段
- `Enter`：确认当前选择
- `Ctrl+C`：取消整个初始化

注意：

- “返回上一步”是 UI 行为，不改变上游 Step 定义
- Step 6 最终确认后，仍然只在用户明确确认时调用 `init_project.py`

## File Strategy

### Existing file to keep

- `webnovel-writer/scripts/init_source_loader.py`
- `webnovel-writer/scripts/codex_cli.py`
- `webnovel-writer/scripts/init_project.py`

### Existing file to refactor

- `webnovel-writer/scripts/init_terminal_ui.py`

### Dependency update

- `webnovel-writer/scripts/requirements.txt`

新增依赖：

- `prompt_toolkit`

## Testing Strategy

### 1. Source-backed behavior remains intact

现有解析测试保留：

- `test_init_source_loader.py`

### 2. Wizard behavior tests keep using fake IO

`InitWizard` 的业务测试继续保留，确保：

- 字段顺序不变
- payload 不变
- `init_project.py` 参数映射不变

### 3. Add TUI adapter tests

新增针对 `PromptToolkitIO` 的测试：

- 固定高度窗口只显示部分选项
- 焦点上下移动时视口滚动而不是增量打印
- 选择 `手动输入` 后能进入文本输入视图
- 返回上一步不丢字段状态

## Success Criteria

满足以下条件才算完成：

1. `题材分类` / `第二题材` / `主题材` 这类菜单不再反复打印到 shell 历史
2. 列表始终以固定窗口显示，多余项滚动显示
3. `一句话故事` 等字段先展示候选，再允许手输
4. 用户可从输入态回到候选态
5. 现有 init payload 和 `init_project.py` 调用不变

## Migration Notes

在正式切换前，应保留数值型 fallback 或最简单文本 fallback 作为兜底，仅在：

- 无 TTY
- 缺失 `prompt_toolkit`
- 极端兼容环境

时才启用。

默认正常路径改为 `prompt_toolkit` TUI。

