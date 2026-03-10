#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke test the Codex controller demo through a temp CODEX_HOME install."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install_codex_support.py"


def _python_exec() -> str:
    executable = str(getattr(sys, "executable", "") or "").strip()
    return executable or "python3"


def _run(command: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _make_book_project(temp_root: Path) -> Path:
    project_root = (temp_root / "book-project").resolve()
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text(
        json.dumps({"name": "controller-demo-smoke"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return project_root


def _run_wrapper(
    wrapper_path: Path,
    *,
    env: dict[str, str],
    project_root: Path,
    user_input: str,
) -> dict[str, object]:
    proc = _run(
        [
            str(wrapper_path),
            "--mode",
            "codex",
            "--json",
            "--project-root",
            str(project_root),
            user_input,
        ],
        env=env,
    )
    return json.loads(proc.stdout)


def run_smoke_test(*, keep_temp: bool = False) -> dict[str, object]:
    temp_root = Path(tempfile.mkdtemp(prefix="webnovel-controller-smoke-")).resolve()
    codex_home = temp_root / ".codex"
    env = dict(os.environ)
    env["CODEX_HOME"] = str(codex_home)

    project_root = _make_book_project(temp_root)

    try:
        install_proc = _run(
            [
                _python_exec(),
                str(INSTALL_SCRIPT),
                "--codex-home",
                str(codex_home),
                "--repo-root",
                str(REPO_ROOT),
            ],
            env=env,
        )
        install_payload = json.loads(install_proc.stdout)
        wrapper_path = Path(install_payload["wrapper_path"])
        if not wrapper_path.is_file():
            raise RuntimeError(f"Wrapper missing after install: {wrapper_path}")

        transcript = []
        expected_steps = [
            ("开始控制器测试", "step-1", False),
            ("继续", "step-2", False),
            ("标准模式", "step-3", False),
            ("确认执行", "step-4", False),
            ("继续验证", "step-5", True),
        ]
        for user_input, expected_step, expected_done in expected_steps:
            payload = _run_wrapper(
                wrapper_path,
                env=env,
                project_root=project_root,
                user_input=user_input,
            )
            action = payload.get("action") or {}
            if action.get("type") != "controller_step":
                raise RuntimeError(f"Unexpected action for {user_input}: {payload}")
            if action.get("step_id") != expected_step:
                raise RuntimeError(f"Unexpected step for {user_input}: {payload}")
            if bool(action.get("done")) is not expected_done:
                raise RuntimeError(f"Unexpected completion flag for {user_input}: {payload}")
            transcript.append(
                {
                    "input": user_input,
                    "step_id": action.get("step_id"),
                    "done": bool(action.get("done")),
                }
            )

        artifact_dir = project_root / "controller-demo"
        artifacts = [
            artifact_dir / "01-session.md",
            artifact_dir / "02-choice.json",
            artifact_dir / "03-result.md",
        ]
        for artifact in artifacts:
            if not artifact.is_file():
                raise RuntimeError(f"Missing artifact: {artifact}")

        choice_payload = json.loads((artifact_dir / "02-choice.json").read_text(encoding="utf-8"))
        if choice_payload.get("profile") != "standard":
            raise RuntimeError(f"Unexpected controller choice payload: {choice_payload}")

        session_path = project_root / ".webnovel" / "controller_sessions" / "demo-proof.json"
        session_payload = json.loads(session_path.read_text(encoding="utf-8"))
        if session_payload.get("active"):
            raise RuntimeError("Controller session should be inactive after completion")

        if (project_root / "docs" / "plans").exists():
            raise RuntimeError("Controller demo unexpectedly created docs/plans in the book project")

        return {
            "status": "ok",
            "temp_root": str(temp_root),
            "codex_home": str(codex_home),
            "project_root": str(project_root),
            "install": install_payload,
            "transcript": transcript,
            "artifacts": [str(path) for path in artifacts],
            "keep_temp": keep_temp,
        }
    finally:
        if not keep_temp:
            shutil.rmtree(temp_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the Codex controller demo in a temp CODEX_HOME")
    parser.add_argument("--keep-temp", action="store_true", help="Keep the temporary directory for inspection")
    args = parser.parse_args()

    result = run_smoke_test(keep_temp=args.keep_temp)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
