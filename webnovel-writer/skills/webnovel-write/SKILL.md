---
name: webnovel-write
description: Writes webnovel chapters (default 2000-2500 words). Use when the user asks to write a chapter or runs /webnovel-write. Runs context, drafting, review, polish, and data extraction.
allowed-tools: Read Write Edit Grep Bash Task
---

# Chapter Writing (Structured Workflow v2)

## 目标

- 以稳定流程产出可发布章节：`正文/第{volume_num}卷/第{chapter_short_padded}章.md`。
- 默认章节字数目标：2000-2500（用户或大纲明确覆盖时从其约定）。
- 保证审查、润色、数据回写完整闭环，避免“写完即丢上下文”。
- 输出直接可被后续章节消费的结构化数据：`review_metrics`、`summaries`、`chapter_meta`。

## 执行原则

1. 先校验输入完整性，再进入写作流程；缺关键输入时立即阻断。
2. 审查与数据回写是硬步骤，`--fast`/`--minimal` 只允许降级可选环节。
3. 参考资料严格按步骤按需加载，不一次性灌入全部文档。
4. Step 2B 与 Step 4 职责分离：2B 只做风格转译，4 只做问题修复与质控。
5. 任一步失败优先做最小回滚，不重跑全流程。

## 模式定义

- `/webnovel-write`：Step 1 → 2A → 2B → 3 → 4 → 5 → 6
- `/webnovel-write --fast`：Step 1 → 2A → 3 → 4 → 5 → 6（跳过 2B）
- `/webnovel-write --minimal`：Step 1 → 2A → 3（仅3个基础审查）→ 4 → 5 → 6

最小产物（所有模式）：
- `正文/第{volume_num}卷/第{chapter_short_padded}章.md`
- `index.db.review_metrics` 新纪录（含 `overall_score`）
- `.webnovel/summaries/ch{NNNN}.md`
- `.webnovel/state.json` 的进度与 `chapter_meta` 更新

## 引用加载等级（strict, lazy）

- L0：未进入对应步骤前，不加载任何参考文件。
- L1：每步仅加载该步“必读”文件。
- L2：仅在触发条件满足时加载“条件必读/可选”文件。

路径约定：
- `references/...` 相对当前 skill 目录。
- `../../references/...` 指向全局共享参考。

## References（逐文件引用清单）

### 根目录

- `references/step-3-review-gate.md`
  - 用途：Step 3 审查调用模板、汇总格式、落库 JSON 规范。
  - 触发：Step 3 必读。
- `references/step-5-debt-switch.md`
  - 用途：Step 5 债务利息开关规则（默认关闭）。
  - 触发：Step 5 必读。
- `../../references/shared/core-constraints.md`
  - 用途：Step 2A 写作硬约束（大纲即法律 / 设定即物理 / 发明需识别）。
  - 触发：Step 2A 必读。
- `references/polish-guide.md`
  - 用途：Step 4 问题修复、Anti-AI 与 No-Poison 规则。
  - 触发：Step 4 必读。
- `references/writing/typesetting.md`
  - 用途：Step 4 移动端阅读排版与发布前速查。
  - 触发：Step 4 必读。
- `references/style-adapter.md`
  - 用途：Step 2B 风格转译规则，不改剧情事实。
  - 触发：Step 2B 执行时必读（`--fast`/`--minimal` 跳过）。
- `references/style-variants.md`
  - 用途：Step 1（内置 Contract）开头/钩子/节奏变体与重复风险控制。
  - 触发：Step 1 当需要做差异化设计时加载。
- `../../references/reading-power-taxonomy.md`
  - 用途：Step 1（内置 Contract）钩子、爽点、微兑现 taxonomy。
  - 触发：Step 1 当需要追读力设计时加载。
- `../../references/genre-profiles.md`
  - 用途：Step 1（内置 Contract）按题材配置节奏阈值与钩子偏好。
  - 触发：Step 1 当 `state.project.genre` 已知时加载。
- `references/writing/genre-hook-payoff-library.md`
  - 用途：电竞/直播文/克苏鲁的钩子与微兑现快速库。
  - 触发：Step 1 题材命中 `esports/livestream/cosmic-horror` 时必读。

### writing（问题定向加读）

- `references/writing/combat-scenes.md`
  - 触发：战斗章或审查命中“战斗可读性/镜头混乱”。
- `references/writing/dialogue-writing.md`
  - 触发：审查命中 OOC、对话说明书化、对白辨识差。
- `references/writing/emotion-psychology.md`
  - 触发：情绪转折生硬、动机断层、共情弱。
- `references/writing/scene-description.md`
  - 触发：场景空泛、空间方位不清、切场突兀。
- `references/writing/desire-description.md`
  - 触发：主角目标弱、欲望驱动力不足。

## 工具策略（按需）

- `Read/Grep`：读取 `state.json`、大纲、章节正文与参考文件。
- `Bash`：运行 `extract_chapter_context.py`、`review_prepare.py`、`review_finalize.py`、`index_manager`、`workflow_manager`。
- `Task`：Claude Code 可用于 `context-agent` / `data-agent` / 审查 subagent；Codex Desktop 由当前会话严格扮演这些 agent，不得跳步。

## 交互流程

## Desktop Strict Adapter（Codex Desktop 必做）

如果 helper 返回：
- `action.type=follow_skill`
- `action.execution_model=desktop_strict_follow_skill`

则不能直接自由执行写作流程，必须先走下面这条 artifact chain：

```bash
python "${SCRIPTS_DIR}/write_prepare.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}" --mode {standard|fast|minimal}
```

然后严格按阶段推进：
1. 读取当前阶段的 `*.prompt.txt`
2. 只生成该阶段要求的 `*.result.json`
3. 运行 `write_finalize.py --stage ...`
4. 由 `write_finalize.py` 生成下一阶段 prompt/schema 或拉起审查准备

禁止事项：
- 不得在 Codex Desktop 中直接以 `review_agents_runner.py` 作为 Step 3 主入口
- 不得在 Step 5 前手写 `.webnovel/tmp/chapter_{N}.json` 跳过前序阶段
- 不得把 Step 2B / Step 4 / Step 5 仅当作 workflow 标记；必须留下结构化产物

### Step 0：预检与上下文最小加载

必须做：
- 解析真实书项目根（book project_root）：必须包含 `.webnovel/state.json`。
- 校验核心输入：`大纲/总纲.md`、`${CLAUDE_PLUGIN_ROOT}/scripts/extract_chapter_context.py` 存在。
- 规范化变量：
  - `WORKSPACE_ROOT`：Claude Code 打开的工作区根目录（可能是书项目的父目录，例如 `D:\wk\xiaoshuo`）
  - `PROJECT_ROOT`：真实书项目根目录（必须包含 `.webnovel/state.json`，例如 `D:\wk\xiaoshuo\凡人资本论`）
  - `SKILL_ROOT`：skill 所在目录（固定 `${CLAUDE_PLUGIN_ROOT}/skills/webnovel-write`）
  - `SCRIPTS_DIR`：脚本目录（固定 `${CLAUDE_PLUGIN_ROOT}/scripts`）
  - `chapter_num`：当前章号（整数）
  - `chapter_padded`：四位章号（如 `0007`）
  - `chapter_short_padded`：三位章号（如 `007`）
  - `volume_num`：卷号（默认每 50 章一卷；第 1-50 章为第 1 卷）

环境设置（bash 命令执行前）：
```bash
# WORKSPACE_ROOT：Claude Code 的工作区根（通常等于 $CLAUDE_PROJECT_DIR）
export WORKSPACE_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"

if [ -z "${CLAUDE_PLUGIN_ROOT}" ] || [ ! -d "${CLAUDE_PLUGIN_ROOT}/skills/webnovel-write" ]; then
  echo "ERROR: 未设置 CLAUDE_PLUGIN_ROOT 或缺少目录: ${CLAUDE_PLUGIN_ROOT}/skills/webnovel-write" >&2
  exit 1
fi
export SKILL_ROOT="${CLAUDE_PLUGIN_ROOT}/skills/webnovel-write"

if [ -z "${CLAUDE_PLUGIN_ROOT}" ] || [ ! -d "${CLAUDE_PLUGIN_ROOT}/scripts" ]; then
  echo "ERROR: 未设置 CLAUDE_PLUGIN_ROOT 或缺少目录: ${CLAUDE_PLUGIN_ROOT}/scripts" >&2
  exit 1
fi
export SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"

if [ ! -f "${SCRIPTS_DIR}/extract_chapter_context.py" ]; then
  echo "ERROR: 缺少脚本: ${SCRIPTS_DIR}/extract_chapter_context.py" >&2
  exit 1
fi

# 解析真实书项目根（后续所有 Read/Write 路径都必须以 $PROJECT_ROOT 为前缀，避免写到工作区根目录）
export PROJECT_ROOT="$(python "${SCRIPTS_DIR}/webnovel.py" --project-root "${WORKSPACE_ROOT}" where)"

# 默认章节文件使用卷布局
chapter_padded="$(printf '%04d' "${chapter_num}")"
chapter_short_padded="$(printf '%03d' "${chapter_num}")"
volume_num="$(( (chapter_num - 1) / 50 + 1 ))"
```

输出：
- “已就绪输入”与“缺失输入”清单；缺失则阻断并提示先补齐。

### Step 0.5：工作流断点记录（best-effort，不阻断）

```bash
# 开始整条任务
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" workflow start-task --command webnovel-write --chapter {chapter_num} || true

# 进入某一步（示例：Step 1）
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" workflow start-step --step-id "Step 1" --step-name "Context Agent" || true

# Step 1 完成后记录（每个 Step 结束都要调用）
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" workflow complete-step --step-id "Step 1" --artifacts '{"ok":true}' || true

# 全部 Step 结束后，再结束整条任务
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" workflow complete-task --artifacts '{"ok":true}' || true
```

要求：
- `--step-id` 仅允许：`Step 1` / `Step 2A` / `Step 2B` / `Step 3` / `Step 4` / `Step 5` / `Step 6`。
- 任何记录失败只记警告，不阻断写作。
- 每个 Step 执行结束后，同样需要 `complete-step`（失败不阻断）。

### Step 1：Context Agent（内置 Contract v2，生成直写执行包）

Desktop strict 命令：
```bash
python "${SCRIPTS_DIR}/write_prepare.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}" --mode {standard|fast|minimal}
```

然后：
- 读取 `.webnovel/write_workflow/ch{chapter_padded}/context_agent.prompt.txt`
- 只输出合法 JSON 到 `.webnovel/write_workflow/ch{chapter_padded}/context_agent.result.json`
- 再执行：
```bash
python "${SCRIPTS_DIR}/write_finalize.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}" --mode {standard|fast|minimal} --stage context
```

使用 Task 调用 `context-agent`，参数：
- `chapter`
- `project_root`
- `storage_path=.webnovel/`
- `state_file=.webnovel/state.json`

硬要求：
- 若 `state` 或大纲不可用，立即阻断并返回缺失项。
- 输出必须同时包含：
  - 7 板块任务书（目标/冲突/承接/角色/场景约束/伏笔/追读力）；
  - Contract v2 全字段（目标/阻力/代价/本章变化/未闭合问题/开头类型/情绪节奏/信息密度/过渡章判定/追读力设计）；
  - Step 2A 可直接消费的“写作执行包”（章节节拍、不可变事实清单、禁止事项、终检清单）。
- 合同与任务书出现冲突时，以“大纲与设定约束更严格者”为准。

输出：
- 单一“创作执行包”（任务书 + Contract v2 + 直写提示词），供 Step 2A 直接消费，不再拆分独立 Step 1.5。

### Step 2A：正文起草

Desktop strict：
- 读取 `.webnovel/write_workflow/ch{chapter_padded}/draft.prompt.txt`
- 输出 `.webnovel/write_workflow/ch{chapter_padded}/draft.result.json`
- 再执行：
```bash
python "${SCRIPTS_DIR}/write_finalize.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}" --mode {standard|fast|minimal} --stage draft
```

执行前必须加载：
```bash
cat "${SKILL_ROOT}/../../references/shared/core-constraints.md"
```

硬要求：
- 只输出纯正文到 `正文/第{volume_num}卷/第{chapter_short_padded}章.md`。
- 默认按 2000-2500 字执行；若大纲为关键战斗章/高潮章/卷末章或用户明确指定，则按大纲/用户优先。
- 禁止占位符正文（如 `[TODO]`、`[待补充]`）。
- 保留承接关系：若上章有明确钩子，本章必须回应（可部分兑现）。

输出：
- 章节草稿（可进入 Step 2B 或 Step 3）。

### Step 2B：风格适配（`--fast` / `--minimal` 跳过）

Desktop strict：
- standard 模式下读取 `.webnovel/write_workflow/ch{chapter_padded}/style_adapter.prompt.txt`
- 输出 `.webnovel/write_workflow/ch{chapter_padded}/style_adapter.result.json`
- 再执行：
```bash
python "${SCRIPTS_DIR}/write_finalize.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}" --mode standard --stage style
```

执行前加载：
```bash
cat "${SKILL_ROOT}/references/style-adapter.md"
```

硬要求：
- 只做表达层转译，不改剧情事实、事件顺序、角色行为结果、设定规则。
- 对“模板腔、说明腔、机械腔”做定向改写，为 Step 4 留出问题修复空间。
- 必须至少做 2 轮：Pass A 局部改写，Pass B 全章重读后再修；不得只改一轮就交稿。
- 必须直接修改章节文件，再输出 `style_adapter.result.json`；JSON 中的 `content` 必须与最终文件一致。
- `style_adapter.result.json` 必须包含 `pass_reports` 与 `full_reread_count`，且至少有 1 次全章重读。

输出：
- 风格化正文（覆盖原章节文件）。

### Step 3：审查（full 路由；Desktop strict / shell source-runner）

执行前加载：
```bash
cat "${SKILL_ROOT}/references/step-3-review-gate.md"
```

调用约束：
- 在 Codex Desktop 中，必须先执行 `review_prepare.py` 生成 checker prompt，再逐个生成 checker JSON，最后执行 `review_finalize.py` 汇总；禁止主流程伪造审查结论。
- 在 shell/TUI 中，仍可执行 source-backed runner。
- 在 Claude Code 中，等价实现仍是 `Task` 调用审查 subagent。
- 可并行发起审查，统一汇总 `issues/severity/overall_score`。
- 写作主流程中，标准模式与 `--fast` 都必须使用 `full` 路由：6 个 checker 全跑。

审查器（`full` 必跑 6 个）：
- `consistency-checker`
- `continuity-checker`
- `ooc-checker`
- `reader-pull-checker`
- `high-point-checker`
- `pacing-checker`

模式说明：
- 标准/`--fast`：固定 6 个 checker
- `--minimal`：只跑核心 3 个（忽略条件审查器）

Codex Desktop 执行命令（必做）：
```bash
python "${SCRIPTS_DIR}/review_prepare.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}" --chapter-file "正文/第${volume_num}卷/第${chapter_short_padded}章.md" --mode full
```

对 `.webnovel/reviews/ch${chapter_padded}/checkers/*.prompt.txt` 中列出的每个 checker，必须：
- 只读取对应 prompt 文件
- 只输出合法 JSON 到同名 `.json`
- 不得把多个 checker 合并成一个总评文件

全部 checker JSON 写完后，必须执行：
```bash
python "${SCRIPTS_DIR}/review_finalize.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}"
```

审查完成后，在 Desktop strict 中还必须执行：
```bash
python "${SCRIPTS_DIR}/write_finalize.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}" --mode {standard|fast|minimal} --stage review-initial
```

Shell/TUI 执行命令（必做）：
```bash
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" review --chapter "${chapter_num}" --chapter-file "正文/第${volume_num}卷/第${chapter_short_padded}章.md" --mode full
```

硬要求：
- 上述 runner 成功后，必须存在：
  - `.webnovel/reviews/ch{chapter_padded}/aggregate.json`
  - `.webnovel/reviews/ch{chapter_padded}/checkers/*.json`
  - `审查报告/第{chapter_num}-{chapter_num}章审查报告.md`
- `aggregate.json` 必须包含：`selected_checkers`、`issues`、`severity_counts`、`overall_score`。
- 若 runner 失败、产物缺失，或 `aggregate.json` 缺少上述字段，必须停止流程；不得手写“审查总结”补位。
- `--minimal` 也必须产出 `overall_score`。
- 未落库 `review_metrics` 不得进入 Step 5。Codex runner 已内置落库，不要再手工伪造 `review_metrics.json`。

### Step 4：润色（问题修复优先）

执行前必须加载：
```bash
cat "${SKILL_ROOT}/references/polish-guide.md"
cat "${SKILL_ROOT}/references/writing/typesetting.md"
cat "${PROJECT_ROOT}/.webnovel/reviews/ch${chapter_padded}/aggregate.json"
```

执行顺序：
1. 修复 `critical`（必须）
2. 修复 `high`（不能修复则记录 deviation）
3. 处理 `medium/low`（按收益择优）
4. 基于修订后的章节文件，全章重读并执行 Anti-AI 全文终检（必须输出 `anti_ai_force_check: pass/fail`）
5. 再次全章重读，执行 No-Poison 与 typesetting 终检，必要时继续修
6. 必须重新执行一次 Step 3 的完整审查链，确认修订版 `aggregate.json` / 报告 / `review_metrics` 已覆盖旧版本

输出：
- 润色后正文（覆盖章节文件）
- 变更摘要（至少含：修复项、保留项、deviation、`anti_ai_force_check`）
- `polish.result.json` 必须包含 `pass_reports` 与 `full_reread_count`，且至少有 2 次全章重读。

Step 4 输入契约（Codex 必须遵守）：
- 审查问题源只能来自 `.webnovel/reviews/ch{chapter_padded}/aggregate.json` 的 `issues`
- 不得凭空补写“假问题”或“假修复项”

Desktop strict：
- 输出 `.webnovel/write_workflow/ch{chapter_padded}/polish.result.json`
- 再执行：
```bash
python "${SCRIPTS_DIR}/write_finalize.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}" --mode {standard|fast|minimal} --stage polish
```
- 随后必须重跑一遍 `review_prepare.py` + checker JSON + `review_finalize.py`
- 最后执行：
```bash
python "${SCRIPTS_DIR}/write_finalize.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}" --mode {standard|fast|minimal} --stage review-final
```

### Step 5：Data Agent（状态与索引回写）

当前会话必须严格扮演 `data-agent`，生成 `.webnovel/tmp/chapter_{chapter_num}.json`，然后执行数据回写脚本。参数：
- `chapter`
- `chapter_file="正文/第{volume_num}卷/第{chapter_short_padded}章.md"`
- `review_score=Step 3 overall_score`
- `project_root`
- `storage_path=.webnovel/`
- `state_file=.webnovel/state.json`

执行后检查（最小白名单）：
- `.webnovel/state.json`
- `.webnovel/index.db`
- `.webnovel/summaries/ch{chapter_padded}.md`
- `.webnovel/observability/data_agent_timing.jsonl`（观测日志）

Codex 补强步骤（必做）：
```bash
python "${SCRIPTS_DIR}/write_finalize.py" --project-root "${PROJECT_ROOT}" --chapter "${chapter_num}" --mode {standard|fast|minimal} --stage data
```

原因：
- `state process-chapter` 只保证 `state.json` / `review_metrics` / `summaries` 等核心状态落地；
- dashboard 的 `章节一览` 与 `追读力` 依赖 `index.db.chapters`、`index.db.scenes`、`index.db.chapter_reading_power`；
- Step 3 的审查 runner 在 `aggregate.pass=true` 时会先做一次“审查通过后补库”；
- 但 Step 5 会继续刷新 `state.json.chapter_meta` / `summaries` 等结构化源数据，所以 Step 5 结束后仍必须再执行一次 `sync-chapter-data`，把最终版本覆盖回去，不能只检查 `index.db` 文件是否存在。

性能要求：
- 读取 timing 日志最近一条；
- 当 `TOTAL > 30000ms` 时，输出最慢 2-3 个环节与原因说明。

债务利息：
- 默认关闭，仅在用户明确要求或开启追踪时执行（见 `step-5-debt-switch.md`）。

### Step 6：Git 备份（可失败但需说明）

```bash
git add .
git commit -m "Ch{chapter_num}: {title}"
```

规则：
- 若 commit 失败，必须给出失败原因与未提交文件范围。

## 充分性闸门（必须通过）

未满足以下条件前，不得结束流程：

1. 章节正文文件存在且非空：`正文/第{volume_num}卷/第{chapter_short_padded}章.md`
2. Step 3 已产出 `overall_score` 且 `review_metrics` 成功落库
3. Step 4 已处理全部 `critical`，`high` 未修项有 deviation 记录
4. Step 4 的 `anti_ai_force_check=pass`（基于全文检查；fail 时不得进入 Step 5）
5. Step 5 已回写 `state.json`、`index.db`、`summaries/ch{chapter_padded}.md`
6. Step 5 后已执行 `sync-chapter-data --chapter {chapter_num}`，且 `chapters/scenes/chapter_reading_power` 对应章节可查询
7. 若开启性能观测，已读取最新 timing 记录并输出结论

## 验证与交付

执行检查：

```bash
test -f "${PROJECT_ROOT}/.webnovel/state.json"
test -f "${PROJECT_ROOT}/正文/第${volume_num}卷/第${chapter_short_padded}章.md"
test -f "${PROJECT_ROOT}/.webnovel/summaries/ch${chapter_padded}.md"
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" index get-recent-review-metrics --limit 1
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" sync-chapter-data --chapter "${chapter_num}"
tail -n 1 "${PROJECT_ROOT}/.webnovel/observability/data_agent_timing.jsonl" || true
```

成功标准：
- 章节文件、摘要文件、状态文件齐全且内容可读。
- 审查分数可追溯，`overall_score` 与 Step 5 输入一致。
- 当前章节在 `index.db.chapters`、`index.db.scenes`、`index.db.chapter_reading_power` 中均存在记录。
- 润色后未破坏大纲与设定约束。

## 失败处理（最小回滚）

触发条件：
- 章节文件缺失或空文件；
- 审查结果未落库；
- Data Agent 关键产物缺失；
- 润色引入设定冲突。

恢复流程：
1. 仅重跑失败步骤，不回滚已通过步骤。
2. 常见最小修复：
   - 审查缺失：只重跑 Step 3 并落库；
   - 润色失真：恢复 Step 2A 输出并重做 Step 4；
   - 摘要/状态缺失：只重跑 Step 5；
3. 重新执行“验证与交付”全部检查，通过后结束。
