#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Persistence helpers for lightweight Codex controller sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional, Union


def _project_root_path(project_root: Union[str, Path]) -> Path:
    return Path(project_root).expanduser().resolve()


def controller_sessions_dir(project_root: Union[str, Path]) -> Path:
    return _project_root_path(project_root) / ".webnovel" / "controller_sessions"


def session_path(project_root: Union[str, Path], controller: str) -> Path:
    return controller_sessions_dir(project_root) / f"{str(controller).strip()}.json"


def load_session(project_root: Union[str, Path], controller: str) -> Optional[dict[str, Any]]:
    path = session_path(project_root, controller)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_session(project_root: Union[str, Path], controller: str, session: Mapping[str, Any]) -> Path:
    path = session_path(project_root, controller)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(dict(session), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)
    return path
