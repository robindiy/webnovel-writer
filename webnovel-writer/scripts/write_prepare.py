#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prepare strict desktop write workflow artifacts step-by-step."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Sequence

from codex_write_workflow import (
    _build_context_prompt,
    _build_stage_schema_context,
    _load_context_materials,
    chapter_artifact_dir,
    resolve_project_root,
    start_step,
    start_task,
    write_json,
)
from runtime_compat import enable_windows_utf8_stdio


def _safe_start_task(project_root: Path, chapter: int) -> str | None:
    try:
        start_task(project_root, chapter)
        return None
    except Exception as exc:  # pragma: no cover - depends on current workflow state
        return str(exc)


def _safe_start_step(project_root: Path, step_id: str, step_name: str) -> str | None:
    try:
        start_step(project_root, step_id, step_name)
        return None
    except Exception as exc:  # pragma: no cover - depends on current workflow state
        return str(exc)


def prepare_write(
    *,
    project_root: Path,
    chapter: int,
    mode: str,
) -> Dict[str, Any]:
    resolved_project_root = resolve_project_root(str(project_root))
    artifact_dir = chapter_artifact_dir(resolved_project_root, chapter)
    warnings: list[str] = []

    task_warning = _safe_start_task(resolved_project_root, chapter)
    if task_warning:
        warnings.append(task_warning)
    step_warning = _safe_start_step(resolved_project_root, "Step 1", "Context Agent")
    if step_warning:
        warnings.append(step_warning)

    materials = _load_context_materials(resolved_project_root, chapter)
    materials_path = artifact_dir / "context.materials.json"
    write_json(materials_path, materials)

    prompt_path = artifact_dir / "context_agent.prompt.txt"
    prompt_path.write_text(_build_context_prompt(chapter, materials), encoding="utf-8")
    schema_path = artifact_dir / "context_agent.schema.json"
    write_json(schema_path, _build_stage_schema_context())
    output_path = artifact_dir / "context_agent.result.json"

    manifest = {
        "status": "ok",
        "mode": "desktop_strict_prepare",
        "workflow": "webnovel-write",
        "chapter": chapter,
        "project_root": str(resolved_project_root),
        "artifact_dir": str(artifact_dir),
        "stage": "context",
        "step": {"id": "Step 1", "name": "Context Agent"},
        "prompt_file": str(prompt_path),
        "schema_file": str(schema_path),
        "output_file": str(output_path),
        "materials_file": str(materials_path),
        "warnings": warnings,
    }
    write_json(artifact_dir / "desktop_write_manifest.json", manifest)
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare strict desktop write workflow")
    parser.add_argument("--project-root", required=True, help="书项目根目录或可解析到项目根目录的路径")
    parser.add_argument("--chapter", type=int, required=True, help="目标章节号")
    parser.add_argument("--mode", choices=["standard", "fast", "minimal"], default="standard")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = prepare_write(
        project_root=Path(args.project_root),
        chapter=int(args.chapter),
        mode=str(args.mode),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    enable_windows_utf8_stdio(skip_in_pytest=True)
    raise SystemExit(main())
