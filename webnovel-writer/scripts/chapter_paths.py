#!/usr/bin/env python3
"""
Chapter file path helpers.

This project has seen multiple chapter filename conventions:
1) Legacy flat layout: 正文/第0007章.md
2) Volume layout:    正文/第1卷/第007章-章节标题.md

To keep scripts robust, always resolve chapter files via these helpers instead of hardcoding a format.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


_CHAPTER_NUM_RE = re.compile(r"第(?P<num>\d+)章")
_CHAPTER_RANGE_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


def volume_num_for_chapter(chapter_num: int, *, chapters_per_volume: int = 50) -> int:
    if chapter_num <= 0:
        raise ValueError("chapter_num must be >= 1")
    return (chapter_num - 1) // chapters_per_volume + 1


def _parse_chapters_range(value: object) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    m = _CHAPTER_RANGE_RE.match(value)
    if not m:
        return None
    try:
        start = int(m.group(1))
        end = int(m.group(2))
    except ValueError:
        return None
    if start <= 0 or end <= 0 or start > end:
        return None
    return start, end


def planned_volume_num_for_chapter(project_root: Path, chapter_num: int, *, chapters_per_volume: int = 50) -> int:
    state_path = project_root / ".webnovel" / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
        progress = state.get("progress") if isinstance(state, dict) else None
        volumes_planned = progress.get("volumes_planned") if isinstance(progress, dict) else None
        if isinstance(volumes_planned, list):
            best_match: tuple[int, int] | None = None
            for item in volumes_planned:
                if not isinstance(item, dict):
                    continue
                volume = item.get("volume")
                if not isinstance(volume, int) or volume <= 0:
                    continue
                parsed = _parse_chapters_range(item.get("chapters_range"))
                if not parsed:
                    continue
                start, end = parsed
                if start <= chapter_num <= end:
                    candidate = (start, volume)
                    if best_match is None or candidate[0] > best_match[0] or (
                        candidate[0] == best_match[0] and candidate[1] < best_match[1]
                    ):
                        best_match = candidate
            if best_match is not None:
                return best_match[1]

    return volume_num_for_chapter(chapter_num, chapters_per_volume=chapters_per_volume)


def should_use_volume_layout(project_root: Path) -> bool:
    chapters_dir = project_root / "正文"
    if any(path.is_dir() for path in chapters_dir.glob("第*卷")):
        return True

    state_path = project_root / ".webnovel" / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
        progress = state.get("progress") if isinstance(state, dict) else None
        volumes_planned = progress.get("volumes_planned") if isinstance(progress, dict) else None
        if isinstance(volumes_planned, list) and volumes_planned:
            return True

    return False


def volume_dir_for_chapter(project_root: Path, chapter_num: int, *, chapters_per_volume: int = 50) -> Path:
    volume_num = planned_volume_num_for_chapter(
        project_root,
        chapter_num,
        chapters_per_volume=chapters_per_volume,
    )
    return project_root / "正文" / f"第{volume_num}卷"


def _volume_layout_filename(chapter_num: int) -> str:
    width = max(3, len(str(chapter_num)))
    return f"第{chapter_num:0{width}d}章.md"


def extract_chapter_num_from_filename(filename: str) -> Optional[int]:
    m = _CHAPTER_NUM_RE.search(filename)
    if not m:
        return None
    try:
        return int(m.group("num"))
    except ValueError:
        return None


def find_chapter_file(project_root: Path, chapter_num: int) -> Optional[Path]:
    """
    Find an existing chapter file for chapter_num under project_root/正文.
    Returns the first match (stable sorted order) or None if not found.
    """
    chapters_dir = project_root / "正文"
    if not chapters_dir.exists():
        return None

    vol_dir = volume_dir_for_chapter(project_root, chapter_num)
    if vol_dir.exists():
        candidates = sorted(vol_dir.glob(f"第{chapter_num:03d}章*.md")) + sorted(vol_dir.glob(f"第{chapter_num:04d}章*.md"))
        for c in candidates:
            if c.is_file():
                return c

    legacy = chapters_dir / f"第{chapter_num:04d}章.md"
    if legacy.exists():
        return legacy

    # Fallback: search anywhere under 正文/ (supports custom layouts)
    candidates = sorted(chapters_dir.rglob(f"第{chapter_num:03d}章*.md")) + sorted(chapters_dir.rglob(f"第{chapter_num:04d}章*.md"))
    for c in candidates:
        if c.is_file():
            return c

    return None


def default_chapter_draft_path(project_root: Path, chapter_num: int, *, use_volume_layout: Optional[bool] = None) -> Path:
    """
    Preferred draft path when creating a new chapter file.

    Args:
        project_root: 项目根目录
        chapter_num: 章节号
        use_volume_layout:
            - True 使用卷布局 (正文/第N卷/第NNN章.md)
            - False 使用平坦布局 (正文/第NNNN章.md)
            - None 自动根据项目结构与 state.json 判断

    Default is auto layout; volume layout is preferred when the project has planned volumes.
    """
    if use_volume_layout is None:
        use_volume_layout = should_use_volume_layout(project_root)

    if use_volume_layout:
        vol_dir = volume_dir_for_chapter(project_root, chapter_num)
        return vol_dir / _volume_layout_filename(chapter_num)
    else:
        # Flat layout: 正文/第NNNN章.md (matches SKILL.md)
        return project_root / "正文" / f"第{chapter_num:04d}章.md"
