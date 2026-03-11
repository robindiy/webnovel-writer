#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex source-backed write workflow aligned to upstream webnovel-write topology."""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from chapter_paths import default_chapter_draft_path, find_chapter_file
from project_locator import resolve_project_root
from review_agents_runner import build_codex_exec_command, resolve_codex_executable
from runtime_compat import enable_windows_utf8_stdio


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
WEBNOVEL_CLI = SCRIPTS_DIR / "data_modules" / "webnovel.py"
REVIEW_RUNNER = SCRIPTS_DIR / "review_agents_runner.py"
WRITE_ARTIFACTS_ROOT_REL = Path(".webnovel") / "write_workflow"
OBSERVABILITY_WRITE_REL = Path(".webnovel") / "observability" / "codex_write_workflow.jsonl"
OBSERVABILITY_DATA_REL = Path(".webnovel") / "observability" / "data_agent_timing.jsonl"
OBSERVABILITY_CONTEXT_REL = Path(".webnovel") / "observability" / "context_agent_metrics.jsonl"

CORE_CONSTRAINTS_PATH = REPO_ROOT / "references" / "shared" / "core-constraints.md"
CONTEXT_AGENT_PATH = REPO_ROOT / "agents" / "context-agent.md"
DATA_AGENT_PATH = REPO_ROOT / "agents" / "data-agent.md"
WRITE_SKILL_PATH = REPO_ROOT / "skills" / "webnovel-write" / "SKILL.md"
CONTRACT_V2_PATH = REPO_ROOT / "skills" / "webnovel-write" / "references" / "step-1.5-contract.md"
STYLE_ADAPTER_PATH = REPO_ROOT / "skills" / "webnovel-write" / "references" / "style-adapter.md"
POLISH_GUIDE_PATH = REPO_ROOT / "skills" / "webnovel-write" / "references" / "polish-guide.md"
TYPESETTING_PATH = REPO_ROOT / "skills" / "webnovel-write" / "references" / "writing" / "typesetting.md"

DEFAULT_STAGE_TIMEOUT_SECONDS = int(os.environ.get("WEBNOVEL_WRITE_STAGE_TIMEOUT_SECONDS", "600") or "600")
DEFAULT_STAGE_RETRIES = int(os.environ.get("WEBNOVEL_WRITE_STAGE_RETRIES", "4") or "4")
DEFAULT_STAGE_RETRY_BACKOFF_SECONDS = float(os.environ.get("WEBNOVEL_WRITE_STAGE_RETRY_BACKOFF_SECONDS", "3") or "3")
DEFAULT_STAGE_RECONNECT_RETRY_THRESHOLD = int(os.environ.get("WEBNOVEL_STAGE_RECONNECT_RETRY_THRESHOLD", "3") or "3")
DEFAULT_CONTEXT_STAGE_TIMEOUT_SECONDS = int(
    os.environ.get("WEBNOVEL_CONTEXT_STAGE_TIMEOUT_SECONDS", str(DEFAULT_STAGE_TIMEOUT_SECONDS))
    or str(DEFAULT_STAGE_TIMEOUT_SECONDS)
)
DEFAULT_CONTEXT_STAGE_RETRIES = int(
    os.environ.get("WEBNOVEL_CONTEXT_STAGE_RETRIES", str(DEFAULT_STAGE_RETRIES))
    or str(DEFAULT_STAGE_RETRIES)
)
ENABLE_CONTEXT_DRAFT_COMPACT_RETRY = str(
    os.environ.get("WEBNOVEL_CONTEXT_DRAFT_COMPACT_RETRY", "1") or "1"
).strip().lower() in {"1", "true", "yes", "on"}
USE_MAIN_PROCESS_CONTEXT_DRAFT_PACKAGE = str(
    os.environ.get("WEBNOVEL_CONTEXT_DRAFT_MAIN_PROCESS", "1") or "1"
).strip().lower() in {"1", "true", "yes", "on"}
DISABLE_CONTEXT_COMPRESSION = str(
    os.environ.get("WEBNOVEL_DISABLE_CONTEXT_COMPRESSION", "0") or "0"
).strip().lower() in {"1", "true", "yes", "on"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _emit_tui_line(message: str) -> None:
    text = str(message or "").strip()
    if not text:
        return
    print(text, file=sys.stderr, flush=True)


def _emit_step_banner(step_id: str, step_name: str, *, status: str) -> None:
    mapping = {
        "start": "▶",
        "done": "✅",
        "skip": "⏭",
    }
    prefix = mapping.get(status, "•")
    suffix = {
        "start": f"开始: {step_name}",
        "done": f"完成: {step_name}",
        "skip": f"跳过: {step_name}",
    }.get(status, step_name)
    _emit_tui_line(f"{prefix} {step_id} {suffix}")


def _run_command(command: Sequence[str], *, timeout: Optional[int] = None, cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )


def _run_webnovel(project_root: Path, *args: str, timeout: Optional[int] = None) -> subprocess.CompletedProcess[str]:
    return _run_command([sys.executable, str(WEBNOVEL_CLI), "--project-root", str(project_root), *args], timeout=timeout)


def _run_webnovel_json(project_root: Path, *args: str, timeout: Optional[int] = None) -> Dict[str, Any]:
    proc = _run_webnovel(project_root, *args, timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"命令执行失败: {' '.join(args)}")
    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"命令未返回合法 JSON: {' '.join(args)}\n{proc.stdout}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"命令未返回 JSON 对象: {' '.join(args)}")
    if payload.get("status") == "error":
        error = payload.get("error") or {}
        raise RuntimeError(str(error.get("message") or payload))
    return payload


def _workflow(project_root: Path, *args: str) -> None:
    proc = _run_webnovel(project_root, "workflow", *args)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"workflow 命令失败: {detail}")


def start_task(project_root: Path, chapter: int) -> None:
    _workflow(project_root, "start-task", "--command", "webnovel-write", "--chapter", str(chapter))


def start_step(project_root: Path, step_id: str, step_name: str, note: Optional[str] = None) -> None:
    args = ["start-step", "--step-id", step_id, "--step-name", step_name]
    if note:
        args.extend(["--note", note])
    _workflow(project_root, *args)


def update_step(project_root: Path, step_id: str, note: Optional[str] = None, status_detail: Optional[str] = None) -> None:
    args = ["update-step", "--step-id", step_id]
    if note is not None:
        args.extend(["--note", note])
    if status_detail is not None:
        args.extend(["--status-detail", status_detail])
    _workflow(project_root, *args)


def complete_step(project_root: Path, step_id: str, artifacts: Optional[Dict[str, Any]] = None) -> None:
    payload = json.dumps(artifacts or {"ok": True}, ensure_ascii=False)
    _workflow(project_root, "complete-step", "--step-id", step_id, "--artifacts", payload)


def complete_task(project_root: Path, artifacts: Optional[Dict[str, Any]] = None) -> None:
    payload = json.dumps(artifacts or {"ok": True}, ensure_ascii=False)
    _workflow(project_root, "complete-task", "--artifacts", payload)


def fail_task(project_root: Path, reason: str, artifacts: Optional[Dict[str, Any]] = None) -> None:
    args = ["fail-task", "--reason", str(reason or "unknown error")]
    if artifacts is not None:
        args.extend(["--artifacts", json.dumps(artifacts, ensure_ascii=False)])
    _workflow(project_root, *args)


def observe_write(project_root: Path, stage: str, *, success: bool, elapsed_ms: int, details: Optional[Dict[str, Any]] = None) -> None:
    append_jsonl(
        project_root / OBSERVABILITY_WRITE_REL,
        {
            "timestamp": now_iso(),
            "stage": stage,
            "success": success,
            "elapsed_ms": elapsed_ms,
            "details": details or {},
        },
    )


def observe_data_agent(project_root: Path, chapter: int, timing_ms: Dict[str, int], success: bool, warnings: List[str]) -> None:
    total_ms = int(timing_ms.get("TOTAL", 0))
    top3 = sorted(((k, v) for k, v in timing_ms.items() if k != "TOTAL"), key=lambda item: item[1], reverse=True)[:3]
    append_jsonl(
        project_root / OBSERVABILITY_DATA_REL,
        {
            "timestamp": now_iso(),
            "tool_name": "codex_write_workflow:data-agent",
            "chapter": chapter,
            "success": success,
            "elapsed_ms": total_ms,
            "timing_ms": timing_ms,
            "bottlenecks_top3": [{"stage": name, "elapsed_ms": value} for name, value in top3],
            "warnings": warnings,
        },
    )


def chapter_artifact_dir(project_root: Path, chapter: int) -> Path:
    return ensure_dir(project_root / WRITE_ARTIFACTS_ROOT_REL / f"ch{chapter:04d}")


def _read_optional(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _load_state(project_root: Path) -> Dict[str, Any]:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"缺少状态文件: {state_path}")
    return json.loads(state_path.read_text(encoding="utf-8"))


def _extract_volume_id_from_state(state: Dict[str, Any], chapter: int) -> int:
    progress = state.get("progress") or {}
    for item in progress.get("volumes_planned") or []:
        if not isinstance(item, dict):
            continue
        raw_range = str(item.get("chapters_range") or "")
        match = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", raw_range)
        if not match:
            continue
        start = int(match.group(1))
        end = int(match.group(2))
        if start <= chapter <= end:
            volume = item.get("volume")
            if isinstance(volume, int) and volume > 0:
                return volume
    return ((chapter - 1) // 50) + 1


def _load_volume_timeline(project_root: Path, chapter: int, state: Dict[str, Any]) -> str:
    volume = _extract_volume_id_from_state(state, chapter)
    path = project_root / "大纲" / f"第{volume}卷-时间线.md"
    return _read_optional(path)


def _strip_cli_wrapper(payload: Dict[str, Any]) -> Any:
    if payload.get("status") != "success":
        return payload
    return payload.get("data")


def _parse_cli_json_payload(text: str) -> Dict[str, Any]:
    payload = json.loads(text.strip() or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("CLI 返回不是 JSON 对象")
    if payload.get("status") == "error":
        error = payload.get("error") or {}
        raise RuntimeError(str(error.get("message") or payload))
    return payload


def _build_stage_schema_context() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["chapter", "task_brief", "contract_v2", "draft_package"],
        "properties": {
            "chapter": {"type": "integer"},
            "task_brief": {
                "type": "object",
                "required": [
                    "core_task",
                    "conflict",
                    "carry_from_previous",
                    "characters",
                    "scene_constraints",
                    "foreshadowing",
                    "foreshadowing_plan",
                    "reading_power",
                ],
                "properties": {
                    "core_task": {"type": "string"},
                    "conflict": {"type": "string"},
                    "must_complete": {"type": "array", "items": {"type": "string"}},
                    "must_not": {"type": "array", "items": {"type": "string"}},
                    "villain_tier": {"type": "string"},
                    "carry_from_previous": {"type": "string"},
                    "opening_suggestion": {"type": "string"},
                    "characters": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "scene_constraints": {"type": "array", "items": {"type": "string"}},
                    "time_constraints": {"type": "array", "items": {"type": "string"}},
                    "style_guidance": {"type": "array", "items": {"type": "string"}},
                    "foreshadowing": {"type": "array", "items": {"type": "string"}},
                    "foreshadowing_plan": {
                        "type": "object",
                        "required": ["must_continue", "planned_new", "forbidden_resolve"],
                        "properties": {
                            "must_continue": {
                                "type": "array",
                                "items": {"type": "object", "additionalProperties": True, "required": ["id", "content", "purpose"]}
                            },
                            "planned_new": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "required": ["content", "plant_method", "purpose", "expected_payoff"],
                                    "properties": {
                                        "content": {"type": "string"},
                                        "plant_method": {"type": "string"},
                                        "purpose": {"type": "string"},
                                        "expected_payoff": {"type": "string"},
                                        "tier": {"type": "string"},
                                    },
                                },
                            },
                            "forbidden_resolve": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "reading_power": {"type": "array", "items": {"type": "string"}},
                    "strand_strategy": {"type": "string"},
                },
            },
            "contract_v2": {
                "type": "object",
                "required": [
                    "goal",
                    "obstacle",
                    "cost",
                    "change",
                    "unresolved_question",
                    "core_conflict",
                    "opening_type",
                    "emotion_pacing",
                    "info_density",
                    "is_transition",
                    "hook_type",
                    "hook_strength",
                    "micropayoffs",
                ],
                "properties": {
                    "goal": {"type": "string"},
                    "obstacle": {"type": "string"},
                    "cost": {"type": "string"},
                    "change": {"type": "string"},
                    "unresolved_question": {"type": "string"},
                    "core_conflict": {"type": "string"},
                    "opening_type": {"type": "string"},
                    "emotion_pacing": {"type": "string"},
                    "info_density": {"type": "string"},
                    "is_transition": {"type": "boolean"},
                    "hook_type": {"type": "string"},
                    "hook_strength": {"type": "string"},
                    "micropayoffs": {"type": "array", "items": {"type": "string"}},
                    "cool_point_pattern": {"type": "string"},
                },
            },
            "draft_package": {
                "type": "object",
                "required": ["title_suggestion", "beat_sheet", "immutable_facts", "forbidden", "checklist", "target_words"],
                "properties": {
                    "title_suggestion": {"type": "string"},
                    "beat_sheet": {"type": "array", "items": {"type": "string"}},
                    "immutable_facts": {"type": "array", "items": {"type": "string"}},
                    "forbidden": {"type": "array", "items": {"type": "string"}},
                    "checklist": {"type": "array", "items": {"type": "string"}},
                    "target_words": {"type": "integer", "minimum": 1200},
                },
            },
        },
    }


def _build_stage_schema_context_story_spine() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["chapter", "story_spine"],
        "properties": {
            "chapter": {"type": "integer"},
            "story_spine": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "core_task",
                    "conflict",
                    "carry_from_previous",
                    "must_complete",
                    "must_not",
                    "opening_suggestion",
                ],
                "properties": {
                    "core_task": {"type": "string"},
                    "conflict": {"type": "string"},
                    "must_complete": {"type": "array", "items": {"type": "string"}},
                    "must_not": {"type": "array", "items": {"type": "string"}},
                    "carry_from_previous": {"type": "string"},
                    "opening_suggestion": {"type": "string"},
                },
            },
        },
    }


def _build_stage_schema_context_cast_constraints() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["chapter", "cast_constraints"],
        "properties": {
            "chapter": {"type": "integer"},
            "cast_constraints": {
                "type": "object",
                "additionalProperties": False,
                "required": ["characters", "scene_constraints", "time_constraints", "style_guidance"],
                "properties": {
                    "characters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "role"],
                            "properties": {
                                "name": {"type": "string"},
                                "role": {"type": "string"},
                            },
                        },
                    },
                    "scene_constraints": {"type": "array", "items": {"type": "string"}},
                    "time_constraints": {"type": "array", "items": {"type": "string"}},
                    "style_guidance": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }


def _build_stage_schema_context_foreshadow_plan() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["chapter", "foreshadow_plan"],
        "properties": {
            "chapter": {"type": "integer"},
            "foreshadow_plan": {
                "type": "object",
                "additionalProperties": False,
                "required": ["foreshadowing", "foreshadowing_plan"],
                "properties": {
                    "foreshadowing": {"type": "array", "items": {"type": "string"}},
                    "foreshadowing_plan": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["must_continue", "planned_new", "forbidden_resolve"],
                        "properties": {
                            "must_continue": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["id", "content", "purpose"],
                                    "properties": {
                                        "id": {"type": "string"},
                                        "content": {"type": "string"},
                                        "purpose": {"type": "string"},
                                    },
                                },
                            },
                            "planned_new": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["content", "plant_method", "purpose", "expected_payoff"],
                                    "properties": {
                                        "content": {"type": "string"},
                                        "plant_method": {"type": "string"},
                                        "purpose": {"type": "string"},
                                        "expected_payoff": {"type": "string"},
                                    },
                                },
                            },
                            "forbidden_resolve": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
        },
    }


def _build_stage_schema_context_reader_pull() -> Dict[str, Any]:
    base = _build_stage_schema_context()
    task_props = base["properties"]["task_brief"]["properties"]
    contract_props = base["properties"]["contract_v2"]["properties"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["chapter", "reader_pull"],
        "properties": {
            "chapter": {"type": "integer"},
            "reader_pull": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "reading_power",
                    "strand_strategy",
                    "is_transition",
                    "hook_type",
                    "hook_strength",
                    "micropayoffs",
                    "cool_point_pattern",
                ],
                "properties": {
                    "reading_power": task_props["reading_power"],
                    "strand_strategy": task_props["strand_strategy"],
                    "is_transition": contract_props["is_transition"],
                    "hook_type": contract_props["hook_type"],
                    "hook_strength": contract_props["hook_strength"],
                    "micropayoffs": contract_props["micropayoffs"],
                    "cool_point_pattern": contract_props["cool_point_pattern"],
                },
            },
        },
    }


def _build_stage_schema_context_contract_core() -> Dict[str, Any]:
    base = _build_stage_schema_context()["properties"]["contract_v2"]["properties"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["chapter", "contract_core"],
        "properties": {
            "chapter": {"type": "integer"},
            "contract_core": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "goal",
                    "obstacle",
                    "cost",
                    "change",
                    "unresolved_question",
                    "core_conflict",
                    "opening_type",
                    "emotion_pacing",
                    "info_density",
                ],
                "properties": {
                    "goal": base["goal"],
                    "obstacle": base["obstacle"],
                    "cost": base["cost"],
                    "change": base["change"],
                    "unresolved_question": base["unresolved_question"],
                    "core_conflict": base["core_conflict"],
                    "opening_type": base["opening_type"],
                    "emotion_pacing": base["emotion_pacing"],
                    "info_density": base["info_density"],
                },
            },
        },
    }


def _build_stage_schema_context_draft_package() -> Dict[str, Any]:
    base = _build_stage_schema_context()["properties"]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["chapter", "draft_package"],
        "properties": {
            "chapter": base["chapter"],
            "draft_package": base["draft_package"],
        },
    }


def _build_stage_schema_context_draft_package_wire() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["chapter", "draft_package"],
        "properties": {
            "chapter": {"type": "integer"},
            "draft_package": {"type": "object", "additionalProperties": True},
        },
    }


def _assert_payload_matches_schema(value: Any, schema: Dict[str, Any], *, path: str = "$") -> None:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            raise RuntimeError(f"{path} 应为 object，实际是 {type(value).__name__}")
        for key in schema.get("required") or []:
            if key not in value:
                raise RuntimeError(f"{path} 缺少必填字段: {key}")
        properties = schema.get("properties") or {}
        for key, subschema in properties.items():
            if key in value and isinstance(subschema, dict):
                _assert_payload_matches_schema(value[key], subschema, path=f"{path}.{key}")
        return
    if schema_type == "array":
        if not isinstance(value, list):
            raise RuntimeError(f"{path} 应为 array，实际是 {type(value).__name__}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _assert_payload_matches_schema(item, item_schema, path=f"{path}[{index}]")
        return
    if schema_type == "string":
        if not isinstance(value, str):
            raise RuntimeError(f"{path} 应为 string，实际是 {type(value).__name__}")
        return
    if schema_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError(f"{path} 应为 integer，实际是 {type(value).__name__}")
        minimum = schema.get("minimum")
        if minimum is not None and value < int(minimum):
            raise RuntimeError(f"{path} 应 >= {minimum}，实际是 {value}")
        return
    if schema_type == "boolean":
        if not isinstance(value, bool):
            raise RuntimeError(f"{path} 应为 boolean，实际是 {type(value).__name__}")
        return


def _build_stage_schema_draft() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["title", "content"],
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
        },
    }


def _build_revision_pass_report_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["pass_id", "focus", "full_reread", "applied_changes"],
        "properties": {
            "pass_id": {"type": "string"},
            "focus": {"type": "string"},
            "full_reread": {"type": "boolean"},
            "applied_changes": {"type": "array", "items": {"type": "string"}},
            "remaining_risks": {"type": "array", "items": {"type": "string"}},
            "checks": {"type": "array", "items": {"type": "string"}},
        },
    }


def _build_stage_schema_style() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["content", "change_summary", "pass_reports", "full_reread_count"],
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "change_summary": {"type": "array", "items": {"type": "string"}},
            "pass_reports": {"type": "array", "minItems": 2, "items": _build_revision_pass_report_schema()},
            "full_reread_count": {"type": "integer", "minimum": 1},
            "retained": {"type": "array", "items": {"type": "string"}},
        },
    }


def _build_stage_schema_polish() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": [
            "content",
            "change_summary",
            "anti_ai_force_check",
            "deviation",
            "pass_reports",
            "full_reread_count",
        ],
        "properties": {
            "content": {"type": "string"},
            "change_summary": {"type": "array", "items": {"type": "string"}},
            "anti_ai_force_check": {"type": "string", "enum": ["pass", "fail"]},
            "deviation": {"type": "array", "items": {"type": "string"}},
            "pass_reports": {"type": "array", "minItems": 3, "items": _build_revision_pass_report_schema()},
            "full_reread_count": {"type": "integer", "minimum": 2},
            "retained": {"type": "array", "items": {"type": "string"}},
        },
    }


def _build_stage_schema_data() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": [
            "entities_appeared",
            "entities_new",
            "state_changes",
            "relationships_new",
            "scenes_chunked",
            "uncertain",
            "warnings",
            "chapter_meta",
            "summary_text",
            "foreshadowing_notes",
            "foreshadowing_planted",
            "foreshadowing_continued",
            "foreshadowing_resolved",
            "bridge_line",
            "scenes",
        ],
        "properties": {
            "entities_appeared": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["id", "type", "mentions", "confidence"],
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "mentions": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number"},
                    },
                },
            },
            "entities_new": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["suggested_id", "name", "type", "tier"],
                    "properties": {
                        "suggested_id": {"type": "string"},
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "tier": {"type": "string"},
                    },
                },
            },
            "state_changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["entity_id", "field", "new"],
                    "properties": {
                        "entity_id": {"type": "string"},
                        "field": {"type": "string"},
                        "old": {"type": ["string", "null"]},
                        "new": {"type": "string"},
                        "reason": {"type": ["string", "null"]},
                    },
                },
            },
            "relationships_new": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["from", "to", "type"],
                    "properties": {
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "type": {"type": "string"},
                        "description": {"type": ["string", "null"]},
                        "chapter": {"type": ["integer", "null"]},
                    },
                },
            },
            "scenes_chunked": {"type": "integer", "minimum": 0},
            "uncertain": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["mention", "candidates", "confidence"],
                    "properties": {
                        "mention": {"type": "string"},
                        "candidates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": True,
                                "required": ["type", "id"],
                                "properties": {
                                    "type": {"type": "string"},
                                    "id": {"type": "string"},
                                },
                            },
                        },
                        "confidence": {"type": "number"},
                        "adopted": {"type": ["string", "null"]},
                    },
                },
            },
            "warnings": {"type": "array", "items": {"type": "string"}},
            "chapter_meta": {"type": "object", "additionalProperties": True},
            "summary_text": {"type": "string"},
            "foreshadowing_notes": {"type": "array", "items": {"type": "string"}},
            "foreshadowing_planted": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "foreshadowing_continued": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "foreshadowing_resolved": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "bridge_line": {"type": "string"},
            "time_anchor": {"type": "string"},
            "location": {"type": "string"},
            "characters": {"type": "array", "items": {"type": "string"}},
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["index", "scene_index", "summary", "content"],
                    "properties": {
                        "index": {"type": "integer", "minimum": 1},
                        "scene_index": {"type": "integer", "minimum": 1},
                        "summary": {"type": "string"},
                        "content": {"type": "string"},
                        "location": {"type": "string"},
                        "characters": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }


def _is_retryable_provider_error(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        snippet in lowered
        for snippet in (
            "unexpected status 502",
            "stream disconnected",
            "bad gateway",
            "reconnecting...",
            "too many requests",
            "provider reconnect",
        )
    )


def _select_stage_error_text(stdout: str, stderr: str) -> str:
    stdout_text = str(stdout or "").strip()
    stderr_text = str(stderr or "").strip()
    combined = "\n".join(part for part in (stdout_text, stderr_text) if part)
    if _is_retryable_provider_error(combined):
        return combined
    if stdout_text:
        return stdout_text
    return stderr_text


def _parse_stream_payload(line: str) -> Dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _pump_stream(stream, sink: "queue.Queue[tuple[str, str | None]]", label: str) -> None:
    try:
        for line in iter(stream.readline, ""):
            sink.put((label, line))
    finally:
        sink.put((label, None))


def _terminate_process(proc: subprocess.Popen[str]) -> int:
    if proc.poll() is not None:
        return int(proc.returncode or 0)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    return int(proc.returncode or 0)


def _workflow_step_id_for_stage(stage_name: str) -> Optional[str]:
    return {
        "context_agent": "Step 1",
        "context_story_spine": "Step 1",
        "context_cast_constraints": "Step 1",
        "context_foreshadow_plan": "Step 1",
        "context_reader_pull": "Step 1",
        "context_contract_core": "Step 1",
        "context_draft_package": "Step 1",
        "draft": "Step 2A",
        "style_adapter": "Step 2B",
        "polish": "Step 4",
        "data_agent": "Step 5",
    }.get(stage_name)


def _stage_display_name(stage_name: str) -> str:
    return {
        "context_agent": "Context Agent",
        "context_story_spine": "Context Agent / Story Spine",
        "context_cast_constraints": "Context Agent / Cast Constraints",
        "context_foreshadow_plan": "Context Agent / Foreshadow Plan",
        "context_reader_pull": "Context Agent / Reader Pull",
        "context_contract_core": "Context Agent / Contract Core",
        "context_draft_package": "Context Agent / Draft Package",
        "draft": "正文起草",
        "style_adapter": "风格适配",
        "polish": "润色",
        "data_agent": "Data Agent",
    }.get(stage_name, stage_name)


def _trim_progress_note(text: str, limit: int = 180) -> str:
    value = str(text or "").strip().replace("\r", " ").replace("\n", " ")
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."

def _coerce_snippet(value: Any, *, limit: int = 140) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)
    return _trim_progress_note(text, limit=limit)


def _collect_path_hints(value: Any, sink: List[str]) -> None:
    if len(sink) >= 8:
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key or "").lower()
            if isinstance(nested, str) and lowered in {"file_path", "path", "target_file", "target_path", "chapter_file", "cwd", "workdir"}:
                sink.append(nested)
            elif lowered in {"input", "arguments", "args", "payload", "kwargs", "content"}:
                _collect_path_hints(nested, sink)
            if len(sink) >= 8:
                break
    elif isinstance(value, list):
        for nested in value[:6]:
            _collect_path_hints(nested, sink)
            if len(sink) >= 8:
                break


def _infer_trace_kind(name: str, item_type: str) -> str:
    lowered = f"{name} {item_type}".lower()
    if any(token in lowered for token in ("read", "open", "find", "grep", "search")):
        return "read"
    if any(token in lowered for token in ("write", "edit", "update", "patch", "replace")):
        return "write"
    if any(token in lowered for token in ("bash", "shell", "exec", "command", "terminal")):
        return "bash"
    if any(token in lowered for token in ("agent_message", "message", "assistant")):
        return "assistant_message"
    return "event"


def _extract_trace_entry(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    event_type = str(payload.get("type") or "").strip()

    item: Dict[str, Any] | None = payload.get("item") if isinstance(payload.get("item"), dict) else None
    if item is None:
        for key in ("delta", "output", "data", "payload"):
            container = payload.get(key)
            if not isinstance(container, dict):
                continue
            nested_item = container.get("item") if isinstance(container.get("item"), dict) else None
            if nested_item is not None:
                item = nested_item
                break
            if any(container.get(field) is not None for field in ("type", "name", "tool_name", "call_name", "title", "text", "message", "summary", "args", "path", "file_path")):
                item = container
                break
    if not item:
        return None

    item_type = str(item.get("type") or "").strip()
    name = str(item.get("name") or item.get("tool_name") or item.get("call_name") or item.get("title") or "").strip()
    path_hints: List[str] = []
    _collect_path_hints(item, path_hints)
    if not path_hints:
        _collect_path_hints(payload, path_hints)
    summary = _coerce_snippet(item.get("text") or item.get("message") or item.get("summary") or payload.get("message"))
    return {
        "event_type": event_type,
        "item_type": item_type,
        "name": name,
        "kind": _infer_trace_kind(name, item_type),
        "path_hints": path_hints[:5],
        "summary": summary,
    }


def _trace_note_from_entry(stage_name: str, entry: Dict[str, Any]) -> str:
    prefix = _stage_display_name(stage_name)
    kind = str(entry.get("kind") or "event")
    name = str(entry.get("name") or entry.get("item_type") or kind)
    target = ""
    path_hints = entry.get("path_hints") or []
    if isinstance(path_hints, list) and path_hints:
        target = f" -> {path_hints[0]}"
    summary = str(entry.get("summary") or "").strip()
    if kind == "assistant_message" and summary:
        return _trim_progress_note(f"{prefix} · {summary}")
    if summary:
        return _trim_progress_note(f"{prefix} · {name}{target} · {summary}")
    return _trim_progress_note(f"{prefix} · {entry.get('event_type') or kind} · {name}{target}")


def _path_hint_matches_workspace(path_hints: Sequence[str], workspace_file: Path, project_root: Path) -> bool:
    expected = {str(workspace_file), str(workspace_file.resolve())}
    try:
        expected.add(str(workspace_file.relative_to(project_root)))
    except ValueError:
        pass
    for raw in path_hints:
        candidate = str(raw or "").strip()
        if not candidate:
            continue
        for target in expected:
            if candidate == target or candidate.endswith(target) or target.endswith(candidate):
                return True
    return False


def _summarize_stage_trace(trace_entries: Sequence[Dict[str, Any]], *, workspace_file: Path | None, project_root: Path) -> Dict[str, Any]:
    tool_counts: Dict[str, int] = {"read": 0, "write": 0, "bash": 0, "assistant_message": 0, "event": 0}
    workspace_reads = 0
    workspace_writes = 0
    tools_seen: List[str] = []
    for entry in trace_entries:
        kind = str(entry.get("kind") or "event")
        tool_counts[kind] = tool_counts.get(kind, 0) + 1
        name = str(entry.get("name") or "").strip()
        if name and name not in tools_seen and len(tools_seen) < 8:
            tools_seen.append(name)
        if workspace_file is None:
            continue
        if _path_hint_matches_workspace(entry.get("path_hints") or [], workspace_file, project_root):
            if kind == "read":
                workspace_reads += 1
            elif kind == "write":
                workspace_writes += 1
    return {
        "tool_counts": tool_counts,
        "workspace_reads": workspace_reads,
        "workspace_writes": workspace_writes,
        "events_captured": len(trace_entries),
        "tools_seen": tools_seen,
    }


def _payload_declares_edits(stage_name: str, payload: Dict[str, Any]) -> bool:
    if stage_name == "draft":
        return True
    change_summary = payload.get("change_summary") or []
    if any(str(item).strip() for item in change_summary):
        return True
    for report in payload.get("pass_reports") or []:
        if not isinstance(report, dict):
            continue
        if any(str(item).strip() for item in (report.get("applied_changes") or [])):
            return True
    return False


def _compose_workspace_execution_report(
    *,
    stage_name: str,
    project_root: Path,
    chapter: int | None,
    workspace_file: Path | None,
    before_document: str | None,
    validated_payload: Dict[str, Any],
    trace_summary: Dict[str, Any],
    expected_title: str | None,
    require_mutation: bool,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "stage": stage_name,
        "chapter": chapter,
        "workspace_file": None,
        "trace_summary": trace_summary,
        "mutation_expected": require_mutation or _payload_declares_edits(stage_name, validated_payload),
    }
    if workspace_file is None:
        return report
    try:
        report["workspace_file"] = str(workspace_file.relative_to(project_root))
    except ValueError:
        report["workspace_file"] = str(workspace_file)
    if not workspace_file.exists():
        raise RuntimeError(f"{stage_name} 未生成章节文件: {workspace_file}")
    if chapter is None:
        raise RuntimeError(f"{stage_name} 缺少 chapter，无法校验章节文件")

    title = str(validated_payload.get("title") or expected_title or "").strip()
    if not title:
        raise RuntimeError(f"{stage_name} 缺少标题，无法校验章节文件")
    payload_content = str(validated_payload.get("content") or "")
    current_document = workspace_file.read_text(encoding="utf-8")
    expected_document = _compose_chapter_file(chapter, title, payload_content)
    normalized_current = current_document.replace("\r\n", "\n").strip()
    normalized_expected = expected_document.replace("\r\n", "\n").strip()
    content_matches_file = normalized_current == normalized_expected
    file_changed = (before_document or "").replace("\r\n", "\n").strip() != normalized_current
    report.update(
        {
            "title": title,
            "content_matches_file": content_matches_file,
            "file_changed": file_changed,
            "before_chars": len(before_document or ""),
            "after_chars": len(current_document),
            "content_chars": len(payload_content),
        }
    )
    if not content_matches_file:
        raise RuntimeError(f"{stage_name} 返回的 content/title 与章节文件最终内容不一致")
    if report["mutation_expected"] and not file_changed:
        raise RuntimeError(f"{stage_name} 声称完成了改文，但章节文件未发生变化")
    return report


def _stream_note_from_payload(stage_name: str, payload: Dict[str, Any]) -> str:
    event_type = str(payload.get("type") or "").strip()
    prefix = _stage_display_name(stage_name)
    trace_entry = _extract_trace_entry(payload)
    if trace_entry:
        return _trace_note_from_entry(stage_name, trace_entry)
    if event_type == "thread.started":
        return f"{prefix} · thread.started"
    if event_type == "turn.started":
        return f"{prefix} · turn.started"
    if event_type == "turn.completed":
        return f"{prefix} · turn.completed"
    if event_type == "turn.failed":
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        message = str(error.get("message") or payload.get("message") or "turn.failed").strip()
        return _trim_progress_note(f"{prefix} · {message}")
    if event_type == "error":
        return _trim_progress_note(f"{prefix} · {payload.get('message') or 'error'}")
    message = str(payload.get("message") or "").strip()
    if message:
        return _trim_progress_note(f"{prefix} · {message}")
    return _trim_progress_note(f"{prefix} · {event_type or 'event'}")

def observe_write_event(
    project_root: Path,
    stage: str,
    *,
    attempt: int,
    channel: str,
    event: str,
    message: str,
) -> None:
    append_jsonl(
        project_root / OBSERVABILITY_WRITE_REL,
        {
            "timestamp": now_iso(),
            "kind": "event",
            "stage": stage,
            "attempt": attempt,
            "channel": channel,
            "event": event,
            "message": _trim_progress_note(message, limit=240),
        },
    )


def run_codex_json_stage(
    *,
    stage_name: str,
    prompt: str,
    schema: Dict[str, Any],
    project_root: Path,
    artifact_dir: Path,
    codex_bin: Optional[str] = None,
    sandbox_mode: str = "read-only",
    timeout_seconds: int = DEFAULT_STAGE_TIMEOUT_SECONDS,
    retries: int = DEFAULT_STAGE_RETRIES,
    chapter: int | None = None,
    workspace_file: Path | None = None,
    expected_title: str | None = None,
    require_workspace_mutation: bool = False,
) -> Dict[str, Any]:
    output_path = artifact_dir / f"{stage_name}.json"
    schema_path = artifact_dir / f"{stage_name}.schema.json"
    stdout_log = artifact_dir / f"{stage_name}.stdout.log"
    stderr_log = artifact_dir / f"{stage_name}.stderr.log"
    prompt_path = artifact_dir / f"{stage_name}.prompt.txt"
    trace_path = artifact_dir / f"{stage_name}.trace.json"
    execution_path = artifact_dir / f"{stage_name}.execution.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    write_json(schema_path, schema)

    resolved_codex = resolve_codex_executable(codex_bin)
    command = build_codex_exec_command(
        codex_bin=resolved_codex,
        project_root=project_root,
        output_schema_path=schema_path,
        output_path=output_path,
        sandbox_mode=sandbox_mode,
    )
    step_id = _workflow_step_id_for_stage(stage_name)
    last_error = ""
    last_elapsed_ms = 0
    last_trace_summary: Dict[str, Any] = {}
    output_grace_seconds = 2.0

    def _display_path(path: Path) -> str:
        try:
            return str(path.relative_to(project_root))
        except ValueError:
            return str(path)

    before_document = workspace_file.read_text(encoding="utf-8") if workspace_file and workspace_file.exists() else None

    for attempt in range(1, retries + 2):
        started = time.perf_counter()
        attempt_stdout_path = artifact_dir / f"{stage_name}.attempt{attempt}.stdout.log"
        attempt_stderr_path = artifact_dir / f"{stage_name}.attempt{attempt}.stderr.log"
        for candidate in (output_path, trace_path, execution_path):
            try:
                candidate.unlink(missing_ok=True)
            except Exception:
                pass
        stdout_log.write_text("", encoding="utf-8")
        stderr_log.write_text("", encoding="utf-8")
        attempt_stdout_path.write_text("", encoding="utf-8")
        attempt_stderr_path.write_text("", encoding="utf-8")
        if step_id:
            try:
                update_step(project_root, step_id, note=f"{_stage_display_name(stage_name)} · attempt {attempt} 启动")
            except Exception:
                pass
        observe_write_event(
            project_root,
            stage_name,
            attempt=attempt,
            channel="workflow",
            event="attempt.started",
            message=f"{_stage_display_name(stage_name)} attempt {attempt} 启动",
        )

        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=str(project_root),
            )
        except OSError as exc:
            last_error = f"{stage_name} 启动失败: {exc}"
            break

        assert proc.stdin is not None
        assert proc.stdout is not None
        assert proc.stderr is not None
        proc.stdin.write(prompt)
        proc.stdin.close()

        event_queue: "queue.Queue[tuple[str, str | None]]" = queue.Queue()
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        trace_entries: list[Dict[str, Any]] = []
        stdout_done = False
        stderr_done = False
        turn_completed = False
        reconnect_errors = 0
        force_retry = False
        force_retry_reason = ""
        validated_payload: Dict[str, Any] | None = None
        last_progress_note = ""
        last_progress_at = 0.0
        stdout_thread = threading.Thread(target=_pump_stream, args=(proc.stdout, event_queue, "stdout"), daemon=True)
        stderr_thread = threading.Thread(target=_pump_stream, args=(proc.stderr, event_queue, "stderr"), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        def maybe_update_progress(note: str) -> None:
            nonlocal last_progress_note, last_progress_at
            cleaned = _trim_progress_note(note)
            if not cleaned or not step_id:
                return
            now_tick = time.monotonic()
            if cleaned == last_progress_note and (now_tick - last_progress_at) < 1.0:
                return
            try:
                update_step(project_root, step_id, note=cleaned)
            except Exception:
                pass
            _emit_tui_line(cleaned)
            last_progress_note = cleaned
            last_progress_at = now_tick

        deadline = time.monotonic() + timeout_seconds
        timeout_hit = False

        with stdout_log.open("a", encoding="utf-8") as stdout_fh, stderr_log.open("a", encoding="utf-8") as stderr_fh, attempt_stdout_path.open("a", encoding="utf-8") as attempt_stdout_fh, attempt_stderr_path.open("a", encoding="utf-8") as attempt_stderr_fh:
            while time.monotonic() < deadline:
                if output_path.is_file():
                    try:
                        candidate = json.loads(output_path.read_text(encoding="utf-8"))
                    except Exception:
                        candidate = None
                    if isinstance(candidate, dict):
                        validated_payload = candidate

                if validated_payload is not None and proc.poll() is not None and (turn_completed or (stdout_done and stderr_done)):
                    break

                try:
                    label, line = event_queue.get(timeout=0.2)
                except queue.Empty:
                    if validated_payload is not None and proc.poll() is not None:
                        break
                    if proc.poll() is not None and stdout_done and stderr_done:
                        break
                    continue

                if line is None:
                    if label == "stdout":
                        stdout_done = True
                    else:
                        stderr_done = True
                    if validated_payload is not None and proc.poll() is not None:
                        break
                    if proc.poll() is not None and stdout_done and stderr_done:
                        break
                    continue

                if label == "stdout":
                    stdout_lines.append(line)
                    stdout_fh.write(line)
                    stdout_fh.flush()
                    attempt_stdout_fh.write(line)
                    attempt_stdout_fh.flush()
                    payload = _parse_stream_payload(line)
                    if isinstance(payload, dict):
                        event_type = str(payload.get("type") or "").strip() or "stdout"
                        if event_type == "turn.completed":
                            turn_completed = True
                        trace_entry = _extract_trace_entry(payload)
                        if trace_entry:
                            enriched = dict(trace_entry)
                            enriched["timestamp"] = now_iso()
                            enriched["attempt"] = attempt
                            trace_entries.append(enriched)
                            note = _trace_note_from_entry(stage_name, enriched)
                            observe_write_event(
                                project_root,
                                stage_name,
                                attempt=attempt,
                                channel="stdout",
                                event=f"trace.{enriched.get('kind') or 'event'}",
                                message=note,
                            )
                            maybe_update_progress(note)
                        if event_type in {"thread.started", "turn.started", "turn.completed", "turn.failed", "error"}:
                            note = _stream_note_from_payload(stage_name, payload)
                            observe_write_event(
                                project_root,
                                stage_name,
                                attempt=attempt,
                                channel="stdout",
                                event=event_type,
                                message=note,
                            )
                            maybe_update_progress(note)
                            if event_type == "error":
                                message = str(payload.get("message") or "").strip()
                                if _is_retryable_provider_error(message):
                                    reconnect_errors += 1
                                    if reconnect_errors >= max(1, DEFAULT_STAGE_RECONNECT_RETRY_THRESHOLD):
                                        force_retry = True
                                        force_retry_reason = (
                                            f"{stage_name} provider reconnect 达到阈值 "
                                            f"({reconnect_errors} >= {max(1, DEFAULT_STAGE_RECONNECT_RETRY_THRESHOLD)})"
                                        )
                                        observe_write_event(
                                            project_root,
                                            stage_name,
                                            attempt=attempt,
                                            channel="workflow",
                                            event="attempt.force_retry",
                                            message=f"{_stage_display_name(stage_name)} · {force_retry_reason}",
                                        )
                                        maybe_update_progress(f"{_stage_display_name(stage_name)} · 连续重连过多，提前重试")
                                        break
                else:
                    stderr_lines.append(line)
                    stderr_fh.write(line)
                    stderr_fh.flush()
                    attempt_stderr_fh.write(line)
                    attempt_stderr_fh.flush()
                    stripped = line.strip()
                    if stripped and any(token in stripped.lower() for token in ("warning", "error", "retry", "failed")):
                        note = _trim_progress_note(f"{_stage_display_name(stage_name)} · {stripped}")
                        observe_write_event(
                            project_root,
                            stage_name,
                            attempt=attempt,
                            channel="stderr",
                            event="stderr",
                            message=note,
                        )
                        maybe_update_progress(note)
            else:
                timeout_hit = True

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        last_elapsed_ms = elapsed_ms
        return_code = _terminate_process(proc)

        if turn_completed and not validated_payload and output_path.exists():
            grace_deadline = time.monotonic() + output_grace_seconds
            while time.monotonic() < grace_deadline:
                try:
                    candidate = json.loads(output_path.read_text(encoding="utf-8"))
                except Exception:
                    candidate = None
                if isinstance(candidate, dict):
                    validated_payload = candidate
                    break
                time.sleep(0.1)

        stage_error_text = _select_stage_error_text("".join(stdout_lines), "".join(stderr_lines))
        trace_summary = _summarize_stage_trace(trace_entries, workspace_file=workspace_file, project_root=project_root)
        last_trace_summary = trace_summary
        write_json(
            trace_path,
            {
                "stage": stage_name,
                "attempt": attempt,
                "summary": trace_summary,
                "entries": trace_entries,
            },
        )

        if force_retry:
            last_error = force_retry_reason or f"{stage_name} provider reconnect 过多"
            write_json(
                execution_path,
                {
                    "stage": stage_name,
                    "chapter": chapter,
                    "attempt": attempt,
                    "success": False,
                    "error": last_error,
                    "sandbox_mode": sandbox_mode,
                    "stdout_log": _display_path(stdout_log),
                    "stderr_log": _display_path(stderr_log),
                    "trace_path": _display_path(trace_path),
                    "trace_summary": trace_summary,
                    "workspace_file": _display_path(workspace_file) if workspace_file else None,
                    "return_code": return_code,
                    "turn_completed": turn_completed,
                    "reconnect_errors": reconnect_errors,
                },
            )
        elif timeout_hit:
            last_error = f"{stage_name} 超时: {timeout_seconds}s"
            write_json(
                execution_path,
                {
                    "stage": stage_name,
                    "chapter": chapter,
                    "attempt": attempt,
                    "success": False,
                    "error": last_error,
                    "sandbox_mode": sandbox_mode,
                    "stdout_log": _display_path(stdout_log),
                    "stderr_log": _display_path(stderr_log),
                    "trace_path": _display_path(trace_path),
                    "trace_summary": trace_summary,
                    "workspace_file": _display_path(workspace_file) if workspace_file else None,
                },
            )
        elif validated_payload is not None:
            try:
                execution_report = _compose_workspace_execution_report(
                    stage_name=stage_name,
                    project_root=project_root,
                    chapter=chapter,
                    workspace_file=workspace_file,
                    before_document=before_document,
                    validated_payload=validated_payload,
                    trace_summary=trace_summary,
                    expected_title=expected_title,
                    require_mutation=require_workspace_mutation,
                )
            except Exception as exc:
                last_error = str(exc)
                write_json(
                    execution_path,
                    {
                        "stage": stage_name,
                        "chapter": chapter,
                        "attempt": attempt,
                        "success": False,
                        "error": last_error,
                        "sandbox_mode": sandbox_mode,
                        "stdout_log": _display_path(stdout_log),
                        "stderr_log": _display_path(stderr_log),
                        "trace_path": _display_path(trace_path),
                        "trace_summary": trace_summary,
                        "workspace_file": _display_path(workspace_file) if workspace_file else None,
                        "return_code": return_code,
                        "turn_completed": turn_completed,
                    },
                )
                observe_write_event(
                    project_root,
                    stage_name,
                    attempt=attempt,
                    channel="workflow",
                    event="attempt.validation_failed",
                    message=f"{_stage_display_name(stage_name)} attempt {attempt} 校验失败: {last_error}",
                )
            else:
                execution_payload = {
                    "stage": stage_name,
                    "chapter": chapter,
                    "attempt": attempt,
                    "success": True,
                    "sandbox_mode": sandbox_mode,
                    "stdout_log": _display_path(stdout_log),
                    "stderr_log": _display_path(stderr_log),
                    "trace_path": _display_path(trace_path),
                    "execution_path": _display_path(execution_path),
                    "return_code": return_code,
                    "turn_completed": turn_completed,
                    "live_streamed": True,
                    **execution_report,
                }
                write_json(execution_path, execution_payload)
                observe_write(
                    project_root,
                    stage_name,
                    success=True,
                    elapsed_ms=elapsed_ms,
                    details=execution_payload,
                )
                observe_write_event(
                    project_root,
                    stage_name,
                    attempt=attempt,
                    channel="workflow",
                    event="attempt.succeeded",
                    message=f"{_stage_display_name(stage_name)} attempt {attempt} 完成",
                )
                if step_id:
                    try:
                        update_step(project_root, step_id, note=f"{_stage_display_name(stage_name)} · attempt {attempt} 完成")
                    except Exception:
                        pass
                return validated_payload
        else:
            last_error = stage_error_text or f"{stage_name} 执行失败（exit={return_code}）"
            write_json(
                execution_path,
                {
                    "stage": stage_name,
                    "chapter": chapter,
                    "attempt": attempt,
                    "success": False,
                    "error": last_error,
                    "sandbox_mode": sandbox_mode,
                    "stdout_log": _display_path(stdout_log),
                    "stderr_log": _display_path(stderr_log),
                    "trace_path": _display_path(trace_path),
                    "trace_summary": trace_summary,
                    "workspace_file": _display_path(workspace_file) if workspace_file else None,
                    "return_code": return_code,
                    "turn_completed": turn_completed,
                },
            )

        if attempt <= retries and (force_retry or _is_retryable_provider_error(last_error)):
            observe_write_event(
                project_root,
                stage_name,
                attempt=attempt,
                channel="workflow",
                event="attempt.retry",
                message=f"{_stage_display_name(stage_name)} attempt {attempt} 失败，准备重试",
            )
            if step_id:
                try:
                    update_step(project_root, step_id, note=f"{_stage_display_name(stage_name)} · provider 异常，准备重试")
                except Exception:
                    pass
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass
            time.sleep(DEFAULT_STAGE_RETRY_BACKOFF_SECONDS * attempt)
            continue
        break

    observe_write(
        project_root,
        stage_name,
        success=False,
        elapsed_ms=last_elapsed_ms,
        details={
            "chapter": chapter,
            "error": last_error,
            "sandbox_mode": sandbox_mode,
            "stdout_log": _display_path(stdout_log),
            "stderr_log": _display_path(stderr_log),
            "trace_path": _display_path(trace_path),
            "execution_path": _display_path(execution_path),
            "trace_summary": last_trace_summary,
            "workspace_file": _display_path(workspace_file) if workspace_file else None,
            "live_streamed": True,
        },
    )
    observe_write_event(
        project_root,
        stage_name,
        attempt=retries + 1,
        channel="workflow",
        event="attempt.failed",
        message=f"{_stage_display_name(stage_name)} 失败: {last_error or 'unknown error'}",
    )
    raise RuntimeError(last_error or f"{stage_name} 执行失败")


def _normalize_body(content: str, chapter: int, title: str) -> str:
    text = str(content or "").replace("\r\n", "\n").strip()
    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    patterns = [
        rf"^第\s*{chapter}\s*章(?:\s+|[：: -]).*$",
        rf"^第\s*{chapter:03d}\s*章(?:\s+|[：: -]).*$",
        rf"^第\s*{chapter:04d}\s*章(?:\s+|[：: -]).*$",
    ]
    if any(re.match(pattern, first_line) for pattern in patterns):
        text = "\n".join(text.splitlines()[1:]).strip()
    if first_line == title.strip():
        text = "\n".join(text.splitlines()[1:]).strip()
    return text


def _compose_chapter_file(chapter: int, title: str, body: str) -> str:
    cleaned = _normalize_body(body, chapter, title)
    return f"第{chapter}章 {title.strip()}\n\n{cleaned.strip()}\n"


def _foreshadowing_notes_from_payload(data_payload: Dict[str, Any]) -> List[str]:
    notes = [str(item).strip() for item in (data_payload.get("foreshadowing_notes") or []) if str(item).strip()]
    if notes:
        return notes

    derived: List[str] = []
    for label, key in (("埋设", "foreshadowing_planted"), ("延续", "foreshadowing_continued"), ("回收", "foreshadowing_resolved")):
        for item in data_payload.get(key) or []:
            compact = _compact_foreshadowing_item(item)
            if compact is None:
                continue
            derived.append(f"[{label}] {compact['content']}")
    return derived


def _summary_markdown(chapter: int, data_payload: Dict[str, Any]) -> str:
    chapter_meta = data_payload.get("chapter_meta") or {}
    hook_type = str(chapter_meta.get("hook_type") or "信息钩").strip() or "信息钩"
    hook_strength = str(chapter_meta.get("hook_strength") or "medium").strip() or "medium"
    location = str(data_payload.get("location") or "").strip()
    time_anchor = str(data_payload.get("time_anchor") or "").strip()
    characters = data_payload.get("characters") or []
    state_changes = data_payload.get("state_changes") or []
    summary_text = str(data_payload.get("summary_text") or chapter_meta.get("summary") or "").strip()
    bridge_line = str(data_payload.get("bridge_line") or chapter_meta.get("unresolved_question") or "").strip()
    foreshadowing = _foreshadowing_notes_from_payload(data_payload)
    front = [
        "---",
        f'chapter: "{chapter:04d}"',
        f'time: "{time_anchor}"',
        f'location: "{location}"',
        "characters: " + json.dumps(characters, ensure_ascii=False),
        "state_changes: " + json.dumps(
            [f"{row.get('entity_id', '')}:{row.get('field', '')}" for row in state_changes if isinstance(row, dict)],
            ensure_ascii=False,
        ),
        f'hook_type: "{hook_type}"',
        f'hook_strength: "{hook_strength}"',
        "---",
        "",
        "## 剧情摘要",
        summary_text,
        "",
        "## 伏笔",
    ]
    if foreshadowing:
        front.extend([f"- {item}" for item in foreshadowing])
    else:
        front.append("- [无新增] 本章以主线推进为主")
    front.extend(["", "## 承接点", bridge_line or "待续"])
    return "\n".join(front).strip() + "\n"


def _chapter_stats(project_root: Path) -> Dict[str, int]:
    total = 0
    chapters = 0
    root = project_root / "正文"
    if root.is_dir():
        for path in sorted(root.rglob("第*.md")):
            if not path.is_file():
                continue
            total += len(path.read_text(encoding="utf-8"))
            chapters += 1
    return {"chapters": chapters, "total_chars": total}


def _load_context_materials(project_root: Path, chapter: int) -> Dict[str, Any]:
    state = _load_state(project_root)
    context_payload = _strip_cli_wrapper(_run_webnovel_json(project_root, "context", "--", "--chapter", str(chapter)))
    extract_payload = _strip_cli_wrapper(_run_webnovel_json(project_root, "extract-context", "--chapter", str(chapter), "--format", "json"))
    reading_power = _strip_cli_wrapper(_run_webnovel_json(project_root, "index", "get-recent-reading-power", "--limit", "5"))
    pattern_stats = _strip_cli_wrapper(_run_webnovel_json(project_root, "index", "get-pattern-usage-stats", "--last-n", "20"))
    hook_stats = _strip_cli_wrapper(_run_webnovel_json(project_root, "index", "get-hook-type-stats", "--last-n", "20"))
    debt_summary = _strip_cli_wrapper(_run_webnovel_json(project_root, "index", "get-debt-summary"))
    core_entities = _strip_cli_wrapper(_run_webnovel_json(project_root, "index", "get-core-entities"))
    recent_appearances = _strip_cli_wrapper(_run_webnovel_json(project_root, "index", "recent-appearances", "--limit", "20"))
    timeline_text = _load_volume_timeline(project_root, chapter, state)
    return {
        "state": state,
        "context_manager": context_payload,
        "extract_context": extract_payload,
        "recent_reading_power": reading_power,
        "pattern_usage_stats": pattern_stats,
        "hook_type_stats": hook_stats,
        "debt_summary": debt_summary,
        "core_entities": core_entities,
        "recent_appearances": recent_appearances,
        "timeline_text": timeline_text,
    }


def _truncate_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if DISABLE_CONTEXT_COMPRESSION:
        return text
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(已截断)"


def _sanitize_context_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n?\.\.\.\(已截断\)", "", normalized)
    normalized = re.sub(r"\s*\n\s*", " ", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    normalized = re.sub(r"([。！？；，,.!?;:：])\1+", r"\1", normalized)
    return normalized


def _clip_context_text(value: Any, limit: int) -> str:
    text = _sanitize_context_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，。；：,.!?！？；: ")


def _clip_context_list(values: Any, *, item_limit: int, text_limit: int) -> List[str]:
    if not isinstance(values, list):
        return []
    cleaned: List[str] = []
    for raw in values:
        text = _clip_context_text(raw, text_limit)
        if not text or text in cleaned:
            continue
        cleaned.append(text)
        if len(cleaned) >= item_limit:
            break
    return cleaned


def _clip_context_characters(values: Any, *, item_limit: int = 6) -> List[Dict[str, str]]:
    if not isinstance(values, list):
        return []
    rows: List[Dict[str, str]] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        name = _clip_context_text(raw.get("name"), 24)
        role = _clip_context_text(raw.get("role"), 28)
        if not name:
            continue
        row = {"name": name, "role": role or "角色"}
        if row in rows:
            continue
        rows.append(row)
        if len(rows) >= item_limit:
            break
    return rows


def _clip_context_must_continue(values: Any, *, item_limit: int = 4) -> List[Dict[str, str]]:
    if not isinstance(values, list):
        return []
    rows: List[Dict[str, str]] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        item_id = _clip_context_text(raw.get("id"), 40)
        content = _clip_context_text(raw.get("content"), 90)
        purpose = _clip_context_text(raw.get("purpose"), 80)
        if not (item_id and content and purpose):
            continue
        row = {"id": item_id, "content": content, "purpose": purpose}
        if row in rows:
            continue
        rows.append(row)
        if len(rows) >= item_limit:
            break
    return rows


def _clip_context_planned_new(values: Any, *, item_limit: int = 4) -> List[Dict[str, str]]:
    if not isinstance(values, list):
        return []
    rows: List[Dict[str, str]] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        content = _clip_context_text(raw.get("content"), 90)
        plant_method = _clip_context_text(raw.get("plant_method"), 80)
        purpose = _clip_context_text(raw.get("purpose"), 80)
        expected_payoff = _clip_context_text(raw.get("expected_payoff"), 80)
        if not (content and plant_method and purpose and expected_payoff):
            continue
        row = {
            "content": content,
            "plant_method": plant_method,
            "purpose": purpose,
            "expected_payoff": expected_payoff,
        }
        if row in rows:
            continue
        rows.append(row)
        if len(rows) >= item_limit:
            break
    return rows


def _as_sentence_fragment(value: Any, *, limit: int) -> str:
    text = _clip_context_text(value, limit).strip()
    return text.rstrip("。！？!?；;，,")


def _compact_foreshadowing_item(raw_item: Any) -> Dict[str, Any] | None:
    if not isinstance(raw_item, dict):
        return None
    content = str(raw_item.get("content") or "").strip()
    if not content:
        return None
    item = {
        "id": str(raw_item.get("id") or "").strip(),
        "content": _truncate_text(content, 80),
        "status": str(raw_item.get("status") or "").strip(),
    }
    field_limits = {
        "tier": 24,
        "expected_payoff": 60,
        "purpose": 48,
        "plant_method": 48,
        "note_type": 24,
    }
    for field, limit in field_limits.items():
        value = str(raw_item.get(field) or "").strip()
        if value:
            item[field] = _truncate_text(value, limit)
    for source_key, target_key in (("planted_chapter", "planted_chapter"), ("chapter_planted", "planted_chapter"), ("resolved_chapter", "resolved_chapter")):
        value = raw_item.get(source_key)
        if value not in (None, ""):
            item[target_key] = value
    return item


def _compact_recent_meta_row(chapter: int, row: Dict[str, Any]) -> Dict[str, Any]:
    compact = {"chapter": chapter}
    for key in ("title", "dominant_strand", "hook_type", "hook_strength", "bridge_line"):
        value = row.get(key)
        if value in (None, "", [], {}):
            continue
        compact[key] = _truncate_text(value, 40 if key == "title" else (20 if key == "dominant_strand" else (24 if key == "hook_type" else (18 if key == "hook_strength" else 60))) )
    for key in ("review_score", "words", "foreshadow_open_count"):
        value = row.get(key)
        if value not in (None, ""):
            compact[key] = value
    return compact


def _compact_timeline_digest(value: Any, *, limit_lines: int = 3, limit_chars: int = 120) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    if not lines:
        return ""
    if DISABLE_CONTEXT_COMPRESSION:
        return "\n".join(lines)
    digest = "\n".join(lines[:limit_lines])
    return _truncate_text(digest, limit_chars)


def _signal_tokens(*parts: Any) -> List[str]:
    seen: set[str] = set()
    tokens: List[str] = []
    for part in parts:
        text = str(part or "")
        for token in re.findall(r"[A-Za-z0-9_]+|[一-鿿]", text):
            token = token.strip().lower()
            if len(token) <= 1 and not re.match(r"[一-鿿]", token):
                continue
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    return tokens


def _relevance_score(value: Any, signal_tokens: Sequence[str]) -> int:
    haystack = str(value or "").lower()
    score = 0
    for token in signal_tokens:
        if token and token in haystack:
            score += max(1, len(token))
    return score


def _sort_by_relevance(items: Sequence[Dict[str, Any]], *, signal_tokens: Sequence[str], text_fn, limit: int) -> List[Dict[str, Any]]:
    scored: List[tuple[int, int, Dict[str, Any]]] = []
    for index, item in enumerate(items):
        score = _relevance_score(text_fn(item), signal_tokens)
        scored.append((score, -index, item))
    scored.sort(key=lambda pair: (pair[0], pair[1]), reverse=True)
    ordered = [item for _score, _idx, item in scored]
    if not ordered:
        return []
    top = ordered[:limit]
    if any(_relevance_score(text_fn(item), signal_tokens) > 0 for item in top):
        return top
    return list(items[:limit])


def _prune_empty(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            pruned = _prune_empty(item)
            if pruned in (None, "", [], {}):
                continue
            cleaned[key] = pruned
        return cleaned
    if isinstance(value, list):
        cleaned = []
        for item in value:
            pruned = _prune_empty(item)
            if pruned in (None, "", [], {}):
                continue
            cleaned.append(pruned)
        return cleaned
    return value


def _compact_json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_size_bytes(value: Any) -> int:
    return len(_compact_json_text(value).encode("utf-8"))


CONTEXT_STAGE_INPUT_BUDGETS = {
    "context_story_spine": 2500,
    "context_cast_constraints": 3000,
    "context_foreshadow_plan": 3600,
    "context_reader_pull": 2300,
    "context_contract_core": 5200,
    "context_draft_package": 4200,
}
ENFORCE_CONTEXT_STAGE_INPUT_BUDGET = str(os.environ.get("WEBNOVEL_ENFORCE_CONTEXT_STAGE_INPUT_BUDGET", "0") or "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def _collect_open_foreshadowing(state: Dict[str, Any], *, signal_tokens: Sequence[str]) -> List[Dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    plot_threads = state.get("plot_threads")
    if not isinstance(plot_threads, dict):
        return []
    foreshadowing = plot_threads.get("foreshadowing")
    if not isinstance(foreshadowing, list):
        return []
    items: List[Dict[str, Any]] = []
    for raw_item in foreshadowing:
        compact = _compact_foreshadowing_item(raw_item)
        if compact is None:
            continue
        status = str(compact.get("status") or "").strip().lower()
        if status in {"已回收", "resolved", "closed"}:
            continue
        items.append(compact)
    if DISABLE_CONTEXT_COMPRESSION:
        return items
    ranked = _sort_by_relevance(
        items,
        signal_tokens=signal_tokens,
        text_fn=lambda item: " ".join(str(item.get(key) or "") for key in ("id", "content", "purpose", "expected_payoff", "plant_method")),
        limit=6,
    )
    return ranked


def _compact_context_materials(materials: Dict[str, Any], chapter: int) -> Dict[str, Any]:
    extract_payload = materials.get("extract_context") or {}
    context_payload = materials.get("context_manager") or {}
    state = materials.get("state") or {}
    signal_tokens = _signal_tokens(
        extract_payload.get("outline"),
        "\n".join(extract_payload.get("previous_summaries") or []),
        extract_payload.get("state_summary"),
    )
    recent_meta: List[Dict[str, Any]] = []
    chapter_meta = (state.get("chapter_meta") or {}) if isinstance(state, dict) else {}
    if DISABLE_CONTEXT_COMPRESSION:
        chapter_meta_items: List[tuple[int, Dict[str, Any]]] = []
        for key, row in chapter_meta.items():
            if not isinstance(row, dict):
                continue
            try:
                ch = int(str(key))
            except Exception:
                continue
            if ch >= chapter:
                continue
            chapter_meta_items.append((ch, row))
        chapter_meta_items.sort(key=lambda item: item[0])
        for ch, row in chapter_meta_items:
            recent_meta.append(_compact_recent_meta_row(ch, row))
    else:
        for ch in range(max(1, chapter - 2), chapter):
            row = chapter_meta.get(f"{ch:04d}")
            if isinstance(row, dict):
                recent_meta.append(_compact_recent_meta_row(ch, row))

    guidance_items: List[str] = []
    writing_guidance = context_payload.get("writing_guidance") or {}
    if isinstance(writing_guidance, dict):
        source_guidance = list(writing_guidance.get("guidance_items") or [])
        if not DISABLE_CONTEXT_COMPRESSION:
            source_guidance = source_guidance[:3]
        for item in source_guidance:
            text = _truncate_text(item, 40)
            if text:
                guidance_items.append(text)

    recent_reading_power: List[Dict[str, Any]] = []
    reading_rows = list(materials.get("recent_reading_power") or [])
    if not DISABLE_CONTEXT_COMPRESSION:
        reading_rows = reading_rows[:4]
    for row in reading_rows:
        if not isinstance(row, dict):
            continue
        recent_reading_power.append(
            _prune_empty(
                {
                    "chapter": row.get("end_chapter") or row.get("chapter"),
                    "overall_score": row.get("overall_score"),
                }
            )
        )

    core_entity_rows: List[Dict[str, Any]] = []
    for row in materials.get("core_entities") or []:
        if not isinstance(row, dict):
            continue
        core_entity_rows.append(
            _prune_empty(
                {
                    "id": row.get("id"),
                    "name": _truncate_text(row.get("canonical_name") or row.get("name"), 24),
                    "type": row.get("type"),
                    "tier": row.get("tier"),
                }
            )
        )
    core_entities = _sort_by_relevance(
        core_entity_rows,
        signal_tokens=signal_tokens,
        text_fn=lambda item: " ".join(str(item.get(key) or "") for key in ("name", "id", "type", "tier")),
        limit=len(core_entity_rows) if DISABLE_CONTEXT_COMPRESSION else 6,
    )
    selected_ids = {str(item.get("id") or "").strip() for item in core_entities if str(item.get("id") or "").strip()}

    recent_appearances = []
    for row in materials.get("recent_appearances") or []:
        if not isinstance(row, dict):
            continue
        entity_id = str(row.get("entity_id") or row.get("id") or "").strip()
        if selected_ids and entity_id and entity_id not in selected_ids:
            continue
        recent_appearances.append(
            _prune_empty(
                {
                    "chapter": row.get("chapter") or row.get("last_chapter"),
                    "entity": entity_id or row.get("canonical_name") or row.get("name"),
                    "mentions": row.get("mentions") or row.get("total"),
                }
            )
        )
    if not DISABLE_CONTEXT_COMPRESSION:
        recent_appearances = recent_appearances[:4]

    timeline_anchor_digest = _compact_timeline_digest(materials.get("timeline_text"))
    previous_summaries = list(extract_payload.get("previous_summaries") or [])
    if not DISABLE_CONTEXT_COMPRESSION:
        previous_summaries = previous_summaries[:2]
    compact_previous_summaries = [_truncate_text(item, 90) for item in previous_summaries]
    return _prune_empty(
        {
            "chapter": chapter,
            "outline": _truncate_text(extract_payload.get("outline"), 180),
            "previous_summaries": compact_previous_summaries,
            "state_summary": _truncate_text(extract_payload.get("state_summary"), 140),
            "reader_signal": context_payload.get("reader_signal"),
            "genre_profile": context_payload.get("genre_profile"),
            "writing_guidance": guidance_items,
            "timeline_anchor_digest": timeline_anchor_digest,
            "recent_chapter_meta": recent_meta,
            "open_foreshadowing": _collect_open_foreshadowing(state, signal_tokens=signal_tokens),
            "recent_reading_power": recent_reading_power,
            "pattern_usage_stats": materials.get("pattern_usage_stats"),
            "hook_type_stats": materials.get("hook_type_stats"),
            "debt_summary": materials.get("debt_summary"),
            "core_entities": core_entities,
            "recent_appearances": recent_appearances,
        }
    )


CONTEXT_AGENT_SEGMENTS = (
    "context_story_spine",
    "context_cast_constraints",
    "context_foreshadow_plan",
    "context_reader_pull",
    "context_contract_core",
    "context_draft_package",
)


def _context_material_slice(compact: Dict[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
    return _prune_empty({key: compact.get(key) for key in keys if key in compact})


def _build_context_story_spine_input(chapter: int, compact: Dict[str, Any]) -> Dict[str, Any]:
    recent_meta = compact.get("recent_chapter_meta") or []
    if not DISABLE_CONTEXT_COMPRESSION:
        recent_meta = recent_meta[-1:]
    return _prune_empty(
        {
            "chapter": chapter,
            "outline": compact.get("outline"),
            "previous_summaries": compact.get("previous_summaries"),
            "state_summary": compact.get("state_summary"),
            "timeline_anchor": compact.get("timeline_anchor_digest"),
            "recent_chapter_meta": recent_meta,
        }
    )


def _build_context_cast_constraints_input(chapter: int, compact: Dict[str, Any], story_spine: Dict[str, Any]) -> Dict[str, Any]:
    core_entities = compact.get("core_entities") or []
    recent_appearances = compact.get("recent_appearances") or []
    writing_guidance = compact.get("writing_guidance") or []
    recent_meta = compact.get("recent_chapter_meta") or []
    if not DISABLE_CONTEXT_COMPRESSION:
        core_entities = core_entities[:4]
        recent_appearances = recent_appearances[:3]
        writing_guidance = writing_guidance[:2]
        recent_meta = recent_meta[-1:]
    return _prune_empty(
        {
            "chapter": chapter,
            "story_spine": story_spine,
            "timeline_anchor": compact.get("timeline_anchor_digest")
            if DISABLE_CONTEXT_COMPRESSION
            else _truncate_text(compact.get("timeline_anchor_digest"), 60),
            "recent_chapter_meta": recent_meta,
            "core_entities": core_entities,
            "recent_appearances": recent_appearances,
            "writing_guidance": writing_guidance,
        }
    )


def _build_context_foreshadow_plan_input(chapter: int, compact: Dict[str, Any], story_spine: Dict[str, Any]) -> Dict[str, Any]:
    if DISABLE_CONTEXT_COMPRESSION:
        return _prune_empty(
            {
                "chapter": chapter,
                "story_spine": story_spine,
                "open_foreshadowing": compact.get("open_foreshadowing"),
                "recent_chapter_meta": compact.get("recent_chapter_meta"),
            }
        )
    compact_story_spine = _prune_empty(
        {
            "core_task": _truncate_text(story_spine.get("core_task"), 120),
            "conflict": _truncate_text(story_spine.get("conflict"), 120),
            "carry_from_previous": _truncate_text(story_spine.get("carry_from_previous"), 120),
            "must_complete": [_truncate_text(item, 40) for item in (story_spine.get("must_complete") or [])[:3] if str(item or "").strip()],
            "must_not": [_truncate_text(item, 40) for item in (story_spine.get("must_not") or [])[:3] if str(item or "").strip()],
            "opening_suggestion": _truncate_text(story_spine.get("opening_suggestion"), 80),
        }
    )
    compact_open_foreshadowing = []
    for item in (compact.get("open_foreshadowing") or [])[:4]:
        if not isinstance(item, dict):
            continue
        compact_open_foreshadowing.append(
            _prune_empty(
                {
                    "id": _truncate_text(item.get("id"), 40),
                    "content": _truncate_text(item.get("content"), 120),
                    "status": _truncate_text(item.get("status"), 16),
                    "expected_payoff": _truncate_text(item.get("expected_payoff"), 100),
                }
            )
        )
    return _prune_empty(
        {
            "chapter": chapter,
            "story_spine": compact_story_spine,
            "open_foreshadowing": compact_open_foreshadowing,
            "recent_chapter_meta": (compact.get("recent_chapter_meta") or [])[-1:],
        }
    )


def _build_context_reader_pull_input(chapter: int, compact: Dict[str, Any], story_spine: Dict[str, Any]) -> Dict[str, Any]:
    if DISABLE_CONTEXT_COMPRESSION:
        return _prune_empty(
            {
                "chapter": chapter,
                "story_spine": story_spine,
                "recent_reading_power": compact.get("recent_reading_power"),
                "debt_summary": compact.get("debt_summary"),
                "hook_type_stats": compact.get("hook_type_stats"),
                "recent_chapter_meta": compact.get("recent_chapter_meta"),
            }
        )
    compact_story_spine = _prune_empty(
        {
            "core_task": _truncate_text(story_spine.get("core_task"), 72),
            "conflict": _truncate_text(story_spine.get("conflict"), 72),
            "carry_from_previous": _truncate_text(story_spine.get("carry_from_previous"), 72),
            "must_complete": [_truncate_text(item, 28) for item in (story_spine.get("must_complete") or [])[:2] if str(item or "").strip()],
            "opening_suggestion": _truncate_text(story_spine.get("opening_suggestion"), 48),
        }
    )
    return _prune_empty(
        {
            "chapter": chapter,
            "story_spine": compact_story_spine,
            "recent_reading_power": compact.get("recent_reading_power"),
            "debt_summary": compact.get("debt_summary"),
            "hook_type_stats": compact.get("hook_type_stats"),
            "recent_chapter_meta": compact.get("recent_chapter_meta"),
        }
    )


def _build_context_contract_core_input(chapter: int, story_spine: Dict[str, Any], cast_constraints: Dict[str, Any], reader_pull: Dict[str, Any]) -> Dict[str, Any]:
    return _prune_empty(
        {
            "chapter": chapter,
            "story_spine": story_spine,
            "cast_constraints": cast_constraints,
            "reader_pull": reader_pull,
        }
    )


def _build_context_draft_package_input(
    chapter: int,
    compact: Dict[str, Any],
    task_brief: Dict[str, Any],
    contract_v2: Dict[str, Any],
    *,
    compact_mode: bool = False,
) -> Dict[str, Any]:
    if not compact_mode:
        recent_reading_power = compact.get("recent_reading_power") or []
        if not DISABLE_CONTEXT_COMPRESSION:
            recent_reading_power = recent_reading_power[:1]
        return _prune_empty(
            {
                "chapter": chapter,
                "task_brief": task_brief,
                "contract_v2": contract_v2,
                "pattern_usage_stats": compact.get("pattern_usage_stats"),
                "recent_reading_power": recent_reading_power,
            }
        )

    foreshadowing_plan = task_brief.get("foreshadowing_plan") or {}
    compact_task_brief = {
        "core_task": _clip_context_text(task_brief.get("core_task"), 220),
        "conflict": _clip_context_text(task_brief.get("conflict"), 220),
        "carry_from_previous": _clip_context_text(task_brief.get("carry_from_previous"), 180),
        "must_complete": _clip_context_list(task_brief.get("must_complete"), item_limit=6, text_limit=90),
        "must_not": _clip_context_list(task_brief.get("must_not"), item_limit=6, text_limit=90),
        "opening_suggestion": _clip_context_text(task_brief.get("opening_suggestion"), 180),
        "characters": _clip_context_characters(task_brief.get("characters"), item_limit=6),
        "scene_constraints": _clip_context_list(task_brief.get("scene_constraints"), item_limit=4, text_limit=100),
        "time_constraints": _clip_context_list(task_brief.get("time_constraints"), item_limit=4, text_limit=100),
        "style_guidance": _clip_context_list(task_brief.get("style_guidance"), item_limit=4, text_limit=90),
        "foreshadowing": _clip_context_list(task_brief.get("foreshadowing"), item_limit=5, text_limit=100),
        "foreshadowing_plan": {
            "must_continue": _clip_context_must_continue(foreshadowing_plan.get("must_continue"), item_limit=4),
            "planned_new": _clip_context_planned_new(foreshadowing_plan.get("planned_new"), item_limit=4),
            "forbidden_resolve": _clip_context_list(foreshadowing_plan.get("forbidden_resolve"), item_limit=4, text_limit=90),
        },
        "reading_power": _clip_context_list(task_brief.get("reading_power"), item_limit=4, text_limit=100),
        "strand_strategy": _clip_context_text(task_brief.get("strand_strategy"), 80),
    }
    compact_contract_v2 = {
        "goal": _clip_context_text(contract_v2.get("goal"), 200),
        "obstacle": _clip_context_text(contract_v2.get("obstacle"), 200),
        "cost": _clip_context_text(contract_v2.get("cost"), 180),
        "change": _clip_context_text(contract_v2.get("change"), 180),
        "unresolved_question": _clip_context_text(contract_v2.get("unresolved_question"), 180),
        "core_conflict": _clip_context_text(contract_v2.get("core_conflict"), 180),
        "opening_type": _clip_context_text(contract_v2.get("opening_type"), 40),
        "emotion_pacing": _clip_context_text(contract_v2.get("emotion_pacing"), 40),
        "info_density": _clip_context_text(contract_v2.get("info_density"), 40),
        "is_transition": bool(contract_v2.get("is_transition")),
        "hook_type": _clip_context_text(contract_v2.get("hook_type"), 30),
        "hook_strength": _clip_context_text(contract_v2.get("hook_strength"), 20),
        "micropayoffs": _clip_context_list(contract_v2.get("micropayoffs"), item_limit=4, text_limit=90),
        "cool_point_pattern": _clip_context_text(contract_v2.get("cool_point_pattern"), 40),
    }
    return _prune_empty(
        {
            "chapter": chapter,
            "task_brief": compact_task_brief,
            "contract_v2": compact_contract_v2,
            "pattern_usage_stats": compact.get("pattern_usage_stats"),
            "recent_reading_power": (compact.get("recent_reading_power") or [])[:1],
        }
    )


def _context_budget_breakdown(payload: Dict[str, Any]) -> Dict[str, int]:
    sizes: Dict[str, int] = {}
    for key, value in payload.items():
        if key == "chapter":
            continue
        sizes[key] = _json_size_bytes(value)
    return sizes


def _assert_context_input_budget(stage_name: str, payload: Dict[str, Any]) -> None:
    budget = CONTEXT_STAGE_INPUT_BUDGETS.get(stage_name)
    if budget is None:
        return
    input_bytes = _json_size_bytes(payload)
    if input_bytes <= budget:
        return
    breakdown = ", ".join(f"{key}={size}" for key, size in sorted(_context_budget_breakdown(payload).items(), key=lambda item: item[1], reverse=True))
    if not ENFORCE_CONTEXT_STAGE_INPUT_BUDGET:
        _emit_tui_line(f"{stage_name} input 超预算告警: {input_bytes} bytes > {budget} bytes ({breakdown})")
        return
    raise RuntimeError(f"{stage_name} input 超预算: {input_bytes} bytes > {budget} bytes ({breakdown})")


def observe_context_stage_metric(
    project_root: Path,
    stage: str,
    *,
    chapter: int,
    input_bytes: int,
    schema_bytes: int,
    prompt_bytes: int,
    success: bool,
    attempt: int | None = None,
    elapsed_ms: int | None = None,
    error: str | None = None,
    output_bytes: int | None = None,
) -> None:
    append_jsonl(
        project_root / OBSERVABILITY_CONTEXT_REL,
        {
            "timestamp": now_iso(),
            "chapter": chapter,
            "stage": stage,
            "input_bytes": input_bytes,
            "schema_bytes": schema_bytes,
            "prompt_bytes": prompt_bytes,
            "success": success,
            "attempt": attempt,
            "elapsed_ms": elapsed_ms,
            "error": _trim_progress_note(error or "", limit=240) if error else None,
            "output_bytes": output_bytes,
        },
    )


def _build_context_story_spine_prompt(chapter: int, payload: Dict[str, Any]) -> str:
    return f"""你是 webnovel-writer 的 context-agent，当前是 Step 1 子阶段 1/6。
只输出 JSON，顶层只能有 chapter 与 story_spine，chapter 必须等于 {chapter}。
任务：先定死这一章的主轴，不处理人物细节、伏笔细化和追读力。
优先级：大纲与设定 > 近期摘要 > 其他信号。
输入(JSON)：
{_compact_json_text(payload)}
story_spine 必须包含 core_task, conflict, carry_from_previous, must_complete, must_not, opening_suggestion。"""


def _build_context_cast_constraints_prompt(chapter: int, payload: Dict[str, Any]) -> str:
    return f"""你是 webnovel-writer 的 context-agent，当前是 Step 1 子阶段 2/6。
只输出 JSON，顶层只能有 chapter 与 cast_constraints，chapter 必须等于 {chapter}。
任务：基于既定 story_spine，给出本章可上场角色、场景限制、时间限制、风格提醒。不要重写主任务，不要设计新伏笔。
输入(JSON)：
{_compact_json_text(payload)}
cast_constraints 必须包含 characters、scene_constraints、time_constraints、style_guidance；后两者可为空数组。"""


def _build_context_foreshadow_plan_prompt(chapter: int, payload: Dict[str, Any]) -> str:
    return f"""你是 webnovel-writer 的 context-agent，当前是 Step 1 子阶段 3/6。
只输出 JSON，顶层只能有 chapter 与 foreshadow_plan，chapter 必须等于 {chapter}。
任务：只做伏笔设计。伏笔不是事后总结，必须先设计再写。
输入(JSON)：
{_compact_json_text(payload)}
foreshadow_plan 必须包含 foreshadowing 与 foreshadowing_plan。foreshadowing 为字符串数组。
foreshadowing_plan 必须给出 must_continue, planned_new, forbidden_resolve。
must_continue 的每个元素必须包含 id/content/purpose，id 只能引用输入里的 open_foreshadowing。
planned_new 的每个元素必须包含 content/plant_method/purpose/expected_payoff。"""


def _build_context_reader_pull_prompt(chapter: int, payload: Dict[str, Any]) -> str:
    return f"""你是 webnovel-writer 的 context-agent，当前是 Step 1 子阶段 4/6。
只输出 JSON，顶层只能有 chapter 与 reader_pull，chapter 必须等于 {chapter}。
任务：只判断本章的追读设计与 strand 节奏，不要重写主线和伏笔。
输入(JSON)：
{_compact_json_text(payload)}
reader_pull 必须包含 reading_power, strand_strategy, is_transition, hook_type, hook_strength, micropayoffs, cool_point_pattern。"""


def _build_context_contract_core_prompt(chapter: int, payload: Dict[str, Any]) -> str:
    return f"""你是 webnovel-writer 的 context-agent，当前是 Step 1 子阶段 5/6。
只输出 JSON，顶层只能有 chapter 与 contract_core，chapter 必须等于 {chapter}。
任务：在既定主轴、角色约束、追读策略上，补完整章写作 contract 的核心。
输入(JSON)：
{_compact_json_text(payload)}
contract_core 必须包含 goal, obstacle, cost, change, unresolved_question, core_conflict, opening_type, emotion_pacing, info_density。"""


def _build_context_draft_package_prompt(chapter: int, payload: Dict[str, Any]) -> str:
    return f"""你是 webnovel-writer 的 context-agent，当前是 Step 1 子阶段 6/6。
只输出 JSON，顶层只能有 chapter 与 draft_package，chapter 必须等于 {chapter}。
任务：把已经确定的 task_brief 与 contract_v2 转成可直接给 writer-draft 开写的 draft_package。不要回头改 task_brief 或 contract_v2。
输入(JSON)：
{_compact_json_text(payload)}
draft_package 必须包含 title_suggestion, beat_sheet, immutable_facts, forbidden, checklist, target_words；target_words 不得小于 1200。
所有字符串都用单行短句，不要复制大段原文，不要出现“...(已截断)”字样。"""


def _extract_context_segment(payload: Dict[str, Any], *, chapter: int, key: str, stage_name: str) -> Dict[str, Any]:
    if int(payload.get("chapter") or 0) != chapter:
        raise RuntimeError(f"{stage_name} chapter 不匹配: {payload.get('chapter')} != {chapter}")
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"{stage_name} 缺少 {key} 对象")
    return value


def _merge_context_segments(
    *,
    chapter: int,
    story_spine: Dict[str, Any],
    cast_constraints: Dict[str, Any],
    foreshadow_plan: Dict[str, Any],
    reader_pull: Dict[str, Any],
    contract_core: Dict[str, Any],
    draft_package: Dict[str, Any],
) -> Dict[str, Any]:
    task_brief = {
        **story_spine,
        **cast_constraints,
        **foreshadow_plan,
        "reading_power": reader_pull.get("reading_power") or [],
        "strand_strategy": reader_pull.get("strand_strategy") or "",
    }
    contract_v2 = {
        **contract_core,
        "is_transition": bool(reader_pull.get("is_transition")),
        "hook_type": str(reader_pull.get("hook_type") or ""),
        "hook_strength": str(reader_pull.get("hook_strength") or ""),
        "micropayoffs": list(reader_pull.get("micropayoffs") or []),
        "cool_point_pattern": str(reader_pull.get("cool_point_pattern") or ""),
    }
    return {
        "chapter": chapter,
        "task_brief": task_brief,
        "contract_v2": contract_v2,
        "draft_package": draft_package,
    }


def _build_context_draft_package_fallback(chapter: int, task_brief: Dict[str, Any], contract_v2: Dict[str, Any]) -> Dict[str, Any]:
    if DISABLE_CONTEXT_COMPRESSION:
        core_task_raw = str(task_brief.get("core_task") or "").strip()
        conflict_raw = str(task_brief.get("conflict") or "").strip()
        carry_raw = str(task_brief.get("carry_from_previous") or "").strip()
        opening_raw = str(task_brief.get("opening_suggestion") or "").strip()
        must_complete_raw = [str(item).strip() for item in (task_brief.get("must_complete") or []) if str(item).strip()]
        must_not_raw = [str(item).strip() for item in (task_brief.get("must_not") or []) if str(item).strip()]
        time_constraints_raw = [str(item).strip() for item in (task_brief.get("time_constraints") or []) if str(item).strip()]
        scene_constraints_raw = [str(item).strip() for item in (task_brief.get("scene_constraints") or []) if str(item).strip()]
        reading_power_raw = [str(item).strip() for item in (task_brief.get("reading_power") or []) if str(item).strip()]
        hook_type_raw = str(contract_v2.get("hook_type") or "").strip() or "危机钩"
        hook_strength_raw = str(contract_v2.get("hook_strength") or "").strip() or "中"
        unresolved_raw = str(contract_v2.get("unresolved_question") or "").strip()
        goal_raw = str(contract_v2.get("goal") or "").strip()
        obstacle_raw = str(contract_v2.get("obstacle") or "").strip()
        change_raw = str(contract_v2.get("change") or "").strip()
        micropayoffs_raw = [str(item).strip() for item in (contract_v2.get("micropayoffs") or []) if str(item).strip()]
        title_suggestion_raw = core_task_raw or goal_raw or f"第{chapter}章推进"
        beat_sheet_raw = [
            f"开场：{opening_raw or '冲突直切开场'}，承接{carry_raw or '上一章压力'}。",
            f"目标锁定：{goal_raw or core_task_raw or '明确本章主任务'}。",
            f"第一推进：围绕“{conflict_raw or obstacle_raw or '核心冲突'}”展开现场博弈。",
            "中段翻盘：把文本信息转成可验证事实，形成读者可感知的小兑现。",
            f"结果落点：{change_raw or '主角获得阶段性主动权'}。",
            f"章末钩子：{unresolved_raw or f'{hook_type_raw}（{hook_strength_raw}）'}",
        ]
        immutable_facts_raw = [
            f"章号固定：第{chapter}章。",
            f"核心任务：{core_task_raw or goal_raw or '完成主线推进'}。",
            f"核心冲突：{conflict_raw or obstacle_raw or '主角与对手正面冲突'}。",
        ]
        immutable_facts_raw.extend([f"时间限制：{item}" for item in time_constraints_raw])
        immutable_facts_raw.extend([f"场景限制：{item}" for item in scene_constraints_raw])
        immutable_facts_raw.extend([f"微兑现：{item}" for item in micropayoffs_raw])
        forbidden_raw = must_not_raw or ["禁止脱离本章主线去展开大支线。", "禁止无代价秒赢。"]
        checklist_raw = must_complete_raw + [f"追读点：{item}" for item in reading_power_raw]
        checklist_raw.append(f"章末钩子类型：{hook_type_raw}（强度：{hook_strength_raw}）")
        return {
            "title_suggestion": title_suggestion_raw,
            "beat_sheet": [item for item in beat_sheet_raw if str(item).strip()],
            "immutable_facts": [item for item in immutable_facts_raw if str(item).strip()],
            "forbidden": [item for item in forbidden_raw if str(item).strip()],
            "checklist": [item for item in checklist_raw if str(item).strip()],
            "target_words": 2200,
        }

    core_task = _clip_context_text(task_brief.get("core_task"), 96)
    conflict = _clip_context_text(task_brief.get("conflict"), 120)
    carry = _as_sentence_fragment(task_brief.get("carry_from_previous"), limit=80)
    opening = _as_sentence_fragment(task_brief.get("opening_suggestion"), limit=70)
    must_complete = _clip_context_list(task_brief.get("must_complete"), item_limit=8, text_limit=90)
    must_not = _clip_context_list(task_brief.get("must_not"), item_limit=8, text_limit=90)
    time_constraints = _clip_context_list(task_brief.get("time_constraints"), item_limit=4, text_limit=90)
    scene_constraints = _clip_context_list(task_brief.get("scene_constraints"), item_limit=4, text_limit=90)
    reading_power = _clip_context_list(task_brief.get("reading_power"), item_limit=4, text_limit=90)
    hook_type = _clip_context_text(contract_v2.get("hook_type"), 24) or "危机钩"
    hook_strength = _clip_context_text(contract_v2.get("hook_strength"), 16) or "中"
    unresolved = _clip_context_text(contract_v2.get("unresolved_question"), 100)
    goal = _clip_context_text(contract_v2.get("goal"), 100)
    obstacle = _clip_context_text(contract_v2.get("obstacle"), 100)
    change = _clip_context_text(contract_v2.get("change"), 100)
    micropayoffs = _clip_context_list(contract_v2.get("micropayoffs"), item_limit=4, text_limit=90)
    core_task_fragment = _as_sentence_fragment(core_task or goal or "完成主线推进", limit=100) or "完成主线推进"
    conflict_fragment = _as_sentence_fragment(conflict or obstacle or "主角与对手正面冲突", limit=100) or "主角与对手正面冲突"

    title_seed = _clip_context_text(core_task or goal or f"第{chapter}章推进", 20).replace("：", "").replace(":", "")
    title_suggestion = title_seed or f"第{chapter}章推进"

    beat_sheet = [
        f"开场：{opening or '冲突直切开场'}，承接{carry or '上一章压力'}。",
        f"目标锁定：{_as_sentence_fragment(goal or core_task or '明确本章主任务', limit=90)}。",
        f"第一推进：围绕“{_as_sentence_fragment(conflict or obstacle or '核心冲突', limit=32)}”展开现场博弈。",
        "中段翻盘：把文本信息转成可验证事实，形成读者可感知的小兑现。",
        f"结果落点：{_as_sentence_fragment(change or '主角获得阶段性主动权', limit=90)}。",
        f"章末钩子：{unresolved or f'{hook_type}（{hook_strength}）'}",
    ]

    immutable_facts = [
        f"章号固定：第{chapter}章。",
        f"核心任务：{core_task_fragment}。",
        f"核心冲突：{conflict_fragment}。",
    ]
    immutable_facts.extend([f"时间限制：{_as_sentence_fragment(item, limit=100) or item}" for item in time_constraints[:2]])
    immutable_facts.extend([f"场景限制：{_as_sentence_fragment(item, limit=100) or item}" for item in scene_constraints[:2]])
    immutable_facts.extend([f"微兑现：{_as_sentence_fragment(item, limit=100) or item}" for item in micropayoffs[:2]])

    forbidden = must_not[:6]
    if not forbidden:
        forbidden = ["禁止脱离本章主线去展开大支线。", "禁止无代价秒赢。"]

    checklist = must_complete[:8]
    checklist.extend([f"追读点：{item}" for item in reading_power[:2]])
    checklist.append(f"章末钩子类型：{hook_type}（强度：{hook_strength}）")
    checklist = [item for item in checklist if item.strip()]

    return {
        "title_suggestion": title_suggestion,
        "beat_sheet": beat_sheet[:8],
        "immutable_facts": immutable_facts[:10],
        "forbidden": forbidden[:8],
        "checklist": checklist[:10],
        "target_words": 2200,
    }


def _validate_context_segments(chapter: int, compact: Dict[str, Any], context_package: Dict[str, Any]) -> None:
    task_brief = context_package.get("task_brief") or {}
    contract_v2 = context_package.get("contract_v2") or {}
    draft_package = context_package.get("draft_package") or {}
    open_ids = {str(item.get("id") or "").strip() for item in compact.get("open_foreshadowing") or [] if str(item.get("id") or "").strip()}
    must_continue = (task_brief.get("foreshadowing_plan") or {}).get("must_continue") or []
    forbidden_resolve = set(str(item or "").strip() for item in ((task_brief.get("foreshadowing_plan") or {}).get("forbidden_resolve") or []) if str(item or "").strip())
    continued_ids = set()
    continued_contents = set()
    for item in must_continue:
        item_id = str(item.get("id") or "").strip()
        if item_id and open_ids and item_id not in open_ids:
            raise RuntimeError(f"context_foreshadow_plan 引用了不存在的伏笔 id: {item_id}")
        if item_id:
            continued_ids.add(item_id)
        content = str(item.get("content") or "").strip()
        if content:
            continued_contents.add(content)
    if forbidden_resolve & continued_ids:
        raise RuntimeError("foreshadowing_plan 的 forbidden_resolve 与 must_continue 冲突")
    if forbidden_resolve & continued_contents:
        raise RuntimeError("foreshadowing_plan 的 forbidden_resolve 与 must_continue.content 冲突")
    characters = task_brief.get("characters") or []
    if len(characters) > 8:
        raise RuntimeError(f"context_cast_constraints 角色数过多: {len(characters)} > 8")
    target_words = int(draft_package.get("target_words") or 0)
    if target_words < 1200 or target_words > 3200:
        raise RuntimeError(f"draft_package.target_words 超出允许范围: {target_words}")
    if compact.get("timeline_anchor_digest") and not (task_brief.get("time_constraints") or []):
        raise RuntimeError("context_cast_constraints 缺少 time_constraints，未接住时间锚点")
    if not (contract_v2.get("micropayoffs") or []):
        raise RuntimeError("context_reader_pull / contract_v2 缺少 micropayoffs")
    if int(context_package.get("chapter") or 0) != chapter:
        raise RuntimeError(f"context package chapter 不匹配: {context_package.get('chapter')} != {chapter}")


def _normalize_context_foreshadowing_plan(context_package: Dict[str, Any]) -> Dict[str, int]:
    task_brief = context_package.get("task_brief") or {}
    plan = task_brief.get("foreshadowing_plan")
    if not isinstance(plan, dict):
        return {"removed_conflicts": 0}
    must_continue = plan.get("must_continue")
    forbidden_resolve = plan.get("forbidden_resolve")
    if not isinstance(must_continue, list) or not isinstance(forbidden_resolve, list):
        return {"removed_conflicts": 0}

    continued_ids = set()
    continued_contents = set()
    for item in must_continue:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        content = str(item.get("content") or "").strip()
        if item_id:
            continued_ids.add(item_id)
        if content:
            continued_contents.add(content)

    removed = 0
    filtered: List[str] = []
    for raw in forbidden_resolve:
        text = str(raw or "").strip()
        if not text:
            continue
        if text in continued_ids or text in continued_contents:
            removed += 1
            continue
        if text in filtered:
            continue
        filtered.append(text)

    if removed:
        plan["forbidden_resolve"] = filtered
    return {"removed_conflicts": removed}


def _read_json_object(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_cached_context_package(
    *,
    chapter: int,
    compact: Dict[str, Any],
    artifact_dir: Path,
    allow_reuse: bool,
) -> Optional[tuple[Dict[str, Any], Path]]:
    if not allow_reuse:
        return None
    for path in (
        artifact_dir / "context_package.json",
        artifact_dir / "context_agent.json",
        artifact_dir / "context_agent.result.json",
    ):
        payload = _read_json_object(path)
        if not payload:
            continue
        required = {"chapter", "task_brief", "contract_v2", "draft_package"}
        if not required.issubset(payload.keys()):
            continue
        try:
            _validate_context_segments(chapter, compact, payload)
            _assert_payload_matches_schema(payload, _build_stage_schema_context())
        except Exception:
            continue
        return payload, path
    return None


def _run_context_segment(
    *,
    project_root: Path,
    chapter: int,
    stage_name: str,
    input_payload: Dict[str, Any],
    schema: Dict[str, Any],
    prompt_builder,
    artifact_dir: Path,
    codex_bin: Optional[str],
    key: str,
) -> Dict[str, Any]:
    _assert_context_input_budget(stage_name, input_payload)
    input_path = artifact_dir / f"{stage_name}.input.json"
    previous_input_payload = _read_json_object(input_path)
    write_json(input_path, input_payload)
    prompt = prompt_builder(chapter, input_payload)
    prompt_path = artifact_dir / f"{stage_name}.prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    stage_output_path = artifact_dir / f"{stage_name}.json"
    if previous_input_payload == input_payload:
        cached_payload = _read_json_object(stage_output_path)
        if cached_payload:
            try:
                cached_segment = _extract_context_segment(
                    cached_payload,
                    chapter=chapter,
                    key=key,
                    stage_name=stage_name,
                )
            except Exception:
                cached_segment = None
            if cached_segment is not None:
                display_name = _stage_display_name(stage_name)
                try:
                    update_step(project_root, "Step 1", note=f"{display_name} · 复用缓存")
                except Exception:
                    pass
                _emit_tui_line(f"{display_name} · 复用缓存")
                observe_write_event(
                    project_root,
                    stage_name,
                    attempt=0,
                    channel="workflow",
                    event="cache.hit",
                    message=f"{display_name} 命中缓存",
                )
                observe_context_stage_metric(
                    project_root,
                    stage_name,
                    chapter=chapter,
                    input_bytes=_json_size_bytes(input_payload),
                    schema_bytes=_json_size_bytes(schema),
                    prompt_bytes=len(prompt.encode("utf-8")),
                    success=True,
                    attempt=0,
                    elapsed_ms=0,
                    output_bytes=stage_output_path.stat().st_size if stage_output_path.is_file() else None,
                )
                return cached_segment
    payload = None
    error_text: Optional[str] = None
    try:
        payload = run_codex_json_stage(
            stage_name=stage_name,
            prompt=prompt,
            schema=schema,
            project_root=project_root,
            artifact_dir=artifact_dir,
            codex_bin=codex_bin,
            timeout_seconds=DEFAULT_CONTEXT_STAGE_TIMEOUT_SECONDS,
            retries=DEFAULT_CONTEXT_STAGE_RETRIES,
        )
        return _extract_context_segment(payload, chapter=chapter, key=key, stage_name=stage_name)
    except Exception as exc:
        error_text = str(exc)
        raise
    finally:
        execution_path = artifact_dir / f"{stage_name}.execution.json"
        execution_payload = {}
        if execution_path.is_file():
            try:
                execution_payload = json.loads(execution_path.read_text(encoding="utf-8"))
            except Exception:
                execution_payload = {}
        observe_context_stage_metric(
            project_root,
            stage_name,
            chapter=chapter,
            input_bytes=_json_size_bytes(input_payload),
            schema_bytes=_json_size_bytes(schema),
            prompt_bytes=prompt_path.stat().st_size if prompt_path.is_file() else len(prompt.encode("utf-8")),
            success=error_text is None,
            attempt=execution_payload.get("attempt") if isinstance(execution_payload, dict) else None,
            elapsed_ms=execution_payload.get("elapsed_ms") if isinstance(execution_payload, dict) else None,
            error=error_text or (execution_payload.get("error") if isinstance(execution_payload, dict) else None),
            output_bytes=stage_output_path.stat().st_size if stage_output_path.is_file() else None,
        )


def run_context_agent_stage(
    *,
    project_root: Path,
    chapter: int,
    materials: Dict[str, Any],
    artifact_dir: Path,
    codex_bin: Optional[str] = None,
) -> Dict[str, Any]:
    compact = _compact_context_materials(materials, chapter)
    compact_path = artifact_dir / "context.compact.json"
    previous_compact = _read_json_object(compact_path)
    write_json(compact_path, compact)
    compact_unchanged = previous_compact == compact
    context_package: Optional[Dict[str, Any]] = None
    try:
        cached_package = _load_cached_context_package(
            chapter=chapter,
            compact=compact,
            artifact_dir=artifact_dir,
            allow_reuse=bool(compact_unchanged),
        )
        if cached_package is not None:
            context_package, cached_path = cached_package
            _emit_tui_line(f"Context Agent · 复用缓存包: {cached_path.name}")
            observe_write_event(
                project_root,
                "context_agent",
                attempt=0,
                channel="workflow",
                event="cache.hit",
                message=f"Context Agent 命中缓存包: {cached_path.name}",
            )
            observe_context_stage_metric(
                project_root,
                "context_agent",
                chapter=chapter,
                input_bytes=_json_size_bytes(compact),
                schema_bytes=_json_size_bytes(_build_stage_schema_context()),
                prompt_bytes=0,
                success=True,
                attempt=0,
                elapsed_ms=0,
                output_bytes=(artifact_dir / "context_package.json").stat().st_size if (artifact_dir / "context_package.json").is_file() else None,
            )
            return context_package
        story_spine = _run_context_segment(
            project_root=project_root,
            chapter=chapter,
            stage_name="context_story_spine",
            input_payload=_build_context_story_spine_input(chapter, compact),
            schema=_build_stage_schema_context_story_spine(),
            prompt_builder=_build_context_story_spine_prompt,
            artifact_dir=artifact_dir,
            codex_bin=codex_bin,
            key="story_spine",
        )
        cast_constraints = _run_context_segment(
            project_root=project_root,
            chapter=chapter,
            stage_name="context_cast_constraints",
            input_payload=_build_context_cast_constraints_input(chapter, compact, story_spine),
            schema=_build_stage_schema_context_cast_constraints(),
            prompt_builder=_build_context_cast_constraints_prompt,
            artifact_dir=artifact_dir,
            codex_bin=codex_bin,
            key="cast_constraints",
        )
        foreshadow_plan = _run_context_segment(
            project_root=project_root,
            chapter=chapter,
            stage_name="context_foreshadow_plan",
            input_payload=_build_context_foreshadow_plan_input(chapter, compact, story_spine),
            schema=_build_stage_schema_context_foreshadow_plan(),
            prompt_builder=_build_context_foreshadow_plan_prompt,
            artifact_dir=artifact_dir,
            codex_bin=codex_bin,
            key="foreshadow_plan",
        )
        reader_pull = _run_context_segment(
            project_root=project_root,
            chapter=chapter,
            stage_name="context_reader_pull",
            input_payload=_build_context_reader_pull_input(chapter, compact, story_spine),
            schema=_build_stage_schema_context_reader_pull(),
            prompt_builder=_build_context_reader_pull_prompt,
            artifact_dir=artifact_dir,
            codex_bin=codex_bin,
            key="reader_pull",
        )
        contract_core = _run_context_segment(
            project_root=project_root,
            chapter=chapter,
            stage_name="context_contract_core",
            input_payload=_build_context_contract_core_input(chapter, story_spine, cast_constraints, reader_pull),
            schema=_build_stage_schema_context_contract_core(),
            prompt_builder=_build_context_contract_core_prompt,
            artifact_dir=artifact_dir,
            codex_bin=codex_bin,
            key="contract_core",
        )
        merged_without_draft = _merge_context_segments(
            chapter=chapter,
            story_spine=story_spine,
            cast_constraints=cast_constraints,
            foreshadow_plan=foreshadow_plan,
            reader_pull=reader_pull,
            contract_core=contract_core,
            draft_package={},
        )
        draft_input_payload = _build_context_draft_package_input(
            chapter,
            compact,
            merged_without_draft["task_brief"],
            merged_without_draft["contract_v2"],
        )
        write_json(artifact_dir / "context_draft_package.input.raw.json", draft_input_payload)
        if USE_MAIN_PROCESS_CONTEXT_DRAFT_PACKAGE:
            draft_prompt = _build_context_draft_package_prompt(chapter, draft_input_payload)
            strict_schema = _build_stage_schema_context_draft_package()
            write_json(artifact_dir / "context_draft_package.input.json", draft_input_payload)
            write_json(artifact_dir / "context_draft_package.schema.json", strict_schema)
            (artifact_dir / "context_draft_package.prompt.txt").write_text(draft_prompt, encoding="utf-8")
            started_at = time.time()
            draft_package = _build_context_draft_package_fallback(
                chapter,
                merged_without_draft["task_brief"],
                merged_without_draft["contract_v2"],
            )
            fallback_payload = {"chapter": chapter, "draft_package": draft_package}
            _assert_payload_matches_schema(fallback_payload, strict_schema)
            write_json(artifact_dir / "context_draft_package.json", fallback_payload)
            elapsed_ms = int((time.time() - started_at) * 1000)
            trace_summary = {
                "tool_counts": {
                    "read": 0,
                    "write": 0,
                    "bash": 0,
                    "assistant_message": 0,
                    "event": 0,
                },
                "workspace_reads": 0,
                "workspace_writes": 0,
                "events_captured": 0,
                "tools_seen": [],
            }
            (artifact_dir / "context_draft_package.stdout.log").write_text(
                "Context Agent / Draft Package main-process mode enabled; generated locally.\n",
                encoding="utf-8",
            )
            (artifact_dir / "context_draft_package.stderr.log").write_text("", encoding="utf-8")
            write_json(
                artifact_dir / "context_draft_package.trace.json",
                {
                    "stage": "context_draft_package",
                    "events": [],
                    "summary": trace_summary,
                    "source": "main_process",
                },
            )
            write_json(
                artifact_dir / "context_draft_package.execution.json",
                {
                    "stage": "context_draft_package",
                    "chapter": chapter,
                    "attempt": 0,
                    "success": True,
                    "source": "main_process",
                    "elapsed_ms": elapsed_ms,
                    "return_code": 0,
                    "turn_completed": True,
                    "sandbox_mode": "main-process",
                    "trace_summary": trace_summary,
                },
            )
            _emit_tui_line("Context Agent / Draft Package · 主进程生成完成")
            observe_write_event(
                project_root,
                "context_draft_package",
                attempt=0,
                channel="workflow",
                event="main_process.local",
                message="Context Agent / Draft Package generated in main process",
            )
            observe_context_stage_metric(
                project_root,
                "context_draft_package",
                chapter=chapter,
                input_bytes=_json_size_bytes(draft_input_payload),
                schema_bytes=_json_size_bytes(strict_schema),
                prompt_bytes=len(draft_prompt.encode("utf-8")),
                success=True,
                attempt=0,
                elapsed_ms=elapsed_ms,
                output_bytes=(artifact_dir / "context_draft_package.json").stat().st_size,
            )
        else:
            try:
                draft_package = _run_context_segment(
                    project_root=project_root,
                    chapter=chapter,
                    stage_name="context_draft_package",
                    input_payload=draft_input_payload,
                    schema=_build_stage_schema_context_draft_package_wire(),
                    prompt_builder=_build_context_draft_package_prompt,
                    artifact_dir=artifact_dir,
                    codex_bin=codex_bin,
                    key="draft_package",
                )
            except Exception as exc:
                if not _is_retryable_provider_error(str(exc)):
                    raise
                retry_error = exc
                if ENABLE_CONTEXT_DRAFT_COMPACT_RETRY and not DISABLE_CONTEXT_COMPRESSION:
                    compact_retry_payload = _build_context_draft_package_input(
                        chapter,
                        compact,
                        merged_without_draft["task_brief"],
                        merged_without_draft["contract_v2"],
                        compact_mode=True,
                    )
                    write_json(artifact_dir / "context_draft_package.input.compact.json", compact_retry_payload)
                    compact_bytes = _json_size_bytes(compact_retry_payload)
                    raw_bytes = _json_size_bytes(draft_input_payload)
                    if compact_bytes < raw_bytes:
                        _emit_tui_line(
                            f"Context Agent / Draft Package · provider 异常，切换紧凑输入重试（{raw_bytes} -> {compact_bytes} bytes）"
                        )
                        observe_write_event(
                            project_root,
                            "context_draft_package",
                            attempt=0,
                            channel="workflow",
                            event="retry.compact_input",
                            message=f"Context Agent / Draft Package compact retry {raw_bytes}->{compact_bytes} bytes",
                        )
                        try:
                            draft_package = _run_context_segment(
                                project_root=project_root,
                                chapter=chapter,
                                stage_name="context_draft_package",
                                input_payload=compact_retry_payload,
                                schema=_build_stage_schema_context_draft_package_wire(),
                                prompt_builder=_build_context_draft_package_prompt,
                                artifact_dir=artifact_dir,
                                codex_bin=codex_bin,
                                key="draft_package",
                            )
                            retry_error = None
                        except Exception as compact_exc:
                            if not _is_retryable_provider_error(str(compact_exc)):
                                raise
                            retry_error = compact_exc
                if retry_error is None:
                    pass
                else:
                    draft_package = _build_context_draft_package_fallback(
                        chapter,
                        merged_without_draft["task_brief"],
                        merged_without_draft["contract_v2"],
                    )
                    fallback_payload = {"chapter": chapter, "draft_package": draft_package}
                    _assert_payload_matches_schema(fallback_payload, _build_stage_schema_context_draft_package())
                    write_json(artifact_dir / "context_draft_package.json", fallback_payload)
                    write_json(
                        artifact_dir / "context_draft_package.fallback.json",
                        {
                            "chapter": chapter,
                            "reason": str(retry_error),
                            "input_bytes": _json_size_bytes(draft_input_payload),
                            "source": "local_fallback",
                        },
                    )
                    _emit_tui_line("Context Agent / Draft Package · provider 异常，已切换本地 fallback")
                    observe_write_event(
                        project_root,
                        "context_draft_package",
                        attempt=0,
                        channel="workflow",
                        event="fallback.local",
                        message=f"Context Agent / Draft Package fallback: {_trim_progress_note(str(retry_error), limit=180)}",
                    )
                    observe_context_stage_metric(
                        project_root,
                        "context_draft_package",
                        chapter=chapter,
                        input_bytes=_json_size_bytes(draft_input_payload),
                        schema_bytes=_json_size_bytes(_build_stage_schema_context_draft_package()),
                        prompt_bytes=len(_build_context_draft_package_prompt(chapter, draft_input_payload).encode("utf-8")),
                        success=True,
                        attempt=0,
                        elapsed_ms=0,
                        error="provider_retryable_fallback",
                        output_bytes=(artifact_dir / "context_draft_package.json").stat().st_size,
                    )
        try:
            _assert_payload_matches_schema(
                {"chapter": chapter, "draft_package": draft_package},
                _build_stage_schema_context_draft_package(),
            )
        except Exception as shape_exc:
            draft_package = _build_context_draft_package_fallback(
                chapter,
                merged_without_draft["task_brief"],
                merged_without_draft["contract_v2"],
            )
            fallback_payload = {"chapter": chapter, "draft_package": draft_package}
            _assert_payload_matches_schema(fallback_payload, _build_stage_schema_context_draft_package())
            write_json(artifact_dir / "context_draft_package.json", fallback_payload)
            write_json(
                artifact_dir / "context_draft_package.fallback.json",
                {
                    "chapter": chapter,
                    "reason": f"invalid_draft_package_shape: {shape_exc}",
                    "input_bytes": _json_size_bytes(draft_input_payload),
                    "source": "local_fallback_invalid_output",
                },
            )
            _emit_tui_line("Context Agent / Draft Package · 输出字段不完整，已切换本地 fallback")
            observe_write_event(
                project_root,
                "context_draft_package",
                attempt=0,
                channel="workflow",
                event="fallback.invalid_output",
                message=f"Context Agent / Draft Package invalid output fallback: {_trim_progress_note(str(shape_exc), limit=180)}",
            )
        context_package = _merge_context_segments(
            chapter=chapter,
            story_spine=story_spine,
            cast_constraints=cast_constraints,
            foreshadow_plan=foreshadow_plan,
            reader_pull=reader_pull,
            contract_core=contract_core,
            draft_package=draft_package,
        )
        normalization = _normalize_context_foreshadowing_plan(context_package)
        removed_conflicts = int(normalization.get("removed_conflicts") or 0)
        if removed_conflicts > 0:
            _emit_tui_line(f"Context Agent · 自动修复 foreshadowing 冲突 {removed_conflicts} 项")
            observe_write_event(
                project_root,
                "context_agent",
                attempt=0,
                channel="workflow",
                event="normalize.foreshadowing",
                message=f"Context Agent normalized foreshadowing conflicts: {removed_conflicts}",
            )
        _validate_context_segments(chapter, compact, context_package)
        _assert_payload_matches_schema(context_package, _build_stage_schema_context())
        return context_package
    finally:
        _write_context_agent_compat_artifacts(artifact_dir, context_package=context_package)


def _build_context_prompt(chapter: int, materials: Dict[str, Any]) -> str:
    compact = _compact_context_materials(materials, chapter)
    return _build_context_story_spine_prompt(chapter, _build_context_story_spine_input(chapter, compact))


def _write_context_agent_compat_artifacts(artifact_dir: Path, context_package: Optional[Dict[str, Any]] = None) -> None:
    prompt_sections: List[str] = []
    stdout_sections: List[str] = []
    stderr_sections: List[str] = []
    trace_segments: List[Dict[str, Any]] = []
    execution_segments: List[Dict[str, Any]] = []

    for stage_name in CONTEXT_AGENT_SEGMENTS:
        prompt_path = artifact_dir / f"{stage_name}.prompt.txt"
        stdout_path = artifact_dir / f"{stage_name}.stdout.log"
        stderr_path = artifact_dir / f"{stage_name}.stderr.log"
        trace_path = artifact_dir / f"{stage_name}.trace.json"
        execution_path = artifact_dir / f"{stage_name}.execution.json"

        if prompt_path.is_file():
            prompt_sections.append(f"===== {stage_name} =====\n{prompt_path.read_text(encoding='utf-8')}")
        if stdout_path.is_file():
            stdout_sections.append(f"===== {stage_name} =====\n{stdout_path.read_text(encoding='utf-8')}")
        if stderr_path.is_file():
            stderr_sections.append(f"===== {stage_name} =====\n{stderr_path.read_text(encoding='utf-8')}")
        if trace_path.is_file():
            try:
                payload = json.loads(trace_path.read_text(encoding='utf-8'))
            except Exception:
                payload = {"stage": stage_name, "path": str(trace_path)}
            trace_segments.append(payload)
        if execution_path.is_file():
            try:
                payload = json.loads(execution_path.read_text(encoding='utf-8'))
            except Exception:
                payload = {"stage": stage_name, "path": str(execution_path)}
            execution_segments.append(payload)

    (artifact_dir / "context_agent.prompt.txt").write_text("\n\n".join(prompt_sections), encoding='utf-8')
    (artifact_dir / "context_agent.stdout.log").write_text("\n\n".join(stdout_sections), encoding='utf-8')
    (artifact_dir / "context_agent.stderr.log").write_text("\n\n".join(stderr_sections), encoding='utf-8')
    write_json(artifact_dir / "context_agent.schema.json", _build_stage_schema_context())
    write_json(
        artifact_dir / "context_agent.trace.json",
        {"stage": "context_agent", "segmented": True, "segments": trace_segments},
    )
    write_json(
        artifact_dir / "context_agent.execution.json",
        {"stage": "context_agent", "segmented": True, "segments": execution_segments, "context_package_built": bool(context_package)},
    )
    if context_package is not None:
        write_json(artifact_dir / "context_agent.json", context_package)


def _build_draft_prompt(chapter: int, context_package: Dict[str, Any], mode: str, chapter_file: str) -> str:
    return f"""你是 webnovel-writer 的 `writer-draft` 子流程。

目标：基于创作执行包完成第 {chapter} 章正文草稿。

执行方式：
- 你当前运行在可写工作区，必须直接写章节文件：`{chapter_file}`
- 不允许只把正文写进 JSON 而不落文件；程序会校验章节文件确实被你改过
- 返回 JSON 前，必须以章节文件里的最终正文为准，确认 `title/content` 与文件完全一致
- 允许边写边回读再修，但最终交付必须是文件与 JSON 双一致

硬规则：
- 只基于给定执行包写作
- 大纲即法律，设定即物理
- 默认目标字数以 draft_package.target_words 为准
- 输出 JSON，title 单独返回，content 只返回正文，不要包含章标题行
- 正文只写本章内容，不要附加摘要、统计、解释、作者注

模式：{mode}

核心约束摘要：
- 大纲即法律，设定即物理
- 只写本章正文，不写摘要/统计/解释
- 章首尽快进入冲突或风险
- 章末必须保留未闭合问题、异常、选择或威胁
- 必须执行 `task_brief.foreshadowing_plan`：
  - must_continue 的伏笔要在正文里有可见承接或加压
  - planned_new 的伏笔要有明确落点，不能只在章末总结里出现
  - forbidden_resolve 列出的内容禁止在本章解释透或提前兑现
- 保持网文短段落与行动驱动表达

【创作执行包】
{json.dumps(context_package, ensure_ascii=False, indent=2)}
"""


def _build_style_prompt(chapter: int, title: str, chapter_file: str, chapter_text: str, context_package: Dict[str, Any]) -> str:
    return f"""你是 webnovel-writer 的 `style-adapter` 子流程。

目标：只做表达层转译，把第 {chapter} 章修成更接近网文连载的自然表达。

执行方式：
- 你当前运行在可写工作区，必须直接修改章节文件：`{chapter_file}`
- 不能只在脑内修完再一次性吐 JSON；每一轮都要以文件里的最新正文为准
- 程序会校验章节文件确实发生变化，且 `content` 与文件最终正文完全一致
- 如果你在 Pass B 又发现问题，继续在文件上改，不要停在口头说明

你必须按“两遍处理”完成，不允许只改一轮就交稿：
1. Pass A：局部风格转译。重点拆长句、去总结腔、把抽象句改成动作/反应/代价，不改剧情事实。
2. Pass B：先完整重读 `章节文件` 当前版本，再检查是否还有残余的模板腔、重复解释、钩子疲软、段落压读问题；如果发现，再继续修。

硬规则：
- 不改剧情事实，不改事件顺序，不改角色行为结果，不改设定规则
- content 只返回正文，不要返回章标题行
- 允许压缩说明腔、模板腔、机械腔，但禁止新发明剧情

风格约束摘要：
- 少解释，多动作、对白、反应
- 避免模板腔、总结腔、说明书对白
- 保持移动端友好段落
- 尽量让关键情绪落在具体动作和感官上

输出要求：
- 只输出 JSON
- `content` 返回最终正文
- `change_summary` 汇总所有实质改动
- `pass_reports` 必须至少包含两轮：
  - Pass A：`full_reread=false`
  - Pass B：`full_reread=true`
- `full_reread_count` 必须 >= 1
- 每个 `pass_reports` 项至少包含：`pass_id` / `focus` / `full_reread` / `applied_changes`
- 如果 Pass B 重读后认为某些表达应保留，可写到 `retained`

【当前标题】
{title}

【创作执行包】
{json.dumps(context_package, ensure_ascii=False, indent=2)}

【当前正文】
{chapter_text}
"""


def _build_polish_prompt(chapter: int, title: str, chapter_file: str, chapter_text: str, review_payload: Dict[str, Any]) -> str:
    return f"""你是 webnovel-writer 的 `polish-agent` 子流程。

目标：根据审查结果修第 {chapter} 章，并执行 Anti-AI 终检。

执行方式：
- 你当前运行在可写工作区，必须直接修改章节文件：`{chapter_file}`
- 不能只改 issue 列表里的局部几句就结束；每一轮都要基于文件当前全文继续判断
- 程序会校验章节文件确实发生变化，且 `content` 与文件最终正文完全一致
- 如果 Pass B / Pass C 复读后又发现问题，继续在文件上修，不要只在报告里写“已检查”

你必须按“三遍处理”完成，不允许只做一轮局部修补：
1. Pass A：先修 review issues。先 `critical/high`，再处理中低优先级里收益最高的问题。
2. Pass B：先完整重读 `章节文件` 当前版本，再做 Anti-AI 全文扫描；如果发现残余抽象句、模板句、机械结论句，继续修。
3. Pass C：再次完整重读 `章节文件` 当前版本，执行 No-Poison 与 typesetting 全局检查；如果发现局部修补破坏了节奏、连贯或章末压力，继续修到干净为止。

输出要求：
- 只输出 JSON
- content 只返回修订后的正文，不要返回章标题行
- change_summary: 列出本次真正修改了什么
- deviation: 列出没有改或保留的点
- anti_ai_force_check: 只能是 pass/fail
- retained: 可选，列出刻意保留的表达
- pass_reports: 必须记录三轮处理结果
- full_reread_count: 必须 >= 2（Pass B / Pass C 都必须全章重读）

终检摘要：
- critical 必修
- high 优先修，无法修则 deviation 说明原因
- 中低优先级按收益处理
- Anti-AI：把抽象判断句改成动作/反应/代价表达
- Typesetting：短段落、少连续长句、少模板总结句
- No-Poison：至少显式判断降智推进 / 强行误会 / 圣母无代价 / 工具人配角 / 双标裁决

`pass_reports` 的最小结构：
- Pass A：`full_reread=false`，focus 填“review issues 修复”
- Pass B：`full_reread=true`，checks 至少包含 `anti_ai`
- Pass C：`full_reread=true`，checks 至少包含 `no_poison` 和 `typesetting`
- 每个 pass 至少列出 `applied_changes`

【当前标题】
{title}

【当前正文】
{chapter_text}

【审查结果】
{json.dumps(review_payload, ensure_ascii=False, indent=2)}
"""


def _build_data_prompt(
    chapter: int,
    title: str,
    chapter_text: str,
    review_payload: Dict[str, Any],
    context_package: Dict[str, Any],
    materials: Dict[str, Any],
) -> str:
    return f"""你是 webnovel-writer 的 `data-agent`。

目标：从第 {chapter} 章正文抽取结构化信息，保证 Data Layer 闭环。

必须遵守：
1. 发明需识别：新角色/新地点/新势力必须进入 entities_new 或 entities_appeared
2. 不能伪造不存在的实体和关系
3. chapter_meta 必须能支撑后续 Context Agent 继续写下一章
4. summary_text / bridge_line / scenes 必须让 RAG 和 dashboard 可用

额外输出要求：
- entities_appeared 每项至少包含：id, type, mentions, confidence
- entities_new 每项至少包含：suggested_id, name, type, tier
- state_changes 每项至少包含：entity_id, field, new（可选 old, reason）
- relationships_new 每项至少包含：from, to, type
- uncertain 每项至少包含：mention, candidates[{type,id}], confidence
- scenes 中每个场景都至少包含：index, scene_index, summary, content
- `content` 是该场景的正文摘录，不是标签
- summary_text 为 100-180 字中文摘要
- 不要把“本章总结”伪装成伏笔；伏笔必须对应正文里真实存在的异常、秘密、风险或未兑现承诺
- foreshadowing_planted / foreshadowing_continued / foreshadowing_resolved 必须对照 `创作执行包.task_brief.foreshadowing_plan` 填写
- foreshadowing_notes 只做摘要展示，必须从上述三类结构化伏笔衍生，不允许空泛凑数
- bridge_line 给出下章承接点
- chapter_meta 至少包含：
  - title
  - hook
  - hook_type
  - hook_strength
  - unresolved_question
  - ending_state
  - dominant_strand
  - summary
  - foreshadowing_planted
  - foreshadowing_continued
  - foreshadowing_resolved

数据链约束摘要：
- 新实体要进入 entities_new，已有实体出场要进入 entities_appeared
- 关系变化必须写 relationships_new
- chapter_meta 要能支撑下一章 Context Agent
- scenes 要能直接给 RAG 和 style sampler 使用
- 不确定项进入 uncertain，不能胡乱强判

【标题】
{title}

【正文】
{chapter_text}

【审查结果】
{json.dumps(review_payload, ensure_ascii=False, indent=2)}

【创作执行包】
{json.dumps(context_package, ensure_ascii=False, indent=2)}

【辅助上下文】
{json.dumps({
    "core_entities": materials.get("core_entities"),
    "recent_appearances": materials.get("recent_appearances"),
    "state_progress": (materials.get("state") or {}).get("progress"),
}, ensure_ascii=False, indent=2)}
    """


def _validate_revision_stage_payload(
    payload: Dict[str, Any],
    *,
    label: str,
    min_pass_reports: int,
    min_full_rereads: int,
) -> None:
    pass_reports = payload.get("pass_reports")
    if not isinstance(pass_reports, list) or len(pass_reports) < min_pass_reports:
        raise RuntimeError(f"{label} 缺少足够的 pass_reports，至少需要 {min_pass_reports} 轮")
    declared_rereads = int(payload.get("full_reread_count") or 0)
    actual_rereads = 0
    anti_ai_checked = False
    no_poison_checked = False
    typesetting_checked = False
    meaningful_change_report_count = 0
    for index, report in enumerate(pass_reports, start=1):
        if not isinstance(report, dict):
            raise RuntimeError(f"{label} 第 {index} 个 pass_reports 不是对象")
        for field in ("pass_id", "focus", "applied_changes"):
            if field not in report:
                raise RuntimeError(f"{label} 第 {index} 个 pass_reports 缺少字段: {field}")
        applied_changes = report.get("applied_changes")
        if not isinstance(applied_changes, list) or not any(str(item).strip() for item in applied_changes):
            raise RuntimeError(f"{label} 第 {index} 个 pass_reports.applied_changes 不能为空")
        meaningful_change_report_count += 1
        if bool(report.get("full_reread")):
            actual_rereads += 1
        checks = {str(item).strip() for item in (report.get("checks") or []) if str(item).strip()}
        anti_ai_checked = anti_ai_checked or ("anti_ai" in checks)
        no_poison_checked = no_poison_checked or ("no_poison" in checks)
        typesetting_checked = typesetting_checked or ("typesetting" in checks)
    if declared_rereads < min_full_rereads:
        raise RuntimeError(f"{label} full_reread_count={declared_rereads}，低于要求 {min_full_rereads}")
    if actual_rereads < min_full_rereads:
        raise RuntimeError(f"{label} 实际 full_reread pass 数量不足，至少需要 {min_full_rereads} 轮")
    if meaningful_change_report_count < min_pass_reports:
        raise RuntimeError(f"{label} pass_reports 缺少真实改动记录")
    if label.startswith("polish"):
        if not anti_ai_checked:
            raise RuntimeError(f"{label} 缺少 Anti-AI 全文检查记录")
        if not no_poison_checked:
            raise RuntimeError(f"{label} 缺少 No-Poison 全文检查记录")
        if not typesetting_checked:
            raise RuntimeError(f"{label} 缺少排版终检记录")


def _run_review_cli(project_root: Path, chapter: int, chapter_file: Path, mode: str) -> Dict[str, Any]:
    command = [
        sys.executable,
        str(REVIEW_RUNNER),
        "--project-root",
        str(project_root),
        "--chapter",
        str(chapter),
        "--chapter-file",
        str(chapter_file),
        "--mode",
        mode,
    ]
    proc = _run_command(command, timeout=DEFAULT_STAGE_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or "review runner 失败")
    payload = _parse_cli_json_payload(proc.stdout)
    return payload


def _write_summary_file(project_root: Path, chapter: int, data_payload: Dict[str, Any]) -> Path:
    summary_path = project_root / ".webnovel" / "summaries" / f"ch{chapter:04d}.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(_summary_markdown(chapter, data_payload), encoding="utf-8")
    return summary_path


def _apply_data_payload(project_root: Path, chapter: int, data_payload: Dict[str, Any], artifact_dir: Path, *, enable_debt_interest: bool) -> Dict[str, Any]:
    stage_times: Dict[str, int] = {}

    state_payload_path = artifact_dir / "data_agent.payload.json"
    write_json(state_payload_path, data_payload)

    started = time.perf_counter()
    proc = _run_webnovel(project_root, "state", "process-chapter", "--chapter", str(chapter), "--data", f"@{state_payload_path}")
    stage_times["state_process_chapter"] = int((time.perf_counter() - started) * 1000)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or "state process-chapter 失败")
    state_result = _parse_cli_json_payload(proc.stdout)

    summary_path = _write_summary_file(project_root, chapter, data_payload)

    scenes = data_payload.get("scenes") or []
    scene_payload = []
    for item in scenes:
        if not isinstance(item, dict):
            continue
        scene_index = int(item.get("scene_index") or item.get("index") or 0)
        if scene_index <= 0:
            continue
        scene_payload.append(
            {
                "chapter": chapter,
                "scene_index": scene_index,
                "index": scene_index,
                "summary": str(item.get("summary") or "").strip(),
                "content": str(item.get("content") or "").strip(),
                "location": str(item.get("location") or "").strip(),
                "characters": item.get("characters") or [],
            }
        )

    chapter_file = find_chapter_file(project_root, chapter)
    started = time.perf_counter()
    sync_proc = _run_webnovel(project_root, "sync-chapter-data", "--chapter", str(chapter))
    stage_times["sync_chapter_data"] = int((time.perf_counter() - started) * 1000)
    if sync_proc.returncode != 0:
        detail = (sync_proc.stderr or sync_proc.stdout or "").strip()
        raise RuntimeError(detail or "sync-chapter-data 失败")
    sync_result = _parse_cli_json_payload(sync_proc.stdout)

    started = time.perf_counter()
    rag_args = [
        "rag",
        "index-chapter",
        "--chapter",
        str(chapter),
    ]
    if chapter_file:
        rag_args.extend(["--chapter-file", str(chapter_file.relative_to(project_root))])
    rag_args.extend(
        [
            "--scenes",
            json.dumps(scene_payload, ensure_ascii=False),
            "--summary",
            str(data_payload.get("summary_text") or ""),
        ]
    )
    rag_proc = _run_webnovel(project_root, *rag_args)
    stage_times["rag_index_chapter"] = int((time.perf_counter() - started) * 1000)
    if rag_proc.returncode != 0:
        detail = (rag_proc.stderr or rag_proc.stdout or "").strip()
        raise RuntimeError(detail or "rag index-chapter 失败")
    rag_result = _parse_cli_json_payload(rag_proc.stdout)

    review_score = float(data_payload.get("review_score") or 0.0)
    style_result: Dict[str, Any] = {"skipped": True}
    if review_score >= 80 and scene_payload:
        started = time.perf_counter()
        style_proc = _run_webnovel(
            project_root,
            "style",
            "extract",
            "--chapter",
            str(chapter),
            "--score",
            str(review_score),
            "--scenes",
            json.dumps(scene_payload, ensure_ascii=False),
        )
        stage_times["style_extract"] = int((time.perf_counter() - started) * 1000)
        if style_proc.returncode != 0:
            detail = (style_proc.stderr or style_proc.stdout or "").strip()
            raise RuntimeError(detail or "style extract 失败")
        style_result = _parse_cli_json_payload(style_proc.stdout)
    else:
        stage_times["style_extract"] = 0

    final_stats = _chapter_stats(project_root)
    update_args = [
        "update-state",
        "--",
        "--progress",
        str(chapter),
        str(final_stats.get("total_chars", 0)),
    ]
    dominant_strand = str((data_payload.get("chapter_meta") or {}).get("dominant_strand") or "").strip()
    if dominant_strand:
        update_args.extend(["--strand-dominant", dominant_strand, str(chapter)])
    started = time.perf_counter()
    update_proc = _run_webnovel(project_root, *update_args)
    stage_times["update_state_progress"] = int((time.perf_counter() - started) * 1000)
    if update_proc.returncode != 0:
        detail = (update_proc.stderr or update_proc.stdout or "").strip()
        raise RuntimeError(detail or "update-state progress 失败")

    debt_result: Dict[str, Any] = {"skipped": True}
    if enable_debt_interest:
        started = time.perf_counter()
        debt_proc = _run_webnovel(project_root, "index", "accrue-interest", "--current-chapter", str(chapter))
        stage_times["debt_interest"] = int((time.perf_counter() - started) * 1000)
        if debt_proc.returncode != 0:
            detail = (debt_proc.stderr or debt_proc.stdout or "").strip()
            raise RuntimeError(detail or "debt accrue-interest 失败")
        debt_result = _parse_cli_json_payload(debt_proc.stdout)
    else:
        stage_times["debt_interest"] = 0

    stage_times["TOTAL"] = sum(stage_times.values())
    observe_data_agent(
        project_root,
        chapter=chapter,
        timing_ms=stage_times,
        success=True,
        warnings=list(data_payload.get("warnings") or []),
    )

    return {
        "state": state_result,
        "sync": sync_result,
        "rag": rag_result,
        "style": style_result,
        "update_state": {
            "progress": final_stats.get("total_chars", 0),
            "dominant_strand": dominant_strand,
        },
        "debt": debt_result,
        "summary_file": str(summary_path),
        "timing_ms": stage_times,
    }


def _review_mode_for_pipeline(mode: str) -> str:
    return "minimal" if mode == "minimal" else "full"


def _write_final_files(project_root: Path, chapter: int, title: str, content: str) -> Path:
    chapter_path = default_chapter_draft_path(project_root, chapter, use_volume_layout=True)
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text(_compose_chapter_file(chapter, title, content), encoding="utf-8")
    return chapter_path


def _build_result(
    *,
    project_root: Path,
    chapter: int,
    chapter_file: Path,
    summary_file: Path,
    review_payload: Dict[str, Any],
    final_stats: Dict[str, int],
    style_payload: Dict[str, Any],
    polish_payload: Dict[str, Any],
    data_result: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "status": "ok",
        "topology": "upstream-webnovel-write",
        "project_root": str(project_root),
        "chapter": chapter,
        "chapter_file": str(chapter_file),
        "summary_file": str(summary_file),
        "overall_score": review_payload.get("overall_score"),
        "severity_counts": review_payload.get("severity_counts", {}),
        "report_file": str(review_payload.get("report_file", "")),
        "aggregate_file": str(review_payload.get("aggregate_file", "")),
        "style_change_summary": style_payload.get("change_summary", []),
        "style_pass_reports": style_payload.get("pass_reports", []),
        "style_full_reread_count": style_payload.get("full_reread_count", 0),
        "anti_ai_force_check": polish_payload.get("anti_ai_force_check"),
        "change_summary": polish_payload.get("change_summary", []),
        "deviation": polish_payload.get("deviation", []),
        "polish_pass_reports": polish_payload.get("pass_reports", []),
        "polish_full_reread_count": polish_payload.get("full_reread_count", 0),
        "progress": {
            "current_chapter": chapter,
            "total_chars": final_stats.get("total_chars", 0),
        },
        "data_agent_timing_ms": (data_result.get("timing_ms") or {}),
    }


def run_write_workflow(
    *,
    project_root: Path,
    chapter: int,
    mode: str = "standard",
    codex_bin: Optional[str] = None,
    enable_debt_interest: bool = False,
) -> Dict[str, Any]:
    project_root = resolve_project_root(str(project_root))
    state = _load_state(project_root)
    if not (project_root / "大纲" / "总纲.md").is_file():
        raise FileNotFoundError(f"缺少总纲文件: {project_root / '大纲' / '总纲.md'}")
    if not SCRIPTS_DIR.joinpath("extract_chapter_context.py").is_file():
        raise FileNotFoundError(f"缺少脚本: {SCRIPTS_DIR / 'extract_chapter_context.py'}")

    artifact_dir = chapter_artifact_dir(project_root, chapter)
    start_task(project_root, chapter)
    _emit_tui_line(f"▶ webnovel-write 第 {chapter} 章 · mode={mode}")

    start_step(project_root, "Step 1", "Context Agent")
    _emit_step_banner("Step 1", "Context Agent", status="start")
    materials = _load_context_materials(project_root, chapter)
    write_json(artifact_dir / "context.materials.json", materials)
    context_started = time.perf_counter()
    context_package = run_context_agent_stage(
        project_root=project_root,
        chapter=chapter,
        materials=materials,
        artifact_dir=artifact_dir,
        codex_bin=codex_bin,
    )
    observe_write(
        project_root,
        "context_agent_total",
        success=True,
        elapsed_ms=int((time.perf_counter() - context_started) * 1000),
        details={"chapter": chapter},
    )
    write_json(artifact_dir / "context_package.json", context_package)
    complete_step(project_root, "Step 1", {"context_package": str((artifact_dir / 'context_package.json').relative_to(project_root))})
    _emit_step_banner("Step 1", "Context Agent", status="done")

    start_step(project_root, "Step 2A", "正文起草")
    _emit_step_banner("Step 2A", "正文起草", status="start")
    draft_title_hint = str(context_package.get("draft_package", {}).get("title_suggestion") or f"第{chapter}章").strip()
    chapter_path = default_chapter_draft_path(project_root, chapter, use_volume_layout=True)
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    if not chapter_path.exists():
        chapter_path.write_text(_compose_chapter_file(chapter, draft_title_hint, ""), encoding="utf-8")
    draft_payload = run_codex_json_stage(
        stage_name="draft",
        prompt=_build_draft_prompt(chapter, context_package, mode, str(chapter_path.relative_to(project_root))),
        schema=_build_stage_schema_draft(),
        project_root=project_root,
        artifact_dir=artifact_dir,
        codex_bin=codex_bin,
        sandbox_mode="workspace-write",
        chapter=chapter,
        workspace_file=chapter_path,
        expected_title=draft_title_hint,
        require_workspace_mutation=True,
    )
    title = str(draft_payload.get("title") or draft_title_hint).strip()
    chapter_path = _write_final_files(project_root, chapter, title, str(draft_payload.get("content") or ""))
    complete_step(
        project_root,
        "Step 2A",
        {
            "chapter_file": str(chapter_path.relative_to(project_root)),
            "chars": len(chapter_path.read_text(encoding="utf-8")),
            "execution_file": str((artifact_dir / "draft.execution.json").relative_to(project_root)),
            "trace_file": str((artifact_dir / "draft.trace.json").relative_to(project_root)),
        },
    )
    _emit_step_banner("Step 2A", "正文起草", status="done")

    current_content = read_text(chapter_path)
    style_payload: Dict[str, Any] = {
        "content": current_content,
        "change_summary": [],
        "pass_reports": [],
        "full_reread_count": 0,
    }
    if mode == "standard":
        start_step(project_root, "Step 2B", "风格适配")
        _emit_step_banner("Step 2B", "风格适配", status="start")
        style_payload = run_codex_json_stage(
            stage_name="style_adapter",
            prompt=_build_style_prompt(
                chapter,
                title,
                str(chapter_path.relative_to(project_root)),
                current_content,
                context_package,
            ),
            schema=_build_stage_schema_style(),
            project_root=project_root,
            artifact_dir=artifact_dir,
            codex_bin=codex_bin,
            sandbox_mode="workspace-write",
            chapter=chapter,
            workspace_file=chapter_path,
            expected_title=title,
        )
        _validate_revision_stage_payload(
            style_payload,
            label="style_adapter.result.json",
            min_pass_reports=2,
            min_full_rereads=1,
        )
        chapter_path = _write_final_files(project_root, chapter, title, str(style_payload.get("content") or current_content))
        current_content = read_text(chapter_path)
        complete_step(
            project_root,
            "Step 2B",
            {
                "chapter_file": str(chapter_path.relative_to(project_root)),
                "styled": True,
                "change_summary": style_payload.get("change_summary", []),
                "full_reread_count": style_payload.get("full_reread_count", 0),
                "execution_file": str((artifact_dir / "style_adapter.execution.json").relative_to(project_root)),
                "trace_file": str((artifact_dir / "style_adapter.trace.json").relative_to(project_root)),
            },
        )
        _emit_step_banner("Step 2B", "风格适配", status="done")
    else:
        start_step(project_root, "Step 2B", "风格适配")
        complete_step(project_root, "Step 2B", {"skipped": True, "mode": mode})
        _emit_step_banner("Step 2B", "风格适配", status="skip")

    start_step(project_root, "Step 3", "审查")
    _emit_step_banner("Step 3", "审查", status="start")
    initial_review = _run_review_cli(project_root, chapter, chapter_path, _review_mode_for_pipeline(mode))
    write_json(artifact_dir / "review_initial.json", initial_review)
    complete_step(
        project_root,
        "Step 3",
        {
            "overall_score": initial_review.get("overall_score"),
            "report_file": initial_review.get("report_file"),
            "aggregate_file": initial_review.get("aggregate_file"),
        },
    )
    _emit_step_banner("Step 3", "审查", status="done")

    start_step(project_root, "Step 4", "润色")
    _emit_step_banner("Step 4", "润色", status="start")
    polish_payload = run_codex_json_stage(
        stage_name="polish",
        prompt=_build_polish_prompt(
            chapter,
            title,
            str(chapter_path.relative_to(project_root)),
            current_content,
            initial_review,
        ),
        schema=_build_stage_schema_polish(),
        project_root=project_root,
        artifact_dir=artifact_dir,
        codex_bin=codex_bin,
        sandbox_mode="workspace-write",
        chapter=chapter,
        workspace_file=chapter_path,
        expected_title=title,
    )
    _validate_revision_stage_payload(
        polish_payload,
        label="polish.result.json",
        min_pass_reports=3,
        min_full_rereads=2,
    )
    if str(polish_payload.get("anti_ai_force_check") or "") != "pass":
        raise RuntimeError("Step 4 Anti-AI 终检失败，停止进入 Step 5")
    chapter_path = _write_final_files(project_root, chapter, title, str(polish_payload.get("content") or current_content))
    current_content = read_text(chapter_path)

    final_review = _run_review_cli(project_root, chapter, chapter_path, _review_mode_for_pipeline(mode))
    write_json(artifact_dir / "review_final.json", final_review)
    severity_counts = final_review.get("severity_counts") or {}
    critical_count = int(severity_counts.get("critical", 0) or 0)
    high_count = int(severity_counts.get("high", 0) or 0)
    if critical_count > 0:
        raise RuntimeError(f"Step 4 后仍存在 critical 问题: {critical_count}")
    if high_count > 0 and not (polish_payload.get("deviation") or []):
        raise RuntimeError(f"Step 4 后仍存在 high 问题且未记录 deviation: {high_count}")
    complete_step(
        project_root,
        "Step 4",
        {
            "anti_ai_force_check": polish_payload.get("anti_ai_force_check"),
            "change_summary": polish_payload.get("change_summary", []),
            "deviation": polish_payload.get("deviation", []),
            "full_reread_count": polish_payload.get("full_reread_count", 0),
            "final_overall_score": final_review.get("overall_score"),
            "execution_file": str((artifact_dir / "polish.execution.json").relative_to(project_root)),
            "trace_file": str((artifact_dir / "polish.trace.json").relative_to(project_root)),
        },
    )
    _emit_step_banner("Step 4", "润色", status="done")

    start_step(project_root, "Step 5", "Data Agent")
    _emit_step_banner("Step 5", "Data Agent", status="start")
    data_payload = run_codex_json_stage(
        stage_name="data_agent",
        prompt=_build_data_prompt(chapter, title, current_content, final_review, context_package, materials),
        schema=_build_stage_schema_data(),
        project_root=project_root,
        artifact_dir=artifact_dir,
        codex_bin=codex_bin,
    )
    data_payload["review_score"] = final_review.get("overall_score")
    write_json(artifact_dir / "data_agent_result.json", data_payload)
    data_result = _apply_data_payload(
        project_root,
        chapter=chapter,
        data_payload=data_payload,
        artifact_dir=artifact_dir,
        enable_debt_interest=enable_debt_interest,
    )
    summary_file = project_root / ".webnovel" / "summaries" / f"ch{chapter:04d}.md"
    complete_step(
        project_root,
        "Step 5",
        {
            "summary_file": str(summary_file.relative_to(project_root)),
            "state_file": ".webnovel/state.json",
            "index_file": ".webnovel/index.db",
            "timing_ms": data_result.get("timing_ms", {}),
        },
    )
    _emit_step_banner("Step 5", "Data Agent", status="done")

    start_step(project_root, "Step 6", "Git 备份")
    _emit_step_banner("Step 6", "Git 备份", status="start")
    complete_step(project_root, "Step 6", {"git_backup": "skipped_per_codex_instructions"})
    _emit_step_banner("Step 6", "Git 备份", status="done")
    final_stats = _chapter_stats(project_root)
    complete_task(
        project_root,
        {
            "ok": True,
            "command": "webnovel-write",
            "chapter": chapter,
            "chapter_file": str(chapter_path.relative_to(project_root)),
            "summary_file": str(summary_file.relative_to(project_root)),
            "overall_score": final_review.get("overall_score"),
        },
    )
    _emit_tui_line(f"✅ webnovel-write 第 {chapter} 章完成")

    return _build_result(
        project_root=project_root,
        chapter=chapter,
        chapter_file=chapter_path,
        summary_file=summary_file,
        review_payload=final_review,
        final_stats=final_stats,
        style_payload=style_payload,
        polish_payload=polish_payload,
        data_result=data_result,
    )


class WorkflowInterrupted(KeyboardInterrupt):
    """Raised when the write workflow receives an external interrupt signal."""


def _install_interrupt_handlers(chapter: int) -> Dict[int, Any]:
    previous: Dict[int, Any] = {}

    def _handler(signum, _frame):
        try:
            signal_name = signal.Signals(signum).name
        except Exception:
            signal_name = f"signal {signum}"
        raise WorkflowInterrupted(f"收到 {signal_name}，中止 webnovel-write 第 {chapter} 章")

    for attr in ("SIGINT", "SIGTERM"):
        if not hasattr(signal, attr):
            continue
        sig = getattr(signal, attr)
        previous[int(sig)] = signal.getsignal(sig)
        signal.signal(sig, _handler)
    return previous


def _restore_interrupt_handlers(previous: Dict[int, Any]) -> None:
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)
        except Exception:
            continue


def _force_mark_task_failed(project_root: Path, *, chapter: int, reason: str) -> bool:
    state_path = project_root / ".webnovel" / "workflow_state.json"
    if not state_path.is_file():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    task = state.get("current_task")
    if not isinstance(task, dict):
        return False
    task_args = task.get("args") if isinstance(task.get("args"), dict) else {}
    task_chapter = task_args.get("chapter_num")
    if task.get("command") != "webnovel-write":
        return False
    if task_chapter not in (None, chapter):
        return False

    current_step = task.get("current_step")
    if isinstance(current_step, dict) and current_step.get("status") not in {"completed", "failed"}:
        failed_step = dict(current_step)
        failed_step["status"] = "failed"
        failed_step["failed_at"] = now_iso()
        failed_step["failure_reason"] = reason
        failed_steps = list(task.get("failed_steps") or [])
        failed_steps.append(failed_step)
        task["failed_steps"] = failed_steps
    task["current_step"] = None
    task["status"] = "failed"
    task["failed_at"] = now_iso()
    task["failure_reason"] = reason
    task["last_heartbeat"] = now_iso()
    state["current_task"] = task
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    append_jsonl(
        project_root / ".webnovel" / "observability" / "call_trace.jsonl",
        {
            "timestamp": now_iso(),
            "event": "task_failed_fallback",
            "payload": {
                "command": "webnovel-write",
                "chapter": chapter,
                "reason": reason,
            },
        },
    )
    return True


def _failure_payload(project_root: Path, chapter: int, message: str, *, interrupted: bool) -> Dict[str, Any]:
    return {
        "status": "error",
        "chapter": chapter,
        "project_root": str(project_root),
        "error": message,
        "interrupted": bool(interrupted),
    }


def _handle_workflow_failure(project_root: Path, chapter: int, exc: BaseException, *, interrupted: bool) -> int:
    message = str(exc).strip() or exc.__class__.__name__
    _emit_tui_line(f"❌ webnovel-write 第 {chapter} 章失败: {message}")
    try:
        fail_task(
            project_root,
            reason=message,
            artifacts={
                "ok": False,
                "command": "webnovel-write",
                "chapter": chapter,
                "error": message,
                "interrupted": bool(interrupted),
            },
        )
    except Exception as workflow_exc:
        if _force_mark_task_failed(project_root, chapter=chapter, reason=message):
            _emit_tui_line(f"workflow fail-task 调用失败，已直接写入 failed 状态: {workflow_exc}")
        else:
            _emit_tui_line(f"workflow fail-task 记录失败: {workflow_exc}")
    print(json.dumps(_failure_payload(project_root, chapter, message, interrupted=interrupted), ensure_ascii=False, indent=2))
    return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex source-backed write workflow")
    parser.add_argument("--project-root", required=True, help="书项目根目录或可解析到项目根目录的路径")
    parser.add_argument("--chapter", type=int, required=True, help="目标章节号")
    parser.add_argument("--codex-bin", default=None, help="显式指定 codex 可执行文件")
    parser.add_argument("--mode", choices=["standard", "fast", "minimal"], default="standard")
    parser.add_argument("--enable-debt-interest", action="store_true", help="显式开启债务利息计算")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = resolve_project_root(str(Path(args.project_root)))
    chapter = int(args.chapter)
    previous_handlers = _install_interrupt_handlers(chapter)
    try:
        result = run_write_workflow(
            project_root=project_root,
            chapter=chapter,
            mode=str(args.mode),
            codex_bin=args.codex_bin,
            enable_debt_interest=bool(args.enable_debt_interest),
        )
    except KeyboardInterrupt as exc:
        return _handle_workflow_failure(project_root, chapter, exc, interrupted=True)
    except Exception as exc:
        return _handle_workflow_failure(project_root, chapter, exc, interrupted=False)
    finally:
        _restore_interrupt_handlers(previous_handlers)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    enable_windows_utf8_stdio(skip_in_pytest=True)
    raise SystemExit(main())
