#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_codex_cli_module():
    _ensure_scripts_on_path()
    import codex_cli as codex_cli_module

    return codex_cli_module


def _load_engine_module():
    _ensure_scripts_on_path()
    from codex_controllers import engine as engine_module

    return engine_module


def _load_init_flow_module():
    _ensure_scripts_on_path()
    from codex_controllers import init_flow as init_flow_module

    return init_flow_module


def test_prepare_command_routes_init_to_external_tui(tmp_path):
    module = _load_codex_cli_module()

    payload = module.prepare_command(
        "/webnovel-writer:webnovel-init",
        mode="codex",
        workspace_root=tmp_path,
    )

    assert payload["status"] == "ok"
    assert payload["command"]["name"] == "webnovel-init"
    assert payload["action"]["type"] == "external_init"
    assert payload["action"]["ui"] == "prompt_toolkit"
    assert str(tmp_path.resolve()) in payload["action"]["command"]
    assert "不再在 Codex 对话里逐项问答" in payload["message"]


def test_stale_codex_init_session_is_closed_and_handed_back_to_external_tui(tmp_path):
    module = _load_codex_cli_module()
    engine = _load_engine_module()
    init_flow = _load_init_flow_module()

    engine.start_session(project_root=tmp_path, controller=init_flow.CONTROLLER_NAME)

    payload = module.prepare_command("继续", mode="codex", workspace_root=tmp_path)

    assert payload["status"] == "ok"
    assert payload["action"]["type"] == "external_init"
    assert "检测到旧的 Codex init 会话" in payload["message"]

    session_path = tmp_path / ".webnovel" / "controller_sessions" / f"{init_flow.CONTROLLER_NAME}.json"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    assert session["active"] is False
    assert session["step_id"] == "abandoned"
