#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib
import json
import sys
from pathlib import Path



CHECKERS = [
    "consistency-checker",
    "continuity-checker",
    "ooc-checker",
    "reader-pull-checker",
    "high-point-checker",
    "pacing-checker",
]


def _ensure_repo_root_on_path() -> Path:
    repo_package_root = Path(__file__).resolve().parents[3]
    if str(repo_package_root) not in sys.path:
        sys.path.insert(0, str(repo_package_root))
    return repo_package_root


def test_dashboard_workflow_live_and_stage_log_endpoints(tmp_path):
    _ensure_repo_root_on_path()
    dashboard_app = importlib.import_module("dashboard.app")

    webnovel = tmp_path / ".webnovel"
    artifact_dir = webnovel / "write_workflow" / "ch0005"
    observability = webnovel / "observability"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    observability.mkdir(parents=True, exist_ok=True)

    (webnovel / "state.json").write_text(json.dumps({"project_info": {"title": "测试书"}}, ensure_ascii=False), encoding="utf-8")
    (webnovel / "workflow_state.json").write_text(
        json.dumps(
            {
                "current_task": {
                    "command": "webnovel-write",
                    "args": {"chapter_num": 5},
                    "status": "running",
                    "retry_count": 1,
                    "current_step": {
                        "id": "Step 4",
                        "name": "润色",
                        "progress_note": "Pass B 全文重读",
                    },
                },
                "last_stable_state": {"chapter": 5},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (observability / "call_trace.jsonl").write_text(
        json.dumps({"timestamp": "2026-03-09T21:00:00+08:00", "event": "step_progress", "payload": {"step_id": "Step 4", "chapter": 5, "progress_note": "Pass B 全文重读"}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (observability / "codex_write_workflow.jsonl").write_text(
        json.dumps({"timestamp": "2026-03-09T21:00:01+08:00", "kind": "event", "stage": "polish", "event": "turn.started", "message": "润色 · turn.started"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (observability / "review_agent_timing.jsonl").write_text(
        json.dumps({"timestamp": "2026-03-09T21:00:02+08:00", "tool_name": "review_agents_runner:checker", "chapter": 5, "checker": "reader-pull-checker", "elapsed_ms": 321, "success": True}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (artifact_dir / "polish.stdout.log").write_text("Pass A\nPass B 全文重读\n", encoding="utf-8")
    (artifact_dir / "polish.stderr.log").write_text("", encoding="utf-8")
    (artifact_dir / "style_adapter.stdout.log").write_text("Pass A 局部转译\n", encoding="utf-8")
    (artifact_dir / "style_adapter.stderr.log").write_text("", encoding="utf-8")
    (artifact_dir / "polish.result.json").write_text(
        json.dumps(
            {
                "content": "正文",
                "change_summary": ["收紧说明句"],
                "pass_reports": [
                    {"pass_id": "Pass A", "focus": "修问题", "full_reread": False, "applied_changes": ["修任务面板"]},
                    {"pass_id": "Pass B", "focus": "全文重读", "full_reread": True, "applied_changes": ["复扫 Anti-AI"]},
                    {"pass_id": "Pass C", "focus": "终检", "full_reread": True, "applied_changes": ["No-Poison 通过"]},
                ],
                "full_reread_count": 2,
                "anti_ai_force_check": "pass",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (artifact_dir / "polish.trace.json").write_text(
        json.dumps(
            {
                "stage": "polish",
                "summary": {
                    "workspace_reads": 2,
                    "workspace_writes": 1,
                    "events_captured": 4,
                    "tools_seen": ["read_file", "update_file"],
                },
                "entries": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (artifact_dir / "polish.execution.json").write_text(
        json.dumps(
            {
                "stage": "polish",
                "success": True,
                "file_changed": True,
                "content_matches_file": True,
                "trace_summary": {
                    "workspace_reads": 2,
                    "workspace_writes": 1,
                    "events_captured": 4,
                    "tools_seen": ["read_file", "update_file"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (artifact_dir / "review_initial.json").write_text(
        json.dumps(
            {
                "selected_checkers": CHECKERS,
                "overall_score": 86.5,
                "checkers": {checker: {"score": 86.0, "pass": True, "summary": f"{checker} 初审摘要"} for checker in CHECKERS},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (artifact_dir / "review_final.json").write_text(
        json.dumps(
            {
                "selected_checkers": CHECKERS,
                "overall_score": 88.0,
                "checkers": {checker: {"score": 88.0, "pass": True, "summary": f"{checker} 复审摘要"} for checker in CHECKERS},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    app = dashboard_app.create_app(project_root=tmp_path)
    route_paths = {route.path for route in app.routes}
    assert "/api/workflow/live" in route_paths
    assert "/api/workflow/stage-log" in route_paths

    payload = dashboard_app._build_workflow_live_payload(event_limit=10, log_lines=5)
    assert payload["chapter"] == 5
    assert payload["active_stage"] == "polish"
    assert "polish" in payload["stage_logs"]
    assert payload["review"]["initial"]["selected_checkers"] == CHECKERS
    assert any(item["source"] == "write_observability" for item in payload["recent_events"])

    stage_payload = dashboard_app._stage_log_info(artifact_dir, "polish", log_lines=5)
    assert stage_payload is not None
    assert "Pass B 全文重读" in stage_payload["stdout_excerpt"]
    assert stage_payload["execution_path"] is not None
    assert stage_payload["trace_path"] is not None
    assert stage_payload["result_summary"]["file_changed"] is True
    assert stage_payload["result_summary"]["workspace_writes"] == 1
    assert stage_payload["result_summary"]["tools_seen"] == ["read_file", "update_file"]
