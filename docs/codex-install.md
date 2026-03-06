# Codex 安装说明

这份文档面向 **普通用户**，目标是让你不需要理解内部实现，也能按步骤把 `webnovel-writer` 装到 Codex 里使用。

本仓库是 **基于上游 [`lingfengQAQ/webnovel-writer`](https://github.com/lingfengQAQ/webnovel-writer) 改造的 Codex 适配版本**。

因此这份文档只讲 **Codex 用户的安装和使用方式**。

如果你只是想照着一步步操作，直接按本文执行即可。

## 适用场景

你希望在 **Codex 桌面版 / Codex CLI** 里，尽量沿用原项目的命令习惯，例如：

```text
/webnovel-writer:webnovel-init
/webnovel-writer:webnovel-write 1
/webnovel-writer:webnovel-dashboard
```

说明：

- **在终端 fallback 中**，可以继续使用原 slash 契约
- **在 Codex 对话框中**，不要直接输入未知的 `/webnovel-writer:*`
- 当前 Codex 会先拦截未知 `/命令`，所以在对话框里应改用自然语言触发

## 运行环境

建议环境：

- macOS / Linux
- Git
- Node.js / npm
- Python `3.11`（推荐）或 `3.9+`（最低兼容）
- 可用的 `pip`
- 已安装并可正常启动的 Codex

说明：

- **推荐 Python 3.11**，是为了避免你本机环境过旧时遇到解释器差异。
- 当前仓库已经补过兼容层，**Python 3.9+ 也能运行 Codex 适配层**。
- 正常使用 **不需要 Node.js**，Dashboard 前端产物已经随仓库提供。

## 0) 先确认 Codex 已安装

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

如果仍然找不到 `codex`，请先解决 Codex 本体安装或 `PATH` 配置问题，再继续下面的安装步骤。

确认 `codex --version` 正常后，再继续下面的安装步骤。

## 会安装哪些支持库

执行 `requirements.txt` 后，会安装下面这些 Python 依赖：

### 核心写作链路

- `aiohttp`
- `filelock`
- `pydantic`

### Dashboard

- `fastapi`
- `uvicorn[standard]`
- `watchdog`

### 开发 / 测试（普通用户可一起装，无害）

- `pytest`
- `pytest-cov`
- `pytest-asyncio`
- `pytest-timeout`

## 1) 克隆仓库

如果你用官方仓库：

```bash
git clone https://github.com/lingfengQAQ/webnovel-writer.git
cd webnovel-writer
```

如果你用自己的 fork，把地址替换成你的仓库地址即可。

## 2) 安装 Python 依赖

在仓库根目录执行：

```bash
python3 -m pip install -r requirements.txt
```

如果你的系统没有 `python3`，先确认 Python 是否已正确安装。

macOS 常见安装方式：

```bash
brew install python@3.11
```

安装成功后可验证：

```bash
python3 --version
```

## 3) 先跑一次临时烟测（推荐）

这一步**不会污染真实 `~/.codex`**，只是先验证适配层是否能正常工作。

执行：

```bash
python3 scripts/smoke_test_codex_support.py
```

如果看到类似下面的结果，就说明通过了：

```json
{
  "status": "ok"
}
```

这一步会自动完成：

1. 创建临时 `CODEX_HOME`
2. 安装 Codex 适配层
3. 调用一次 `/webnovel-writer:webnovel-init`
4. 执行恢复
5. 清理临时目录

如果你想保留现场排查，可以这样跑：

```bash
python3 scripts/smoke_test_codex_support.py --keep-temp
```

## 4) 安装到真实 Codex

确认临时烟测通过后，再执行真实安装：

```bash
python3 scripts/install_codex_support.py
```

安装完成后，默认会写入以下位置：

- `~/.codex/skills/webnovel-writer`
- `~/.codex/bin/webnovel-codex`
- `~/.codex/bin/webnovel-codex-restore`
- `~/.codex/webnovel-writer/install_state.json`

其中：

- `webnovel-codex` 是 shell fallback 入口
- `webnovel-codex-restore` 是一键恢复入口
- `install_state.json` 用来记录安装前备份和恢复信息

## 5) 先验证 fallback

先不要启动 Codex。

继续在当前这个终端窗口里执行：

```bash
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-init" --mode codex --json
```

如果这一步成功，输出里应至少包含下面这两个字段：

```json
{
  "status": "ok",
  "command": {
    "name": "webnovel-init"
  }
}
```

如果这一步不正常，就先不要继续下一步。

## 6) 创建小说工作目录

继续在同一个终端窗口里执行：

```bash
mkdir -p "$HOME/Documents/webnovel-workspace"
cd "$HOME/Documents/webnovel-workspace"
```

执行完后，你当前所在目录就是以后放小说项目的地方。

## 7) 启动 Codex

继续在同一个终端窗口里执行：

```bash
codex
```

执行后，你会进入 Codex 会话界面。

## 8) 在 Codex 里输入初始化命令

进入 Codex 会话后，**不要直接输入以 `/` 开头的原始命令**。

当前 Codex 会先拦截未知的 `/命令`，它们在到达模型前就会被拒绝。

所以在 Codex 对话里，先输入：

```text
请使用 webnovel-writer 初始化一个小说项目。
```

这一步会开始初始化小说项目，并在当前工作目录下创建书项目。

## 9) 初始化完成后，继续使用这些命令

```text
请使用 webnovel-writer 规划第 1 卷。
请使用 webnovel-writer 写第 1 章。
请使用 webnovel-writer 审查第 1 到 5 章。
请使用 webnovel-writer 打开 dashboard。
```

## 10) 初始化项目后，补 RAG 配置

在你运行完：

```text
/webnovel-writer:webnovel-init
```

之后，进入新建的书项目根目录，创建 `.env`。

如果项目里已有模板文件：

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

说明：

- `EMBED_API_KEY`：Embedding 服务 Key
- `RERANK_API_KEY`：Rerank 服务 Key
- 不配 RAG 也能跑部分流程，但检索能力会下降

## 11) 如何恢复到安装前状态

如果你想撤销这次 Codex 安装，执行：

```bash
~/.codex/bin/webnovel-codex-restore
```

恢复逻辑：

- 如果安装前已有旧版 `webnovel-writer` skill / wrapper，就恢复旧版
- 如果安装前没有，就删除这次安装生成的文件
- 同时清理 `install_state.json` 和对应备份目录

## 12) 常见问题

### Q1：`python: command not found`

请改用：

```bash
python3 -m pip install -r requirements.txt
```

并确认：

```bash
python3 --version
```

### Q2：Dashboard 打不开

先确认依赖已经安装：

```bash
python3 -m pip install -r requirements.txt
```

再通过 fallback 启动：

```bash
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-dashboard" --execute-dashboard
```

### Q3：我担心装坏 `~/.codex`

先跑：

```bash
python3 scripts/smoke_test_codex_support.py
```

这一步就是为了解决这个问题。

## 推荐的完整用户流程

如果你想严格按“普通用户视角”走一遍，推荐顺序：

```bash
git clone <your-repo-url>
cd webnovel-writer
python3 -m pip install -r requirements.txt
python3 scripts/smoke_test_codex_support.py
python3 scripts/install_codex_support.py
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-init" --mode codex --json
mkdir -p "$HOME/Documents/webnovel-workspace"
cd "$HOME/Documents/webnovel-workspace"
codex
```

进入 Codex 后，先输入：

```text
请使用 webnovel-writer 初始化一个小说项目。
```

如果未来你不想用了，再执行：

```bash
~/.codex/bin/webnovel-codex-restore
```
