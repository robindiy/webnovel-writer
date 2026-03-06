#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib
import sys
from pathlib import Path


def _ensure_runtime_paths() -> None:
    repo_package_root = Path(__file__).resolve().parents[3]
    scripts_dir = Path(__file__).resolve().parents[2]

    if str(repo_package_root) not in sys.path:
        sys.path.insert(0, str(repo_package_root))
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def test_core_modules_import_cleanly_under_python39():
    _ensure_runtime_paths()
    importlib.invalidate_caches()

    core_modules = [
        "data_modules.config",
        "data_modules.context_manager",
        "data_modules.state_manager",
        "data_modules.index_manager",
        "data_modules.rag_adapter",
        "data_modules.style_sampler",
    ]

    for name in core_modules:
        sys.modules.pop(name, None)
        module = importlib.import_module(name)
        assert module is not None
