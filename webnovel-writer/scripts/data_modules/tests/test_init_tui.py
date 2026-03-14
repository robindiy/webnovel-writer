#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_init_tui_module():
    _ensure_scripts_on_path()
    import init_tui as init_tui_module

    return init_tui_module


def test_suggest_project_dir_slugifies_title(tmp_path):
    module = _load_init_tui_module()

    project_dir = module.suggest_project_dir(str(tmp_path), "  我的 新书: 第一卷  ")

    assert project_dir == str(tmp_path.resolve() / "我的-新书-第一卷")


def test_resolve_genre_value_keeps_known_and_custom_genres():
    module = _load_init_tui_module()

    form = module.InitForm(
        workspace_root="/tmp/books",
        genres=["修仙", module.CUSTOM_VALUE],
        custom_genre="规则怪谈+自定义题材",
    )

    assert module.resolve_genre_value(form) == "修仙+规则怪谈+自定义题材"


def test_missing_required_fields_tracks_dependent_fields():
    module = _load_init_tui_module()

    form = module.InitForm(
        workspace_root="/tmp/books",
        title="测试书",
        project_dir="/tmp/books/测试书",
        genres=["修仙"],
        protagonist_name="林澈",
        protagonist_desire="活下来",
        protagonist_flaw="过度多疑",
        target_words=100000,
        target_chapters=120,
        golden_finger_type="系统流",
        world_scale="大陆",
        power_system_type="修仙境界制",
        protagonist_structure="多主角",
        heroine_config="单女主",
    )

    missing = module.missing_required_fields(form)

    assert "多主角名单" in missing
    assert "女主姓名" in missing


def test_missing_required_fields_skip_system_assisted_sections():
    module = _load_init_tui_module()

    form = module.InitForm(
        workspace_root="/tmp/books",
        target_words=100000,
        target_chapters=120,
    )
    form.assist_modes["basic"] = "system"
    form.assist_modes["protagonist"] = "system"
    form.assist_modes["golden_finger"] = "system"
    form.assist_modes["world"] = "system"

    assert module.missing_required_fields(form) == []


def test_build_init_kwargs_clears_irrelevant_relationship_fields():
    module = _load_init_tui_module()

    form = module.InitForm(
        workspace_root="/tmp/books",
        title="测试书",
        project_dir="/tmp/books/测试书",
        genres=["修仙"],
        protagonist_name="林澈",
        protagonist_desire="活下来",
        protagonist_flaw="过度多疑",
        target_words=100000,
        target_chapters=120,
        golden_finger_type="无金手指",
        world_scale="大陆",
        power_system_type="修仙境界制",
        protagonist_structure="单主角",
        co_protagonists="甲,乙",
        co_protagonist_roles="智囊,战力",
        heroine_config="无女主",
        heroine_names="苏晚",
        heroine_role="情感线",
    )

    kwargs = module.build_init_kwargs(form)

    assert kwargs["genre"] == "修仙"
    assert kwargs["co_protagonists"] == ""
    assert kwargs["co_protagonist_roles"] == ""
    assert kwargs["heroine_names"] == ""
    assert kwargs["heroine_role"] == ""


def test_build_init_kwargs_fills_placeholders_for_system_assist():
    module = _load_init_tui_module()

    form = module.InitForm(
        workspace_root="/tmp/books",
        target_words=100000,
        target_chapters=120,
    )
    form.assist_modes["basic"] = "system"
    form.assist_modes["protagonist"] = "system"
    form.assist_modes["golden_finger"] = "system"
    form.assist_modes["world"] = "system"

    kwargs = module.build_init_kwargs(form)

    assert kwargs["title"] == "未命名小说"
    assert kwargs["genre"] == "待Codex建议"
    assert kwargs["protagonist_name"] == "【待 Codex 建议：主角名】"
    assert kwargs["golden_finger_type"] == "【待 Codex 建议：金手指类型】"
    assert kwargs["world_scale"] == "【待 Codex 建议：世界规模】"


def test_build_project_env_content_uses_defaults_and_current_values():
    module = _load_init_tui_module()

    form = module.InitForm(
        workspace_root="/tmp/books",
        embed_api_key="embed-key",
        rerank_api_key="rerank-key",
    )

    content = module.build_project_env_content(form)

    assert "EMBED_BASE_URL=https://api-inference.modelscope.cn/v1" in content
    assert "EMBED_MODEL=Qwen/Qwen3-Embedding-8B" in content
    assert "EMBED_API_KEY=embed-key" in content
    assert "RERANK_BASE_URL=https://api.jina.ai/v1" in content
    assert "RERANK_MODEL=jina-reranker-v3" in content
    assert "RERANK_API_KEY=rerank-key" in content
