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


def test_ensure_utf8_locale_upgrades_c_locale(monkeypatch):
    _ensure_scripts_on_path()

    runtime_compat = importlib.import_module("runtime_compat")
    state = {"current": "C", "calls": []}

    def _fake_setlocale(category, value=None):
        if value is None:
            return state["current"]
        state["calls"].append(value)
        if value == "en_US.UTF-8":
            state["current"] = value
            return value
        raise runtime_compat.locale.Error("unsupported locale")

    monkeypatch.setattr(runtime_compat.locale, "setlocale", _fake_setlocale)
    monkeypatch.setattr(runtime_compat.sys, "platform", "darwin")
    monkeypatch.setenv("LC_CTYPE", "C")
    monkeypatch.setenv("LANG", "")

    selected = runtime_compat.ensure_utf8_locale()

    assert selected == "en_US.UTF-8"
    assert state["calls"][0] == "en_US.UTF-8"
    assert runtime_compat.os.environ["LC_CTYPE"] == "en_US.UTF-8"


def test_ensure_utf8_locale_keeps_existing_utf8_locale(monkeypatch):
    _ensure_scripts_on_path()

    runtime_compat = importlib.import_module("runtime_compat")
    calls = {"count": 0}

    def _fake_setlocale(category, value=None):
        if value is None:
            return "zh_CN.UTF-8"
        calls["count"] += 1
        return value

    monkeypatch.setattr(runtime_compat.locale, "setlocale", _fake_setlocale)

    selected = runtime_compat.ensure_utf8_locale()

    assert selected == "zh_CN.UTF-8"
    assert calls["count"] == 0
