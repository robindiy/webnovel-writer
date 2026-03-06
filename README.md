# Webnovel Writer

[![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Compatible-purple.svg)](https://claude.ai/claude-code)
[![Codex](https://img.shields.io/badge/Codex-Compatible-green.svg)](https://openai.com/)

## 项目简单介绍

`Webnovel Writer` 是基于 Claude Code 的长篇网文创作系统，目标是降低 AI 写作中的“遗忘”和“幻觉”，支持长周期连载创作。

详细文档已拆分到 `docs/`：

- Codex 安装：`docs/codex-install.md`
- 架构与模块：`docs/architecture.md`
- 命令详解：`docs/commands.md`
- RAG 与配置：`docs/rag-and-config.md`
- 题材模板：`docs/genres.md`
- 运维与恢复：`docs/operations.md`
- 文档导航：`docs/README.md`

## 快速开始

### 1) 安装插件（官方 Marketplace）

```bash
claude plugin marketplace add lingfengQAQ/webnovel-writer --scope user
claude plugin install webnovel-writer@webnovel-writer-marketplace --scope user
```

> 仅当前项目生效时，将 `--scope user` 改为 `--scope project`。

### 2) 安装 Python 依赖

```bash
python3 -m pip install -r https://raw.githubusercontent.com/lingfengQAQ/webnovel-writer/HEAD/requirements.txt
```

说明：该入口会同时安装核心写作链路与 Dashboard 依赖。

### 2.5) 安装 Codex 适配层（可选）

如果你希望在 Codex 桌面版/CLI 中沿用原插件命令习惯，执行：

```bash
python3 scripts/install_codex_support.py
```

安装完成后会：

- 把 Codex skill 安装到 `~/.codex/skills/webnovel-writer`
- 生成 shell fallback：`~/.codex/bin/webnovel-codex`
- 生成一键恢复入口：`~/.codex/bin/webnovel-codex-restore`
- 写入安装状态：`~/.codex/webnovel-writer/install_state.json`
- 将当前仓库路径写入 skill 配置，后续可直接从 Codex 调用

Codex 中优先保留原 slash 用法：

```text
/webnovel-writer:webnovel-init
/webnovel-writer:webnovel-write 1
/webnovel-writer:webnovel-dashboard
```

如果在纯 shell 中使用 fallback：

```bash
~/.codex/bin/webnovel-codex webnovel-write 1
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-dashboard" --execute-dashboard
```

建议先跑一次不污染真实环境的临时烟测：

```bash
python3 scripts/smoke_test_codex_support.py
```

需要恢复到安装前状态时：

```bash
~/.codex/bin/webnovel-codex-restore
```

### 3) 初始化小说项目

在 Claude Code / Codex 中优先使用完整 slash 命令：

```bash
/webnovel-writer:webnovel-init
```

说明：部分 Claude 环境也支持短命令别名（如 `/webnovel-init`），但对外兼容契约以 `/webnovel-writer:*` 为准。

`/webnovel-writer:webnovel-init` 会在当前 Workspace 下按书名创建 `PROJECT_ROOT`（子目录），并在 `workspace/.claude/.webnovel-current-project` 写入当前项目指针。

### 4) 配置 RAG 环境（必做）

进入初始化后的书项目根目录，创建 `.env`：

```bash
cp .env.example .env
```

最小配置示例：

```bash
EMBED_BASE_URL=https://api-inference.modelscope.cn/v1
EMBED_MODEL=Qwen/Qwen3-Embedding-8B
EMBED_API_KEY=your_embed_api_key

RERANK_BASE_URL=https://api.jina.ai/v1
RERANK_MODEL=jina-reranker-v3
RERANK_API_KEY=your_rerank_api_key
```

### 5) 开始使用

```bash
/webnovel-writer:webnovel-plan 1
/webnovel-writer:webnovel-write 1
/webnovel-writer:webnovel-review 1-5
```

### 6) 启动可视化面板（可选）

```bash
/webnovel-writer:webnovel-dashboard
```

说明：
- Dashboard 为只读面板（项目状态、实体图谱、章节/大纲浏览、追读力查看）。
- 前端构建产物已随插件发布，使用者无需本地 `npm build`。
- Python 3.9 环境下也可运行；仓库内已移除会导致 `str | None` 报错的注解炸点。

### 7) Agent 模型设置（可选）

本项目所有内置 Agent 默认配置为：

```yaml
model: inherit
```

表示子 Agent 继承当前 Claude 会话所用模型。

如果要单独给某个 Agent 指定模型，编辑对应文件（`webnovel-writer/agents/*.md`）的 frontmatter，例如：

```yaml
---
name: context-agent
description: ...
tools: Read, Grep, Bash
model: sonnet
---
```

常见可选值：`inherit` / `sonnet` / `opus` / `haiku`（以 Claude Code 当前支持为准）。

## 更新简介

| 版本 | 说明 |
|------|------|
| **v5.5.0 (当前)** | 新增只读可视化 Dashboard Skill（`/webnovel-dashboard`）与实时刷新能力；支持插件目录启动与预构建前端分发 |
| **v5.4.4** | 引入官方 Plugin Marketplace 安装机制；统一修复 Skills/Agents/References 的 CLI 调用（`CLAUDE_PLUGIN_ROOT` 单路径，透传命令统一 `--`） |
| **v5.4.3** | 增强智能 RAG 上下文辅助（`auto/graph_hybrid` 回退 BM25） |
| **v5.3** | 引入追读力系统（Hook / Cool-point / 微兑现 / 债务追踪） |

## 开源协议

本项目使用 `GPL v3` 协议，详见 `LICENSE`。

## Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=lingfengQAQ/webnovel-writer&type=Date)](https://star-history.com/#lingfengQAQ/webnovel-writer&Date)

## 致谢

本项目使用 **Claude Code + Gemini CLI + Codex** 配合 Vibe Coding 方式开发。  
灵感来源：[Linux.do 帖子](https://linux.do/t/topic/1397944/49)

## 贡献

欢迎提交 Issue 和 PR：

```bash
git checkout -b feature/your-feature
git commit -m "feat: add your feature"
git push origin feature/your-feature
```

## Codex 兼容说明

当前仓库同时维护两类入口：

- Claude Code 插件入口（原生 Marketplace 方式）
- Codex 适配入口（`scripts/install_codex_support.py` + `codex-skills/webnovel-writer`）

兼容策略：

- **Codex 对话优先保留原 slash 命令**
- **纯 shell 提供 `webnovel-codex` fallback**
- **底层统一复用 `webnovel-writer/scripts/webnovel.py`、`workflow_manager.py`、Dashboard 服务**

对外命令契约以 `/webnovel-writer:*` 为准，便于开源维护和跨运行时对齐。
