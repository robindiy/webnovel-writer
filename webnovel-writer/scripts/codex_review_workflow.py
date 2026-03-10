#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex source-backed review workflow aligned to upstream webnovel-review topology."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from project_locator import resolve_project_root
from runtime_compat import enable_windows_utf8_stdio


SCRIPTS_DIR = Path(__file__).resolve().parent
WEBNOVEL_CLI = SCRIPTS_DIR / "data_modules" / "webnovel.py"
REVIEW_RUNNER = SCRIPTS_DIR / "review_agents_runner.py"


def _parse_range(raw: str) -> Tuple[int, int]:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("章节范围不能为空")
    if "-" in value:
        start_str, end_str = value.split("-", 1)
        start = int(start_str.strip())
        end = int(end_str.strip())
        if start <= 0 or end <= 0 or start > end:
            raise ValueError(f"非法章节范围: {value}")
        return start, end
    chapter = int(value)
    if chapter <= 0:
        raise ValueError(f"非法章节号: {value}")
    return chapter, chapter


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), capture_output=True, text=True, check=False)


def _run_json_command(command: Sequence[str]) -> Dict[str, Any]:
    proc = _run_command(command)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"命令执行失败: {' '.join(command)}")
    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"命令未返回合法 JSON: {' '.join(command)}\n{proc.stdout}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"命令未返回 JSON 对象: {' '.join(command)}")
    return payload


def _webnovel_cmd(project_root: Path, *args: str) -> list[str]:
    return [sys.executable, str(WEBNOVEL_CLI), "--project-root", str(project_root), *args]


def _workflow(project_root: Path, *args: str) -> None:
    proc = _run_command(_webnovel_cmd(project_root, "workflow", *args))
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"workflow 命令失败: {detail}")


def _start_step(project_root: Path, step_id: str, step_name: str) -> None:
    _workflow(project_root, "start-step", "--step-id", step_id, "--step-name", step_name)


def _complete_step(project_root: Path, step_id: str, artifacts: Optional[Dict[str, Any]] = None) -> None:
    payload = json.dumps(artifacts or {"ok": True}, ensure_ascii=False)
    _workflow(project_root, "complete-step", "--step-id", step_id, "--artifacts", payload)


def _start_task(project_root: Path, *, end_chapter: int) -> None:
    _workflow(project_root, "start-task", "--command", "webnovel-review", "--chapter", str(end_chapter))


def _complete_task(project_root: Path, artifacts: Optional[Dict[str, Any]] = None) -> None:
    payload = json.dumps(artifacts or {"ok": True}, ensure_ascii=False)
    _workflow(project_root, "complete-task", "--artifacts", payload)


def _verify_state_exists(project_root: Path) -> Path:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"缺少状态文件: {state_path}")
    return state_path


def _run_review_step(
    *,
    project_root: Path,
    start_chapter: int,
    end_chapter: int,
    mode: str,
    codex_bin: Optional[str],
    max_parallel: int,
    chapter_file: Optional[str],
) -> Dict[str, Any]:
    command = [sys.executable, str(REVIEW_RUNNER), "--project-root", str(project_root), "--mode", mode, "--max-parallel", str(max_parallel)]
    if codex_bin:
        command.extend(["--codex-bin", str(codex_bin)])
    if start_chapter == end_chapter:
        command.extend(["--chapter", str(start_chapter)])
        if chapter_file:
            command.extend(["--chapter-file", str(chapter_file)])
    else:
        command.extend(["--start-chapter", str(start_chapter), "--end-chapter", str(end_chapter)])
    return _run_json_command(command)


def _latest_review_metric(project_root: Path) -> Dict[str, Any]:
    payload = _run_json_command(_webnovel_cmd(project_root, "index", "get-recent-review-metrics", "--limit", "1"))
    data = payload.get("data")
    if isinstance(data, list) and data:
        row = data[0]
        return row if isinstance(row, dict) else {}
    return {}


def _update_state_review(project_root: Path, *, start_chapter: int, end_chapter: int, report_path: Path) -> None:
    rel_report = str(report_path.relative_to(project_root))
    command = _webnovel_cmd(
        project_root,
        "update-state",
        "--",
        "--add-review",
        f"{start_chapter}-{end_chapter}",
        rel_report,
    )
    proc = _run_command(command)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"update-state --add-review 失败: {detail}")


def run_review_workflow(
    *,
    project_root: Path,
    start_chapter: int,
    end_chapter: int,
    mode: str = "auto",
    codex_bin: Optional[str] = None,
    max_parallel: int = 3,
    chapter_file: Optional[str] = None,
) -> Dict[str, Any]:
    project_root = resolve_project_root(str(project_root))
    _verify_state_exists(project_root)

    _start_task(project_root, end_chapter=end_chapter)

    _start_step(project_root, "Step 1", "加载参考")
    _complete_step(project_root, "Step 1", {"ok": True, "source": "webnovel-review topology"})

    _start_step(project_root, "Step 2", "加载项目状态")
    state_path = _verify_state_exists(project_root)
    _complete_step(project_root, "Step 2", {"ok": True, "state_file": str(state_path)})

    _start_step(project_root, "Step 3", "并行调用检查员")
    review_payload = _run_review_step(
        project_root=project_root,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        mode=mode,
        codex_bin=codex_bin,
        max_parallel=max_parallel,
        chapter_file=chapter_file,
    )
    _complete_step(
        project_root,
        "Step 3",
        {
            "ok": True,
            "overall_score": review_payload.get("overall_score"),
            "aggregate_file": review_payload.get("aggregate_file"),
            "report_file": review_payload.get("report_file"),
        },
    )

    _start_step(project_root, "Step 4", "生成审查报告")
    report_path = Path(str(review_payload.get("report_file", ""))).resolve()
    if not report_path.is_file():
        raise FileNotFoundError(f"缺少审查报告: {report_path}")
    _complete_step(project_root, "Step 4", {"ok": True, "report_file": str(report_path)})

    _start_step(project_root, "Step 5", "保存审查指标")
    latest_metrics = _latest_review_metric(project_root)
    _complete_step(
        project_root,
        "Step 5",
        {
            "ok": bool(latest_metrics),
            "metrics": latest_metrics,
        },
    )

    _start_step(project_root, "Step 6", "写回审查记录")
    _update_state_review(project_root, start_chapter=start_chapter, end_chapter=end_chapter, report_path=report_path)
    _complete_step(
        project_root,
        "Step 6",
        {"ok": True, "report_file": str(report_path.relative_to(project_root))},
    )

    _start_step(project_root, "Step 7", "处理关键问题")
    severity_counts = review_payload.get("severity_counts") or {}
    critical_count = int(severity_counts.get("critical", 0) or 0)
    critical_issues = review_payload.get("critical_issues") or []
    needs_user_decision = critical_count > 0 or bool(critical_issues)
    _complete_step(
        project_root,
        "Step 7",
        {
            "ok": not needs_user_decision,
            "critical_count": critical_count,
            "critical_issues": critical_issues,
            "needs_user_decision": needs_user_decision,
        },
    )

    result: Dict[str, Any] = {
        "status": "needs_input" if needs_user_decision else "ok",
        "project_root": str(project_root),
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "mode": mode,
        "report_file": str(report_path),
        "aggregate_file": str(review_payload.get("aggregate_file", "")),
        "overall_score": review_payload.get("overall_score"),
        "severity_counts": severity_counts,
        "critical_issues": critical_issues,
        "workflow_completed": not needs_user_decision,
        "topology": "upstream-webnovel-review",
    }

    if needs_user_decision:
        result["message"] = "发现 critical 问题；按上游拓扑需要用户决定是否立即修复。"
        return result

    _start_step(project_root, "Step 8", "收尾")
    _complete_step(project_root, "Step 8", {"ok": True})
    _complete_task(
        project_root,
        {
            "ok": True,
            "command": "webnovel-review",
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "report_file": str(report_path.relative_to(project_root)),
        },
    )
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex source-backed review workflow")
    parser.add_argument("--project-root", required=True, help="书项目根目录或可解析到项目根目录的路径")
    parser.add_argument("--range", default=None, help="章节范围，如 1-5 或 7")
    parser.add_argument("--chapter", type=int, default=None, help="单章审查")
    parser.add_argument("--start-chapter", type=int, default=None, help="区间起始章")
    parser.add_argument("--end-chapter", type=int, default=None, help="区间结束章")
    parser.add_argument("--chapter-file", default=None, help="单章文件路径（可选）")
    parser.add_argument("--mode", choices=["auto", "minimal", "full"], default="auto")
    parser.add_argument("--codex-bin", default=None)
    parser.add_argument("--max-parallel", type=int, default=3)
    return parser.parse_args(argv)


def _resolve_range(args: argparse.Namespace) -> Tuple[int, int]:
    if args.chapter is not None:
        return int(args.chapter), int(args.chapter)
    if args.start_chapter is not None and args.end_chapter is not None:
        return int(args.start_chapter), int(args.end_chapter)
    if args.range:
        return _parse_range(str(args.range))
    raise SystemExit("必须提供 --chapter、--range，或同时提供 --start-chapter / --end-chapter")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    start_chapter, end_chapter = _resolve_range(args)
    result = run_review_workflow(
        project_root=Path(args.project_root),
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        mode=str(args.mode),
        codex_bin=args.codex_bin,
        max_parallel=int(args.max_parallel),
        chapter_file=args.chapter_file,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    enable_windows_utf8_stdio(skip_in_pytest=True)
    raise SystemExit(main())
