#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def test_default_chapter_draft_path_prefers_volume_layout_when_project_has_volumes(tmp_path):
    _ensure_scripts_on_path()

    from chapter_paths import default_chapter_draft_path

    (tmp_path / ".webnovel").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "progress": {
                    "volumes_planned": [
                        {"volume": 1, "chapters_range": "1-50"},
                        {"volume": 2, "chapters_range": "51-100"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "正文" / "第1卷").mkdir(parents=True, exist_ok=True)

    assert default_chapter_draft_path(tmp_path, 7) == tmp_path / "正文" / "第1卷" / "第007章.md"
    assert default_chapter_draft_path(tmp_path, 51) == tmp_path / "正文" / "第2卷" / "第051章.md"


def test_find_chapter_file_prefers_volume_file_over_legacy_flat(tmp_path):
    _ensure_scripts_on_path()

    from chapter_paths import find_chapter_file

    (tmp_path / ".webnovel").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".webnovel" / "state.json").write_text(
        json.dumps({"progress": {"volumes_planned": [{"volume": 1, "chapters_range": "1-50"}]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    chapters_dir = tmp_path / "正文"
    vol_dir = chapters_dir / "第1卷"
    vol_dir.mkdir(parents=True, exist_ok=True)

    legacy = chapters_dir / "第0007章.md"
    legacy.write_text("legacy", encoding="utf-8")
    volume_file = vol_dir / "第007章.md"
    volume_file.write_text("volume", encoding="utf-8")

    assert find_chapter_file(tmp_path, 7) == volume_file
