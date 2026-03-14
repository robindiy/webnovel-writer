#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Delegate installed Codex skill commands back to the repository adapter."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence


def load_repo_config(skill_root: Optional[Path] = None) -> dict:
    resolved_skill_root = skill_root or Path(__file__).resolve().parents[1]
    config_path = resolved_skill_root / "repo_config.json"
    return json.loads(config_path.read_text(encoding="utf-8"))


def resolve_repo_python(repo_root: Path) -> str:
    candidates = [
        repo_root / ".venv" / "bin" / "python",
        repo_root / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    return str(getattr(sys, "executable", "") or "python3")


def build_delegate_command(argv: Sequence[str], *, skill_root: Optional[Path] = None) -> list[str]:
    config = load_repo_config(skill_root)
    repo_root = Path(config["repo_root"]).expanduser().resolve()
    codex_cli = repo_root / "webnovel-writer" / "scripts" / "codex_cli.py"
    python_exec = resolve_repo_python(repo_root)
    return [python_exec, str(codex_cli), *list(argv)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    command = build_delegate_command(list(argv or sys.argv[1:]))
    proc = subprocess.run(command)
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
