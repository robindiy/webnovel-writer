#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys


def test_update_state_cli_syncs_foreshadowing_from_outline(tmp_path, monkeypatch):
    import update_state as update_state_module

    webnovel_dir = tmp_path / ".webnovel"
    webnovel_dir.mkdir(parents=True, exist_ok=True)
    outline_dir = tmp_path / "大纲"
    outline_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "project_info": {},
        "progress": {"current_chapter": 1, "total_words": 0},
        "protagonist_state": {
            "power": {"realm": "炼气", "layer": 1, "bottleneck": None},
            "location": "村口",
        },
        "relationships": {},
        "world_settings": {},
        "plot_threads": {
            "active_threads": [],
            "foreshadowing": [
                {"content": "临时乱写的伏笔", "status": "未回收", "tier": "支线"}
            ],
        },
        "review_checkpoints": [],
    }
    state_file = webnovel_dir / "state.json"
    state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    (outline_dir / "总纲.md").write_text(
        """# 总纲

## 伏笔表
| 伏笔内容 | 埋设章 | 回收章 | 层级 |
|----------|--------|--------|------|
| 林父留下的破笔记里缺失的最后三页 | 第5章 | 第120章 | 主线 |
| 开运大会真正想开的不是财路而是城运阀门 | 第15章 | 第50章 | 卷内 |
""",
        encoding="utf-8",
    )
    (outline_dir / "第1卷-详细大纲.md").write_text(
        """# 第 1 卷

## 伏笔规划
| 章节 | 操作 | 伏笔内容 |
|------|------|---------|
| 29 | 埋设 | 黑签楼里第一次出现“宁总”称呼 |
| 50 | 新钩子 | 天机盘对宁远山背后的更高名字再次回避 |
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(update_state_module.StateUpdater, "backup", lambda self: True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "update_state",
            "--project-root",
            str(tmp_path),
            "--sync-foreshadowing-from-outline",
        ],
    )
    update_state_module.main()

    updated = json.loads(state_file.read_text(encoding="utf-8"))
    foreshadowing = updated.get("plot_threads", {}).get("foreshadowing", [])
    assert len(foreshadowing) == 4
    assert all(item.get("source") == "outline" for item in foreshadowing)
    assert all(item.get("content") != "临时乱写的伏笔" for item in foreshadowing)

    rows = {item["content"]: item for item in foreshadowing}
    assert rows["林父留下的破笔记里缺失的最后三页"]["planted_chapter"] == 5
    assert rows["林父留下的破笔记里缺失的最后三页"]["target_chapter"] == 120
    assert rows["黑签楼里第一次出现“宁总”称呼"]["planted_chapter"] == 29
    assert rows["天机盘对宁远山背后的更高名字再次回避"]["planted_chapter"] == 50
