# Codex 安装说明

这份文档面向 **普通用户**，目标是让你不需要理解内部实现，也能按步骤把 `webnovel-writer` 装到 Codex 里使用。

如果你只是想照着一步步操作，直接按本文执行即可。

## 适用场景

你希望在 **Codex 桌面版 / Codex CLI** 里，尽量沿用原项目的命令习惯，例如：

```text
/webnovel-writer:webnovel-init
/webnovel-writer:webnovel-write 1
/webnovel-writer:webnovel-dashboard
```

## 运行环境

建议环境：

- macOS / Linux
- Git
- Python `3.11`（推荐）或 `3.9+`（最低兼容）
- 可用的 `pip`
- 已安装并可正常启动的 Codex

说明：

- **推荐 Python 3.11**，是为了避免你本机环境过旧时遇到解释器差异。
- 当前仓库已经补过兼容层，**Python 3.9+ 也能运行 Codex 适配层**。
- 正常使用 **不需要 Node.js**，Dashboard 前端产物已经随仓库提供。

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

## 5) 安装后怎么用

### 方式 A：在 Codex 对话里用原 slash 命令

优先使用：

```text
/webnovel-writer:webnovel-init
/webnovel-writer:webnovel-plan 1
/webnovel-writer:webnovel-write 1
/webnovel-writer:webnovel-review 1-5
/webnovel-writer:webnovel-dashboard
```

### 方式 B：在终端里用 shell fallback

如果你想在终端直接验证，也可以：

```bash
~/.codex/bin/webnovel-codex webnovel-write 1
```

或者直接传完整 slash：

```bash
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-write 1"
```

如果要启动 Dashboard：

```bash
~/.codex/bin/webnovel-codex "/webnovel-writer:webnovel-dashboard" --execute-dashboard
```

## 6) 初始化项目后，补 RAG 配置

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

## 7) 如何恢复到安装前状态

如果你想撤销这次 Codex 安装，执行：

```bash
~/.codex/bin/webnovel-codex-restore
```

恢复逻辑：

- 如果安装前已有旧版 `webnovel-writer` skill / wrapper，就恢复旧版
- 如果安装前没有，就删除这次安装生成的文件
- 同时清理 `install_state.json` 和对应备份目录

## 8) 常见问题

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
```

之后在 Codex 里输入：

```text
/webnovel-writer:webnovel-init
```

如果未来你不想用了，再执行：

```bash
~/.codex/bin/webnovel-codex-restore
```
