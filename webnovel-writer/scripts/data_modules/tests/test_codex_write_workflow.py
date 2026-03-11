#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import json
import pytest
import sys
from pathlib import Path
from types import SimpleNamespace


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_module():
    _ensure_scripts_on_path()
    import codex_write_workflow as module

    return module


def test_run_write_workflow_happy_path(monkeypatch, tmp_path, capsys):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()
    total_path = project_root / "大纲" / "总纲.md"
    state_path = project_root / ".webnovel" / "state.json"

    total_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    total_path.write_text("# 总纲", encoding="utf-8")
    state_path.write_text(json.dumps({"progress": {}}, ensure_ascii=False), encoding="utf-8")

    calls = {"steps": [], "task_completed": 0}

    monkeypatch.setattr(module, "resolve_project_root", lambda raw: Path(raw))
    monkeypatch.setattr(module, "start_task", lambda project_root, chapter: calls.__setitem__("task", chapter))
    monkeypatch.setattr(module, "start_step", lambda project_root, step_id, step_name, note=None: calls["steps"].append(("start", step_id)))
    monkeypatch.setattr(module, "complete_step", lambda project_root, step_id, artifacts=None: calls["steps"].append(("complete", step_id)))
    monkeypatch.setattr(module, "complete_task", lambda project_root, artifacts=None: calls.__setitem__("task_completed", calls["task_completed"] + 1))
    monkeypatch.setattr(module, "_load_state", lambda project_root: {"progress": {}})
    monkeypatch.setattr(module, "_load_context_materials", lambda project_root, chapter: {"state": {"progress": {}}})

    stage_payloads = {
        "context_agent": {
            "chapter": 9,
            "task_brief": {
                "core_task": "推进仓库线",
                "conflict": "主角潜入风险高",
                "carry_from_previous": "接住第8章药铺仓库线索",
                "characters": [],
                "scene_constraints": [],
                "foreshadowing": [],
                "foreshadowing_plan": {"must_continue": [], "planned_new": [], "forbidden_resolve": []},
                "reading_power": [],
            },
            "contract_v2": {
                "goal": "查仓库",
                "obstacle": "守卫和风险",
                "cost": "暴露可能",
                "change": "拿到新线索",
                "unresolved_question": "谁在仓库接货",
                "core_conflict": "主角要不要冒险潜入",
                "opening_type": "危机开场",
                "emotion_pacing": "紧张",
                "info_density": "中高",
                "is_transition": False,
                "hook_type": "悬念钩",
                "hook_strength": "strong",
                "micropayoffs": ["发现新证据"],
            },
            "draft_package": {
                "title_suggestion": "旧仓里的回声",
                "beat_sheet": ["开场", "推进", "反转", "钩子"],
                "immutable_facts": ["药铺仓库线索来自第8章"],
                "forbidden": ["不能越级"],
                "checklist": ["接住上章"],
                "target_words": 2200,
            },
        },
        "draft": {"title": "旧仓里的回声", "content": "林小天推开旧仓木门。"},
        "style_adapter": {
            "title": "旧仓里的回声",
            "content": "林小天推开旧仓木门，冷风一下灌进来。",
            "change_summary": ["拆分说明句", "压短段落"],
            "pass_reports": [
                {
                    "pass_id": "style-pass-a",
                    "focus": "局部风格转译",
                    "full_reread": False,
                    "applied_changes": ["把说明句改成动作句"],
                },
                {
                    "pass_id": "style-pass-b",
                    "focus": "全章回读与节奏校正",
                    "full_reread": True,
                    "applied_changes": ["压缩重复解释"],
                    "checks": ["opening_conflict", "hook", "typesetting"],
                },
            ],
            "full_reread_count": 1,
            "retained": [],
        },
        "polish": {
            "content": "林小天推开旧仓木门，冷风一下灌进来。\n他先听见回声，再闻到药味。",
            "change_summary": ["压缩说明腔", "补强感官锚点"],
            "anti_ai_force_check": "pass",
            "deviation": [],
            "pass_reports": [
                {
                    "pass_id": "polish-pass-a",
                    "focus": "review issues 修复",
                    "full_reread": False,
                    "applied_changes": ["修补说明腔", "补日期锚点"],
                },
                {
                    "pass_id": "polish-pass-b",
                    "focus": "全章重读 + Anti-AI",
                    "full_reread": True,
                    "applied_changes": ["抽象判断改成动作反应"],
                    "checks": ["anti_ai"],
                },
                {
                    "pass_id": "polish-pass-c",
                    "focus": "全章重读 + No-Poison + 排版",
                    "full_reread": True,
                    "applied_changes": ["压短一处长段落"],
                    "checks": ["no_poison", "typesetting"],
                },
            ],
            "full_reread_count": 2,
            "retained": [],
        },
        "data_agent": {
            "entities_appeared": [],
            "entities_new": [{"suggested_id": "old_warehouse", "name": "旧药仓", "type": "地点", "tier": "重要"}],
            "state_changes": [],
            "relationships_new": [],
            "scenes_chunked": 1,
            "uncertain": [],
            "warnings": [],
            "chapter_meta": {
                "title": "旧仓里的回声",
                "hook": "仓库深处传来第二道脚步声",
                "hook_type": "悬念钩",
                "hook_strength": "strong",
                "unresolved_question": "仓库里还有谁",
                "ending_state": "主角摸到仓库入口",
                "dominant_strand": "quest",
                "summary": "主角进入旧药仓并发现新的异常动静。",
            },
            "summary_text": "林小天追到旧药仓，确认药味与失衡波动重叠。",
            "foreshadowing_notes": ["[推进] 药仓线索落地"],
            "foreshadowing_planted": [
                {"id": "fs_warehouse_buyer", "content": "旧药仓深处还有更上游的接货人", "purpose": "把仓库线抬到上游黑手", "plant_method": "脚步声+避人痕迹", "expected_payoff": "Ch10-12", "tier": "核心"}
            ],
            "foreshadowing_continued": [],
            "foreshadowing_resolved": [],
            "bridge_line": "下章进入仓库深处",
            "location": "南河路旧药仓",
            "time_anchor": "清晨",
            "characters": ["林小天"],
            "scenes": [{"index": 1, "scene_index": 1, "summary": "林小天靠近旧药仓", "content": "林小天推开旧仓木门。"}],
        },
    }

    stage_calls = []

    def fake_run_codex_json_stage(stage_name, **kwargs):
        stage_calls.append((stage_name, kwargs))
        return stage_payloads[stage_name]

    monkeypatch.setattr(module, "run_codex_json_stage", fake_run_codex_json_stage)
    monkeypatch.setattr(module, "run_context_agent_stage", lambda **_kwargs: stage_payloads["context_agent"])

    review_modes = []

    monkeypatch.setattr(
        module,
        "_run_review_cli",
        lambda *args, **kwargs: review_modes.append(kwargs.get("mode") if "mode" in kwargs else args[3]) or {
            "overall_score": 83.0,
            "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "report_file": str(project_root / "审查报告" / "第9-9章审查报告.md"),
            "aggregate_file": str(project_root / ".webnovel" / "reviews" / "ch0009" / "aggregate.json"),
        },
    )
    monkeypatch.setattr(
        module,
        "_apply_data_payload",
        lambda *args, **kwargs: {
            "summary_file": str(project_root / ".webnovel" / "summaries" / "ch0009.md"),
            "timing_ms": {"TOTAL": 1234},
        },
    )
    monkeypatch.setattr(module, "_chapter_stats", lambda project_root: {"chapters": 9, "total_chars": 20000})

    result = module.run_write_workflow(project_root=project_root, chapter=9, mode="standard")

    assert result["status"] == "ok"
    assert result["chapter"] == 9
    assert result["anti_ai_force_check"] == "pass"
    assert result["style_full_reread_count"] == 1
    assert result["polish_full_reread_count"] == 2
    assert result["overall_score"] == 83.0
    assert calls["task"] == 9
    assert calls["task_completed"] == 1
    assert ("start", "Step 1") in calls["steps"]
    assert ("complete", "Step 6") in calls["steps"]
    assert (project_root / "正文" / "第1卷" / "第009章.md").is_file()
    assert review_modes == ["full", "full"]

    captured = capsys.readouterr()
    assert "▶ Step 1 开始: Context Agent" in captured.err
    assert "✅ Step 4 完成: 润色" in captured.err
    assert "✅ webnovel-write 第 9 章完成" in captured.err

    stage_kwargs = {stage_name: kwargs for stage_name, kwargs in stage_calls}
    assert "context_agent" not in stage_kwargs
    assert stage_kwargs["draft"]["sandbox_mode"] == "workspace-write"
    assert stage_kwargs["draft"]["require_workspace_mutation"] is True
    assert stage_kwargs["draft"]["expected_title"] == "旧仓里的回声"
    assert stage_kwargs["style_adapter"]["sandbox_mode"] == "workspace-write"
    assert stage_kwargs["style_adapter"]["workspace_file"].name == "第009章.md"
    assert stage_kwargs["polish"]["sandbox_mode"] == "workspace-write"
    assert stage_kwargs["polish"]["workspace_file"].name == "第009章.md"
    assert "正文/第1卷/第009章.md" in stage_kwargs["draft"]["prompt"]
    assert "正文/第1卷/第009章.md" in stage_kwargs["style_adapter"]["prompt"]
    assert "正文/第1卷/第009章.md" in stage_kwargs["polish"]["prompt"]


def test_apply_data_payload_updates_progress_and_strand(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    chapter_file = project_root / "正文" / "第1卷" / "第009章.md"
    chapter_file.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    chapter_file.write_text("第9章 测试\n\n正文。", encoding="utf-8")

    calls = []

    def fake_run_webnovel(project_root_arg, *args, timeout=None):
        calls.append(args)
        if args[:2] == ("state", "process-chapter"):
            return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "success", "data": {"chapter": 9}}, ensure_ascii=False), stderr="")
        if args[:1] == ("sync-chapter-data",):
            return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "success", "data": {"chapters_synced": 1}}, ensure_ascii=False), stderr="")
        if args[:2] == ("rag", "index-chapter"):
            return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "success", "data": {"indexed": 1}}, ensure_ascii=False), stderr="")
        if args[:2] == ("style", "extract"):
            return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "success", "data": {"patterns": []}}, ensure_ascii=False), stderr="")
        if args[:1] == ("update-state",):
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(module, "_run_webnovel", fake_run_webnovel)
    monkeypatch.setattr(module, "find_chapter_file", lambda *_args, **_kwargs: chapter_file)
    monkeypatch.setattr(module, "_chapter_stats", lambda *_args, **_kwargs: {"chapters": 9, "total_chars": 2222})
    monkeypatch.setattr(module, "observe_data_agent", lambda *_args, **_kwargs: None)

    result = module._apply_data_payload(
        project_root=project_root,
        chapter=9,
        data_payload={
            "entities_appeared": [{"id": "lin_xiaotian", "type": "角色", "mentions": ["林小天"], "confidence": 1.0}],
            "entities_new": [],
            "state_changes": [],
            "relationships_new": [],
            "scenes_chunked": 1,
            "uncertain": [],
            "warnings": [],
            "chapter_meta": {"dominant_strand": "quest"},
            "summary_text": "摘要",
            "foreshadowing_notes": [],
            "foreshadowing_planted": [],
            "foreshadowing_continued": [],
            "foreshadowing_resolved": [],
            "bridge_line": "承接",
            "scenes": [{"index": 1, "scene_index": 1, "summary": "场景", "content": "正文"}],
            "review_score": 86.0,
        },
        artifact_dir=artifact_dir,
        enable_debt_interest=False,
    )

    update_call = next(args for args in calls if args and args[0] == "update-state")
    assert "--progress" in update_call
    assert "2222" in update_call
    assert "--strand-dominant" in update_call
    assert "quest" in update_call
    assert result["update_state"]["progress"] == 2222
    assert result["update_state"]["dominant_strand"] == "quest"


def test_run_codex_json_stage_retries_when_stdout_has_provider_502_but_stderr_is_warning(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0001"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(module, "resolve_codex_executable", lambda _raw: "/usr/bin/codex")
    monkeypatch.setattr(module, "build_codex_exec_command", lambda **_kwargs: ["codex", "exec"])
    observe_calls = []
    monkeypatch.setattr(module, "observe_write", lambda *args, **kwargs: observe_calls.append((args, kwargs)))
    monkeypatch.setattr(module, "observe_write_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "update_step", lambda *args, **kwargs: None)

    calls = {"count": 0}

    class _FakePipe:
        def __init__(self):
            self.buffer = []

        def write(self, chunk):
            self.buffer.append(chunk)
            return len(chunk)

        def close(self):
            return None

    class _FakePopen:
        def __init__(self, *_args, **_kwargs):
            calls["count"] += 1
            output_path = artifact_dir / "context_agent.json"
            self.stdin = _FakePipe()
            if calls["count"] == 1:
                output_path.write_text("", encoding="utf-8")
                self.returncode = 1
                self.stdout = io.StringIO(
                    '{"type":"thread.started"}\n'
                    '{"type":"error","message":"Reconnecting... 1/2 (unexpected status 502 Bad Gateway)"}\n'
                    '{"type":"error","message":"unexpected status 502 Bad Gateway"}\n'
                    '{"type":"turn.failed","error":{"message":"unexpected status 502 Bad Gateway"}}\n'
                )
                self.stderr = io.StringIO(f"Warning: no last agent message; wrote empty content to {output_path}\n")
            else:
                output_path.write_text(json.dumps({"chapter": 1, "task_brief": {}}, ensure_ascii=False), encoding="utf-8")
                self.returncode = 0
                self.stdout = io.StringIO(
                    '{"type":"thread.started"}\n'
                    '{"type":"turn.started"}\n'
                    '{"type":"turn.completed"}\n'
                )
                self.stderr = io.StringIO("")

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            return None

        def kill(self):
            return None

    monkeypatch.setattr(module.subprocess, "Popen", _FakePopen)

    payload = module.run_codex_json_stage(
        stage_name="context_agent",
        prompt="prompt",
        schema={"type": "object"},
        project_root=project_root,
        artifact_dir=artifact_dir,
        retries=2,
    )

    assert payload["chapter"] == 1
    assert calls["count"] == 2
    assert observe_calls[-1][1]["details"]["attempt"] == 2


def test_run_codex_json_stage_captures_trace_and_execution_sidecars(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0001"
    workspace_file = project_root / "正文" / "第1卷" / "第001章.md"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    workspace_file.parent.mkdir(parents=True, exist_ok=True)
    workspace_file.write_text(module._compose_chapter_file(1, "旧标题", "旧正文"), encoding="utf-8")

    monkeypatch.setattr(module, "resolve_codex_executable", lambda _raw: "/usr/bin/codex")
    monkeypatch.setattr(module, "build_codex_exec_command", lambda **_kwargs: ["codex", "exec"])
    observe_calls = []
    monkeypatch.setattr(module, "observe_write", lambda *args, **kwargs: observe_calls.append((args, kwargs)))
    monkeypatch.setattr(module, "observe_write_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "update_step", lambda *args, **kwargs: None)

    class _FakePipe:
        def __init__(self):
            self.buffer = []

        def write(self, chunk):
            self.buffer.append(chunk)
            return len(chunk)

        def close(self):
            return None

    class _FakePopen:
        def __init__(self, *_args, **_kwargs):
            output_path = artifact_dir / "draft.json"
            output_path.write_text(json.dumps({"title": "新标题", "content": "改后正文"}, ensure_ascii=False), encoding="utf-8")
            workspace_file.write_text(module._compose_chapter_file(1, "新标题", "改后正文"), encoding="utf-8")
            self.stdin = _FakePipe()
            self.returncode = 0
            self.stdout = io.StringIO(
                '{"type":"thread.started"}\n'
                '{"type":"response.item","item":{"type":"tool_call","name":"read_file","path":"正文/第1卷/第001章.md","summary":"读取当前章节"}}\n'
                '{"type":"response.item","item":{"type":"tool_call","name":"update_file","path":"正文/第1卷/第001章.md","summary":"写回修订正文"}}\n'
                '{"type":"turn.completed"}\n'
            )
            self.stderr = io.StringIO("")

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

        def terminate(self):
            return None

        def kill(self):
            return None

    monkeypatch.setattr(module.subprocess, "Popen", _FakePopen)

    payload = module.run_codex_json_stage(
        stage_name="draft",
        prompt="prompt",
        schema={"type": "object"},
        project_root=project_root,
        artifact_dir=artifact_dir,
        sandbox_mode="workspace-write",
        chapter=1,
        workspace_file=workspace_file,
        expected_title="旧标题",
        require_workspace_mutation=True,
    )

    trace_payload = json.loads((artifact_dir / "draft.trace.json").read_text(encoding="utf-8"))
    execution_payload = json.loads((artifact_dir / "draft.execution.json").read_text(encoding="utf-8"))

    assert payload["title"] == "新标题"
    assert trace_payload["summary"]["workspace_reads"] == 1
    assert trace_payload["summary"]["workspace_writes"] == 1
    assert trace_payload["summary"]["tools_seen"] == ["read_file", "update_file"]
    assert execution_payload["file_changed"] is True
    assert execution_payload["content_matches_file"] is True
    assert execution_payload["mutation_expected"] is True
    assert observe_calls[-1][1]["details"]["trace_summary"]["workspace_writes"] == 1



def test_summary_markdown_derives_foreshadowing_from_structured_fields():
    module = _load_module()

    markdown = module._summary_markdown(12, {
        "chapter_meta": {"hook_type": "悬念钩", "hook_strength": "strong"},
        "summary_text": "摘要",
        "bridge_line": "承接",
        "foreshadowing_notes": [],
        "foreshadowing_planted": [{"content": "井底有人提前动过封条"}],
        "foreshadowing_continued": [{"content": "赵国威继续盯住回春堂线"}],
        "foreshadowing_resolved": [{"content": "张浩栽赃线正式坐实"}],
    })

    assert "[埋设] 井底有人提前动过封条" in markdown
    assert "[延续] 赵国威继续盯住回春堂线" in markdown
    assert "[回收] 张浩栽赃线正式坐实" in markdown


def test_main_marks_task_failed_on_keyboard_interrupt(monkeypatch, tmp_path, capsys):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()
    project_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda _argv=None: SimpleNamespace(
            project_root=str(project_root),
            chapter=16,
            mode="standard",
            codex_bin=None,
            enable_debt_interest=False,
        ),
    )
    monkeypatch.setattr(module, "resolve_project_root", lambda value: Path(value))
    monkeypatch.setattr(module, "_install_interrupt_handlers", lambda _chapter: {})
    monkeypatch.setattr(module, "_restore_interrupt_handlers", lambda _handlers: None)
    monkeypatch.setattr(
        module,
        "run_write_workflow",
        lambda **_kwargs: (_ for _ in ()).throw(module.WorkflowInterrupted("收到 SIGTERM，停止测试")),
    )

    fail_calls = []
    monkeypatch.setattr(module, "fail_task", lambda project_root_arg, reason, artifacts=None: fail_calls.append((project_root_arg, reason, artifacts)))

    exit_code = module.main([])

    assert exit_code == 1
    assert fail_calls
    assert fail_calls[0][0] == project_root
    assert fail_calls[0][1] == "收到 SIGTERM，停止测试"
    assert fail_calls[0][2]["interrupted"] is True
    captured = capsys.readouterr()
    assert "❌ webnovel-write 第 16 章失败: 收到 SIGTERM，停止测试" in captured.err
    assert '"interrupted": true' in captured.out


def test_main_falls_back_to_direct_state_failure_when_fail_task_errors(monkeypatch, tmp_path, capsys):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()
    state_path = project_root / ".webnovel" / "workflow_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "current_task": {
                    "command": "webnovel-write",
                    "args": {"chapter_num": 16},
                    "status": "running",
                    "last_heartbeat": "2026-03-10T12:08:22+08:00",
                    "current_step": {
                        "id": "Step 1",
                        "name": "Context Agent",
                        "status": "running",
                    },
                    "failed_steps": [],
                },
                "history": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda _argv=None: SimpleNamespace(
            project_root=str(project_root),
            chapter=16,
            mode="standard",
            codex_bin=None,
            enable_debt_interest=False,
        ),
    )
    monkeypatch.setattr(module, "resolve_project_root", lambda value: Path(value))
    monkeypatch.setattr(module, "_install_interrupt_handlers", lambda _chapter: {})
    monkeypatch.setattr(module, "_restore_interrupt_handlers", lambda _handlers: None)
    monkeypatch.setattr(
        module,
        "run_write_workflow",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider 502")),
    )
    monkeypatch.setattr(module, "fail_task", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("workflow cli down")))

    exit_code = module.main([])

    assert exit_code == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    task = state["current_task"]
    assert task["status"] == "failed"
    assert task["failure_reason"] == "provider 502"
    assert task["current_step"] is None
    assert task["failed_steps"][-1]["id"] == "Step 1"
    captured = capsys.readouterr()
    assert "workflow fail-task 调用失败，已直接写入 failed 状态" in captured.err
    assert '"error": "provider 502"' in captured.out


def test_run_context_agent_stage_segments_requests(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setattr(module, "USE_MAIN_PROCESS_CONTEXT_DRAFT_PACKAGE", False)
    project_root = (tmp_path / "book").resolve()
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    calls = []

    payloads = {
        "context_story_spine": {
            "chapter": 9,
            "story_spine": {
                "core_task": "推进仓库线",
                "conflict": "潜入风险高",
                "must_complete": ["拿到仓库异常证据"],
                "must_not": ["不能提前揭露主使"],
                "villain_tier": "地头蛇",
                "carry_from_previous": "接住上章线索",
                "opening_suggestion": "从夜里摸到旧仓开场",
            },
        },
        "context_cast_constraints": {
            "chapter": 9,
            "cast_constraints": {
                "characters": [{"name": "林小天", "role": "执行者"}, {"name": "阿强", "role": "望风"}],
                "scene_constraints": ["主要场景限定在旧仓与后巷"],
                "time_constraints": ["必须发生在深夜一个时辰内"],
                "style_guidance": ["少解释，多动作反馈"],
            },
        },
        "context_foreshadow_plan": {
            "chapter": 9,
            "foreshadow_plan": {
                "foreshadowing": ["仓库里有人提前来过"],
                "foreshadowing_plan": {
                    "must_continue": [{"id": "fs_old", "content": "旧仓异动", "purpose": "接住上章悬念"}],
                    "planned_new": [{"content": "墙后还有第二层暗门", "plant_method": "通过脚印与回声暗示", "purpose": "下一章扩大势力线", "expected_payoff": "第10章发现暗门后的新交易线"}],
                    "forbidden_resolve": ["旧仓幕后主使"],
                },
            },
        },
        "context_reader_pull": {
            "chapter": 9,
            "reader_pull": {
                "reading_power": ["当章拿到第一份硬证据", "章末再抛更大疑点"],
                "strand_strategy": "主线70/悬念20/人物10",
                "is_transition": False,
                "hook_type": "悬念钩",
                "hook_strength": "strong",
                "micropayoffs": ["确认仓库被人动过"],
                "cool_point_pattern": "认知爽",
            },
        },
        "context_contract_core": {
            "chapter": 9,
            "contract_core": {
                "goal": "查仓库并确认是谁先一步来过",
                "obstacle": "守卫巡查与环境噪音",
                "cost": "一旦暴露会被反盯上",
                "change": "从猜测升级到掌握一条真实线索",
                "unresolved_question": "真正的主使是谁",
                "core_conflict": "继续深挖还是先撤",
                "opening_type": "危机开场",
                "emotion_pacing": "紧张递进",
                "info_density": "中高",
            },
        },
        "context_draft_package": {
            "chapter": 9,
            "draft_package": {
                "title_suggestion": "旧仓里的回声",
                "beat_sheet": ["夜入旧仓", "排查脚印", "锁定暗门", "章末钩"],
                "immutable_facts": ["药铺仓库线索来自第8章", "旧仓幕后主使本章不能揭露"],
                "forbidden": ["不能越级开打"],
                "checklist": ["接住上章", "埋新伏笔"],
                "target_words": 2200,
            },
        },
    }

    def fake_run_codex_json_stage(stage_name, **kwargs):
        calls.append((stage_name, kwargs))
        (artifact_dir / f"{stage_name}.prompt.txt").write_text(f"prompt for {stage_name}", encoding="utf-8")
        (artifact_dir / f"{stage_name}.stdout.log").write_text(f"stdout for {stage_name}", encoding="utf-8")
        (artifact_dir / f"{stage_name}.stderr.log").write_text("", encoding="utf-8")
        module.write_json(artifact_dir / f"{stage_name}.trace.json", {"stage": stage_name, "summary": {"events_captured": 1}})
        module.write_json(artifact_dir / f"{stage_name}.execution.json", {"stage": stage_name, "ok": True, "attempt": 1, "elapsed_ms": 12})
        return payloads[stage_name]

    monkeypatch.setattr(module, "run_codex_json_stage", fake_run_codex_json_stage)

    result = module.run_context_agent_stage(
        project_root=project_root,
        chapter=9,
        materials={
            "state": {
                "progress": {},
                "plot_threads": {
                    "foreshadowing": [
                        {"id": "fs_old", "content": "旧仓异动", "status": "open", "purpose": "接住上章悬念"}
                    ]
                },
            },
            "extract_context": {
                "outline": "第9章进入旧仓，确认有人提前来过。",
                "previous_summaries": ["第8章章末发现旧仓异响。"],
                "state_summary": "林小天准备夜探旧仓。",
            },
            "timeline_text": "第9章 深夜 天井巷旧仓",
        },
        artifact_dir=artifact_dir,
        codex_bin=None,
    )

    assert [name for name, _kwargs in calls] == [
        "context_story_spine",
        "context_cast_constraints",
        "context_foreshadow_plan",
        "context_reader_pull",
        "context_contract_core",
        "context_draft_package",
    ]
    assert result["task_brief"]["core_task"] == "推进仓库线"
    assert result["task_brief"]["time_constraints"] == ["必须发生在深夜一个时辰内"]
    assert result["task_brief"]["foreshadowing_plan"]["must_continue"][0]["id"] == "fs_old"
    assert result["contract_v2"]["goal"] == "查仓库并确认是谁先一步来过"
    assert result["contract_v2"]["hook_type"] == "悬念钩"
    assert result["draft_package"]["title_suggestion"] == "旧仓里的回声"
    assert (artifact_dir / "context_agent.json").is_file()
    assert (artifact_dir / "context_agent.stdout.log").is_file()
    assert (artifact_dir / "context_story_spine.input.json").is_file()
    assert "context_story_spine" in (artifact_dir / "context_agent.prompt.txt").read_text(encoding="utf-8")
    metrics_path = project_root / ".webnovel" / "observability" / "context_agent_metrics.jsonl"
    assert metrics_path.is_file()
    assert "context_contract_core" in metrics_path.read_text(encoding="utf-8")


def _build_context_segment_fixtures(chapter: int = 9):
    materials = {
        "state": {
            "progress": {},
            "plot_threads": {
                "foreshadowing": [
                    {"id": "fs_old", "content": "旧仓异动", "status": "open", "purpose": "接住上章悬念"}
                ]
            },
        },
        "extract_context": {
            "outline": "第9章进入旧仓，确认有人提前来过。",
            "previous_summaries": ["第8章章末发现旧仓异响。"],
            "state_summary": "林小天准备夜探旧仓。",
        },
        "timeline_text": "第9章 深夜 天井巷旧仓",
    }
    payloads = {
        "context_story_spine": {
            "chapter": chapter,
            "story_spine": {
                "core_task": "推进仓库线",
                "conflict": "潜入风险高",
                "must_complete": ["拿到仓库异常证据"],
                "must_not": ["不能提前揭露主使"],
                "villain_tier": "地头蛇",
                "carry_from_previous": "接住上章线索",
                "opening_suggestion": "从夜里摸到旧仓开场",
            },
        },
        "context_cast_constraints": {
            "chapter": chapter,
            "cast_constraints": {
                "characters": [{"name": "林小天", "role": "执行者"}, {"name": "阿强", "role": "望风"}],
                "scene_constraints": ["主要场景限定在旧仓与后巷"],
                "time_constraints": ["必须发生在深夜一个时辰内"],
                "style_guidance": ["少解释，多动作反馈"],
            },
        },
        "context_foreshadow_plan": {
            "chapter": chapter,
            "foreshadow_plan": {
                "foreshadowing": ["仓库里有人提前来过"],
                "foreshadowing_plan": {
                    "must_continue": [{"id": "fs_old", "content": "旧仓异动", "purpose": "接住上章悬念"}],
                    "planned_new": [{"content": "墙后还有第二层暗门", "plant_method": "通过脚印与回声暗示", "purpose": "下一章扩大势力线", "expected_payoff": "第10章发现暗门后的新交易线"}],
                    "forbidden_resolve": ["旧仓幕后主使"],
                },
            },
        },
        "context_reader_pull": {
            "chapter": chapter,
            "reader_pull": {
                "reading_power": ["当章拿到第一份硬证据", "章末再抛更大疑点"],
                "strand_strategy": "主线70/悬念20/人物10",
                "is_transition": False,
                "hook_type": "悬念钩",
                "hook_strength": "strong",
                "micropayoffs": ["确认仓库被人动过"],
                "cool_point_pattern": "认知爽",
            },
        },
        "context_contract_core": {
            "chapter": chapter,
            "contract_core": {
                "goal": "查仓库并确认是谁先一步来过",
                "obstacle": "守卫巡查与环境噪音",
                "cost": "一旦暴露会被反盯上",
                "change": "从猜测升级到掌握一条真实线索",
                "unresolved_question": "真正的主使是谁",
                "core_conflict": "继续深挖还是先撤",
                "opening_type": "危机开场",
                "emotion_pacing": "紧张递进",
                "info_density": "中高",
            },
        },
        "context_draft_package": {
            "chapter": chapter,
            "draft_package": {
                "title_suggestion": "旧仓里的回声",
                "beat_sheet": ["夜入旧仓", "排查脚印", "锁定暗门", "章末钩"],
                "immutable_facts": ["药铺仓库线索来自第8章", "旧仓幕后主使本章不能揭露"],
                "forbidden": ["不能越级开打"],
                "checklist": ["接住上章", "埋新伏笔"],
                "target_words": 2200,
            },
        },
    }
    return materials, payloads


def test_run_context_agent_stage_reuses_cached_segment_when_input_unchanged(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setattr(module, "USE_MAIN_PROCESS_CONTEXT_DRAFT_PACKAGE", False)
    project_root = (tmp_path / "book").resolve()
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    materials, payloads = _build_context_segment_fixtures(chapter=9)
    compact = module._compact_context_materials(materials, 9)
    story_spine_input = module._build_context_story_spine_input(9, compact)
    module.write_json(artifact_dir / "context_story_spine.input.json", story_spine_input)
    module.write_json(artifact_dir / "context_story_spine.json", payloads["context_story_spine"])

    calls = []

    def fake_run_codex_json_stage(stage_name, **kwargs):
        calls.append(stage_name)
        return payloads[stage_name]

    monkeypatch.setattr(module, "run_codex_json_stage", fake_run_codex_json_stage)

    result = module.run_context_agent_stage(
        project_root=project_root,
        chapter=9,
        materials=materials,
        artifact_dir=artifact_dir,
        codex_bin=None,
    )

    assert calls == [
        "context_cast_constraints",
        "context_foreshadow_plan",
        "context_reader_pull",
        "context_contract_core",
        "context_draft_package",
    ]
    assert result["task_brief"]["core_task"] == "推进仓库线"
    metrics_path = project_root / ".webnovel" / "observability" / "context_agent_metrics.jsonl"
    rows = [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cache_hits = [row for row in rows if row.get("stage") == "context_story_spine" and row.get("attempt") == 0]
    assert cache_hits


def test_run_context_agent_stage_uses_main_process_for_draft_package(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setattr(module, "USE_MAIN_PROCESS_CONTEXT_DRAFT_PACKAGE", True)
    project_root = (tmp_path / "book").resolve()
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    materials, payloads = _build_context_segment_fixtures(chapter=9)
    calls = []

    def fake_run_codex_json_stage(stage_name, **kwargs):
        calls.append(stage_name)
        if stage_name == "context_draft_package":
            raise AssertionError("draft package should be generated in main process")
        return payloads[stage_name]

    monkeypatch.setattr(module, "run_codex_json_stage", fake_run_codex_json_stage)

    result = module.run_context_agent_stage(
        project_root=project_root,
        chapter=9,
        materials=materials,
        artifact_dir=artifact_dir,
        codex_bin=None,
    )

    assert calls == [
        "context_story_spine",
        "context_cast_constraints",
        "context_foreshadow_plan",
        "context_reader_pull",
        "context_contract_core",
    ]
    assert isinstance(result["draft_package"], dict)
    assert result["draft_package"]["target_words"] >= 1200
    execution = json.loads((artifact_dir / "context_draft_package.execution.json").read_text(encoding="utf-8"))
    assert execution["source"] == "main_process"
    assert execution["success"] is True
    assert (artifact_dir / "context_draft_package.json").is_file()


def test_run_context_agent_stage_reuses_cached_context_package_when_compact_unchanged(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    materials, payloads = _build_context_segment_fixtures(chapter=9)
    compact = module._compact_context_materials(materials, 9)
    module.write_json(artifact_dir / "context.compact.json", compact)
    context_package = module._merge_context_segments(
        chapter=9,
        story_spine=payloads["context_story_spine"]["story_spine"],
        cast_constraints=payloads["context_cast_constraints"]["cast_constraints"],
        foreshadow_plan=payloads["context_foreshadow_plan"]["foreshadow_plan"],
        reader_pull=payloads["context_reader_pull"]["reader_pull"],
        contract_core=payloads["context_contract_core"]["contract_core"],
        draft_package=payloads["context_draft_package"]["draft_package"],
    )
    module.write_json(artifact_dir / "context_package.json", context_package)

    monkeypatch.setattr(
        module,
        "run_codex_json_stage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected stage call")),
    )

    result = module.run_context_agent_stage(
        project_root=project_root,
        chapter=9,
        materials=materials,
        artifact_dir=artifact_dir,
        codex_bin=None,
    )

    assert result == context_package
    assert (artifact_dir / "context_agent.json").is_file()


def test_run_context_agent_stage_invalidates_segment_cache_when_input_changes(monkeypatch, tmp_path):
    module = _load_module()
    project_root = (tmp_path / "book").resolve()
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    materials, payloads = _build_context_segment_fixtures(chapter=9)
    stale_input = {"chapter": 9, "outline": "旧输入", "previous_summaries": ["旧摘要"], "state_summary": "旧状态"}
    module.write_json(artifact_dir / "context_story_spine.input.json", stale_input)
    module.write_json(artifact_dir / "context_story_spine.json", payloads["context_story_spine"])

    calls = []

    def fake_run_codex_json_stage(stage_name, **kwargs):
        calls.append(stage_name)
        return payloads[stage_name]

    monkeypatch.setattr(module, "run_codex_json_stage", fake_run_codex_json_stage)

    result = module.run_context_agent_stage(
        project_root=project_root,
        chapter=9,
        materials=materials,
        artifact_dir=artifact_dir,
        codex_bin=None,
    )

    assert calls[0] == "context_story_spine"
    assert result["draft_package"]["title_suggestion"] == "旧仓里的回声"


def test_context_stage_inputs_fit_budget(tmp_path):
    module = _load_module()
    long_text = "旧仓" * 200
    materials = {
        "extract_context": {
            "outline": f"第17章围绕旧仓展开。{long_text}",
            "previous_summaries": [f"上章提到旧仓异动。{long_text}", f"林小天决定夜探。{long_text}"],
            "state_summary": f"当前焦点仍在旧仓与后巷。{long_text}",
        },
        "state": {
            "chapter_meta": {
                "0015": {"title": "旧铜镜会发烫", "dominant_strand": "mystery", "bridge_line": long_text},
                "0016": {"title": "井口的湿痕", "dominant_strand": "mystery", "bridge_line": long_text},
            },
            "plot_threads": {
                "foreshadowing": [
                    {"id": f"fs_{idx}", "content": f"旧仓相关伏笔{idx}{long_text}", "status": "open", "purpose": "推进旧仓线"}
                    for idx in range(12)
                ]
            },
        },
        "timeline_text": f"第17章 深夜 旧仓\n{long_text}",
        "core_entities": [
            {"id": f"entity_{idx}", "canonical_name": f"旧仓角色{idx}", "type": "角色", "tier": "核心"}
            for idx in range(20)
        ],
        "recent_appearances": [
            {"entity_id": f"entity_{idx}", "chapter": 16, "mentions": 3}
            for idx in range(20)
        ],
        "recent_reading_power": [{"chapter": 16, "overall_score": 88, "severity_counts": {"low": 2}}],
        "hook_type_stats": {"悬念钩": 3},
        "pattern_usage_stats": {"认知爽": 4},
        "debt_summary": {"open_threads": 3},
    }
    compact = module._compact_context_materials(materials, 17)
    story_spine_input = module._build_context_story_spine_input(17, compact)
    story_spine = {
        "core_task": "查清旧仓里是否有人先到一步",
        "conflict": "夜探风险高",
        "must_complete": ["确认旧仓是否被动过"],
        "must_not": ["不能直接揭露幕后黑手"],
        "carry_from_previous": "接住上章旧仓线",
        "opening_suggestion": "从摸黑进旧仓开场",
    }
    cast_input = module._build_context_cast_constraints_input(17, compact, story_spine)
    foreshadow_input = module._build_context_foreshadow_plan_input(17, compact, story_spine)
    reader_input = module._build_context_reader_pull_input(17, compact, story_spine)

    assert module._json_size_bytes(story_spine_input) <= module.CONTEXT_STAGE_INPUT_BUDGETS["context_story_spine"]
    assert module._json_size_bytes(cast_input) <= module.CONTEXT_STAGE_INPUT_BUDGETS["context_cast_constraints"]
    assert module._json_size_bytes(foreshadow_input) <= module.CONTEXT_STAGE_INPUT_BUDGETS["context_foreshadow_plan"]
    assert module._json_size_bytes(reader_input) <= module.CONTEXT_STAGE_INPUT_BUDGETS["context_reader_pull"]
    assert len(compact["open_foreshadowing"]) <= 6
    assert len(compact["core_entities"]) <= 8


def test_build_context_draft_package_input_compacts_noisy_fields():
    module = _load_module()
    noisy = "围绕“一张假合同”完成当场拆穿\n...(已截断)。。"
    task_brief = {
        "core_task": noisy * 4,
        "conflict": noisy * 4,
        "carry_from_previous": noisy * 4,
        "must_complete": [noisy, noisy, "锁定合同漏洞"],
        "must_not": [noisy, "不能扩大战场"],
        "opening_suggestion": noisy * 2,
        "characters": [{"name": "林小天", "role": noisy}, {"name": "林小天", "role": noisy}],
        "scene_constraints": [noisy],
        "time_constraints": [noisy],
        "style_guidance": [noisy],
        "foreshadowing": [noisy],
        "foreshadowing_plan": {
            "must_continue": [{"id": "fs_01", "content": noisy, "purpose": noisy}],
            "planned_new": [{"content": noisy, "plant_method": noisy, "purpose": noisy, "expected_payoff": noisy}],
            "forbidden_resolve": [noisy],
        },
        "reading_power": [noisy],
        "strand_strategy": noisy,
    }
    contract_v2 = {
        "goal": noisy * 3,
        "obstacle": noisy * 3,
        "cost": noisy * 3,
        "change": noisy * 3,
        "unresolved_question": noisy * 3,
        "core_conflict": noisy * 3,
        "opening_type": noisy,
        "emotion_pacing": noisy,
        "info_density": noisy,
        "is_transition": False,
        "hook_type": "危机钩",
        "hook_strength": "强",
        "micropayoffs": [noisy, noisy],
        "cool_point_pattern": noisy,
    }

    payload = module._build_context_draft_package_input(
        19,
        {"pattern_usage_stats": {"认知爽": 4}, "recent_reading_power": [{"chapter": 18, "overall_score": 90}]},
        task_brief,
        contract_v2,
        compact_mode=True,
    )

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "...(已截断)" not in serialized
    assert "。。" not in serialized
    assert len(payload["task_brief"]["must_complete"]) == 2
    assert payload["task_brief"]["characters"][0]["name"] == "林小天"
    assert payload["task_brief"]["characters"][0]["role"].startswith("围绕“一张假合同”完成当场拆穿")
    assert payload["contract_v2"]["hook_type"] == "危机钩"


def test_build_context_draft_package_fallback_cleans_truncation_marker():
    module = _load_module()
    task_brief = {
        "core_task": "围绕“一张假合同”完成当场拆穿\n...(已截断)",
        "conflict": "对方拿出手续齐全的合同\n...(已截断)。。",
        "carry_from_previous": "接住上章线索\n...(已截断)",
        "opening_suggestion": "签前最后核对\n...(已截断)",
        "must_complete": ["阻断签署\n...(已截断)", "锁定漏洞"],
        "must_not": ["不能无代价秒赢\n...(已截断)"],
        "time_constraints": ["三小时内闭环\n...(已截断)"],
        "scene_constraints": ["现场核验\n...(已截断)"],
        "reading_power": ["时间压力\n...(已截断)"],
    }
    contract_v2 = {
        "goal": "阻断签署\n...(已截断)",
        "obstacle": "对方造假流程完整\n...(已截断)",
        "change": "从被动到主动\n...(已截断)",
        "unresolved_question": "对手后手是什么\n...(已截断)",
        "hook_type": "危机钩",
        "hook_strength": "强",
        "micropayoffs": ["当场卡住流程\n...(已截断)"],
    }

    fallback = module._build_context_draft_package_fallback(19, task_brief, contract_v2)
    serialized = json.dumps(fallback, ensure_ascii=False)
    assert "...(已截断)" not in serialized
    assert "。。" not in serialized
    assert fallback["title_suggestion"]
    assert fallback["target_words"] >= 1200


def test_validate_context_segments_rejects_unknown_foreshadow_id(tmp_path):
    module = _load_module()
    compact = {
        "timeline_anchor_digest": "第9章 深夜 旧仓",
        "open_foreshadowing": [{"id": "fs_real", "content": "旧仓异动"}],
    }
    context_package = {
        "chapter": 9,
        "task_brief": {
            "core_task": "推进旧仓线",
            "conflict": "潜入风险高",
            "carry_from_previous": "接上章",
            "characters": [{"name": "林小天"}],
            "scene_constraints": ["场景限定在旧仓"],
            "time_constraints": ["必须发生在深夜"],
            "foreshadowing": ["旧仓异动"],
            "foreshadowing_plan": {
                "must_continue": [{"id": "fs_missing", "content": "不存在的伏笔", "purpose": "测试"}],
                "planned_new": [],
                "forbidden_resolve": [],
            },
            "reading_power": ["拿到线索"],
            "strand_strategy": "主线优先",
        },
        "contract_v2": {
            "goal": "夜探旧仓",
            "obstacle": "守卫巡逻",
            "cost": "暴露风险",
            "change": "拿到线索",
            "unresolved_question": "是谁先来过",
            "core_conflict": "继续深入还是撤退",
            "opening_type": "危机开场",
            "emotion_pacing": "紧张",
            "info_density": "中高",
            "is_transition": False,
            "hook_type": "悬念钩",
            "hook_strength": "strong",
            "micropayoffs": ["确认旧仓被动过"],
            "cool_point_pattern": "认知爽",
        },
        "draft_package": {
            "title_suggestion": "旧仓里的回声",
            "beat_sheet": ["开场", "推进", "章末钩"],
            "immutable_facts": ["旧仓线已在前章出现"],
            "forbidden": ["不能揭底"],
            "checklist": ["接住上章"],
            "target_words": 2200,
        },
    }

    with pytest.raises(RuntimeError, match="不存在的伏笔 id"):
        module._validate_context_segments(9, compact, context_package)


def test_normalize_context_foreshadowing_plan_removes_forbidden_conflicts():
    module = _load_module()
    context_package = {
        "chapter": 19,
        "task_brief": {
            "foreshadowing_plan": {
                "must_continue": [
                    {"id": "fs_contract_gap", "content": "合同授权链有断点", "purpose": "持续推进合同线"},
                    {"id": "fs_rooftop", "content": "天台人影仍在盯梢", "purpose": "持续推进监视线"},
                ],
                "planned_new": [],
                "forbidden_resolve": [
                    "fs_contract_gap",
                    "合同授权链有断点",
                    "幕后主使身份",
                    "幕后主使身份",
                ],
            }
        },
    }

    result = module._normalize_context_foreshadowing_plan(context_package)
    plan = context_package["task_brief"]["foreshadowing_plan"]

    assert result["removed_conflicts"] == 2
    assert plan["forbidden_resolve"] == ["幕后主使身份"]
