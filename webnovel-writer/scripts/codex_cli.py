#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex adapter entrypoint for slash-compatible webnovel commands."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Union

from codex_command_registry import ParsedCommand, parse_argv, parse_command_text
from codex_interaction import render_numbered_options
from project_locator import resolve_project_root
from runtime_compat import resolve_python_executable


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_PACKAGE_ROOT = SCRIPTS_DIR.parent


def _command_to_dict(command: ParsedCommand) -> dict[str, Any]:
    return {
        "name": command.name,
        "args": list(command.args),
        "slash_command": command.slash_command,
        "skill_name": command.skill_name,
        "skill_path": str(command.skill_path),
        "requires_project": command.requires_project,
    }


def _parse_command(raw_command: Union[str, Sequence[str]]) -> ParsedCommand:
    if isinstance(raw_command, str):
        return parse_command_text(raw_command)
    return parse_argv(list(raw_command))


def _resolve_project_root(
    *,
    explicit_project_root: Optional[Union[str, Path]] = None,
    workspace_root: Optional[Union[str, Path]] = None,
) -> Path:
    if explicit_project_root:
        return resolve_project_root(str(explicit_project_root))
    if workspace_root:
        return resolve_project_root(cwd=Path(workspace_root))
    return resolve_project_root()


def _missing_project_payload(command: ParsedCommand, *, mode: str) -> dict[str, Any]:
    options = [
        {
            "id": "provide-project-root",
            "label": "提供项目路径",
            "description": "指定包含 .webnovel/state.json 的书项目根目录",
        },
        {
            "id": "run-init",
            "label": "先初始化项目",
            "description": "如果项目还没创建，先运行 /webnovel-writer:webnovel-init",
        },
        {
            "id": "check-workspace-pointer",
            "label": "检查当前工作区",
            "description": "确认 .claude/.webnovel-current-project 指针是否存在",
        },
    ]
    payload = {
        "status": "needs_input",
        "mode": mode,
        "command": _command_to_dict(command),
        "project_root": None,
        "action": {"type": "select_project"},
        "options": options,
    }
    payload["message"] = render_numbered_options(
        "未找到当前小说项目",
        "请选择下一步操作：",
        options,
    )
    return payload


def prepare_command(
    raw_command: Union[str, Sequence[str]],
    *,
    mode: str = "codex",
    project_root: Optional[Union[str, Path]] = None,
    workspace_root: Optional[Union[str, Path]] = None,
) -> dict[str, Any]:
    command = _parse_command(raw_command)

    resolved_project_root: Optional[Path] = None
    if command.requires_project:
        try:
            resolved_project_root = _resolve_project_root(
                explicit_project_root=project_root,
                workspace_root=workspace_root,
            )
        except FileNotFoundError:
            return _missing_project_payload(command, mode=mode)

    action_type = "start_dashboard" if command.name == "webnovel-dashboard" else "follow_skill"

    payload = {
        "status": "ok",
        "mode": mode,
        "command": _command_to_dict(command),
        "project_root": str(resolved_project_root) if resolved_project_root else None,
        "workspace_root": str(Path(workspace_root).resolve()) if workspace_root else None,
        "action": {
            "type": action_type,
            "skill_path": str(command.skill_path),
        },
    }
    return payload


def start_dashboard(
    project_root: Union[str, Path],
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    open_browser: bool = False,
) -> dict[str, Any]:
    python_executable = resolve_python_executable()
    env = dict(os.environ)
    env["WEBNOVEL_PROJECT_ROOT"] = str(Path(project_root).resolve())
    resolved_host = host or str(env.get("WEBNOVEL_DASHBOARD_HOST") or "127.0.0.1")
    try:
        resolved_port = int(port if port is not None else env.get("WEBNOVEL_DASHBOARD_PORT", "5678"))
    except (TypeError, ValueError):
        resolved_port = 5678
    existing_pythonpath = env.get("PYTHONPATH", "")
    pythonpath_parts = [str(REPO_PACKAGE_ROOT)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)

    command = [
        python_executable,
        "-m",
        "dashboard.server",
        "--project-root",
        str(Path(project_root).resolve()),
        "--host",
        resolved_host,
        "--port",
        str(resolved_port),
    ]
    if not open_browser:
        command.append("--no-browser")

    process = subprocess.Popen(
        command,
        cwd=str(REPO_PACKAGE_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "status": "started",
        "pid": int(process.pid),
        "url": f"http://{resolved_host}:{resolved_port}",
        "command": command,
    }


def _render_payload(payload: dict[str, Any]) -> str:
    if payload.get("status") == "needs_input":
        return str(payload.get("message", "")).strip()

    action = payload.get("action") or {}
    command = payload.get("command") or {}
    lines = [
        f"命令: {command.get('slash_command', '')}",
        f"动作: {action.get('type', '')}",
    ]
    if payload.get("project_root"):
        lines.append(f"项目: {payload['project_root']}")
    if action.get("skill_path"):
        lines.append(f"Skill: {action['skill_path']}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Codex adapter for webnovel-writer slash commands")
    parser.add_argument("command", nargs="+", help="Slash command or fallback command")
    parser.add_argument("--mode", choices=["codex", "shell"], default="codex")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--workspace-root", default=None)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--execute-dashboard",
        action="store_true",
        help="Actually start dashboard.server for /webnovel-writer:webnovel-dashboard",
    )
    args = parser.parse_args(argv)

    raw_command: Union[str, Sequence[str]]
    if len(args.command) == 1 and str(args.command[0]).startswith("/webnovel-writer:"):
        raw_command = str(args.command[0])
    else:
        raw_command = list(args.command)

    payload = prepare_command(
        raw_command,
        mode=args.mode,
        project_root=args.project_root,
        workspace_root=args.workspace_root,
    )

    if args.execute_dashboard and payload.get("status") == "ok":
        command_info = payload.get("command") or {}
        if command_info.get("name") == "webnovel-dashboard" and payload.get("project_root"):
            payload = start_dashboard(payload["project_root"])

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_payload(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
