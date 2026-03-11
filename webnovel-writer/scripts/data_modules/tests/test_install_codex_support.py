#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib.util
import json
from pathlib import Path


BOOK_PROJECT_HELPER_REL = Path("scripts") / "run_webnovel_command.py"


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


def _book_helper_path(book_root: Path) -> Path:
    return book_root / BOOK_PROJECT_HELPER_REL


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
    assert state["targets"]["book_project_helper_path"] == ""
    assert state["previous_install"]["skill_root_backed_up"] is True
    assert state["previous_install"]["wrapper_backed_up"] is True
    assert state["previous_install"]["book_project_helper_backed_up"] is False
    backup_dir = Path(state["backup_dir"])
    assert (backup_dir / "skills" / "webnovel-writer" / "SKILL.md").read_text(encoding="utf-8") == "legacy skill"
    assert (backup_dir / "bin" / "webnovel-codex").read_text(encoding="utf-8").startswith("#!/bin/sh")
    assert restore_wrapper.is_file()
    assert "restore_codex_support.py" in restore_wrapper.read_text(encoding="utf-8")


def test_install_codex_support_installs_book_project_helper(tmp_path):
    module = _install_module()
    codex_home = tmp_path / ".codex"
    book_root = tmp_path / "book-project"

    result = module.install_codex_support(
        codex_home=codex_home,
        repo_root=_repo_root(),
        python_executable="/tmp/fake-venv/bin/python3.12",
        book_project_root=book_root,
    )

    helper_path = _book_helper_path(book_root)
    installed_helper = Path(result["skill_root"]) / "scripts" / "run_webnovel_command.py"
    state = json.loads((codex_home / "webnovel-writer" / "install_state.json").read_text(encoding="utf-8"))
    helper_text = helper_path.read_text(encoding="utf-8")

    assert result["book_project_helper_path"] == str(helper_path)
    assert state["targets"]["book_project_helper_path"] == str(helper_path)
    assert state["previous_install"]["book_project_helper_backed_up"] is False
    assert helper_path.is_file()
    assert helper_path.stat().st_mode & 0o111
    assert f'DEFAULT_HELPER_PATH = "{installed_helper}"' in helper_text
    assert f'DEFAULT_PYTHON_EXEC = "{result["python_executable"]}"' in helper_text
    assert 'os.environ.get("CODEX_HOME")' in helper_text
    assert 'return codex_home / "skills" / "webnovel-writer" / "scripts" / "run_webnovel_command.py"' in helper_text


def test_install_codex_support_backs_up_existing_book_project_helper(tmp_path):
    module = _install_module()
    codex_home = tmp_path / ".codex"
    book_root = tmp_path / "book-project"
    helper_path = _book_helper_path(book_root)
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("legacy helper\n", encoding="utf-8")

    module.install_codex_support(codex_home=codex_home, repo_root=_repo_root(), book_project_root=book_root)

    state = json.loads((codex_home / "webnovel-writer" / "install_state.json").read_text(encoding="utf-8"))
    backup_dir = Path(state["backup_dir"])

    assert state["previous_install"]["book_project_helper_backed_up"] is True
    assert (backup_dir / "book-project" / "scripts" / "run_webnovel_command.py").read_text(encoding="utf-8") == "legacy helper\n"


def test_install_wrapper_bootstraps_utf8_locale(tmp_path):
    module = _install_module()
    codex_home = tmp_path / ".codex"

    result = module.install_codex_support(codex_home=codex_home, repo_root=_repo_root())
    wrapper_path = Path(result["wrapper_path"])
    wrapper_text = wrapper_path.read_text(encoding="utf-8")

    assert 'if [[ -z "${LC_CTYPE:-}" || "${LC_CTYPE}" == "C" || "${LC_CTYPE}" == "POSIX" ]]; then' in wrapper_text
    assert 'export LC_CTYPE="en_US.UTF-8"' in wrapper_text
    assert 'export LANG="en_US.UTF-8"' in wrapper_text


def test_install_wrapper_pins_current_python_interpreter(tmp_path):
    module = _install_module()
    codex_home = tmp_path / ".codex"

    result = module.install_codex_support(
        codex_home=codex_home,
        repo_root=_repo_root(),
        python_executable="/tmp/fake-venv/bin/python3.12",
    )
    wrapper_text = Path(result["wrapper_path"]).read_text(encoding="utf-8")

    assert f'DEFAULT_PYTHON_EXEC="{result["python_executable"]}"' in wrapper_text


def test_main_installs_runtime_dependencies_by_default(monkeypatch, capsys, tmp_path):
    module = _install_module()
    calls = {}

    monkeypatch.setattr(module, "_default_codex_home", lambda: tmp_path / ".codex")
    monkeypatch.setattr(
        module,
        "_install_runtime_dependencies",
        lambda python_executable: calls.setdefault("python_executable", python_executable),
    )

    exit_code = module.main([])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert calls["python_executable"]
    assert '"runtime_requirements"' in captured.out


def test_restore_codex_support_recovers_previous_install(tmp_path):
    install_module = _install_module()
    restore_module = _restore_module()
    codex_home = tmp_path / ".codex"
    book_root = tmp_path / "book-project"

    old_skill = codex_home / "skills" / "webnovel-writer"
    old_wrapper = codex_home / "bin" / "webnovel-codex"
    old_book_helper = _book_helper_path(book_root)
    old_skill.mkdir(parents=True, exist_ok=True)
    (old_skill / "SKILL.md").write_text("legacy skill", encoding="utf-8")
    old_wrapper.parent.mkdir(parents=True, exist_ok=True)
    old_wrapper.write_text("#!/bin/sh\necho legacy\n", encoding="utf-8")
    old_book_helper.parent.mkdir(parents=True, exist_ok=True)
    old_book_helper.write_text("legacy helper\n", encoding="utf-8")

    install_module.install_codex_support(codex_home=codex_home, repo_root=_repo_root(), book_project_root=book_root)

    restored = restore_module.restore_codex_support(codex_home=codex_home)

    assert restored["restored_skill"] is True
    assert restored["restored_wrapper"] is True
    assert restored["restored_book_project_helper"] is True
    assert (codex_home / "skills" / "webnovel-writer" / "SKILL.md").read_text(encoding="utf-8") == "legacy skill"
    assert (codex_home / "bin" / "webnovel-codex").read_text(encoding="utf-8").startswith("#!/bin/sh")
    assert old_book_helper.read_text(encoding="utf-8") == "legacy helper\n"
    assert not (codex_home / "webnovel-writer" / "install_state.json").exists()


def test_restore_codex_support_removes_fresh_install_when_no_backup(tmp_path):
    install_module = _install_module()
    restore_module = _restore_module()
    codex_home = tmp_path / ".codex"
    book_root = tmp_path / "book-project"

    install_module.install_codex_support(codex_home=codex_home, repo_root=_repo_root(), book_project_root=book_root)
    restored = restore_module.restore_codex_support(codex_home=codex_home)

    assert restored["restored_skill"] is False
    assert restored["restored_wrapper"] is False
    assert restored["restored_book_project_helper"] is False
    assert not (codex_home / "skills" / "webnovel-writer").exists()
    assert not (codex_home / "bin" / "webnovel-codex").exists()
    assert not _book_helper_path(book_root).exists()
    assert not (codex_home / "webnovel-writer" / "install_state.json").exists()
