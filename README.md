# Webnovel Writer

[![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-npm_required-green.svg)](https://nodejs.org/)
[![Codex](https://img.shields.io/badge/Codex-Compatible-green.svg)](https://openai.com/)

## 项目简单介绍

这是一个 **基于上游项目 [`lingfengQAQ/webnovel-writer`](https://github.com/lingfengQAQ/webnovel-writer) 改造的 Codex 适配版本**。

目标是把原项目的小说工作流、命令习惯、RAG 配置和 Dashboard 能力迁移到 **Codex 桌面版 / Codex CLI**，让 Codex 用户可以直接使用。

如果你是普通用户，可以把这个仓库理解为：

- **来源**：派生自上游 `webnovel-writer`
- **定位**：面向 Codex 用户的适配版本
- **目标**：在终端 fallback 中尽量保留原命令契约，如 `/webnovel-writer:*`

详细文档已拆分到 `docs/`：

- Codex 安装：`docs/codex-install.md`
- 架构与模块：`docs/architecture.md`
- 命令详解：`docs/commands.md`
- RAG 与配置：`docs/rag-and-config.md`
- 题材模板：`docs/genres.md`
- 运维与恢复：`docs/operations.md`
- 文档导航：`docs/README.md`

## 快速开始

### 0) 先确认 Codex 已安装

如果你还没有安装 Codex CLI，先执行官方安装命令：

```bash
npm i -g @openai/codex
```

如果这一步报 `npm: command not found`，说明你本机还没有可用的 Node.js / npm，需要先安装 Node.js，再重新执行上面的命令。

安装完成后，再执行：

```bash
codex --version
```

如果这一步报 `command not found`，先不要继续后面的安装步骤。

这通常说明有两种情况：

1. 你还没有安装 Codex
2. 你已经安装了 Codex，但当前终端还没有拿到 `codex` 命令

这时请先完成 Codex 的安装，并确认 `codex` 命令已经进入当前终端环境。

如果你刚装好 Codex，最常见的处理方式是：

```bash
exec $SHELL -l
codex --version
```

如果仍然找不到 `codex`，请先解决 Codex 本体安装或 `PATH` 配置问题，再继续下面的步骤。

确认 `codex --version` 正常后，再继续下面的步骤。

### 1) 克隆仓库

```bash
git clone <your-repo-url>
cd webnovel-writer
```

### 2) 初始化本地 Python 环境

```bash
./scripts/bootstrap_env.sh
```

说明：该入口会创建/复用仓库根目录下的 `.venv/`，并安装核心写作链路与 Dashboard 依赖。

后续在仓库里优先使用这两个命令入口，避免误用系统 Python：

```bash
./scripts/py -m pytest
./scripts/pytest-local webnovel-writer/scripts/data_modules/tests/test_state_manager_extra.py
```

### 3) 先跑临时烟测（推荐）

这一步不会污染真实 `~/.codex`，只是先验证当前仓库的 Codex 安装链路是否正常：

```bash
./scripts/py scripts/smoke_test_codex_support.py
```

### 4) 安装 Codex 支持

执行：

```bash
./scripts/py scripts/install_codex_support.py
```

安装完成后会：

- 把 Codex skill 安装到 `~/.codex/skills/webnovel-writer`
- 生成 shell fallback：`~/.codex/bin/webnovel-codex`
- 生成一键恢复入口：`~/.codex/bin/webnovel-codex-restore`
- 写入安装状态：`~/.codex/webnovel-writer/install_state.json`
- 将当前仓库路径写入 skill 配置，后续可直接从 Codex 调用

### 5) 先验证 fallback

先不要启动 Codex。

继续在当前这个终端窗口里执行：

```bash
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-init" --mode codex --json
```

如果这一步成功，输出里应至少包含：

```json
{
  "status": "ok",
  "command": {
    "name": "webnovel-init"
  }
}
```

这一步也顺便说明：**终端 fallback 支持原 slash 契约**。

### 6) 创建小说工作目录

继续在同一个终端窗口里执行：

```bash
mkdir -p "$HOME/Documents/webnovel-workspace"
cd "$HOME/Documents/webnovel-workspace"
```

这一步执行完后，你当前所在目录就是以后放小说项目的地方。

### 7) 启动 Codex

继续在同一个终端窗口里执行：

```bash
codex
```

执行后，你会进入 Codex 会话界面。

### 8) 在 Codex 里输入初始化命令

进入 Codex 会话后，**不要直接输入以 `/` 开头的原始命令**。

当前 Codex 会先拦截未知的 `/命令`，它们在到达模型前就会被拒绝。

所以在 Codex 对话里，请输入自然语言版本，例如：

```text
请使用 webnovel-writer 初始化一个小说项目。
```

这一步会开始初始化小说项目，并在当前工作目录下创建书项目。

### 9) 初始化完成后，继续使用这些命令

```text
请使用 webnovel-writer 规划第 1 卷。
请使用 webnovel-writer 写第 1 章。
请使用 webnovel-writer 审查第 1 到 5 章。
请使用 webnovel-writer 打开 dashboard。
```

### 10) 配置 RAG 环境（必做）

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

### 11) 开始使用

```bash
/webnovel-writer:webnovel-plan 1
/webnovel-writer:webnovel-write 1
/webnovel-writer:webnovel-review 1-5
```

### 12) 启动可视化面板（可选）

```bash
/webnovel-writer:webnovel-dashboard
```

说明：
- Dashboard 为只读面板（项目状态、实体图谱、章节/大纲浏览、追读力查看）。
- 前端构建产物已随插件发布，使用者无需本地 `npm build`。
- Python 3.9 环境下也可运行；仓库内已移除会导致 `str | None` 报错的注解炸点。

### 13) 恢复到安装前状态

如果你想撤销本次 Codex 安装，执行：

```bash
~/.codex/bin/webnovel-codex-restore
```

## 更新简介

| 版本 | 说明 |
|------|------|
| **Codex Adapter MVP** | 新增 Codex 命令适配层、安装脚本、恢复脚本、临时烟测、Dashboard 兼容和 shell fallback |
| **上游 v5.5.0** | 原始项目引入 Dashboard Skill 与实时刷新能力 |
| **上游历史版本** | 上游项目的历史能力与设计演进，作为本适配版的来源参考 |

## 开源协议

本项目使用 `GPL v3` 协议，详见 `LICENSE`。

## Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=lingfengQAQ/webnovel-writer&type=Date)](https://star-history.com/#lingfengQAQ/webnovel-writer&Date)

## 致谢

本适配版本使用 **Codex 配合 Vibe Coding** 方式开发。
上游原项目作者与设计来源请参考：[lingfengQAQ/webnovel-writer](https://github.com/lingfengQAQ/webnovel-writer)

## 贡献

欢迎提交 Issue 和 PR：

```bash
git checkout -b feature/your-feature
git commit -m "feat: add your feature"
git push origin feature/your-feature
```

## Codex 兼容说明

当前仓库对外只强调 **Codex 入口**：

- 安装脚本：`scripts/install_codex_support.py`
- Skill 包：`codex-skills/webnovel-writer`
- shell fallback：`~/.codex/bin/webnovel-codex`
- TUI 初始化快捷命令：`~/.codex/bin/webnovel-init`

兼容策略：

- **Codex 对话优先保留原 slash 命令**
- **纯 shell 提供 `webnovel-codex` fallback**
- **字段很多的初始化场景提供 `webnovel-init` TUI 快捷入口**
- **底层复用上游核心脚本、工作流和 Dashboard 服务**

对外命令契约以 `/webnovel-writer:*` 为准，便于开源维护和跨运行时对齐。
