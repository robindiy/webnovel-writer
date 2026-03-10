#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import json
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
    project_root = (tmp_path / "book").resolve()
    artifact_dir = project_root / ".webnovel" / "write_workflow" / "ch0009"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    calls = []

    payloads = {
        "context_task_brief": {
            "chapter": 9,
            "task_brief": {
                "core_task": "推进仓库线",
                "conflict": "潜入风险高",
                "carry_from_previous": "接住上章线索",
                "characters": [],
                "scene_constraints": ["夜晚进入旧仓"],
                "foreshadowing": ["仓库里有人提前来过"],
                "foreshadowing_plan": {"must_continue": [], "planned_new": [], "forbidden_resolve": []},
                "reading_power": ["新线索落地"],
            },
        },
        "context_contract_v2": {
            "chapter": 9,
            "contract_v2": {
                "goal": "查仓库",
                "obstacle": "守卫巡查",
                "cost": "暴露风险",
                "change": "锁定接货人",
                "unresolved_question": "真正的主使是谁",
                "core_conflict": "冒险潜入还是先退",
                "opening_type": "危机开场",
                "emotion_pacing": "紧张",
                "info_density": "中高",
                "is_transition": False,
                "hook_type": "悬念钩",
                "hook_strength": "strong",
                "micropayoffs": ["拿到新证据"],
            },
        },
        "context_draft_package": {
            "chapter": 9,
            "draft_package": {
                "title_suggestion": "旧仓里的回声",
                "beat_sheet": ["开场","推进","发现","章末钩"],
                "immutable_facts": ["药铺仓库线索来自第8章"],
                "forbidden": ["不能越级"],
                "checklist": ["接住上章"],
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
        module.write_json(artifact_dir / f"{stage_name}.execution.json", {"stage": stage_name, "ok": True})
        return payloads[stage_name]

    monkeypatch.setattr(module, "run_codex_json_stage", fake_run_codex_json_stage)

    result = module.run_context_agent_stage(
        project_root=project_root,
        chapter=9,
        materials={"state": {"progress": {}}},
        artifact_dir=artifact_dir,
        codex_bin=None,
    )

    assert [name for name, _kwargs in calls] == ["context_task_brief", "context_contract_v2", "context_draft_package"]
    assert result["task_brief"]["core_task"] == "推进仓库线"
    assert result["contract_v2"]["goal"] == "查仓库"
    assert result["draft_package"]["title_suggestion"] == "旧仓里的回声"
    assert (artifact_dir / "context_agent.json").is_file()
    assert (artifact_dir / "context_agent.stdout.log").is_file()
    assert "context_task_brief" in (artifact_dir / "context_agent.prompt.txt").read_text(encoding="utf-8")
