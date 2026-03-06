#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_module():
    _ensure_scripts_on_path()
    import codex_cli as codex_cli_module

    return codex_cli_module


def test_prepare_command_returns_skill_payload(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()

    monkeypatch.setattr(module, "_resolve_project_root", lambda **_kwargs: project_root)

    payload = module.prepare_command(["webnovel-write", "1"], mode="codex")

    assert payload["status"] == "ok"
    assert payload["command"]["name"] == "webnovel-write"
    assert payload["command"]["args"] == ["1"]
    assert payload["project_root"] == str(project_root)
    assert payload["action"]["type"] == "follow_skill"
    assert payload["action"]["skill_path"].endswith("webnovel-write/SKILL.md")


def test_prepare_command_returns_choices_when_project_missing(monkeypatch):
    module = _load_module()

    def _missing_root(**_kwargs):
        raise FileNotFoundError("missing project")

    monkeypatch.setattr(module, "_resolve_project_root", _missing_root)

    payload = module.prepare_command(["webnovel-review", "1"], mode="codex")

    assert payload["status"] == "needs_input"
    assert payload["command"]["name"] == "webnovel-review"
    assert any("webnovel-init" in option["description"] for option in payload["options"])


def test_start_dashboard_uses_resolved_python(monkeypatch, tmp_path):
    module = _load_module()

    calls = {}

    class _FakeProcess:
        pid = 12345

    def _fake_popen(cmd, **kwargs):
        calls["cmd"] = list(cmd)
        calls["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr(module, "resolve_python_executable", lambda: "/usr/bin/python3")
    monkeypatch.setattr(module.subprocess, "Popen", _fake_popen)

    result = module.start_dashboard(tmp_path, host="127.0.0.1", port=8765, open_browser=False)

    assert result["status"] == "started"
    assert result["pid"] == 12345
    assert calls["cmd"][:3] == ["/usr/bin/python3", "-m", "dashboard.server"]
    assert calls["kwargs"]["cwd"] == str(module.REPO_PACKAGE_ROOT)
    assert str(module.REPO_PACKAGE_ROOT) in calls["kwargs"]["env"]["PYTHONPATH"]
