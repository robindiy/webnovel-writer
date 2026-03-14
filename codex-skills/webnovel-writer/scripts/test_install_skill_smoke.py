#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib.util
import json
from pathlib import Path


def _load_helper():
    helper_path = Path(__file__).resolve().parent / "run_webnovel_command.py"
    spec = importlib.util.spec_from_file_location("run_webnovel_command", helper_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_delegate_command_uses_repo_config(tmp_path):
    helper = _load_helper()
    skill_root = tmp_path / "webnovel-writer"
    scripts_dir = skill_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    venv_python = repo_root / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("", encoding="utf-8")

    (skill_root / "repo_config.json").write_text(
        json.dumps({"repo_root": str(repo_root)}),
        encoding="utf-8",
    )

    command = helper.build_delegate_command(
        ["/webnovel-writer:webnovel-write", "1"],
        skill_root=skill_root,
    )

    assert command[0] == str(venv_python)
    assert command[1].endswith("webnovel-writer/scripts/codex_cli.py")
    assert command[-2:] == ["/webnovel-writer:webnovel-write", "1"]
