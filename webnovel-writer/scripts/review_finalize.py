#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Finalize strict desktop review outputs from checker JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from review_agents_runner import (
    aggregate_checker_results,
    append_observability,
    artifact_dir_for_chapter,
    artifact_dir_for_range,
    build_metrics_payload,
    build_range_summary,
    load_valid_checker_payload,
    now_iso,
    render_chapter_report,
    render_range_report,
    report_path_for_range,
    resolve_project_root,
    save_review_metrics,
    sync_chapter_data_after_review,
    write_json,
)
from runtime_compat import enable_windows_utf8_stdio


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON 文件不是对象: {path}")
    return payload


def _resolve_manifest_path(raw_path: Any, *, fallback: Path) -> Path:
    if not raw_path:
        return fallback
    candidate = Path(str(raw_path)).expanduser()
    return candidate if candidate.is_absolute() else fallback.parent / candidate


def _materialize_desktop_checker_logs(
    *,
    chapter_artifact_dir: Path,
    chapter: int,
    manifest: Dict[str, Any],
    results: List[Dict[str, Any]],
) -> None:
    checker_dir = chapter_artifact_dir / "checkers"
    manifest_map: Dict[str, Dict[str, Any]] = {}
    for item in manifest.get("checkers") or []:
        if isinstance(item, dict) and str(item.get("agent") or "").strip():
            manifest_map[str(item["agent"]).strip()] = item

    for payload in results:
        agent = str(payload.get("agent") or "").strip()
        if not agent:
            continue
        manifest_entry = manifest_map.get(agent) or {}
        prompt_path = _resolve_manifest_path(manifest_entry.get("prompt_file"), fallback=checker_dir / f"{agent}.prompt.txt")
        output_path = _resolve_manifest_path(manifest_entry.get("output_file"), fallback=checker_dir / f"{agent}.json")
        stdout_path = _resolve_manifest_path(manifest_entry.get("stdout_log_file"), fallback=checker_dir / f"{agent}.stdout.log")
        stderr_path = _resolve_manifest_path(manifest_entry.get("stderr_log_file"), fallback=checker_dir / f"{agent}.stderr.log")

        if not stdout_path.exists():
            issues = payload.get("issues") or []
            issue_titles = [str(item.get("title") or "").strip() for item in issues if isinstance(item, dict) and str(item.get("title") or "").strip()]
            stdout_lines = [
                f"[desktop_strict] checker={agent}",
                f"chapter={chapter}",
                "source=artifact_chain",
                f"prompt_file={prompt_path}",
                f"output_file={output_path}",
                f"overall_score={payload.get('overall_score', 0)}",
                f"pass={payload.get('pass')}",
                f"issues={len(issues)}",
                f"summary={str(payload.get('summary') or '').strip()}",
            ]
            if issue_titles:
                stdout_lines.append("issue_titles=" + " | ".join(issue_titles))
            stdout_path.write_text("\n".join(stdout_lines) + "\n", encoding="utf-8")

        if not stderr_path.exists():
            stderr_path.write_text(
                "\n".join(
                    [
                        f"[desktop_strict] checker={agent}",
                        "no subprocess stderr captured",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )


def finalize_single_chapter(
    *,
    project_root: Path,
    chapter: int,
    persist_metrics: bool = True,
    sync_on_pass: bool = True,
) -> Dict[str, Any]:
    resolved_project_root = resolve_project_root(str(project_root))
    chapter_artifact_dir = artifact_dir_for_chapter(resolved_project_root, chapter)
    manifest_path = chapter_artifact_dir / "prepare_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"缺少 prepare manifest: {manifest_path}")

    manifest = _read_json(manifest_path)
    selected_checkers = [str(item).strip() for item in manifest.get("selected_checkers") or [] if str(item).strip()]
    if not selected_checkers:
        raise RuntimeError(f"prepare manifest 未给出 selected_checkers: {manifest_path}")

    chapter_file = Path(str(manifest.get("chapter_file") or "")).expanduser().resolve()
    checker_dir = chapter_artifact_dir / "checkers"
    results: List[Dict[str, Any]] = []
    missing: List[str] = []
    invalid: List[str] = []

    for agent in selected_checkers:
        output_path = checker_dir / f"{agent}.json"
        if not output_path.exists():
            missing.append(agent)
            continue
        payload = load_valid_checker_payload(output_path, expected_agent=agent, chapter=chapter)
        if payload is None:
            invalid.append(agent)
            continue
        metrics = payload.setdefault("metrics", {})
        if isinstance(metrics, dict):
            metrics.setdefault("review_mode", "desktop_strict")
        results.append(payload)

    if missing or invalid:
        details: List[str] = []
        if missing:
            details.append(f"缺少 checker 输出: {', '.join(missing)}")
        if invalid:
            details.append(f"checker 输出结构非法: {', '.join(invalid)}")
        raise RuntimeError("; ".join(details))

    _materialize_desktop_checker_logs(
        chapter_artifact_dir=chapter_artifact_dir,
        chapter=chapter,
        manifest=manifest,
        results=results,
    )

    results.sort(key=lambda item: selected_checkers.index(item["agent"]))
    aggregate = aggregate_checker_results(
        chapter=chapter,
        chapter_file=chapter_file,
        selected_checkers=selected_checkers,
        results=results,
    )
    aggregate["execution_mode"] = "desktop_strict"

    post_review_sync: Dict[str, Any] = {"attempted": False, "success": False, "reason": "review_not_passed"}
    if sync_on_pass and aggregate.get("pass"):
        post_review_sync = {"attempted": True, "success": False}
        try:
            sync_payload = sync_chapter_data_after_review(resolved_project_root, chapter)
            post_review_sync.update(
                {
                    "success": True,
                    "chapters_synced": int(sync_payload.get("chapters_synced", 0) or 0),
                    "elapsed_ms": sync_payload.get("elapsed_ms"),
                }
            )
        except Exception as exc:
            post_review_sync["error"] = str(exc)
    aggregate["post_review_sync"] = post_review_sync

    aggregate_path = chapter_artifact_dir / "aggregate.json"
    report_path = report_path_for_range(resolved_project_root, chapter, chapter)
    report_text = render_chapter_report(aggregate, chapter_artifact_dir, report_path)
    report_path.write_text(report_text, encoding="utf-8")
    aggregate["report_file"] = str(report_path)
    aggregate["aggregate_file"] = str(aggregate_path)
    write_json(aggregate_path, aggregate)

    metrics_payload = build_metrics_payload(
        start_chapter=chapter,
        end_chapter=chapter,
        aggregate=aggregate,
        report_path=report_path,
        notes=f"selected_checkers={','.join(selected_checkers)}; generated_by=desktop_strict",
    )
    if persist_metrics:
        save_review_metrics(resolved_project_root, metrics_payload)

    append_observability(
        resolved_project_root,
        {
            "timestamp": now_iso(),
            "tool_name": "review_finalize:aggregate",
            "chapter": chapter,
            "report_file": str(report_path),
            "overall_score": aggregate.get("overall_score", 0),
            "severity_counts": aggregate.get("severity_counts", {}),
            "success": True,
        },
    )

    return aggregate


def finalize_review(
    *,
    project_root: Path,
    chapter: int | None,
    start_chapter: int | None,
    end_chapter: int | None,
    sync_on_pass: bool = True,
) -> Dict[str, Any]:
    resolved_project_root = resolve_project_root(str(project_root))

    if chapter is not None:
        aggregate = finalize_single_chapter(
            project_root=resolved_project_root,
            chapter=int(chapter),
            persist_metrics=True,
            sync_on_pass=sync_on_pass,
        )
        return {
            "status": "ok",
            "mode": "desktop_strict_finalize",
            **aggregate,
        }

    if start_chapter is None or end_chapter is None:
        raise ValueError("必须提供 --chapter，或同时提供 --start-chapter / --end-chapter")
    if int(start_chapter) > int(end_chapter):
        raise ValueError("start_chapter 不能大于 end_chapter")

    chapter_aggregates: List[Dict[str, Any]] = []
    report_files: List[Path] = []
    for chapter_num in range(int(start_chapter), int(end_chapter) + 1):
        aggregate = finalize_single_chapter(
            project_root=resolved_project_root,
            chapter=chapter_num,
            persist_metrics=False,
            sync_on_pass=sync_on_pass,
        )
        chapter_aggregates.append(aggregate)
        report_files.append(Path(str(aggregate["report_file"])))

    summary = build_range_summary(chapter_aggregates, report_files)
    summary["execution_mode"] = "desktop_strict"
    range_artifact_dir = artifact_dir_for_range(resolved_project_root, int(start_chapter), int(end_chapter))
    aggregate_path = range_artifact_dir / "aggregate.json"

    report_path = report_path_for_range(resolved_project_root, int(start_chapter), int(end_chapter))
    report_path.write_text(render_range_report(summary, report_files), encoding="utf-8")
    summary["report_file"] = str(report_path)
    summary["aggregate_file"] = str(aggregate_path)
    write_json(aggregate_path, summary)

    save_review_metrics(
        resolved_project_root,
        {
            "start_chapter": int(start_chapter),
            "end_chapter": int(end_chapter),
            "overall_score": summary.get("overall_score", 0.0),
            "dimension_scores": summary.get("dimension_scores", {}),
            "severity_counts": summary.get("severity_counts", {}),
            "critical_issues": summary.get("critical_issues", []),
            "report_file": str(report_path.relative_to(resolved_project_root)),
            "notes": f"batch_review chapters={start_chapter}-{end_chapter}; generated_by=desktop_strict",
        },
    )

    append_observability(
        resolved_project_root,
        {
            "timestamp": now_iso(),
            "tool_name": "review_finalize:range",
            "start_chapter": int(start_chapter),
            "end_chapter": int(end_chapter),
            "report_file": str(report_path),
            "overall_score": summary.get("overall_score", 0),
            "severity_counts": summary.get("severity_counts", {}),
            "success": True,
        },
    )

    return {
        "status": "ok",
        "mode": "desktop_strict_finalize",
        **summary,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finalize strict desktop review outputs")
    parser.add_argument("--project-root", required=True, help="书项目根目录或可解析到项目根目录的路径")
    parser.add_argument("--chapter", type=int, help="单章审查")
    parser.add_argument("--start-chapter", type=int, help="区间起始章")
    parser.add_argument("--end-chapter", type=int, help="区间结束章")
    parser.add_argument("--no-sync-on-pass", action="store_true", help="通过后不执行 sync-chapter-data")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = finalize_review(
        project_root=Path(args.project_root),
        chapter=args.chapter,
        start_chapter=args.start_chapter,
        end_chapter=args.end_chapter,
        sync_on_pass=not bool(args.no_sync_on_pass),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    enable_windows_utf8_stdio(skip_in_pytest=True)
    raise SystemExit(main())
