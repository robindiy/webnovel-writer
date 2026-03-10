#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib
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


def test_dashboard_watcher_matches_nested_workflow_artifacts():
    _ensure_repo_root_on_path()
    dashboard_watcher = importlib.import_module("dashboard.watcher")

    assert dashboard_watcher._should_watch_path(Path("write_workflow/ch0012/polish.stdout.log")) is True
    assert dashboard_watcher._should_watch_path(Path("observability/call_trace.jsonl")) is True
    assert dashboard_watcher._should_watch_path(Path("reviews/ch0012/aggregate.json")) is True
    assert dashboard_watcher._should_watch_path(Path("misc/tmp.bin")) is False


def test_dashboard_walk_tree_supports_volume_layout(tmp_path):
    _ensure_repo_root_on_path()
    dashboard_app = importlib.import_module("dashboard.app")

    root = tmp_path
    chapter_path = root / "正文" / "第1卷" / "第001章.md"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text("测试正文", encoding="utf-8")

    tree = dashboard_app._walk_tree(root / "正文", root)

    assert tree == [
        {
            "name": "第1卷",
            "type": "dir",
            "path": "正文/第1卷",
            "children": [
                {
                    "name": "第001章.md",
                    "type": "file",
                    "path": "正文/第1卷/第001章.md",
                    "size": len("测试正文".encode("utf-8")),
                }
            ],
        }
    ]
