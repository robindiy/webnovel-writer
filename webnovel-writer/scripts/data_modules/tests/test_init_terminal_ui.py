#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import builtins
import sys
from pathlib import Path


def _ensure_scripts_on_path() -> None:
    scripts_dir = Path(__file__).resolve().parents[2]
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def _load_module():
    _ensure_scripts_on_path()
    import init_terminal_ui as module

    return module


class _FakeIO:
    def __init__(self):
        self.shown_steps = []
        self.ask_text_calls = []
        self.ask_text_payloads = []
        self.choose_calls = []
        self.choose_payloads = []
        self.confirm_calls = []
        self.confirm_payloads = []
        self.summary_payloads = []
        self.post_init_payloads = []
        self.text_answers = {
            "project_title": "天道就是我",
            "story_scale": "200万字",
            "protagonist_name": "林渊",
            "golden_finger_name": "天道残片",
            "factions": "朝廷、宗门与黑市三方争夺灵矿命脉",
            "social_class_resource": "上层修士垄断刻印资源，凡人只能献祭换取余烬",
            "creative_package_custom_direction": "想写规则会吞噬城市秩序，但主角必须靠付出记忆来修补它",
        }
        self.choice_answers = {
            "genre_category": "玄幻修仙类",
            "genre_primary": "修仙",
            "genre_secondary": "系统流",
            "one_liner": "凡人流：主角资质平平，靠算计、谨慎和金手指逆袭。",
            "core_conflict": "资源争夺，小人陷害。",
            "target_reader": "男频",
            "platform": "起点",
            "protagonist_desire": "长生",
            "protagonist_flaw": "傲慢",
            "protagonist_structure": "单主角",
            "heroine_config": "无",
            "protagonist_archetype": "苟道流",
            "antagonist_mirror": "宿命之敌：与你互为镜像，深层羁绊。",
            "golden_finger_type": "系统流",
            "golden_finger_style": "克制",
            "gf_visibility": "半明牌",
            "gf_irreversible_cost": "反噬/失控",
            "growth_pacing": "中速",
            "world_scale": "多界",
            "power_system_type": "传统修仙",
            "factions": "宗门/学院",
        }
        self.confirm_answers = {
            "include_secondary_genre": True,
            "final_confirm": True,
            "rag_env_modify": False,
        }

    def show_step(self, step_id, title):
        self.shown_steps.append((step_id, title))

    def ask_text(self, field_key, label, prompt, default=None):
        self.ask_text_calls.append(field_key)
        self.ask_text_payloads.append(
            {"field_key": field_key, "label": label, "prompt": prompt, "default": default}
        )
        return self.text_answers[field_key]

    def choose(self, field_key, label, prompt, options, allow_skip=False):
        self.choose_calls.append(field_key)
        self.choose_payloads.append(
            {
                "field_key": field_key,
                "label": label,
                "prompt": prompt,
                "options": list(options),
                "allow_skip": allow_skip,
            }
        )
        answer = self.choice_answers[field_key]
        if isinstance(answer, list):
            if not answer:
                raise AssertionError(f"no choice answer left for {field_key}")
            return answer.pop(0)
        return answer

    def confirm(self, field_key, prompt, default=False, yes_label="确认", no_label="返回修改"):
        self.confirm_calls.append(field_key)
        self.confirm_payloads.append(
            {
                "field_key": field_key,
                "prompt": prompt,
                "default": default,
                "yes_label": yes_label,
                "no_label": no_label,
            }
        )
        answer = self.confirm_answers[field_key]
        if isinstance(answer, list):
            if not answer:
                raise AssertionError(f"no confirm answer left for {field_key}")
            return answer.pop(0)
        return answer

    def show_summary(self, _summary):
        self.summary_payloads.append(_summary)
        return None

    def show_post_init_handoff(self, project_dir, command, copied):
        self.post_init_payloads.append(
            {
                "project_dir": str(project_dir),
                "command": command,
                "copied": copied,
            }
        )


def test_init_wizard_collects_in_source_order(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()

    monkeypatch.setattr(
        module.InitWizard,
        "_build_creative_packages",
        lambda self: [
            {
                "id": "pkg-1",
                "one_liner": "修仙者发现自己是天道故障修复程序。",
                "anti_trope": "金手指有代价且不可逆",
                "hard_constraints": ["不能直接杀人", "每次升级都要失去记忆"],
                "opening_hook": "主角被逐出宗门当天，天道面板在脑海点亮。",
                "score": {"total": 42},
            },
            {
                "id": "pkg-2",
                "one_liner": "修仙世界的系统宿主必须彼此猎杀。",
                "anti_trope": "金手指被多人共享",
                "hard_constraints": ["系统宿主不能结盟", "每次胜利都暴露位置"],
                "opening_hook": "主角第一次签到，系统广播了他的坐标。",
                "score": {"total": 38},
            },
        ],
    )

    fake_io.choice_answers["creative_package"] = "pkg-1"
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)

    result = wizard.collect()

    assert [step_id for step_id, _ in fake_io.shown_steps] == [
        "Step 1",
        "Step 2",
        "Step 3",
        "Step 4",
        "Step 5",
        "Step 6",
    ]
    assert result["project"]["title"] == "天道就是我"
    assert result["project"]["genre"] == "修仙+系统流"
    assert result["project"]["target_reader"] == "男频"
    assert result["project"]["platform"] == "起点"
    assert result["protagonist"]["name"] == "林渊"
    assert result["protagonist"]["desire"] == "长生"
    assert result["protagonist"]["flaw"] == "傲慢"
    assert result["protagonist"]["archetype"] == "苟道流"
    assert result["golden_finger"]["type"] == "系统流"
    assert result["golden_finger"]["irreversible_cost"] == "反噬/失控"
    assert result["world"]["power_system_type"] == "传统修仙"
    assert result["world"]["factions"] == "宗门/学院"
    assert result["constraints"]["selected_package"]["id"] == "pkg-1"
    assert "target_reader" in fake_io.choose_calls
    assert "platform" in fake_io.choose_calls
    assert "one_liner" in fake_io.choose_calls
    assert "core_conflict" in fake_io.choose_calls
    assert "protagonist_desire" in fake_io.choose_calls
    assert "protagonist_flaw" in fake_io.choose_calls
    assert "protagonist_archetype" in fake_io.choose_calls
    assert "antagonist_mirror" in fake_io.choose_calls
    assert "power_system_type" in fake_io.choose_calls
    assert "factions" in fake_io.choose_calls
    assert "target_reader_platform" not in fake_io.ask_text_calls


def test_init_wizard_builds_init_project_argv(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()

    monkeypatch.setattr(
        module.InitWizard,
        "_build_creative_packages",
        lambda self: [
            {
                "id": "pkg-1",
                "one_liner": "修仙者发现自己是天道故障修复程序。",
                "anti_trope": "金手指有代价且不可逆",
                "hard_constraints": ["不能直接杀人", "每次升级都要失去记忆"],
                "opening_hook": "主角被逐出宗门当天，天道面板在脑海点亮。",
                "score": {"total": 42},
            }
        ],
    )

    fake_io.choice_answers["creative_package"] = "pkg-1"
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)
    payload = wizard.collect()

    argv = wizard.build_init_project_argv(payload)

    assert argv[0] == str((tmp_path / "天道就是我").resolve())
    assert argv[1:3] == ["天道就是我", "修仙+系统流"]
    assert "--protagonist-name" in argv
    assert "--golden-finger-type" in argv
    assert "--core-selling-points" in argv
    assert "--target-reader" in argv
    assert "--platform" in argv
    assert "--protagonist-archetype" in argv


def test_init_wizard_supports_single_genre_when_secondary_is_rejected(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()
    fake_io.confirm_answers["include_secondary_genre"] = False

    monkeypatch.setattr(
        module.InitWizard,
        "_build_creative_packages",
        lambda self: [
            {
                "id": "pkg-1",
                "one_liner": "修仙者发现自己是天道故障修复程序。",
                "anti_trope": "金手指有代价且不可逆",
                "hard_constraints": ["不能直接杀人", "每次升级都要失去记忆"],
                "opening_hook": "主角被逐出宗门当天，天道面板在脑海点亮。",
                "score": {"total": 42},
            }
        ],
    )

    fake_io.choice_answers["creative_package"] = "pkg-1"
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)

    payload = wizard.collect()

    assert payload["confirmed"] is True
    assert payload["project"]["genre"] == "修仙"


def test_init_wizard_returns_to_previous_step_when_final_confirmation_is_rejected(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()
    fake_io.confirm_answers["final_confirm"] = [False, True]

    monkeypatch.setattr(
        module.InitWizard,
        "_build_creative_packages",
        lambda self: [
            {
                "id": "pkg-1",
                "one_liner": "修仙者发现自己是天道故障修复程序。",
                "anti_trope": "金手指有代价且不可逆",
                "hard_constraints": ["不能直接杀人", "每次升级都要失去记忆"],
                "opening_hook": "主角被逐出宗门当天，天道面板在脑海点亮。",
                "score": {"total": 42},
            }
        ],
    )

    fake_io.choice_answers["creative_package"] = "pkg-1"
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)

    payload = wizard.collect()

    assert payload["confirmed"] is True
    assert [step_id for step_id, _ in fake_io.shown_steps] == [
        "Step 1",
        "Step 2",
        "Step 3",
        "Step 4",
        "Step 5",
        "Step 6",
        "Step 5",
        "Step 6",
    ]


def test_init_wizard_run_copies_cd_command_after_success(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)
    payload = {
        "confirmed": True,
        "project": {"title": "天道就是我", "genre": "修仙", "story_scale": ""},
        "protagonist": {},
        "relationship": {},
        "golden_finger": {},
        "world": {},
        "constraints": {},
    }
    copied = []

    monkeypatch.setattr(module.InitWizard, "collect", lambda self: payload)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, cwd=None: type("Result", (), {"returncode": 0})(),
    )
    monkeypatch.setattr(
        module,
        "_copy_text_to_clipboard",
        lambda text: copied.append(text) or True,
    )
    monkeypatch.setattr(
        module.InitWizard,
        "_configure_project_outputs",
        lambda self, project_dir, payload: (dict(module.DEFAULT_RAG_ENV), []),
    )

    result = wizard.run()

    expected_dir = str((tmp_path / "天道就是我").resolve())
    assert result["status"] == "confirmed"
    assert copied == [f'cd "{expected_dir}"']
    assert fake_io.post_init_payloads == [
        {
            "project_dir": expected_dir,
            "command": f'cd "{expected_dir}"',
            "copied": True,
        }
    ]


def test_init_wizard_run_falls_back_when_clipboard_copy_fails(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)
    payload = {
        "confirmed": True,
        "project": {"title": "天道就是我", "genre": "修仙", "story_scale": ""},
        "protagonist": {},
        "relationship": {},
        "golden_finger": {},
        "world": {},
        "constraints": {},
    }

    monkeypatch.setattr(module.InitWizard, "collect", lambda self: payload)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, cwd=None: type("Result", (), {"returncode": 0})(),
    )
    monkeypatch.setattr(module, "_copy_text_to_clipboard", lambda text: False)
    monkeypatch.setattr(
        module.InitWizard,
        "_configure_project_outputs",
        lambda self, project_dir, payload: (dict(module.DEFAULT_RAG_ENV), []),
    )

    wizard.run()

    assert fake_io.post_init_payloads[0]["copied"] is False


def test_configure_project_outputs_writes_default_env_without_manual_commands(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)
    payload = {
        "project": {"title": "天道就是我"},
        "protagonist": {},
        "relationship": {},
        "golden_finger": {},
        "world": {},
        "constraints": {},
    }
    calls = {}

    monkeypatch.setattr(module, "write_project_env", lambda project_dir, env_values: calls.setdefault("env", dict(env_values)))
    monkeypatch.setattr(module, "write_idea_bank", lambda project_dir, payload: calls.__setitem__("idea_bank", str(project_dir)))
    monkeypatch.setattr(module, "patch_master_outline", lambda project_dir, payload: calls.__setitem__("outline", str(project_dir)))
    monkeypatch.setattr(module, "verify_init_outputs", lambda project_dir: [])

    env_values, errors = wizard._configure_project_outputs(tmp_path / "天道就是我", payload)

    assert errors == []
    assert env_values["EMBED_BASE_URL"] == "https://api-inference.modelscope.cn/v1"
    assert env_values["EMBED_MODEL"] == "Qwen/Qwen3-Embedding-8B"
    assert env_values["EMBED_API_KEY"] == "your_embed_api_key"
    assert env_values["RERANK_BASE_URL"] == "https://api.jina.ai/v1"
    assert env_values["RERANK_MODEL"] == "jina-reranker-v3"
    assert env_values["RERANK_API_KEY"] == "your_rerank_api_key"
    assert calls["env"]["EMBED_API_KEY"] == "your_embed_api_key"
    rag_confirm = next(item for item in fake_io.confirm_payloads if item["field_key"] == "rag_env_modify")
    assert "已自动生成项目级 `.env` 默认配置" in rag_confirm["prompt"]
    assert "请选择下一步" in rag_confirm["prompt"]


def test_configure_project_outputs_allows_interactive_rag_edits(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()
    fake_io.confirm_answers["rag_env_modify"] = True
    fake_io.choice_answers["rag_env_edit"] = [
        "EMBED_API_KEY = your_embed_api_key",
        "RERANK_API_KEY = your_rerank_api_key",
        "完成并继续",
    ]
    fake_io.text_answers["rag_env:EMBED_API_KEY"] = "embed-secret"
    fake_io.text_answers["rag_env:RERANK_API_KEY"] = "rerank-secret"
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)

    monkeypatch.setattr(module, "write_project_env", lambda project_dir, env_values: None)
    monkeypatch.setattr(module, "write_idea_bank", lambda project_dir, payload: None)
    monkeypatch.setattr(module, "patch_master_outline", lambda project_dir, payload: None)
    monkeypatch.setattr(module, "verify_init_outputs", lambda project_dir: [])

    env_values, errors = wizard._configure_project_outputs(tmp_path / "天道就是我", {"project": {}})

    assert errors == []
    assert env_values["EMBED_API_KEY"] == "embed-secret"
    assert env_values["RERANK_API_KEY"] == "rerank-secret"
    rag_confirm = next(item for item in fake_io.confirm_payloads if item["field_key"] == "rag_env_modify")
    assert rag_confirm["yes_label"] == "修改配置"
    assert rag_confirm["no_label"] == "直接使用当前配置"
    assert "rag_env:EMBED_API_KEY" in fake_io.ask_text_calls
    assert "rag_env:RERANK_API_KEY" in fake_io.ask_text_calls


def test_collect_constraints_appends_system_recommend_and_custom_actions(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)
    wizard._project_cache = {"genre": "都市脑洞", "one_liner": "都市异象流：都市中出现各种异常现象"}
    wizard._protagonist_cache = {"flaw": "多疑"}
    wizard._relationship_cache = {"antagonist_mirror": "宿命之敌"}
    wizard._world_cache = {"scale": "多界"}

    monkeypatch.setattr(
        module.InitWizard,
        "_build_creative_packages",
        lambda self: [
            {"id": "M04", "title": "规则入侵", "one_liner": "都市异象流：都市中出现各种异常现象｜规则入侵", "anti_trope": "规则会反噬制定者", "hard_constraints": ["规则公开后会自我变异"], "opening_hook": "第一条规则出现在地铁", "score": {"total": 41}},
            {"id": "M05", "title": "代价系统", "one_liner": "都市异象流：都市中出现各种异常现象｜代价系统", "anti_trope": "每次获利都要支付现实代价", "hard_constraints": ["代价不能外包"], "opening_hook": "主角第一次使用能力就失去一天记忆", "score": {"total": 43}},
            {"id": "M01", "title": "代价修炼", "one_liner": "都市异象流：都市中出现各种异常现象｜代价修炼", "anti_trope": "修炼越快越接近失控", "hard_constraints": ["境界突破必须牺牲关系"], "opening_hook": "主角在医院走廊完成第一次突破", "score": {"total": 39}},
        ],
    )
    fake_io.choice_answers["creative_package"] = "M04｜规则入侵｜都市异象流：都市中出现各种异常现象｜规则入侵"

    payload = {"constraints": {}}
    wizard._collect_constraints(payload)

    creative_choice = next(item for item in fake_io.choose_payloads if item["field_key"] == "creative_package")
    assert creative_choice["options"][-2] == "系统推荐｜帮我从当前候选里挑最适合的一项"
    assert creative_choice["options"][-1] == "自定义｜我提供一句方向，你帮我生成候选"


def test_collect_constraints_system_recommend_shows_reason_and_can_return(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)
    wizard._project_cache = {"genre": "都市脑洞", "one_liner": "都市异象流：都市中出现各种异常现象", "core_conflict": "规则侵蚀城市秩序"}
    wizard._protagonist_cache = {"flaw": "多疑"}
    wizard._relationship_cache = {"antagonist_mirror": "宿命之敌"}
    wizard._world_cache = {"scale": "多界"}

    monkeypatch.setattr(
        module.InitWizard,
        "_build_creative_packages",
        lambda self: [
            {"id": "M04", "title": "规则入侵", "one_liner": "都市异象流：都市中出现各种异常现象｜规则入侵", "anti_trope": "规则会反噬制定者", "hard_constraints": ["规则公开后会自我变异"], "opening_hook": "第一条规则出现在地铁", "score": {"total": 41}},
            {"id": "M05", "title": "代价系统", "one_liner": "都市异象流：都市中出现各种异常现象｜代价系统", "anti_trope": "每次获利都要支付现实代价", "hard_constraints": ["代价不能外包"], "opening_hook": "主角第一次使用能力就失去一天记忆", "score": {"total": 43}},
            {"id": "M01", "title": "代价修炼", "one_liner": "都市异象流：都市中出现各种异常现象｜代价修炼", "anti_trope": "修炼越快越接近失控", "hard_constraints": ["境界突破必须牺牲关系"], "opening_hook": "主角在医院走廊完成第一次突破", "score": {"total": 39}},
        ],
    )
    fake_io.choice_answers["creative_package"] = [
        "系统推荐｜帮我从当前候选里挑最适合的一项",
        "M04｜规则入侵｜都市异象流：都市中出现各种异常现象｜规则入侵",
    ]
    fake_io.confirm_answers["creative_package_recommend"] = False

    payload = {"constraints": {}}
    wizard._collect_constraints(payload)

    assert payload["constraints"]["selected_package"]["id"] == "M04"
    assert any("推荐理由" in summary and "都市脑洞" in summary for summary in fake_io.summary_payloads)
    recommend_confirm = next(item for item in fake_io.confirm_payloads if item["field_key"] == "creative_package_recommend")
    assert recommend_confirm["yes_label"] == "采用该推荐"
    assert recommend_confirm["no_label"] == "返回 Step 5"


def test_collect_constraints_custom_direction_generates_candidates(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)
    wizard._project_cache = {"genre": "都市脑洞", "one_liner": "都市异象流：都市中出现各种异常现象", "core_conflict": "规则侵蚀城市秩序"}
    wizard._protagonist_cache = {"flaw": "多疑"}
    wizard._relationship_cache = {"antagonist_mirror": "宿命之敌"}
    wizard._world_cache = {"scale": "多界"}

    monkeypatch.setattr(
        module.InitWizard,
        "_build_creative_packages",
        lambda self: [
            {"id": "M04", "title": "规则入侵", "one_liner": "都市异象流：都市中出现各种异常现象｜规则入侵", "anti_trope": "规则会反噬制定者", "hard_constraints": ["规则公开后会自我变异"], "opening_hook": "第一条规则出现在地铁", "score": {"total": 41}},
            {"id": "M05", "title": "代价系统", "one_liner": "都市异象流：都市中出现各种异常现象｜代价系统", "anti_trope": "每次获利都要支付现实代价", "hard_constraints": ["代价不能外包"], "opening_hook": "主角第一次使用能力就失去一天记忆", "score": {"total": 43}},
            {"id": "M01", "title": "代价修炼", "one_liner": "都市异象流：都市中出现各种异常现象｜代价修炼", "anti_trope": "修炼越快越接近失控", "hard_constraints": ["境界突破必须牺牲关系"], "opening_hook": "主角在医院走廊完成第一次突破", "score": {"total": 39}},
        ],
    )
    fake_io.choice_answers["creative_package"] = "自定义｜我提供一句方向，你帮我生成候选"
    fake_io.choice_answers["creative_package_custom"] = "C01｜自定义方向候选 1｜想写规则会吞噬城市秩序，但主角必须靠付出记忆来修补它"

    payload = {"constraints": {}}
    wizard._collect_constraints(payload)

    assert payload["constraints"]["selected_package"]["id"] == "C01"
    custom_prompt = next(item for item in fake_io.ask_text_payloads if item["field_key"] == "creative_package_custom_direction")
    assert "请输入一句想法/方向" in custom_prompt["prompt"]
    custom_choice = next(item for item in fake_io.choose_payloads if item["field_key"] == "creative_package_custom")
    assert len(custom_choice["options"]) == 4
    assert custom_choice["options"][-1] == "返回 Step 5"


class _TTYStream:
    def __init__(self):
        self.buffer = []
        self.readline_calls = 0

    def isatty(self):
        return True

    def write(self, value):
        self.buffer.append(value)
        return len(value)

    def flush(self):
        return None

    def readline(self):
        self.readline_calls += 1
        return "bad\n"


class _FakeDialog:
    def __init__(self, result):
        self.result = result
        self.ran = False

    def run(self):
        self.ran = True
        return self.result


def test_shellio_ask_text_uses_builtin_input_for_default_tty(monkeypatch):
    module = _load_module()
    fake_in = _TTYStream()
    fake_out = _TTYStream()
    calls = {"count": 0, "prompt": None}

    monkeypatch.setattr(module.sys, "stdin", fake_in)
    monkeypatch.setattr(module.sys, "stdout", fake_out)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt="": calls.update({"count": calls["count"] + 1, "prompt": prompt}) or "我就是天道",
    )

    shell_io = module.ShellIO()
    value = shell_io.ask_text("project_title", "书名", "请输入书名。")

    assert value == "我就是天道"
    assert calls["count"] == 1
    assert calls["prompt"] == "> "
    assert fake_in.readline_calls == 0


def test_shellio_ask_text_enables_readline_for_default_tty(monkeypatch):
    module = _load_module()
    fake_in = _TTYStream()
    fake_out = _TTYStream()
    calls = {"count": 0}

    monkeypatch.setattr(module.sys, "stdin", fake_in)
    monkeypatch.setattr(module.sys, "stdout", fake_out)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt="": "我就是天道",
    )
    monkeypatch.setattr(
        module.ShellIO,
        "_enable_line_editing",
        lambda self: calls.__setitem__("count", calls["count"] + 1),
    )

    shell_io = module.ShellIO()
    shell_io.ask_text("project_title", "书名", "请输入书名。")

    assert calls["count"] == 1


def test_prompt_toolkit_io_choose_uses_direct_choice_prompt(monkeypatch):
    module = _load_module()
    calls = []

    monkeypatch.setattr(
        module,
        "_prompt_toolkit_choice_prompt",
        lambda **kwargs: calls.append(kwargs) or "系统流",
    )

    io = module.PromptToolkitIO()
    io.show_step("Step 3", "金手指与兑现机制")
    value = io.choose("golden_finger_type", "金手指类型", "请选择金手指类型：", ["无金手指", "系统流"])

    assert value == "系统流"
    assert calls[0]["options"] == [("无金手指", "无金手指"), ("系统流", "系统流")]
    assert "Enter/Space" in calls[0]["bottom_toolbar"]
    assert calls[0]["label"] == "金手指类型"


def test_prompt_toolkit_io_ask_text_uses_prompt_and_default(monkeypatch):
    module = _load_module()
    calls = []

    monkeypatch.setattr(
        module,
        "_prompt_toolkit_text_prompt",
        lambda **kwargs: calls.append(kwargs) or "",
    )

    io = module.PromptToolkitIO()
    io.show_step("Step 1", "故事核与商业定位")
    value = io.ask_text("project_title", "书名", "请输入书名。", default="默认书名")

    assert value == "默认书名"
    assert "请输入书名。" in calls[0]["message"]
    assert calls[0]["default"] == "默认书名"


def test_prompt_toolkit_io_cancel_raises_keyboard_interrupt(monkeypatch):
    module = _load_module()

    io = module.PromptToolkitIO()

    monkeypatch.setattr(
        module,
        "_prompt_toolkit_choice_prompt",
        lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    try:
        io.choose("genre_category", "题材分类", "请选择主题材分类：", ["玄幻修仙类"])
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("expected KeyboardInterrupt")


def test_prompt_toolkit_io_confirm_uses_direct_choice_prompt(monkeypatch):
    module = _load_module()
    calls = []

    monkeypatch.setattr(
        module,
        "_prompt_toolkit_choice_prompt",
        lambda **kwargs: calls.append(kwargs) or "__yes__",
    )

    io = module.PromptToolkitIO()
    value = io.confirm("final_confirm", "确认按以上摘要生成项目吗？", default=False, yes_label="确认生成", no_label="返回上一步")

    assert value is True
    assert calls[0]["options"] == [("__yes__", "确认生成"), ("__no__", "返回上一步")]


def test_story_core_secondary_genre_confirm_uses_add_and_skip_labels(monkeypatch, tmp_path):
    module = _load_module()
    fake_io = _FakeIO()

    monkeypatch.setattr(
        module.InitWizard,
        "_build_creative_packages",
        lambda self: [
            {
                "id": "pkg-1",
                "one_liner": "修仙者发现自己是天道故障修复程序。",
                "anti_trope": "金手指有代价且不可逆",
                "hard_constraints": ["不能直接杀人", "每次升级都要失去记忆"],
                "opening_hook": "主角被逐出宗门当天，天道面板在脑海点亮。",
                "score": {"total": 42},
            }
        ],
    )

    fake_io.choice_answers["creative_package"] = "pkg-1"
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)

    wizard.collect()

    include_secondary = next(item for item in fake_io.confirm_payloads if item["field_key"] == "include_secondary_genre")
    assert include_secondary["yes_label"] == "添加第二题材"
    assert include_secondary["no_label"] == "不添加第二题材"


def test_prompt_toolkit_io_show_summary_uses_direct_choice_prompt(monkeypatch):
    module = _load_module()
    calls = []

    monkeypatch.setattr(
        module,
        "_prompt_toolkit_choice_prompt",
        lambda **kwargs: calls.append(kwargs) or "__continue__",
    )

    io = module.PromptToolkitIO()
    io.show_summary("初始化摘要草案")

    assert calls[0]["options"] == [("__continue__", "继续")]
    assert calls[0]["prompt"] == "初始化摘要草案"


def test_run_shell_init_wizard_prefers_prompt_toolkit_when_available(monkeypatch, tmp_path):
    module = _load_module()
    captured = {}

    class _FakeWizard:
        def __init__(self, *, workspace_root, io, spec=None):
            captured["workspace_root"] = workspace_root
            captured["io_type"] = type(io).__name__

        def run(self):
            return {"status": "ok"}

    monkeypatch.setattr(module, "InitWizard", _FakeWizard)
    monkeypatch.setattr(module, "_supports_prompt_toolkit_io", lambda: True)

    result = module.run_shell_init_wizard(workspace_root=tmp_path)

    assert result == {"status": "ok"}
    assert captured["workspace_root"] == tmp_path.resolve()
    assert captured["io_type"] == "PromptToolkitIO"


def test_run_shell_init_wizard_requires_prompt_toolkit_tui(monkeypatch, tmp_path):
    module = _load_module()

    monkeypatch.setattr(module, "_supports_prompt_toolkit_io", lambda: False)

    try:
        module.run_shell_init_wizard(workspace_root=tmp_path)
    except RuntimeError as exc:
        assert "prompt_toolkit TUI" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_ansi_clear_lines_resets_column_before_clearing():
    module = _load_module()

    value = module._ansi_clear_lines(2)

    assert value == "\r\x1b[1A\x1b[2K\r\x1b[1A\x1b[2K"


def test_render_menu_block_uses_crlf_boundaries():
    module = _load_module()

    value = module._render_menu_block(["题材分类", "❯ 玄幻修仙类"])

    assert value == "\r题材分类\r\n❯ 玄幻修仙类\r\n"


def test_render_fullscreen_menu_uses_home_clear_and_viewport():
    module = _load_module()

    value = module._render_fullscreen_menu(
        "第二题材",
        "请选择第二题材：",
        ["修仙", "系统流", "高武", "西幻", "无限流", "末世", "科幻"],
        selected_index=4,
        terminal_height=7,
        terminal_width=40,
    )

    assert value.startswith("\x1b[H\x1b[2J")
    assert "第二题材" in value
    assert "请选择第二题材：" in value
    assert "❯ 无限流" in value
    assert "\r\n" in value
    assert value.replace("\r\n", "") == value.replace("\r\n", "").replace("\n", "")


def test_render_choice_lines_is_left_aligned_with_ten_item_window():
    module = _load_module()

    lines = module._render_choice_lines(
        label="第二题材",
        prompt="请选择第二题材：",
        options=[f"选项{i}" for i in range(1, 13)],
        selected_index=0,
        max_visible=10,
    )

    option_lines = [line for line in lines if line.startswith("❯ ") or line.startswith("  ")]
    assert lines[0] == "第二题材"
    assert lines[1] == "请选择第二题材："
    assert len(option_lines) == 10
    assert option_lines[0] == "❯ 选项1"
    assert option_lines[-1] == "  选项10"
    assert "↓ 更多选项" in lines


def test_render_choice_lines_shows_both_yes_no_options_without_clipping():
    module = _load_module()

    lines = module._render_choice_lines(
        label="确认",
        prompt="是否添加第二题材（A+B 复合）？",
        options=["确认", "返回修改"],
        selected_index=1,
        max_visible=10,
    )

    option_lines = [line for line in lines if line.startswith("❯ ") or line.startswith("  ")]
    assert option_lines == ["  确认", "❯ 返回修改"]
    assert "↓ 更多选项" not in lines


def test_choose_or_enter_adds_manual_guidance_from_source_options(tmp_path):
    module = _load_module()
    fake_io = _FakeIO()
    fake_io.choice_answers["factions"] = "手动输入"
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)

    value = wizard._choose_or_enter(
        "factions",
        wizard.fields["factions"].label,
        "请选择势力格局模板。",
        wizard.spec.faction_options,
    )

    assert value == "朝廷、宗门与黑市三方争夺灵矿命脉"
    prompt = fake_io.ask_text_payloads[-1]["prompt"]
    assert "也可以直接输入你自己的版本" in prompt
    assert "可参考" in prompt
    assert wizard.spec.faction_options[0] in prompt


def test_collect_story_core_reprompts_when_project_dir_exists(tmp_path):
    module = _load_module()

    class _CollisionIO(_FakeIO):
        def __init__(self):
            super().__init__()
            self._title_answers = iter(["我 就是天道", "我就是天道2"])

        def ask_text(self, field_key, label, prompt, default=None):
            self.ask_text_calls.append(field_key)
            self.ask_text_payloads.append(
                {"field_key": field_key, "label": label, "prompt": prompt, "default": default}
            )
            if field_key == "project_title":
                return next(self._title_answers)
            return self.text_answers[field_key]

    fake_io = _CollisionIO()
    wizard = module.InitWizard(workspace_root=tmp_path, io=fake_io)
    existing_dir = tmp_path / "我-就是天道"
    existing_dir.mkdir()
    payload = {"project": {}}

    wizard._collect_story_core(payload)

    assert payload["project"]["title"] == "我就是天道2"
    title_prompts = [call["prompt"] for call in fake_io.ask_text_payloads if call["field_key"] == "project_title"]
    assert len(title_prompts) == 2
    assert "已存在" in title_prompts[1]
    assert str(existing_dir) in title_prompts[1]


def test_build_init_project_argv_uses_safe_project_dir_name(tmp_path):
    module = _load_module()
    wizard = module.InitWizard(workspace_root=tmp_path, io=_FakeIO())
    payload = {
        "project": {
            "title": "我 是/天道",
            "genre": "修仙",
            "story_scale": "",
            "target_reader": "",
            "platform": "",
        },
        "protagonist": {},
        "relationship": {},
        "golden_finger": {},
        "world": {},
        "constraints": {},
    }

    argv = wizard.build_init_project_argv(payload)

    assert argv[0] == str((tmp_path / "我-是天道").resolve())
