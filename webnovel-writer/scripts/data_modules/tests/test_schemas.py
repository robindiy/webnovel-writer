#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from data_modules.schemas import normalize_data_agent_output, validate_data_agent_output


def test_normalize_data_agent_output_accepts_foreshadowing_variants():
    payload = normalize_data_agent_output(
        {
            "entities_appeared": [],
            "entities_new": [],
            "state_changes": [],
            "relationships_new": [],
            "foreshadowing": [
                "旧桥死局另有主谋",
                {"content": "天机盘规则不能白嫖", "tier": "核心"},
            ],
        }
    )

    assert payload["foreshadowing"] == [
        {"content": "旧桥死局另有主谋"},
        {"content": "天机盘规则不能白嫖", "tier": "核心"},
    ]

    validated = validate_data_agent_output(payload)
    assert len(validated.foreshadowing) == 2
    assert validated.foreshadowing[0].content == "旧桥死局另有主谋"


def test_normalize_data_agent_output_accepts_scene_variants():
    payload = normalize_data_agent_output(
        {
            "entities_appeared": [],
            "entities_new": [],
            "state_changes": [],
            "relationships_new": [],
            "scenes": {
                "index": 1,
                "start_line": 1,
                "end_line": 20,
                "location": "乌坦城",
                "summary": "开场",
                "characters": ["xiaoyan"],
            },
        }
    )

    assert payload["scenes"] == [
        {
            "index": 1,
            "start_line": 1,
            "end_line": 20,
            "location": "乌坦城",
            "summary": "开场",
            "characters": ["xiaoyan"],
        }
    ]

    validated = validate_data_agent_output(payload)
    assert validated.scenes is not None
    assert len(validated.scenes) == 1
    assert validated.scenes[0].location == "乌坦城"
