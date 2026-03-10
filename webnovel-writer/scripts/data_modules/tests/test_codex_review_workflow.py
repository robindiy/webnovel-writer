#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_module():
    _ensure_scripts_on_path()
    import codex_review_workflow as module

    return module


def test_parse_range_supports_single_and_span():
    module = _load_module()

    assert module._parse_range("7") == (7, 7)
    assert module._parse_range("1-5") == (1, 5)


def test_run_review_workflow_happy_path(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()
    report_path = project_root / "审查报告" / "第1-5章审查报告.md"
    aggregate_path = project_root / ".webnovel" / "reviews" / "range-0001-0005" / "aggregate.json"
    state_path = project_root / ".webnovel" / "state.json"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report", encoding="utf-8")
    aggregate_path.write_text("{}", encoding="utf-8")
    state_path.write_text("{}", encoding="utf-8")

    calls = {"start_steps": [], "complete_steps": [], "completed_task": 0, "update_state": None}

    monkeypatch.setattr(module, "resolve_project_root", lambda raw: Path(raw))
    monkeypatch.setattr(module, "_start_task", lambda project_root, end_chapter: calls.setdefault("task", end_chapter))
    monkeypatch.setattr(module, "_start_step", lambda project_root, step_id, step_name: calls["start_steps"].append((step_id, step_name)))
    monkeypatch.setattr(module, "_complete_step", lambda project_root, step_id, artifacts=None: calls["complete_steps"].append((step_id, artifacts)))
    monkeypatch.setattr(module, "_complete_task", lambda project_root, artifacts=None: calls.__setitem__("completed_task", calls["completed_task"] + 1))
    monkeypatch.setattr(module, "_verify_state_exists", lambda project_root: state_path)
    monkeypatch.setattr(
        module,
        "_run_review_step",
        lambda **kwargs: {
            "overall_score": 81.6,
            "severity_counts": {"critical": 0, "high": 0, "medium": 1, "low": 2},
            "critical_issues": [],
            "report_file": str(report_path),
            "aggregate_file": str(aggregate_path),
        },
    )
    monkeypatch.setattr(module, "_latest_review_metric", lambda project_root: {"overall_score": 81.6})
    monkeypatch.setattr(
        module,
        "_update_state_review",
        lambda project_root, start_chapter, end_chapter, report_path: calls.__setitem__(
            "update_state", (start_chapter, end_chapter, str(report_path))
        ),
    )

    result = module.run_review_workflow(project_root=project_root, start_chapter=1, end_chapter=5)

    assert result["status"] == "ok"
    assert result["workflow_completed"] is True
    assert result["overall_score"] == 81.6
    assert calls["task"] == 5
    assert calls["update_state"] == (1, 5, str(report_path))
    assert calls["completed_task"] == 1
    assert ("Step 8", "收尾") in calls["start_steps"]


def test_run_review_workflow_returns_needs_input_for_critical(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()
    report_path = project_root / "审查报告" / "第7-7章审查报告.md"
    aggregate_path = project_root / ".webnovel" / "reviews" / "ch0007" / "aggregate.json"
    state_path = project_root / ".webnovel" / "state.json"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("# report", encoding="utf-8")
    aggregate_path.write_text("{}", encoding="utf-8")
    state_path.write_text("{}", encoding="utf-8")

    calls = {"completed_task": 0}

    monkeypatch.setattr(module, "resolve_project_root", lambda raw: Path(raw))
    monkeypatch.setattr(module, "_start_task", lambda project_root, end_chapter: None)
    monkeypatch.setattr(module, "_start_step", lambda project_root, step_id, step_name: None)
    monkeypatch.setattr(module, "_complete_step", lambda project_root, step_id, artifacts=None: None)
    monkeypatch.setattr(module, "_complete_task", lambda project_root, artifacts=None: calls.__setitem__("completed_task", calls["completed_task"] + 1))
    monkeypatch.setattr(module, "_verify_state_exists", lambda project_root: state_path)
    monkeypatch.setattr(
        module,
        "_run_review_step",
        lambda **kwargs: {
            "overall_score": 65.0,
            "severity_counts": {"critical": 1, "high": 0, "medium": 0, "low": 0},
            "critical_issues": ["设定自相矛盾"],
            "report_file": str(report_path),
            "aggregate_file": str(aggregate_path),
        },
    )
    monkeypatch.setattr(module, "_latest_review_metric", lambda project_root: {"overall_score": 65.0})
    monkeypatch.setattr(module, "_update_state_review", lambda project_root, start_chapter, end_chapter, report_path: None)

    result = module.run_review_workflow(project_root=project_root, start_chapter=7, end_chapter=7)

    assert result["status"] == "needs_input"
    assert result["workflow_completed"] is False
    assert result["critical_issues"] == ["设定自相矛盾"]
    assert calls["completed_task"] == 0
