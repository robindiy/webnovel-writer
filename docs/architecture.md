# 系统架构与模块设计

## 核心理念

### 防幻觉三定律

| 定律 | 说明 | 执行方式 |
|------|------|---------|
| **大纲即法律** | 遵循大纲，不擅自发挥 | Context Agent 强制加载章节大纲 |
| **设定即物理** | 遵守设定，不自相矛盾 | Consistency Checker 实时校验 |
| **发明需识别** | 新实体必须入库管理 | Data Agent 自动提取并消歧 |

### Strand Weave 节奏系统

| Strand | 含义 | 理想占比 | 说明 |
|--------|------|---------|------|
| **Quest** | 主线剧情 | 60% | 推动核心冲突 |
| **Fire** | 感情线 | 20% | 人物关系发展 |
| **Constellation** | 世界观扩展 | 20% | 背景/势力/设定 |

节奏红线：

- Quest 连续不超过 5 章
- Fire 断档不超过 10 章
- Constellation 断档不超过 15 章

## 总体架构图

```text
┌─────────────────────────────────────────────────────────────┐
│            Claude Code / Codex Desktop / Shell             │
├─────────────────────────────────────────────────────────────┤
│  Slash Commands + Codex Adapter Registry                   │
├─────────────────────────────────────────────────────────────┤
│  Skills (init / plan / write / review / query / resume)    │
├─────────────────────────────────────────────────────────────┤
│  Agents (Context / Data / 多维 Checker)                    │
├─────────────────────────────────────────────────────────────┤
│  Data Layer: state.json / index.db / vectors.db            │
└─────────────────────────────────────────────────────────────┘
```

## Codex 适配层

为兼容 Codex，本仓库新增三层：

- **Runtime Compatibility**
  - 统一解释器选择
  - Python 3.9+ 注解兼容
- **Command Registry**
  - 单一来源维护 `/webnovel-writer:*` 与 shell fallback 的映射
- **Codex Adapter CLI**
  - 解析 slash 命令
  - 给 Codex 返回结构化选项
  - 启动 Dashboard
  - 把命令路由回原有 skill 文档与 Python 核心

对应实现文件：

- `webnovel-writer/scripts/runtime_compat.py`
- `webnovel-writer/scripts/codex_command_registry.py`
- `webnovel-writer/scripts/codex_cli.py`
- `webnovel-writer/scripts/codex_interaction.py`
- `codex-skills/webnovel-writer/SKILL.md`
- `scripts/install_codex_support.py`
- `scripts/restore_codex_support.py`
- `scripts/smoke_test_codex_support.py`

## 双 Agent 架构

### Context Agent（读）

职责：在写作前构建“创作任务书”，提供本章上下文、约束和追读力策略。

### Data Agent（写）

职责：从正文提取实体与状态变化，更新 `state.json`、`index.db`、`vectors.db`，保证数据链闭环。

## 六维并行审查

| Checker | 检查重点 |
|---------|---------|
| High-point Checker | 爽点密度与质量 |
| Consistency Checker | 设定一致性（战力/地点/时间线） |
| Pacing Checker | Strand 比例与断档 |
| OOC Checker | 人物行为是否偏离人设 |
| Continuity Checker | 场景与叙事连贯性 |
| Reader-pull Checker | 钩子强度、期待管理、追读力 |
