#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_engine_module():
    _ensure_scripts_on_path()
    from codex_controllers import engine as engine_module

    return engine_module


def _load_demo_flow_module():
    _ensure_scripts_on_path()
    from codex_controllers import demo_flow as demo_flow_module

    return demo_flow_module


def _load_codex_cli_module():
    _ensure_scripts_on_path()
    import codex_cli as codex_cli_module

    return codex_cli_module


def _load_registry_module():
    _ensure_scripts_on_path()
    import codex_command_registry as registry_module

    return registry_module


def _make_book_project(tmp_path: Path) -> Path:
    project_root = (tmp_path / "book").resolve()
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")
    return project_root


def test_controller_session_lifecycle(tmp_path):
    engine = _load_engine_module()
    demo_flow = _load_demo_flow_module()
    project_root = _make_book_project(tmp_path)

    session = engine.start_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME)

    assert session["controller"] == demo_flow.CONTROLLER_NAME
    assert session["active"] is True
    assert session["step_id"] == "step-1"

    loaded = engine.load_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME)
    assert loaded == session

    invalid = engine.advance_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME, user_input="随便写点什么")
    assert invalid["step_id"] == "step-1"
    assert invalid["active"] is True
    assert invalid["last_error"] == "invalid-option"

    finished = engine.finish_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME)
    assert finished["active"] is False
    assert finished["step_id"] == "finished"

    persisted = engine.load_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME)
    assert persisted["active"] is False


def test_demo_flow_renders_five_controlled_steps_and_artifacts(tmp_path):
    engine = _load_engine_module()
    demo_flow = _load_demo_flow_module()
    project_root = _make_book_project(tmp_path)

    session = engine.start_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME)
    action = demo_flow.build_controller_action(session)
    assert action["type"] == "controller_step"
    assert action["step_id"] == "step-1"
    assert "Controller Demo 1/5" in action["message"]

    session = engine.advance_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME, user_input="继续")
    action = demo_flow.build_controller_action(session)
    assert action["step_id"] == "step-2"
    assert [option["id"] for option in action["options"]] == ["standard", "strict"]

    session = engine.advance_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME, user_input="标准模式")
    action = demo_flow.build_controller_action(session)
    assert action["step_id"] == "step-3"
    assert "selected profile: standard" in action["message"]

    session = engine.advance_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME, user_input="确认执行")
    action = demo_flow.build_controller_action(session)
    assert action["step_id"] == "step-4"
    assert "Controller Demo 4/5" in action["message"]

    artifacts = [
        project_root / "controller-demo" / "01-session.md",
        project_root / "controller-demo" / "02-choice.json",
        project_root / "controller-demo" / "03-result.md",
    ]
    for artifact in artifacts:
        assert artifact.is_file()

    choice_payload = json.loads(artifacts[1].read_text(encoding="utf-8"))
    assert choice_payload["profile"] == "standard"
    assert choice_payload["controller"] == demo_flow.CONTROLLER_NAME

    session = engine.advance_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME, user_input="继续验证")
    action = demo_flow.build_controller_action(session)
    assert action["step_id"] == "step-5"
    assert action["done"] is True
    assert session["active"] is False
    assert not (project_root / "docs" / "plans").exists()


def test_demo_flow_invalid_input_re_renders_current_step(tmp_path):
    engine = _load_engine_module()
    demo_flow = _load_demo_flow_module()
    project_root = _make_book_project(tmp_path)

    engine.start_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME)
    session = engine.advance_session(project_root=project_root, controller=demo_flow.CONTROLLER_NAME, user_input="不是可用选项")

    action = demo_flow.build_controller_action(session)
    assert action["step_id"] == "step-1"
    assert "仅支持当前步骤给出的固定选项" in action["message"]
    assert [option["label"] for option in action["options"]] == ["继续", "取消"]


def test_registry_parses_controller_demo_commands():
    module = _load_registry_module()

    slash = module.parse_command_text("/webnovel-writer:webnovel-controller-demo")
    assert slash.name == "webnovel-controller-demo"
    assert slash.args == ()

    shell = module.parse_argv(["controller-demo"])
    assert shell.name == "webnovel-controller-demo"
    assert shell.slash_command == "/webnovel-writer:webnovel-controller-demo"

    natural = module.parse_argv(["开始控制器测试"])
    assert natural.name == "webnovel-controller-demo"


def test_prepare_command_routes_demo_and_active_session(monkeypatch, tmp_path):
    module = _load_codex_cli_module()
    project_root = _make_book_project(tmp_path)

    monkeypatch.setattr(module, "_resolve_project_root", lambda **_kwargs: project_root)

    initial = module.prepare_command("开始控制器测试", mode="codex")
    assert initial["status"] == "ok"
    assert initial["command"]["name"] == "webnovel-controller-demo"
    assert initial["action"]["type"] == "controller_step"
    assert initial["action"]["step_id"] == "step-1"
    assert initial["action"]["done"] is False
    assert initial["action"].get("skill_path") is None

    next_step = module.prepare_command("继续", mode="codex")
    assert next_step["action"]["type"] == "controller_step"
    assert next_step["action"]["step_id"] == "step-2"

    escape = module.prepare_command(["webnovel-write", "1"], mode="codex")
    assert escape["command"]["name"] == "webnovel-write"
    assert escape["action"]["type"] == "follow_skill"
