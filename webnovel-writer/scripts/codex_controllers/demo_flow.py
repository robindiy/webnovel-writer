#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic 5-step controller demo used to prove Codex turn control."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from uuid import uuid4


CONTROLLER_NAME = "demo-proof"
COMMAND_NAME = "webnovel-controller-demo"
STEP_COUNT = 5
OUTPUT_DIR_NAME = "controller-demo"
SESSION_FILE_NAME = f"{CONTROLLER_NAME}.json"
WHITELIST_DIRS = (
    f"{OUTPUT_DIR_NAME}/",
    ".webnovel/controller_sessions/",
)


def _project_root_path(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve()


def _normalize_token(value: object) -> str:
    return "".join(str(value or "").strip().casefold().split())


def _clone_session(session: Mapping[str, Any]) -> dict[str, Any]:
    cloned = dict(session)
    cloned["artifacts"] = list(session.get("artifacts") or [])
    cloned["verification_errors"] = list(session.get("verification_errors") or [])
    return cloned


def _relative_paths(paths: Sequence[str], project_root: Path) -> list[str]:
    return [str(Path(path).resolve().relative_to(project_root)) for path in paths]


def _step_options(step_id: str) -> list[dict[str, Any]]:
    mapping = {
        "step-1": [
            {"id": "continue", "label": "继续", "aliases": ("1",)},
            {"id": "cancel", "label": "取消", "aliases": ("2",)},
        ],
        "step-2": [
            {"id": "standard", "label": "标准模式", "aliases": ("1",)},
            {"id": "strict", "label": "严格模式", "aliases": ("2",)},
        ],
        "step-3": [
            {"id": "confirm-execution", "label": "确认执行", "aliases": ("1",)},
            {"id": "back-step-2", "label": "返回上一步", "aliases": ("2",)},
        ],
        "step-4": [
            {"id": "continue-verify", "label": "继续验证", "aliases": ("1",)},
        ],
    }
    return [dict(option) for option in mapping.get(str(step_id).strip(), [])]


def _match_option(user_input: object, options: Sequence[Mapping[str, Any]]) -> Optional[str]:
    normalized = _normalize_token(user_input)
    if not normalized:
        return None
    for index, option in enumerate(options, start=1):
        candidates = {option.get("id", ""), option.get("label", ""), str(index)}
        candidates.update(option.get("aliases") or ())
        if normalized in {_normalize_token(candidate) for candidate in candidates}:
            return str(option.get("id", "")).strip()
    return None


def new_session(project_root: str | Path) -> dict[str, Any]:
    resolved_project_root = _project_root_path(project_root)
    return {
        "controller": CONTROLLER_NAME,
        "session_id": f"{CONTROLLER_NAME}-{uuid4()}",
        "active": True,
        "step_id": "step-1",
        "profile": None,
        "project_root": str(resolved_project_root),
        "artifacts": [],
        "last_error": None,
        "verification_errors": [],
        "docs_plans_present_at_start": (resolved_project_root / "docs" / "plans").exists(),
    }


def force_finish(session: Mapping[str, Any], *, step_id: str = "finished") -> dict[str, Any]:
    updated = _clone_session(session)
    updated["active"] = False
    updated["step_id"] = step_id
    updated["last_error"] = None
    updated["verification_errors"] = []
    return updated


def _write_demo_artifacts(session: Mapping[str, Any]) -> list[str]:
    project_root = _project_root_path(str(session["project_root"]))
    output_dir = project_root / OUTPUT_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    session_md = output_dir / "01-session.md"
    choice_json = output_dir / "02-choice.json"
    result_md = output_dir / "03-result.md"

    artifact_paths = [session_md, choice_json, result_md]

    session_md.write_text(
        "\n".join(
            [
                "# Controller Demo Session",
                "",
                f"- controller: {CONTROLLER_NAME}",
                f"- session_id: {session['session_id']}",
                f"- profile: {session.get('profile') or 'unset'}",
                f"- output_dir: {OUTPUT_DIR_NAME}/",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    choice_payload = {
        "controller": CONTROLLER_NAME,
        "session_id": session["session_id"],
        "profile": session.get("profile"),
        "output_directory": f"{OUTPUT_DIR_NAME}/",
        "file_whitelist": list(WHITELIST_DIRS),
        "step_count": STEP_COUNT,
    }
    choice_json.write_text(json.dumps(choice_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result_md.write_text(
        "\n".join(
            [
                "# Controller Demo Result",
                "",
                "status: generated",
                f"profile: {session.get('profile') or 'unset'}",
                "next_step: verify",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return [str(path.resolve()) for path in artifact_paths]


def verify_session(session: Mapping[str, Any]) -> list[str]:
    project_root = _project_root_path(str(session["project_root"]))
    errors: list[str] = []

    artifacts = [Path(path) for path in session.get("artifacts") or []]
    expected_names = {"01-session.md", "02-choice.json", "03-result.md"}
    if {path.name for path in artifacts} != expected_names:
        errors.append("artifacts-mismatch")

    for path in artifacts:
        if not path.is_file():
            errors.append(f"missing:{path.name}")

    if artifacts:
        json_path = next((path for path in artifacts if path.name == "02-choice.json"), None)
        if json_path is None:
            errors.append("missing:02-choice.json")
        else:
            try:
                json.loads(json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                errors.append("invalid-json:02-choice.json")

    if not session.get("docs_plans_present_at_start") and (project_root / "docs" / "plans").exists():
        errors.append("unexpected-docs-plans")

    return errors


def apply_input(session: Mapping[str, Any], user_input: object) -> dict[str, Any]:
    updated = _clone_session(session)
    if not updated.get("active"):
        return updated

    step_id = str(updated.get("step_id", "")).strip()
    option_id = _match_option(user_input, _step_options(step_id))
    if option_id is None:
        updated["last_error"] = "invalid-option"
        return updated

    updated["last_error"] = None
    updated["verification_errors"] = []

    if step_id == "step-1":
        if option_id == "continue":
            updated["step_id"] = "step-2"
            return updated
        if option_id == "cancel":
            return force_finish(updated, step_id="cancelled")

    if step_id == "step-2":
        if option_id in {"standard", "strict"}:
            updated["profile"] = option_id
            updated["step_id"] = "step-3"
            return updated

    if step_id == "step-3":
        if option_id == "back-step-2":
            updated["step_id"] = "step-2"
            return updated
        if option_id == "confirm-execution":
            updated["artifacts"] = _write_demo_artifacts(updated)
            updated["step_id"] = "step-4"
            return updated

    if step_id == "step-4" and option_id == "continue-verify":
        errors = verify_session(updated)
        if errors:
            updated["verification_errors"] = errors
            updated["last_error"] = "verification-failed"
            return updated
        updated["step_id"] = "step-5"
        updated["active"] = False
        return updated

    updated["last_error"] = "invalid-option"
    return updated


def _error_prefix(session: Mapping[str, Any]) -> str:
    last_error = str(session.get("last_error") or "").strip()
    if last_error == "invalid-option":
        return "仅支持当前步骤给出的固定选项，请按按钮或输入选项名称。\n\n"
    if last_error == "verification-failed":
        details = ", ".join(str(item) for item in session.get("verification_errors") or [])
        if details:
            return f"验证失败：{details}\n\n"
        return "验证失败，请检查演示产物。\n\n"
    return ""


def _message_for_session(session: Mapping[str, Any]) -> str:
    project_root = _project_root_path(str(session["project_root"]))
    prefix = _error_prefix(session)
    step_id = str(session.get("step_id", "")).strip()
    profile = str(session.get("profile") or "unset").strip()
    artifact_paths = _relative_paths(session.get("artifacts") or [], project_root)

    if step_id == "step-1":
        return (
            prefix
            + "[Controller Demo 1/5] 最小控制器验证\n"
            + "goal: prove Codex stays inside a repo-owned 5-step controller\n"
            + "warning: 这只是 demo proof，不会触发 webnovel-plan / webnovel-write / webnovel-review"
        )
    if step_id == "step-2":
        return prefix + "[Controller Demo 2/5] 请选择运行模式："
    if step_id == "step-3":
        return "\n".join(
            [
                prefix + "[Controller Demo 3/5] 请确认执行契约",
                f"selected profile: {profile}",
                f"output directory: {OUTPUT_DIR_NAME}/",
                f"file whitelist: {', '.join(WHITELIST_DIRS)}",
                f"step count: {STEP_COUNT}",
            ]
        ).strip()
    if step_id == "step-4":
        artifact_lines = "\n".join(f"- {path}" for path in artifact_paths)
        return (
            prefix
            + "[Controller Demo 4/5] 已生成演示产物，准备执行验证。\n"
            + "generated artifacts:\n"
            + artifact_lines
        )
    if step_id == "step-5":
        artifact_lines = "\n".join(f"- {path}" for path in artifact_paths)
        return (
            "[Controller Demo 5/5] 验证完成。\n"
            + "generated artifacts:\n"
            + artifact_lines
        )
    if step_id == "cancelled":
        return "[Controller Demo] 已取消，不会写入新的 demo 产物。"
    if step_id == "abandoned":
        return "[Controller Demo] 已被新的显式命令中断。"
    return "[Controller Demo] 会话已结束。"


def build_controller_action(session: Mapping[str, Any]) -> dict[str, Any]:
    step_id = str(session.get("step_id", "")).strip()
    return {
        "type": "controller_step",
        "controller": CONTROLLER_NAME,
        "session_id": str(session.get("session_id", "")).strip(),
        "step_id": step_id,
        "done": not bool(session.get("active")),
        "message": _message_for_session(session),
        "options": [] if not session.get("active") else _step_options(step_id),
    }
