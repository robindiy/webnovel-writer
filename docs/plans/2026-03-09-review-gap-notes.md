# 2026-03-09 Review Gap Notes

## 背景

用户对 `/webnovel-writer:webnovel-review 1-5` 的当前行为提出疑问，认为其与 Claude Code 中“写完每章后会审稿并改稿”的体验不一致。

## 已确认现象

1. `/webnovel-review 1-5` 当前产出的是区间审查报告与聚合结果，不会自动改写第 1-5 章正文。
2. 本次运行最终落盘成功，但分章报告显示 `execution_mode=degraded_local`，说明没有完整走到理想的多 checker 子进程审查路径。
3. 用户体感上没有看到“逐章审稿”的过程，也没有看到明确的多进程审查痕迹。
4. 用户预期的“审稿”包含：
   - 逐章检查
   - 调动多个 checker / 子进程
   - 在必要时直接修改措辞、修正文稿

## 第 7 章写作日志新增确认

1. Step 1 缺失：
   - 日志中没有 Task 调用 `context-agent`
   - 也没有形成明确的 Contract v2 / 写作执行包
   - 只有手工读取 `SKILL.md`、`core-constraints.md`、部分上下文

2. Step 2B 缺失：
   - 标准模式本应执行风格适配
   - 日志中没有读取 `references/style-adapter.md`
   - 也没有独立的风格转译步骤

3. Step 3 部分成立但质量降级：
   - 确实执行了 `review_agents_runner.py`
   - 但 `ch0007/aggregate.json` 里明确记录为 `execution_mode=degraded_local`
   - 这与“source-backed runner 并行拉起 codex exec checker 子进程”的理想路径不一致

4. Step 4 不符合规范：
   - 日志里只看到基于 1 个 low 问题手工改了章末
   - 没有看到按 `aggregate.json` 系统处理 critical/high/medium/low
   - 没有 `anti_ai_force_check`
   - 没有 deviation / 修复摘要输出

5. Step 5 不是 Data Agent：
   - 日志里没有 Task 调用 `data-agent`
   - 实际行为是手工写摘要，然后调用 `state process-chapter`
   - `.webnovel/observability/data_agent_timing.jsonl` 最新记录也不是 data-agent timing，而是 `state_manager:process-chapter`

6. 工作流断点记录不完整：
   - 技能规范要求 Step 1..6 都应 `start-step` / `complete-step`
   - 从日志可见，没有成体系地记录这些步骤

## 当前实现与用户预期的偏差

1. `webnovel-review` 更接近“生成审查报告”，不是“审查并自动改稿”。
2. 文稿改写逻辑主要在 `webnovel-write` 的 Step 4 polish，而不是独立的 `/webnovel-review`。
3. 当 review runner 降级到 `degraded_local` 时，审查可信度、可见度、过程反馈都会弱很多。

## 待验证事项

1. 测试 `/webnovel-write 7` 是否会正常触发：
   - Step 3 审查 runner
   - 多 checker / 子进程
   - Step 4 polish 对正文的实际修改
   - Step 5 数据回写与补库
2. 若 `/webnovel-write 7` 仍未表现出“审查后改稿”，需要把问题收敛到：
   - runner 没真正拉起子进程
   - Step 4 没消费审查结果
   - 技能流只生成报告，未进入润色修复

## 处理状态

- 先暂存，不在本次记录里直接修改实现。
- 等用户完成第 7 章写作测试后，再根据真实日志继续收敛问题。
