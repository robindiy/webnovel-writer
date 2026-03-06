# Codex Adapter Handoff / Recovery

**Date:** 2026-03-06

**Branch:** `codex/codex-adapter-mvp`

**Worktree:** `/Users/robin/Documents/newbook/webnovel-writer-worktrees/.worktrees/codex-adapter-mvp`

## 这份文档给谁看

给后续接手的 AI 或人工维护者，用来快速回答 4 个问题：

1. 这一轮到底改了什么
2. 现在哪些地方已经验证过
3. 如果要继续开发，应该从哪里接着做
4. 如果装坏了本机 `~/.codex`，怎么恢复

## 已完成内容

### 1) Python 运行时兼容

目标：让仓库在 macOS 常见 `python3=3.9` 环境下尽量可跑。

已完成：

- 新增 `webnovel-writer/scripts/runtime_compat.py`
- Dashboard 与若干核心模块改为 Python 3.9 可导入
- 避免直接依赖裸 `python`

重点文件：

- `webnovel-writer/dashboard/server.py`
- `webnovel-writer/dashboard/app.py`
- `webnovel-writer/dashboard/watcher.py`
- `webnovel-writer/scripts/runtime_compat.py`

### 2) Codex 命令适配层

目标：尽量保留原插件命令契约，优先兼容：

- `/webnovel-writer:webnovel-init`
- `/webnovel-writer:webnovel-plan`
- `/webnovel-writer:webnovel-write`
- `/webnovel-writer:webnovel-review`
- `/webnovel-writer:webnovel-dashboard`

已完成：

- 单一来源命令注册表
- Codex CLI 适配器
- 对话模式下的编号选项文本
- shell fallback 命令

重点文件：

- `webnovel-writer/scripts/codex_command_registry.py`
- `webnovel-writer/scripts/codex_cli.py`
- `webnovel-writer/scripts/codex_interaction.py`

### 3) Codex 安装包

目标：把仓库能力正式安装到 Codex，而不是依赖本地手改缓存。

已完成：

- Codex skill 包：`codex-skills/webnovel-writer/`
- 安装脚本：`scripts/install_codex_support.py`
- shell wrapper：`scripts/webnovel-codex`
- 恢复脚本：`scripts/restore_codex_support.py`
- 临时烟测：`scripts/smoke_test_codex_support.py`

安装后默认写入：

- `~/.codex/skills/webnovel-writer`
- `~/.codex/bin/webnovel-codex`
- `~/.codex/bin/webnovel-codex-restore`
- `~/.codex/webnovel-writer/install_state.json`

## 已验证内容

### 单元 / 适配测试

已跑通过的测试命令：

```bash
python3 -m pytest --no-cov \
  webnovel-writer/scripts/data_modules/tests/test_runtime_compat.py \
  webnovel-writer/scripts/data_modules/tests/test_dashboard_imports.py \
  webnovel-writer/scripts/data_modules/tests/test_python39_core_imports.py \
  webnovel-writer/scripts/data_modules/tests/test_codex_command_registry.py \
  webnovel-writer/scripts/data_modules/tests/test_codex_cli.py \
  webnovel-writer/scripts/data_modules/tests/test_install_codex_support.py \
  codex-skills/webnovel-writer/scripts/test_install_skill_smoke.py \
  webnovel-writer/scripts/data_modules/tests/test_project_locator.py \
  webnovel-writer/scripts/data_modules/tests/test_webnovel_unified_cli.py -q
```

### 编译检查

已跑通过：

```bash
python3 -m py_compile \
  scripts/install_codex_support.py \
  scripts/restore_codex_support.py \
  scripts/smoke_test_codex_support.py \
  codex-skills/webnovel-writer/scripts/run_webnovel_command.py \
  webnovel-writer/scripts/codex_command_registry.py \
  webnovel-writer/scripts/codex_interaction.py \
  webnovel-writer/scripts/codex_cli.py \
  webnovel-writer/scripts/runtime_compat.py
```

### 临时安装烟测

推荐命令：

```bash
python3 scripts/smoke_test_codex_support.py
```

该命令会在临时目录里执行：

1. 预置旧版 `webnovel-writer` skill / wrapper
2. 安装新的 Codex 适配层
3. 通过已安装的 `webnovel-codex` 调用 `/webnovel-writer:webnovel-init`
4. 通过 `webnovel-codex-restore` 恢复旧版状态
5. 校验恢复成功并清理临时目录

## 恢复真实环境

如果已经对真实 `~/.codex` 执行过：

```bash
python3 scripts/install_codex_support.py
```

那么恢复方式是：

```bash
~/.codex/bin/webnovel-codex-restore
```

恢复脚本会读取：

- `~/.codex/webnovel-writer/install_state.json`

再按备份记录恢复或删除：

- `~/.codex/skills/webnovel-writer`
- `~/.codex/bin/webnovel-codex`
- `~/.codex/bin/webnovel-codex-restore`

## 当前已知问题

### 1) 旧测试基线并不完全干净

以下测试不是这轮适配新增的问题，而是仓库原有测试/调用假设不一致：

- `webnovel-writer/scripts/data_modules/tests/test_workflow_manager.py`

目前没有纳入这轮 Codex 适配的完成条件。

### 2) Codex 原生 slash 注册能力

当前实现是：

- 仓库内维护 `/webnovel-writer:*` 的单一映射
- Codex 通过 skill + adapter CLI + shell fallback 模拟原插件契约

如果未来 Codex 提供更正式的 slash 扩展注册机制，可以把当前 registry 继续作为底层单一来源，不需要推翻现有结构。

## 后续建议

1. 先在临时 `CODEX_HOME` 跑 `scripts/smoke_test_codex_support.py`
2. 确认无误后，再对真实 `~/.codex` 执行安装
3. 真机安装后，再补一轮针对 Codex 桌面对话流的人工验收
4. 最后再处理更深层的 skill 交互与命令 UI 优化
