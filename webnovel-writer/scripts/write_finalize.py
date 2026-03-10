#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Finalize strict desktop write workflow stages and materialize next-stage prompts."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Sequence

from pydantic import ValidationError

from codex_write_workflow import (
    _apply_data_payload,
    _build_data_prompt,
    _build_draft_prompt,
    _build_polish_prompt,
    _build_stage_schema_data,
    _build_stage_schema_draft,
    _build_stage_schema_polish,
    _build_stage_schema_style,
    _build_style_prompt,
    _build_result,
    _chapter_stats,
    _load_context_materials,
    _review_mode_for_pipeline,
    _run_review_cli,
    _validate_revision_stage_payload,
    _write_final_files,
    chapter_artifact_dir,
    complete_step,
    complete_task,
    read_text,
    resolve_project_root,
    start_step,
    write_json,
)
from data_modules.schemas import format_validation_error, validate_data_agent_output
from review_finalize import finalize_review
from review_prepare import prepare_review
from runtime_compat import enable_windows_utf8_stdio


def _safe_start_step(project_root: Path, step_id: str, step_name: str) -> str | None:
    try:
        start_step(project_root, step_id, step_name)
        return None
    except Exception as exc:  # pragma: no cover - depends on current workflow state
        return str(exc)


def _safe_complete_step(project_root: Path, step_id: str, artifacts: Dict[str, Any]) -> str | None:
    try:
        complete_step(project_root, step_id, artifacts)
        return None
    except Exception as exc:  # pragma: no cover - depends on current workflow state
        return str(exc)


def _safe_complete_task(project_root: Path, artifacts: Dict[str, Any]) -> str | None:
    try:
        complete_task(project_root, artifacts)
        return None
    except Exception as exc:  # pragma: no cover - depends on current workflow state
        return str(exc)


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON 文件不是对象: {path}")
    return payload


def _write_stage_bundle(*, artifact_dir: Path, stage_name: str, prompt: str, schema: Dict[str, Any]) -> Dict[str, str]:
    prompt_path = artifact_dir / f"{stage_name}.prompt.txt"
    schema_path = artifact_dir / f"{stage_name}.schema.json"
    output_path = artifact_dir / f"{stage_name}.result.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    write_json(schema_path, schema)
    return {
        "prompt_file": str(prompt_path),
        "schema_file": str(schema_path),
        "output_file": str(output_path),
    }


def _snapshot_review_outputs(*, project_root: Path, chapter: int, artifact_dir: Path, snapshot_name: str, review_payload: Dict[str, Any]) -> Dict[str, str]:
    review_dir = project_root / ".webnovel" / "reviews" / f"ch{chapter:04d}"
    snapshot_file = artifact_dir / f"{snapshot_name}.json"
    write_json(snapshot_file, review_payload)

    copied: Dict[str, str] = {"snapshot_file": str(snapshot_file.relative_to(project_root))}

    aggregate_path = review_dir / "aggregate.json"
    if aggregate_path.exists():
        aggregate_snapshot = artifact_dir / f"{snapshot_name}.aggregate.json"
        shutil.copy2(aggregate_path, aggregate_snapshot)
        copied["aggregate_snapshot_file"] = str(aggregate_snapshot.relative_to(project_root))

    manifest_path = review_dir / "prepare_manifest.json"
    if manifest_path.exists():
        manifest_snapshot = artifact_dir / f"{snapshot_name}.prepare_manifest.json"
        shutil.copy2(manifest_path, manifest_snapshot)
        copied["prepare_manifest_snapshot_file"] = str(manifest_snapshot.relative_to(project_root))

    checker_dir = review_dir / "checkers"
    if checker_dir.exists():
        checker_snapshot_dir = artifact_dir / f"{snapshot_name}_checkers"
        if checker_snapshot_dir.exists():
            shutil.rmtree(checker_snapshot_dir)
        shutil.copytree(checker_dir, checker_snapshot_dir)
        copied["checker_snapshot_dir"] = str(checker_snapshot_dir.relative_to(project_root))

    return copied


def _require_fields(payload: Dict[str, Any], fields: Sequence[str], *, label: str) -> None:
    missing: List[str] = []
    for field in fields:
        if field not in payload:
            missing.append(field)
            continue
        value = payload.get(field)
        if value is None:
            missing.append(field)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field)
    if missing:
        raise RuntimeError(f"{label} 缺少必填字段: {', '.join(missing)}")


def _context_payload_path(artifact_dir: Path) -> Path:
    return artifact_dir / "context_agent.result.json"


def _draft_payload_path(artifact_dir: Path) -> Path:
    return artifact_dir / "draft.result.json"


def _style_payload_path(artifact_dir: Path) -> Path:
    return artifact_dir / "style_adapter.result.json"


def _polish_payload_path(artifact_dir: Path) -> Path:
    return artifact_dir / "polish.result.json"


def _data_payload_path(artifact_dir: Path) -> Path:
    return artifact_dir / "data_agent.result.json"


def _context_package_path(artifact_dir: Path) -> Path:
    return artifact_dir / "context_package.json"


def _materials_path(artifact_dir: Path) -> Path:
    return artifact_dir / "context.materials.json"


def _read_title_from_chapter(chapter_file: Path) -> str:
    first_line = chapter_file.read_text(encoding="utf-8").splitlines()[0].strip()
    match = re.match(r"^第\d+章\s+(.+)$", first_line)
    if match:
        return match.group(1).strip()
    return first_line.strip()


def _materialize_stage_logs(*, artifact_dir: Path, stage_name: str, payload: Dict[str, Any]) -> None:
    stdout_path = artifact_dir / f"{stage_name}.stdout.log"
    stderr_path = artifact_dir / f"{stage_name}.stderr.log"

    if not stdout_path.exists():
        lines = [
            f"[desktop_strict] stage={stage_name}",
            "source=artifact_chain",
        ]
        if stage_name == "context_agent":
            task_brief = payload.get("task_brief") if isinstance(payload.get("task_brief"), dict) else {}
            core_task = str(task_brief.get("core_task") or "").strip()
            lines.append(f"chapter={payload.get('chapter', '?')}")
            lines.append(f"core_task={core_task or '—'}")
        elif stage_name == "draft":
            title = str(payload.get("title") or "").strip()
            content = str(payload.get("content") or "")
            lines.append(f"title={title or '—'}")
            lines.append(f"chars={len(content)}")
        elif stage_name in {"style_adapter", "polish"}:
            lines.append(f"full_reread_count={payload.get('full_reread_count', 0)}")
            for report in payload.get("pass_reports", []) or []:
                if not isinstance(report, dict):
                    continue
                pass_id = str(report.get("pass_id") or "pass")
                focus = str(report.get("focus") or "").strip()
                reread = bool(report.get("full_reread"))
                lines.append(f"pass={pass_id} | full_reread={str(reread).lower()} | focus={focus}")
                for item in report.get("applied_changes", []) or []:
                    lines.append(f"  - {item}")
            change_summary = payload.get("change_summary", []) or []
            if change_summary:
                lines.append("change_summary:")
                for item in change_summary:
                    lines.append(f"  - {item}")
        elif stage_name == "data_agent":
            lines.append(f"summary_text={str(payload.get('summary_text') or '').strip()[:120]}")
            lines.append(f"foreshadowing_notes={len(payload.get('foreshadowing_notes') or [])}")
            lines.append(f"foreshadowing_planted={len(payload.get('foreshadowing_planted') or [])}")
            lines.append(f"foreshadowing_continued={len(payload.get('foreshadowing_continued') or [])}")
            lines.append(f"foreshadowing_resolved={len(payload.get('foreshadowing_resolved') or [])}")
            lines.append(f"scenes={len(payload.get('scenes') or [])}")
        stdout_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    if not stderr_path.exists():
        stderr_path.write_text(
            f"[desktop_strict] stage={stage_name}\nno subprocess stderr captured\n",
            encoding="utf-8",
        )


def _finalize_context(*, project_root: Path, chapter: int, mode: str, artifact_dir: Path) -> Dict[str, Any]:
    context_payload = _read_json(_context_payload_path(artifact_dir))
    _require_fields(context_payload, ("chapter", "task_brief", "contract_v2", "draft_package"), label="context_agent.result.json")
    _materialize_stage_logs(artifact_dir=artifact_dir, stage_name="context_agent", payload=context_payload)
    write_json(_context_package_path(artifact_dir), context_payload)

    warnings: List[str] = []
    warning = _safe_complete_step(
        project_root,
        "Step 1",
        {"context_package": str(_context_package_path(artifact_dir).relative_to(project_root))},
    )
    if warning:
        warnings.append(warning)
    warning = _safe_start_step(project_root, "Step 2A", "正文起草")
    if warning:
        warnings.append(warning)

    bundle = _write_stage_bundle(
        artifact_dir=artifact_dir,
        stage_name="draft",
        prompt=_build_draft_prompt(chapter, context_payload, mode),
        schema=_build_stage_schema_draft(),
    )
    payload = {
        "status": "ok",
        "mode": "desktop_strict_finalize",
        "workflow": "webnovel-write",
        "chapter": chapter,
        "stage": "draft",
        "step": {"id": "Step 2A", "name": "正文起草"},
        "warnings": warnings,
        **bundle,
    }
    write_json(artifact_dir / "desktop_write_manifest.json", payload)
    return payload


def _finalize_draft(*, project_root: Path, chapter: int, mode: str, artifact_dir: Path) -> Dict[str, Any]:
    context_package = _read_json(_context_package_path(artifact_dir))
    draft_payload = _read_json(_draft_payload_path(artifact_dir))
    _require_fields(draft_payload, ("title", "content"), label="draft.result.json")
    _materialize_stage_logs(artifact_dir=artifact_dir, stage_name="draft", payload=draft_payload)

    title = str(draft_payload.get("title") or "").strip()
    chapter_path = _write_final_files(project_root, chapter, title, str(draft_payload.get("content") or ""))
    warnings: List[str] = []
    warning = _safe_complete_step(
        project_root,
        "Step 2A",
        {
            "chapter_file": str(chapter_path.relative_to(project_root)),
            "chars": len(chapter_path.read_text(encoding="utf-8")),
        },
    )
    if warning:
        warnings.append(warning)

    if mode == "standard":
        warning = _safe_start_step(project_root, "Step 2B", "风格适配")
        if warning:
            warnings.append(warning)
        bundle = _write_stage_bundle(
            artifact_dir=artifact_dir,
            stage_name="style_adapter",
            prompt=_build_style_prompt(
                chapter,
                title,
                str(chapter_path.relative_to(project_root)),
                read_text(chapter_path),
                context_package,
            ),
            schema=_build_stage_schema_style(),
        )
        payload = {
            "status": "ok",
            "mode": "desktop_strict_finalize",
            "workflow": "webnovel-write",
            "chapter": chapter,
            "stage": "style",
            "step": {"id": "Step 2B", "name": "风格适配"},
            "chapter_file": str(chapter_path.relative_to(project_root)),
            "warnings": warnings,
            **bundle,
        }
    else:
        warning = _safe_start_step(project_root, "Step 2B", "风格适配")
        if warning:
            warnings.append(warning)
        warning = _safe_complete_step(project_root, "Step 2B", {"skipped": True, "mode": mode})
        if warning:
            warnings.append(warning)
        warning = _safe_start_step(project_root, "Step 3", "审查")
        if warning:
            warnings.append(warning)
        review_manifest = prepare_review(project_root=project_root, chapter=chapter, start_chapter=None, end_chapter=None, mode=_review_mode_for_pipeline(mode), chapter_file=chapter_path)
        payload = {
            "status": "ok",
            "mode": "desktop_strict_finalize",
            "workflow": "webnovel-write",
            "chapter": chapter,
            "stage": "review_initial",
            "step": {"id": "Step 3", "name": "审查"},
            "chapter_file": str(chapter_path.relative_to(project_root)),
            "warnings": warnings,
            "review_manifest": review_manifest,
        }

    write_json(artifact_dir / "desktop_write_manifest.json", payload)
    return payload


def _finalize_style(*, project_root: Path, chapter: int, mode: str, artifact_dir: Path) -> Dict[str, Any]:
    style_payload = _read_json(_style_payload_path(artifact_dir))
    _require_fields(style_payload, ("content", "change_summary", "pass_reports", "full_reread_count"), label="style_adapter.result.json")
    _materialize_stage_logs(artifact_dir=artifact_dir, stage_name="style_adapter", payload=style_payload)
    _validate_revision_stage_payload(
        style_payload,
        label="style_adapter.result.json",
        min_pass_reports=2,
        min_full_rereads=1,
    )

    chapter_path = _chapter_file_from_path(project_root, chapter)
    if chapter_path.exists():
        title = _read_title_from_chapter(chapter_path)
    else:
        title = str(style_payload.get("title") or f"第{chapter}章").strip()
    chapter_path = _write_final_files(project_root, chapter, title, str(style_payload.get("content") or ""))

    warnings: List[str] = []
    warning = _safe_complete_step(
        project_root,
        "Step 2B",
        {
            "chapter_file": str(chapter_path.relative_to(project_root)),
            "styled": True,
            "change_summary": style_payload.get("change_summary", []),
            "full_reread_count": style_payload.get("full_reread_count", 0),
        },
    )
    if warning:
        warnings.append(warning)
    warning = _safe_start_step(project_root, "Step 3", "审查")
    if warning:
        warnings.append(warning)
    review_manifest = prepare_review(project_root=project_root, chapter=chapter, start_chapter=None, end_chapter=None, mode=_review_mode_for_pipeline(mode), chapter_file=chapter_path)
    payload = {
        "status": "ok",
        "mode": "desktop_strict_finalize",
        "workflow": "webnovel-write",
        "chapter": chapter,
        "stage": "review_initial",
        "step": {"id": "Step 3", "name": "审查"},
        "chapter_file": str(chapter_path.relative_to(project_root)),
        "warnings": warnings,
        "review_manifest": review_manifest,
    }
    write_json(artifact_dir / "desktop_write_manifest.json", payload)
    return payload


def _chapter_file_from_path(project_root: Path, chapter: int) -> Path:
    from chapter_paths import default_chapter_draft_path

    return default_chapter_draft_path(project_root, chapter, use_volume_layout=True)


def _load_review_payload(project_root: Path, chapter: int) -> Dict[str, Any]:
    aggregate_path = project_root / ".webnovel" / "reviews" / f"ch{chapter:04d}" / "aggregate.json"
    if not aggregate_path.exists():
        raise FileNotFoundError(f"缺少审查聚合文件: {aggregate_path}")
    return _read_json(aggregate_path)


def _finalize_review_initial(*, project_root: Path, chapter: int, mode: str, artifact_dir: Path) -> Dict[str, Any]:
    review_payload = finalize_review(project_root=project_root, chapter=chapter, start_chapter=None, end_chapter=None, sync_on_pass=True)
    if str(review_payload.get("execution_mode") or "") != "desktop_strict":
        raise RuntimeError("Desktop strict 审查未生成 desktop_strict aggregate")
    snapshot_info = _snapshot_review_outputs(
        project_root=project_root,
        chapter=chapter,
        artifact_dir=artifact_dir,
        snapshot_name="review_initial",
        review_payload=review_payload,
    )

    warnings: List[str] = []
    warning = _safe_complete_step(
        project_root,
        "Step 3",
        {
            "overall_score": review_payload.get("overall_score"),
            "report_file": review_payload.get("report_file"),
            "aggregate_file": review_payload.get("aggregate_file"),
        },
    )
    if warning:
        warnings.append(warning)
    warning = _safe_start_step(project_root, "Step 4", "润色")
    if warning:
        warnings.append(warning)

    chapter_path = _chapter_file_from_path(project_root, chapter)
    title = _read_title_from_chapter(chapter_path)
    bundle = _write_stage_bundle(
        artifact_dir=artifact_dir,
        stage_name="polish",
        prompt=_build_polish_prompt(
            chapter,
            title,
            str(chapter_path.relative_to(project_root)),
            read_text(chapter_path),
            review_payload,
        ),
        schema=_build_stage_schema_polish(),
    )
    payload = {
        "status": "ok",
        "mode": "desktop_strict_finalize",
        "workflow": "webnovel-write",
        "chapter": chapter,
        "stage": "polish",
        "step": {"id": "Step 4", "name": "润色"},
        "warnings": warnings,
        "review_payload": review_payload,
        **snapshot_info,
        **bundle,
    }
    write_json(artifact_dir / "desktop_write_manifest.json", payload)
    return payload


def _finalize_polish(*, project_root: Path, chapter: int, mode: str, artifact_dir: Path) -> Dict[str, Any]:
    polish_payload = _read_json(_polish_payload_path(artifact_dir))
    _materialize_stage_logs(artifact_dir=artifact_dir, stage_name="polish", payload=polish_payload)
    _require_fields(
        polish_payload,
        ("content", "change_summary", "anti_ai_force_check", "deviation", "pass_reports", "full_reread_count"),
        label="polish.result.json",
    )
    _validate_revision_stage_payload(
        polish_payload,
        label="polish.result.json",
        min_pass_reports=3,
        min_full_rereads=2,
    )
    if str(polish_payload.get("anti_ai_force_check") or "").strip() != "pass":
        raise RuntimeError("anti_ai_force_check != pass，禁止进入 Step 5")

    chapter_path = _chapter_file_from_path(project_root, chapter)
    title = _read_title_from_chapter(chapter_path)
    chapter_path = _write_final_files(project_root, chapter, title, str(polish_payload.get("content") or ""))
    write_json(artifact_dir / "polish.applied.json", polish_payload)

    review_manifest = prepare_review(
        project_root=project_root,
        chapter=chapter,
        start_chapter=None,
        end_chapter=None,
        mode=_review_mode_for_pipeline(mode),
        chapter_file=chapter_path,
    )
    payload = {
        "status": "ok",
        "mode": "desktop_strict_finalize",
        "workflow": "webnovel-write",
        "chapter": chapter,
        "stage": "review_final",
        "step": {"id": "Step 4", "name": "润色"},
        "chapter_file": str(chapter_path.relative_to(project_root)),
        "polish_payload_file": str((artifact_dir / "polish.applied.json").relative_to(project_root)),
        "review_manifest": review_manifest,
    }
    write_json(artifact_dir / "desktop_write_manifest.json", payload)
    return payload


def _finalize_review_final(*, project_root: Path, chapter: int, mode: str, artifact_dir: Path, enable_debt_interest: bool) -> Dict[str, Any]:
    polish_payload = _read_json(artifact_dir / "polish.applied.json")
    final_review = finalize_review(project_root=project_root, chapter=chapter, start_chapter=None, end_chapter=None, sync_on_pass=True)
    if str(final_review.get("execution_mode") or "") != "desktop_strict":
        raise RuntimeError("Desktop strict 复审未生成 desktop_strict aggregate")
    snapshot_info = _snapshot_review_outputs(
        project_root=project_root,
        chapter=chapter,
        artifact_dir=artifact_dir,
        snapshot_name="review_final",
        review_payload=final_review,
    )
    severity_counts = final_review.get("severity_counts") or {}
    critical_count = int(severity_counts.get("critical", 0) or 0)
    high_count = int(severity_counts.get("high", 0) or 0)
    if critical_count > 0:
        raise RuntimeError(f"Step 4 后仍存在 critical 问题: {critical_count}")
    if high_count > 0 and not (polish_payload.get("deviation") or []):
        raise RuntimeError(f"Step 4 后仍存在 high 问题且未记录 deviation: {high_count}")

    warnings: List[str] = []
    warning = _safe_complete_step(
        project_root,
        "Step 4",
        {
            "anti_ai_force_check": polish_payload.get("anti_ai_force_check"),
            "change_summary": polish_payload.get("change_summary", []),
            "deviation": polish_payload.get("deviation", []),
            "full_reread_count": polish_payload.get("full_reread_count", 0),
            "final_overall_score": final_review.get("overall_score"),
        },
    )
    if warning:
        warnings.append(warning)
    warning = _safe_start_step(project_root, "Step 5", "Data Agent")
    if warning:
        warnings.append(warning)

    materials = _read_json(_materials_path(artifact_dir)) if _materials_path(artifact_dir).exists() else _load_context_materials(project_root, chapter)
    context_package = _read_json(_context_package_path(artifact_dir))
    chapter_path = _chapter_file_from_path(project_root, chapter)
    title = _read_title_from_chapter(chapter_path)
    bundle = _write_stage_bundle(
        artifact_dir=artifact_dir,
        stage_name="data_agent",
        prompt=_build_data_prompt(chapter, title, read_text(chapter_path), final_review, context_package, materials),
        schema=_build_stage_schema_data(),
    )
    payload = {
        "status": "ok",
        "mode": "desktop_strict_finalize",
        "workflow": "webnovel-write",
        "chapter": chapter,
        "stage": "data",
        "step": {"id": "Step 5", "name": "Data Agent"},
        "warnings": warnings,
        "enable_debt_interest": enable_debt_interest,
        "final_review": final_review,
        **snapshot_info,
        **bundle,
    }
    write_json(artifact_dir / "desktop_write_manifest.json", payload)
    return payload


def _finalize_data(*, project_root: Path, chapter: int, artifact_dir: Path, enable_debt_interest: bool) -> Dict[str, Any]:
    data_payload = _read_json(_data_payload_path(artifact_dir))
    _materialize_stage_logs(artifact_dir=artifact_dir, stage_name="data_agent", payload=data_payload)
    required_fields = (
        "entities_appeared",
        "entities_new",
        "state_changes",
        "relationships_new",
        "scenes_chunked",
        "uncertain",
        "warnings",
        "chapter_meta",
        "summary_text",
        "foreshadowing_notes",
        "foreshadowing_planted",
        "foreshadowing_continued",
        "foreshadowing_resolved",
        "bridge_line",
        "scenes",
    )
    _require_fields(data_payload, required_fields, label="data_agent.result.json")
    try:
        validate_data_agent_output(data_payload)
    except ValidationError as exc:
        detail = format_validation_error(exc)
        raise RuntimeError(json.dumps(detail, ensure_ascii=False))
    final_review = _load_review_payload(project_root, chapter)
    data_payload["review_score"] = final_review.get("overall_score")
    write_json(artifact_dir / "data_agent.applied.json", data_payload)

    data_result = _apply_data_payload(
        project_root,
        chapter=chapter,
        data_payload=data_payload,
        artifact_dir=artifact_dir,
        enable_debt_interest=enable_debt_interest,
    )
    summary_file = project_root / ".webnovel" / "summaries" / f"ch{chapter:04d}.md"

    warnings: List[str] = []
    warning = _safe_complete_step(
        project_root,
        "Step 5",
        {
            "summary_file": str(summary_file.relative_to(project_root)),
            "state_file": ".webnovel/state.json",
            "index_file": ".webnovel/index.db",
            "timing_ms": data_result.get("timing_ms", {}),
        },
    )
    if warning:
        warnings.append(warning)
    warning = _safe_start_step(project_root, "Step 6", "Git 备份")
    if warning:
        warnings.append(warning)
    warning = _safe_complete_step(project_root, "Step 6", {"git_backup": "skipped_per_codex_instructions"})
    if warning:
        warnings.append(warning)

    chapter_file = _chapter_file_from_path(project_root, chapter)
    final_stats = _chapter_stats(project_root)
    style_payload = _read_json(_style_payload_path(artifact_dir)) if _style_payload_path(artifact_dir).exists() else {}
    polish_payload = _read_json(artifact_dir / "polish.applied.json") if (artifact_dir / "polish.applied.json").exists() else {}
    result = _build_result(
        project_root=project_root,
        chapter=chapter,
        chapter_file=chapter_file,
        summary_file=summary_file,
        review_payload=final_review,
        final_stats=final_stats,
        style_payload=style_payload,
        polish_payload=polish_payload,
        data_result=data_result,
    )
    warning = _safe_complete_task(
        project_root,
        {
            "ok": True,
            "command": "webnovel-write",
            "chapter": chapter,
            "chapter_file": str(chapter_file.relative_to(project_root)),
            "summary_file": str(summary_file.relative_to(project_root)),
            "overall_score": final_review.get("overall_score"),
        },
    )
    if warning:
        warnings.append(warning)
    result["warnings"] = warnings
    write_json(artifact_dir / "final_result.json", result)
    return result


def finalize_stage(
    *,
    project_root: Path,
    chapter: int,
    stage: str,
    mode: str,
    enable_debt_interest: bool,
) -> Dict[str, Any]:
    resolved_project_root = resolve_project_root(str(project_root))
    artifact_dir = chapter_artifact_dir(resolved_project_root, chapter)

    if stage == "context":
        return _finalize_context(project_root=resolved_project_root, chapter=chapter, mode=mode, artifact_dir=artifact_dir)
    if stage == "draft":
        return _finalize_draft(project_root=resolved_project_root, chapter=chapter, mode=mode, artifact_dir=artifact_dir)
    if stage == "style":
        return _finalize_style(project_root=resolved_project_root, chapter=chapter, mode=mode, artifact_dir=artifact_dir)
    if stage == "review-initial":
        return _finalize_review_initial(project_root=resolved_project_root, chapter=chapter, mode=mode, artifact_dir=artifact_dir)
    if stage == "polish":
        return _finalize_polish(project_root=resolved_project_root, chapter=chapter, mode=mode, artifact_dir=artifact_dir)
    if stage == "review-final":
        return _finalize_review_final(project_root=resolved_project_root, chapter=chapter, mode=mode, artifact_dir=artifact_dir, enable_debt_interest=enable_debt_interest)
    if stage == "data":
        return _finalize_data(project_root=resolved_project_root, chapter=chapter, artifact_dir=artifact_dir, enable_debt_interest=enable_debt_interest)
    raise ValueError(f"不支持的 stage: {stage}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize strict desktop write stages")
    parser.add_argument("--project-root", required=True, help="书项目根目录或可解析到项目根目录的路径")
    parser.add_argument("--chapter", type=int, required=True, help="目标章节号")
    parser.add_argument(
        "--stage",
        required=True,
        choices=["context", "draft", "style", "review-initial", "polish", "review-final", "data"],
        help="要收口的流程阶段",
    )
    parser.add_argument("--mode", choices=["standard", "fast", "minimal"], default="standard")
    parser.add_argument("--enable-debt-interest", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = finalize_stage(
        project_root=Path(args.project_root),
        chapter=int(args.chapter),
        stage=str(args.stage),
        mode=str(args.mode),
        enable_debt_interest=bool(args.enable_debt_interest),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    enable_windows_utf8_stdio(skip_in_pytest=True)
    raise SystemExit(main())
