#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib
import sys
from pathlib import Path


def _ensure_repo_root_on_path() -> Path:
    repo_package_root = Path(__file__).resolve().parents[3]
    if str(repo_package_root) not in sys.path:
        sys.path.insert(0, str(repo_package_root))
    return repo_package_root


def _ensure_scripts_on_path() -> Path:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    return scripts_dir


def test_scripts_package_imports_under_repo_root():
    _ensure_repo_root_on_path()

    importlib.invalidate_caches()
    sys.modules.pop("scripts.security_utils", None)
    sys.modules.pop("scripts", None)

    module = importlib.import_module("scripts.security_utils")

    assert callable(module.enable_windows_utf8_stdio)


def test_resolve_python_executable_prefers_current_interpreter(monkeypatch):
    _ensure_scripts_on_path()

    runtime_compat = importlib.import_module("runtime_compat")

    monkeypatch.setattr(runtime_compat.sys, "executable", "/tmp/venv/bin/python3.11")
    monkeypatch.setattr(runtime_compat.shutil, "which", lambda _name: None)

    resolved = runtime_compat.resolve_python_executable()

    assert resolved == "/tmp/venv/bin/python3.11"


def test_ensure_local_pydeps_adds_nearest_match(tmp_path):
    _ensure_scripts_on_path()

    runtime_compat = importlib.import_module("runtime_compat")
    pydeps = tmp_path / ".pydeps"
    pydeps.mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    pydeps_str = str(pydeps)
    if pydeps_str in sys.path:
        sys.path.remove(pydeps_str)

    found = runtime_compat.ensure_local_pydeps(nested)

    assert found == pydeps
    assert sys.path[0] == pydeps_str
