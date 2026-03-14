#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Restore the user's Codex environment to the pre-install webnovel state."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Optional, Union


SUPPORT_ROOT_NAME = "webnovel-writer"


def _default_codex_home() -> Path:
    raw = os.environ.get("CODEX_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def _state_dir(codex_home: Path) -> Path:
    return codex_home / SUPPORT_ROOT_NAME


def _state_path(codex_home: Path) -> Path:
    return _state_dir(codex_home) / "install_state.json"


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()


def _restore_path(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        _remove_path(destination)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return True


def _load_install_state(codex_home: Path) -> tuple[Path, dict]:
    state_path = _state_path(codex_home)
    if not state_path.exists():
        raise FileNotFoundError(f"Install state not found: {state_path}")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    return state_path, payload


def _cleanup_state(codex_home: Path, backup_dir: Path) -> None:
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    state_dir = _state_dir(codex_home)
    state_path = _state_path(codex_home)
    if state_path.exists():
        state_path.unlink()
    current = state_dir
    while current != codex_home and current.exists():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def restore_codex_support(*, codex_home: Optional[Union[str, Path]] = None) -> dict[str, Union[str, bool]]:
    resolved_codex_home = Path(codex_home).expanduser().resolve() if codex_home else _default_codex_home()
    _, state = _load_install_state(resolved_codex_home)

    targets = state.get("targets", {})
    previous_install = state.get("previous_install", {})
    backup_dir = Path(state["backup_dir"]).expanduser().resolve()

    skill_target = Path(targets["skill_root"]).expanduser().resolve()
    wrapper_target = Path(targets["wrapper_path"]).expanduser().resolve()
    restore_wrapper_target = Path(targets["restore_wrapper_path"]).expanduser().resolve()
    shortcut_wrapper_targets = {
        name: Path(path).expanduser().resolve()
        for name, path in (targets.get("shortcut_wrapper_paths") or {}).items()
    }

    _remove_path(skill_target)
    _remove_path(wrapper_target)
    _remove_path(restore_wrapper_target)
    for target in shortcut_wrapper_targets.values():
        _remove_path(target)

    restored_skill = False
    restored_wrapper = False
    restored_restore_wrapper = False
    restored_shortcut_wrappers: dict[str, bool] = {}

    if previous_install.get("skill_root_backed_up"):
        restored_skill = _restore_path(
            backup_dir / "skills" / SUPPORT_ROOT_NAME,
            skill_target,
        )
    if previous_install.get("wrapper_backed_up"):
        restored_wrapper = _restore_path(
            backup_dir / "bin" / "webnovel-codex",
            wrapper_target,
        )
    if previous_install.get("restore_wrapper_backed_up"):
        restored_restore_wrapper = _restore_path(
            backup_dir / "bin" / "webnovel-codex-restore",
            restore_wrapper_target,
        )
    for name, target in shortcut_wrapper_targets.items():
        if (previous_install.get("shortcut_wrappers_backed_up") or {}).get(name):
            restored_shortcut_wrappers[name] = _restore_path(
                backup_dir / "bin" / name,
                target,
            )
        else:
            restored_shortcut_wrappers[name] = False

    _cleanup_state(resolved_codex_home, backup_dir)

    return {
        "codex_home": str(resolved_codex_home),
        "restored_skill": restored_skill,
        "restored_wrapper": restored_wrapper,
        "restored_restore_wrapper": restored_restore_wrapper,
        "restored_shortcut_wrappers": restored_shortcut_wrappers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore Codex support for webnovel-writer")
    parser.add_argument("--codex-home", default=None, help="Codex home directory (default: $CODEX_HOME or ~/.codex)")
    args = parser.parse_args()

    result = restore_codex_support(codex_home=args.codex_home)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
