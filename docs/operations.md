# 项目结构与运维

## 目录层级（真实运行）

在 Codex 适配版下，至少有 4 层概念：

1. `WORKSPACE_ROOT`（你当前打开或执行命令的工作目录）
2. `PROJECT_ROOT`（真实小说项目根，`/webnovel-writer:webnovel-init` 按书名创建）
3. `CODEX_HOME`（Codex 用户目录，默认 `~/.codex`）
4. `SKILL_ROOT`（安装到 Codex 后的 skill 目录）

### A) 工作区目录

```text
workspace-root/
├── 小说A/
├── 小说B/
└── ...
```

### B) 小说项目目录（`PROJECT_ROOT`）

```text
project-root/
├── .webnovel/            # 运行时数据（state/index/vectors/summaries）
├── 正文/                  # 正文章节
├── 大纲/                  # 总纲与卷纲
└── 设定集/                # 世界观、角色、力量体系
```

### C) Codex 安装目录

Codex 支持安装完成后，默认会写入：

```text
~/.codex/
├── skills/
│   └── webnovel-writer/
├── bin/
│   ├── webnovel-codex
│   └── webnovel-codex-restore
└── webnovel-writer/
    └── install_state.json
```

## 常用运维命令

统一前置（手动 CLI 场景）：

```bash
export WORKSPACE_ROOT="$PWD"
export PROJECT_ROOT="/path/to/your/book-project"
```

### 索引重建

```bash
python3 webnovel-writer/scripts/webnovel.py --project-root "${PROJECT_ROOT}" index process-chapter --chapter 1
python3 webnovel-writer/scripts/webnovel.py --project-root "${PROJECT_ROOT}" index stats
```

### 健康报告

```bash
python3 webnovel-writer/scripts/webnovel.py --project-root "${PROJECT_ROOT}" status -- --focus all
python3 webnovel-writer/scripts/webnovel.py --project-root "${PROJECT_ROOT}" status -- --focus urgency
```

### 向量重建

```bash
python3 webnovel-writer/scripts/webnovel.py --project-root "${PROJECT_ROOT}" rag index-chapter --chapter 1
python3 webnovel-writer/scripts/webnovel.py --project-root "${PROJECT_ROOT}" rag stats
```

### 测试入口

```bash
python3 scripts/smoke_test_codex_support.py
python3 -m pytest
```

## Codex 适配层运维

### 安装到 Codex

```bash
python3 scripts/install_codex_support.py
```

默认会写入：

- `~/.codex/skills/webnovel-writer`
- `~/.codex/bin/webnovel-codex`
- `~/.codex/bin/webnovel-codex-restore`
- `~/.codex/webnovel-writer/install_state.json`

### 临时环境烟测（推荐先跑）

```bash
python3 scripts/smoke_test_codex_support.py
```

说明：

- 该命令会创建临时 `CODEX_HOME`
- 执行一次完整的“安装 → 命令代理 → 恢复”
- 默认结束后自动删除临时目录
- 如果要保留现场排查，可加 `--keep-temp`

### 一键恢复

如果真实 `~/.codex` 已安装了本适配层，需要回到安装前状态，执行：

```bash
~/.codex/bin/webnovel-codex-restore
```

恢复逻辑：

- 若安装前已有 `webnovel-writer` skill / wrapper，则恢复旧版本
- 若安装前不存在，则删除本次安装产生的 skill / wrapper
- 清理 `install_state.json` 与对应备份目录
