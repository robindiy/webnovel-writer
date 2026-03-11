#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path

import pytest


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_registry_module():
    _ensure_scripts_on_path()
    import codex_command_registry as registry_module

    return registry_module


def test_parse_slash_init_command():
    module = _load_registry_module()

    command = module.parse_command_text("/webnovel-writer:webnovel-init")

    assert command.name == "webnovel-init"
    assert command.args == ()
    assert command.slash_command == "/webnovel-writer:webnovel-init"
    assert command.skill_name == "webnovel-init"


def test_parse_slash_write_command_with_args():
    module = _load_registry_module()

    command = module.parse_command_text("/webnovel-writer:webnovel-write 1")

    assert command.name == "webnovel-write"
    assert command.args == ("1",)
    assert command.requires_project is True


def test_parse_shell_fallback_command():
    module = _load_registry_module()

    command = module.parse_argv(["webnovel-review", "1-5"])

    assert command.name == "webnovel-review"
    assert command.args == ("1-5",)
    assert command.slash_command == "/webnovel-writer:webnovel-review 1-5"


def test_parse_single_token_shell_write_command():
    module = _load_registry_module()

    command = module.parse_argv(["webnovel-write 19"])

    assert command.name == "webnovel-write"
    assert command.args == ("19",)
    assert command.slash_command == "/webnovel-writer:webnovel-write 19"


def test_parse_single_token_shell_write_command_with_mode():
    module = _load_registry_module()

    command = module.parse_argv(["webnovel-write 19 --fast"])

    assert command.name == "webnovel-write"
    assert command.args == ("19", "--fast")
    assert command.slash_command == "/webnovel-writer:webnovel-write 19 --fast"


def test_reject_unknown_command():
    module = _load_registry_module()

    with pytest.raises(ValueError) as exc:
        module.parse_command_text("/webnovel-writer:webnovel-unknown")

    assert "webnovel-unknown" in str(exc.value)


def test_parse_natural_language_init_command():
    module = _load_registry_module()

    command = module.parse_argv(["请使用 webnovel-writer 初始化一个小说项目。"])

    assert command.name == "webnovel-init"
    assert command.args == ()
    assert command.slash_command == "/webnovel-writer:webnovel-init"


def test_parse_natural_language_write_command():
    module = _load_registry_module()

    command = module.parse_argv(["请使用 webnovel-writer 写第 12 章。"])

    assert command.name == "webnovel-write"
    assert command.args == ("12",)
    assert command.slash_command == "/webnovel-writer:webnovel-write 12"


def test_parse_natural_language_write_command_with_webnovel_write_keyword():
    module = _load_registry_module()

    command = module.parse_argv(["请使用webnovel-write 开始撰写第19章"])

    assert command.name == "webnovel-write"
    assert command.args == ("19",)
    assert command.slash_command == "/webnovel-writer:webnovel-write 19"


def test_parse_natural_language_review_intent_overrides_webnovel_write_keyword():
    module = _load_registry_module()

    command = module.parse_argv(["请使用webnovel-write 开始审查第8章"])

    assert command.name == "webnovel-review"
    assert command.args == ("8",)
    assert command.slash_command == "/webnovel-writer:webnovel-review 8"


def test_parse_natural_language_review_range_command():
    module = _load_registry_module()

    command = module.parse_argv(["请使用 webnovel-writer 审查第 1 到 5 章。"])

    assert command.name == "webnovel-review"
    assert command.args == ("1-5",)
    assert command.slash_command == "/webnovel-writer:webnovel-review 1-5"


def test_parse_shell_skill_name_as_write_shorthand():
    module = _load_registry_module()

    command = module.parse_argv(["webnovel-writer", "16"])

    assert command.name == "webnovel-write"
    assert command.args == ("16",)
    assert command.slash_command == "/webnovel-writer:webnovel-write 16"


def test_parse_natural_language_skill_name_shorthand():
    module = _load_registry_module()

    command = module.parse_argv(["webnovel-writer 16"])

    assert command.name == "webnovel-write"
    assert command.args == ("16",)
    assert command.slash_command == "/webnovel-writer:webnovel-write 16"
