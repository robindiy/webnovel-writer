#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
from pathlib import Path

import pytest


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_runner_module():
    _ensure_scripts_on_path()
    import review_agents_runner as module

    return module


def _write_chapter(project_root: Path, chapter: int, text: str) -> Path:
    chapter_dir = project_root / "正文" / "第1卷"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    chapter_file = chapter_dir / f"第{chapter:03d}章.md"
    chapter_file.write_text(text, encoding="utf-8")
    return chapter_file


def test_select_checkers_auto_routes_optional_checkers():
    module = _load_runner_module()

    context_payload = {
        "outline": "章末未闭合问题: 他能不能反杀\nStrand: Quest\n爽点: 打脸",
        "reader_signal": {"review_trend": {"overall_avg": 76}},
        "writing_guidance": {"guidance_items": ["保持追读力"], "checklist": []},
    }

    selected = module.select_checkers(
        chapter=12,
        chapter_text="主角在巷口完成反杀，顺手打脸了反派。",
        context_payload=context_payload,
        mode="auto",
    )

    assert selected[:3] == module.CORE_CHECKERS
    assert "reader-pull-checker" in selected
    assert "high-point-checker" in selected
    assert "pacing-checker" in selected


def test_validate_checker_payload_rejects_missing_contract_fields():
    module = _load_runner_module()

    with pytest.raises(ValueError):
        module.validate_checker_payload(
            {
                "agent": "consistency-checker",
                "chapter": 1,
                "overall_score": 88,
                "pass": True,
                "metrics": {},
                "summary": "ok",
            },
            expected_agent="consistency-checker",
            chapter=1,
        )



def test_build_checker_prompt_lists_target_files_and_allows_read_only_tools(tmp_path):
    module = _load_runner_module()

    project_root = tmp_path
    artifact_dir = project_root / ".webnovel" / "reviews" / "ch0002"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")
    (artifact_dir / "context.json").write_text("{}", encoding="utf-8")
    outline_dir = project_root / "大纲"
    outline_dir.mkdir(parents=True, exist_ok=True)
    (outline_dir / "第1卷-详细大纲.md").write_text("### 第2章：测试\n主线推进", encoding="utf-8")
    setting_dir = project_root / "设定集"
    setting_dir.mkdir(parents=True, exist_ok=True)
    (setting_dir / "力量体系.md").write_text("练气不可外放灵气", encoding="utf-8")
    (setting_dir / "主角卡.md").write_text("林小天谨慎记仇", encoding="utf-8")
    chapter1 = _write_chapter(project_root, 1, "# 第1章\n上一章内容")
    chapter2 = _write_chapter(project_root, 2, "# 第2章\n本章内容")
    summaries_dir = project_root / ".webnovel" / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    (summaries_dir / "ch0001.md").write_text("## 剧情摘要\n上一章摘要", encoding="utf-8")

    prompt = module.build_checker_prompt(
        agent="consistency-checker",
        chapter=2,
        chapter_file=chapter2,
        context_payload={
            "outline": "主线推进，检验设定回扣",
            "previous_summaries": ["### 第1章摘要\n上一章摘要"],
            "state_summary": "主角仍在旧巷调查",
        },
        chapter_text=chapter2.read_text(encoding="utf-8"),
        project_root=project_root,
        artifact_dir=artifact_dir,
    )

    assert "source-backed review" in prompt
    assert "先读这些文件（required）" in prompt
    assert ".webnovel/reviews/ch0002/context.json" in prompt
    assert ".webnovel/state.json" in prompt
    assert "大纲/第1卷-详细大纲.md" in prompt
    assert "设定集/力量体系.md" in prompt
    assert module._display_path(chapter1, project_root) in prompt
    assert "允许调用当前 Codex 子进程可用的只读工具" in prompt
    assert "severity 只能使用 critical/high/medium/low/minor" in prompt
    assert "不要调用工具" not in prompt


def test_validate_checker_payload_accepts_minor_and_aggregate_preserves_it(tmp_path):
    module = _load_runner_module()

    payload = module.validate_checker_payload(
        {
            "agent": "reader-pull-checker",
            "chapter": 2,
            "overall_score": 87,
            "pass": True,
            "issues": [
                {
                    "id": "HOOK-9",
                    "type": "TAIL_POLISH",
                    "severity": "minor",
                    "location": "章末",
                    "description": "章末最后一句还能更利落。",
                    "suggestion": "把解释性尾句再压短半拍。",
                    "can_override": True,
                }
            ],
            "metrics": {},
            "summary": "ok",
        },
        expected_agent="reader-pull-checker",
        chapter=2,
    )

    aggregate = module.aggregate_checker_results(
        chapter=2,
        chapter_file=tmp_path / "正文" / "第1卷" / "第002章.md",
        selected_checkers=["reader-pull-checker"],
        results=[payload],
    )
    report = module.render_chapter_report(aggregate, tmp_path, tmp_path / "report.md")
    range_report = module.render_range_report(
        module.build_range_summary([aggregate], [tmp_path / "report.md"]),
        [tmp_path / "report.md"],
    )

    assert aggregate["severity_counts"]["minor"] == 1
    assert aggregate["checkers"]["reader-pull-checker"]["minor"] == 1
    assert "| minor | 1 |" in report
    assert "| Checker | 分数 | critical | high | medium | low | minor | 结论 |" in report
    assert "| chapter | score | critical | high | medium | low | minor | selected_checkers | report_file |" in range_report


def test_build_codex_exec_command_supports_workspace_write():
    module = _load_runner_module()

    command = module.build_codex_exec_command(
        codex_bin="/usr/bin/codex",
        project_root=Path("/tmp/book"),
        output_schema_path=Path("/tmp/schema.json"),
        output_path=Path("/tmp/output.json"),
        sandbox_mode="workspace-write",
    )

    assert "-s" in command
    assert command[command.index("-s") + 1] == "workspace-write"


def test_run_checker_subprocess_stops_after_turn_completed_without_waiting_for_exit(tmp_path, monkeypatch):
    module = _load_runner_module()

    project_root = tmp_path
    artifact_dir = project_root / ".webnovel" / "reviews" / "ch0001"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    chapter_file = project_root / "正文" / "第1卷" / "第001章.md"
    chapter_file.parent.mkdir(parents=True, exist_ok=True)
    chapter_file.write_text("正文", encoding="utf-8")
    context_file = artifact_dir / "context.json"
    context_file.write_text("{}", encoding="utf-8")

    class _FakeStdin:
        def __init__(self):
            self.buffer = []

        def write(self, text):
            self.buffer.append(text)

        def close(self):
            return None

    class _FakeReadable:
        def __init__(self, lines):
            self._lines = list(lines)

        def readline(self):
            if not self._lines:
                return ""
            return self._lines.pop(0)

    class _FakePopen:
        def __init__(self, cmd, stdin, stdout, stderr, text, bufsize):
            output_path = Path(cmd[cmd.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {
                        "agent": "consistency-checker",
                        "chapter": 1,
                        "overall_score": 88,
                        "pass": True,
                        "issues": [],
                        "metrics": {"power_violations": 0},
                        "summary": "ok",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.stdin = _FakeStdin()
            self.stdout = _FakeReadable(
                [
                    '{"type":"thread.started","thread_id":"t1"}\n',
                    '{"type":"turn.started"}\n',
                    '{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"{\\"agent\\":\\"consistency-checker\\"}"}}\n',
                    '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n',
                ]
            )
            self.stderr = _FakeReadable(["warn line\n"])
            self.returncode = None
            self.terminated = False

        def poll(self):
            return None if not self.terminated else self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            if self.returncode is None:
                self.returncode = -15
            return self.returncode

        def kill(self):
            self.terminated = True
            self.returncode = -9

    monkeypatch.setattr(module.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(module, "build_checker_prompt", lambda **_kwargs: "prompt")

    result = module.run_checker_subprocess(
        codex_bin="/usr/bin/codex",
        project_root=project_root,
        chapter=1,
        agent="consistency-checker",
        chapter_file=chapter_file,
        context_payload={},
        chapter_text="正文",
        artifact_dir=artifact_dir,
    )

    assert result.payload["agent"] == "consistency-checker"
    assert result.payload["overall_score"] == 88
    assert result.elapsed_ms >= 0


def test_run_checker_subprocess_fast_fails_after_retryable_provider_errors(tmp_path, monkeypatch):
    module = _load_runner_module()

    project_root = tmp_path
    artifact_dir = project_root / ".webnovel" / "reviews" / "ch0001"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    chapter_file = project_root / "正文" / "第1卷" / "第001章.md"
    chapter_file.parent.mkdir(parents=True, exist_ok=True)
    chapter_file.write_text("正文", encoding="utf-8")

    class _FakeStdin:
        def write(self, _text):
            return None

        def close(self):
            return None

    class _FakeReadable:
        def __init__(self, lines):
            self._lines = list(lines)

        def readline(self):
            if not self._lines:
                return ""
            return self._lines.pop(0)

    class _FakePopen:
        def __init__(self, *_args, **_kwargs):
            self.stdin = _FakeStdin()
            self.stdout = _FakeReadable(
                [
                    '{"type":"thread.started","thread_id":"t1"}\n',
                    '{"type":"turn.started"}\n',
                    '{"type":"error","message":"Reconnecting... 1/30 (unexpected status 502 Bad Gateway)"}\n',
                    '{"type":"error","message":"Reconnecting... 2/30 (unexpected status 502 Bad Gateway)"}\n',
                ]
            )
            self.stderr = _FakeReadable([])
            self.returncode = None
            self.terminated = False

        def poll(self):
            return None if not self.terminated else self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            if self.returncode is None:
                self.returncode = -15
            return self.returncode

        def kill(self):
            self.terminated = True
            self.returncode = -9

    monkeypatch.setattr(module.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(module, "build_checker_prompt", lambda **_kwargs: "prompt")
    monkeypatch.setenv("WEBNOVEL_REVIEW_CHILD_FAST_FAIL_ERROR_THRESHOLD", "2")

    with pytest.raises(RuntimeError, match="连续错误 2 次后快速失败"):
        module.run_checker_subprocess(
            codex_bin="/usr/bin/codex",
            project_root=project_root,
            chapter=1,
            agent="consistency-checker",
            chapter_file=chapter_file,
            context_payload={},
            chapter_text="正文",
            artifact_dir=artifact_dir,
        )


def test_review_single_chapter_writes_aggregate_and_report(tmp_path, monkeypatch):
    module = _load_runner_module()

    project_root = tmp_path
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")
    chapter_file = _write_chapter(project_root, 1, "# 第1章\n林小天硬刚张浩，最后当场打脸。")

    monkeypatch.setattr(module, "resolve_project_root", lambda raw: Path(raw))
    monkeypatch.setattr(
        module,
        "build_chapter_context_payload",
        lambda root, chapter: {
            "outline": "章末未闭合问题: 废井会不会再次发光\nStrand: Quest\n爽点: 打脸",
            "reader_signal": {"review_trend": {"overall_avg": 78}},
            "writing_guidance": {"guidance_items": ["保持追读力"], "checklist": []},
        },
    )
    monkeypatch.setattr(module, "resolve_codex_executable", lambda explicit=None: "/usr/bin/codex")

    def _fake_checker(*, agent, artifact_dir, **_kwargs):
        checker_dir = artifact_dir / "checkers"
        checker_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "agent": agent,
            "chapter": 1,
            "overall_score": {
                "consistency-checker": 91,
                "continuity-checker": 86,
                "ooc-checker": 88,
                "reader-pull-checker": 90,
                "high-point-checker": 84,
                "pacing-checker": 82,
            }[agent],
            "pass": True,
            "issues": [],
            "metrics": {"sample": True},
            "summary": f"{agent} done",
        }
        if agent == "continuity-checker":
            payload["issues"] = [
                {
                    "id": "CONT-1",
                    "type": "THREAD_GAP",
                    "severity": "medium",
                    "location": "第3段",
                    "description": "废井线索还不够具体",
                    "suggestion": "补一个可验证的异常细节",
                    "can_override": False,
                }
            ]
        if agent == "reader-pull-checker":
            payload["issues"] = [
                {
                    "id": "HOOK-1",
                    "type": "HOOK_SOFT",
                    "severity": "low",
                    "location": "章末",
                    "description": "章末悬念还可以更尖",
                    "suggestion": "把废井异象提前半拍抛出",
                    "can_override": True,
                }
            ]
        if agent == "high-point-checker":
            payload["issues"] = [
                {
                    "id": "HIGH-1",
                    "type": "REACTION_POLISH",
                    "severity": "minor",
                    "location": "章中",
                    "description": "围观反馈再多一个动作细节会更有层次。",
                    "suggestion": "补一笔旁观者反应，抬高爽点反馈。",
                    "can_override": True,
                }
            ]
        (checker_dir / f"{agent}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return module.CheckerRunResult(agent=agent, payload=payload, elapsed_ms=12)

    saved_metrics = {}
    sync_calls = []

    monkeypatch.setattr(module, "run_checker_subprocess", _fake_checker)
    monkeypatch.setattr(module, "save_review_metrics", lambda root, payload: saved_metrics.setdefault("payload", payload))
    monkeypatch.setattr(
        module,
        "sync_chapter_data_after_review",
        lambda project_root, chapter: sync_calls.append((project_root, chapter)) or {"chapters_synced": 1, "elapsed_ms": 9},
    )

    result = module.review_single_chapter(
        project_root=project_root,
        chapter=1,
        chapter_file=Path("正文/第1卷/第001章.md"),
        mode="auto",
        max_parallel=2,
    )

    aggregate_path = project_root / ".webnovel" / "reviews" / "ch0001" / "aggregate.json"
    report_path = project_root / "审查报告" / "第1-1章审查报告.md"
    observability_path = project_root / ".webnovel" / "observability" / "review_agent_timing.jsonl"

    assert aggregate_path.exists()
    assert report_path.exists()
    assert observability_path.exists()
    assert result["selected_checkers"] == [
        "consistency-checker",
        "continuity-checker",
        "ooc-checker",
        "reader-pull-checker",
        "high-point-checker",
        "pacing-checker",
    ]
    assert result["severity_counts"]["medium"] == 1
    assert result["severity_counts"]["low"] == 1
    assert result["severity_counts"]["minor"] == 1
    assert "issues" in result and len(result["issues"]) == 3
    assert saved_metrics["payload"]["report_file"] == "审查报告/第1-1章审查报告.md"
    assert "selected_checkers=" in saved_metrics["payload"]["notes"]
    assert sync_calls == [(project_root, 1)]
    assert result["post_review_sync"]["success"] is True


def test_review_single_chapter_skips_sync_when_review_not_passed(tmp_path, monkeypatch):
    module = _load_runner_module()

    project_root = tmp_path
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")
    _write_chapter(project_root, 1, "# 第1章\n林小天忽然无理由公开了系统秘密。")

    monkeypatch.setattr(module, "resolve_project_root", lambda raw: Path(raw))
    monkeypatch.setattr(
        module,
        "build_chapter_context_payload",
        lambda root, chapter: {
            "outline": "主角仍应隐藏异常能力",
            "reader_signal": {"review_trend": {"overall_avg": 78}},
            "writing_guidance": {"guidance_items": ["保持设定一致"], "checklist": []},
        },
    )
    monkeypatch.setattr(module, "resolve_codex_executable", lambda explicit=None: "/usr/bin/codex")

    sync_calls = []

    def _fake_checker(*, agent, artifact_dir, **_kwargs):
        checker_dir = artifact_dir / "checkers"
        checker_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "agent": agent,
            "chapter": 1,
            "overall_score": 60 if agent == "consistency-checker" else 82,
            "pass": False if agent == "consistency-checker" else True,
            "issues": [],
            "metrics": {},
            "summary": f"{agent} done",
        }
        if agent == "consistency-checker":
            payload["issues"] = [
                {
                    "id": "CONS-1",
                    "type": "SETTING_CONFLICT",
                    "severity": "high",
                    "location": "第2段",
                    "description": "主角在无铺垫情况下公开了系统秘密",
                    "suggestion": "恢复隐藏能力约束，重写该段冲突表达",
                    "can_override": False,
                }
            ]
        (checker_dir / f"{agent}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return module.CheckerRunResult(agent=agent, payload=payload, elapsed_ms=10)

    monkeypatch.setattr(module, "run_checker_subprocess", _fake_checker)
    monkeypatch.setattr(module, "save_review_metrics", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "sync_chapter_data_after_review",
        lambda project_root, chapter: sync_calls.append((project_root, chapter)) or {"chapters_synced": 1},
    )

    result = module.review_single_chapter(
        project_root=project_root,
        chapter=1,
        mode="minimal",
        max_parallel=1,
    )

    assert result["pass"] is False
    assert sync_calls == []
    assert result["post_review_sync"]["attempted"] is False
    assert result["post_review_sync"]["reason"] == "review_not_passed"


def test_review_single_chapter_falls_back_to_aggregate_runner(tmp_path, monkeypatch):
    module = _load_runner_module()

    project_root = tmp_path
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")
    chapter_file = _write_chapter(project_root, 1, "# 第1章\n林小天在巷口听到井里传来第二次异响。")

    monkeypatch.setattr(module, "resolve_project_root", lambda raw: Path(raw))
    monkeypatch.setattr(
        module,
        "build_chapter_context_payload",
        lambda root, chapter: {
            "outline": "章末未闭合问题: 井里究竟是什么",
            "previous_summaries": ["第0章摘要"],
            "state_summary": "当前主角状态稳定",
        },
    )
    monkeypatch.setattr(module, "resolve_codex_executable", lambda explicit=None: "/usr/bin/codex")
    monkeypatch.setattr(module, "run_checker_subprocess", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("child timeout")))
    monkeypatch.setattr(
        module,
        "run_aggregate_fallback",
        lambda **_kwargs: [
            {
                "agent": "consistency-checker",
                "chapter": 1,
                "overall_score": 82,
                "pass": True,
                "issues": [],
                "metrics": {},
                "summary": "ok",
            },
            {
                "agent": "continuity-checker",
                "chapter": 1,
                "overall_score": 83,
                "pass": True,
                "issues": [],
                "metrics": {},
                "summary": "ok",
            },
            {
                "agent": "ooc-checker",
                "chapter": 1,
                "overall_score": 84,
                "pass": True,
                "issues": [],
                "metrics": {},
                "summary": "ok",
            },
            {
                "agent": "reader-pull-checker",
                "chapter": 1,
                "overall_score": 85,
                "pass": True,
                "issues": [],
                "metrics": {},
                "summary": "ok",
            },
            {
                "agent": "high-point-checker",
                "chapter": 1,
                "overall_score": 80,
                "pass": True,
                "issues": [],
                "metrics": {},
                "summary": "ok",
            },
            {
                "agent": "pacing-checker",
                "chapter": 1,
                "overall_score": 81,
                "pass": True,
                "issues": [],
                "metrics": {},
                "summary": "ok",
            },
        ],
    )
    monkeypatch.setattr(module, "save_review_metrics", lambda *_args, **_kwargs: None)

    result = module.review_single_chapter(
        project_root=project_root,
        chapter=1,
        chapter_file=Path("正文/第1卷/第001章.md"),
        mode="full",
    )

    assert result["selected_checkers"] == [
        "consistency-checker",
        "continuity-checker",
        "ooc-checker",
        "reader-pull-checker",
        "high-point-checker",
        "pacing-checker",
    ]
    assert result["overall_score"] == 82.5


def test_review_single_chapter_stops_after_first_failure_and_uses_local_degraded_fallback(tmp_path, monkeypatch):
    module = _load_runner_module()

    project_root = tmp_path
    (project_root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (project_root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")
    chapter_file = _write_chapter(project_root, 1, "# 第1章\n林小天回到旧巷，发现废井旁的石栏上多了一道新裂痕。")

    monkeypatch.setattr(module, "resolve_project_root", lambda raw: Path(raw))
    monkeypatch.setattr(
        module,
        "build_chapter_context_payload",
        lambda root, chapter: {
            "outline": "章末未闭合问题: 废井异响究竟来自哪里",
            "previous_summaries": ["林小天刚刚被迫接下一单怪活。"],
            "state_summary": "主角尚未公开异常能力",
        },
    )
    monkeypatch.setattr(module, "resolve_codex_executable", lambda explicit=None: "/usr/bin/codex")

    call_order = []

    def _fake_checker(*, agent, **_kwargs):
        call_order.append(agent)
        if agent == "consistency-checker":
            raise RuntimeError("child timeout")
        payload = {
            "agent": agent,
            "chapter": 1,
            "overall_score": 88,
            "pass": True,
            "issues": [],
            "metrics": {},
            "summary": "ok",
        }
        return module.CheckerRunResult(agent=agent, payload=payload, elapsed_ms=8)

    monkeypatch.setattr(module, "run_checker_subprocess", _fake_checker)
    monkeypatch.setattr(module, "run_aggregate_fallback", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("fallback down")))
    monkeypatch.setattr(module, "save_review_metrics", lambda *_args, **_kwargs: None)

    result = module.review_single_chapter(
        project_root=project_root,
        chapter=1,
        chapter_file=Path("正文/第1卷/第001章.md"),
        mode="minimal",
        max_parallel=1,
    )

    aggregate_path = project_root / ".webnovel" / "reviews" / "ch0001" / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))

    assert call_order == ["consistency-checker"]
    assert result["execution_mode"] == "degraded_local"
    assert aggregate["execution_mode"] == "degraded_local"
    assert "failure_reasons" in aggregate
    assert (project_root / ".webnovel" / "reviews" / "ch0001" / "checkers" / "continuity-checker.json").exists()
    assert (project_root / ".webnovel" / "reviews" / "ch0001" / "checkers" / "ooc-checker.json").exists()


def test_unified_cli_forwards_review_runner(monkeypatch, tmp_path):
    _ensure_scripts_on_path()
    import data_modules.webnovel as module

    calls = {}
    monkeypatch.setattr(module, "_resolve_root", lambda _raw: tmp_path)
    
    def _fake_run_script(script, argv):
        calls["call"] = (script, list(argv))
        return 0

    monkeypatch.setattr(module, "_run_script", _fake_run_script)
    monkeypatch.setattr(module.sys, "argv", ["webnovel.py", "--project-root", str(tmp_path), "review", "--chapter", "1"])

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 0
    assert calls["call"][0] == "review_agents_runner.py"
    assert calls["call"][1][:2] == ["--project-root", str(tmp_path)]
    assert "--chapter" in calls["call"][1]


def test_build_codex_exec_command_inherits_provider_retries_by_default(monkeypatch):
    module = _load_runner_module()

    monkeypatch.setattr(module, "resolve_active_model_provider_name", lambda: "gmn")
    monkeypatch.delenv("WEBNOVEL_REVIEW_CHILD_REQUEST_MAX_RETRIES", raising=False)
    monkeypatch.delenv("WEBNOVEL_REVIEW_CHILD_STREAM_MAX_RETRIES", raising=False)
    monkeypatch.delenv("WEBNOVEL_REVIEW_CHILD_STREAM_IDLE_TIMEOUT_MS", raising=False)

    command = module.build_codex_exec_command(
        codex_bin="/usr/bin/codex",
        project_root=Path("/tmp/book"),
        output_schema_path=Path("/tmp/schema.json"),
        output_path=Path("/tmp/output.json"),
        sandbox_mode="read-only",
    )

    assert all("model_providers.gmn.request_max_retries=" not in item for item in command)
    assert all("model_providers.gmn.stream_max_retries=" not in item for item in command)
    assert all("model_providers.gmn.stream_idle_timeout_ms=" not in item for item in command)


def test_build_codex_exec_command_supports_explicit_provider_retry_overrides(monkeypatch):
    module = _load_runner_module()

    monkeypatch.setattr(module, "resolve_active_model_provider_name", lambda: "gmn")
    monkeypatch.setenv("WEBNOVEL_REVIEW_CHILD_REQUEST_MAX_RETRIES", "8")
    monkeypatch.setenv("WEBNOVEL_REVIEW_CHILD_STREAM_MAX_RETRIES", "30")
    monkeypatch.setenv("WEBNOVEL_REVIEW_CHILD_STREAM_IDLE_TIMEOUT_MS", "300000")

    command = module.build_codex_exec_command(
        codex_bin="/usr/bin/codex",
        project_root=Path("/tmp/book"),
        output_schema_path=Path("/tmp/schema.json"),
        output_path=Path("/tmp/output.json"),
        sandbox_mode="read-only",
    )

    assert f"model_providers.gmn.request_max_retries=8" in command
    assert f"model_providers.gmn.stream_max_retries=30" in command
    assert f"model_providers.gmn.stream_idle_timeout_ms=300000" in command
