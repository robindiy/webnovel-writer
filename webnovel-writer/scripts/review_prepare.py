#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare strict desktop review artifacts without spawning child codex exec workers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from chapter_paths import find_chapter_file
from extract_chapter_context import build_chapter_context_payload
from review_agents_runner import (
    artifact_dir_for_chapter,
    artifact_dir_for_range,
    build_checker_prompt,
    checker_output_schema,
    ensure_dir,
    make_context_dump,
    read_chapter_text,
    reset_chapter_artifacts,
    resolve_chapter_file,
    resolve_project_root,
    select_checkers,
    write_json,
)
from runtime_compat import enable_windows_utf8_stdio


def _prepare_single_chapter(
    *,
    project_root: Path,
    chapter: int,
    mode: str,
    chapter_file: Path | None = None,
) -> Dict[str, Any]:
    resolved_project_root = resolve_project_root(str(project_root))
    resolved_chapter_file = resolve_chapter_file(resolved_project_root, chapter_file) or find_chapter_file(
        resolved_project_root,
        chapter,
    )
    if resolved_chapter_file is None:
        raise FileNotFoundError(f"未找到第 {chapter} 章文件")

    chapter_artifact_dir = artifact_dir_for_chapter(resolved_project_root, chapter)
    reset_chapter_artifacts(chapter_artifact_dir)
    checker_dir = ensure_dir(chapter_artifact_dir / "checkers")

    context_payload = build_chapter_context_payload(resolved_project_root, chapter)
    context_file = make_context_dump(context_payload, resolved_chapter_file, chapter_artifact_dir)
    chapter_text = read_chapter_text(resolved_chapter_file)
    selected_checkers = select_checkers(
        chapter=chapter,
        chapter_text=chapter_text,
        context_payload=context_payload,
        mode=mode,
    )

    schema_path = chapter_artifact_dir / "checker-output.schema.json"
    write_json(schema_path, checker_output_schema())

    checker_manifests: List[Dict[str, Any]] = []
    for agent in selected_checkers:
        prompt = build_checker_prompt(
            agent=agent,
            chapter=chapter,
            chapter_file=resolved_chapter_file,
            context_payload=context_payload,
            chapter_text=chapter_text,
            project_root=resolved_project_root,
            artifact_dir=chapter_artifact_dir,
        )
        prompt_path = checker_dir / f"{agent}.prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        checker_manifests.append(
            {
                "agent": agent,
                "prompt_file": str(prompt_path),
                "output_file": str(checker_dir / f"{agent}.json"),
                "stdout_log_file": str(checker_dir / f"{agent}.stdout.log"),
                "stderr_log_file": str(checker_dir / f"{agent}.stderr.log"),
            }
        )

    manifest = {
        "chapter": chapter,
        "mode": mode,
        "project_root": str(resolved_project_root),
        "chapter_file": str(resolved_chapter_file),
        "artifact_dir": str(chapter_artifact_dir),
        "context_file": str(context_file),
        "checker_schema_file": str(schema_path),
        "selected_checkers": selected_checkers,
        "checkers": checker_manifests,
    }
    write_json(chapter_artifact_dir / "prepare_manifest.json", manifest)
    return manifest


def prepare_review(
    *,
    project_root: Path,
    chapter: int | None,
    start_chapter: int | None,
    end_chapter: int | None,
    mode: str,
    chapter_file: Path | None = None,
) -> Dict[str, Any]:
    resolved_project_root = resolve_project_root(str(project_root))

    if chapter is not None:
        manifest = _prepare_single_chapter(
            project_root=resolved_project_root,
            chapter=int(chapter),
            chapter_file=chapter_file,
            mode=mode,
        )
        return {
            "status": "ok",
            "mode": "desktop_strict_prepare",
            "project_root": str(resolved_project_root),
            "chapter": int(chapter),
            "chapters": [manifest],
        }

    if start_chapter is None or end_chapter is None:
        raise ValueError("必须提供 --chapter，或同时提供 --start-chapter / --end-chapter")
    if int(start_chapter) > int(end_chapter):
        raise ValueError("start_chapter 不能大于 end_chapter")

    chapter_manifests: List[Dict[str, Any]] = []
    for chapter_num in range(int(start_chapter), int(end_chapter) + 1):
        chapter_manifests.append(
            _prepare_single_chapter(
                project_root=resolved_project_root,
                chapter=chapter_num,
                mode=mode,
            )
        )

    range_artifact_dir = artifact_dir_for_range(resolved_project_root, int(start_chapter), int(end_chapter))
    range_manifest = {
        "start_chapter": int(start_chapter),
        "end_chapter": int(end_chapter),
        "mode": mode,
        "project_root": str(resolved_project_root),
        "artifact_dir": str(range_artifact_dir),
        "chapters": chapter_manifests,
    }
    write_json(range_artifact_dir / "prepare_manifest.json", range_manifest)
    return {
        "status": "ok",
        "mode": "desktop_strict_prepare",
        "project_root": str(resolved_project_root),
        "start_chapter": int(start_chapter),
        "end_chapter": int(end_chapter),
        "chapters": chapter_manifests,
        "range_manifest": str(range_artifact_dir / "prepare_manifest.json"),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare strict desktop review checker prompts")
    parser.add_argument("--project-root", required=True, help="书项目根目录或可解析到项目根目录的路径")
    parser.add_argument("--chapter", type=int, help="单章审查")
    parser.add_argument("--start-chapter", type=int, help="区间起始章")
    parser.add_argument("--end-chapter", type=int, help="区间结束章")
    parser.add_argument("--chapter-file", help="显式指定单章文件路径（可选）")
    parser.add_argument("--mode", choices=["auto", "minimal", "full"], default="auto", help="审查路由模式")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = prepare_review(
        project_root=Path(args.project_root),
        chapter=args.chapter,
        start_chapter=args.start_chapter,
        end_chapter=args.end_chapter,
        mode=str(args.mode),
        chapter_file=Path(args.chapter_file) if args.chapter_file else None,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    enable_windows_utf8_stdio(skip_in_pytest=True)
    raise SystemExit(main())
