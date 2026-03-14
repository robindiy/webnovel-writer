#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib
import json
import sys
from pathlib import Path


def _ensure_repo_root_on_path() -> Path:
    repo_package_root = Path(__file__).resolve().parents[3]
    if str(repo_package_root) not in sys.path:
        sys.path.insert(0, str(repo_package_root))
    return repo_package_root


def test_dashboard_modules_import_cleanly():
    _ensure_repo_root_on_path()
    importlib.invalidate_caches()

    for name in ["dashboard.server", "dashboard.app", "dashboard.watcher"]:
        sys.modules.pop(name, None)
        module = importlib.import_module(name)
        assert module is not None


def test_dashboard_app_discovers_workspace_projects(tmp_path):
    _ensure_repo_root_on_path()
    module = importlib.import_module("dashboard.app")

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    book_a = workspace / "书A"
    (book_a / ".webnovel").mkdir(parents=True)
    (book_a / ".webnovel" / "state.json").write_text(
        json.dumps({"project_info": {"title": "书A"}, "progress": {"current_chapter": 3, "total_words": 1234}}, ensure_ascii=False),
        encoding="utf-8",
    )

    book_b = workspace / "书B"
    (book_b / ".webnovel").mkdir(parents=True)
    (book_b / ".webnovel" / "state.json").write_text(
        json.dumps({"project_info": {"title": "书B"}, "progress": {"current_chapter": 0, "total_words": 0}}, ensure_ascii=False),
        encoding="utf-8",
    )

    module._project_root = book_a
    module._workspace_root = workspace

    projects = module._list_available_projects()
    assert [item["title"] for item in projects] == ["书A", "书B"]
    assert projects[0]["is_current"] is True
    assert module._resolve_requested_project(str(book_b)) == book_b.resolve()
