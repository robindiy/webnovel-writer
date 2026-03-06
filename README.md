# Webnovel Writer

[![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![Codex](https://img.shields.io/badge/Codex-Compatible-green.svg)](https://openai.com/)

## 项目简单介绍

这是一个 **基于上游项目 [`lingfengQAQ/webnovel-writer`](https://github.com/lingfengQAQ/webnovel-writer) 改造的 Codex 适配版本**。

目标是把原项目的小说工作流、命令习惯、RAG 配置和 Dashboard 能力迁移到 **Codex 桌面版 / Codex CLI**，让 Codex 用户可以直接使用。

如果你是普通用户，可以把这个仓库理解为：

- **来源**：派生自上游 `webnovel-writer`
- **定位**：面向 Codex 用户的适配版本
- **目标**：尽量保留原命令契约，如 `/webnovel-writer:*`

详细文档已拆分到 `docs/`：

- Codex 安装：`docs/codex-install.md`
- 架构与模块：`docs/architecture.md`
- 命令详解：`docs/commands.md`
- RAG 与配置：`docs/rag-and-config.md`
- 题材模板：`docs/genres.md`
- 运维与恢复：`docs/operations.md`
- 文档导航：`docs/README.md`

## 快速开始

### 1) 克隆仓库

```bash
git clone <your-repo-url>
cd webnovel-writer
```

### 2) 安装 Python 依赖

```bash
python3 -m pip install -r requirements.txt
```

说明：该入口会同时安装核心写作链路与 Dashboard 依赖，供 Codex 版本使用。

### 3) 先跑临时烟测（推荐）

这一步不会污染真实 `~/.codex`，只是先验证当前仓库的 Codex 安装链路是否正常：

```bash
python3 scripts/smoke_test_codex_support.py
```

### 4) 安装 Codex 支持

执行：

```bash
python3 scripts/install_codex_support.py
```

安装完成后会：

- 把 Codex skill 安装到 `~/.codex/skills/webnovel-writer`
- 生成 shell fallback：`~/.codex/bin/webnovel-codex`
- 生成一键恢复入口：`~/.codex/bin/webnovel-codex-restore`
- 写入安装状态：`~/.codex/webnovel-writer/install_state.json`
- 将当前仓库路径写入 skill 配置，后续可直接从 Codex 调用

### 5) 在 Codex 中使用原 slash 命令

优先保留原命令用法：

```text
/webnovel-writer:webnovel-init
/webnovel-writer:webnovel-plan 1
/webnovel-writer:webnovel-write 1
/webnovel-writer:webnovel-review 1-5
/webnovel-writer:webnovel-dashboard
```

如果在纯 shell 中使用 fallback：

```bash
~/.codex/bin/webnovel-codex webnovel-write 1
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-dashboard" --execute-dashboard
```

### 6) 初始化小说项目

在 Codex 中执行：

```bash
/webnovel-writer:webnovel-init
```

`/webnovel-writer:webnovel-init` 会在当前工作目录下按书名创建书项目，并写入当前项目指针。

### 7) 配置 RAG 环境（必做）

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

### 8) 开始使用

```bash
/webnovel-writer:webnovel-plan 1
/webnovel-writer:webnovel-write 1
/webnovel-writer:webnovel-review 1-5
```

### 9) 启动可视化面板（可选）

```bash
/webnovel-writer:webnovel-dashboard
```

说明：
- Dashboard 为只读面板（项目状态、实体图谱、章节/大纲浏览、追读力查看）。
- 前端构建产物已随插件发布，使用者无需本地 `npm build`。
- Python 3.9 环境下也可运行；仓库内已移除会导致 `str | None` 报错的注解炸点。

### 10) 恢复到安装前状态

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

兼容策略：

- **Codex 对话优先保留原 slash 命令**
- **纯 shell 提供 `webnovel-codex` fallback**
- **底层复用上游核心脚本、工作流和 Dashboard 服务**

对外命令契约以 `/webnovel-writer:*` 为准，便于开源维护和跨运行时对齐。
