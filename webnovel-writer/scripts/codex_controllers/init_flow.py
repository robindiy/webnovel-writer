#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Source-backed init controller for Codex chat."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess
import uuid
from typing import Any, Mapping, Optional, Sequence

from init_postprocess import (
    build_default_rag_env,
    parse_full_rag_env_block,
    parse_rag_key_block,
    patch_master_outline,
    read_project_env,
    verify_init_outputs,
    write_idea_bank,
    write_project_env,
)
from init_source_loader import InitWorkflowSpec, load_init_workflow_spec
from init_terminal_ui import INIT_PROJECT_SCRIPT, PACKAGE_ROOT, InitWizard
from runtime_compat import resolve_python_executable


CONTROLLER_NAME = "webnovel-init-chat"
COMMAND_NAME = "webnovel-init"

_PRECHECK_OPTIONS = [
    {"id": "fast-init", "label": "快速初始化（推荐）", "description": "每个大步骤一次性填写，显著减少回合数", "aliases": ("1",)},
    {"id": "granular-init", "label": "逐项填写", "description": "按字段逐个选择/输入，适合需要细抠每一步", "aliases": ("2",)},
    {"id": "cancel", "label": "取消", "description": "结束当前 init 会话", "aliases": ("3",)},
]
_CONFIRM_OPTIONS = [
    {"id": "confirm", "label": "确认生成", "description": "执行 init_project.py 并进入 RAG 配置", "aliases": ("1",)},
    {"id": "step-1", "label": "返回 Step 1", "description": "重采集故事核与商业定位", "aliases": ("2",)},
    {"id": "step-2", "label": "返回 Step 2", "description": "重采集角色骨架与关系冲突", "aliases": ("3",)},
    {"id": "step-3", "label": "返回 Step 3", "description": "重采集金手指与兑现机制", "aliases": ("4",)},
    {"id": "step-4", "label": "返回 Step 4", "description": "重采集世界观与力量规则", "aliases": ("5",)},
    {"id": "step-5", "label": "返回 Step 5", "description": "重选创意约束包", "aliases": ("6",)},
    {"id": "cancel", "label": "取消", "description": "放弃本次 init 控制器会话", "aliases": ("7",)},
]
_RAG_OPTIONS = [
    {
        "id": "template-only",
        "label": "生成 .env 模板",
        "description": "使用默认模型并创建项目级 .env，API Key 先留空",
        "aliases": ("1",),
    },
    {
        "id": "default-with-keys",
        "label": "默认模型 + 现在填 Key",
        "description": "下一步一次性输入两个 API Key，不会长期留在 controller session 里",
        "aliases": ("2",),
    },
    {
        "id": "custom-block",
        "label": "自定义全部 RAG 配置",
        "description": "下一步一次性输入 6 行 EMBED/RERANK 配置",
        "aliases": ("3",),
    },
]
_VERIFY_FAILED_OPTIONS = [
    {"id": "retry", "label": "重试验证", "description": "重新检查 state / 总纲 / idea_bank / .env", "aliases": ("1",)},
    {"id": "back-rag", "label": "返回 RAG 配置", "description": "重新生成项目级 .env", "aliases": ("2",)},
    {"id": "cancel", "label": "取消", "description": "结束当前 init 会话", "aliases": ("3",)},
]

_STEP_START = {
    "step-1": "project_title",
    "step-2": "protagonist_name",
    "step-3": "golden_finger_type",
    "step-4": "world_scale",
    "step-5": "creative_package",
}

_BATCH_STEP_START = {
    "step-1": "story_bundle",
    "step-2": "character_bundle",
    "step-3": "golden_finger_bundle",
    "step-4": "world_bundle",
    "step-5": "creative_package",
}

_FIELD_OPTIONS = {
    "protagonist_structure": ["单主角", "多主角"],
    "heroine_config": ["无", "单女主", "多女主"],
    "golden_finger_style": ["硬核", "诙谐", "黑暗", "克制"],
    "gf_visibility": ["明牌", "半明牌", "暗牌"],
    "growth_pacing": ["慢热", "中速", "快节奏"],
    "world_scale": ["单城", "多域", "大陆", "多界"],
}

_SPEC: Optional[InitWorkflowSpec] = None


def _spec() -> InitWorkflowSpec:
    global _SPEC
    if _SPEC is None:
        _SPEC = load_init_workflow_spec()
    return _SPEC


def _clone_session(session: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(session))


def _project_root_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _new_payload() -> dict[str, Any]:
    return {
        "project": {},
        "protagonist": {},
        "relationship": {},
        "golden_finger": {},
        "world": {},
        "constraints": {},
        "confirmed": False,
    }


def _project(session: Mapping[str, Any]) -> dict[str, Any]:
    return dict((session.get("payload") or {}).get("project") or {})


def _protagonist(session: Mapping[str, Any]) -> dict[str, Any]:
    return dict((session.get("payload") or {}).get("protagonist") or {})


def _relationship(session: Mapping[str, Any]) -> dict[str, Any]:
    return dict((session.get("payload") or {}).get("relationship") or {})


def _golden_finger(session: Mapping[str, Any]) -> dict[str, Any]:
    return dict((session.get("payload") or {}).get("golden_finger") or {})


def _world(session: Mapping[str, Any]) -> dict[str, Any]:
    return dict((session.get("payload") or {}).get("world") or {})


def _constraints(session: Mapping[str, Any]) -> dict[str, Any]:
    return dict((session.get("payload") or {}).get("constraints") or {})


def _wizard(session: Mapping[str, Any]) -> InitWizard:
    wizard = InitWizard(workspace_root=_project_root_path(str(session["workspace_root"])), spec=_spec())
    wizard._project_cache = _project(session)
    wizard._protagonist_cache = _protagonist(session)
    wizard._relationship_cache = _relationship(session)
    wizard._world_cache = _world(session)
    return wizard


def _set_payload_value(updated: dict[str, Any], section: str, key: str, value: Any) -> None:
    payload = updated.setdefault("payload", _new_payload())
    bucket = payload.setdefault(section, {})
    bucket[key] = value


def _set_project_root(updated: dict[str, Any], title: str) -> Path:
    project_dir = _wizard(updated)._project_dir_for_title(title)
    updated["project_root"] = str(project_dir)
    return project_dir


def _push_history(updated: dict[str, Any]) -> None:
    current = str(updated.get("step_id") or "").strip()
    if not current:
        return
    history = updated.setdefault("history", [])
    if not history or history[-1] != current:
        history.append(current)


def _go_to(updated: dict[str, Any], next_step: str, *, push_current: bool = True) -> dict[str, Any]:
    if push_current:
        _push_history(updated)
    updated["step_id"] = next_step
    updated["last_error"] = None
    updated["error_detail"] = None
    return updated


def _go_back(updated: dict[str, Any]) -> dict[str, Any]:
    history = updated.setdefault("history", [])
    if history:
        updated["step_id"] = history.pop()
    updated["last_error"] = None
    updated["error_detail"] = None
    return updated


def _force_error(updated: dict[str, Any], error_code: str, detail: str = "") -> dict[str, Any]:
    updated["last_error"] = error_code
    updated["error_detail"] = detail
    return updated


def _label_options(values: Sequence[str], *, recommended: Optional[str] = None) -> list[dict[str, Any]]:
    options = []
    for index, value in enumerate([str(item).strip() for item in values if str(item).strip()], start=1):
        label = value
        if recommended and value == recommended:
            label = f"{value}（推荐）"
        options.append(
            {
                "id": value,
                "label": label,
                "description": "",
                "aliases": (str(index), value, label),
            }
        )
    return options


def _text_step_options(*, allow_back: bool = True) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    if allow_back:
        options.append({"id": "back", "label": "返回上一步", "description": "回到上一条采集项", "aliases": ("1",)})
        options.append({"id": "cancel", "label": "取消", "description": "结束当前 init 会话", "aliases": ("2",)})
        return options
    options.append({"id": "cancel", "label": "取消", "description": "结束当前 init 会话", "aliases": ("1",)})
    return options


def _append_nav_options(options: list[dict[str, Any]], *, include_back: bool = True, include_cancel: bool = True) -> list[dict[str, Any]]:
    items = list(options)
    alias_index = len(items) + 1
    if include_back:
        items.append(
            {
                "id": "back",
                "label": "返回上一步",
                "description": "回到上一条采集项",
                "aliases": (str(alias_index),),
            }
        )
        alias_index += 1
    if include_cancel:
        items.append(
            {
                "id": "cancel",
                "label": "取消",
                "description": "结束当前 init 会话",
                "aliases": (str(alias_index),),
            }
        )
    return items


def _match_option(user_input: object, options: Sequence[Mapping[str, Any]]) -> Optional[str]:
    raw = str(user_input or "").strip()
    if not raw:
        return None
    lowered = raw.casefold()
    for index, option in enumerate(options, start=1):
        label = str(option.get("label", "")).strip()
        aliases = [str(index), str(option.get("id", "")).strip(), label]
        aliases.extend(str(alias).strip() for alias in option.get("aliases") or [])
        if any(lowered == candidate.casefold() for candidate in aliases if candidate):
            return str(option.get("id", "")).strip()
    return None


def _current_genres(session: Mapping[str, Any]) -> list[str]:
    genre = _project(session).get("genre", "")
    return [token for token in str(genre).split("+") if token]


def _step_header(step_no: str, title: str, subtitle: str) -> str:
    return f"[Init Controller {step_no}] {title}\n{subtitle}".strip()


def _project_dir_text(session: Mapping[str, Any]) -> str:
    project_root = session.get("project_root")
    return str(project_root or "（待确定）")


def _session_mode(session: Mapping[str, Any]) -> str:
    return str(session.get("mode") or "fast").strip() or "fast"


def _parse_key_value_block(raw_text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in str(raw_text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif "：" in line:
            key, value = line.split("：", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        parsed[str(key).strip()] = str(value).strip()
    return parsed


def _required_from_block(block: Mapping[str, str], labels: Sequence[str]) -> list[str]:
    return [label for label in labels if not str(block.get(label, "")).strip()]


def _apply_story_bundle(updated: dict[str, Any], raw_text: str) -> dict[str, Any]:
    block = _parse_key_value_block(raw_text)
    required = _required_from_block(block, ["书名", "题材", "目标规模", "一句话故事", "核心冲突", "目标读者", "平台"])
    if required:
        return _force_error(updated, "empty-text", "缺少字段：" + "、".join(required))
    project = updated.setdefault("payload", _new_payload()).setdefault("project", {})
    project["title"] = block["书名"]
    project["genre"] = block["题材"].replace("｜", "+").replace("|", "+")
    project["story_scale"] = block["目标规模"]
    project["one_liner"] = block["一句话故事"]
    project["core_conflict"] = block["核心冲突"]
    project["target_reader"] = block["目标读者"]
    project["platform"] = block["平台"]
    project_dir = _set_project_root(updated, project["title"])
    if project_dir.exists():
        return _force_error(updated, "project-exists", str(project_dir))
    return updated


def _apply_character_bundle(updated: dict[str, Any], raw_text: str) -> dict[str, Any]:
    block = _parse_key_value_block(raw_text)
    required = _required_from_block(
        block,
        ["主角姓名", "主角欲望", "主角缺陷", "主角结构", "感情线配置", "主角原型", "反派分层", "反派镜像"],
    )
    if required:
        return _force_error(updated, "empty-text", "缺少字段：" + "、".join(required))
    payload = updated.setdefault("payload", _new_payload())
    payload.setdefault("protagonist", {}).update(
        {
            "name": block["主角姓名"],
            "desire": block["主角欲望"],
            "flaw": block["主角缺陷"],
            "archetype": block["主角原型"],
        }
    )
    payload.setdefault("relationship", {}).update(
        {
            "structure": block["主角结构"],
            "heroine_config": block["感情线配置"],
            "antagonist_level": "小/中/大",
            "antagonist_tiers": block["反派分层"],
            "antagonist_mirror": block["反派镜像"],
            "heroine_names": block.get("女主姓名", ""),
            "heroine_role": block.get("女主定位", ""),
            "co_protagonists": block.get("多主角姓名", ""),
            "co_protagonist_roles": block.get("多主角分工", ""),
        }
    )
    return updated


def _apply_golden_finger_bundle(updated: dict[str, Any], raw_text: str) -> dict[str, Any]:
    block = _parse_key_value_block(raw_text)
    required = _required_from_block(block, ["金手指类型", "不可逆代价", "成长节奏"])
    if required:
        return _force_error(updated, "empty-text", "缺少字段：" + "、".join(required))
    gf_type = block["金手指类型"]
    payload = updated.setdefault("payload", _new_payload()).setdefault("golden_finger", {})
    payload["type"] = gf_type
    payload["name"] = "" if gf_type == "无金手指" else block.get("名称", "")
    payload["style"] = "无金手指" if gf_type == "无金手指" else block.get("风格", "")
    payload["visibility"] = "无" if gf_type == "无金手指" else block.get("可见度", "半明牌")
    payload["irreversible_cost"] = block["不可逆代价"]
    payload["growth_pacing"] = block["成长节奏"]
    payload["extra_notes"] = block.get("补充说明", "")
    return updated


def _apply_world_bundle(updated: dict[str, Any], raw_text: str) -> dict[str, Any]:
    block = _parse_key_value_block(raw_text)
    required = _required_from_block(
        block,
        ["世界规模", "力量体系", "势力格局", "社会阶层与资源分配", "货币体系", "兑换规则", "宗门/组织层级", "境界链", "小境界"],
    )
    if required:
        return _force_error(updated, "empty-text", "缺少字段：" + "、".join(required))
    payload = updated.setdefault("payload", _new_payload()).setdefault("world", {})
    payload.update(
        {
            "scale": block["世界规模"],
            "power_system_type": block["力量体系"],
            "factions": block["势力格局"],
            "social_class": block["社会阶层与资源分配"],
            "resource_distribution": block["社会阶层与资源分配"],
            "currency_system": block["货币体系"],
            "currency_exchange": block["兑换规则"],
            "sect_hierarchy": block["宗门/组织层级"],
            "cultivation_chain": block["境界链"],
            "cultivation_subtiers": block["小境界"],
        }
    )
    return updated


def new_session(project_root: str | Path) -> dict[str, Any]:
    workspace_root = _project_root_path(project_root)
    return {
        "controller": CONTROLLER_NAME,
        "command_name": COMMAND_NAME,
        "session_id": f"{CONTROLLER_NAME}-{uuid.uuid4()}",
        "active": True,
        "step_id": "precheck",
        "history": [],
        "workspace_root": str(workspace_root),
        "project_root": None,
        "mode": "fast",
        "payload": _new_payload(),
        "artifacts": [],
        "last_error": None,
        "error_detail": None,
        "verification_errors": [],
    }


def force_finish(session: Mapping[str, Any], *, step_id: str = "finished") -> dict[str, Any]:
    updated = _clone_session(session)
    updated["active"] = False
    updated["step_id"] = step_id
    return updated


def _error_prefix(session: Mapping[str, Any]) -> str:
    error_code = str(session.get("last_error") or "").strip()
    detail = str(session.get("error_detail") or "").strip()
    if error_code == "invalid-option":
        return "仅支持当前步骤给出的固定选项，或按提示直接输入文本。\n\n"
    if error_code == "project-exists":
        return f"书名对应项目目录已存在：{detail}\n\n"
    if error_code == "empty-text":
        return "当前步骤需要非空输入。\n\n"
    if error_code == "generate-failed":
        return f"初始化脚本执行失败：{detail or '请检查参数与环境。'}\n\n"
    if error_code == "rag-parse-failed":
        return f"RAG 配置解析失败：{detail}\n\n"
    if error_code == "verification-failed":
        if session.get("verification_errors"):
            joined = ", ".join(str(item) for item in session.get("verification_errors") or [])
            return f"验证失败：{joined}\n\n"
        return "验证失败，请检查生成结果。\n\n"
    return ""


def _field_options_for(step_id: str, session: Mapping[str, Any]) -> list[str]:
    spec = _spec()
    if step_id == "genre_category":
        return list(spec.genre_categories.keys())
    if step_id == "genre_primary":
        category = _project(session).get("genre_category", "")
        return list(spec.genre_categories.get(category, []))
    if step_id == "genre_secondary":
        primary = _project(session).get("genre_primary", "")
        values = [value for items in spec.genre_categories.values() for value in items if value != primary]
        return values
    if step_id == "target_reader":
        return list(spec.target_reader_options)
    if step_id == "platform":
        return list(spec.platform_options)
    if step_id == "protagonist_desire":
        return list(spec.protagonist_desire_options)
    if step_id == "protagonist_flaw":
        return list(spec.protagonist_flaw_options)
    if step_id == "protagonist_structure":
        return list(_FIELD_OPTIONS["protagonist_structure"])
    if step_id == "heroine_config":
        return list(_FIELD_OPTIONS["heroine_config"])
    if step_id == "protagonist_archetype":
        return list(spec.protagonist_archetype_options)
    if step_id == "antagonist_mirror":
        return list(spec.antagonist_mirror_options)
    if step_id == "golden_finger_type":
        return list(next(field.options for step in spec.steps for field in step.fields if field.key == "golden_finger_type"))
    if step_id == "golden_finger_style":
        return list(_FIELD_OPTIONS["golden_finger_style"])
    if step_id == "gf_visibility":
        return list(_FIELD_OPTIONS["gf_visibility"])
    if step_id == "gf_irreversible_cost":
        return list(spec.golden_finger_cost_options)
    if step_id == "growth_pacing":
        return list(_FIELD_OPTIONS["growth_pacing"])
    if step_id == "world_scale":
        return list(_FIELD_OPTIONS["world_scale"])
    if step_id == "power_system_type":
        return list(spec.power_system_options)
    if step_id == "factions":
        return list(spec.faction_options)
    return []


def _creative_packages(session: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _wizard(session)._build_creative_packages()


def _creative_recommendation(session: Mapping[str, Any], packages: list[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], str]:
    if not packages:
        return None, ""
    chosen = max(packages, key=lambda package: int(package.get("score", {}).get("total", 0)))
    reason = _wizard(session)._build_system_recommend_reason(chosen)
    return chosen, reason


def _build_custom_packages(session: Mapping[str, Any], direction: str) -> list[dict[str, Any]]:
    return _wizard(session)._build_custom_creative_packages(direction)


def _summary_text(session: Mapping[str, Any]) -> str:
    payload = deepcopy(session.get("payload") or _new_payload())
    payload["confirmed"] = True
    return _wizard(session)._build_summary(payload)


def _build_init_project_argv(session: Mapping[str, Any]) -> list[str]:
    payload = deepcopy(session.get("payload") or _new_payload())
    wizard = _wizard(session)
    argv = wizard.build_init_project_argv(payload)
    relationship = payload.get("relationship") or {}
    world = payload.get("world") or {}
    extras = [
        ("--heroine-names", relationship.get("heroine_names", "")),
        ("--heroine-role", relationship.get("heroine_role", "")),
        ("--co-protagonists", relationship.get("co_protagonists", "")),
        ("--co-protagonist-roles", relationship.get("co_protagonist_roles", "")),
        ("--antagonist-tiers", relationship.get("antagonist_tiers", "")),
        ("--currency-system", world.get("currency_system", "")),
        ("--currency-exchange", world.get("currency_exchange", "")),
        ("--sect-hierarchy", world.get("sect_hierarchy", "")),
        ("--cultivation-chain", world.get("cultivation_chain", "")),
        ("--cultivation-subtiers", world.get("cultivation_subtiers", "")),
    ]
    existing = set(argv)
    for option, value in extras:
        if option in existing or not value:
            continue
        argv.extend([option, value])
    return argv


def _run_generation(updated: dict[str, Any]) -> dict[str, Any]:
    argv = _build_init_project_argv(updated)
    command = [resolve_python_executable(), str(INIT_PROJECT_SCRIPT), *argv]
    result = subprocess.run(command, cwd=str(PACKAGE_ROOT), capture_output=True, text=True)
    if int(result.returncode or 0) != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return _force_error(updated, "generate-failed", detail)
    project_root = _project_root_path(argv[0])
    updated["project_root"] = str(project_root)
    write_idea_bank(project_root, updated["payload"])
    patch_master_outline(project_root, updated["payload"])
    updated["artifacts"] = [
        str(project_root / ".webnovel" / "state.json"),
        str(project_root / ".webnovel" / "idea_bank.json"),
        str(project_root / "大纲" / "总纲.md"),
        str(project_root / ".env.example"),
    ]
    return updated


def _verify_and_maybe_finish(updated: dict[str, Any]) -> dict[str, Any]:
    project_root = updated.get("project_root")
    if not project_root:
        return _force_error(updated, "verification-failed", "project_root missing")
    errors = verify_init_outputs(project_root)
    updated["verification_errors"] = errors
    if errors:
        updated["step_id"] = "verify_failed"
        updated["last_error"] = "verification-failed"
        return updated
    updated["active"] = False
    updated["step_id"] = "done"
    updated["last_error"] = None
    updated["error_detail"] = None
    artifacts = list(updated.get("artifacts") or [])
    env_path = str(_project_root_path(project_root) / ".env")
    if env_path not in artifacts:
        artifacts.append(env_path)
    updated["artifacts"] = artifacts
    return updated


def _set_text_value(updated: dict[str, Any], section: str, key: str, raw_value: object) -> dict[str, Any]:
    value = str(raw_value or "").strip()
    if not value:
        return _force_error(updated, "empty-text")
    _set_payload_value(updated, section, key, value)
    if section == "project" and key == "title":
        project_dir = _set_project_root(updated, value)
        if project_dir.exists():
            return _force_error(updated, "project-exists", str(project_dir))
    return updated


def _next_after(step_id: str, updated: Mapping[str, Any]) -> str:
    relationship = _relationship(updated)
    golden_finger = _golden_finger(updated)
    if step_id == "story_bundle":
        return "character_bundle"
    if step_id == "character_bundle":
        return "golden_finger_bundle"
    if step_id == "golden_finger_bundle":
        return "world_bundle"
    if step_id == "world_bundle":
        return "creative_package"
    if step_id == "project_title":
        return "genre_category"
    if step_id == "genre_category":
        return "genre_primary"
    if step_id == "genre_primary":
        return "include_secondary_genre"
    if step_id == "include_secondary_genre":
        return "story_scale"
    if step_id == "genre_secondary":
        return "story_scale"
    if step_id == "story_scale":
        return "one_liner"
    if step_id == "one_liner":
        return "core_conflict"
    if step_id == "core_conflict":
        return "target_reader"
    if step_id == "target_reader":
        return "platform"
    if step_id == "platform":
        return "protagonist_name"
    if step_id == "protagonist_name":
        return "protagonist_desire"
    if step_id == "protagonist_desire":
        return "protagonist_flaw"
    if step_id == "protagonist_flaw":
        return "protagonist_structure"
    if step_id == "protagonist_structure":
        return "heroine_config"
    if step_id == "heroine_config":
        if relationship.get("heroine_config") in {"单女主", "多女主"}:
            return "heroine_names"
        return "protagonist_archetype"
    if step_id == "heroine_names":
        return "heroine_role"
    if step_id == "heroine_role":
        return "protagonist_archetype"
    if step_id == "protagonist_archetype":
        if relationship.get("structure") == "多主角":
            return "co_protagonists"
        return "antagonist_tiers"
    if step_id == "co_protagonists":
        return "co_protagonist_roles"
    if step_id == "co_protagonist_roles":
        return "antagonist_tiers"
    if step_id == "antagonist_tiers":
        return "antagonist_mirror"
    if step_id == "antagonist_mirror":
        return "golden_finger_type"
    if step_id == "golden_finger_type":
        if golden_finger.get("type") == "无金手指":
            return "gf_irreversible_cost"
        return "golden_finger_name"
    if step_id == "golden_finger_name":
        return "golden_finger_style"
    if step_id == "golden_finger_style":
        return "gf_visibility"
    if step_id == "gf_visibility":
        return "gf_irreversible_cost"
    if step_id == "gf_irreversible_cost":
        return "growth_pacing"
    if step_id == "growth_pacing":
        gf_type = str(golden_finger.get("type") or "")
        if gf_type in {"系统面板", "重生穿越", "器灵导师"}:
            return "gf_extra_notes"
        return "world_scale"
    if step_id == "gf_extra_notes":
        return "world_scale"
    if step_id == "world_scale":
        return "power_system_type"
    if step_id == "power_system_type":
        return "factions"
    if step_id == "factions":
        return "social_class_resource"
    if step_id == "social_class_resource":
        return "currency_system"
    if step_id == "currency_system":
        return "currency_exchange"
    if step_id == "currency_exchange":
        return "sect_hierarchy"
    if step_id == "sect_hierarchy":
        return "cultivation_chain"
    if step_id == "cultivation_chain":
        return "cultivation_subtiers"
    if step_id == "cultivation_subtiers":
        return "creative_package"
    if step_id == "creative_package_custom_direction":
        return "creative_package_custom_select"
    if step_id == "creative_package_custom_select":
        return "final_summary"
    if step_id == "creative_package":
        return "final_summary"
    return "final_summary"


def _prompt_for_text_step(step_id: str, session: Mapping[str, Any]) -> str:
    if step_id == "story_bundle":
        return _step_header(
            "1/7",
            "Step 1 故事核与商业定位",
            "\n".join(
                [
                    "请一次性填写以下字段，每行一个 `键=值`：",
                    "书名=...",
                    "题材=修仙+规则怪谈",
                    "目标规模=200万字 / 600章",
                    "一句话故事=...",
                    "核心冲突=...",
                    "目标读者=男频",
                    "平台=起点",
                ]
            ),
        )
    if step_id == "character_bundle":
        return _step_header(
            "2/7",
            "Step 2 角色骨架与关系冲突",
            "\n".join(
                [
                    "请一次性填写以下字段，每行一个 `键=值`：",
                    "主角姓名=...",
                    "主角欲望=...",
                    "主角缺陷=...",
                    "主角结构=单主角/多主角",
                    "感情线配置=无/单女主/多女主",
                    "主角原型=...",
                    "反派分层=小反派:张三;中反派:李四;大反派:王五",
                    "反派镜像=...",
                    "可选：女主姓名=... / 女主定位=... / 多主角姓名=... / 多主角分工=...",
                ]
            ),
        )
    if step_id == "golden_finger_bundle":
        return _step_header(
            "3/7",
            "Step 3 金手指与兑现机制",
            "\n".join(
                [
                    "请一次性填写以下字段，每行一个 `键=值`：",
                    "金手指类型=无金手指/系统面板/随身空间/重生穿越/签到打卡/器灵导师/血脉觉醒/异能觉醒",
                    "名称=...（无金手指可留空）",
                    "风格=硬核/诙谐/黑暗/克制",
                    "可见度=明牌/半明牌/暗牌",
                    "不可逆代价=...",
                    "成长节奏=慢热/中速/快节奏",
                    "可选：补充说明=系统性格/重生时间点/器灵边界等",
                ]
            ),
        )
    if step_id == "world_bundle":
        return _step_header(
            "4/7",
            "Step 4 世界观与力量规则",
            "\n".join(
                [
                    "请一次性填写以下字段，每行一个 `键=值`：",
                    "世界规模=单城/多域/大陆/多界",
                    "力量体系=...",
                    "势力格局=...",
                    "社会阶层与资源分配=...",
                    "货币体系=...",
                    "兑换规则=...",
                    "宗门/组织层级=...",
                    "境界链=...",
                    "小境界=...",
                ]
            ),
        )
    if step_id == "project_title":
        return _step_header("0/7", "Step 0 预检与上下文加载", f"工作区：{session['workspace_root']}\n请输入书名（可先用工作名）。")
    if step_id == "story_scale":
        return _step_header("1/7", "Step 1 故事核与商业定位", "请输入目标规模，例如：200万字 / 600章。")
    if step_id == "protagonist_name":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请输入主角姓名。")
    if step_id == "heroine_names":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请输入女主姓名，多个用逗号分隔。")
    if step_id == "heroine_role":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请输入女主定位，例如：事业线 / 情感线 / 对抗线。")
    if step_id == "co_protagonists":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请输入多主角姓名，多个用逗号分隔。")
    if step_id == "co_protagonist_roles":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请输入多主角分工，多个用逗号分隔。")
    if step_id == "antagonist_tiers":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请输入反派分层，例如：小反派:张三;中反派:李四;大反派:王五。")
    if step_id == "golden_finger_name":
        return _step_header("3/7", "Step 3 金手指与兑现机制", "请输入名称/系统名；若你就是想留空，输入“无”。")
    if step_id == "gf_extra_notes":
        gf_type = _golden_finger(session).get("type", "")
        return _step_header("3/7", "Step 3 金手指与兑现机制", f"请补充 {gf_type} 的条件信息，例如系统性格 / 重生时间点 / 器灵边界。")
    if step_id == "social_class_resource":
        return _step_header("4/7", "Step 4 世界观与力量规则", "请输入社会阶层与资源分配。")
    if step_id == "currency_system":
        return _step_header("4/7", "Step 4 世界观与力量规则", "请输入货币体系。")
    if step_id == "currency_exchange":
        return _step_header("4/7", "Step 4 世界观与力量规则", "请输入兑换规则 / 面值体系。")
    if step_id == "sect_hierarchy":
        return _step_header("4/7", "Step 4 世界观与力量规则", "请输入宗门/组织层级。")
    if step_id == "cultivation_chain":
        return _step_header("4/7", "Step 4 世界观与力量规则", "请输入典型境界链。")
    if step_id == "cultivation_subtiers":
        return _step_header("4/7", "Step 4 世界观与力量规则", "请输入小境界划分，例如：初 / 中 / 后 / 巅。")
    if step_id == "creative_package_custom_direction":
        return _step_header("5/7", "Step 5 创意约束包", "请输入一句自定义方向，我会基于当前信息生成 2-3 个候选。")
    if step_id == "rag_key_block":
        return _step_header(
            "7/7",
            "RAG 环境配置",
            "请一次性输入两行：\nEMBED_API_KEY=...\nRERANK_API_KEY=...\n\n提示：本次输入不会长期保存在 controller session 文件里。",
        )
    if step_id == "rag_custom_block":
        return _step_header(
            "7/7",
            "RAG 环境配置",
            "请一次性输入 6 行配置：\nEMBED_BASE_URL=...\nEMBED_MODEL=...\nEMBED_API_KEY=...\nRERANK_BASE_URL=...\nRERANK_MODEL=...\nRERANK_API_KEY=...",
        )
    return _step_header("0/7", "Init", "请输入当前步骤需要的文本内容。")


def _prompt_for_choice_step(step_id: str, session: Mapping[str, Any], options: list[dict[str, Any]]) -> str:
    wizard = _wizard(session)
    if step_id == "precheck":
        return _step_header(
            "0/7",
            "Step 0 预检与上下文加载",
            f"工作区：{session['workspace_root']}\n当前 init 会话将由 repo controller 接管。默认推荐快速初始化，每个大步骤只填一次。",
        )
    if step_id == "genre_category":
        return _step_header("1/7", "Step 1 故事核与商业定位", "请选择主题材分类。")
    if step_id == "genre_primary":
        category = _project(session).get("genre_category", "")
        return _step_header("1/7", "Step 1 故事核与商业定位", f"当前分类：{category}\n请选择主题材。")
    if step_id == "include_secondary_genre":
        return _step_header("1/7", "Step 1 故事核与商业定位", "是否添加第二题材（A+B 复合）？")
    if step_id == "genre_secondary":
        return _step_header("1/7", "Step 1 故事核与商业定位", "请选择第二题材。")
    if step_id == "one_liner":
        genres = "+".join(_current_genres(session))
        return _step_header("1/7", "Step 1 故事核与商业定位", f"当前题材：{genres}\n请选择一句话故事方向，也可以直接输入自定义内容。")
    if step_id == "core_conflict":
        return _step_header("1/7", "Step 1 故事核与商业定位", "请选择核心冲突方向，也可以直接输入自定义内容。")
    if step_id == "target_reader":
        return _step_header("1/7", "Step 1 故事核与商业定位", "请选择目标读者，也可以直接输入自定义内容。")
    if step_id == "platform":
        return _step_header("1/7", "Step 1 故事核与商业定位", "请选择目标平台，也可以直接输入自定义内容。")
    if step_id == "protagonist_desire":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请选择主角欲望，也可以直接输入自定义内容。")
    if step_id == "protagonist_flaw":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请选择主角缺陷，也可以直接输入自定义内容。")
    if step_id == "protagonist_structure":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请选择主角结构。")
    if step_id == "heroine_config":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请选择感情线配置。")
    if step_id == "protagonist_archetype":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请选择主角原型标签，也可以直接输入自定义内容。")
    if step_id == "antagonist_mirror":
        return _step_header("2/7", "Step 2 角色骨架与关系冲突", "请选择反派镜像方向，也可以直接输入自定义内容。")
    if step_id == "golden_finger_type":
        return _step_header("3/7", "Step 3 金手指与兑现机制", "请选择金手指类型。")
    if step_id == "golden_finger_style":
        return _step_header("3/7", "Step 3 金手指与兑现机制", "请选择金手指风格。")
    if step_id == "gf_visibility":
        return _step_header("3/7", "Step 3 金手指与兑现机制", "请选择金手指可见度。")
    if step_id == "gf_irreversible_cost":
        return _step_header("3/7", "Step 3 金手指与兑现机制", "请选择不可逆代价方向，也可以直接输入自定义内容。")
    if step_id == "growth_pacing":
        return _step_header("3/7", "Step 3 金手指与兑现机制", "请选择成长节奏。")
    if step_id == "world_scale":
        return _step_header("4/7", "Step 4 世界观与力量规则", "请选择世界规模。")
    if step_id == "power_system_type":
        return _step_header("4/7", "Step 4 世界观与力量规则", "请选择力量体系类型，也可以直接输入自定义内容。")
    if step_id == "factions":
        return _step_header("4/7", "Step 4 世界观与力量规则", "请选择势力格局模板，也可以直接输入自定义内容。")
    if step_id == "creative_package":
        packages = _creative_packages(session)
        recommended, reason = _creative_recommendation(session, packages)
        recommendation_lines = [reason] if reason else []
        preview_lines = []
        for index, package in enumerate(packages, start=1):
            tag = "（推荐）" if recommended and package.get("id") == recommended.get("id") else ""
            preview_lines.extend(
                [
                    f"方案 {index}{tag}：{package.get('title', package.get('id', '方案'))}",
                    f"- 卖点：{package.get('one_liner', '')}",
                    f"- 反套路：{package.get('anti_trope', '')}",
                    f"- 硬约束：{'；'.join(package.get('hard_constraints', []))}",
                ]
            )
        return "\n".join(
            [
                _step_header("5/7", "Step 5 创意约束包", "请选择最终采用的创意约束方案。"),
                "",
                *recommendation_lines,
                *( [""] if recommendation_lines else [] ),
                *preview_lines,
            ]
        ).strip()
    if step_id == "creative_package_custom_select":
        return _step_header("5/7", "Step 5 创意约束包", "请选择一个自定义候选方案。")
    if step_id == "final_summary":
        return "\n".join(
            [
                _step_header("6/7", "Step 6 一致性复述与最终确认", f"项目目录：{_project_dir_text(session)}"),
                "",
                _summary_text(session),
                "",
                "请选择下一步。",
            ]
        ).strip()
    if step_id == "rag_mode":
        project_root = _project_root_path(str(session.get("project_root") or ""))
        return _step_header(
            "7/7",
            "RAG 环境配置",
            f"项目已生成：{project_root}\n`.env.example` 已存在。请选择如何生成项目级 `.env`。",
        )
    if step_id == "verify_failed":
        return _step_header("7/7", "初始化验证失败", "请根据错误信息重试验证，或返回 RAG 配置。")
    return _step_header("0/7", "Init", "请选择下一步。")


def _options_for_session(session: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    step_id = str(session.get("step_id") or "")
    project = _project(session)
    relationship = _relationship(session)
    if step_id == "precheck":
        options = list(_PRECHECK_OPTIONS)
        return options, _prompt_for_choice_step(step_id, session, options)
    if step_id in {"story_bundle", "character_bundle", "golden_finger_bundle", "world_bundle"}:
        options = _text_step_options()
        return options, _prompt_for_text_step(step_id, session)
    if step_id == "project_title":
        options = _text_step_options(allow_back=False)
        return options, _prompt_for_text_step(step_id, session)
    if step_id == "include_secondary_genre":
        options = [
            {"id": "yes", "label": "添加第二题材", "description": "进入第二题材选择", "aliases": ("1",)},
            {"id": "no", "label": "不添加", "description": "保持单题材，继续下一项", "aliases": ("2",)},
        ]
        options = _append_nav_options(options)
        return options, _prompt_for_choice_step(step_id, session, options)
    if step_id in {"genre_category", "genre_primary", "genre_secondary", "protagonist_structure", "heroine_config", "golden_finger_type", "golden_finger_style", "gf_visibility", "growth_pacing", "world_scale", "rag_mode", "verify_failed", "final_summary", "creative_package", "creative_package_custom_select"}:
        if step_id == "rag_mode":
            options = list(_RAG_OPTIONS)
        elif step_id == "verify_failed":
            options = list(_VERIFY_FAILED_OPTIONS)
        elif step_id == "final_summary":
            options = list(_CONFIRM_OPTIONS)
        elif step_id == "creative_package":
            packages = _creative_packages(session)
            recommended, _ = _creative_recommendation(session, packages)
            labels = []
            for package in packages:
                label = package.get("title", package.get("id", "方案"))
                if recommended and package.get("id") == recommended.get("id"):
                    label = f"{label}（推荐）"
                labels.append(
                    {
                        "id": package.get("id", label),
                        "label": label,
                        "description": package.get("one_liner", ""),
                        "aliases": (package.get("id", label),),
                    }
                )
            labels.append(
                {
                    "id": "custom",
                    "label": "自定义方向",
                    "description": "我给一句方向，你生成 2-3 个候选",
                    "aliases": (str(len(labels) + 1),),
                }
            )
            options = _append_nav_options(labels)
        elif step_id == "creative_package_custom_select":
            candidates = list(session.get("creative_package_custom_candidates") or [])
            labels = [
                {
                    "id": candidate.get("id", f"C{index}"),
                    "label": candidate.get("title", candidate.get("id", f"候选{index}")),
                    "description": candidate.get("one_liner", ""),
                    "aliases": (candidate.get("id", f"C{index}"),),
                }
                for index, candidate in enumerate(candidates, start=1)
            ]
            options = _append_nav_options(labels)
        else:
            options = _append_nav_options(_label_options(_field_options_for(step_id, session)))
        return options, _prompt_for_choice_step(step_id, session, options)
    if step_id in {"one_liner", "core_conflict", "target_reader", "platform", "protagonist_desire", "protagonist_flaw", "protagonist_archetype", "antagonist_mirror", "gf_irreversible_cost", "power_system_type", "factions"}:
        recommended = None
        if step_id == "one_liner":
            values = _wizard(session)._story_candidates(_current_genres(session))
        elif step_id == "core_conflict":
            values = _wizard(session)._conflict_candidates(_current_genres(session))
        else:
            values = _field_options_for(step_id, session)
        options = _append_nav_options(_label_options(values, recommended=recommended))
        return options, _prompt_for_choice_step(step_id, session, options)
    options = _text_step_options()
    return options, _prompt_for_text_step(step_id, session)


def _assign_selected_value(updated: dict[str, Any], step_id: str, value: str) -> dict[str, Any]:
    if step_id == "project_title":
        return _set_text_value(updated, "project", "title", value)
    if step_id == "genre_category":
        _set_payload_value(updated, "project", "genre_category", value)
        return updated
    if step_id == "genre_primary":
        _set_payload_value(updated, "project", "genre_primary", value)
        _set_payload_value(updated, "project", "genre", value)
        return updated
    if step_id == "genre_secondary":
        primary = _project(updated).get("genre_primary", "")
        genre_value = "+".join([token for token in (primary, value) if token])
        _set_payload_value(updated, "project", "genre_secondary", value)
        _set_payload_value(updated, "project", "genre", genre_value)
        return updated
    if step_id == "story_scale":
        return _set_text_value(updated, "project", "story_scale", value)
    if step_id in {"one_liner", "core_conflict", "target_reader", "platform"}:
        return _set_text_value(updated, "project", step_id, value)
    if step_id == "protagonist_name":
        return _set_text_value(updated, "protagonist", "name", value)
    if step_id in {"protagonist_desire", "protagonist_flaw", "protagonist_archetype"}:
        key = {"protagonist_desire": "desire", "protagonist_flaw": "flaw", "protagonist_archetype": "archetype"}[step_id]
        return _set_text_value(updated, "protagonist", key, value)
    if step_id == "protagonist_structure":
        _set_payload_value(updated, "relationship", "structure", value)
        return updated
    if step_id == "heroine_config":
        _set_payload_value(updated, "relationship", "heroine_config", value)
        return updated
    if step_id == "heroine_names":
        return _set_text_value(updated, "relationship", "heroine_names", value)
    if step_id == "heroine_role":
        return _set_text_value(updated, "relationship", "heroine_role", value)
    if step_id == "co_protagonists":
        return _set_text_value(updated, "relationship", "co_protagonists", value)
    if step_id == "co_protagonist_roles":
        return _set_text_value(updated, "relationship", "co_protagonist_roles", value)
    if step_id == "antagonist_tiers":
        result = _set_text_value(updated, "relationship", "antagonist_tiers", value)
        _set_payload_value(updated, "relationship", "antagonist_level", "小/中/大")
        return result
    if step_id == "antagonist_mirror":
        return _set_text_value(updated, "relationship", "antagonist_mirror", value)
    if step_id == "golden_finger_type":
        _set_payload_value(updated, "golden_finger", "type", value)
        if value == "无金手指":
            _set_payload_value(updated, "golden_finger", "name", "")
            _set_payload_value(updated, "golden_finger", "style", "无金手指")
            _set_payload_value(updated, "golden_finger", "visibility", "无")
        return updated
    if step_id == "golden_finger_name":
        normalized = "" if value == "无" else value
        _set_payload_value(updated, "golden_finger", "name", normalized)
        return updated
    if step_id == "golden_finger_style":
        _set_payload_value(updated, "golden_finger", "style", value)
        return updated
    if step_id == "gf_visibility":
        _set_payload_value(updated, "golden_finger", "visibility", value)
        return updated
    if step_id == "gf_irreversible_cost":
        return _set_text_value(updated, "golden_finger", "irreversible_cost", value)
    if step_id == "growth_pacing":
        _set_payload_value(updated, "golden_finger", "growth_pacing", value)
        return updated
    if step_id == "gf_extra_notes":
        return _set_text_value(updated, "golden_finger", "extra_notes", value)
    if step_id == "world_scale":
        _set_payload_value(updated, "world", "scale", value)
        return updated
    if step_id == "power_system_type":
        return _set_text_value(updated, "world", "power_system_type", value)
    if step_id == "factions":
        return _set_text_value(updated, "world", "factions", value)
    if step_id == "social_class_resource":
        result = _set_text_value(updated, "world", "social_class", value)
        _set_payload_value(updated, "world", "resource_distribution", value)
        return result
    if step_id == "currency_system":
        return _set_text_value(updated, "world", "currency_system", value)
    if step_id == "currency_exchange":
        return _set_text_value(updated, "world", "currency_exchange", value)
    if step_id == "sect_hierarchy":
        return _set_text_value(updated, "world", "sect_hierarchy", value)
    if step_id == "cultivation_chain":
        return _set_text_value(updated, "world", "cultivation_chain", value)
    if step_id == "cultivation_subtiers":
        return _set_text_value(updated, "world", "cultivation_subtiers", value)
    return updated


def _choose_creative_package(updated: dict[str, Any], package: Mapping[str, Any]) -> None:
    chosen = dict(package)
    payload = updated.setdefault("payload", _new_payload())
    payload["constraints"] = {
        "selected_package": chosen,
        "anti_trope": chosen.get("anti_trope", ""),
        "hard_constraints": list(chosen.get("hard_constraints") or []),
        "core_selling_points": [chosen.get("one_liner", ""), chosen.get("anti_trope", ""), *(chosen.get("hard_constraints") or [])],
        "opening_hook": chosen.get("opening_hook", ""),
    }


def _apply_rag_mode_choice(updated: dict[str, Any], option_id: str) -> dict[str, Any]:
    if option_id == "template-only":
        write_project_env(updated["project_root"], build_default_rag_env())
        return _verify_and_maybe_finish(updated)
    if option_id == "default-with-keys":
        return _go_to(updated, "rag_key_block")
    if option_id == "custom-block":
        return _go_to(updated, "rag_custom_block")
    return _force_error(updated, "invalid-option")


def apply_input(session: Mapping[str, Any], user_input: object) -> dict[str, Any]:
    updated = _clone_session(session)
    if not updated.get("active"):
        return updated

    step_id = str(updated.get("step_id") or "").strip()
    raw_text = str(user_input or "").strip()
    options, _ = _options_for_session(updated)
    option_id = _match_option(raw_text, options)

    if option_id == "cancel":
        return force_finish(updated, step_id="cancelled")
    if option_id == "back":
        return _go_back(updated)

    updated["last_error"] = None
    updated["error_detail"] = None

    if step_id == "precheck":
        if option_id == "fast-init":
            updated["mode"] = "fast"
            return _go_to(updated, "story_bundle")
        if option_id == "granular-init":
            updated["mode"] = "granular"
            return _go_to(updated, "project_title")
        return force_finish(updated, step_id="cancelled")

    if step_id == "story_bundle":
        updated = _apply_story_bundle(updated, raw_text)
        if updated.get("last_error"):
            return updated
        return _go_to(updated, "character_bundle")

    if step_id == "character_bundle":
        updated = _apply_character_bundle(updated, raw_text)
        if updated.get("last_error"):
            return updated
        return _go_to(updated, "golden_finger_bundle")

    if step_id == "golden_finger_bundle":
        updated = _apply_golden_finger_bundle(updated, raw_text)
        if updated.get("last_error"):
            return updated
        return _go_to(updated, "world_bundle")

    if step_id == "world_bundle":
        updated = _apply_world_bundle(updated, raw_text)
        if updated.get("last_error"):
            return updated
        return _go_to(updated, "creative_package")

    if step_id == "include_secondary_genre":
        if option_id == "yes":
            return _go_to(updated, "genre_secondary")
        if option_id == "no":
            _set_payload_value(updated, "project", "genre", _project(updated).get("genre_primary", ""))
            return _go_to(updated, "story_scale")
        return _force_error(updated, "invalid-option")

    if step_id == "creative_package":
        if option_id == "custom":
            return _go_to(updated, "creative_package_custom_direction")
        packages = _creative_packages(updated)
        chosen = next((package for package in packages if str(package.get("id")) == option_id), None)
        if chosen is None:
            return _force_error(updated, "invalid-option")
        _choose_creative_package(updated, chosen)
        return _go_to(updated, "final_summary")

    if step_id == "creative_package_custom_select":
        candidates = list(updated.get("creative_package_custom_candidates") or [])
        chosen = next((package for package in candidates if str(package.get("id")) == option_id), None)
        if chosen is None:
            return _force_error(updated, "invalid-option")
        _choose_creative_package(updated, chosen)
        return _go_to(updated, "final_summary")

    if step_id == "final_summary":
        if option_id == "confirm":
            generated = _run_generation(updated)
            if generated.get("last_error"):
                return generated
            generated.setdefault("payload", {})["confirmed"] = True
            return _go_to(generated, "rag_mode")
        step_start = _BATCH_STEP_START if _session_mode(updated) == "fast" else _STEP_START
        if option_id in step_start:
            updated["history"] = []
            updated["step_id"] = step_start[option_id]
            return updated
        return _force_error(updated, "invalid-option")

    if step_id == "rag_mode":
        if option_id is None:
            return _force_error(updated, "invalid-option")
        return _apply_rag_mode_choice(updated, option_id)

    if step_id == "verify_failed":
        if option_id == "retry":
            return _verify_and_maybe_finish(updated)
        if option_id == "back-rag":
            return _go_to(updated, "rag_mode")
        return _force_error(updated, "invalid-option")

    if step_id == "rag_key_block":
        try:
            env_values = parse_rag_key_block(raw_text)
        except ValueError as exc:
            return _force_error(updated, "rag-parse-failed", str(exc))
        write_project_env(updated["project_root"], env_values)
        return _verify_and_maybe_finish(updated)

    if step_id == "rag_custom_block":
        try:
            env_values = parse_full_rag_env_block(raw_text)
        except ValueError as exc:
            return _force_error(updated, "rag-parse-failed", str(exc))
        write_project_env(updated["project_root"], env_values)
        return _verify_and_maybe_finish(updated)

    if step_id == "creative_package_custom_direction":
        if not raw_text:
            return _force_error(updated, "empty-text")
        updated["creative_package_custom_candidates"] = _build_custom_packages(updated, raw_text)
        return _go_to(updated, "creative_package_custom_select")

    if step_id in {"genre_category", "genre_primary", "genre_secondary", "protagonist_structure", "heroine_config", "golden_finger_type", "golden_finger_style", "gf_visibility", "growth_pacing", "world_scale"}:
        if option_id is None:
            return _force_error(updated, "invalid-option")
        updated = _assign_selected_value(updated, step_id, option_id)
        if updated.get("last_error"):
            return updated
        return _go_to(updated, _next_after(step_id, updated))

    if step_id in {"one_liner", "core_conflict", "target_reader", "platform", "protagonist_desire", "protagonist_flaw", "protagonist_archetype", "antagonist_mirror", "gf_irreversible_cost", "power_system_type", "factions"}:
        chosen = option_id or raw_text
        if not chosen:
            return _force_error(updated, "empty-text")
        updated = _assign_selected_value(updated, step_id, chosen)
        if updated.get("last_error"):
            return updated
        return _go_to(updated, _next_after(step_id, updated))

    if not raw_text:
        return _force_error(updated, "empty-text")
    updated = _assign_selected_value(updated, step_id, raw_text)
    if updated.get("last_error"):
        return updated
    return _go_to(updated, _next_after(step_id, updated))


def _message_for_session(session: Mapping[str, Any]) -> str:
    prefix = _error_prefix(session)
    step_id = str(session.get("step_id") or "").strip()
    if step_id == "done":
        project_root = _project_root_path(str(session.get("project_root") or ""))
        env_values = read_project_env(project_root)
        key_status = "已填写" if env_values.get("EMBED_API_KEY") or env_values.get("RERANK_API_KEY") else "留空模板"
        artifacts = "\n".join(f"- {path}" for path in session.get("artifacts") or [])
        return (
            "[Init Controller] 初始化完成。\n"
            + f"project: {project_root}\n"
            + f"rag env: {project_root / '.env'} ({key_status})\n"
            + "next:\n"
            + "- /webnovel-writer:webnovel-plan 1\n"
            + "- /webnovel-writer:webnovel-dashboard\n"
            + "generated artifacts:\n"
            + artifacts
        )
    if step_id == "cancelled":
        return "[Init Controller] 已取消，本次 init 不会继续写入新项目。"
    if step_id == "abandoned":
        return "[Init Controller] 已被新的显式命令中断。"
    _, prompt = _options_for_session(session)
    return prefix + prompt


def build_controller_action(session: Mapping[str, Any]) -> dict[str, Any]:
    options, _ = _options_for_session(session)
    step_id = str(session.get("step_id") or "").strip()
    accepts_text_input = step_id not in {
        "precheck",
        "genre_category",
        "genre_primary",
        "include_secondary_genre",
        "genre_secondary",
        "protagonist_structure",
        "heroine_config",
        "golden_finger_type",
        "golden_finger_style",
        "gf_visibility",
        "growth_pacing",
        "world_scale",
        "creative_package",
        "creative_package_custom_select",
        "final_summary",
        "rag_mode",
        "verify_failed",
    }
    return {
        "type": "controller_step",
        "controller": CONTROLLER_NAME,
        "session_id": str(session.get("session_id", "")).strip(),
        "step_id": step_id,
        "done": not bool(session.get("active")),
        "message": _message_for_session(session),
        "options": [] if not session.get("active") else options,
        "accepts_text_input": accepts_text_input,
    }
