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
    import review_prepare as module

    return module


def _load_finalize_module():
    _ensure_scripts_on_path()
    import review_finalize as module

    return module


def _make_book_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = (tmp_path / "book").resolve()
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")
    chapter_dir = project_root / "正文" / "第1卷"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    chapter_file = chapter_dir / "第001章.md"
    chapter_file.write_text("第1章 测试\n\n主角看见巷口有异样。", encoding="utf-8")
    return project_root, chapter_file


def test_review_prepare_materializes_checker_prompts(monkeypatch, tmp_path):
    module = _load_prepare_module()
    project_root, chapter_file = _make_book_project(tmp_path)

    monkeypatch.setattr(module, "build_chapter_context_payload", lambda *_args, **_kwargs: {"outline": "主线推进", "previous_summaries": [], "state_summary": ""})

    payload = module.prepare_review(
        project_root=project_root,
        chapter=1,
        start_chapter=None,
        end_chapter=None,
        mode="minimal",
        chapter_file=chapter_file,
    )

    assert payload["status"] == "ok"
    assert payload["chapter"] == 1
    manifest = payload["chapters"][0]
    checker_names = manifest["selected_checkers"]
    assert checker_names == ["consistency-checker", "continuity-checker", "ooc-checker"]
    checker_entries = {item["agent"]: item for item in manifest["checkers"]}
    for checker in checker_names:
        prompt_file = project_root / ".webnovel" / "reviews" / "ch0001" / "checkers" / f"{checker}.prompt.txt"
        assert prompt_file.is_file()
        assert "你是 webnovel-writer 的" in prompt_file.read_text(encoding="utf-8")
        assert checker_entries[checker]["stdout_log_file"].endswith(f"{checker}.stdout.log")
        assert checker_entries[checker]["stderr_log_file"].endswith(f"{checker}.stderr.log")


def test_review_finalize_aggregates_checker_outputs(monkeypatch, tmp_path):
    module = _load_finalize_module()
    project_root, chapter_file = _make_book_project(tmp_path)

    artifact_dir = project_root / ".webnovel" / "reviews" / "ch0001"
    checker_dir = artifact_dir / "checkers"
    checker_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "prepare_manifest.json").write_text(
        json.dumps(
            {
                "chapter": 1,
                "chapter_file": str(chapter_file),
                "selected_checkers": ["consistency-checker", "continuity-checker"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    for agent in ("consistency-checker", "continuity-checker"):
        (checker_dir / f"{agent}.json").write_text(
            json.dumps(
                {
                    "agent": agent,
                    "chapter": 1,
                    "overall_score": 84.0,
                    "pass": True,
                    "issues": [],
                    "metrics": {},
                    "summary": f"{agent} ok",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(module, "save_review_metrics", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "sync_chapter_data_after_review", lambda *_args, **_kwargs: {"chapters_synced": 1, "elapsed_ms": 3})

    payload = module.finalize_review(
        project_root=project_root,
        chapter=1,
        start_chapter=None,
        end_chapter=None,
        sync_on_pass=True,
    )

    assert payload["status"] == "ok"
    assert payload["chapter"] == 1
    assert payload["execution_mode"] == "desktop_strict"
    assert Path(payload["aggregate_file"]).is_file()
    assert Path(payload["report_file"]).is_file()
    aggregate = json.loads(Path(payload["aggregate_file"]).read_text(encoding="utf-8"))
    assert aggregate["selected_checkers"] == ["consistency-checker", "continuity-checker"]
    assert aggregate["post_review_sync"]["success"] is True
    assert aggregate["report_file"] == payload["report_file"]
    assert aggregate["aggregate_file"] == payload["aggregate_file"]
    for agent in ("consistency-checker", "continuity-checker"):
        stdout_log = checker_dir / f"{agent}.stdout.log"
        stderr_log = checker_dir / f"{agent}.stderr.log"
        assert stdout_log.is_file()
        assert stderr_log.is_file()
        assert "desktop_strict" in stdout_log.read_text(encoding="utf-8")
        assert "no subprocess stderr captured" in stderr_log.read_text(encoding="utf-8")
