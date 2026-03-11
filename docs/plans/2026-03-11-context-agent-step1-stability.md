# Context Agent Step1 稳定性改造记录（2026-03-11）

## 背景
- 现象：`webnovel-write` 在 Step 1（Context Agent）频繁卡住，出现 `502 Bad Gateway` / `429 Too Many Requests`，导致单次运行长时间停留在 Step 1。
- 影响：
  - 写作链路被阻断，无法稳定进入 Step 2A~Step 6。
  - 重跑时重复消耗 token，且再次触发上游异常概率上升。
- 已确认：Context Agent 当前是**串行分段**执行，不是并行同时启动多个子进程。

## 方案对比

### 方案 A：回滚到旧模式（单段 Context 或手工补链）
- 优点：改动小，短期可恢复“看起来能跑”。
- 缺点：
  - 与“完整复刻 Claude Code 流程”目标偏离。
  - 易回到手工补链/非严格自动化路径，审查与修改链路可追溯性下降。
  - 无法根治 Step1 重跑浪费与断点恢复问题。

### 方案 B：保留分段 Context Agent，增加断点续跑/缓存复用（本次选择）
- 核心：
  - Step1 仍按 6 子阶段执行，保持流程完整。
  - 已成功子阶段结果可复用；重跑只从失败段继续。
  - 若整包 `context_package` 已存在且校验通过，直接复用进入 Step2A。
- 预期收益：
  - 大幅减少重复请求与 token 浪费。
  - 提升 Step1 在网络抖动场景下的可完成率。
  - 保持“失败即终止 / 成功才进入下一步”的严格语义。

## 实施范围
- 代码：`webnovel-writer/scripts/codex_write_workflow.py`
- 测试：`webnovel-writer/scripts/data_modules/tests/test_codex_write_workflow.py`

## 变更原则
- 不引入“手工补写正文”的兜底路径。
- 不跳过 Step3/Step4 审查与修改环节。
- 失败策略保持：Step 失败即终止当前流程。

## 回滚路径
- 代码级回滚：
  - `git checkout -- webnovel-writer/scripts/codex_write_workflow.py`
  - `git checkout -- webnovel-writer/scripts/data_modules/tests/test_codex_write_workflow.py`
  - `git checkout -- docs/plans/2026-03-11-context-agent-step1-stability.md`
- 提交级回滚（若后续产生提交）：
  - 使用 `git revert <commit>` 回退本次提交。

## 验证计划
1. 单测：
   - Context Agent 分段调用顺序仍正确。
   - 已产出的分段结果可被复用，缺失段才会继续调用。
   - 已完成的 `context_package` 可直接复用。
2. 端到端：
   - `webnovel-write <chapter>` 在 Step1 异常重跑时可从断点继续。

## 实际改动（已完成）
1. `codex_write_workflow.py`
   - 新增 Context 专用参数：
     - `WEBNOVEL_CONTEXT_STAGE_TIMEOUT_SECONDS`
     - `WEBNOVEL_CONTEXT_STAGE_RETRIES`
   - 新增缓存读取与校验逻辑：
     - `_read_json_object`
     - `_load_cached_context_package`
   - Step1 分段执行改为可断点复用：
     - 若 `stage.input.json` 与本次输入一致且 `stage.json` 合法，则直接复用该段结果，不再重复请求上游。
     - 若 `context.compact.json` 与本次一致且已有合法 `context_package`，直接复用整包。
   - 维持严格语义：
     - 仍是串行 6 段；
     - 失败仍抛错终止，不做“手工写正文”兜底。

2. `test_codex_write_workflow.py`
   - 新增 3 个用例：
     - `test_run_context_agent_stage_reuses_cached_segment_when_input_unchanged`
     - `test_run_context_agent_stage_reuses_cached_context_package_when_compact_unchanged`
     - `test_run_context_agent_stage_invalidates_segment_cache_when_input_changes`
   - 用例覆盖：
     - 分段缓存命中；
     - 整包缓存命中；
     - 输入变化时禁止复用旧缓存。

## 测试结果（已完成）
- 通过：
  - `pytest -q --no-cov webnovel-writer/scripts/data_modules/tests/test_codex_write_workflow.py`
  - `pytest -q --no-cov webnovel-writer/scripts/data_modules/tests/test_codex_command_registry.py webnovel-writer/scripts/data_modules/tests/test_codex_cli.py`
- 说明：
  - 仓库默认开启覆盖率门槛（90%）；本次为定向功能验证，使用 `--no-cov` 避免被全仓覆盖率门槛阻断。
