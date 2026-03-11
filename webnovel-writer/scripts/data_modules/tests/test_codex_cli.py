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

    payload = module.prepare_command(["webnovel-plan", "1"], mode="codex")

    assert payload["status"] == "ok"
    assert payload["command"]["name"] == "webnovel-plan"
    assert payload["command"]["args"] == ["1"]
    assert payload["project_root"] == str(project_root)
    assert payload["action"]["type"] == "follow_skill"
    assert payload["action"]["skill_path"].endswith("webnovel-plan/SKILL.md")


def test_prepare_command_returns_desktop_strict_skill_for_review(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()

    monkeypatch.setattr(module, "_resolve_project_root", lambda **_kwargs: project_root)

    payload = module.prepare_command(["webnovel-review", "1-5"], mode="codex")

    assert payload["status"] == "ok"
    assert payload["command"]["name"] == "webnovel-review"
    assert payload["project_root"] == str(project_root)
    assert payload["action"]["type"] == "follow_skill"
    assert payload["action"]["desktop_mode"] == "strict_follow_skill"
    assert payload["action"]["execution_model"] == "desktop_strict_follow_skill"
    assert "desktop_contract" in payload["action"]["topology_note"]
    assert payload["action"]["skill_path"].endswith("webnovel-review/SKILL.md")
    assert payload["action"]["desktop_contract"]["prepare_script"].endswith("review_prepare.py")
    assert payload["action"]["desktop_contract"]["finalize_script"].endswith("review_finalize.py")
    assert "review_agents_runner.py" in payload["action"]["desktop_contract"]["forbid_direct_runner"]


def test_prepare_command_returns_source_workflow_for_write_in_codex_mode(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()

    monkeypatch.setattr(module, "_resolve_project_root", lambda **_kwargs: project_root)
    monkeypatch.setattr(module, "resolve_python_executable", lambda: "/usr/bin/python3")

    payload = module.prepare_command(["webnovel-write", "8", "--fast"], mode="codex")

    assert payload["status"] == "ok"
    assert payload["command"]["name"] == "webnovel-write"
    assert payload["project_root"] == str(project_root)
    assert payload["action"]["type"] == "run_source_workflow"
    assert payload["action"]["workflow_id"] == "webnovel-write"
    assert payload["action"]["script_path"].endswith("codex_write_workflow.py")
    assert payload["action"]["command_line"][:2] == ["/usr/bin/python3", payload["action"]["script_path"]]
    assert "--chapter" in payload["action"]["command_line"]
    assert "8" in payload["action"]["command_line"]
    assert payload["action"]["command_line"][-2:] == ["--mode", "fast"]


def test_prepare_command_accepts_single_token_shell_style_write(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()

    monkeypatch.setattr(module, "_resolve_project_root", lambda **_kwargs: project_root)
    monkeypatch.setattr(module, "resolve_python_executable", lambda: "/usr/bin/python3")

    payload = module.prepare_command(["webnovel-write 19"], mode="codex")

    assert payload["status"] == "ok"
    assert payload["command"]["name"] == "webnovel-write"
    assert payload["command"]["args"] == ["19"]
    assert payload["action"]["type"] == "run_source_workflow"
    assert "--chapter" in payload["action"]["command_line"]
    assert "19" in payload["action"]["command_line"]


def test_prepare_command_returns_source_workflow_for_review_in_shell_mode(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()

    monkeypatch.setattr(module, "_resolve_project_root", lambda **_kwargs: project_root)
    monkeypatch.setattr(module, "resolve_python_executable", lambda: "/usr/bin/python3")

    payload = module.prepare_command(["webnovel-review", "1-5"], mode="shell")

    assert payload["status"] == "ok"
    assert payload["action"]["type"] == "run_source_workflow"
    assert payload["action"]["workflow_id"] == "webnovel-review"
    assert payload["action"]["script_path"].endswith("codex_review_workflow.py")
    assert payload["action"]["command_line"][:2] == ["/usr/bin/python3", payload["action"]["script_path"]]
    assert payload["action"]["command_line"][-2:] == ["--range", "1-5"]


def test_prepare_command_returns_source_workflow_for_write_in_shell_mode(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()

    monkeypatch.setattr(module, "_resolve_project_root", lambda **_kwargs: project_root)
    monkeypatch.setattr(module, "resolve_python_executable", lambda: "/usr/bin/python3")

    payload = module.prepare_command(["webnovel-write", "8", "--fast"], mode="shell")

    assert payload["status"] == "ok"
    assert payload["action"]["type"] == "run_source_workflow"
    assert payload["action"]["workflow_id"] == "webnovel-write"
    assert payload["action"]["script_path"].endswith("codex_write_workflow.py")
    assert payload["action"]["command_line"][:2] == ["/usr/bin/python3", payload["action"]["script_path"]]
    assert "--chapter" in payload["action"]["command_line"]
    assert "8" in payload["action"]["command_line"]
    assert payload["action"]["command_line"][-2:] == ["--mode", "fast"]


def test_prepare_command_returns_choices_when_project_missing(monkeypatch):
    module = _load_module()

    def _missing_root(**_kwargs):
        raise FileNotFoundError("missing project")

    monkeypatch.setattr(module, "_resolve_project_root", _missing_root)

    payload = module.prepare_command(["webnovel-review", "1"], mode="codex")

    assert payload["status"] == "needs_input"
    assert payload["command"]["name"] == "webnovel-review"
    assert any("webnovel-init" in option["description"] for option in payload["options"])


def test_prepare_command_accepts_natural_language(monkeypatch):
    module = _load_module()

    payload = module.prepare_command("请使用 webnovel-writer 初始化一个小说项目。", mode="codex")

    assert payload["status"] == "ok"
    assert payload["command"]["name"] == "webnovel-init"
    assert payload["command"]["args"] == []
    assert payload["action"]["type"] == "external_init"
    assert payload["action"]["ui"] == "prompt_toolkit"
    assert "/webnovel-writer:webnovel-init" in payload["action"]["command"]


def test_start_dashboard_uses_resolved_python(monkeypatch, tmp_path):
    module = _load_module()

    calls = {}

    class _FakeProcess:
        pid = 12345

    class _FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_popen(cmd, **kwargs):
        calls["cmd"] = list(cmd)
        calls["kwargs"] = kwargs
        return _FakeProcess()

    monkeypatch.setattr(module, "resolve_python_executable", lambda: "/usr/bin/python3")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: _FakeCompleted())
    monkeypatch.setattr(module.subprocess, "Popen", _fake_popen)

    result = module.start_dashboard(tmp_path)

    assert result["status"] == "started"
    assert result["pid"] == 12345
    assert result["url"] == "http://127.0.0.1:18765"
    assert result["browser_requested"] is True
    assert calls["cmd"][:3] == ["/usr/bin/python3", "-m", "dashboard.server"]
    assert "--no-browser" not in calls["cmd"]
    assert "18765" in calls["cmd"]
    assert calls["kwargs"]["cwd"] == str(module.REPO_PACKAGE_ROOT)
    assert str(module.REPO_PACKAGE_ROOT) in calls["kwargs"]["env"]["PYTHONPATH"]


def test_start_dashboard_reports_missing_runtime_dependencies(monkeypatch, tmp_path):
    module = _load_module()

    class _FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "ModuleNotFoundError: No module named 'fastapi'"

    monkeypatch.setattr(module, "resolve_python_executable", lambda: "/usr/bin/python3")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: _FakeCompleted())

    try:
        module.start_dashboard(tmp_path)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        message = str(exc)
        assert "Dashboard 依赖未就绪" in message
        assert "dashboard/requirements.txt" in message
        assert "fastapi" in message


def test_render_payload_for_started_dashboard_mentions_auto_browser():
    module = _load_module()

    rendered = module._render_payload(
        {
            "status": "started",
            "pid": 12345,
            "url": "http://127.0.0.1:18765",
            "browser_requested": True,
        }
    )

    assert "/webnovel-writer:webnovel-dashboard 已启动。" in rendered
    assert "http://127.0.0.1:18765" in rendered
    assert "自动打开默认浏览器" in rendered


def test_render_payload_for_source_workflow_mentions_script():
    module = _load_module()

    rendered = module._render_payload(
        {
            "status": "ok",
            "project_root": "/tmp/book",
            "command": {
                "slash_command": "/webnovel-writer:webnovel-review 1-5",
            },
            "action": {
                "type": "run_source_workflow",
                "script_path": "/tmp/codex_review_workflow.py",
                "command_line": ["/usr/bin/python3", "/tmp/codex_review_workflow.py", "--range", "1-5"],
            },
        }
    )

    assert "run_source_workflow" in rendered
    assert "/tmp/codex_review_workflow.py" in rendered
    assert "--range 1-5" in rendered


def test_main_shell_init_runs_wizard(monkeypatch):
    module = _load_module()
    calls = {}

    monkeypatch.setattr(
        module,
        "run_init_wizard",
        lambda workspace_root=None: calls.setdefault("workspace_root", workspace_root) or {"status": "confirmed"},
    )
    monkeypatch.setattr(
        module,
        "ensure_utf8_locale",
        lambda: calls.__setitem__("locale", calls.get("locale", 0) + 1) or "en_US.UTF-8",
    )

    exit_code = module.main(["--mode", "shell", "/webnovel-writer:webnovel-init"])

    assert exit_code == 0
    assert "workspace_root" in calls
    assert calls["locale"] == 1


def test_main_shell_init_json_does_not_run_wizard(monkeypatch, capsys):
    module = _load_module()
    calls = {"count": 0}

    monkeypatch.setattr(
        module,
        "run_init_wizard",
        lambda workspace_root=None: calls.__setitem__("count", calls["count"] + 1),
    )

    exit_code = module.main(["--mode", "shell", "--json", "/webnovel-writer:webnovel-init"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert calls["count"] == 0
    assert '"name": "webnovel-init"' in captured.out


def test_main_shell_init_handles_keyboardinterrupt(monkeypatch, capsys):
    module = _load_module()

    monkeypatch.setattr(
        module,
        "run_init_wizard",
        lambda workspace_root=None: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    exit_code = module.main(["--mode", "shell", "/webnovel-writer:webnovel-init"])
    captured = capsys.readouterr()

    assert exit_code == 130
    assert "已取消" in captured.err
