#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run a temp-CODEX_HOME install/command/restore smoke test for Codex support."""

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


def run_smoke_test(*, keep_temp: bool = False) -> dict[str, object]:
    temp_root = Path(tempfile.mkdtemp(prefix="webnovel-codex-smoke-")).resolve()
    codex_home = temp_root / ".codex"
    legacy_skill = codex_home / "skills" / "webnovel-writer"
    legacy_wrapper = codex_home / "bin" / "webnovel-codex"
    legacy_skill.mkdir(parents=True, exist_ok=True)
    (legacy_skill / "SKILL.md").write_text("legacy skill bundle\n", encoding="utf-8")
    legacy_wrapper.parent.mkdir(parents=True, exist_ok=True)
    legacy_wrapper.write_text("#!/bin/sh\necho legacy wrapper\n", encoding="utf-8")

    env = dict(os.environ)
    env["CODEX_HOME"] = str(codex_home)

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
        restore_wrapper_path = Path(install_payload["restore_wrapper_path"])
        if not wrapper_path.is_file():
            raise RuntimeError(f"Wrapper missing after install: {wrapper_path}")
        if not restore_wrapper_path.is_file():
            raise RuntimeError(f"Restore wrapper missing after install: {restore_wrapper_path}")

        command_proc = _run(
            [
                str(wrapper_path),
                "/webnovel-writer:webnovel-init",
                "--mode",
                "codex",
                "--json",
            ],
            env=env,
        )
        command_payload = json.loads(command_proc.stdout)
        if command_payload.get("status") != "ok":
            raise RuntimeError(f"Unexpected command payload: {command_payload}")
        if (command_payload.get("command") or {}).get("name") != "webnovel-init":
            raise RuntimeError(f"Unexpected command routing: {command_payload}")

        restore_proc = _run([str(restore_wrapper_path)], env=env)
        restore_payload = json.loads(restore_proc.stdout)

        restored_skill_text = (legacy_skill / "SKILL.md").read_text(encoding="utf-8")
        restored_wrapper_text = legacy_wrapper.read_text(encoding="utf-8")
        state_path = codex_home / "webnovel-writer" / "install_state.json"

        if restored_skill_text != "legacy skill bundle\n":
            raise RuntimeError("Legacy skill bundle was not restored")
        if "legacy wrapper" not in restored_wrapper_text:
            raise RuntimeError("Legacy wrapper was not restored")
        if state_path.exists():
            raise RuntimeError("Install state was not cleaned up")

        return {
            "status": "ok",
            "temp_root": str(temp_root),
            "codex_home": str(codex_home),
            "install": install_payload,
            "command": command_payload,
            "restore": restore_payload,
            "keep_temp": keep_temp,
        }
    finally:
        if not keep_temp:
            shutil.rmtree(temp_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the Codex adapter in a temp CODEX_HOME")
    parser.add_argument("--keep-temp", action="store_true", help="Keep the temporary test directory for inspection")
    args = parser.parse_args()

    result = run_smoke_test(keep_temp=args.keep_temp)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
