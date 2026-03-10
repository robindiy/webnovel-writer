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
from codex_controllers import engine as controller_engine
from codex_controllers import demo_flow
from codex_interaction import render_numbered_options
from codex_topology import get_topology
from init_terminal_ui import run_shell_init_wizard
from project_locator import resolve_project_root
from runtime_compat import ensure_utf8_locale, resolve_python_executable


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


def _source_workflow_action(command: ParsedCommand, project_root: Path) -> dict[str, Any]:
    topology = get_topology(command.name)
    python_executable = resolve_python_executable()
    if command.name == "webnovel-review":
        script_path = SCRIPTS_DIR / "codex_review_workflow.py"
        command_line = [
            python_executable,
            str(script_path),
            "--project-root",
            str(project_root),
        ]
        range_arg = str(command.args[0]).strip() if command.args else ""
        if range_arg:
            command_line.extend(["--range", range_arg])
    elif command.name == "webnovel-write":
        script_path = SCRIPTS_DIR / "codex_write_workflow.py"
        command_line = [
            python_executable,
            str(script_path),
            "--project-root",
            str(project_root),
        ]
        if command.args:
            chapter_arg = str(command.args[0]).strip()
            if chapter_arg:
                command_line.extend(["--chapter", chapter_arg])
        for extra_arg in command.args[1:]:
            value = str(extra_arg).strip()
            if value == "--fast":
                command_line.extend(["--mode", "fast"])
            elif value == "--minimal":
                command_line.extend(["--mode", "minimal"])
            elif value:
                command_line.append(value)
    else:
        raise RuntimeError(f"未支持的 source workflow 命令: {command.name}")

    return {
        "type": "run_source_workflow",
        "workflow_id": command.name,
        "script_path": str(script_path),
        "python_executable": python_executable,
        "command_line": command_line,
        "topology": topology.to_dict() if topology else None,
    }


def _follow_skill_action(command: ParsedCommand) -> dict[str, Any]:
    topology = get_topology(command.name)
    return {
        "type": "follow_skill",
        "skill_path": str(command.skill_path),
        "topology": topology.to_dict() if topology else None,
        "execution_model": topology.execution_model if topology else "skill",
    }


def _desktop_strict_skill_action(command: ParsedCommand) -> dict[str, Any]:
    action = _follow_skill_action(command)
    action["desktop_mode"] = "strict_follow_skill"
    action["execution_model"] = "desktop_strict_follow_skill"
    action["topology_note"] = "For Codex Desktop, execute action.desktop_contract before any topology entrypoint that still references shell/source runners."
    if command.name == "webnovel-write":
        action["desktop_contract"] = {
            "mode": "artifact_chain_v1",
            "prepare_script": str(SCRIPTS_DIR / "write_prepare.py"),
            "finalize_script": str(SCRIPTS_DIR / "write_finalize.py"),
            "review_prepare_script": str(SCRIPTS_DIR / "review_prepare.py"),
            "review_finalize_script": str(SCRIPTS_DIR / "review_finalize.py"),
            "forbid_direct_runner": ["review_agents_runner.py"],
        }
    elif command.name == "webnovel-review":
        action["desktop_contract"] = {
            "mode": "checker_prompt_chain_v1",
            "prepare_script": str(SCRIPTS_DIR / "review_prepare.py"),
            "finalize_script": str(SCRIPTS_DIR / "review_finalize.py"),
            "forbid_direct_runner": ["review_agents_runner.py"],
        }
    return action


def _parse_command(raw_command: Union[str, Sequence[str]]) -> ParsedCommand:
    if isinstance(raw_command, str):
        return parse_command_text(raw_command)
    return parse_argv(list(raw_command))


def _stringify_raw_command(raw_command: Union[str, Sequence[str]]) -> str:
    if isinstance(raw_command, str):
        return str(raw_command).strip()
    return " ".join(str(part).strip() for part in raw_command if str(part).strip()).strip()


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
            "description": "如果项目还没创建，先在外部终端运行 /webnovel-writer:webnovel-init 的 TUI 向导",
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


def _maybe_resolve_project_root(
    *,
    project_root: Optional[Union[str, Path]] = None,
    workspace_root: Optional[Union[str, Path]] = None,
) -> Optional[Path]:
    try:
        return _resolve_project_root(explicit_project_root=project_root, workspace_root=workspace_root)
    except FileNotFoundError:
        return None


def _default_workspace_root(workspace_root: Optional[Union[str, Path]] = None) -> Path:
    if workspace_root:
        return Path(workspace_root).expanduser().resolve()
    return Path.cwd().resolve()


def _external_init_command(workspace_root: Optional[Union[str, Path]] = None) -> str:
    parts = ['~/.codex/bin/webnovel-codex', '--mode', 'shell']
    if workspace_root:
        parts.extend(['--workspace-root', f'"{Path(workspace_root).expanduser().resolve()}"'])
    parts.append('"/webnovel-writer:webnovel-init"')
    return " ".join(parts)


def _controller_command(command_name: str) -> ParsedCommand:
    return parse_command_text(f"/webnovel-writer:{command_name}")


def _render_controller_message(action: dict[str, Any]) -> str:
    message = str(action.get("message", "")).strip()
    options = action.get("options") or []
    if not options:
        return message

    lines = [message, "", "可用选项："]
    for index, option in enumerate(options, start=1):
        label = str(option.get("label", "")).strip()
        description = str(option.get("description", "")).strip()
        if description:
            lines.append(f"{index}. {label} — {description}")
        else:
            lines.append(f"{index}. {label}")
    return "\n".join(lines).strip()


def _controller_payload(
    *,
    command: ParsedCommand,
    session: dict[str, Any],
    mode: str,
    project_root: Optional[Path],
    workspace_root: Optional[Union[str, Path]] = None,
) -> dict[str, Any]:
    action = controller_engine.build_action(session)
    return {
        "status": "ok",
        "mode": mode,
        "command": _command_to_dict(command),
        "project_root": str(project_root) if project_root else None,
        "workspace_root": str(Path(workspace_root).resolve()) if workspace_root else None,
        "action": action,
        "message": _render_controller_message(action),
    }


def _external_init_payload(
    *,
    command: ParsedCommand,
    mode: str,
    workspace_root: Optional[Union[str, Path]] = None,
    stale_session_closed: bool = False,
) -> dict[str, Any]:
    resolved_workspace_root = _default_workspace_root(workspace_root)
    shell_command = _external_init_command(resolved_workspace_root)
    lines = []
    if stale_session_closed:
        lines.append("检测到旧的 Codex init 会话，已停止继续续跑。")
        lines.append("")
    lines.extend(
        [
            "`/webnovel-writer:webnovel-init` 已恢复为外部终端初始化，不再在 Codex 对话里逐项问答。",
            "",
            "请在普通终端执行：",
            shell_command,
            "",
            "它会启动支持方向键选择的 `prompt_toolkit` TUI 向导。",
            "初始化完成后进入书项目目录，再回到 Codex 继续规划、写作、审稿；如果前面有留空或写了“系统补全”，Codex 再在项目内补齐。",
        ]
    )
    return {
        "status": "ok",
        "mode": mode,
        "command": _command_to_dict(command),
        "project_root": None,
        "workspace_root": str(resolved_workspace_root),
        "action": {
            "type": "external_init",
            "command": shell_command,
            "ui": "prompt_toolkit",
            "requires_terminal": True,
        },
        "message": "\n".join(lines).strip(),
    }


def _candidate_session_roots(
    *,
    project_root: Optional[Union[str, Path]] = None,
    workspace_root: Optional[Union[str, Path]] = None,
) -> list[Path]:
    roots: list[Path] = []
    resolved_project_root = _maybe_resolve_project_root(project_root=project_root, workspace_root=workspace_root)
    if resolved_project_root is not None:
        roots.append(resolved_project_root)
    resolved_workspace_root = _default_workspace_root(workspace_root)
    if resolved_workspace_root not in roots:
        roots.append(resolved_workspace_root)
    return roots


def _maybe_continue_active_controller(
    raw_command: Union[str, Sequence[str]],
    *,
    mode: str,
    project_root: Optional[Union[str, Path]] = None,
    workspace_root: Optional[Union[str, Path]] = None,
) -> Optional[dict[str, Any]]:
    raw_text = _stringify_raw_command(raw_command)
    if not raw_text or raw_text.startswith("/"):
        return None

    for session_root in _candidate_session_roots(project_root=project_root, workspace_root=workspace_root):
        session = controller_engine.load_active_session(session_root)
        if not session:
            continue
        controller = str(session.get("controller", "")).strip()
        if mode == "codex" and controller_engine.command_name(session) == "webnovel-init":
            controller_engine.finish_session(
                project_root=session_root,
                controller=controller,
                step_id="abandoned",
            )
            return _external_init_payload(
                command=_controller_command("webnovel-init"),
                mode=mode,
                workspace_root=workspace_root or session_root,
                stale_session_closed=True,
            )
        updated = controller_engine.advance_session(
            project_root=session_root,
            controller=controller,
            user_input=raw_text,
        )
        return _controller_payload(
            command=_controller_command(controller_engine.command_name(updated)),
            session=updated,
            mode=mode,
            project_root=Path(str(updated.get("project_root"))).resolve() if updated.get("project_root") else None,
            workspace_root=workspace_root or session_root,
        )
    return None


def prepare_command(
    raw_command: Union[str, Sequence[str]],
    *,
    mode: str = "codex",
    project_root: Optional[Union[str, Path]] = None,
    workspace_root: Optional[Union[str, Path]] = None,
) -> dict[str, Any]:
    try:
        command = _parse_command(raw_command)
    except ValueError:
        controller_payload = _maybe_continue_active_controller(
            raw_command,
            mode=mode,
            project_root=project_root,
            workspace_root=workspace_root,
        )
        if controller_payload is not None:
            return controller_payload
        raise

    resolved_project_root: Optional[Path] = None
    if command.requires_project:
        try:
            resolved_project_root = _resolve_project_root(
                explicit_project_root=project_root,
                workspace_root=workspace_root,
            )
        except FileNotFoundError:
            return _missing_project_payload(command, mode=mode)
    else:
        resolved_project_root = _maybe_resolve_project_root(project_root=project_root, workspace_root=workspace_root)

    if command.name == demo_flow.COMMAND_NAME:
        if resolved_project_root is None:
            return _missing_project_payload(command, mode=mode)
        session = controller_engine.start_session(
            project_root=resolved_project_root,
            controller=demo_flow.CONTROLLER_NAME,
        )
        return _controller_payload(
            command=command,
            session=session,
            mode=mode,
            project_root=resolved_project_root,
            workspace_root=workspace_root,
        )

    if command.name == "webnovel-init" and mode == "codex":
        return _external_init_payload(
            command=command,
            mode=mode,
            workspace_root=workspace_root,
        )

    for candidate_root in _candidate_session_roots(project_root=project_root, workspace_root=workspace_root):
        active_session = controller_engine.load_active_session(candidate_root)
        if not active_session:
            continue
        controller_engine.finish_session(
            project_root=candidate_root,
            controller=str(active_session.get("controller", "")).strip(),
            step_id="abandoned",
        )

    if command.name == "webnovel-dashboard":
        action: dict[str, Any] = {"type": "start_dashboard"}
    elif command.name == "webnovel-write":
        action = _source_workflow_action(command, resolved_project_root)
    elif mode == "shell" and command.name == "webnovel-review":
        action = _source_workflow_action(command, resolved_project_root)
    elif command.name == "webnovel-review":
        action = _desktop_strict_skill_action(command)
    else:
        action = _follow_skill_action(command)

    payload = {
        "status": "ok",
        "mode": mode,
        "command": _command_to_dict(command),
        "project_root": str(resolved_project_root) if resolved_project_root else None,
        "workspace_root": str(Path(workspace_root).resolve()) if workspace_root else None,
        "action": action,
    }
    return payload


def start_dashboard(
    project_root: Union[str, Path],
    *,
    host: str = "127.0.0.1",
    port: int = 18765,
    open_browser: bool = True,
) -> dict[str, Any]:
    python_executable = resolve_python_executable()
    env = dict(os.environ)
    env["WEBNOVEL_PROJECT_ROOT"] = str(Path(project_root).resolve())
    existing_pythonpath = env.get("PYTHONPATH", "")
    pythonpath_parts = [str(REPO_PACKAGE_ROOT)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    _ensure_dashboard_runtime_ready(python_executable, env)

    command = [
        python_executable,
        "-m",
        "dashboard.server",
        "--project-root",
        str(Path(project_root).resolve()),
        "--host",
        host,
        "--port",
        str(port),
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
        "url": f"http://{host}:{port}",
        "command": command,
        "browser_requested": bool(open_browser),
    }


def _ensure_dashboard_runtime_ready(python_executable: str, env: dict[str, str]) -> None:
    probe = [
        python_executable,
        "-c",
        "import fastapi, uvicorn, dashboard.app, dashboard.watcher",
    ]
    proc = subprocess.run(
        probe,
        cwd=str(REPO_PACKAGE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return

    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    tail = detail[-1] if detail else "unknown import error"
    requirements_path = REPO_PACKAGE_ROOT / "dashboard" / "requirements.txt"
    raise RuntimeError(
        "Dashboard 依赖未就绪，无法启动。\n"
        f"请先执行：{python_executable} -m pip install -r '{requirements_path}'\n"
        f"最后错误：{tail}"
    )


def _render_payload(payload: dict[str, Any]) -> str:
    if payload.get("status") == "started":
        lines = [
            "/webnovel-writer:webnovel-dashboard 已启动。",
            "",
            f"- 地址：{payload.get('url', '')}",
            f"- 进程：PID {payload.get('pid', '')}",
        ]
        if payload.get("browser_requested"):
            lines.append("- 已请求自动打开默认浏览器；如果没有弹出，再手动打开上面的地址。")
        else:
            lines.append("- 当前为 --no-browser 模式，需要你手动打开上面的地址。")
        return "\n".join(lines).strip()

    if payload.get("status") == "needs_input":
        return str(payload.get("message", "")).strip()

    action = payload.get("action") or {}
    command = payload.get("command") or {}
    if action.get("type") in {"controller_step", "external_init"}:
        return str(payload.get("message", "")).strip()

    if action.get("type") == "run_source_workflow":
        lines = [
            f"命令: {command.get('slash_command', '')}",
            f"动作: {action.get('type', '')}",
            f"脚本: {action.get('script_path', '')}",
            f"执行: {' '.join(action.get('command_line') or [])}",
        ]
        if payload.get("project_root"):
            lines.append(f"项目: {payload['project_root']}")
        return "\n".join(lines)

    lines = [
        f"命令: {command.get('slash_command', '')}",
        f"动作: {action.get('type', '')}",
    ]
    if payload.get("project_root"):
        lines.append(f"项目: {payload['project_root']}")
    if action.get("skill_path"):
        lines.append(f"Skill: {action['skill_path']}")
    return "\n".join(lines)


def run_init_wizard(workspace_root: Optional[Union[str, Path]] = None) -> dict[str, Any]:
    resolved_workspace_root = Path(workspace_root).expanduser().resolve() if workspace_root else Path.cwd().resolve()
    return run_shell_init_wizard(workspace_root=resolved_workspace_root)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        ensure_utf8_locale()

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

        if (
            args.mode == "shell"
            and not args.json
            and payload.get("status") == "ok"
            and (payload.get("command") or {}).get("name") == "webnovel-init"
        ):
            run_init_wizard(workspace_root=args.workspace_root)
            return 0

        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(_render_payload(payload))
        return 0
    except KeyboardInterrupt:
        print("已取消初始化。", file=sys.stderr)
        return 130
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
