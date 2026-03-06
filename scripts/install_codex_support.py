#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install the Codex-compatible webnovel-writer skill bundle."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_SOURCE_ROOT = REPO_ROOT / "codex-skills" / "webnovel-writer"
WRAPPER_TEMPLATE = REPO_ROOT / "scripts" / "webnovel-codex"
RESTORE_SCRIPT = REPO_ROOT / "scripts" / "restore_codex_support.py"
SUPPORT_ROOT_NAME = "webnovel-writer"


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


def _install_wrapper(wrapper_target: Path, helper_path: Path) -> Path:
    wrapper_target.parent.mkdir(parents=True, exist_ok=True)
    template = WRAPPER_TEMPLATE.read_text(encoding="utf-8")
    rendered = template.replace("__HELPER_PATH__", str(helper_path))
    wrapper_target.write_text(rendered, encoding="utf-8")
    wrapper_target.chmod(wrapper_target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return wrapper_target


def install_codex_support(
    *,
    codex_home: Optional[Union[str, Path]] = None,
    repo_root: Optional[Union[str, Path]] = None,
) -> dict[str, str]:
    resolved_codex_home = Path(codex_home).expanduser().resolve() if codex_home else _default_codex_home()
    resolved_repo_root = Path(repo_root).expanduser().resolve() if repo_root else REPO_ROOT

    skill_target = resolved_codex_home / "skills" / SUPPORT_ROOT_NAME
    wrapper_target = resolved_codex_home / "bin" / "webnovel-codex"
    restore_wrapper_target = resolved_codex_home / "bin" / "webnovel-codex-restore"
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
    }

    if skill_target.exists():
        shutil.rmtree(skill_target)
    shutil.copytree(SKILL_SOURCE_ROOT, skill_target)

    repo_config = _write_repo_config(skill_target, resolved_repo_root)
    wrapper_path = _install_wrapper(wrapper_target, skill_target / "scripts" / "run_webnovel_command.py")
    restore_wrapper_path = _install_wrapper(restore_wrapper_target, RESTORE_SCRIPT)
    install_state = _write_install_state(
        resolved_codex_home,
        {
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "repo_root": str(resolved_repo_root),
            "backup_dir": str(backup_dir),
            "targets": {
                "skill_root": str(skill_target),
                "wrapper_path": str(wrapper_path),
                "restore_wrapper_path": str(restore_wrapper_path),
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
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Codex support for webnovel-writer")
    parser.add_argument("--codex-home", default=None, help="Codex home directory (default: $CODEX_HOME or ~/.codex)")
    parser.add_argument("--repo-root", default=None, help="Repository root (default: current repo)")
    args = parser.parse_args()

    result = install_codex_support(codex_home=args.codex_home, repo_root=args.repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
