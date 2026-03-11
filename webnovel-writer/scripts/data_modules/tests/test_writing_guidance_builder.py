#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_module():
    _ensure_scripts_on_path()
    import data_modules.writing_guidance_builder as module

    return module


def test_hook_diversification_requires_diversity_and_balance():
    module = _load_module()
    item = {"id": "hook_diversification"}

    assert module.is_checklist_item_completed(item, {"hook_type_usage": {"a": 8, "b": 2}}) is False
    assert module.is_checklist_item_completed(item, {"hook_type_usage": {"a": 9, "b": 1, "c": 1}}) is False
    assert module.is_checklist_item_completed(item, {"hook_type_usage": {"a": 5, "b": 3, "c": 2}}) is True


def test_coolpoint_combo_requires_diversity_and_balance():
    module = _load_module()
    item = {"id": "coolpoint_combo"}

    assert module.is_checklist_item_completed(item, {"pattern_usage": {"a": 6, "b": 4}}) is False
    assert module.is_checklist_item_completed(item, {"pattern_usage": {"a": 8, "b": 1, "c": 1}}) is False
    assert module.is_checklist_item_completed(item, {"pattern_usage": {"a": 4, "b": 3, "c": 3}}) is True


def test_genre_anchor_consistency_requires_signal():
    module = _load_module()
    item = {"id": "genre_anchor_consistency"}

    assert module.is_checklist_item_completed(item, {}) is False
    assert module.is_checklist_item_completed(item, {"genre_anchor_score": 0.6}) is False
    assert module.is_checklist_item_completed(item, {"genre_anchor_score": 0.8}) is True


def test_methodology_and_fallback_are_not_auto_completed():
    module = _load_module()

    assert module.is_checklist_item_completed({"id": "x", "source": "methodology.next_reason"}, {}) is False
    assert module.is_checklist_item_completed({"id": "x", "source": "fallback"}, {}) is False

