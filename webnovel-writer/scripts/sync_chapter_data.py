#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backfill/sync chapter-derived index rows for dashboard and downstream readers.

This script exists because Codex write flow may already have:
- 正文章节文件
- .webnovel/state.json chapter_meta
- .webnovel/summaries/chNNNN.md
- entities / appearances / relationships

but still miss the derived index rows consumed by dashboard/context:
- index.db.chapters
- index.db.scenes
- index.db.chapter_reading_power
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from chapter_paths import extract_chapter_num_from_filename, find_chapter_file
from project_locator import resolve_project_root
from runtime_compat import enable_windows_utf8_stdio

try:
    from data_modules.config import DataModulesConfig
    from data_modules.index_manager import ChapterMeta, ChapterReadingPowerMeta, IndexManager, SceneMeta
    from data_modules.observability import safe_append_perf_timing, safe_log_tool_call
    from data_modules.state_validator import get_chapter_meta_entry
except ImportError:
    from scripts.data_modules.config import DataModulesConfig
    from scripts.data_modules.index_manager import ChapterMeta, ChapterReadingPowerMeta, IndexManager, SceneMeta
    from scripts.data_modules.observability import safe_append_perf_timing, safe_log_tool_call
    from scripts.data_modules.state_validator import get_chapter_meta_entry


TITLE_RE = re.compile(r"^\s*第\s*(?P<num>\d+)\s*章(?:\s*[-:： ]\s*|\s+)?(?P<title>.*)\s*$")
COOLPOINT_PATTERNS: Sequence[Tuple[str, str]] = (
    ("打脸", "打脸"),
    ("反杀", "反杀"),
    ("翻盘", "翻盘"),
    ("破局", "破局"),
    ("救下", "救援"),
    ("救了", "救援"),
    ("觉醒", "觉醒"),
    ("揭穿", "揭露"),
    ("揭开", "揭露"),
    ("真相", "真相推进"),
)
STRONG_HOOK_TYPES = {"危机钩", "悬念钩", "生死钩"}
MEDIUM_HOOK_TYPES = {"承诺钩", "情绪钩", "关系钩", "信息钩"}
LOCATION_ENTITY_TYPES = {"地点", "场景", "星球"}


def _load_state(project_root: Path) -> Dict[str, Any]:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"缺少 state.json: {state_path}")
    return json.loads(state_path.read_text(encoding="utf-8"))


def _discover_chapter_files(project_root: Path) -> List[Tuple[int, Path]]:
    chapters_dir = project_root / "正文"
    if not chapters_dir.is_dir():
        return []
    pairs: List[Tuple[int, Path]] = []
    for path in sorted(chapters_dir.rglob("第*.md")):
        chapter = extract_chapter_num_from_filename(path.name)
        if chapter is None:
            continue
        pairs.append((chapter, path))
    unique: Dict[int, Path] = {}
    for chapter, path in pairs:
        unique.setdefault(chapter, path)
    return sorted(unique.items())


def _strip_summary_markdown(raw: str) -> str:
    lines = [line.rstrip() for line in raw.splitlines()]
    body: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        body.append(stripped)
    return "\n".join(body).strip()


def _load_summary_text(project_root: Path, chapter: int) -> str:
    summary_path = project_root / ".webnovel" / "summaries" / f"ch{chapter:04d}.md"
    if not summary_path.is_file():
        return ""
    return _strip_summary_markdown(summary_path.read_text(encoding="utf-8"))


def _load_review_aggregate(project_root: Path, chapter: int) -> Dict[str, Any]:
    aggregate_path = project_root / ".webnovel" / "reviews" / f"ch{chapter:04d}" / "aggregate.json"
    if not aggregate_path.is_file():
        return {}
    try:
        return json.loads(aggregate_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_reader_pull_metrics(project_root: Path, chapter: int) -> Dict[str, Any]:
    aggregate = _load_review_aggregate(project_root, chapter)
    checkers = aggregate.get("checkers") if isinstance(aggregate, dict) else {}
    checker_row = checkers.get("reader-pull-checker") if isinstance(checkers, dict) else {}
    metrics = checker_row.get("metrics") if isinstance(checker_row, dict) else {}
    return metrics if isinstance(metrics, dict) else {}


def _parse_title(chapter: int, chapter_file: Path, chapter_text: str, chapter_meta: Dict[str, Any]) -> str:
    first_line = ""
    for line in chapter_text.splitlines():
        if line.strip():
            first_line = line.strip()
            break
    if first_line:
        match = TITLE_RE.match(first_line)
        if match:
            parsed = str(match.group("title") or "").strip()
            if parsed:
                return parsed
    title = str(chapter_meta.get("title") or "").strip()
    if title:
        return title
    stem = chapter_file.stem
    match = TITLE_RE.match(stem)
    if match:
        parsed = str(match.group("title") or "").strip()
        if parsed:
            return parsed
    return f"第{chapter}章"


def _count_chars(chapter_text: str) -> int:
    content_lines = chapter_text.splitlines()
    if content_lines and TITLE_RE.match(content_lines[0].strip()):
        content_lines = content_lines[1:]
    body = "".join(content_lines)
    return len(re.sub(r"\s+", "", body))


def _derive_coolpoint_patterns(chapter_meta: Dict[str, Any], chapter_text: str) -> List[str]:
    existing = chapter_meta.get("coolpoint_patterns")
    if isinstance(existing, list):
        normalized = [str(item).strip() for item in existing if str(item).strip()]
        if normalized:
            return normalized
    if isinstance(existing, str) and existing.strip():
        return [part.strip() for part in re.split(r"[、,，/|+；;]+", existing) if part.strip()]

    found: List[str] = []
    for keyword, tag in COOLPOINT_PATTERNS:
        if keyword in chapter_text and tag not in found:
            found.append(tag)

    if found:
        return found

    strand = str(chapter_meta.get("dominant_strand") or "").strip().lower()
    if strand == "fire":
        return ["情绪推进"]
    if strand == "constellation":
        return ["世界观揭露"]
    if strand == "quest":
        return ["任务推进"]
    return []


def _derive_hook_type_and_strength(chapter_meta: Dict[str, Any], review_metrics: Dict[str, Any]) -> Tuple[str, str]:
    hook_type = str(review_metrics.get("hook_type") or chapter_meta.get("hook_type") or "").strip()
    strength = str(review_metrics.get("hook_strength") or chapter_meta.get("hook_strength") or "").strip().lower()
    if strength in {"strong", "medium", "weak"}:
        return hook_type, strength

    unresolved = str(chapter_meta.get("unresolved_question") or "").strip()
    hook = str(chapter_meta.get("hook") or "").strip()
    if hook_type in STRONG_HOOK_TYPES and (hook or unresolved):
        return hook_type, "strong"
    if hook_type in MEDIUM_HOOK_TYPES and (hook or unresolved):
        return hook_type, "medium"
    if hook or unresolved:
        return hook_type, "medium"
    return hook_type, "weak"


def _derive_micropayoffs(chapter_meta: Dict[str, Any], review_metrics: Dict[str, Any]) -> List[str]:
    review_items = review_metrics.get("micropayoffs")
    if isinstance(review_items, list):
        normalized = [str(item).strip() for item in review_items if str(item).strip()]
        if normalized:
            return normalized[:3]

    items: List[str] = []
    ending_state = str(chapter_meta.get("ending_state") or "").strip()
    if ending_state:
        items.append(ending_state)
    summary = str(chapter_meta.get("summary") or "").strip()
    if summary and summary not in items:
        items.append(summary)
    return items[:3]


def _derive_transition(chapter_meta: Dict[str, Any], chapter_text: str, review_metrics: Dict[str, Any]) -> bool:
    review_value = review_metrics.get("is_transition")
    if isinstance(review_value, bool):
        return review_value

    explicit = chapter_meta.get("is_transition")
    if isinstance(explicit, bool):
        return explicit
    stripped = re.sub(r"\s+", "", chapter_text)
    if len(stripped) < 1800:
        return True
    return any(token in stripped for token in ("承上启下", "过渡", "整理思路", "缓一口气"))


def _load_entity_context(manager: IndexManager, chapter: int) -> Tuple[str, List[str]]:
    with manager._get_conn() as conn:  # type: ignore[attr-defined]
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT a.entity_id, e.canonical_name, e.type
            FROM appearances a
            JOIN entities e ON e.id = a.entity_id
            WHERE a.chapter = ?
            ORDER BY
                CASE e.type
                    WHEN '地点' THEN 0
                    WHEN '场景' THEN 0
                    WHEN '星球' THEN 0
                    WHEN '角色' THEN 1
                    ELSE 2
                END,
                e.canonical_name ASC
            """,
            (chapter,),
        ).fetchall()

        location = ""
        characters: List[str] = []
        for row in rows:
            entity_type = str(row["type"] or "")
            name = str(row["canonical_name"] or row["entity_id"] or "").strip()
            if not name:
                continue
            if not location and entity_type in LOCATION_ENTITY_TYPES:
                location = name
            if entity_type == "角色" and name not in characters:
                characters.append(name)
        return location, characters


def sync_single_chapter(
    *,
    project_root: Path,
    manager: IndexManager,
    state: Dict[str, Any],
    chapter: int,
    chapter_file: Path,
) -> Dict[str, Any]:
    chapter_text = chapter_file.read_text(encoding="utf-8")
    chapter_meta = get_chapter_meta_entry(state, chapter)
    review_metrics = _load_reader_pull_metrics(project_root, chapter)
    summary = _load_summary_text(project_root, chapter) or str(chapter_meta.get("summary") or "").strip()
    title = _parse_title(chapter, chapter_file, chapter_text, chapter_meta)
    location, characters = _load_entity_context(manager, chapter)
    word_count = _count_chars(chapter_text)

    manager.add_chapter(
        ChapterMeta(
            chapter=chapter,
            title=title,
            location=location,
            word_count=word_count,
            characters=characters,
            summary=summary,
        )
    )

    lines = chapter_text.splitlines()
    manager.add_scenes(
        chapter,
        [
            SceneMeta(
                chapter=chapter,
                scene_index=1,
                start_line=1,
                end_line=max(1, len(lines)),
                location=location,
                summary=summary,
                characters=characters,
            )
        ],
    )

    hook_type, hook_strength = _derive_hook_type_and_strength(chapter_meta, review_metrics)
    debt_balance_raw = review_metrics.get("debt_balance", 0.0)
    try:
        debt_balance = float(debt_balance_raw)
    except (TypeError, ValueError):
        debt_balance = 0.0
    manager.save_chapter_reading_power(
        ChapterReadingPowerMeta(
            chapter=chapter,
            hook_type=hook_type,
            hook_strength=hook_strength,
            coolpoint_patterns=_derive_coolpoint_patterns(chapter_meta, chapter_text),
            micropayoffs=_derive_micropayoffs(chapter_meta, review_metrics),
            hard_violations=[],
            soft_suggestions=[],
            is_transition=_derive_transition(chapter_meta, chapter_text, review_metrics),
            override_count=0,
            debt_balance=debt_balance,
        )
    )

    return {
        "chapter": chapter,
        "title": title,
        "location": location,
        "word_count": word_count,
        "characters": characters,
        "summary_present": bool(summary),
        "hook_type": hook_type,
        "hook_strength": hook_strength,
    }


def _resolve_targets(project_root: Path, chapter: Optional[int], chapter_file: Optional[Path]) -> List[Tuple[int, Path]]:
    if chapter is not None:
        path = chapter_file or find_chapter_file(project_root, chapter)
        if path is None or not Path(path).is_file():
            raise FileNotFoundError(f"未找到第 {chapter} 章文件")
        return [(int(chapter), Path(path))]

    targets = _discover_chapter_files(project_root)
    if not targets:
        raise FileNotFoundError(f"未在 {project_root / '正文'} 下发现任何章节文件")
    return targets


def sync_project(
    *,
    project_root: Path,
    chapter: Optional[int] = None,
    chapter_file: Optional[Path] = None,
) -> Dict[str, Any]:
    started = time.monotonic()
    state = _load_state(project_root)
    config = DataModulesConfig(project_root=project_root)
    manager = IndexManager(config=config)
    targets = _resolve_targets(project_root, chapter, chapter_file)

    rows: List[Dict[str, Any]] = []
    for chapter_num, path in targets:
        rows.append(sync_single_chapter(project_root=project_root, manager=manager, state=state, chapter=chapter_num, chapter_file=path))

    elapsed_ms = int((time.monotonic() - started) * 1000)
    payload = {
        "project_root": str(project_root),
        "chapters_synced": len(rows),
        "chapters": rows,
        "elapsed_ms": elapsed_ms,
    }
    safe_log_tool_call(manager, tool_name="sync_chapter_data", success=True, chapter=chapter)
    safe_append_perf_timing(
        project_root,
        tool_name="sync_chapter_data",
        success=True,
        elapsed_ms=elapsed_ms,
        chapter=chapter,
        meta={"chapters_synced": len(rows)},
    )
    return payload


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步章节索引与追读力元数据")
    parser.add_argument("--project-root", required=True, help="书项目根目录")
    parser.add_argument("--chapter", type=int, default=None, help="仅同步指定章节")
    parser.add_argument("--chapter-file", default=None, help="指定章节文件路径（可选）")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    project_root = resolve_project_root(str(args.project_root))
    chapter_file = Path(args.chapter_file).resolve() if args.chapter_file else None
    try:
        payload = sync_project(project_root=project_root, chapter=args.chapter, chapter_file=chapter_file)
    except Exception as exc:
        safe_append_perf_timing(
            project_root,
            tool_name="sync_chapter_data",
            success=False,
            elapsed_ms=0,
            chapter=args.chapter,
            error_code="SYNC_FAILED",
            error_message=str(exc),
        )
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        enable_windows_utf8_stdio()
    raise SystemExit(main())
