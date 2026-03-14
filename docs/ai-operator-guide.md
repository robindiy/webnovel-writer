# AI Operator Guide

目标：给 AI / Codex / 自动化代理一个**单一、可执行、可核对**的仓库操作说明。

本文件优先级：
- 对自动化调用、路径约束、章节落盘规则、dashboard 多书切换规则，本文件高于零散历史文档。
- 对创作流程细节，仍以对应 skill 的 `SKILL.md` 为准。

## 1. 快速启动

仓库根目录：

```bash
cd /root/newbook/code
```

初始化本地 Python 环境：

```bash
./scripts/bootstrap_env.sh
```

统一 Python 入口：

```bash
./scripts/py ...
```

统一测试入口（跳过仓库默认 coverage 门槛）：

```bash
./scripts/pytest-local ...
```

Dashboard 前端构建：

```bash
cd /root/newbook/code/webnovel-writer/dashboard/frontend
npm_config_cache=/tmp/npm-cache npm ci
npm_config_cache=/tmp/npm-cache npm run build
```

## 2. 绝对不要做的事

- 不要假设当前 `cwd` 就是书项目根。
- 不要手写 `正文/第0001章.md` 这类平铺章节路径。
- 不要绕过 `webnovel.py` 直接从 skill 里拼复杂 `python -m data_modules...` 命令。
- 不要直接访问 `PROJECT_ROOT` 之外的文件给 dashboard。
- 不要把 `.pydeps/` 当成正式源码的一部分提交。

## 3. 核心入口文件

- `/root/newbook/code/scripts/bootstrap_env.sh`
  - 作用：创建/更新仓库根 `.venv`
- `/root/newbook/code/scripts/py`
  - 作用：所有 Python 命令统一走仓库 `.venv`
- `/root/newbook/code/scripts/pytest-local`
  - 作用：本地定向测试入口
- `/root/newbook/code/scripts/dashboard-service.sh`
  - 作用：后台启动/停止/status dashboard
- `/root/newbook/code/webnovel-writer/scripts/data_modules/webnovel.py`
  - 作用：**统一 CLI 入口**
- `/root/newbook/code/webnovel-writer/scripts/project_locator.py`
  - 作用：解析真实 `PROJECT_ROOT`
- `/root/newbook/code/webnovel-writer/scripts/chapter_paths.py`
  - 作用：统一章节文件定位/默认落盘路径

## 4. PROJECT_ROOT 规则

合法书项目根目录必须满足：

```text
<PROJECT_ROOT>/.webnovel/state.json
```

自动化脚本必须优先通过下面命令确认项目根：

```bash
./scripts/py webnovel-writer/scripts/webnovel.py --project-root "<workspace-or-project-root>" where
```

说明：
- `--project-root` 可以传工作区根，也可以传真实书项目根。
- `project_locator.py` 会通过 `.claude/.webnovel-current-project`、用户级 registry、目录搜索解析真实书项目。

## 5. 章节路径硬约束

当前默认章节落盘规则：

```text
正文/第{volume_num}卷/第{chapter_num:03d}章.md
```

示例：
- 第 1 章：`正文/第1卷/第001章.md`
- 第 8 章：`正文/第1卷/第008章.md`
- 第 51 章：`正文/第2卷/第051章.md`

绝对约束：
- 创建新章节时，必须调用 `default_chapter_draft_path(...)`
- 查找已有章节时，必须调用 `find_chapter_file(...)`
- 不允许在新代码里重新写死 `正文/第0001章.md`

关键文件：
- `/root/newbook/code/webnovel-writer/scripts/chapter_paths.py`

## 6. webnovel-write 硬步骤

参考文件：
- `/root/newbook/code/webnovel-writer/skills/webnovel-write/SKILL.md`

当前约束：
- `Step 1`: Context Agent（内置 Contract v2）
- `Step 2A`: Draft
- `Step 2B`: Style Adapter（`--fast`/`--minimal` 可跳过）
- `Step 3`: Review
- `Step 4`: Polish
- `Step 5`: Data Agent 回写
- `Step 6`: Git 备份

最小完成产物：
- `正文/第{volume_num}卷/第{chapter_num:03d}章.md`
- `.webnovel/summaries/ch{chapter_num:04d}.md`
- `index.db.review_metrics` 记录
- `state.json.progress`
- `state.json.chapter_meta`

Step 3 必须先落库 `review_metrics`，再进入 Step 5。

Step 5 结束后最少要存在：
- `.webnovel/state.json`
- `.webnovel/index.db`
- `.webnovel/summaries/chNNNN.md`
- `.webnovel/observability/data_agent_timing.jsonl`

## 7. Dashboard 规则

后端：
- `/root/newbook/code/webnovel-writer/dashboard/app.py`
- `/root/newbook/code/webnovel-writer/dashboard/server.py`

前端：
- `/root/newbook/code/webnovel-writer/dashboard/frontend/src/App.jsx`
- `/root/newbook/code/webnovel-writer/dashboard/frontend/src/api.js`

当前 dashboard 行为：
- 支持多书项目选择页
- `/api/projects` 返回当前工作区内可读书项目列表
- 其余 `/api/*` 接口支持 `?project=<absolute-project-root>`
- 前端通过 `project` query param 切换当前书，而不是要求重启服务

后台启动：

```bash
./scripts/dashboard-service.sh start "<project-root-or-workspace>" 0.0.0.0 5678
./scripts/dashboard-service.sh status "<project-root-or-workspace>" 5678
./scripts/dashboard-service.sh stop "<project-root-or-workspace>" 5678
```

公网访问默认命令：

```bash
./scripts/dashboard-service.sh restart "<project-root-or-workspace>" 0.0.0.0 5678
```

## 8. 当前工作区书项目示例

当前 `/root/newbook` 下，至少存在这两个合法书项目：

- `/root/newbook/我真不是骗子`
- `/root/newbook/救命，我抢了曹操的女人`

两本书都已经按卷目录规则整理：
- 第一卷正文在 `正文/第1卷/`
- 第二卷默认新稿会写到 `正文/第2卷/`

## 9. Git 约束

仓库代码仓：

```text
/root/newbook/code
```

当前可运行版本分支：

```text
codex-cli-v20260314
```

注意：
- 书项目自己的 `.git` 与代码仓 `.git` 是分离的。
- 在某些沙箱会话里，书项目 `.git` 可能是只读映射，导致 Step 6 Git 失败。
- 若出现 `index.lock` / `read-only file system`，这通常是执行环境问题，不一定是仓库本身损坏。

## 10. AI 执行建议

如果你是自动化代理，推荐使用顺序：

1. `./scripts/bootstrap_env.sh`
2. `./scripts/py webnovel-writer/scripts/webnovel.py --project-root "<root>" where`
3. 根据任务调用 `webnovel.py`
4. 需要测试时用 `./scripts/pytest-local`
5. 需要 dashboard 时用 `./scripts/dashboard-service.sh`

不要自己发明新的 Python 入口层。

## 11. 迁移旧稿规则

如果发现旧书稿仍在平铺路径：

```text
正文/第0001章.md
```

迁移目标：

```text
正文/第1卷/第001章.md
```

迁移时必须同步检查：
- `workflow_state.json` 里的 `artifacts.chapter_file`
- RAG `source_file`
- 后续 `default_chapter_draft_path` 是否已切到卷目录

## 12. 当前已知有效验证命令

章节路径：

```bash
./scripts/py -m pytest -o addopts='' webnovel-writer/scripts/data_modules/tests/test_chapter_paths.py
```

Workflow 路径恢复：

```bash
./scripts/py -m pytest -o addopts='' webnovel-writer/scripts/data_modules/tests/test_workflow_manager.py -k cleanup_artifacts
```

RAG 章节 source_file：

```bash
./scripts/py -m pytest -o addopts='' webnovel-writer/scripts/data_modules/tests/test_rag_adapter.py -k rag_adapter_cli
```

Dashboard：

```bash
./scripts/py -m pytest -o addopts='' webnovel-writer/scripts/data_modules/tests/test_dashboard_imports.py
cd webnovel-writer/dashboard/frontend && npm_config_cache=/tmp/npm-cache npm run build
```
