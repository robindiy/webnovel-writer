#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_modules():
    _ensure_scripts_on_path()
    import sync_chapter_data as sync_module
    from data_modules.config import DataModulesConfig
    from data_modules.index_manager import EntityMeta, IndexManager

    return sync_module, DataModulesConfig, IndexManager, EntityMeta


def test_sync_project_backfills_chapter_and_reading_power(tmp_path):
    sync_module, DataModulesConfig, IndexManager, EntityMeta = _load_modules()

    project_root = tmp_path
    (project_root / ".webnovel" / "summaries").mkdir(parents=True, exist_ok=True)
    (project_root / "正文" / "第1卷").mkdir(parents=True, exist_ok=True)

    state = {
        "project_info": {"title": "测试书"},
        "progress": {"current_chapter": 1, "total_words": 0},
        "chapter_meta": {
            "0001": {
                "title": "井边湿痕",
                "hook": "井中异响再次出现",
                "hook_type": "悬念钩",
                "unresolved_question": "井下到底藏着什么",
                "ending_state": "主角确认异响不是幻觉",
                "dominant_strand": "quest",
                "summary": "主角在旧巷废井旁发现新的湿痕与回声。",
            }
        },
    }
    (project_root / ".webnovel" / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (project_root / ".webnovel" / "summaries" / "ch0001.md").write_text(
        "### 第1章摘要\n主角在旧巷废井旁发现新的湿痕与回声。\n",
        encoding="utf-8",
    )
    (project_root / "正文" / "第1卷" / "第001章.md").write_text(
        "第1章 井边湿痕\n\n林小天回到天井巷，看见废井边缘有新的湿痕。\n秦瘸爷低声提醒他今晚别靠太近。\n",
        encoding="utf-8",
    )

    config = DataModulesConfig(project_root=project_root)
    manager = IndexManager(config=config)
    manager.upsert_entity(
        EntityMeta(
            id="lin_xiaotian",
            type="角色",
            canonical_name="林小天",
            tier="核心",
            first_appearance=1,
            last_appearance=1,
            is_protagonist=True,
        ),
        update_metadata=True,
    )
    manager.upsert_entity(
        EntityMeta(
            id="qin_guaye",
            type="角色",
            canonical_name="秦瘸爷",
            tier="重要",
            first_appearance=1,
            last_appearance=1,
        ),
        update_metadata=True,
    )
    manager.upsert_entity(
        EntityMeta(
            id="tianjing_feijing",
            type="地点",
            canonical_name="天井巷废井",
            tier="重要",
            first_appearance=1,
            last_appearance=1,
        ),
        update_metadata=True,
    )
    manager.record_appearance("lin_xiaotian", 1, ["林小天"])
    manager.record_appearance("qin_guaye", 1, ["秦瘸爷"])
    manager.record_appearance("tianjing_feijing", 1, ["废井"])

    payload = sync_module.sync_project(project_root=project_root, chapter=1)

    assert payload["chapters_synced"] == 1
    chapter_row = manager.get_chapter(1)
    assert chapter_row is not None
    assert chapter_row["title"] == "井边湿痕"
    assert chapter_row["location"] == "天井巷废井"
    assert chapter_row["summary"] == "主角在旧巷废井旁发现新的湿痕与回声。"
    assert "林小天" in chapter_row["characters"]
    assert "秦瘸爷" in chapter_row["characters"]

    scenes = manager.get_scenes(1)
    assert len(scenes) == 1
    assert scenes[0]["location"] == "天井巷废井"

    reading_power = manager.get_chapter_reading_power(1)
    assert reading_power is not None
    assert reading_power["hook_type"] == "悬念钩"
    assert reading_power["hook_strength"] == "strong"
    assert "任务推进" in reading_power["coolpoint_patterns"]


def test_sync_project_prefers_latest_review_reader_pull_metrics(tmp_path):
    sync_module, DataModulesConfig, IndexManager, EntityMeta = _load_modules()

    project_root = tmp_path
    (project_root / ".webnovel" / "summaries").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "reviews" / "ch0001").mkdir(parents=True, exist_ok=True)
    (project_root / "正文" / "第1卷").mkdir(parents=True, exist_ok=True)

    state = {
        "project_info": {"title": "测试书"},
        "progress": {"current_chapter": 1, "total_words": 0},
        "chapter_meta": {
            "0001": {
                "title": "旧版本标题",
                "hook_type": "承诺钩",
                "hook_strength": "weak",
                "ending_state": "旧 ending",
                "summary": "旧摘要",
            }
        },
    }
    (project_root / ".webnovel" / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (project_root / "正文" / "第1卷" / "第001章.md").write_text(
        "第1章 新标题\n\n林小天在巷口做出新的选择，章末留下更强的悬念。\n",
        encoding="utf-8",
    )
    (project_root / ".webnovel" / "reviews" / "ch0001" / "aggregate.json").write_text(
        json.dumps(
            {
                "chapter": 1,
                "pass": True,
                "checkers": {
                    "reader-pull-checker": {
                        "metrics": {
                            "hook_type": "危机钩",
                            "hook_strength": "strong",
                            "micropayoffs": ["身份兑现", "危机升级"],
                            "is_transition": False,
                            "debt_balance": 1.5,
                        }
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    config = DataModulesConfig(project_root=project_root)
    manager = IndexManager(config=config)
    manager.upsert_entity(
        EntityMeta(
            id="lin_xiaotian",
            type="角色",
            canonical_name="林小天",
            tier="核心",
            first_appearance=1,
            last_appearance=1,
            is_protagonist=True,
        ),
        update_metadata=True,
    )
    manager.record_appearance("lin_xiaotian", 1, ["林小天"])

    sync_module.sync_project(project_root=project_root, chapter=1)

    reading_power = manager.get_chapter_reading_power(1)
    assert reading_power is not None
    assert reading_power["hook_type"] == "危机钩"
    assert reading_power["hook_strength"] == "strong"
    assert "身份兑现" in reading_power["micropayoffs"]
    assert reading_power["is_transition"] == 0
    assert reading_power["debt_balance"] == 1.5
