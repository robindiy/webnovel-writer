# 2026-03-09 Codex Parity Topology

## 目标

把上游 `webnovel-writer` 的命令流完整拓扑出来，作为 Codex 适配层的唯一执行蓝图。后续所有 Codex 集成必须遵守以下原则：

1. 命令名与上游一致。
2. 参数来源与上游一致。
3. Step 顺序与上游一致。
4. 需要脚本调用的地方，优先走与上游相同的 `webnovel.py` / 子脚本入口。
5. 需要子代理/Task 的地方，Codex 不再“口头模拟”，而是改成 source-backed runner 或显式子进程。

## 全局公共约束

所有命令共享的公共前置：

1. `CLAUDE_PLUGIN_ROOT/scripts` 是上游技能文档中的脚本根。
2. `python "${SCRIPTS_DIR}/webnovel.py" --project-root "{WORKSPACE_ROOT}" where` 是统一 project root 解析入口。
3. `webnovel.py` 是稳定 CLI facade，负责把命令转发到：
   - `init_project.py`
   - `extract_chapter_context.py`
   - `review_agents_runner.py`
   - `workflow_manager.py`
   - `update_state.py`
   - `status_reporter.py`
   - `sync_chapter_data.py`
   - `data_modules/index_manager.py`
   - `data_modules/state_manager.py`
   - `data_modules/context_manager.py`
   - `data_modules/rag_adapter.py`
   - `data_modules/style_sampler.py`
4. 书项目根的定义不变：必须能解析到包含 `.webnovel/state.json` 的目录。

## 命令拓扑总表

| 命令 | 上游技能 | 参数来源 | 主要执行模型 | 核心脚本/入口 | Codex 对齐策略 |
|---|---|---|---|---|---|
| `webnovel-init` | `skills/webnovel-init/SKILL.md` | 用户输入 + 工作区路径 | 深交互采集 | `webnovel.py init` -> `init_project.py` | 外部 TUI，但采集字段/生成参数必须与上游 Step 0-6 同构 |
| `webnovel-plan` | `skills/webnovel-plan/SKILL.md` | 卷号/卷范围 | 技能驱动生成 | `webnovel.py where` + `update-state` | 先拓扑冻结，后续做 source-backed |
| `webnovel-write` | `skills/webnovel-write/SKILL.md` | 章节号 + 项目状态 | 多 Step 创作流水线 | `extract-context` / `review_agents_runner.py` / `index save-review-metrics` / `data-agent` / `git` | 重点改造成 source-backed runner |
| `webnovel-review` | `skills/webnovel-review/SKILL.md` | 单章/区间 | 多 checker 审查流水线 | `review_agents_runner.py` / `index save-review-metrics` / `update-state` / `workflow_manager.py` | 先改成 source-backed runner |
| `webnovel-dashboard` | `skills/webnovel-dashboard/SKILL.md` | 项目根 | 服务启动 | `python -m dashboard.server` | 已是脚本化入口，继续保留 |
| `webnovel-query` | `skills/webnovel-query/SKILL.md` | 查询词 | 只读查询 | `status_reporter.py` / 读取 state & 设定文件 | 先拓扑冻结，后续做 source-backed |
| `webnovel-resume` | `skills/webnovel-resume/SKILL.md` | 当前 workflow state | 恢复协议 | `workflow_manager.py detect/cleanup/clear` | 先拓扑冻结，后续做 source-backed |

## `webnovel-init` 上游拓扑

来源：`/Users/robin/Documents/newbook/webnovel-writer/webnovel-writer/skills/webnovel-init/SKILL.md`

### 参数来源

- `WORKSPACE_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"`
- 用户采集字段：
  - 书名
  - 题材（支持 A+B）
  - 目标规模
  - 一句话故事
  - 核心冲突
  - 目标读者/平台
  - 主角骨架
  - 反派分层
  - 金手指/代价/成长节奏
  - 世界观/势力/力量体系
  - 创意约束包

### Step 拓扑

1. Step 0：预检与上下文加载
   - 入口：`webnovel.py where`
   - 读取：
     - `references/system-data-flow.md`
     - `references/genre-tropes.md`
     - `templates/genres/`（按需）
2. Step 1：故事核与商业定位
3. Step 2：角色骨架与关系冲突
4. Step 3：金手指与兑现机制
5. Step 4：世界观与力量规则
6. Step 5：创意约束包
7. Step 6：一致性复述与最终确认
8. 执行生成：
   - `python "${SCRIPTS_DIR}/webnovel.py" init ...`
   - 实际落到 `init_project.py`

### Codex 对齐约束

- UI 可以是外部 `prompt_toolkit` TUI。
- 但采集字段、归一化选项、最终传给 `init_project.py` 的参数必须保持上游同构。
- 不能在 Codex 对话里自由发挥额外字段。

## `webnovel-plan` 上游拓扑

来源：`skills/webnovel-plan/SKILL.md`

### 参数来源

- `PROJECT_ROOT="$(python "${SCRIPTS_DIR}/webnovel.py" --project-root "${WORKSPACE_ROOT}" where)"`
- 命令参数：卷号或卷范围

### Step 拓扑

1. Load project data
2. Build setting baseline from `总纲 + 世界观`
3. Select volume
4. Generate volume beat sheet
5. Generate volume timeline
6. Generate volume skeleton
7. Generate chapter outlines (batched)
8. Enrich existing setting files from volume outline
9. Validate + save
10. `webnovel.py update-state -- --volume-planned ...`

### 关键文件

- `大纲/第{volume}卷-节拍表.md`
- `大纲/第{volume}卷-时间线.md`
- `大纲/第{volume}卷-详细大纲.md`
- `设定集/*`
- `.webnovel/state.json`

## `webnovel-write` 上游拓扑

来源：`skills/webnovel-write/SKILL.md`、`agents/context-agent.md`、`agents/data-agent.md`

### 参数来源

- 命令参数：`chapter_num`
- `PROJECT_ROOT="$(python "${SCRIPTS_DIR}/webnovel.py" --project-root "${WORKSPACE_ROOT}" where)"`
- 固定存储：
  - `storage_path=.webnovel/`
  - `state_file=.webnovel/state.json`

### Step 拓扑

1. Step 0：预检与最小加载
   - 校验：
     - `大纲/总纲.md`
     - `extract_chapter_context.py`
   - 解析 `PROJECT_ROOT`
2. Step 0.5：工作流断点记录
   - `workflow start-task --command webnovel-write --chapter {chapter_num}`
   - `workflow start-step --step-id "Step 1" --step-name "Context Agent"`
3. Step 1：Context Agent
   - Task 调用 `context-agent`
   - 参数：
     - `chapter`
     - `project_root`
     - `storage_path=.webnovel/`
     - `state_file=.webnovel/state.json`
   - 该 Agent 内部必须走：
     - `webnovel.py context -- --chapter {NNNN}`
     - `webnovel.py extract-context --chapter {NNNN} --format json`
     - `index get-recent-reading-power`
     - `index get-pattern-usage-stats`
     - `index get-hook-type-stats`
     - `index get-debt-summary`
     - `index get-core-entities`
     - `index recent-appearances --limit 20`
   - 输出：
     - 任务书
     - Contract v2
     - Step 2A 直写执行包
4. Step 2A：正文起草
   - 先读：`references/shared/core-constraints.md`
   - 输出正文到章节文件
5. Step 2B：风格适配
   - 先读：`references/style-adapter.md`
   - 仅做表达层转译
6. Step 3：审查
   - 先读：`references/step-3-review-gate.md`
   - 必须由 Task/子代理执行
   - 默认 `auto` 路由
   - 核心 checker：
     - `consistency-checker`
     - `continuity-checker`
     - `ooc-checker`
   - 条件 checker：
     - `reader-pull-checker`
     - `high-point-checker`
     - `pacing-checker`
   - 落库：
     - `webnovel.py index save-review-metrics --data '@review_metrics.json'`
7. Step 4：润色
   - 先读：
     - `references/polish-guide.md`
     - `references/writing/typesetting.md`
   - 顺序：
     - 修 critical
     - 修 high
     - 处理 medium/low
     - 执行 `anti_ai_force_check`
   - 输出：
     - 覆盖后的正文章节
     - 修复摘要 / deviation / anti_ai_force_check
8. Step 5：Data Agent
   - Task 调用 `data-agent`
   - 参数：
     - `chapter`
     - `chapter_file`
     - `review_score`
     - `project_root`
     - `storage_path=.webnovel/`
     - `state_file=.webnovel/state.json`
   - 写入：
     - `.webnovel/state.json`
     - `.webnovel/index.db`
     - `.webnovel/summaries/ch{NNNN}.md`
     - `.webnovel/observability/data_agent_timing.jsonl`
   - 还会用到：
     - `index upsert-entity`
     - `index register-alias`
     - `index record-state-change`
     - `index upsert-relationship`
     - `state process-chapter`
     - `rag index-chapter`
     - `style extract`
     - `index accrue-interest`（条件）
9. Step 6：Git 备份
   - `git add .`
   - `git commit -m "Ch{chapter_num}: {title}"`

### Codex 现状偏差

1. 当前 `codex_cli.py` 仍把 `webnovel-write` 当成 `follow_skill`。
2. Step 1 / Step 2B / Step 4 / Step 5 没有 source-backed runner。
3. Step 3 虽有 `review_agents_runner.py`，但整个 write 流水线仍不是脚本编排。

### Codex 对齐目标

- 改成 `write workflow runner` 统一编排。
- 每个 Step 都由脚本记录 workflow step。
- 需要子代理的地方由 `codex exec` 子进程实现，不再由主对话“代演”。

## `webnovel-review` 上游拓扑

来源：`skills/webnovel-review/SKILL.md`

### 参数来源

- 命令参数：`chapter` 或 `start-end`
- `PROJECT_ROOT="$(python "${SCRIPTS_DIR}/webnovel.py" --project-root "${WORKSPACE_ROOT}" where)"`

### Step 拓扑

1. Step 0.5：工作流断点
   - `workflow start-task --command webnovel-review --chapter {end}`
2. Step 1：加载参考
   - 读取 skill references
   - `workflow start-step/complete-step`
3. Step 2：加载项目状态
   - `cat "$PROJECT_ROOT/.webnovel/state.json"`
4. Step 3：并行调用检查员
   - Core：
     - `consistency-checker`
     - `continuity-checker`
     - `ooc-checker`
     - `reader-pull-checker`
   - Full 追加：
     - `high-point-checker`
     - `pacing-checker`
   - 当前 Codex 侧实际 runner：`review_agents_runner.py`
5. Step 4：生成审查报告
   - 输出：`审查报告/第{start}-{end}章审查报告.md`
6. Step 5：保存审查指标
   - `webnovel.py index save-review-metrics --data '@review_metrics.json'`
7. Step 6：写回审查记录
   - `webnovel.py update-state -- --add-review "{start}-{end}" "审查报告/第{start}-{end}章审查报告.md"`
8. Step 7：处理 critical
   - 若存在 critical，必须 AskUserQuestion
9. Step 8：收尾
   - `workflow start-step/complete-step`
   - `workflow complete-task`

### Codex 对齐目标

- 由脚本统一执行 Step 0.5 -> Step 8。
- `review_agents_runner.py` 只负责 Step 3/4/5 的主体产出。
- `update-state`、critical 检查、workflow state 由外层 runner 接管。

## `webnovel-dashboard` 上游拓扑

来源：`skills/webnovel-dashboard/SKILL.md`

### Step 拓扑

1. Step 0：环境确认
2. Step 1：首次依赖安装
3. Step 2：解析项目根并准备 `PYTHONPATH`
   - `webnovel.py where`
4. Step 3：启动 `python -m dashboard.server`

### Codex 对齐策略

- 保持脚本化启动。
- 端口由 Codex 版独立维护。

## `webnovel-query` 上游拓扑

来源：`skills/webnovel-query/SKILL.md`

### Step 拓扑

1. 识别查询类型
2. 加载对应参考
3. 加载项目数据
4. 确认上下文充足
5. 执行查询
   - `webnovel.py status -- --focus urgency`
   - `webnovel.py status -- --focus strand`
   - 以及静态文件读取
6. 格式化输出

## `webnovel-resume` 上游拓扑

来源：`skills/webnovel-resume/SKILL.md`

### Step 拓扑

1. 加载恢复协议
2. 加载数据规范
3. 确认上下文
4. 检测中断
   - `webnovel.py workflow detect`
5. 展示恢复选项
6. 执行恢复
   - `webnovel.py workflow cleanup --chapter {N} --confirm`
   - `webnovel.py workflow clear`
   - 或 `git reset --hard ch{N-1:04d}` + `workflow clear`
7. 继续任务（可选）

## Codex 实施顺序

1. 先冻结这份拓扑，作为所有适配变更的依据。
2. 第一批 source-backed：
   - `webnovel-review`
   - `webnovel-write`
3. 第二批 source-backed：
   - `webnovel-query`
   - `webnovel-resume`
4. `webnovel-init` 继续保留外部 TUI，但字段/参数与上游技能严格同构。
