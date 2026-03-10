"""
Webnovel Dashboard - FastAPI 主应用

仅提供 GET 接口（严格只读）；所有文件读取经过 path_guard 防穿越校验。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .path_guard import safe_resolve
from .watcher import FileWatcher

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------
_project_root: Path | None = None
_watcher = FileWatcher()

STATIC_DIR = Path(__file__).parent / "frontend" / "dist"


def _get_project_root() -> Path:
    if _project_root is None:
        raise HTTPException(status_code=500, detail="项目根目录未配置")
    return _project_root


def _webnovel_dir() -> Path:
    return _get_project_root() / ".webnovel"


def _read_json_file(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_jsonl_tail(path: Path, limit: int = 100) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows[-limit:]


def _parse_timestamp(value: Any) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    raw = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return 0.0


def _tail_text(path: Path, *, max_lines: int = 40, max_chars: int = 6000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tail = "\n".join(lines[-max_lines:])
    if len(tail) <= max_chars:
        return tail
    return tail[-max_chars:]


def _relative_project_path(path: Path) -> str:
    try:
        return str(path.relative_to(_get_project_root())).replace("\\", "/")
    except Exception:
        return str(path)


WORKFLOW_STAGE_LABELS = {
    "context_agent": "Step 1 · Context Agent",
    "draft": "Step 2A · 正文起草",
    "style_adapter": "Step 2B · 风格适配",
    "polish": "Step 4 · 润色",
    "data_agent": "Step 5 · Data Agent",
}

STEP_TO_STAGE = {
    "Step 1": "context_agent",
    "Step 2A": "draft",
    "Step 2B": "style_adapter",
    "Step 4": "polish",
    "Step 5": "data_agent",
}


def _result_path(artifact_dir: Path, stage: str) -> Path | None:
    for candidate in (artifact_dir / f"{stage}.result.json", artifact_dir / f"{stage}.json"):
        if candidate.is_file():
            return candidate
    return None


def _stage_log_info(artifact_dir: Path, stage: str, *, log_lines: int = 40) -> dict | None:
    stdout_path = artifact_dir / f"{stage}.stdout.log"
    stderr_path = artifact_dir / f"{stage}.stderr.log"
    result_path = _result_path(artifact_dir, stage)
    trace_path = artifact_dir / f"{stage}.trace.json"
    execution_path = artifact_dir / f"{stage}.execution.json"
    if not stdout_path.is_file() and not stderr_path.is_file() and result_path is None and not trace_path.is_file() and not execution_path.is_file():
        return None

    result_payload = _read_json_file(result_path, {}) if result_path else {}
    trace_payload = _read_json_file(trace_path, {}) if trace_path.is_file() else {}
    execution_payload = _read_json_file(execution_path, {}) if execution_path.is_file() else {}
    trace_summary = execution_payload.get("trace_summary") if isinstance(execution_payload.get("trace_summary"), dict) else {}
    if not trace_summary and isinstance(trace_payload.get("summary"), dict):
        trace_summary = trace_payload.get("summary") or {}

    summary: dict[str, Any] = {}
    if stage == "context_agent":
        brief = result_payload.get("task_brief") if isinstance(result_payload.get("task_brief"), dict) else {}
        summary = {
            "chapter": result_payload.get("chapter"),
            "core_task": brief.get("core_task"),
        }
    elif stage == "draft":
        content = str(result_payload.get("content") or "")
        summary = {
            "title": result_payload.get("title") or execution_payload.get("title"),
            "file_changed": execution_payload.get("file_changed"),
            "workspace_writes": trace_summary.get("workspace_writes"),
            "tools_seen": trace_summary.get("tools_seen") or [],
            "chars": len(content),
            "workspace_reads": trace_summary.get("workspace_reads"),
            "events_captured": trace_summary.get("events_captured"),
        }
    elif stage in {"style_adapter", "polish"}:
        summary = {
            "file_changed": execution_payload.get("file_changed"),
            "workspace_writes": trace_summary.get("workspace_writes"),
            "workspace_reads": trace_summary.get("workspace_reads"),
            "tools_seen": trace_summary.get("tools_seen") or [],
            "pass_count": len(result_payload.get("pass_reports") or []),
            "full_reread_count": result_payload.get("full_reread_count", 0),
            "change_summary": result_payload.get("change_summary") or [],
            "anti_ai_force_check": result_payload.get("anti_ai_force_check"),
        }
    elif stage == "data_agent":
        summary = {
            "summary_text": result_payload.get("summary_text"),
            "foreshadowing_count": len(result_payload.get("foreshadowing_notes") or []),
            "scene_count": len(result_payload.get("scenes") or []),
        }

    candidates = [p for p in (stdout_path, stderr_path, result_path, trace_path, execution_path) if p and p.exists()]
    updated_at = max((p.stat().st_mtime for p in candidates), default=0)
    return {
        "stage": stage,
        "label": WORKFLOW_STAGE_LABELS.get(stage, stage),
        "stdout_exists": stdout_path.is_file(),
        "stderr_exists": stderr_path.is_file(),
        "stdout_excerpt": _tail_text(stdout_path, max_lines=log_lines),
        "stderr_excerpt": _tail_text(stderr_path, max_lines=min(20, log_lines)),
        "stdout_path": _relative_project_path(stdout_path) if stdout_path.is_file() else None,
        "stderr_path": _relative_project_path(stderr_path) if stderr_path.is_file() else None,
        "result_path": _relative_project_path(result_path) if result_path else None,
        "trace_path": _relative_project_path(trace_path) if trace_path.is_file() else None,
        "execution_path": _relative_project_path(execution_path) if execution_path.is_file() else None,
        "trace_summary": trace_summary,
        "result_summary": summary,
        "updated_at": updated_at,
    }


def _active_workflow_chapter(workflow_state: dict) -> int | None:
    current_task = workflow_state.get("current_task") if isinstance(workflow_state, dict) else None
    if isinstance(current_task, dict):
        chapter = current_task.get("args", {}).get("chapter_num")
        if isinstance(chapter, int) and chapter > 0:
            return chapter
    last_stable = workflow_state.get("last_stable_state") if isinstance(workflow_state, dict) else None
    if isinstance(last_stable, dict):
        chapter = last_stable.get("chapter") or last_stable.get("chapter_num")
        if isinstance(chapter, int) and chapter > 0:
            return chapter
    return None


def _active_stage_name(workflow_state: dict, stage_logs: dict[str, dict]) -> str | None:
    current_task = workflow_state.get("current_task") if isinstance(workflow_state, dict) else None
    current_step = current_task.get("current_step") if isinstance(current_task, dict) else None
    if isinstance(current_step, dict):
        step_id = str(current_step.get("id") or "")
        if step_id in STEP_TO_STAGE:
            return STEP_TO_STAGE[step_id]
    if stage_logs:
        latest = max(stage_logs.values(), key=lambda row: float(row.get("updated_at") or 0))
        return str(latest.get("stage") or "") or None
    return None


def _load_review_snapshot(artifact_dir: Path, name: str) -> dict:
    payload = _read_json_file(artifact_dir / name, {})
    return payload if isinstance(payload, dict) else {}


def _format_call_trace_event(row: dict) -> dict:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    event = str(row.get("event") or "trace")
    title = event
    message = ""
    if event == "task_started":
        title = "任务启动"
        message = f"{payload.get('command') or 'unknown'} · 第 {payload.get('args', {}).get('chapter_num') or '?'} 章"
    elif event == "task_reentered":
        title = "任务重入"
        message = f"重试次数 {payload.get('retry_count') or 0}"
    elif event == "step_started":
        title = f"{payload.get('step_id') or 'Step'} 开始"
        message = str(payload.get("step_name") or "")
        if payload.get("progress_note"):
            message = f"{message} · {payload.get('progress_note')}".strip(" ·")
    elif event == "step_progress":
        title = f"{payload.get('step_id') or 'Step'} 进度"
        message = str(payload.get("progress_note") or payload.get("status_detail") or "")
    elif event == "step_completed":
        title = f"{payload.get('step_id') or 'Step'} 完成"
        message = str(payload.get("command") or "")
    elif event == "task_completed":
        title = "任务完成"
        message = f"第 {payload.get('chapter') or '?'} 章"
    elif event == "step_order_violation":
        title = "步骤顺序异常"
        message = str(payload.get("step_id") or "")
    return {
        "timestamp": row.get("timestamp"),
        "source": "call_trace",
        "title": title,
        "message": message,
        "chapter": payload.get("chapter") or payload.get("args", {}).get("chapter_num"),
    }


def _format_write_event(row: dict) -> dict:
    stage = str(row.get("stage") or "stage")
    kind = str(row.get("kind") or "summary")
    if kind == "event":
        title = f"{WORKFLOW_STAGE_LABELS.get(stage, stage)} · {row.get('event') or 'event'}"
        message = str(row.get("message") or "")
    else:
        title = f"{WORKFLOW_STAGE_LABELS.get(stage, stage)} {'完成' if row.get('success') else '失败'}"
        elapsed = row.get("elapsed_ms")
        message = f"elapsed={elapsed}ms" if elapsed else str((row.get("details") or {}).get("error") or "")
    return {
        "timestamp": row.get("timestamp"),
        "source": "write_observability",
        "title": title,
        "message": message,
        "chapter": (row.get("details") or {}).get("chapter"),
    }


def _format_review_event(row: dict) -> dict:
    tool_name = str(row.get("tool_name") or "review")
    checker = str(row.get("checker") or "").strip()
    title = tool_name
    message = ""
    if checker:
        title = f"{checker} {'通过' if row.get('success', True) else '失败'}"
        if row.get("elapsed_ms"):
            message = f"elapsed={row.get('elapsed_ms')}ms"
        elif row.get("error"):
            message = str(row.get("error") or "")
    elif tool_name.endswith(":aggregate"):
        title = "审查聚合"
        message = f"score={row.get('overall_score')}"
    elif tool_name.endswith(":plan"):
        title = "审查计划"
        message = ", ".join(row.get("selected_checkers") or [])
    else:
        message = str(row.get("error") or row.get("details") or "")
    return {
        "timestamp": row.get("timestamp"),
        "source": "review_observability",
        "title": title,
        "message": message,
        "chapter": row.get("chapter"),
    }


def _build_workflow_live_payload(*, event_limit: int = 80, log_lines: int = 40) -> dict:
    webnovel = _webnovel_dir()
    workflow_state = _read_json_file(webnovel / "workflow_state.json", {}) or {}
    chapter = _active_workflow_chapter(workflow_state)
    artifact_dir = webnovel / "write_workflow" / f"ch{chapter:04d}" if chapter else None

    stage_logs: dict[str, dict] = {}
    if artifact_dir and artifact_dir.is_dir():
        for stage in WORKFLOW_STAGE_LABELS:
            info = _stage_log_info(artifact_dir, stage, log_lines=log_lines)
            if info:
                stage_logs[stage] = info

    recent_events = [
        *(_format_call_trace_event(row) for row in _read_jsonl_tail(webnovel / "observability" / "call_trace.jsonl", limit=event_limit * 2)),
        *(_format_write_event(row) for row in _read_jsonl_tail(webnovel / "observability" / "codex_write_workflow.jsonl", limit=event_limit * 2)),
        *(_format_review_event(row) for row in _read_jsonl_tail(webnovel / "observability" / "review_agent_timing.jsonl", limit=event_limit * 2)),
    ]
    recent_events = sorted(recent_events, key=lambda row: _parse_timestamp(row.get("timestamp")), reverse=True)[:event_limit]

    return {
        "workflow_state": workflow_state,
        "current_task": workflow_state.get("current_task"),
        "last_stable_state": workflow_state.get("last_stable_state"),
        "chapter": chapter,
        "artifact_dir": _relative_project_path(artifact_dir) if artifact_dir and artifact_dir.exists() else None,
        "active_stage": _active_stage_name(workflow_state, stage_logs),
        "stage_logs": stage_logs,
        "review": {
            "initial": _load_review_snapshot(artifact_dir, "review_initial.json") if artifact_dir and artifact_dir.exists() else {},
            "final": _load_review_snapshot(artifact_dir, "review_final.json") if artifact_dir and artifact_dir.exists() else {},
        },
        "recent_events": recent_events,
        "sources": {
            "call_trace": _relative_project_path(webnovel / "observability" / "call_trace.jsonl"),
            "write_observability": _relative_project_path(webnovel / "observability" / "codex_write_workflow.jsonl"),
            "review_observability": _relative_project_path(webnovel / "observability" / "review_agent_timing.jsonl"),
        },
    }


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------

def create_app(project_root: str | Path | None = None) -> FastAPI:
    global _project_root

    if project_root:
        _project_root = Path(project_root).resolve()

    @asynccontextmanager
    async def _lifespan(_: FastAPI):
        webnovel = _webnovel_dir()
        if webnovel.is_dir():
            _watcher.start(webnovel, asyncio.get_running_loop())
        try:
            yield
        finally:
            _watcher.stop()

    app = FastAPI(title="Webnovel Dashboard", version="0.1.0", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # ===========================================================
    # API：项目元信息
    # ===========================================================

    @app.get("/api/project/info")
    def project_info():
        """返回 state.json 完整内容（只读）。"""
        state_path = _webnovel_dir() / "state.json"
        if not state_path.is_file():
            raise HTTPException(404, "state.json 不存在")
        return json.loads(state_path.read_text(encoding="utf-8"))

    # ===========================================================
    # API：实体数据库（index.db 只读查询）
    # ===========================================================

    def _get_db() -> sqlite3.Connection:
        db_path = _webnovel_dir() / "index.db"
        if not db_path.is_file():
            raise HTTPException(404, "index.db 不存在")
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _fetchall_safe(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict]:
        """执行只读查询；若目标表不存在（旧库），返回空列表。"""
        try:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise HTTPException(status_code=500, detail=f"数据库查询失败: {exc}") from exc

    @app.get("/api/entities")
    def list_entities(
        entity_type: Optional[str] = Query(None, alias="type"),
        include_archived: bool = False,
    ):
        """列出所有实体（可按类型过滤）。"""
        with closing(_get_db()) as conn:
            q = "SELECT * FROM entities"
            params: list = []
            clauses: list[str] = []
            if entity_type:
                clauses.append("type = ?")
                params.append(entity_type)
            if not include_archived:
                clauses.append("is_archived = 0")
            if clauses:
                q += " WHERE " + " AND ".join(clauses)
            q += " ORDER BY last_appearance DESC"
            rows = conn.execute(q, params).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/entities/{entity_id}")
    def get_entity(entity_id: str):
        with closing(_get_db()) as conn:
            row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
            if not row:
                raise HTTPException(404, "实体不存在")
            return dict(row)

    @app.get("/api/relationships")
    def list_relationships(entity: Optional[str] = None, limit: int = 200):
        with closing(_get_db()) as conn:
            if entity:
                rows = conn.execute(
                    "SELECT * FROM relationships WHERE from_entity = ? OR to_entity = ? ORDER BY chapter DESC LIMIT ?",
                    (entity, entity, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM relationships ORDER BY chapter DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/relationship-events")
    def list_relationship_events(
        entity: Optional[str] = None,
        from_chapter: Optional[int] = None,
        to_chapter: Optional[int] = None,
        limit: int = 200,
    ):
        with closing(_get_db()) as conn:
            q = "SELECT * FROM relationship_events"
            params: list = []
            clauses: list[str] = []
            if entity:
                clauses.append("(from_entity = ? OR to_entity = ?)")
                params.extend([entity, entity])
            if from_chapter is not None:
                clauses.append("chapter >= ?")
                params.append(from_chapter)
            if to_chapter is not None:
                clauses.append("chapter <= ?")
                params.append(to_chapter)
            if clauses:
                q += " WHERE " + " AND ".join(clauses)
            q += " ORDER BY chapter DESC, id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(q, params).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/chapters")
    def list_chapters():
        with closing(_get_db()) as conn:
            rows = conn.execute("SELECT * FROM chapters ORDER BY chapter ASC").fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/scenes")
    def list_scenes(chapter: Optional[int] = None, limit: int = 500):
        with closing(_get_db()) as conn:
            if chapter is not None:
                rows = conn.execute(
                    "SELECT * FROM scenes WHERE chapter = ? ORDER BY scene_index ASC", (chapter,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scenes ORDER BY chapter ASC, scene_index ASC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/reading-power")
    def list_reading_power(limit: int = 50):
        with closing(_get_db()) as conn:
            rows = conn.execute(
                "SELECT * FROM chapter_reading_power ORDER BY chapter DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/review-metrics")
    def list_review_metrics(limit: int = 20):
        with closing(_get_db()) as conn:
            rows = conn.execute(
                "SELECT * FROM review_metrics ORDER BY end_chapter DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/state-changes")
    def list_state_changes(entity: Optional[str] = None, limit: int = 100):
        with closing(_get_db()) as conn:
            if entity:
                rows = conn.execute(
                    "SELECT * FROM state_changes WHERE entity_id = ? ORDER BY chapter DESC LIMIT ?",
                    (entity, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM state_changes ORDER BY chapter DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    @app.get("/api/aliases")
    def list_aliases(entity: Optional[str] = None):
        with closing(_get_db()) as conn:
            if entity:
                rows = conn.execute(
                    "SELECT * FROM aliases WHERE entity_id = ?", (entity,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM aliases").fetchall()
            return [dict(r) for r in rows]

    # ===========================================================
    # API：扩展表（v5.3+ / v5.4+）
    # ===========================================================

    @app.get("/api/overrides")
    def list_overrides(status: Optional[str] = None, limit: int = 100):
        with closing(_get_db()) as conn:
            if status:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM override_contracts WHERE status = ? ORDER BY chapter DESC LIMIT ?",
                    (status, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM override_contracts ORDER BY chapter DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/debts")
    def list_debts(status: Optional[str] = None, limit: int = 100):
        with closing(_get_db()) as conn:
            if status:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM chase_debt WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM chase_debt ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/debt-events")
    def list_debt_events(debt_id: Optional[int] = None, limit: int = 200):
        with closing(_get_db()) as conn:
            if debt_id is not None:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM debt_events WHERE debt_id = ? ORDER BY chapter DESC, id DESC LIMIT ?",
                    (debt_id, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM debt_events ORDER BY chapter DESC, id DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/invalid-facts")
    def list_invalid_facts(status: Optional[str] = None, limit: int = 100):
        with closing(_get_db()) as conn:
            if status:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM invalid_facts WHERE status = ? ORDER BY marked_at DESC LIMIT ?",
                    (status, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM invalid_facts ORDER BY marked_at DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/rag-queries")
    def list_rag_queries(query_type: Optional[str] = None, limit: int = 100):
        with closing(_get_db()) as conn:
            if query_type:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM rag_query_log WHERE query_type = ? ORDER BY created_at DESC LIMIT ?",
                    (query_type, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM rag_query_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/tool-stats")
    def list_tool_stats(tool_name: Optional[str] = None, limit: int = 200):
        with closing(_get_db()) as conn:
            if tool_name:
                return _fetchall_safe(
                    conn,
                    "SELECT * FROM tool_call_stats WHERE tool_name = ? ORDER BY created_at DESC LIMIT ?",
                    (tool_name, limit),
                )
            return _fetchall_safe(
                conn,
                "SELECT * FROM tool_call_stats ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/checklist-scores")
    def list_checklist_scores(limit: int = 100):
        with closing(_get_db()) as conn:
            return _fetchall_safe(
                conn,
                "SELECT * FROM writing_checklist_scores ORDER BY chapter DESC LIMIT ?",
                (limit,),
            )

    @app.get("/api/workflow/state")
    def workflow_state():
        return _read_json_file(_webnovel_dir() / "workflow_state.json", {}) or {}

    @app.get("/api/workflow/call-trace")
    def workflow_call_trace(limit: int = 120):
        return _read_jsonl_tail(_webnovel_dir() / "observability" / "call_trace.jsonl", limit=limit)

    @app.get("/api/workflow/write-observability")
    def workflow_write_observability(limit: int = 120):
        return _read_jsonl_tail(_webnovel_dir() / "observability" / "codex_write_workflow.jsonl", limit=limit)

    @app.get("/api/workflow/review-observability")
    def workflow_review_observability(limit: int = 120):
        return _read_jsonl_tail(_webnovel_dir() / "observability" / "review_agent_timing.jsonl", limit=limit)

    @app.get("/api/workflow/live")
    def workflow_live(event_limit: int = 80, log_lines: int = 40):
        return _build_workflow_live_payload(event_limit=event_limit, log_lines=log_lines)

    @app.get("/api/workflow/stage-log")
    def workflow_stage_log(stage: str, stream: str = "stdout", chapter: Optional[int] = None):
        if stream not in {"stdout", "stderr"}:
            raise HTTPException(400, "stream 仅支持 stdout / stderr")
        if stage not in WORKFLOW_STAGE_LABELS:
            raise HTTPException(400, f"未知 stage: {stage}")

        workflow_state = _read_json_file(_webnovel_dir() / "workflow_state.json", {}) or {}
        target_chapter = chapter or _active_workflow_chapter(workflow_state)
        if not target_chapter:
            raise HTTPException(404, "未找到活动章节")

        artifact_dir = _webnovel_dir() / "write_workflow" / f"ch{target_chapter:04d}"
        log_path = artifact_dir / f"{stage}.{stream}.log"
        if not log_path.is_file():
            raise HTTPException(404, f"未找到 {stage}.{stream}.log")
        return {
            "chapter": target_chapter,
            "stage": stage,
            "label": WORKFLOW_STAGE_LABELS.get(stage, stage),
            "stream": stream,
            "path": _relative_project_path(log_path),
            "content": log_path.read_text(encoding="utf-8"),
        }

    # ===========================================================
    # API：文档浏览（正文/大纲/设定集 —— 只读）
    # ===========================================================

    @app.get("/api/files/tree")
    def file_tree():
        """列出 正文/、大纲/、设定集/ 三个目录的树结构。"""
        root = _get_project_root()
        result = {}
        for folder_name in ("正文", "大纲", "设定集"):
            folder = root / folder_name
            if not folder.is_dir():
                result[folder_name] = []
                continue
            result[folder_name] = _walk_tree(folder, root)
        return result

    @app.get("/api/files/read")
    def file_read(path: str):
        """只读读取一个文件内容（限 正文/大纲/设定集 目录）。"""
        root = _get_project_root()
        resolved = safe_resolve(root, path)

        # 二次限制：只允许三大目录
        allowed_parents = [root / n for n in ("正文", "大纲", "设定集")]
        if not any(_is_child(resolved, p) for p in allowed_parents):
            raise HTTPException(403, "仅允许读取 正文/大纲/设定集 目录下的文件")

        if not resolved.is_file():
            raise HTTPException(404, "文件不存在")

        # 文本文件直接读；其他情况返回占位信息
        try:
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = "[二进制文件，无法预览]"

        return {"path": path, "content": content}

    # ===========================================================
    # SSE：实时变更推送
    # ===========================================================

    @app.get("/api/events")
    async def sse():
        """Server-Sent Events 端点，推送 .webnovel/ 下的文件变更。"""
        q = _watcher.subscribe()

        async def _gen():
            try:
                while True:
                    msg = await q.get()
                    yield f"data: {msg}\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                _watcher.unsubscribe(q)

        return StreamingResponse(_gen(), media_type="text/event-stream")

    # ===========================================================
    # 前端静态文件托管
    # ===========================================================

    if STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

        @app.get("/{full_path:path}")
        def serve_spa(full_path: str):
            """SPA fallback：任何非 /api 路径都返回 index.html。"""
            index = STATIC_DIR / "index.html"
            if index.is_file():
                return FileResponse(str(index))
            raise HTTPException(404, "前端尚未构建")
    else:
        @app.get("/")
        def no_frontend():
            return HTMLResponse(
                "<h2>Webnovel Dashboard API is running</h2>"
                "<p>前端尚未构建。请先在 <code>dashboard/frontend</code> 目录执行 <code>npm run build</code>。</p>"
                '<p>API 文档：<a href="/docs">/docs</a></p>'
            )

    return app


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _walk_tree(folder: Path, root: Path) -> list[dict]:
    items = []
    for child in sorted(folder.iterdir()):
        rel = str(child.relative_to(root)).replace("\\", "/")
        if child.is_dir():
            items.append({"name": child.name, "type": "dir", "path": rel, "children": _walk_tree(child, root)})
        else:
            items.append({"name": child.name, "type": "file", "path": rel, "size": child.stat().st_size})
    return items


def _is_child(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
