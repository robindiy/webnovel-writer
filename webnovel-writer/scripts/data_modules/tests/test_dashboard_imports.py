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
