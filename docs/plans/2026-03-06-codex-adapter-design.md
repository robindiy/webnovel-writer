# Codex Webnovel Adapter Design

**Date:** 2026-03-06

**Status:** Approved for implementation

## Goal

将 `webnovel-writer` 从 “Claude Code 插件专用” 扩展为 “Codex 可安装、可维护、可开源发布” 的兼容版本，同时尽量保持原有使用习惯，尤其保留 `/webnovel-writer:*` 这一组命令契约。

## Product Contract

- 对外优先保留原命令字面形式：
  - `/webnovel-writer:webnovel-init`
  - `/webnovel-writer:webnovel-plan`
  - `/webnovel-writer:webnovel-write 1`
  - `/webnovel-writer:webnovel-review 1`
  - `/webnovel-writer:webnovel-dashboard`
- Codex 桌面版是主场景；桌面版内优先支持原 slash 命令体验。
- 纯终端环境允许使用等价 fallback，但行为必须与原命令保持一致。
- 安装方式必须进入仓库，不能依赖用户手工 patch `~/.claude/plugins/cache/...`。
- 仓库未来需要支持开源协作维护，因此命令映射、安装方式、兼容策略都必须可读、可测、可文档化。

## Non-Goals

- 不在本轮直接重写所有 Claude skills/agents 的文学提示词内容。
- 不在本轮重做前端 Dashboard UI。
- 不在本轮引入新的创作流程命令；先对齐现有命令集合。
- 不依赖 Claude 私有运行时或缓存目录作为正式发布路径。

## Approaches Considered

### 方案 A：仅修兼容，不做 Codex 包装

只修 `python`/`python3` 和 Python 版本兼容，让现有脚本在本地运行。

**优点**
- 改动最小
- 风险低

**缺点**
- Codex 桌面版无法自然复用
- 不能保留 `/webnovel-writer:*` 命令体验
- 用户必须知道底层脚本路径

**结论**
- 不满足目标。

### 方案 B1：轻量包装，只在对话里手工模拟

在 Codex 中通过普通对话提示词模拟 init/write/review/dashboard。

**优点**
- 开发快
- 几乎不改底层代码

**缺点**
- 体验不稳定
- 命令契约不是单一来源
- 安装后用户仍不清楚如何使用

**结论**
- 仅适合临时演示，不适合作为开源发布方案。

### 方案 B2：混合适配层（选择方案）

底层复用现有 Python 核心；新增一层 Codex 适配器和安装入口：

- Codex 桌面版：优先识别并执行 `/webnovel-writer:*`
- 终端：提供交互菜单与命令行 fallback
- 两个入口共用同一套命令注册表和工作流分发逻辑

**优点**
- 兼顾兼容性、可维护性、开源发布体验
- 最大化复用现有数据核心
- 用户不需要理解背后的 Claude/Codex 差异

**缺点**
- 需要新增适配层、安装脚本、技能包
- 需要梳理原命令与下层脚本的映射

**结论**
- 推荐并已获确认。

## Architecture

### 1. Runtime Compatibility Layer

目标：先解决“能跑”的问题。

范围：
- 统一解释器解析：避免硬编码 `python`
- Python 3.9 兼容：移除 `str | None`、`Path | None`、`list[...]` 等不兼容类型注解
- 保持 Python 3.10+ 仍可运行

设计：
- 在 `webnovel-writer/scripts/runtime_compat.py` 扩展解释器与版本辅助函数
- 所有仓库内新增入口都经由统一兼容函数选择解释器与子进程调用方式
- Dashboard 相关模块改为 `typing.Optional` / `typing.List` / `typing.Union`

### 2. Command Registry

目标：建立命令契约的单一来源。

新增一个仓库内注册表模块，维护：
- slash 命令字面值
- fallback shell 命令
- 对应的执行器
- 是否需要交互选择
- 参数解析规则

建议命令注册表覆盖：
- `/webnovel-writer:webnovel-init`
- `/webnovel-writer:webnovel-plan`
- `/webnovel-writer:webnovel-write`
- `/webnovel-writer:webnovel-review`
- `/webnovel-writer:webnovel-dashboard`
- `/webnovel-writer:webnovel-query`
- `/webnovel-writer:webnovel-resume`

### 3. Codex Adapter Layer

目标：把 Codex 可见的用户输入转换为原项目工作流调用。

职责：
- 解析字面 slash 命令
- 管理需要用户选择的步骤
- 在 Codex 对话中输出 `1/2/3` 选项
- 在终端模式下输出可交互菜单
- 调用底层 `webnovel-writer/scripts/webnovel.py`、`workflow_manager.py`、Dashboard server

建议新增入口：
- `webnovel-writer/scripts/codex_cli.py`
- `webnovel-writer/scripts/codex_command_registry.py`
- `webnovel-writer/scripts/codex_interaction.py`

### 4. Codex Skill Package

目标：让 Codex 桌面版/CLI 在安装后自然理解 `/webnovel-writer:*`。

建议新增目录：
- `codex-skills/webnovel-writer/SKILL.md`
- `codex-skills/webnovel-writer/agents/openai.yaml`
- `codex-skills/webnovel-writer/scripts/...`
- `codex-skills/webnovel-writer/references/...`

Skill 行为：
- 当用户在 Codex 中输入 `/webnovel-writer:*` 或描述性命令时触发
- 读取仓库安装配置，定位 repo root
- 调用 `codex_cli.py`
- 当命令需要交互时，优先走对话内选项

### 5. Installer

目标：把“本机调通”变成“别人安装后就能用”。

建议新增安装脚本：
- `scripts/install_codex_support.py`

安装脚本职责：
- 将 `codex-skills/webnovel-writer` 安装到 `$CODEX_HOME/skills/webnovel-writer`
- 写入 repo root / 配置文件
- 创建终端 fallback wrapper（如 `webnovel-codex`）
- 输出安装成功后的最小使用说明

## Interaction Model

### Codex 桌面版

主目标：保留原 slash 使用习惯。

用户输入：
- `/webnovel-writer:webnovel-init`
- `/webnovel-writer:webnovel-write 1`

系统行为：
- 直接解析 slash 字符串
- 如需多选，输出：
  - `1. 继续当前项目`
  - `2. 新建项目`
  - `3. 查看当前状态`
- 用户回复数字后继续

### 终端模式

保留两种运行方式：
- 菜单模式：`webnovel-codex`
- fallback 命令模式：`webnovel-codex "/webnovel-writer:webnovel-write 1"`

说明：
- 纯 shell 中不能指望 `/webnovel-writer:*` 作为裸命令存在
- 但 slash 字面值仍作为参数保留，达到“命令契约不变、载体不同”的兼容目标

## Data Flow

1. 用户输入 slash 命令或自然语言
2. Codex Skill / 终端 wrapper 调用 `codex_cli.py`
3. `codex_cli.py` 查 `codex_command_registry.py`
4. 适配层决定：
   - 直接执行
   - 还是先返回选项、等待下一轮输入
5. 最终调用原项目核心：
   - `scripts/webnovel.py`
   - `scripts/workflow_manager.py`
   - `dashboard/server.py`
   - `scripts/data_modules/*`
6. 结果以用户可读文本回到 Codex 对话或终端界面

## Compatibility Strategy

### Python

- 第一优先：仓库内所有核心入口支持 Python 3.9
- 第二优先：不破坏 Python 3.10+ 语法环境
- 第三优先：统一使用 `sys.executable` 或解释器解析器，而不是裸 `python`

### Claude Coupling

保留现有 Claude 插件目录，不直接移除；但新增的 Codex 支持不依赖：
- `~/.claude/plugins/cache/...`
- Claude 专属 slash 命令注册机制
- Claude 私有 Agent/Skill 调度能力

### Command Compatibility

- 桌面版：尽量字面兼容 slash
- 终端：slash 作为参数兼容
- 文档：优先介绍 slash 用法，fallback 作为补充

## Error Handling

- 未安装 skill：安装脚本给出明确修复命令
- Python 版本过低：输出清晰错误并给出兼容提示
- 缺少 RAG `.env`：允许降级运行，并提示缺失字段
- 缺少当前项目指针：在对话/终端中引导用户选择项目
- Dashboard 启动失败：回显具体端口/导入/依赖错误

## Testing Strategy

### 自动化验证

- Python 3.9 下导入 Dashboard 模块不报语法错误
- 命令注册表能解析 slash 与 fallback
- `codex_cli.py` 能正确路由到统一 CLI
- installer 能生成 skill 安装目标与 wrapper

### 手工验收

- Codex 对话里执行 `/webnovel-writer:webnovel-init`
- Codex 对话里执行 `/webnovel-writer:webnovel-write 1`
- 终端里执行 `webnovel-codex "/webnovel-writer:webnovel-dashboard"`
- Dashboard 成功启动并可访问

## Open Source Maintenance Rules

- 不把本地缓存目录改动视为正式修复
- 所有兼容策略必须进入仓库与文档
- 命令映射只维护一份注册表
- 新命令必须同时考虑：
  - Codex 桌面版
  - 终端 fallback
  - 文档说明
  - 自动化测试

## Immediate MVP Scope

1. 修 Python 解释器调用与 Python 3.9 兼容
2. 新增 Codex 命令注册表与 CLI 适配层
3. 新增 Codex skill 安装目录与安装脚本
4. 更新 README / docs，加入 Codex 安装与使用说明

完成以上四项后，即可形成第一版可安装、可演示、可维护的 Codex 兼容发行版。
