#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install the Codex-compatible webnovel-writer skill bundle."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence, Union


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_SOURCE_ROOT = REPO_ROOT / "codex-skills" / "webnovel-writer"
WRAPPER_TEMPLATE = REPO_ROOT / "scripts" / "webnovel-codex"
RESTORE_SCRIPT = REPO_ROOT / "scripts" / "restore_codex_support.py"
SUPPORT_ROOT_NAME = "webnovel-writer"
RUNTIME_REQUIREMENTS = REPO_ROOT / "webnovel-writer" / "scripts" / "requirements-runtime.txt"
BOOK_PROJECT_HELPER_REL = Path("scripts") / "run_webnovel_command.py"


BOOK_PROJECT_HELPER_TEMPLATE = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Book-project shim that forwards to the installed Codex helper."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


DEFAULT_HELPER_PATH = {helper_path}
DEFAULT_PYTHON_EXEC = {python_exec}


def _fallback_helper() -> Path:
    raw = os.environ.get("CODEX_HOME")
    if raw:
        codex_home = Path(raw).expanduser().resolve()
    else:
        codex_home = (Path.home() / ".codex").resolve()
    return codex_home / "skills" / "webnovel-writer" / "scripts" / "run_webnovel_command.py"


def main(argv: Sequence[str] | None = None) -> int:
    helper = Path(DEFAULT_HELPER_PATH).expanduser().resolve()
    if not helper.is_file():
        helper = _fallback_helper()
    if not helper.is_file():
        print(f"webnovel helper not found: {{helper}}", file=sys.stderr)
        return 1
    python_exec = str(Path(DEFAULT_PYTHON_EXEC).expanduser()) if DEFAULT_PYTHON_EXEC else (getattr(sys, "executable", "") or "python3")
    proc = subprocess.run([python_exec, str(helper), *(argv or sys.argv[1:])])
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''


def _default_codex_home() -> Path:
    raw = os.environ.get("CODEX_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def _write_repo_config(skill_root: Path, repo_root: Path) -> Path:
    config_path = skill_root / "repo_config.json"
    config = {
        "repo_root": str(repo_root),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def _state_dir(codex_home: Path) -> Path:
    return codex_home / SUPPORT_ROOT_NAME


def _state_path(codex_home: Path) -> Path:
    return _state_dir(codex_home) / "install_state.json"


def _backups_root(codex_home: Path) -> Path:
    return _state_dir(codex_home) / "backups"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup_path_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return True


def _write_install_state(codex_home: Path, payload: dict) -> Path:
    path = _state_path(codex_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _resolved_python_executable(explicit_python: Optional[Union[str, Path]] = None) -> str:
    candidate = str(explicit_python or getattr(sys, "executable", "") or "python3").strip()
    return str(Path(candidate).expanduser().resolve()) if candidate else "python3"


def _install_runtime_dependencies(python_executable: str) -> None:
    subprocess.run(
        [
            python_executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(RUNTIME_REQUIREMENTS),
        ],
        check=True,
        cwd=str(REPO_ROOT),
    )


def _install_wrapper(wrapper_target: Path, helper_path: Path, python_executable: str) -> Path:
    wrapper_target.parent.mkdir(parents=True, exist_ok=True)
    template = WRAPPER_TEMPLATE.read_text(encoding="utf-8")
    rendered = template.replace("__HELPER_PATH__", str(helper_path)).replace("__PYTHON_EXEC__", python_executable)
    wrapper_target.write_text(rendered, encoding="utf-8")
    wrapper_target.chmod(wrapper_target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return wrapper_target


def _install_book_project_helper(book_project_root: Path, helper_path: Path, python_executable: str) -> Path:
    helper_target = book_project_root / BOOK_PROJECT_HELPER_REL
    helper_target.parent.mkdir(parents=True, exist_ok=True)
    rendered = BOOK_PROJECT_HELPER_TEMPLATE.format(
        helper_path=json.dumps(str(helper_path)),
        python_exec=json.dumps(str(python_executable)),
    )
    helper_target.write_text(rendered, encoding="utf-8")
    helper_target.chmod(helper_target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return helper_target


def install_codex_support(
    *,
    codex_home: Optional[Union[str, Path]] = None,
    repo_root: Optional[Union[str, Path]] = None,
    python_executable: Optional[Union[str, Path]] = None,
    install_deps: bool = False,
    book_project_root: Optional[Union[str, Path]] = None,
) -> dict[str, str]:
    resolved_codex_home = Path(codex_home).expanduser().resolve() if codex_home else _default_codex_home()
    resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else REPO_ROOT
    resolved_python = _resolved_python_executable(python_executable)
    resolved_book_project = Path(book_project_root).expanduser().resolve() if book_project_root else None

    skill_target = resolved_codex_home / "skills" / SUPPORT_ROOT_NAME
    wrapper_target = resolved_codex_home / "bin" / "webnovel-codex"
    restore_wrapper_target = resolved_codex_home / "bin" / "webnovel-codex-restore"
    book_helper_target = resolved_book_project / BOOK_PROJECT_HELPER_REL if resolved_book_project else None
    backup_dir = _backups_root(resolved_codex_home) / _timestamp()

    previous_install = {
        "skill_root_backed_up": _backup_path_if_exists(
            skill_target,
            backup_dir / "skills" / SUPPORT_ROOT_NAME,
        ),
        "wrapper_backed_up": _backup_path_if_exists(
            wrapper_target,
            backup_dir / "bin" / "webnovel-codex",
        ),
        "restore_wrapper_backed_up": _backup_path_if_exists(
            restore_wrapper_target,
            backup_dir / "bin" / "webnovel-codex-restore",
        ),
        "book_project_helper_backed_up": _backup_path_if_exists(
            book_helper_target,
            backup_dir / "book-project" / BOOK_PROJECT_HELPER_REL,
        ) if book_helper_target else False,
    }

    if skill_target.exists():
        shutil.rmtree(skill_target)
    shutil.copytree(SKILL_SOURCE_ROOT, skill_target)

    if install_deps:
        _install_runtime_dependencies(resolved_python)

    repo_config = _write_repo_config(skill_target, resolved_repo_root)
    installed_helper = skill_target / "scripts" / "run_webnovel_command.py"
    wrapper_path = _install_wrapper(wrapper_target, installed_helper, resolved_python)
    restore_wrapper_path = _install_wrapper(restore_wrapper_target, RESTORE_SCRIPT, resolved_python)
    book_project_helper_path = (
        _install_book_project_helper(resolved_book_project, installed_helper, resolved_python)
        if resolved_book_project
        else None
    )
    install_state = _write_install_state(
        resolved_codex_home,
        {
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "repo_root": str(resolved_repo_root),
            "python_executable": resolved_python,
            "runtime_requirements": str(RUNTIME_REQUIREMENTS),
            "backup_dir": str(backup_dir),
            "targets": {
                "skill_root": str(skill_target),
                "wrapper_path": str(wrapper_path),
                "restore_wrapper_path": str(restore_wrapper_path),
                "book_project_helper_path": str(book_project_helper_path) if book_project_helper_path else "",
            },
            "previous_install": previous_install,
        },
    )

    return {
        "codex_home": str(resolved_codex_home),
        "skill_root": str(skill_target),
        "repo_config": str(repo_config),
        "wrapper_path": str(wrapper_path),
        "restore_wrapper_path": str(restore_wrapper_path),
        "install_state": str(install_state),
        "python_executable": resolved_python,
        "runtime_requirements": str(RUNTIME_REQUIREMENTS),
        "book_project_helper_path": str(book_project_helper_path) if book_project_helper_path else "",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Install Codex support for webnovel-writer")
    parser.add_argument("--codex-home", default=None, help="Codex home directory (default: $CODEX_HOME or ~/.codex)")
    parser.add_argument("--repo-root", default=None, help="Repository root (default: current repo)")
    parser.add_argument("--python-executable", default=None, help="Python interpreter to pin into wrapper and use for runtime deps")
    parser.add_argument("--skip-deps", action="store_true", help="Skip installing runtime dependencies into the selected Python")
    parser.add_argument("--book-project-root", default=None, help="Optional book project root where scripts/run_webnovel_command.py shim should be installed")
    args = parser.parse_args(argv)

    result = install_codex_support(
        codex_home=args.codex_home,
        repo_root=args.repo_root,
        python_executable=args.python_executable,
        install_deps=not args.skip_deps,
        book_project_root=args.book_project_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
