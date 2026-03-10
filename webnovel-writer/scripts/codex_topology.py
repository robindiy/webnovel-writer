#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Machine-readable topology registry for Codex parity with upstream webnovel-writer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
UPSTREAM_SKILLS_ROOT = REPO_ROOT / "skills"


@dataclass(frozen=True)
class StepSpec:
    id: str
    name: str
    kind: str
    entrypoints: tuple[str, ...] = ()
    task_agents: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandTopology:
    command: str
    source_skill: Path
    execution_model: str
    parameter_sources: tuple[str, ...]
    step_specs: tuple[StepSpec, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "source_skill": str(self.source_skill),
            "execution_model": self.execution_model,
            "parameter_sources": list(self.parameter_sources),
            "steps": [
                {
                    "id": step.id,
                    "name": step.name,
                    "kind": step.kind,
                    "entrypoints": list(step.entrypoints),
                    "task_agents": list(step.task_agents),
                }
                for step in self.step_specs
            ],
        }


COMMAND_TOPOLOGY: Dict[str, CommandTopology] = {
    "webnovel-init": CommandTopology(
        command="webnovel-init",
        source_skill=UPSTREAM_SKILLS_ROOT / "webnovel-init" / "SKILL.md",
        execution_model="external_tui_same_schema",
        parameter_sources=("workspace_root", "interactive_fields", "genre_templates"),
        step_specs=(
            StepSpec("Step 0", "预检与上下文加载", "guard", ("webnovel.py where",)),
            StepSpec("Step 1", "故事核与商业定位", "interactive"),
            StepSpec("Step 2", "角色骨架与关系冲突", "interactive"),
            StepSpec("Step 3", "金手指与兑现机制", "interactive"),
            StepSpec("Step 4", "世界观与力量规则", "interactive"),
            StepSpec("Step 5", "创意约束包", "interactive"),
            StepSpec("Step 6", "一致性复述与最终确认", "interactive"),
            StepSpec("Generate", "项目生成", "script", ("webnovel.py init", "init_project.py")),
        ),
    ),
    "webnovel-plan": CommandTopology(
        command="webnovel-plan",
        source_skill=UPSTREAM_SKILLS_ROOT / "webnovel-plan" / "SKILL.md",
        execution_model="skill_topology_frozen",
        parameter_sources=("workspace_root", "volume_range"),
        step_specs=(
            StepSpec("Step 1", "Load project data", "read"),
            StepSpec("Step 2", "Build setting baseline", "read"),
            StepSpec("Step 3", "Select volume", "logic"),
            StepSpec("Step 4", "Generate volume beat sheet", "write"),
            StepSpec("Step 4.5", "Generate volume timeline", "write"),
            StepSpec("Step 5", "Generate volume skeleton", "write"),
            StepSpec("Step 6", "Generate chapter outlines", "write"),
            StepSpec("Step 7", "Enrich setting files", "write"),
            StepSpec("Step 8", "Validate and save", "script", ("webnovel.py update-state",)),
        ),
    ),
    "webnovel-write": CommandTopology(
        command="webnovel-write",
        source_skill=UPSTREAM_SKILLS_ROOT / "webnovel-write" / "SKILL.md",
        execution_model="source_workflow_runner",
        parameter_sources=("workspace_root", "chapter_num", "state.json", "outline", "index.db"),
        step_specs=(
            StepSpec("Step 0", "预检与最小加载", "guard", ("webnovel.py where", "extract_chapter_context.py")),
            StepSpec("Step 0.5", "工作流断点记录", "script", ("webnovel.py workflow start-task", "webnovel.py workflow start-step")),
            StepSpec(
                "Step 1",
                "Context Agent",
                "task",
                (
                    "webnovel.py context -- --chapter {NNNN}",
                    "webnovel.py extract-context --chapter {NNNN} --format json",
                    "webnovel.py index get-recent-reading-power --limit 5",
                    "webnovel.py index get-pattern-usage-stats --last-n 20",
                    "webnovel.py index get-hook-type-stats --last-n 20",
                    "webnovel.py index get-debt-summary",
                    "webnovel.py index get-core-entities",
                    "webnovel.py index recent-appearances --limit 20",
                ),
                ("context-agent",),
            ),
            StepSpec("Step 2A", "正文起草", "task", task_agents=("writer-draft",)),
            StepSpec("Step 2B", "风格适配", "task", task_agents=("style-adapter",)),
            StepSpec(
                "Step 3",
                "审查",
                "script",
                ("review_agents_runner.py", "webnovel.py index save-review-metrics"),
                ("consistency-checker", "continuity-checker", "ooc-checker", "reader-pull-checker", "high-point-checker", "pacing-checker"),
            ),
            StepSpec("Step 4", "润色", "task", task_agents=("polish-agent",)),
            StepSpec(
                "Step 5",
                "Data Agent",
                "task",
                (
                    "webnovel.py state process-chapter",
                    "webnovel.py rag index-chapter",
                    "webnovel.py style extract",
                    "webnovel.py index accrue-interest",
                ),
                ("data-agent",),
            ),
            StepSpec("Step 6", "Git 备份", "script", ("git add .", 'git commit -m "Ch{chapter_num}: {title}"')),
        ),
    ),
    "webnovel-review": CommandTopology(
        command="webnovel-review",
        source_skill=UPSTREAM_SKILLS_ROOT / "webnovel-review" / "SKILL.md",
        execution_model="source_workflow_runner",
        parameter_sources=("workspace_root", "chapter_range", "state.json", "chapter_files"),
        step_specs=(
            StepSpec("Step 0.5", "工作流断点", "script", ("webnovel.py workflow start-task",)),
            StepSpec("Step 1", "加载参考", "script", ("webnovel.py workflow start-step", "webnovel.py workflow complete-step")),
            StepSpec("Step 2", "加载项目状态", "read", ("cat .webnovel/state.json",)),
            StepSpec(
                "Step 3",
                "并行调用检查员",
                "script",
                ("review_agents_runner.py",),
                ("consistency-checker", "continuity-checker", "ooc-checker", "reader-pull-checker", "high-point-checker", "pacing-checker"),
            ),
            StepSpec("Step 4", "生成审查报告", "script"),
            StepSpec("Step 5", "保存审查指标", "script", ("webnovel.py index save-review-metrics",)),
            StepSpec("Step 6", "写回审查记录", "script", ("webnovel.py update-state -- --add-review",)),
            StepSpec("Step 7", "处理 critical", "interactive"),
            StepSpec("Step 8", "收尾", "script", ("webnovel.py workflow complete-task",)),
        ),
    ),
    "webnovel-dashboard": CommandTopology(
        command="webnovel-dashboard",
        source_skill=UPSTREAM_SKILLS_ROOT / "webnovel-dashboard" / "SKILL.md",
        execution_model="script_launcher",
        parameter_sources=("workspace_root", "project_root", "python_env"),
        step_specs=(
            StepSpec("Step 0", "环境确认", "guard"),
            StepSpec("Step 1", "安装依赖", "script"),
            StepSpec("Step 2", "解析项目根与 PYTHONPATH", "script", ("webnovel.py where",)),
            StepSpec("Step 3", "启动服务", "script", ("python -m dashboard.server",)),
        ),
    ),
    "webnovel-query": CommandTopology(
        command="webnovel-query",
        source_skill=UPSTREAM_SKILLS_ROOT / "webnovel-query" / "SKILL.md",
        execution_model="skill_topology_frozen",
        parameter_sources=("workspace_root", "query_text", "state.json", "setting_files"),
        step_specs=(
            StepSpec("Step 1", "识别查询类型", "logic"),
            StepSpec("Step 2", "加载对应参考", "read"),
            StepSpec("Step 3", "加载项目数据", "read"),
            StepSpec("Step 4", "确认上下文充足", "logic"),
            StepSpec("Step 5", "执行查询", "script", ("webnovel.py status -- --focus urgency", "webnovel.py status -- --focus strand")),
            StepSpec("Step 6", "格式化输出", "logic"),
        ),
    ),
    "webnovel-resume": CommandTopology(
        command="webnovel-resume",
        source_skill=UPSTREAM_SKILLS_ROOT / "webnovel-resume" / "SKILL.md",
        execution_model="skill_topology_frozen",
        parameter_sources=("workspace_root", "workflow_state"),
        step_specs=(
            StepSpec("Step 1", "加载恢复协议", "read"),
            StepSpec("Step 2", "加载数据规范", "read"),
            StepSpec("Step 3", "确认上下文", "logic"),
            StepSpec("Step 4", "检测中断", "script", ("webnovel.py workflow detect",)),
            StepSpec("Step 5", "展示恢复选项", "interactive"),
            StepSpec("Step 6", "执行恢复", "script", ("webnovel.py workflow cleanup --chapter {N} --confirm", "webnovel.py workflow clear")),
            StepSpec("Step 7", "继续任务", "logic"),
        ),
    ),
}


def get_topology(command_name: str) -> CommandTopology | None:
    return COMMAND_TOPOLOGY.get(str(command_name or "").strip())


def list_topology_dicts() -> List[Dict[str, Any]]:
    return [item.to_dict() for item in COMMAND_TOPOLOGY.values()]
