#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib.util
import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_module(name: str, relative_path: str):
    path = _repo_root() / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _install_module():
    return _load_module("install_codex_support", "scripts/install_codex_support.py")


def _restore_module():
    return _load_module("restore_codex_support", "scripts/restore_codex_support.py")


def test_install_codex_support_records_backup_state(tmp_path):
    module = _install_module()
    codex_home = tmp_path / ".codex"
    old_skill = codex_home / "skills" / "webnovel-writer"
    old_wrapper = codex_home / "bin" / "webnovel-codex"
    old_skill.mkdir(parents=True, exist_ok=True)
    (old_skill / "SKILL.md").write_text("legacy skill", encoding="utf-8")
    old_wrapper.parent.mkdir(parents=True, exist_ok=True)
    old_wrapper.write_text("#!/bin/sh\necho legacy\n", encoding="utf-8")

    result = module.install_codex_support(codex_home=codex_home, repo_root=_repo_root())

    state_path = codex_home / "webnovel-writer" / "install_state.json"
    restore_wrapper = codex_home / "bin" / "webnovel-codex-restore"
    assert state_path.is_file()
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["install_state"] == str(state_path)
    assert result["restore_wrapper_path"] == str(restore_wrapper)
    assert state["repo_root"] == str(_repo_root())
    assert state["targets"]["skill_root"] == str(codex_home / "skills" / "webnovel-writer")
    assert state["targets"]["wrapper_path"] == str(codex_home / "bin" / "webnovel-codex")
    assert state["targets"]["restore_wrapper_path"] == str(restore_wrapper)
    assert state["previous_install"]["skill_root_backed_up"] is True
    assert state["previous_install"]["wrapper_backed_up"] is True
    backup_dir = Path(state["backup_dir"])
    assert (backup_dir / "skills" / "webnovel-writer" / "SKILL.md").read_text(encoding="utf-8") == "legacy skill"
    assert (backup_dir / "bin" / "webnovel-codex").read_text(encoding="utf-8").startswith("#!/bin/sh")
    assert restore_wrapper.is_file()
    assert "restore_codex_support.py" in restore_wrapper.read_text(encoding="utf-8")


def test_restore_codex_support_recovers_previous_install(tmp_path):
    install_module = _install_module()
    restore_module = _restore_module()
    codex_home = tmp_path / ".codex"

    old_skill = codex_home / "skills" / "webnovel-writer"
    old_wrapper = codex_home / "bin" / "webnovel-codex"
    old_skill.mkdir(parents=True, exist_ok=True)
    (old_skill / "SKILL.md").write_text("legacy skill", encoding="utf-8")
    old_wrapper.parent.mkdir(parents=True, exist_ok=True)
    old_wrapper.write_text("#!/bin/sh\necho legacy\n", encoding="utf-8")

    install_module.install_codex_support(codex_home=codex_home, repo_root=_repo_root())

    restored = restore_module.restore_codex_support(codex_home=codex_home)

    assert restored["restored_skill"] is True
    assert restored["restored_wrapper"] is True
    assert (codex_home / "skills" / "webnovel-writer" / "SKILL.md").read_text(encoding="utf-8") == "legacy skill"
    assert (codex_home / "bin" / "webnovel-codex").read_text(encoding="utf-8").startswith("#!/bin/sh")
    assert not (codex_home / "webnovel-writer" / "install_state.json").exists()


def test_restore_codex_support_removes_fresh_install_when_no_backup(tmp_path):
    install_module = _install_module()
    restore_module = _restore_module()
    codex_home = tmp_path / ".codex"

    install_module.install_codex_support(codex_home=codex_home, repo_root=_repo_root())
    restored = restore_module.restore_codex_support(codex_home=codex_home)

    assert restored["restored_skill"] is False
    assert restored["restored_wrapper"] is False
    assert not (codex_home / "skills" / "webnovel-writer").exists()
    assert not (codex_home / "bin" / "webnovel-codex").exists()
    assert not (codex_home / "webnovel-writer" / "install_state.json").exists()
