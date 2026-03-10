#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_prepare_module():
    _ensure_scripts_on_path()
    import write_prepare as module

    return module


def _load_finalize_module():
    _ensure_scripts_on_path()
    import write_finalize as module

    return module


def _make_book_project(tmp_path: Path) -> Path:
    project_root = (tmp_path / "book").resolve()
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text(
        json.dumps({"progress": {"current_chapter": 0}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (project_root / "大纲").mkdir(parents=True, exist_ok=True)
    (project_root / "大纲" / "总纲.md").write_text("# 总纲", encoding="utf-8")
    chapter_dir = project_root / "正文" / "第1卷"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    return project_root


def test_write_prepare_creates_context_prompt(monkeypatch, tmp_path):
    module = _load_prepare_module()
    project_root = _make_book_project(tmp_path)

    monkeypatch.setattr(module, "start_task", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "start_step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "_load_context_materials",
        lambda *_args, **_kwargs: {
            "state": {"progress": {"current_chapter": 8}},
            "context_manager": {"writing_guidance": {"guidance_items": ["保持钩子"]}},
            "extract_context": {"outline": "推进主线", "previous_summaries": [], "state_summary": "摘要"},
            "recent_reading_power": [],
            "pattern_usage_stats": {},
            "hook_type_stats": {},
            "debt_summary": {},
            "core_entities": [],
            "recent_appearances": [],
            "timeline_text": "",
        },
    )

    payload = module.prepare_write(project_root=project_root, chapter=9, mode="standard")

    assert payload["status"] == "ok"
    assert payload["stage"] == "context"
    assert Path(payload["prompt_file"]).is_file()
    assert Path(payload["schema_file"]).is_file()
    assert Path(payload["materials_file"]).is_file()


def test_write_finalize_context_to_draft(monkeypatch, tmp_path):
    module = _load_finalize_module()
    project_root = _make_book_project(tmp_path)
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "context_agent.result.json").write_text(
        json.dumps(
            {
                "chapter": 9,
                "task_brief": {
                    "core_task": "推进",
                    "conflict": "冲突",
                    "carry_from_previous": "承接",
                    "characters": [],
                    "scene_constraints": [],
                    "foreshadowing": [],
                    "reading_power": [],
                },
                "contract_v2": {"goal": "目标"},
                "draft_package": {"title_suggestion": "测试标题", "target_words": 2400},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "complete_step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "start_step", lambda *_args, **_kwargs: None)

    payload = module.finalize_stage(project_root=project_root, chapter=9, stage="context", mode="standard", enable_debt_interest=False)

    assert payload["status"] == "ok"
    assert payload["stage"] == "draft"
    assert Path(payload["prompt_file"]).is_file()
    assert Path(payload["schema_file"]).is_file()


def test_write_finalize_draft_to_style(monkeypatch, tmp_path):
    module = _load_finalize_module()
    project_root = _make_book_project(tmp_path)
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "context_package.json").write_text(
        json.dumps({"draft_package": {"title_suggestion": "测试标题"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (artifact_dir / "draft.result.json").write_text(
        json.dumps({"title": "测试标题", "content": "第一段。\n\n第二段。"}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "complete_step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "start_step", lambda *_args, **_kwargs: None)

    payload = module.finalize_stage(project_root=project_root, chapter=9, stage="draft", mode="standard", enable_debt_interest=False)

    assert payload["status"] == "ok"
    assert payload["stage"] == "style"
    chapter_file = project_root / "正文" / "第1卷" / "第009章.md"
    assert chapter_file.is_file()
    assert "测试标题" in chapter_file.read_text(encoding="utf-8")


def test_write_finalize_style_requires_reread_evidence(monkeypatch, tmp_path):
    module = _load_finalize_module()
    project_root = _make_book_project(tmp_path)
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    chapter_file = project_root / "正文" / "第1卷" / "第009章.md"
    chapter_file.write_text("第9章 测试标题\n\n第一段。\n\n第二段。", encoding="utf-8")
    (artifact_dir / "style_adapter.result.json").write_text(
        json.dumps(
            {
                "content": "第一段。\n\n第二段。",
                "change_summary": ["压缩一句说明腔"],
                "pass_reports": [
                    {
                        "pass_id": "style-pass-a",
                        "focus": "局部风格转译",
                        "full_reread": False,
                        "applied_changes": ["压缩说明句"],
                    },
                    {
                        "pass_id": "style-pass-b",
                        "focus": "全章回读与节奏校正",
                        "full_reread": True,
                        "applied_changes": ["确认章末钩子保留"],
                        "checks": ["hook", "typesetting"],
                    },
                ],
                "full_reread_count": 1,
                "retained": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    called = {"prepare_review": 0}

    def fake_prepare_review(*_args, **_kwargs):
        called["prepare_review"] += 1
        assert _kwargs["mode"] == "full"
        return {"status": "ok", "chapters": [{"selected_checkers": ["consistency-checker", "continuity-checker", "ooc-checker", "reader-pull-checker", "high-point-checker", "pacing-checker"]}]}

    monkeypatch.setattr(module, "prepare_review", fake_prepare_review)
    monkeypatch.setattr(module, "complete_step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "start_step", lambda *_args, **_kwargs: None)

    payload = module.finalize_stage(project_root=project_root, chapter=9, stage="style", mode="standard", enable_debt_interest=False)

    assert payload["status"] == "ok"
    assert payload["stage"] == "review_initial"
    assert called["prepare_review"] == 1


def test_write_finalize_polish_always_prepares_second_review(monkeypatch, tmp_path):
    module = _load_finalize_module()
    project_root = _make_book_project(tmp_path)
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    chapter_file = project_root / "正文" / "第1卷" / "第009章.md"
    chapter_file.write_text("第9章 测试标题\n\n第一段。\n\n第二段。", encoding="utf-8")
    (artifact_dir / "polish.result.json").write_text(
        json.dumps(
            {
                "content": "第一段。\n\n第二段。",
                "change_summary": [],
                "anti_ai_force_check": "pass",
                "deviation": ["无实质修改"],
                "pass_reports": [
                    {
                        "pass_id": "polish-pass-a",
                        "focus": "review issues 修复",
                        "full_reread": False,
                        "applied_changes": ["无"],
                    },
                    {
                        "pass_id": "polish-pass-b",
                        "focus": "全章重读 + Anti-AI",
                        "full_reread": True,
                        "applied_changes": ["无"],
                        "checks": ["anti_ai"],
                    },
                    {
                        "pass_id": "polish-pass-c",
                        "focus": "全章重读 + No-Poison + 排版",
                        "full_reread": True,
                        "applied_changes": ["无"],
                        "checks": ["no_poison", "typesetting"],
                    },
                ],
                "full_reread_count": 2,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    called = {"prepare_review": 0}

    def fake_prepare_review(*_args, **_kwargs):
        called["prepare_review"] += 1
        assert _kwargs["mode"] == "full"
        return {"status": "ok", "chapters": [{"selected_checkers": ["consistency-checker", "continuity-checker", "ooc-checker", "reader-pull-checker", "high-point-checker", "pacing-checker"]}]}

    monkeypatch.setattr(module, "prepare_review", fake_prepare_review)

    payload = module.finalize_stage(project_root=project_root, chapter=9, stage="polish", mode="standard", enable_debt_interest=False)

    assert payload["status"] == "ok"
    assert payload["stage"] == "review_final"
    assert called["prepare_review"] == 1
    assert payload["review_manifest"]["chapters"][0]["selected_checkers"] == [
        "consistency-checker",
        "continuity-checker",
        "ooc-checker",
        "reader-pull-checker",
        "high-point-checker",
        "pacing-checker",
    ]
    applied = json.loads((artifact_dir / "polish.applied.json").read_text(encoding="utf-8"))
    assert "reuse_previous_review" not in applied


def test_write_finalize_review_initial_persists_snapshot(monkeypatch, tmp_path):
    module = _load_finalize_module()
    project_root = _make_book_project(tmp_path)
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    review_dir = project_root / ".webnovel" / "reviews" / "ch0009"
    checker_dir = review_dir / "checkers"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    checker_dir.mkdir(parents=True, exist_ok=True)
    chapter_file = project_root / "正文" / "第1卷" / "第009章.md"
    chapter_file.write_text("第9章 测试标题\n\n第一段。", encoding="utf-8")
    (artifact_dir / "context.materials.json").write_text(json.dumps({"state": {"progress": {"current_chapter": 8}}}, ensure_ascii=False), encoding="utf-8")
    (review_dir / "prepare_manifest.json").write_text(
        json.dumps(
            {
                "chapter": 9,
                "chapter_file": str(chapter_file),
                "selected_checkers": ["consistency-checker"],
                "checkers": [
                    {
                        "agent": "consistency-checker",
                        "prompt_file": str(checker_dir / "consistency-checker.prompt.txt"),
                        "output_file": str(checker_dir / "consistency-checker.json"),
                        "stdout_log_file": str(checker_dir / "consistency-checker.stdout.log"),
                        "stderr_log_file": str(checker_dir / "consistency-checker.stderr.log"),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for suffix, content in {
        "prompt.txt": "prompt",
        "json": json.dumps({"agent": "consistency-checker"}, ensure_ascii=False),
        "stdout.log": "stdout",
        "stderr.log": "stderr",
    }.items():
        (checker_dir / f"consistency-checker.{suffix}").write_text(content, encoding="utf-8")
    (review_dir / "aggregate.json").write_text(json.dumps({"selected_checkers": ["consistency-checker"]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(
        module,
        "finalize_review",
        lambda *_args, **_kwargs: {
            "overall_score": 86.0,
            "execution_mode": "desktop_strict",
            "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "report_file": str(project_root / "审查报告" / "第9-9章审查报告.md"),
            "aggregate_file": str(review_dir / "aggregate.json"),
        },
    )
    monkeypatch.setattr(module, "complete_step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "start_step", lambda *_args, **_kwargs: None)

    payload = module.finalize_stage(project_root=project_root, chapter=9, stage="review-initial", mode="standard", enable_debt_interest=False)

    assert payload["status"] == "ok"
    assert Path(artifact_dir / "review_initial.json").is_file()
    assert Path(artifact_dir / "review_initial_checkers" / "consistency-checker.stdout.log").is_file()


def test_write_finalize_review_final_requires_second_review_outputs(monkeypatch, tmp_path):
    module = _load_finalize_module()
    project_root = _make_book_project(tmp_path)
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    chapter_file = project_root / "正文" / "第1卷" / "第009章.md"
    chapter_file.write_text("第9章 测试标题\n\n第一段。", encoding="utf-8")
    (artifact_dir / "context.materials.json").write_text(json.dumps({"state": {"progress": {"current_chapter": 8}}}, ensure_ascii=False), encoding="utf-8")
    (artifact_dir / "context_package.json").write_text(json.dumps({"task_brief": {"core_task": "推进"}}, ensure_ascii=False), encoding="utf-8")
    (artifact_dir / "polish.applied.json").write_text(
        json.dumps(
            {
                "content": "第一段。",
                "change_summary": [],
                "anti_ai_force_check": "pass",
                "deviation": ["无实质修改"],
                "pass_reports": [
                    {
                        "pass_id": "polish-pass-a",
                        "focus": "review issues 修复",
                        "full_reread": False,
                        "applied_changes": ["无"],
                    },
                    {
                        "pass_id": "polish-pass-b",
                        "focus": "全章重读 + Anti-AI",
                        "full_reread": True,
                        "applied_changes": ["无"],
                        "checks": ["anti_ai"],
                    },
                    {
                        "pass_id": "polish-pass-c",
                        "focus": "全章重读 + No-Poison + 排版",
                        "full_reread": True,
                        "applied_changes": ["无"],
                        "checks": ["no_poison", "typesetting"],
                    },
                ],
                "full_reread_count": 2,
                "reuse_previous_review": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    calls = {"finalize_review": 0}

    def fake_finalize_review(*_args, **_kwargs):
        calls["finalize_review"] += 1
        return {
            "overall_score": 86.0,
            "execution_mode": "desktop_strict",
            "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "report_file": str(project_root / "审查报告" / "第9-9章审查报告.md"),
            "aggregate_file": str(project_root / ".webnovel" / "reviews" / "ch0009" / "aggregate.json"),
        }

    monkeypatch.setattr(module, "finalize_review", fake_finalize_review)
    monkeypatch.setattr(
        module,
        "_load_review_payload",
        lambda *_args, **_kwargs: {
            "overall_score": 86.0,
            "execution_mode": "desktop_strict",
            "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "report_file": str(project_root / "审查报告" / "第9-9章审查报告.md"),
            "aggregate_file": str(project_root / ".webnovel" / "reviews" / "ch0009" / "aggregate.json"),
        },
    )
    monkeypatch.setattr(module, "_load_context_materials", lambda *_args, **_kwargs: {"state": {"progress": {"current_chapter": 8}}})

    payload = module.finalize_stage(project_root=project_root, chapter=9, stage="review-final", mode="standard", enable_debt_interest=False)

    assert payload["status"] == "ok"
    assert payload["stage"] == "data"
    assert calls["finalize_review"] == 1
    assert Path(payload["prompt_file"]).is_file()
    assert Path(artifact_dir / "review_final.json").is_file()


def test_build_stage_schema_data_matches_state_contract():
    _ensure_scripts_on_path()
    from codex_write_workflow import _build_stage_schema_data

    schema = _build_stage_schema_data()

    appeared = schema["properties"]["entities_appeared"]["items"]
    assert set(("id", "type", "mentions", "confidence")).issubset(set(appeared["required"]))

    state_change = schema["properties"]["state_changes"]["items"]
    assert set(("entity_id", "field", "new")).issubset(set(state_change["required"]))

    uncertain = schema["properties"]["uncertain"]["items"]
    assert set(("mention", "candidates", "confidence")).issubset(set(uncertain["required"]))


def test_write_finalize_data_rejects_payload_that_process_chapter_cannot_accept(monkeypatch, tmp_path):
    module = _load_finalize_module()
    project_root = _make_book_project(tmp_path)
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "data_agent.result.json").write_text(
        json.dumps(
            {
                "entities_appeared": [{"id": "lin_xiaotian", "type": "角色"}],
                "entities_new": [],
                "state_changes": [{"entity": "lin_xiaotian", "field": "status", "new": "ok"}],
                "relationships_new": [],
                "scenes_chunked": 0,
                "uncertain": [],
                "warnings": [],
                "chapter_meta": {"title": "测试"},
                "summary_text": "摘要",
                "foreshadowing_notes": [],
                "foreshadowing_planted": [],
                "foreshadowing_continued": [],
                "foreshadowing_resolved": [],
                "bridge_line": "承接",
                "scenes": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "_load_review_payload", lambda *_args, **_kwargs: {"overall_score": 85})
    monkeypatch.setattr(module, "_apply_data_payload", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not reach apply")))

    try:
        module.finalize_stage(project_root=project_root, chapter=9, stage="data", mode="standard", enable_debt_interest=False)
    except RuntimeError as exc:
        message = str(exc)
        assert "SCHEMA_VALIDATION_FAILED" in message
        assert "mentions" in message or "entity_id" in message
    else:  # pragma: no cover - defensive
        raise AssertionError("expected RuntimeError")
