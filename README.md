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

先确认你当前就在仓库根目录；如果不是，先执行：

```bash
cd /Users/robin/Documents/newbook/webnovel-writer-worktrees/.worktrees/codex-adapter-mvp
```

再执行：

```bash
python3 scripts/install_codex_support.py
```

如果你人在别的目录，也可以直接用绝对路径：

```bash
python3 /Users/robin/Documents/newbook/webnovel-writer-worktrees/.worktrees/codex-adapter-mvp/scripts/install_codex_support.py
```

安装完成后会：

- 把 Codex skill 安装到 `~/.codex/skills/webnovel-writer`
- 生成 shell fallback：`~/.codex/bin/webnovel-codex`
- 生成一键恢复入口：`~/.codex/bin/webnovel-codex-restore`
- 写入安装状态：`~/.codex/webnovel-writer/install_state.json`
- 自动把运行时依赖安装到“当前执行安装脚本的这套 Python”里
- 让 `webnovel-codex` 固定使用这套 Python，而不是随 shell 漂移到别的 `python3`
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
  },
  "action": {
    "type": "external_init"
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

### 7) 在终端里启动初始化向导（推荐）

继续在同一个终端窗口里执行：

```bash
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-init" --mode shell
```

这一步会直接进入 **source-backed 初始化向导**：

- 步骤顺序按上游 `webnovel-init/SKILL.md`
- 使用 `prompt_toolkit` 全屏 TUI，长列表会固定窗口滚动显示
- 选择菜单支持 `↑/↓` 移动，`Enter` / `Space` 直接确认，不再需要 `Tab` 到按钮
- 题材、主角结构、感情线、成长节奏等可枚举项优先走选择
- Step 5 创意约束包保留按题材动态生成的推荐项，并追加 `系统推荐` / `自定义`
- 手动输入项会带上 source-backed 提示和示例；若书名映射出的项目目录已存在，会要求你重新命名
- 最后会先给你看“初始化摘要草案”，只有你确认后才真正生成项目

这也是当前 **最接近 Claude Code TUI 的确定性初始化入口**。

### 8) 初始化完成后，先进入新书项目目录

初始化成功后，程序会自动把“进入新书项目目录”的命令复制到剪贴板。

你现在只需要在当前终端窗口里：

- 按 `Cmd+V`
- 再按回车

这样就会进入刚刚生成的新书项目目录。

如果自动复制失败，终端会打印一条可直接复制的 `cd "..."` 命令；你手动复制那条命令并回车即可。

### 9) 配置 RAG 环境（必做）

进入书项目目录后，继续执行：

```bash
cp .env.example .env
open -e .env
```

打开 `.env` 后，你会看到 6 个字段：

```bash
EMBED_BASE_URL=https://api-inference.modelscope.cn/v1
EMBED_MODEL=Qwen/Qwen3-Embedding-8B
EMBED_API_KEY=

RERANK_BASE_URL=https://api.jina.ai/v1
RERANK_MODEL=jina-reranker-v3
RERANK_API_KEY=
```

字段说明：

- `EMBED_BASE_URL`：Embedding 服务地址；默认是 ModelScope 的推理地址
- `EMBED_MODEL`：Embedding 模型名；默认是 `Qwen/Qwen3-Embedding-8B`
- `EMBED_API_KEY`：Embedding 服务的 API Key，需要你自己去对应平台注册获取
- `RERANK_BASE_URL`：Rerank 服务地址；默认是 Jina 的 API 地址
- `RERANK_MODEL`：Rerank 模型名；默认是 `jina-reranker-v3`
- `RERANK_API_KEY`：Rerank 服务的 API Key，需要你自己去对应平台注册获取

使用建议：

- 如果你先想跑通流程，可以先保留默认 `BASE_URL` 和 `MODEL`
- 你至少需要填好 `EMBED_API_KEY` 和 `RERANK_API_KEY`
- 如果你要换成自己的向量模型 / rerank 服务，请把对应的 `BASE_URL`、`MODEL`、`API_KEY` 成套改掉，不要只改其中一项

### 10) 再启动 Codex

继续在同一个终端窗口里执行：

```bash
codex
```

执行后，你会进入 Codex 会话界面。

### 11) 进入 Codex 后，继续使用这些命令

```text
请使用 webnovel-writer 规划第 1 卷。
请使用 webnovel-writer 写第 1 章。
请使用 webnovel-writer 审查第 1 到 5 章。
请使用 webnovel-writer 打开 dashboard。
```

写作 / 审查链路补充说明：

- `webnovel-write` 的 Step 3 审查现在是 source-backed runner，不再允许对话里手写“自审结论”
- `webnovel-review` 现在也不再走 `follow_skill`；Codex helper 会直接分发到 `webnovel-writer/scripts/codex_review_workflow.py`
- `codex_review_workflow.py` 会按上游 `webnovel-review` 的 Step 0.5 -> Step 8 顺序执行：workflow 记录、checker 审查、指标确认、`update-state --add-review`、收尾
- runner 会并行拉起多个 `codex exec` checker 子进程
- 如果子进程连续出现 provider 重连/502，runner 会快速判失败，不再把所有 checker 逐个拖满超时
- 快速失败后会先尝试 aggregate fallback；若 fallback 也失败，则补齐 `degraded_local` 审查产物，并在 `aggregate.json` / 审查报告里写出 `execution_mode`
- 单章审查在 `aggregate.pass=true` 时，会自动执行一次 `sync-chapter-data --chapter N`，把 dashboard 的 `章节一览 / 追读力` 刷到当前通过版本
- 如果章节返工后重新审查，只要新的审查结果再次通过，就会再次执行 `sync-chapter-data` 覆盖旧索引
- `webnovel-write` 的 Step 5 在写回 `state.json.chapter_meta` / 摘要后，仍会再执行一次 `sync-chapter-data`，确保最终结构化数据与 dashboard 一致
- 审查完成后会写出：
  - `.webnovel/reviews/chNNNN/checkers/*.json`
  - `.webnovel/reviews/chNNNN/aggregate.json`
  - `审查报告/第N-N章审查报告.md`
- 区间审查还会额外写：
  - `.webnovel/reviews/range-XXXX-YYYY/aggregate.json`
  - `审查报告/第X-Y章审查报告.md`
- 命令拓扑基线见：`docs/plans/2026-03-09-codex-parity-topology.md`

#### 控制器 demo proof（最小验证）

进入书项目目录后，在 Codex 中输入：

```text
开始控制器测试
```

预期结果：

- Codex 直接进入仓库自带的 5 步控制器 demo
- 只会写入 `controller-demo/` 与 `.webnovel/controller_sessions/`
- 不会额外生成 `docs/plans`

### 12) 开始使用

```bash
/webnovel-writer:webnovel-plan 1
/webnovel-writer:webnovel-write 1
/webnovel-writer:webnovel-review 1-5
```

### 13) 启动可视化面板（可选）

```bash
/webnovel-writer:webnovel-dashboard
```

说明：
- Dashboard 为只读面板（项目状态、实体图谱、章节/大纲浏览、追读力查看）。
- Codex 版默认监听 `http://127.0.0.1:18765`，并会尝试自动打开默认浏览器，避免与 Claude 版常见的 `8765` 端口冲突。
- 前端构建产物已随插件发布，使用者无需本地 `npm build`。
- Python 3.9 环境下也可运行；仓库内已移除会导致 `str | None` 报错的注解炸点。

### 14) 恢复到安装前状态

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
