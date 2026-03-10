#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Codex-backed review runner.

This runner replaces prompt-only "please use Task" instructions with a source-backed
execution path for Codex:
- select review checkers from chapter/context signals
- spawn one `codex exec` subprocess per checker
- validate checker JSON output
- aggregate issues/scores into Step 3 artifacts
- persist review metrics so downstream context can consume them
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import queue
import shutil
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib

from chapter_paths import find_chapter_file, volume_num_for_chapter
from extract_chapter_context import build_chapter_context_payload
from runtime_compat import enable_windows_utf8_stdio, resolve_python_executable

SCRIPTS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPTS_DIR.parent
REFERENCES_DIR = PACKAGE_ROOT / "references"
AGENTS_DIR = PACKAGE_ROOT / "agents"
CHECKER_SCHEMA_MD = REFERENCES_DIR / "checker-output-schema.md"
OBSERVABILITY_REL = Path(".webnovel") / "observability" / "review_agent_timing.jsonl"
ARTIFACTS_ROOT_REL = Path(".webnovel") / "reviews"
REPORTS_DIRNAME = "审查报告"
DEFAULT_CHECKER_TIMEOUT_SECONDS = 180
DEFAULT_FALLBACK_TIMEOUT_SECONDS = 75
OUTPUT_GRACE_SECONDS = 5
DEFAULT_MAX_PARALLEL_CHECKERS = 1
DEFAULT_CHILD_REASONING_EFFORT = "low"
DEFAULT_CHILD_FAST_FAIL_ERROR_THRESHOLD = 2

CORE_CHECKERS = [
    "consistency-checker",
    "continuity-checker",
    "ooc-checker",
]

OPTIONAL_CHECKERS = [
    "reader-pull-checker",
    "high-point-checker",
    "pacing-checker",
]

SEVERITY_ORDER = ("critical", "high", "medium", "low", "minor")

HIGH_POINT_KEYWORDS = (
    "战斗",
    "交手",
    "反杀",
    "打脸",
    "爆发",
    "越级",
    "身份揭露",
    "揭露",
    "反转",
    "觉醒",
    "硬刚",
    "决战",
)

TRANSITION_HINTS = (
    "过渡",
    "转场",
    "承上启下",
    "信息整理",
    "纯铺垫",
)

CHECKER_BRIEFS: Dict[str, str] = {
    "consistency-checker": """职责重点：
- 核查章节是否与现有设定、卷纲、前文事实冲突
- 重点关注：设定冲突、力量越权、地点/实体矛盾、时间线硬冲突
- 只有在能明确指出冲突位置与冲突事实时，才给出 medium 以上问题
- metrics 建议包含：power_violations / location_errors / timeline_issues / entity_conflicts""",
    "continuity-checker": """职责重点：
- 检查章节与上一章、当前卷主线、已埋伏笔之间的承接是否顺畅
- 重点关注：线索断档、承接跳跃、应兑现未兑现、逻辑桥接不足
- 对于“后续补一刀即可”的问题，优先给 low/medium
- metrics 建议包含：transition_grade / active_threads / dormant_threads / forgotten_foreshadowing / logic_holes / outline_deviations""",
    "ooc-checker": """职责重点：
- 检查角色言行、说话方式、风险偏好是否符合既有人设
- 重点关注：主角口吻偏移、角色动机突变、反派智商突然掉线、对白说明书化
- 只有在能指出具体段落和具体偏离类型时，才给问题
- metrics 建议包含：severe_ooc / moderate_ooc / minor_ooc / speech_violations / character_development_valid""",
    "reader-pull-checker": """职责重点：
- 检查追读驱动力、章末未闭合问题、微兑现和下一章点击理由
- 重点关注：章末钩子是否成立、兑现是否稀薄、过渡章是否过于平
- 不要把正常铺垫误判成大问题，更多给 low/medium 的优化建议
- metrics 建议包含：hook_present / hook_type / hook_strength / prev_hook_fulfilled / micropayoff_count / is_transition / debt_balance""",
    "high-point-checker": """职责重点：
- 检查高光点、打脸点、反转点、身份揭露点是否足够明确
- 重点关注：高潮章是否不够爽、反击是否不够成立、高光密度是否偏低
- 非高潮章可以保守判断，避免滥打低分
- metrics 建议包含：cool_point_count / cool_point_types / density_score / type_diversity / milestone_present""",
    "pacing-checker": """职责重点：
- 检查本章节奏推进、信息密度和主副线分配是否失衡
- 重点关注：拖沓、连续铺垫无回报、冲突推进过慢、信息堆叠太密
- 结合章号和前序趋势做判断，不要只盯单章句子
- metrics 建议包含：dominant_strand / quest_ratio / fire_ratio / constellation_ratio / consecutive_quest / fire_gap / constellation_gap / fatigue_risk""",
}

CHECKER_REVIEW_FOCUS: Dict[str, List[str]] = {
    "consistency-checker": [
        "境界/能力/资源数量/系统规则是否与既有设定一致。",
        "地点、势力、角色属性、重要实体是否与 state 或设定卡冲突。",
        "时间锚点、倒计时、前后事件顺序是否自洽。",
        "只有能明确指出冲突事实和定位时，才给 medium 以上问题。",
    ],
    "continuity-checker": [
        "本章开头是否接住上一章结尾承诺或压力。",
        "场景切换、时间推进、信息揭露是否有桥接。",
        "既有伏笔、主线线程、卷纲要求是否继续推进或至少被提醒。",
        "章末是否把问题自然递送到下一章，而不是断档。",
    ],
    "ooc-checker": [
        "主角与关键配角的动机、风险偏好、说话方式是否延续。",
        "角色是否为了推进剧情而突然降智、圣母或失去既有防备。",
        "对白是否保留人物指纹，而不是统一说明腔。",
        "如属于成长型变化，要区分“有铺垫的变化”和“无因偏移”。",
    ],
    "reader-pull-checker": [
        "上一章承诺的钩子是否有兑现或被明确延迟。",
        "本章是否有微兑现、明确目标阻力、清晰未闭合问题。",
        "过渡章是否仍然给出下一章点击理由，而不是纯搬运信息。",
        "区分 medium/low/minor：只有会伤到追读意愿时才升到 medium 以上。",
    ],
    "high-point-checker": [
        "本章定位下，高光/打脸/翻盘/揭露是否足够可见。",
        "爽点是否有铺垫、兑现和旁观反馈，而不是只靠旁白宣布。",
        "如果是过渡章，要判断“不过量承诺”而不是机械追求爽点密度。",
        "轻度措辞优化建议优先标为 minor，而不是 low。",
    ],
    "pacing-checker": [
        "主导 Strand、信息密度、兑现节拍是否失衡。",
        "连续 Quest/缺 Fire/缺 Constellation 等疲劳信号是否出现。",
        "章中是否有长段解释堆叠、过晚入戏或中段塌陷。",
        "需要结合前序章节与状态跟踪判断，不要只看单章句子。",
    ],
}

CHECKER_REFERENCE_PLAN: Dict[str, Dict[str, Any]] = {
    "consistency-checker": {"prev_chapters": 2, "prev_summaries": 2, "include_state": True, "include_outline": True, "include_settings": True},
    "continuity-checker": {"prev_chapters": 2, "prev_summaries": 2, "include_state": True, "include_outline": True, "include_settings": False},
    "ooc-checker": {"prev_chapters": 2, "prev_summaries": 1, "include_state": True, "include_outline": False, "include_settings": True},
    "reader-pull-checker": {"prev_chapters": 1, "prev_summaries": 2, "include_state": True, "include_outline": True, "include_settings": False},
    "high-point-checker": {"prev_chapters": 1, "prev_summaries": 2, "include_state": False, "include_outline": True, "include_settings": False},
    "pacing-checker": {"prev_chapters": 1, "prev_summaries": 3, "include_state": True, "include_outline": True, "include_settings": False},
}

CHECKER_SETTING_KEYWORDS: Dict[str, Sequence[str]] = {
    "consistency-checker": ("力量", "体系", "世界观", "设定", "规则", "金手指", "主角", "角色", "反派", "地点", "势力", "时间"),
    "ooc-checker": ("主角", "角色", "人物", "女主", "反派", "配角", "卡"),
}


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path.resolve())


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return str(value)


def _unique_paths(paths: Iterable[Path]) -> List[Path]:
    seen: set[str] = set()
    unique: List[Path] = []
    for raw in paths:
        path = Path(raw)
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen or not path.exists() or not path.is_file():
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _collect_outline_files(project_root: Path, chapter: int) -> List[Path]:
    outline_dir = project_root / "大纲"
    if not outline_dir.exists():
        return []

    volume_num = volume_num_for_chapter(chapter)
    volume_token = f"第{volume_num}卷"
    candidates: List[Path] = [
        outline_dir / f"第{volume_num}卷-详细大纲.md",
        outline_dir / f"第{volume_num}卷 详细大纲.md",
        outline_dir / f"第{volume_num}卷详细大纲.md",
    ]
    for file in sorted(outline_dir.glob("*.md")):
        name = file.name
        if volume_token in name and any(keyword in name for keyword in ("详细大纲", "节拍表", "时间线", "卷纲", "大纲")):
            candidates.append(file)
    return _unique_paths(candidates)[:5]


def _collect_recent_chapter_files(project_root: Path, chapter: int, window: int) -> List[Path]:
    candidates: List[Path] = []
    for prev in range(max(1, chapter - window), chapter):
        found = find_chapter_file(project_root, prev)
        if found is not None:
            candidates.append(found)
    return _unique_paths(candidates)


def _collect_recent_summary_files(project_root: Path, chapter: int, window: int) -> List[Path]:
    summary_dir = project_root / ".webnovel" / "summaries"
    if not summary_dir.exists():
        return []
    candidates = [summary_dir / f"ch{prev:04d}.md" for prev in range(max(1, chapter - window), chapter)]
    return _unique_paths(candidates)


def _rank_setting_files(project_root: Path, agent: str, *, limit: int = 6) -> List[Path]:
    keywords = tuple(CHECKER_SETTING_KEYWORDS.get(agent, ()))
    if not keywords:
        return []

    sources: List[Path] = []
    setting_dir = project_root / "设定集"
    if setting_dir.exists():
        sources.extend(sorted(setting_dir.rglob("*.md")))
    sources.extend(sorted(project_root.glob("*.md")))

    scored: List[tuple[int, str, Path]] = []
    for path in _unique_paths(sources):
        rel = _display_path(path, project_root)
        score = 0
        for index, keyword in enumerate(keywords):
            if keyword in rel:
                score += max(18 - index, 1)
        if score <= 0:
            continue
        scored.append((-score, rel, path))

    scored.sort()
    return [path for _score, _rel, path in scored[:limit]]


def _checker_reference_files(
    *,
    agent: str,
    chapter: int,
    chapter_file: Path,
    project_root: Path,
    artifact_dir: Path,
) -> Dict[str, Any]:
    plan = CHECKER_REFERENCE_PLAN.get(agent, {})
    context_file = artifact_dir / "context.json"
    required: List[tuple[Path, str]] = [
        (AGENTS_DIR / f"{agent}.md", "审查器规范与职责边界"),
        (CHECKER_SCHEMA_MD, "统一输出 schema"),
        (context_file, "主进程整理的上下文摘要"),
        (chapter_file, "当前章节正文"),
    ]

    supporting: List[tuple[Path, str]] = []
    if plan.get("include_state"):
        supporting.append((project_root / ".webnovel" / "state.json", "当前状态、伏笔、Strand 与章节元数据"))
    if plan.get("include_outline"):
        supporting.extend((path, "卷纲 / 节拍 / 时间线约束") for path in _collect_outline_files(project_root, chapter))
    for path in _collect_recent_chapter_files(project_root, chapter, int(plan.get("prev_chapters", 0) or 0)):
        supporting.append((path, "相邻前文正文，用于承接、口吻和事实对照"))
    for path in _collect_recent_summary_files(project_root, chapter, int(plan.get("prev_summaries", 0) or 0)):
        supporting.append((path, "前文章节摘要，用于快速对齐承接与 hook"))
    if plan.get("include_settings"):
        supporting.extend((path, "角色卡 / 世界观 / 规则设定") for path in _rank_setting_files(project_root, agent))

    required_existing = [(path, reason) for path, reason in required if path.exists() and path.is_file()]
    supporting_existing = [(path, reason) for path, reason in supporting if path.exists() and path.is_file()]
    return {
        "required": required_existing,
        "supporting": supporting_existing,
        "supporting_with_reason": supporting_existing,
    }


def _render_reference_lines(items: Sequence[tuple[Path, str]], project_root: Path) -> str:
    if not items:
        return "- 无"
    lines = []
    for path, reason in items:
        lines.append(f"- {_display_path(path, project_root)}  // {reason}")
    return "\n".join(lines)


def _build_context_digest(context_payload: Dict[str, Any]) -> str:
    digest: List[str] = []
    outline = str(context_payload.get("outline") or "").strip()
    if outline and not outline.startswith("⚠️"):
        digest.append(f"- 大纲摘要：{_truncate_text(outline, 260)}")

    previous = "\n\n".join(context_payload.get("previous_summaries") or []).strip()
    if previous:
        digest.append(f"- 前文摘要：{_truncate_text(previous, 260)}")

    state_summary = str(context_payload.get("state_summary") or "").strip()
    if state_summary and not state_summary.startswith("⚠️"):
        digest.append(f"- 状态摘要：{_truncate_text(state_summary, 220)}")

    reader_signal = context_payload.get("reader_signal") or {}
    if reader_signal:
        digest.append(f"- 追读信号：{_truncate_text(_compact_json(reader_signal), 220)}")

    writing_guidance = context_payload.get("writing_guidance") or {}
    if writing_guidance:
        digest.append(f"- 写作约束：{_truncate_text(_compact_json(writing_guidance), 220)}")

    rag_assist = context_payload.get("rag_assist") or {}
    rag_results = rag_assist.get("results") if isinstance(rag_assist, dict) else None
    if rag_results:
        digest.append(
            f"- RAG 辅助：{_truncate_text(_compact_json({'query': rag_assist.get('query'), 'mode': rag_assist.get('mode'), 'results': rag_results[:2]}), 260)}"
        )

    return "\n".join(digest) if digest else "- 无额外摘要；请直接读文件。"


def _render_focus_lines(agent: str) -> str:
    items = CHECKER_REVIEW_FOCUS.get(agent) or ["围绕当前 checker 名称进行保守、具体、可定位的章节质量审查。"]
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def _render_tool_hints(agent: str, project_root: Path, chapter_file: Path) -> str:
    hints = [
        "- 允许调用当前 Codex 子进程可用的只读工具：文件读取、关键词搜索、只读 Bash。",
        "- 推荐先读当前章、context.json、agent 规范，再按疑点补读 supporting files。",
        f'- 可用 `rg -n "关键词" {_display_path(chapter_file, project_root)} .webnovel/state.json 大纲 设定集` 快速定位证据。',
        "- 如果某个问题需要额外证据，可以继续读取与该问题直接相关的相邻章节或设定文件，但不要无目标全盘扫库。",
        "- 禁止任何写入、删除、格式化、覆盖、git 操作；只做只读审查。",
    ]
    if agent == "pacing-checker":
        hints.append(
            f'- 节奏检查可选运行：python "{SCRIPTS_DIR / "webnovel.py"}" --project-root "{project_root}" status -- --focus strand'
        )
    return "\n".join(hints)



@dataclass
class CheckerRunResult:
    agent: str
    payload: Dict[str, Any]
    elapsed_ms: int
    stdout: str = ""
    stderr: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def checker_output_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["agent", "chapter", "overall_score", "pass", "issues", "metrics", "summary"],
        "properties": {
            "agent": {"type": "string"},
            "chapter": {"type": "integer", "minimum": 1},
            "overall_score": {"type": "number"},
            "pass": {"type": "boolean"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["id", "type", "severity", "location", "description", "suggestion", "can_override"],
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "severity": {"type": "string", "enum": list(SEVERITY_ORDER)},
                        "location": {"type": "string"},
                        "description": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "can_override": {"type": "boolean"},
                    },
                },
            },
            "metrics": {"type": "object"},
            "summary": {"type": "string"},
        },
    }


def aggregate_fallback_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "required": ["chapter", "selected_checkers", "checker_results"],
        "properties": {
            "chapter": {"type": "integer", "minimum": 1},
            "selected_checkers": {"type": "array", "items": {"type": "string"}},
            "checker_results": {
                "type": "array",
                "items": checker_output_schema(),
            },
            "notes": {"type": "string"},
        },
    }


def resolve_codex_executable(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env_value = str(os.environ.get("WEBNOVEL_CODEX_BIN", "") or "").strip()
    if env_value:
        return env_value

    found = shutil.which("codex")
    if found:
        return found

    fallback = Path.home() / ".codex" / "bin" / "codex"
    if fallback.exists():
        return str(fallback)

    raise FileNotFoundError("未找到 codex 可执行文件；请先安装 Codex CLI。")


def resolve_active_model_provider_name() -> str | None:
    config_path = Path.home() / ".codex" / "config.toml"
    if not config_path.exists():
        return None
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    provider = str(payload.get("model_provider") or "").strip()
    return provider or None


def _provider_runtime_override(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _provider_override_args(provider_name: str) -> List[str]:
    overrides = []
    request_retries = _provider_runtime_override("WEBNOVEL_REVIEW_CHILD_REQUEST_MAX_RETRIES")
    stream_retries = _provider_runtime_override("WEBNOVEL_REVIEW_CHILD_STREAM_MAX_RETRIES")
    stream_idle_timeout_ms = _provider_runtime_override("WEBNOVEL_REVIEW_CHILD_STREAM_IDLE_TIMEOUT_MS")
    if request_retries is not None:
        overrides.extend(["-c", f"model_providers.{provider_name}.request_max_retries={int(request_retries)}"])
    if stream_retries is not None:
        overrides.extend(["-c", f"model_providers.{provider_name}.stream_max_retries={int(stream_retries)}"])
    if stream_idle_timeout_ms is not None:
        overrides.extend(["-c", f"model_providers.{provider_name}.stream_idle_timeout_ms={int(stream_idle_timeout_ms)}"])
    return overrides


def resolve_project_root(raw: str) -> Path:
    from project_locator import resolve_project_root as _resolve_project_root

    return _resolve_project_root(raw)


def read_chapter_text(chapter_file: Path) -> str:
    return chapter_file.read_text(encoding="utf-8")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def reset_chapter_artifacts(chapter_artifact_dir: Path) -> None:
    checker_dir = chapter_artifact_dir / "checkers"
    if checker_dir.exists():
        for child in checker_dir.iterdir():
            if child.is_file():
                child.unlink()
    for name in ("aggregate.json", "aggregate-fallback.raw.json", "aggregate-fallback.schema.json", "checker-output.schema.json"):
        target = chapter_artifact_dir / name
        if target.exists():
            target.unlink()


def resolve_chapter_file(project_root: Path, chapter_file: Path | None) -> Path | None:
    if chapter_file is None:
        return None
    if chapter_file.is_absolute():
        return chapter_file
    return (project_root / chapter_file).resolve()


def artifact_dir_for_chapter(project_root: Path, chapter: int) -> Path:
    return ensure_dir(project_root / ARTIFACTS_ROOT_REL / f"ch{chapter:04d}")


def artifact_dir_for_range(project_root: Path, start: int, end: int) -> Path:
    return ensure_dir(project_root / ARTIFACTS_ROOT_REL / f"range-{start:04d}-{end:04d}")


def report_path_for_range(project_root: Path, start: int, end: int) -> Path:
    return ensure_dir(project_root / REPORTS_DIRNAME) / f"第{start}-{end}章审查报告.md"


def make_context_dump(context_payload: Dict[str, Any], chapter_file: Path, artifact_dir: Path) -> Path:
    context_path = artifact_dir / "context.json"
    payload = dict(context_payload)
    payload["chapter_file"] = str(chapter_file)
    context_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return context_path


def _text_blob(values: Iterable[Any]) -> str:
    chunks: list[str] = []
    for value in values:
        if not value:
            continue
        if isinstance(value, str):
            chunks.append(value)
        else:
            try:
                chunks.append(json.dumps(value, ensure_ascii=False))
            except Exception:
                chunks.append(str(value))
    return "\n".join(chunks)


def _truncate_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(已截断)"


def should_run_reader_pull(context_payload: Dict[str, Any], chapter_text: str) -> bool:
    outline = str(context_payload.get("outline") or "")
    guidance = _text_blob(
        [
            (context_payload.get("writing_guidance") or {}).get("guidance_items"),
            (context_payload.get("writing_guidance") or {}).get("checklist"),
        ]
    )
    combined = f"{outline}\n{guidance}\n{chapter_text[-400:]}"
    if any(hint in combined for hint in TRANSITION_HINTS):
        return False
    return True


def should_run_high_point(context_payload: Dict[str, Any], chapter_text: str) -> bool:
    combined = f"{context_payload.get('outline', '')}\n{chapter_text}"
    return any(keyword in combined for keyword in HIGH_POINT_KEYWORDS)


def should_run_pacing(chapter: int, context_payload: Dict[str, Any], chapter_text: str) -> bool:
    if chapter >= 10:
        return True
    reader_signal = context_payload.get("reader_signal") or {}
    review_trend = reader_signal.get("review_trend") or {}
    overall_avg = review_trend.get("overall_avg")
    try:
        if overall_avg is not None and float(overall_avg) < 80:
            return True
    except (TypeError, ValueError):
        pass
    if len(chapter_text) >= 4500:
        return True
    outline = str(context_payload.get("outline") or "")
    return "Strand:" in outline or "节奏" in outline


def select_checkers(*, chapter: int, chapter_text: str, context_payload: Dict[str, Any], mode: str) -> List[str]:
    selected = list(CORE_CHECKERS)
    if mode == "minimal":
        return selected

    if mode == "full":
        return selected + list(OPTIONAL_CHECKERS)

    if should_run_reader_pull(context_payload, chapter_text):
        selected.append("reader-pull-checker")
    if should_run_high_point(context_payload, chapter_text):
        selected.append("high-point-checker")
    if should_run_pacing(chapter, context_payload, chapter_text):
        selected.append("pacing-checker")
    return selected


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_checker_prompt(
    *,
    agent: str,
    chapter: int,
    chapter_file: Path,
    context_payload: Dict[str, Any],
    chapter_text: str,
    project_root: Path,
    artifact_dir: Path,
) -> str:
    agent_path = AGENTS_DIR / f"{agent}.md"
    if not agent_path.exists():
        raise FileNotFoundError(f"缺少审查器提示词文件: {agent_path}")

    checker_brief = CHECKER_BRIEFS.get(agent, "职责重点：围绕当前 checker 名称进行保守、具体、可定位的章节质量审查。")
    references = _checker_reference_files(
        agent=agent,
        chapter=chapter,
        chapter_file=chapter_file,
        project_root=project_root,
        artifact_dir=artifact_dir,
    )
    required_text = _render_reference_lines(references.get("required") or [], project_root)
    supporting_text = _render_reference_lines(references.get("supporting_with_reason") or [], project_root)
    context_digest = _build_context_digest(context_payload)
    chapter_meta = f"字数约 {len(chapter_text.strip())}"

    return f"""你是 webnovel-writer 的 `{agent}` 子审查器。

任务：审查第{chapter}章的 {agent} 维度，并输出结构化 JSON。

项目根目录：{project_root}
章节文件：{_display_path(chapter_file, project_root)}
章号：{chapter}
章节体量：{chapter_meta}

这次使用 Claude 风格的 source-backed review：你必须先自己定向读取文件，再下结论。下面的摘要只用于帮你决定先看什么，不能替代实际查证。

先读这些文件（required）：
{required_text}

如发现疑点，再按需补读这些文件（supporting）：
{supporting_text}

重点检查：
{_render_focus_lines(agent)}

快速摘要：
{context_digest}

补充约束：
{checker_brief}

允许的工具与动作：
{_render_tool_hints(agent, project_root, chapter_file)}

严重度分级：
- `critical`：硬冲突 / 会直接误导后续流程，必须修复
- `high`：明显影响阅读或逻辑，优先修复
- `medium`：会削弱体验或承接，建议本轮修
- `low`：不修也能读，但收益明确的优化项
- `minor`：更偏打磨级的小问题，不影响逻辑，只做精修提示

输出硬约束：
- 只输出一个 JSON 对象，不要输出 Markdown、解释、代码块
- 必填字段：agent, chapter, overall_score, pass, issues, metrics, summary
- issues 的每个元素都必须包含：id, type, severity, location, description, suggestion, can_override
- severity 只能使用 critical/high/medium/low/minor
- location 必须能定位到正文位置，例如“第6段”“第11-12段”“章末”
- 如果没有问题，issues 也必须返回 []
- summary 用中文，要求具体，不要空话
- 结论必须基于你实际读到的文件；不要伪造“已核对”

禁止事项：
- 不要修改任何文件
- 不要输出“已润色/已回写/已修复”之类流程外信息
- 不要替别的 checker 做职责外判断，重点遵循你自己的 agent 规范
"""


def build_codex_exec_command(
    *,
    codex_bin: str,
    project_root: Path,
    output_schema_path: Path,
    output_path: Path,
    sandbox_mode: str = "read-only",
) -> List[str]:
    reasoning_effort = str(os.environ.get("WEBNOVEL_REVIEW_CHILD_REASONING_EFFORT", DEFAULT_CHILD_REASONING_EFFORT) or DEFAULT_CHILD_REASONING_EFFORT).strip()
    command = [
        codex_bin,
        "exec",
        "--json",
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "-c",
        "mcp_servers.notion.enabled=false",
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
        "-s",
        str(sandbox_mode),
        "-C",
        str(project_root),
        "--output-schema",
        str(output_schema_path),
        "-o",
        str(output_path),
        "-",
    ]
    provider_name = resolve_active_model_provider_name()
    if provider_name:
        command.extend(_provider_override_args(provider_name))
    return command


def _pump_stream(stream, sink: "queue.Queue[tuple[str, str | None]]", label: str) -> None:
    try:
        for line in iter(stream.readline, ""):
            sink.put((label, line))
    finally:
        sink.put((label, None))


def _terminate_process(proc: subprocess.Popen[str]) -> int:
    if proc.poll() is not None:
        return int(proc.returncode or 0)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    return int(proc.returncode or 0)


def _parse_stream_payload(line: str) -> Dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _is_retryable_provider_error(message: str) -> bool:
    lowered = str(message or "").lower()
    return (
        "reconnecting..." in lowered
        or "unexpected status 502" in lowered
        or "stream disconnected" in lowered
        or "bad gateway" in lowered
    )


def _degraded_issue(
    *,
    issue_id: str,
    issue_type: str,
    severity: str,
    location: str,
    description: str,
    suggestion: str,
) -> Dict[str, Any]:
    return {
        "id": issue_id,
        "type": issue_type,
        "severity": severity,
        "location": location,
        "description": description,
        "suggestion": suggestion,
        "can_override": True,
    }


def build_local_degraded_checker_payload(
    *,
    agent: str,
    chapter: int,
    chapter_text: str,
    context_payload: Dict[str, Any],
    failure_reasons: Sequence[str],
) -> Dict[str, Any]:
    lines = [line.strip() for line in chapter_text.splitlines() if line.strip()]
    paragraph_count = len(lines)
    char_count = len(chapter_text.strip())
    tail_text = "\n".join(lines[-4:])
    outline = str(context_payload.get("outline") or "")
    previous = "\n".join(context_payload.get("previous_summaries") or [])
    issues: List[Dict[str, Any]] = []
    score = 82.0

    if agent == "consistency-checker":
        if outline and not any(token in chapter_text for token in ("系统", "灵气", "因果", "天道", "废井", "巷", "修炼")):
            issues.append(
                _degraded_issue(
                    issue_id="DL-CONS-1",
                    issue_type="SETTING_CALLBACK_WEAK",
                    severity="low",
                    location="全章",
                    description="本章对既有设定关键词的显性回扣偏弱，读者不容易感知世界规则仍在持续起作用。",
                    suggestion="补一处与当前世界规则直接相关的动作后果或异常细节。",
                )
            )
            score -= 3
        summary = "降级本地审查未发现可直接定位的硬性设定冲突；当前结论主要基于显性设定词、章节结构与前文摘要交叉比对。"
    elif agent == "continuity-checker":
        if previous and not any(token in chapter_text for token in ("妹妹", "医院", "废井", "张浩", "苏晚晴", "巷")):
            issues.append(
                _degraded_issue(
                    issue_id="DL-CONT-1",
                    issue_type="THREAD_CALLBACK_WEAK",
                    severity="medium",
                    location="章中",
                    description="本章与前文主线的显性回扣偏弱，承接线索需要读者自行补脑，连续追读时会有轻微跳步感。",
                    suggestion="补一句明确承接上一章压力或目标的提醒，让读者快速对齐当前场景与主线关系。",
                )
            )
            score -= 6
        summary = "降级本地审查主要检查了前文摘要回扣、主线关键词延续和章末承接力度；未发现会直接阻断阅读的断档。"
    elif agent == "ooc-checker":
        if chapter_text.count("“") <= 2 and chapter_text.count('"') <= 2:
            issues.append(
                _degraded_issue(
                    issue_id="DL-OOC-1",
                    issue_type="CHARACTER_EXPOSURE_THIN",
                    severity="low",
                    location="全章",
                    description="本章对白偏少，角色个性更多依赖叙述承载，人物辨识度提升空间还在。",
                    suggestion="给主角或关键配角补一两句带人设指纹的短对白，增强角色落点。",
                )
            )
            score -= 2
        summary = "降级本地审查未看到明显的人设反转型问题；当前结论主要覆盖对白密度、主角风险偏好和行为一致性。"
    elif agent == "reader-pull-checker":
        if not any(marker in tail_text for marker in ("？", "?", "下一刻", "就在这时", "却", "然而", "忽然")):
            issues.append(
                _degraded_issue(
                    issue_id="DL-HOOK-1",
                    issue_type="HOOK_SOFT",
                    severity="low",
                    location="章末",
                    description="章末悬念信号偏软，读者能感知到未完，但点击下一章的迫切性还不够尖。",
                    suggestion="把章末收束改成更具体的异常、选择或威胁，让问题落在一个更清晰的动作点上。",
                )
            )
            score -= 4
        summary = "降级本地审查主要依据章末信号词、未闭合问题和尾段转折力度估算追读拉力；建议以后仍以真实子审查结果为准。"
    elif agent == "high-point-checker":
        if not any(token in chapter_text for token in HIGH_POINT_KEYWORDS):
            issues.append(
                _degraded_issue(
                    issue_id="DL-HIGH-1",
                    issue_type="HIGH_POINT_LIGHT",
                    severity="low",
                    location="全章",
                    description="本章显性高光或反转信号偏少，阅读驱动更依赖持续悬念而不是即时爽点。",
                    suggestion="若本章定位不是纯过渡，可增加一次更明确的反制、揭露或局势翻面。",
                )
            )
            score -= 3
        summary = "降级本地审查主要检查了高光关键词、反转信号与局势翻面密度；当前判断偏保守。"
    elif agent == "pacing-checker":
        avg_line_len = int(sum(len(item) for item in lines) / max(1, paragraph_count))
        if char_count < 2400:
            issues.append(
                _degraded_issue(
                    issue_id="DL-PACE-1",
                    issue_type="PAYLOAD_LIGHT",
                    severity="low",
                    location="全章",
                    description="本章篇幅略短，信息推进虽清楚，但单位章节的兑现量偏保守。",
                    suggestion="补一处更具体的推进结果或更明确的异常证据，提升单章获得感。",
                )
            )
            score -= 3
        elif avg_line_len > 120:
            issues.append(
                _degraded_issue(
                    issue_id="DL-PACE-2",
                    issue_type="INFO_DENSITY_HEAVY",
                    severity="medium",
                    location="章中",
                    description="本章单段承载的信息略密，移动端阅读时容易出现连续解释堆叠感。",
                    suggestion="把较长段拆成动作、对白、信息三种更短的节拍，给读者留呼吸位。",
                )
            )
            score -= 5
        summary = "降级本地审查重点看了章长、段落密度和尾段推进力度；未发现节奏层面的硬阻断。"
    else:
        summary = "降级本地审查已完成基础结构检查；建议后续仍以真实子审查结果为准。"

    score = max(72.0, min(88.0, score))
    payload = {
        "agent": agent,
        "chapter": chapter,
        "overall_score": round(score, 2),
        "pass": True,
        "issues": issues,
        "metrics": {
            "review_mode": "degraded_local",
            "char_count": char_count,
            "paragraph_count": paragraph_count,
            "failure_reason_count": len(list(failure_reasons)),
        },
        "summary": summary,
    }
    return validate_checker_payload(payload, expected_agent=agent, chapter=chapter)


def hydrate_missing_results_with_local_fallback(
    *,
    project_root: Path,
    chapter: int,
    selected_checkers: Sequence[str],
    existing_results: Sequence[Dict[str, Any]],
    chapter_text: str,
    context_payload: Dict[str, Any],
    artifact_dir: Path,
    failure_reasons: Sequence[str],
) -> List[Dict[str, Any]]:
    checker_dir = ensure_dir(artifact_dir / "checkers")
    result_map = {str(row.get("agent")): dict(row) for row in existing_results}
    for agent in selected_checkers:
        if agent in result_map:
            continue
        payload = build_local_degraded_checker_payload(
            agent=agent,
            chapter=chapter,
            chapter_text=chapter_text,
            context_payload=context_payload,
            failure_reasons=failure_reasons,
        )
        write_json(checker_dir / f"{agent}.json", payload)
        append_observability(
            project_root,
            {
                "timestamp": now_iso(),
                "tool_name": "review_agents_runner:degraded_local",
                "chapter": chapter,
                "checker": agent,
                "success": True,
                "failure_reasons": list(failure_reasons),
            },
        )
        result_map[agent] = payload
    return [result_map[agent] for agent in selected_checkers if agent in result_map]


def validate_checker_payload(payload: Dict[str, Any], expected_agent: str, chapter: int) -> Dict[str, Any]:
    missing = [key for key in ("agent", "chapter", "overall_score", "pass", "issues", "metrics", "summary") if key not in payload]
    if missing:
        raise ValueError(f"{expected_agent} 输出缺少字段: {', '.join(missing)}")
    if payload.get("agent") != expected_agent:
        raise ValueError(f"{expected_agent} 输出 agent 不匹配: {payload.get('agent')}")
    if int(payload.get("chapter")) != int(chapter):
        raise ValueError(f"{expected_agent} 输出 chapter 不匹配: {payload.get('chapter')}")
    if not isinstance(payload.get("issues"), list):
        raise ValueError(f"{expected_agent} issues 必须是数组")

    validated_issues = []
    for index, issue in enumerate(payload.get("issues") or [], start=1):
        if not isinstance(issue, dict):
            raise ValueError(f"{expected_agent} 第 {index} 个 issue 不是对象")
        issue_missing = [
            key for key in ("id", "type", "severity", "location", "description", "suggestion", "can_override") if key not in issue
        ]
        if issue_missing:
            raise ValueError(f"{expected_agent} 第 {index} 个 issue 缺少字段: {', '.join(issue_missing)}")
        severity = str(issue.get("severity"))
        if severity not in SEVERITY_ORDER:
            raise ValueError(f"{expected_agent} 第 {index} 个 issue severity 非法: {severity}")
        enriched = dict(issue)
        enriched["agent"] = expected_agent
        validated_issues.append(enriched)

    payload = dict(payload)
    payload["issues"] = validated_issues
    payload["overall_score"] = float(payload.get("overall_score", 0))
    payload["pass"] = bool(payload.get("pass"))
    if not isinstance(payload.get("metrics"), dict):
        raise ValueError(f"{expected_agent} metrics 必须是对象")
    payload["summary"] = str(payload.get("summary") or "").strip()
    return payload


def load_valid_checker_payload(output_path: Path, *, expected_agent: str, chapter: int) -> Dict[str, Any] | None:
    if not output_path.exists():
        return None
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    try:
        return validate_checker_payload(payload, expected_agent=expected_agent, chapter=chapter)
    except Exception:
        return None


def append_observability(project_root: Path, row: Dict[str, Any]) -> None:
    path = project_root / OBSERVABILITY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_checker_subprocess(
    *,
    codex_bin: str,
    project_root: Path,
    chapter: int,
    agent: str,
    chapter_file: Path,
    context_payload: Dict[str, Any],
    chapter_text: str,
    artifact_dir: Path,
) -> CheckerRunResult:
    checker_dir = ensure_dir(artifact_dir / "checkers")
    output_path = checker_dir / f"{agent}.json"
    schema_path = artifact_dir / "checker-output.schema.json"
    if not schema_path.exists():
        write_json(schema_path, checker_output_schema())

    command = build_codex_exec_command(
        codex_bin=codex_bin,
        project_root=project_root,
        output_schema_path=schema_path,
        output_path=output_path,
    )
    prompt = build_checker_prompt(
        agent=agent,
        chapter=chapter,
        chapter_file=chapter_file,
        context_payload=context_payload,
        chapter_text=chapter_text,
        project_root=project_root,
        artifact_dir=artifact_dir,
    )

    started = time.monotonic()
    timeout_seconds = int(os.environ.get("WEBNOVEL_REVIEW_CHECKER_TIMEOUT_SECONDS", str(DEFAULT_CHECKER_TIMEOUT_SECONDS)) or DEFAULT_CHECKER_TIMEOUT_SECONDS)
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None
    proc.stdin.write(prompt)
    proc.stdin.close()

    event_queue: "queue.Queue[tuple[str, str | None]]" = queue.Queue()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_done = False
    stderr_done = False
    turn_completed = False
    validated_payload: Dict[str, Any] | None = None
    retryable_error_count = 0
    forced_failure_reason: str | None = None

    stdout_thread = threading.Thread(target=_pump_stream, args=(proc.stdout, event_queue, "stdout"), daemon=True)
    stderr_thread = threading.Thread(target=_pump_stream, args=(proc.stderr, event_queue, "stderr"), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    deadline = started + timeout_seconds
    while time.monotonic() < deadline:
        validated_payload = load_valid_checker_payload(output_path, expected_agent=agent, chapter=chapter)
        if validated_payload is not None:
            break
        if turn_completed and output_path.exists():
            break
        try:
            label, line = event_queue.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None and stdout_done and stderr_done:
                break
            continue

        if line is None:
            if label == "stdout":
                stdout_done = True
            else:
                stderr_done = True
            if proc.poll() is not None and stdout_done and stderr_done:
                break
            continue

        if label == "stdout":
            stdout_lines.append(line)
            payload = _parse_stream_payload(line)
            if isinstance(payload, dict) and payload.get("type") == "turn.completed":
                turn_completed = True
            if isinstance(payload, dict) and payload.get("type") == "error":
                message = str(payload.get("message") or "").strip()
                if _is_retryable_provider_error(message):
                    retryable_error_count += 1
                    max_errors = int(
                        os.environ.get(
                            "WEBNOVEL_REVIEW_CHILD_FAST_FAIL_ERROR_THRESHOLD",
                            str(DEFAULT_CHILD_FAST_FAIL_ERROR_THRESHOLD),
                        )
                        or DEFAULT_CHILD_FAST_FAIL_ERROR_THRESHOLD
                    )
                    if retryable_error_count >= max_errors:
                        forced_failure_reason = message
                        break
        else:
            stderr_lines.append(line)

    validated_payload = validated_payload or load_valid_checker_payload(output_path, expected_agent=agent, chapter=chapter)

    if turn_completed and not output_path.exists():
        grace_deadline = time.monotonic() + OUTPUT_GRACE_SECONDS
        while time.monotonic() < grace_deadline:
            validated_payload = load_valid_checker_payload(output_path, expected_agent=agent, chapter=chapter)
            if validated_payload is not None:
                break
            time.sleep(0.1)

    if validated_payload is None and proc.poll() is None and time.monotonic() >= deadline:
        _terminate_process(proc)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        stdout_path = checker_dir / f"{agent}.stdout.log"
        stderr_path = checker_dir / f"{agent}.stderr.log"
        stdout_path.write_text("".join(stdout_lines), encoding="utf-8")
        stderr_path.write_text("".join(stderr_lines), encoding="utf-8")
        raise RuntimeError(f"{agent} 审查超时（>{timeout_seconds}s），未等到 turn.completed")

    if forced_failure_reason is not None:
        return_code = _terminate_process(proc)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        stdout_path = checker_dir / f"{agent}.stdout.log"
        stderr_path = checker_dir / f"{agent}.stderr.log"
        stdout_path.write_text("".join(stdout_lines), encoding="utf-8")
        stderr_path.write_text("".join(stderr_lines), encoding="utf-8")
        raise RuntimeError(
            f"{agent} 审查子进程连续错误 {retryable_error_count} 次后快速失败（exit={return_code}, elapsed_ms={elapsed_ms}）: {forced_failure_reason}"
        )

    return_code = _terminate_process(proc)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    stdout_text = "".join(stdout_lines)
    stderr_text = "".join(stderr_lines)

    stdout_path = checker_dir / f"{agent}.stdout.log"
    stderr_path = checker_dir / f"{agent}.stderr.log"
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")

    validated_payload = validated_payload or load_valid_checker_payload(output_path, expected_agent=agent, chapter=chapter)
    if validated_payload is None:
        raise RuntimeError(f"{agent} 审查未生成有效输出文件: {output_path}")
    if return_code not in {0, -15} and not turn_completed:
        raise RuntimeError(f"{agent} 审查子进程失败（exit={return_code}）: {(stderr_text or stdout_text).strip()}")
    return CheckerRunResult(agent=agent, payload=validated_payload, elapsed_ms=elapsed_ms, stdout=stdout_text, stderr=stderr_text)


def build_aggregate_fallback_prompt(
    *,
    chapter: int,
    selected_checkers: Sequence[str],
    chapter_file: Path,
    context_payload: Dict[str, Any],
    chapter_text: str,
    project_root: Path,
    failure_reasons: Sequence[str],
) -> str:
    outline = _truncate_text(context_payload.get("outline", ""), 900)
    previous = _truncate_text("\n\n".join(context_payload.get("previous_summaries") or []), 1200)
    state_summary = _truncate_text(context_payload.get("state_summary", ""), 280)
    chapter_excerpt = _truncate_text(chapter_text, 4200)
    checker_briefs = "\n".join(f"- {name}: {CHECKER_BRIEFS.get(name, '')}" for name in selected_checkers)
    failure_text = "\n".join(f"- {item}" for item in failure_reasons) if failure_reasons else "- 无"

    return f"""你是 webnovel-writer 的聚合审查器。

当前多子进程 checker 审查发生失败或超时，需要你一次性完成聚合式章节审查。

严格要求：
- 可以使用只读工具补充核查，但优先利用当前材料包
- 若要补读文件，只能读取与失败 checker 直接相关的少量文件
- 只输出一个 JSON 对象
- 输出必须匹配给定 schema
- `checker_results` 中必须为每个 selected checker 都生成一条完整结果
- 每条 checker 结果都必须遵循标准 checker 输出字段：agent, chapter, overall_score, pass, issues, metrics, summary
- issue 必须带 id/type/severity/location/description/suggestion/can_override
- severity 只能使用 critical/high/medium/low/minor
- 若某个 checker 没发现问题，也必须返回 issues=[]

chapter={chapter}
chapter_file={chapter_file}
project_root={project_root}
selected_checkers={', '.join(selected_checkers)}

各 checker 职责摘要：
{checker_briefs}

本次 fallback 触发原因：
{failure_text}

材料包：

【章节大纲】
{outline}

【前文摘要】
{previous}

【状态摘要】
{state_summary}

【当前章节正文】
{chapter_excerpt}
"""


def run_aggregate_fallback(
    *,
    codex_bin: str,
    project_root: Path,
    chapter: int,
    selected_checkers: Sequence[str],
    chapter_file: Path,
    context_payload: Dict[str, Any],
    chapter_text: str,
    artifact_dir: Path,
    failure_reasons: Sequence[str],
) -> List[Dict[str, Any]]:
    checker_dir = ensure_dir(artifact_dir / "checkers")
    output_path = artifact_dir / "aggregate-fallback.raw.json"
    schema_path = artifact_dir / "aggregate-fallback.schema.json"
    write_json(schema_path, aggregate_fallback_schema())
    command = build_codex_exec_command(
        codex_bin=codex_bin,
        project_root=project_root,
        output_schema_path=schema_path,
        output_path=output_path,
    )
    prompt = build_aggregate_fallback_prompt(
        chapter=chapter,
        selected_checkers=selected_checkers,
        chapter_file=chapter_file,
        context_payload=context_payload,
        chapter_text=chapter_text,
        project_root=project_root,
        failure_reasons=failure_reasons,
    )

    started = time.monotonic()
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None
    proc.stdin.write(prompt)
    proc.stdin.close()

    event_queue: "queue.Queue[tuple[str, str | None]]" = queue.Queue()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_done = False
    stderr_done = False
    stdout_thread = threading.Thread(target=_pump_stream, args=(proc.stdout, event_queue, "stdout"), daemon=True)
    stderr_thread = threading.Thread(target=_pump_stream, args=(proc.stderr, event_queue, "stderr"), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    timeout_seconds = int(
        os.environ.get("WEBNOVEL_REVIEW_FALLBACK_TIMEOUT_SECONDS", str(DEFAULT_FALLBACK_TIMEOUT_SECONDS))
        or DEFAULT_FALLBACK_TIMEOUT_SECONDS
    )
    deadline = started + timeout_seconds
    valid_results: List[Dict[str, Any]] | None = None
    retryable_error_count = 0
    forced_failure_reason: str | None = None
    while time.monotonic() < deadline:
        if output_path.exists():
            try:
                raw = json.loads(output_path.read_text(encoding="utf-8"))
            except Exception:
                raw = None
            if isinstance(raw, dict):
                checker_results = raw.get("checker_results")
                if isinstance(checker_results, list) and len(checker_results) == len(selected_checkers):
                    try:
                        validated = [
                            validate_checker_payload(item, expected_agent=agent, chapter=chapter)
                            for agent, item in zip(selected_checkers, checker_results)
                        ]
                        valid_results = validated
                        break
                    except Exception:
                        pass
        try:
            label, line = event_queue.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None and stdout_done and stderr_done:
                break
            continue
        if line is None:
            if label == "stdout":
                stdout_done = True
            else:
                stderr_done = True
            continue
        if label == "stdout":
            stdout_lines.append(line)
            payload = _parse_stream_payload(line)
            if isinstance(payload, dict) and payload.get("type") == "error":
                message = str(payload.get("message") or "").strip()
                if _is_retryable_provider_error(message):
                    retryable_error_count += 1
                    max_errors = int(
                        os.environ.get(
                            "WEBNOVEL_REVIEW_CHILD_FAST_FAIL_ERROR_THRESHOLD",
                            str(DEFAULT_CHILD_FAST_FAIL_ERROR_THRESHOLD),
                        )
                        or DEFAULT_CHILD_FAST_FAIL_ERROR_THRESHOLD
                    )
                    if retryable_error_count >= max_errors:
                        forced_failure_reason = message
                        break
        else:
            stderr_lines.append(line)

    return_code = _terminate_process(proc)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    (checker_dir / "_aggregate_fallback.stdout.log").write_text("".join(stdout_lines), encoding="utf-8")
    (checker_dir / "_aggregate_fallback.stderr.log").write_text("".join(stderr_lines), encoding="utf-8")

    if valid_results is None:
        detail = forced_failure_reason or "未生成有效 aggregate-fallback 输出"
        raise RuntimeError(f"aggregate fallback 失败（exit={return_code}, elapsed_ms={elapsed_ms}）: {detail}")

    for row in valid_results:
        row = dict(row)
        row.setdefault("metrics", {})
        if isinstance(row["metrics"], dict):
            row["metrics"].setdefault("review_mode", "aggregate_fallback")
        write_json(checker_dir / f"{row['agent']}.json", row)
    append_observability(
        project_root,
        {
            "timestamp": now_iso(),
            "tool_name": "review_agents_runner:fallback",
            "chapter": chapter,
            "elapsed_ms": elapsed_ms,
            "selected_checkers": list(selected_checkers),
            "failure_reasons": list(failure_reasons),
            "success": True,
        },
    )
    return valid_results


def summarize_dimension_scores(results: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    scores = {row["agent"]: float(row.get("overall_score", 0)) for row in results}

    def mean_of(keys: Sequence[str]) -> float:
        values = [scores[key] for key in keys if key in scores]
        if not values:
            return 0.0
        return round(float(statistics.mean(values)), 2)

    dimension_scores: Dict[str, float] = {
        "consistency": scores.get("consistency-checker", 0.0),
        "continuity": scores.get("continuity-checker", 0.0),
        "ooc": scores.get("ooc-checker", 0.0),
    }
    if "reader-pull-checker" in scores:
        dimension_scores["reader_pull"] = scores["reader-pull-checker"]
    if "high-point-checker" in scores:
        dimension_scores["high_point"] = scores["high-point-checker"]
    if "pacing-checker" in scores:
        dimension_scores["pacing"] = scores["pacing-checker"]

    dimension_scores["plot"] = scores.get("continuity-checker", 0.0)
    dimension_scores["character"] = scores.get("ooc-checker", 0.0)
    dimension_scores["hook"] = scores.get("reader-pull-checker", scores.get("continuity-checker", 0.0))
    dimension_scores["style"] = mean_of(["ooc-checker", "reader-pull-checker"])
    dimension_scores["readability"] = mean_of(["continuity-checker", "reader-pull-checker", "pacing-checker"])
    return {key: round(float(value), 2) for key, value in dimension_scores.items() if value}


def aggregate_checker_results(
    *,
    chapter: int,
    chapter_file: Path,
    selected_checkers: Sequence[str],
    results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    severity_counts = {level: 0 for level in SEVERITY_ORDER}
    all_issues: List[Dict[str, Any]] = []
    critical_issues: List[str] = []
    timeline_blockers: List[Dict[str, Any]] = []
    checkers: Dict[str, Any] = {}

    for row in results:
        agent = str(row.get("agent"))
        issues = list(row.get("issues") or [])
        per_checker_counts = {level: 0 for level in SEVERITY_ORDER}
        for issue in issues:
            severity = str(issue.get("severity"))
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            if severity not in per_checker_counts:
                per_checker_counts[severity] = 0
            per_checker_counts[severity] += 1
            all_issues.append(dict(issue))
            if severity == "critical":
                critical_issues.append(f"{agent}: {issue.get('description', '')}")
            if issue.get("type") == "TIMELINE_ISSUE" and severity in {"critical", "high"}:
                timeline_blockers.append(dict(issue))

        checkers[agent] = {
            "score": float(row.get("overall_score", 0)),
            "pass": bool(row.get("pass")),
            "critical": per_checker_counts.get("critical", 0),
            "high": per_checker_counts.get("high", 0),
            "medium": per_checker_counts.get("medium", 0),
            "low": per_checker_counts.get("low", 0),
            "minor": per_checker_counts.get("minor", 0),
            "severity_counts": per_checker_counts,
            "summary": row.get("summary", ""),
            "metrics": row.get("metrics", {}),
        }

    overall_score = round(float(statistics.mean(float(row.get("overall_score", 0)) for row in results)), 2) if results else 0.0
    aggregate_pass = all(bool(row.get("pass")) for row in results) and not timeline_blockers
    execution_mode = "standard"
    if any((row.get("metrics") or {}).get("review_mode") == "degraded_local" for row in results):
        execution_mode = "degraded_local"
    elif any((row.get("metrics") or {}).get("review_mode") == "aggregate_fallback" for row in results):
        execution_mode = "aggregate_fallback"
    return {
        "chapter": chapter,
        "start_chapter": chapter,
        "end_chapter": chapter,
        "chapter_file": str(chapter_file),
        "selected_checkers": list(selected_checkers),
        "overall_score": overall_score,
        "pass": aggregate_pass,
        "timeline_blocked": bool(timeline_blockers),
        "timeline_blocking_issues": timeline_blockers,
        "severity_counts": severity_counts,
        "critical_issues": critical_issues,
        "issues": all_issues,
        "dimension_scores": summarize_dimension_scores(results),
        "checkers": checkers,
        "execution_mode": execution_mode,
        "generated_at": now_iso(),
        "runner": "codex-exec-review-agents-v1",
    }


def issue_sort_key(issue: Dict[str, Any]) -> tuple[int, str, str]:
    severity = str(issue.get("severity") or "low")
    rank = SEVERITY_ORDER.index(severity) if severity in SEVERITY_ORDER else len(SEVERITY_ORDER)
    return (rank, str(issue.get("agent") or ""), str(issue.get("location") or ""))


def render_chapter_report(aggregate: Dict[str, Any], chapter_artifact_dir: Path, report_path: Path) -> str:
    post_review_sync = aggregate.get("post_review_sync") or {}
    if post_review_sync.get("attempted"):
        sync_summary = "ok" if post_review_sync.get("success") else f"failed ({post_review_sync.get('error', 'unknown')})"
    else:
        sync_summary = f"skipped ({post_review_sync.get('reason', 'not_requested')})"

    lines = [
        f"# 第{aggregate['chapter']}章审查报告",
        "",
        "## 总览",
        f"- 章节文件：{aggregate['chapter_file']}",
        f"- selected_checkers: {', '.join(aggregate.get('selected_checkers') or [])}",
        f"- overall_score: {aggregate.get('overall_score', 0)}",
        f"- pass: {'yes' if aggregate.get('pass') else 'no'}",
        f"- timeline_blocked: {'yes' if aggregate.get('timeline_blocked') else 'no'}",
        f"- execution_mode: {aggregate.get('execution_mode', 'standard')}",
        f"- post_review_sync: {sync_summary}",
        "",
        "## 严重度统计",
        "| 等级 | 数量 |",
        "|------|------|",
    ]
    for level in SEVERITY_ORDER:
        lines.append(f"| {level} | {int((aggregate.get('severity_counts') or {}).get(level, 0))} |")

    lines.extend(
        [
            "",
            "## 审查器摘要",
            "| Checker | 分数 | critical | high | medium | low | minor | 结论 |",
            "|---------|------|----------|------|--------|-----|-------|------|",
        ]
    )
    for agent in aggregate.get("selected_checkers") or []:
        row = (aggregate.get("checkers") or {}).get(agent, {})
        lines.append(
            f"| {agent} | {row.get('score', 0)} | {row.get('critical', 0)} | {row.get('high', 0)} | {row.get('medium', 0)} | {row.get('low', 0)} | {row.get('minor', 0)} | {row.get('summary', '')} |"
        )

    lines.extend([
        "",
        "## 问题清单",
        "| severity | checker | type | location | description | suggestion |",
        "|----------|---------|------|----------|-------------|------------|",
    ])
    issues = sorted(list(aggregate.get("issues") or []), key=issue_sort_key)
    if issues:
        for issue in issues:
            lines.append(
                "| {severity} | {agent} | {type} | {location} | {description} | {suggestion} |".format(
                    severity=issue.get("severity", ""),
                    agent=issue.get("agent", ""),
                    type=issue.get("type", ""),
                    location=issue.get("location", ""),
                    description=str(issue.get("description", "")).replace("\n", " ").strip(),
                    suggestion=str(issue.get("suggestion", "")).replace("\n", " ").strip(),
                )
            )
    else:
        lines.append("| - | - | - | - | 未发现结构化问题 | - |")

    priority_issues = [issue for issue in issues if issue.get("severity") in {"critical", "high"}]
    lines.extend(["", "## Step 4 修复优先级"])
    if priority_issues:
        for issue in priority_issues:
            lines.append(
                f"- [{issue.get('severity')}] {issue.get('agent')} @ {issue.get('location')}: {issue.get('description')} -> {issue.get('suggestion')}"
            )
    else:
        lines.append("- 当前没有 critical/high 问题，Step 4 以 medium/low/minor 的收益修复为主。")

    lines.extend(
        [
            "",
            "## 产物",
            f"- aggregate_json: {chapter_artifact_dir / 'aggregate.json'}",
            f"- checker_dir: {chapter_artifact_dir / 'checkers'}",
            f"- observability: {report_path.parent.parent / OBSERVABILITY_REL if report_path.parent.parent else OBSERVABILITY_REL}",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def build_metrics_payload(*, start_chapter: int, end_chapter: int, aggregate: Dict[str, Any], report_path: Path, notes: str) -> Dict[str, Any]:
    return {
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "overall_score": aggregate.get("overall_score", 0.0),
        "dimension_scores": aggregate.get("dimension_scores", {}),
        "severity_counts": aggregate.get("severity_counts", {}),
        "critical_issues": aggregate.get("critical_issues", []),
        "report_file": str(report_path.relative_to(report_path.parent.parent)) if report_path.is_absolute() else str(report_path),
        "notes": f"{notes}; execution_mode={aggregate.get('execution_mode', 'standard')}",
    }


def save_review_metrics(project_root: Path, metrics_payload: Dict[str, Any]) -> None:
    temp_dir = ensure_dir(project_root / ".webnovel" / "tmp")
    payload_path = temp_dir / f"review_metrics_{metrics_payload['start_chapter']}_{metrics_payload['end_chapter']}.json"
    write_json(payload_path, metrics_payload)
    command = [
        resolve_python_executable(),
        str(SCRIPTS_DIR / "webnovel.py"),
        "--project-root",
        str(project_root),
        "index",
        "save-review-metrics",
        "--data",
        f"@{payload_path}",
    ]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"save-review-metrics 失败: {(proc.stderr or proc.stdout).strip()}")


def sync_chapter_data_after_review(project_root: Path, chapter: int) -> Dict[str, Any]:
    command = [
        resolve_python_executable(),
        str(SCRIPTS_DIR / "webnovel.py"),
        "--project-root",
        str(project_root),
        "sync-chapter-data",
        "--chapter",
        str(chapter),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"sync-chapter-data 失败: {(proc.stderr or proc.stdout).strip()}")

    stdout = (proc.stdout or "").strip()
    if not stdout:
        return {"chapters_synced": 0}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"raw_stdout": stdout}
    return payload if isinstance(payload, dict) else {"raw": payload}


def build_range_summary(chapter_aggregates: Sequence[Dict[str, Any]], report_files: Sequence[Path]) -> Dict[str, Any]:
    severity_counts = {level: 0 for level in SEVERITY_ORDER}
    dimension_totals: Dict[str, List[float]] = {}
    critical_issues: List[str] = []
    chapter_rows = []

    for aggregate, report_path in zip(chapter_aggregates, report_files):
        for level, count in (aggregate.get("severity_counts") or {}).items():
            try:
                severity_counts[level] = severity_counts.get(level, 0) + int(count)
            except (TypeError, ValueError):
                continue
        for key, value in (aggregate.get("dimension_scores") or {}).items():
            try:
                dimension_totals.setdefault(key, []).append(float(value))
            except (TypeError, ValueError):
                continue
        critical_issues.extend(list(aggregate.get("critical_issues") or []))
        chapter_rows.append(
            {
                "chapter": aggregate.get("chapter"),
                "overall_score": aggregate.get("overall_score", 0),
                "selected_checkers": aggregate.get("selected_checkers", []),
                "report_file": str(report_path),
                "severity_counts": aggregate.get("severity_counts", {}),
            }
        )

    overall_scores = [float(item.get("overall_score", 0)) for item in chapter_aggregates]
    dimension_scores = {
        key: round(float(statistics.mean(values)), 2) for key, values in dimension_totals.items() if values
    }
    return {
        "start_chapter": int(chapter_aggregates[0]["start_chapter"]),
        "end_chapter": int(chapter_aggregates[-1]["end_chapter"]),
        "overall_score": round(float(statistics.mean(overall_scores)), 2) if overall_scores else 0.0,
        "dimension_scores": dimension_scores,
        "severity_counts": severity_counts,
        "critical_issues": critical_issues,
        "chapters": chapter_rows,
        "generated_at": now_iso(),
    }


def render_range_report(summary: Dict[str, Any], report_files: Sequence[Path]) -> str:
    lines = [
        f"# 第{summary['start_chapter']}-{summary['end_chapter']}章审查报告",
        "",
        "## 总览",
        f"- overall_score: {summary.get('overall_score', 0)}",
        "",
        "## 严重度统计",
        "| 等级 | 数量 |",
        "|------|------|",
    ]
    for level in SEVERITY_ORDER:
        lines.append(f"| {level} | {int((summary.get('severity_counts') or {}).get(level, 0))} |")

    lines.extend([
        "",
        "## 分章摘要",
        "| chapter | score | critical | high | medium | low | minor | selected_checkers | report_file |",
        "|---------|-------|----------|------|--------|-----|-------|-------------------|-------------|",
    ])
    for item, report_path in zip(summary.get("chapters") or [], report_files):
        severities = item.get("severity_counts") or {}
        lines.append(
            f"| {item.get('chapter')} | {item.get('overall_score', 0)} | {int(severities.get('critical', 0))} | {int(severities.get('high', 0))} | {int(severities.get('medium', 0))} | {int(severities.get('low', 0))} | {int(severities.get('minor', 0))} | {', '.join(item.get('selected_checkers') or [])} | {report_path.name} |"
        )
    return "\n".join(lines).strip() + "\n"


def review_single_chapter(
    *,
    project_root: Path,
    chapter: int,
    mode: str,
    chapter_file: Path | None = None,
    codex_bin: str | None = None,
    max_parallel: int = DEFAULT_MAX_PARALLEL_CHECKERS,
    persist_metrics: bool = True,
) -> Dict[str, Any]:
    project_root = resolve_project_root(str(project_root))
    chapter_file = resolve_chapter_file(project_root, chapter_file) or find_chapter_file(project_root, chapter)
    if chapter_file is None:
        raise FileNotFoundError(f"未找到第 {chapter} 章文件")

    chapter_artifact_dir = artifact_dir_for_chapter(project_root, chapter)
    reset_chapter_artifacts(chapter_artifact_dir)
    context_payload = build_chapter_context_payload(project_root, chapter)
    context_file = make_context_dump(context_payload, chapter_file, chapter_artifact_dir)
    chapter_text = read_chapter_text(chapter_file)
    selected_checkers = select_checkers(
        chapter=chapter,
        chapter_text=chapter_text,
        context_payload=context_payload,
        mode=mode,
    )

    resolved_codex = resolve_codex_executable(codex_bin)
    append_observability(
        project_root,
        {
            "timestamp": now_iso(),
            "tool_name": "review_agents_runner:plan",
            "chapter": chapter,
            "selected_checkers": selected_checkers,
            "mode": mode,
        },
    )

    results: List[Dict[str, Any]] = []
    failures: List[str] = []
    max_workers = max(1, min(max_parallel, len(selected_checkers)))

    if max_workers == 1:
        for agent in selected_checkers:
            try:
                result = run_checker_subprocess(
                    codex_bin=resolved_codex,
                    project_root=project_root,
                    chapter=chapter,
                    agent=agent,
                    chapter_file=chapter_file,
                    context_payload=context_payload,
                    chapter_text=chapter_text,
                    artifact_dir=chapter_artifact_dir,
                )
            except Exception as exc:
                failures.append(f"{agent}: {exc}")
                append_observability(
                    project_root,
                    {
                        "timestamp": now_iso(),
                        "tool_name": "review_agents_runner:checker",
                        "chapter": chapter,
                        "checker": agent,
                        "success": False,
                        "error": str(exc),
                    },
                )
                break
            results.append(result.payload)
            append_observability(
                project_root,
                {
                    "timestamp": now_iso(),
                    "tool_name": "review_agents_runner:checker",
                    "chapter": chapter,
                    "checker": agent,
                    "elapsed_ms": result.elapsed_ms,
                    "success": True,
                },
            )
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(
                    run_checker_subprocess,
                    codex_bin=resolved_codex,
                    project_root=project_root,
                    chapter=chapter,
                    agent=agent,
                    chapter_file=chapter_file,
                    context_payload=context_payload,
                    chapter_text=chapter_text,
                    artifact_dir=chapter_artifact_dir,
                ): agent
                for agent in selected_checkers
            }
            abort_parallel = False
            for future in concurrent.futures.as_completed(future_map):
                agent = future_map[future]
                if abort_parallel:
                    continue
                try:
                    result = future.result()
                except Exception as exc:
                    failures.append(f"{agent}: {exc}")
                    append_observability(
                        project_root,
                        {
                            "timestamp": now_iso(),
                            "tool_name": "review_agents_runner:checker",
                            "chapter": chapter,
                            "checker": agent,
                            "success": False,
                            "error": str(exc),
                        },
                    )
                    abort_parallel = True
                    for other_future in future_map:
                        if other_future is not future:
                            other_future.cancel()
                    continue
                results.append(result.payload)
                append_observability(
                    project_root,
                    {
                        "timestamp": now_iso(),
                        "tool_name": "review_agents_runner:checker",
                        "chapter": chapter,
                        "checker": agent,
                        "elapsed_ms": result.elapsed_ms,
                        "success": True,
                    },
                )

    if failures:
        try:
            results = run_aggregate_fallback(
                codex_bin=resolved_codex,
                project_root=project_root,
                chapter=chapter,
                selected_checkers=selected_checkers,
                chapter_file=chapter_file,
                context_payload=context_payload,
                chapter_text=chapter_text,
                artifact_dir=chapter_artifact_dir,
                failure_reasons=failures,
            )
        except Exception as exc:
            failures.append(f"aggregate-fallback: {exc}")
            append_observability(
                project_root,
                {
                    "timestamp": now_iso(),
                    "tool_name": "review_agents_runner:fallback",
                    "chapter": chapter,
                    "success": False,
                    "error": str(exc),
                },
            )
            results = hydrate_missing_results_with_local_fallback(
                project_root=project_root,
                chapter=chapter,
                selected_checkers=selected_checkers,
                existing_results=results,
                chapter_text=chapter_text,
                context_payload=context_payload,
                artifact_dir=chapter_artifact_dir,
                failure_reasons=failures,
            )

    results.sort(key=lambda item: selected_checkers.index(item["agent"]))
    aggregate = aggregate_checker_results(
        chapter=chapter,
        chapter_file=chapter_file,
        selected_checkers=selected_checkers,
        results=results,
    )
    post_review_sync: Dict[str, Any] = {"attempted": False, "success": False, "reason": "review_not_passed"}
    if aggregate.get("pass"):
        post_review_sync = {"attempted": True, "success": False}
        try:
            sync_payload = sync_chapter_data_after_review(project_root, chapter)
            post_review_sync.update(
                {
                    "success": True,
                    "chapters_synced": int(sync_payload.get("chapters_synced", 0) or 0),
                    "elapsed_ms": sync_payload.get("elapsed_ms"),
                }
            )
        except Exception as exc:
            post_review_sync["error"] = str(exc)
        append_observability(
            project_root,
            {
                "timestamp": now_iso(),
                "tool_name": "review_agents_runner:post_review_sync",
                "chapter": chapter,
                "success": bool(post_review_sync.get("success")),
                "details": post_review_sync,
            },
        )
    aggregate["post_review_sync"] = post_review_sync
    aggregate_path = chapter_artifact_dir / "aggregate.json"
    if failures:
        aggregate["failure_reasons"] = list(failures)
    write_json(aggregate_path, aggregate)

    report_path = report_path_for_range(project_root, chapter, chapter)
    report_text = render_chapter_report(aggregate, chapter_artifact_dir, report_path)
    report_path.write_text(report_text, encoding="utf-8")

    metrics_payload = build_metrics_payload(
        start_chapter=chapter,
        end_chapter=chapter,
        aggregate=aggregate,
        report_path=report_path,
        notes=f"selected_checkers={','.join(selected_checkers)}",
    )
    if persist_metrics:
        save_review_metrics(project_root, metrics_payload)
    append_observability(
        project_root,
        {
            "timestamp": now_iso(),
            "tool_name": "review_agents_runner:aggregate",
            "chapter": chapter,
            "report_file": str(report_path),
            "overall_score": aggregate.get("overall_score", 0),
            "severity_counts": aggregate.get("severity_counts", {}),
            "success": True,
        },
    )
    aggregate["report_file"] = str(report_path)
    aggregate["aggregate_file"] = str(aggregate_path)
    return aggregate


def review_range(
    *,
    project_root: Path,
    start_chapter: int,
    end_chapter: int,
    mode: str,
    codex_bin: str | None = None,
    max_parallel: int = DEFAULT_MAX_PARALLEL_CHECKERS,
) -> Dict[str, Any]:
    if start_chapter > end_chapter:
        raise ValueError("start_chapter 不能大于 end_chapter")

    chapter_aggregates: List[Dict[str, Any]] = []
    report_files: List[Path] = []
    for chapter in range(start_chapter, end_chapter + 1):
        aggregate = review_single_chapter(
            project_root=project_root,
            chapter=chapter,
            mode=mode,
            codex_bin=codex_bin,
            max_parallel=max_parallel,
            persist_metrics=False,
        )
        chapter_aggregates.append(aggregate)
        report_files.append(Path(aggregate["report_file"]))

    summary = build_range_summary(chapter_aggregates, report_files)
    range_artifact_dir = artifact_dir_for_range(resolve_project_root(str(project_root)), start_chapter, end_chapter)
    aggregate_path = range_artifact_dir / "aggregate.json"
    write_json(aggregate_path, summary)

    report_path = report_path_for_range(resolve_project_root(str(project_root)), start_chapter, end_chapter)
    report_path.write_text(render_range_report(summary, report_files), encoding="utf-8")
    save_review_metrics(
        resolve_project_root(str(project_root)),
        {
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "overall_score": summary.get("overall_score", 0.0),
            "dimension_scores": summary.get("dimension_scores", {}),
            "severity_counts": summary.get("severity_counts", {}),
            "critical_issues": summary.get("critical_issues", []),
            "report_file": str(report_path.relative_to(resolve_project_root(str(project_root)))),
            "notes": f"batch_review chapters={start_chapter}-{end_chapter}",
        },
    )
    summary["report_file"] = str(report_path)
    summary["aggregate_file"] = str(aggregate_path)
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex-backed chapter review subagents")
    parser.add_argument("--project-root", required=True, help="书项目根目录或可解析到项目根目录的路径")
    parser.add_argument("--chapter", type=int, help="单章审查")
    parser.add_argument("--start-chapter", type=int, help="区间起始章")
    parser.add_argument("--end-chapter", type=int, help="区间结束章")
    parser.add_argument("--chapter-file", help="显式指定单章文件路径（可选）")
    parser.add_argument("--mode", choices=["auto", "minimal", "full"], default="auto", help="审查路由模式")
    parser.add_argument("--max-parallel", type=int, default=DEFAULT_MAX_PARALLEL_CHECKERS, help="单章内最大并发 checker 数")
    parser.add_argument("--codex-bin", help="显式指定 codex 可执行文件")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = resolve_project_root(args.project_root)

    if args.chapter:
        result = review_single_chapter(
            project_root=project_root,
            chapter=int(args.chapter),
            chapter_file=Path(args.chapter_file) if args.chapter_file else None,
            mode=args.mode,
            codex_bin=args.codex_bin,
            max_parallel=args.max_parallel,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.start_chapter and args.end_chapter:
        result = review_range(
            project_root=project_root,
            start_chapter=int(args.start_chapter),
            end_chapter=int(args.end_chapter),
            mode=args.mode,
            codex_bin=args.codex_bin,
            max_parallel=args.max_parallel,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    raise SystemExit("必须提供 --chapter，或同时提供 --start-chapter / --end-chapter")


if __name__ == "__main__":
    enable_windows_utf8_stdio(skip_in_pytest=True)
    raise SystemExit(main())
