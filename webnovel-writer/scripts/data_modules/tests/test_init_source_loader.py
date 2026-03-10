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
    import init_source_loader as module

    return module


def test_load_init_workflow_extracts_step_order():
    module = _load_module()

    spec = module.load_init_workflow_spec()

    assert [step.id for step in spec.steps] == [
        "Step 1",
        "Step 2",
        "Step 3",
        "Step 4",
        "Step 5",
        "Step 6",
    ]


def test_load_init_workflow_extracts_genre_categories():
    module = _load_module()

    spec = module.load_init_workflow_spec()

    assert "玄幻修仙类" in spec.genre_categories
    assert "修仙" in spec.genre_categories["玄幻修仙类"]
    assert "规则怪谈" in spec.genre_categories["特殊题材"]
    assert "狗血言情" in spec.genre_categories["言情类"]


def test_load_init_workflow_extracts_inline_enum_options():
    module = _load_module()

    spec = module.load_init_workflow_spec()

    fields = {field.key: field for step in spec.steps for field in step.fields}

    assert fields["protagonist_structure"].options == ["单主角", "多主角"]
    assert fields["heroine_config"].options == ["无", "单女主", "多女主"]
    assert fields["growth_pacing"].options == ["慢热", "中速", "快节奏"]
    assert fields["world_scale"].options == ["单城", "多域", "大陆", "多界"]


def test_load_init_workflow_extracts_source_backed_guidance():
    module = _load_module()

    spec = module.load_init_workflow_spec()

    assert "起点" in spec.platform_options
    assert "番茄" in spec.platform_options
    assert "基础特征四维度" not in spec.platform_options
    assert "男频" in spec.target_reader_options
    assert "女频" in spec.target_reader_options
    assert "长生" in spec.protagonist_desire_options
    assert "傲慢" in spec.protagonist_flaw_options
    assert "苟道流" in spec.protagonist_archetype_options
    assert "传统修仙" in spec.power_system_options
    assert "宗门/学院" in spec.faction_options
    assert "反噬/失控" in spec.golden_finger_cost_options
    assert spec.genre_guidance["修仙"].premise_candidates
    assert spec.genre_guidance["修仙"].conflict_candidates
