#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arrow-key TUI wizard for webnovel project initialization."""

from __future__ import annotations

import argparse
import curses
import json
import locale
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

import init_project as init_project_module
from runtime_compat import enable_windows_utf8_stdio
from security_utils import atomic_write_json


if sys.platform == "win32":
    enable_windows_utf8_stdio()

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass


CUSTOM_VALUE = "__custom__"
SECTION_ORDER: tuple[str, ...] = ("basic", "protagonist", "golden_finger", "world", "rag_config")
SECTION_TITLES = {
    "basic": "基础信息",
    "protagonist": "角色与冲突",
    "golden_finger": "金手指",
    "world": "世界观与规则",
    "rag_config": "Embedding / Reranker",
}

EMBED_BASE_URL_DEFAULT = "https://api-inference.modelscope.cn/v1"
EMBED_MODEL_DEFAULT = "Qwen/Qwen3-Embedding-8B"
RERANK_BASE_URL_DEFAULT = "https://api.jina.ai/v1"
RERANK_MODEL_DEFAULT = "jina-reranker-v3"

GENRE_OPTIONS: tuple[str, ...] = (
    "修仙",
    "系统流",
    "高武",
    "西幻",
    "无限流",
    "末世",
    "科幻",
    "都市异能",
    "都市日常",
    "都市脑洞",
    "现实题材",
    "黑暗题材",
    "电竞",
    "直播文",
    "古言",
    "宫斗宅斗",
    "青春甜宠",
    "豪门总裁",
    "职场婚恋",
    "民国言情",
    "幻想言情",
    "现言脑洞",
    "女频悬疑",
    "狗血言情",
    "替身文",
    "多子多福",
    "种田",
    "年代",
    "规则怪谈",
    "悬疑脑洞",
    "悬疑灵异",
    "历史古代",
    "历史脑洞",
    "游戏体育",
    "抗战谍战",
    "知乎短篇",
    "克苏鲁",
)

PROTAGONIST_STRUCTURE_OPTIONS: tuple[str, ...] = ("单主角", "多主角")
HEROINE_CONFIG_OPTIONS: tuple[str, ...] = ("无女主", "单女主", "多女主")
GF_VISIBILITY_OPTIONS: tuple[str, ...] = ("暗牌", "半明牌", "明牌")
WORLD_SCALE_OPTIONS: tuple[str, ...] = ("单城", "多城/一国", "多域", "大陆", "多界")
GF_TYPE_OPTIONS: tuple[str, ...] = (
    "系统流",
    "签到流",
    "重生",
    "传承",
    "模拟器",
    "鉴定流",
    "器灵/老爷爷",
    "无金手指",
)
PLATFORM_OPTIONS: tuple[str, ...] = (
    "起点中文网",
    "番茄小说",
    "七猫小说",
    "纵横中文网",
    "晋江文学城",
    "知乎盐选",
    "微信读书",
    "未定",
)


def _default_assist_modes() -> dict[str, str]:
    return {section: "manual" for section in SECTION_ORDER}


def _default_assist_notes() -> dict[str, str]:
    return {section: "" for section in SECTION_ORDER}


@dataclass
class InitForm:
    workspace_root: str
    title: str = ""
    project_dir: str = ""
    genres: list[str] = field(default_factory=list)
    custom_genre: str = ""
    target_words: int = 2_000_000
    target_chapters: int = 600
    target_reader: str = ""
    platform: str = ""
    core_selling_points: str = ""
    protagonist_name: str = ""
    protagonist_desire: str = ""
    protagonist_flaw: str = ""
    protagonist_archetype: str = ""
    protagonist_structure: str = PROTAGONIST_STRUCTURE_OPTIONS[0]
    heroine_config: str = HEROINE_CONFIG_OPTIONS[0]
    heroine_names: str = ""
    heroine_role: str = ""
    co_protagonists: str = ""
    co_protagonist_roles: str = ""
    antagonist_level: str = ""
    antagonist_tiers: str = ""
    golden_finger_type: str = ""
    golden_finger_name: str = ""
    golden_finger_style: str = ""
    gf_visibility: str = GF_VISIBILITY_OPTIONS[0]
    gf_irreversible_cost: str = ""
    world_scale: str = ""
    factions: str = ""
    power_system_type: str = ""
    social_class: str = ""
    resource_distribution: str = ""
    currency_system: str = ""
    currency_exchange: str = ""
    sect_hierarchy: str = ""
    cultivation_chain: str = ""
    cultivation_subtiers: str = ""
    write_env_file: bool = False
    embed_base_url: str = EMBED_BASE_URL_DEFAULT
    embed_model: str = EMBED_MODEL_DEFAULT
    embed_api_key: str = ""
    rerank_base_url: str = RERANK_BASE_URL_DEFAULT
    rerank_model: str = RERANK_MODEL_DEFAULT
    rerank_api_key: str = ""
    assist_modes: dict[str, str] = field(default_factory=_default_assist_modes)
    assist_notes: dict[str, str] = field(default_factory=_default_assist_notes)


def _sanitize_project_name(title: str) -> str:
    raw = str(title or "").strip()
    raw = re.sub(r"\s+", "-", raw)
    raw = re.sub(r'[<>:"/\\|?*]+', "-", raw)
    raw = re.sub(r"-{2,}", "-", raw)
    raw = raw.strip(" .-")
    if not raw:
        raw = "webnovel-project"
    if raw.startswith("."):
        raw = f"proj-{raw.lstrip('.')}"
    return raw


def suggest_project_dir(workspace_root: str, title: str) -> str:
    root = Path(workspace_root).expanduser().resolve()
    return str(root / _sanitize_project_name(title))


def _split_multi_values(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    normalized = re.sub(r"[+/、，,；;]", "+", text)
    return [part.strip() for part in normalized.split("+") if part.strip()]


def resolve_genre_value(form: InitForm) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for item in list(form.genres) + _split_multi_values(form.custom_genre):
        if item == CUSTOM_VALUE:
            continue
        if item not in seen:
            seen.add(item)
            parts.append(item)
    return "+".join(parts)


def is_system_assisted(form: InitForm, section: str) -> bool:
    return str(form.assist_modes.get(section, "manual")) == "system"


def _system_placeholder(label: str) -> str:
    return f"【待 Codex 建议：{label}】"


def missing_required_fields(form: InitForm) -> list[str]:
    missing: list[str] = []
    if not str(form.workspace_root or "").strip():
        missing.append("工作区目录")

    if not str(form.title or "").strip() and not is_system_assisted(form, "basic"):
        missing.append("书名")
    if not str(form.project_dir or "").strip() and not is_system_assisted(form, "basic"):
        missing.append("项目目录")
    if not resolve_genre_value(form) and not is_system_assisted(form, "basic"):
        missing.append("题材")
    if int(form.target_words or 0) <= 0:
        missing.append("目标字数")
    if int(form.target_chapters or 0) <= 0:
        missing.append("目标章节数")

    if not is_system_assisted(form, "protagonist"):
        if not str(form.protagonist_name or "").strip():
            missing.append("主角名")
        if not str(form.protagonist_desire or "").strip():
            missing.append("主角欲望")
        if not str(form.protagonist_flaw or "").strip():
            missing.append("主角缺陷")
        if form.protagonist_structure == "多主角" and not str(form.co_protagonists or "").strip():
            missing.append("多主角名单")
        if form.heroine_config != "无女主" and not str(form.heroine_names or "").strip():
            missing.append("女主姓名")

    if not is_system_assisted(form, "golden_finger") and not str(form.golden_finger_type or "").strip():
        missing.append("金手指类型")

    if not is_system_assisted(form, "world"):
        if not str(form.world_scale or "").strip():
            missing.append("世界规模")
        if not str(form.power_system_type or "").strip():
            missing.append("力量体系类型")

    return missing


def _value_or_placeholder(raw: str, *, assisted: bool, label: str) -> str:
    value = str(raw or "").strip()
    if value:
        return value
    if assisted:
        return _system_placeholder(label)
    return value


def build_init_kwargs(form: InitForm) -> dict[str, object]:
    basic_assisted = is_system_assisted(form, "basic")
    protagonist_assisted = is_system_assisted(form, "protagonist")
    gf_assisted = is_system_assisted(form, "golden_finger")
    world_assisted = is_system_assisted(form, "world")

    title = str(form.title or "").strip() or ("未命名小说" if basic_assisted else "")
    genre = resolve_genre_value(form) or ("待Codex建议" if basic_assisted else "")
    project_dir = str(form.project_dir or "").strip() or suggest_project_dir(
        form.workspace_root,
        title or "webnovel-project",
    )

    heroine_names = form.heroine_names if form.heroine_config != "无女主" else ""
    heroine_role = form.heroine_role if form.heroine_config != "无女主" else ""
    if form.heroine_config != "无女主" and protagonist_assisted:
        heroine_names = _value_or_placeholder(heroine_names, assisted=True, label="女主姓名")
        heroine_role = _value_or_placeholder(heroine_role, assisted=True, label="女主定位")

    co_protagonists = form.co_protagonists if form.protagonist_structure == "多主角" else ""
    co_roles = form.co_protagonist_roles if form.protagonist_structure == "多主角" else ""
    if form.protagonist_structure == "多主角" and protagonist_assisted:
        co_protagonists = _value_or_placeholder(co_protagonists, assisted=True, label="多主角名单")
        co_roles = _value_or_placeholder(co_roles, assisted=True, label="多主角分工")

    return {
        "project_dir": project_dir,
        "title": title,
        "genre": genre,
        "protagonist_name": _value_or_placeholder(
            form.protagonist_name,
            assisted=protagonist_assisted,
            label="主角名",
        ),
        "target_words": int(form.target_words),
        "target_chapters": int(form.target_chapters),
        "golden_finger_name": _value_or_placeholder(
            form.golden_finger_name,
            assisted=gf_assisted and form.golden_finger_type != "无金手指",
            label="金手指名称",
        ),
        "golden_finger_type": _value_or_placeholder(
            form.golden_finger_type,
            assisted=gf_assisted,
            label="金手指类型",
        ),
        "golden_finger_style": _value_or_placeholder(
            form.golden_finger_style,
            assisted=gf_assisted,
            label="金手指风格",
        ),
        "core_selling_points": _value_or_placeholder(
            form.core_selling_points,
            assisted=basic_assisted,
            label="核心卖点",
        ),
        "protagonist_structure": str(form.protagonist_structure),
        "heroine_config": str(form.heroine_config),
        "heroine_names": str(heroine_names),
        "heroine_role": str(heroine_role),
        "co_protagonists": str(co_protagonists),
        "co_protagonist_roles": str(co_roles),
        "antagonist_tiers": _value_or_placeholder(
            form.antagonist_tiers,
            assisted=protagonist_assisted,
            label="反派分层",
        ),
        "world_scale": _value_or_placeholder(
            form.world_scale,
            assisted=world_assisted,
            label="世界规模",
        ),
        "factions": _value_or_placeholder(
            form.factions,
            assisted=world_assisted,
            label="势力格局",
        ),
        "power_system_type": _value_or_placeholder(
            form.power_system_type,
            assisted=world_assisted,
            label="力量体系类型",
        ),
        "social_class": _value_or_placeholder(
            form.social_class,
            assisted=world_assisted,
            label="社会阶层",
        ),
        "resource_distribution": _value_or_placeholder(
            form.resource_distribution,
            assisted=world_assisted,
            label="资源分配",
        ),
        "gf_visibility": str(form.gf_visibility),
        "gf_irreversible_cost": _value_or_placeholder(
            form.gf_irreversible_cost,
            assisted=gf_assisted,
            label="金手指不可逆代价",
        ),
        "protagonist_desire": _value_or_placeholder(
            form.protagonist_desire,
            assisted=protagonist_assisted,
            label="主角欲望",
        ),
        "protagonist_flaw": _value_or_placeholder(
            form.protagonist_flaw,
            assisted=protagonist_assisted,
            label="主角缺陷",
        ),
        "protagonist_archetype": _value_or_placeholder(
            form.protagonist_archetype,
            assisted=protagonist_assisted,
            label="主角人设类型",
        ),
        "antagonist_level": _value_or_placeholder(
            form.antagonist_level,
            assisted=protagonist_assisted,
            label="反派等级",
        ),
        "target_reader": _value_or_placeholder(
            form.target_reader,
            assisted=basic_assisted,
            label="目标读者",
        ),
        "platform": _value_or_placeholder(
            form.platform,
            assisted=basic_assisted,
            label="发布平台",
        ),
        "currency_system": _value_or_placeholder(
            form.currency_system,
            assisted=world_assisted,
            label="货币体系",
        ),
        "currency_exchange": _value_or_placeholder(
            form.currency_exchange,
            assisted=world_assisted,
            label="兑换规则",
        ),
        "sect_hierarchy": _value_or_placeholder(
            form.sect_hierarchy,
            assisted=world_assisted,
            label="宗门层级",
        ),
        "cultivation_chain": _value_or_placeholder(
            form.cultivation_chain,
            assisted=world_assisted,
            label="境界链",
        ),
        "cultivation_subtiers": _value_or_placeholder(
            form.cultivation_subtiers,
            assisted=world_assisted,
            label="小境界",
        ),
    }


def build_assist_metadata(form: InitForm, kwargs: dict[str, object]) -> dict[str, object]:
    sections: dict[str, dict[str, object]] = {}
    pending: list[dict[str, str]] = []
    for section in SECTION_ORDER:
        mode = "system" if is_system_assisted(form, section) else "manual"
        note = str(form.assist_notes.get(section, "") or "").strip()
        sections[section] = {
            "title": SECTION_TITLES[section],
            "mode": mode,
            "note": note,
        }

    tracked_fields = [
        ("basic", "title", "书名"),
        ("basic", "genre", "题材"),
        ("basic", "target_reader", "目标读者"),
        ("basic", "platform", "发布平台"),
        ("basic", "core_selling_points", "核心卖点"),
        ("protagonist", "protagonist_name", "主角名"),
        ("protagonist", "protagonist_desire", "主角欲望"),
        ("protagonist", "protagonist_flaw", "主角缺陷"),
        ("protagonist", "protagonist_archetype", "主角人设类型"),
        ("protagonist", "antagonist_level", "反派等级"),
        ("golden_finger", "golden_finger_type", "金手指类型"),
        ("golden_finger", "golden_finger_name", "金手指名称"),
        ("golden_finger", "golden_finger_style", "金手指风格"),
        ("golden_finger", "gf_irreversible_cost", "金手指不可逆代价"),
        ("world", "world_scale", "世界规模"),
        ("world", "power_system_type", "力量体系类型"),
        ("world", "factions", "势力格局"),
        ("world", "currency_system", "货币体系"),
        ("world", "sect_hierarchy", "宗门层级"),
        ("rag_config", "embed_base_url", "Embedding Base URL"),
        ("rag_config", "embed_model", "Embedding 模型"),
        ("rag_config", "rerank_base_url", "Reranker Base URL"),
        ("rag_config", "rerank_model", "Reranker 模型"),
    ]
    for section, field_name, label in tracked_fields:
        if not is_system_assisted(form, section):
            continue
        if section == "rag_config":
            value = str(getattr(form, field_name, "") or "")
            if not value:
                value = _system_placeholder(label)
        else:
            value = str(kwargs.get(field_name, "") or "")
        if "待 Codex 建议" in value or value == "待Codex建议" or section == "rag_config":
            pending.append(
                {
                    "section": section,
                    "field": field_name,
                    "label": label,
                    "value": value,
                }
            )

    return {
        "source": "init_tui",
        "sections": sections,
        "codex_assist_sections": [section for section in SECTION_ORDER if is_system_assisted(form, section)],
        "pending_suggestions": pending,
    }


def _assist_summary_lines(form: InitForm) -> list[str]:
    lines: list[str] = []
    for section in SECTION_ORDER:
        mode_label = "系统协助" if is_system_assisted(form, section) else "手动填写"
        note = str(form.assist_notes.get(section, "") or "").strip()
        line = f"{SECTION_TITLES[section]}: {mode_label}"
        if note:
            line += f" | 说明: {note}"
        lines.append(line)
    return lines


def _secret_status(value: str) -> str:
    return "已填写" if str(value or "").strip() else "未填写"


def build_project_env_content(form: InitForm) -> str:
    lines = [
        "# Webnovel Writer 项目级配置",
        "# 由 webnovel-init TUI 生成，可按需手改。",
        "",
        "# Embedding",
        f"EMBED_BASE_URL={form.embed_base_url.strip() or EMBED_BASE_URL_DEFAULT}",
        f"EMBED_MODEL={form.embed_model.strip() or EMBED_MODEL_DEFAULT}",
        f"EMBED_API_KEY={form.embed_api_key.strip()}",
        "",
        "# Rerank",
        f"RERANK_BASE_URL={form.rerank_base_url.strip() or RERANK_BASE_URL_DEFAULT}",
        f"RERANK_MODEL={form.rerank_model.strip() or RERANK_MODEL_DEFAULT}",
        f"RERANK_API_KEY={form.rerank_api_key.strip()}",
        "",
    ]
    return "\n".join(lines)


def format_summary(form: InitForm) -> str:
    missing = missing_required_fields(form)
    lines = [
        "当前初始化摘要",
        "",
        f"书名: {form.title or '未填写'}",
        f"项目目录: {form.project_dir or '未填写'}",
        f"题材: {resolve_genre_value(form) or '未填写'}",
        f"规模: {form.target_words} 字 / {form.target_chapters} 章",
        "",
        f"主角: {form.protagonist_name or '未填写'}",
        f"欲望: {form.protagonist_desire or '未填写'}",
        f"缺陷: {form.protagonist_flaw or '未填写'}",
        f"结构: {form.protagonist_structure or '未填写'}",
        f"女主配置: {form.heroine_config or '未填写'}",
        "",
        f"金手指: {form.golden_finger_type or '未填写'} / {form.golden_finger_name or '未命名'}",
        f"世界规模: {form.world_scale or '未填写'}",
        f"力量体系: {form.power_system_type or '未填写'}",
        f"平台: {form.platform or '未填写'}",
        "",
        f"项目级 .env: {'写入' if form.write_env_file else '仅保留 .env.example'}",
        f"Embedding: {form.embed_model or EMBED_MODEL_DEFAULT} | Key: {_secret_status(form.embed_api_key)}",
        f"Reranker: {form.rerank_model or RERANK_MODEL_DEFAULT} | Key: {_secret_status(form.rerank_api_key)}",
        "",
        "分区填写方式:",
        *[f"- {line}" for line in _assist_summary_lines(form)],
        "",
        "未完成必填项:",
        " - 无" if not missing else " - " + "\n - ".join(missing),
    ]
    return "\n".join(lines)


def write_assist_metadata(project_dir: str, form: InitForm, kwargs: dict[str, object]) -> None:
    project_root = Path(project_dir).expanduser().resolve()
    metadata = build_assist_metadata(form, kwargs)

    state_path = project_root / ".webnovel" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    project_info = state.setdefault("project_info", {})
    project_info["tui_init_preferences"] = metadata
    project_info["codex_assist_sections"] = metadata["codex_assist_sections"]
    project_info["env_write_mode"] = "project_env" if form.write_env_file else "example_only"
    atomic_write_json(state_path, state, use_lock=True, backup=False)

    note_lines = [
        "# 初始化偏好",
        "",
        "> 本文件记录 TUI 初始化阶段哪些分区使用了“系统协助我填写”。",
        "> 后续如果 Codex 读取到本文件或 state.json 中的 `tui_init_preferences`，应优先给出优化建议。",
        "",
    ]
    for section in SECTION_ORDER:
        mode = "系统协助" if is_system_assisted(form, section) else "手动填写"
        note_lines.append(f"## {SECTION_TITLES[section]}")
        note_lines.append(f"- 模式：{mode}")
        note = str(form.assist_notes.get(section, "") or "").strip()
        if note:
            note_lines.append(f"- 用户提示：{note}")
        note_lines.append("")

    note_lines.extend(
        [
            "## Embedding / Reranker",
            f"- 项目级 .env：{'写入' if form.write_env_file else '仅保留 .env.example'}",
            f"- EMBED_BASE_URL：{form.embed_base_url}",
            f"- EMBED_MODEL：{form.embed_model}",
            f"- EMBED_API_KEY：{_secret_status(form.embed_api_key)}",
            f"- RERANK_BASE_URL：{form.rerank_base_url}",
            f"- RERANK_MODEL：{form.rerank_model}",
            f"- RERANK_API_KEY：{_secret_status(form.rerank_api_key)}",
            "",
        ]
    )

    pending = metadata.get("pending_suggestions") or []
    if pending:
        note_lines.extend(
            [
                "## 待 Codex 优化的字段",
                "",
            ]
        )
        for item in pending:
            note_lines.append(f"- {SECTION_TITLES[item['section']]} / {item['label']}：{item['value']}")
        note_lines.append("")

    note_path = project_root / "设定集" / "初始化偏好.md"
    note_path.write_text("\n".join(note_lines).rstrip() + "\n", encoding="utf-8")

    if form.write_env_file:
        env_path = project_root / ".env"
        env_path.write_text(build_project_env_content(form), encoding="utf-8")


class TerminalUI:
    def __init__(self, stdscr: curses.window):
        self.stdscr = stdscr
        self.height, self.width = self.stdscr.getmaxyx()

    def refresh_size(self) -> None:
        self.height, self.width = self.stdscr.getmaxyx()

    def _safe_cursor(self, visible: int) -> None:
        try:
            curses.curs_set(visible)
        except curses.error:
            pass

    def _wrap_lines(self, text: str) -> list[str]:
        width = max(10, self.width - 4)
        lines: list[str] = []
        for raw_line in str(text or "").splitlines() or [""]:
            wrapped = textwrap.wrap(raw_line, width=width, replace_whitespace=False, drop_whitespace=False)
            lines.extend(wrapped or [""])
        return lines or [""]

    def _draw_lines(
        self,
        title: str,
        lines: Sequence[str],
        *,
        scroll: int = 0,
        footer: str = "",
        options: Optional[Sequence[str]] = None,
        selected_index: int = 0,
        multi_selected: Optional[set[int]] = None,
    ) -> None:
        self.refresh_size()
        self.stdscr.erase()
        title_text = str(title)[: self.width - 1]
        self.stdscr.addnstr(0, 0, title_text, self.width - 1, curses.A_BOLD)

        if footer:
            footer_text = str(footer)[: self.width - 1]
            self.stdscr.addnstr(self.height - 1, 0, footer_text, self.width - 1, curses.A_DIM)

        y = 2
        usable_height = self.height - 4
        rendered_body: list[str] = []
        for line in lines:
            rendered_body.extend(self._wrap_lines(line))

        if options is None:
            view = rendered_body[scroll : scroll + usable_height]
            for line in view:
                if y >= self.height - 1:
                    break
                self.stdscr.addnstr(y, 1, line, self.width - 2)
                y += 1
            self.stdscr.refresh()
            return

        # Lock description and options into stable vertical zones to avoid
        # menu items jumping around when the description wraps.
        option_area_height = min(len(options), max(6, usable_height // 2))
        body_budget = max(0, usable_height - option_area_height - 1)
        view = rendered_body[scroll : scroll + body_budget]
        for line in view:
            if y >= self.height - 2:
                break
            self.stdscr.addnstr(y, 0, line, self.width - 1)
            y += 1

        divider_y = min(self.height - 2, max(2, 2 + body_budget))
        if divider_y < self.height - 1:
            self.stdscr.hline(divider_y, 0, curses.ACS_HLINE, self.width - 1)

        options_y = min(self.height - 2, divider_y + 1)
        visible_count = max(1, self.height - options_y - 1)
        option_start = 0
        if len(options) > visible_count and selected_index >= visible_count:
            option_start = max(0, selected_index - visible_count + 1)

        visible_options = options[option_start : option_start + visible_count]
        y = options_y
        for idx, label in enumerate(visible_options, start=option_start):
            if y >= self.height - 1:
                break
            prefix = "  "
            attr = curses.A_NORMAL
            if idx == selected_index:
                prefix = "▸ "
                attr = curses.A_REVERSE
            if multi_selected is not None:
                prefix += "[x] " if idx in multi_selected else "[ ] "
            rendered = (prefix + label)[: self.width - 1]
            self.stdscr.addnstr(y, 0, rendered, self.width - 1, attr)
            y += 1
        self.stdscr.refresh()

    def _wait_key(self) -> str | int:
        key = self.stdscr.get_wch()
        return key

    def text_input(self, title: str, prompt: str, default: str = "") -> Optional[str]:
        buffer = list(str(default or ""))
        cursor = len(buffer)
        self._safe_cursor(1)
        while True:
            self.refresh_size()
            self.stdscr.erase()
            self.stdscr.addnstr(0, 0, title[: self.width - 1], self.width - 1, curses.A_BOLD)
            prompt_lines = self._wrap_lines(prompt)
            y = 2
            for line in prompt_lines:
                if y >= self.height - 3:
                    break
                self.stdscr.addnstr(y, 1, line, self.width - 2)
                y += 1
            if y < self.height - 2:
                y += 1

            input_width = max(10, self.width - 4)
            text = "".join(buffer)
            start = 0
            if cursor >= input_width:
                start = cursor - input_width + 1
            visible = text[start : start + input_width]
            self.stdscr.addnstr(y, 1, visible, self.width - 2)
            try:
                self.stdscr.move(y, 1 + cursor - start)
            except curses.error:
                pass
            footer = "Enter 提交 | Esc 返回 | ← → 移动 | Backspace 删除"
            self.stdscr.addnstr(self.height - 1, 0, footer[: self.width - 1], self.width - 1, curses.A_DIM)
            self.stdscr.refresh()

            key = self._wait_key()
            if key in ("\n", "\r") or key == curses.KEY_ENTER:
                self._safe_cursor(0)
                return "".join(buffer).strip()
            if key == "\x1b":
                self._safe_cursor(0)
                return None
            if key in (curses.KEY_LEFT,) and cursor > 0:
                cursor -= 1
                continue
            if key in (curses.KEY_RIGHT,) and cursor < len(buffer):
                cursor += 1
                continue
            if key in (curses.KEY_HOME,):
                cursor = 0
                continue
            if key in (curses.KEY_END,):
                cursor = len(buffer)
                continue
            if key in (curses.KEY_BACKSPACE, "\b", "\x7f"):
                if cursor > 0:
                    del buffer[cursor - 1]
                    cursor -= 1
                continue
            if key == curses.KEY_DC:
                if cursor < len(buffer):
                    del buffer[cursor]
                continue
            if isinstance(key, str) and key.isprintable():
                buffer.insert(cursor, key)
                cursor += 1

    def menu(
        self,
        title: str,
        description: str,
        options: Sequence[tuple[str, str]],
        *,
        default: int = 0,
    ) -> Optional[str]:
        index = min(max(default, 0), max(0, len(options) - 1))
        scroll = 0
        self._safe_cursor(0)
        while True:
            labels = [label for _, label in options]
            footer = "↑ ↓ 选择 | Enter 确认 | Esc 返回"
            self._draw_lines(title, self._wrap_lines(description), scroll=scroll, footer=footer, options=labels, selected_index=index)
            key = self._wait_key()
            if key in ("\n", "\r") or key == curses.KEY_ENTER:
                return options[index][0]
            if key == "\x1b":
                return None
            if key in (curses.KEY_UP, "k"):
                index = (index - 1) % len(options)
                continue
            if key in (curses.KEY_DOWN, "j"):
                index = (index + 1) % len(options)
                continue
            if key == curses.KEY_PPAGE:
                index = max(0, index - 5)
                continue
            if key == curses.KEY_NPAGE:
                index = min(len(options) - 1, index + 5)
                continue
            if key == curses.KEY_RESIZE:
                self.refresh_size()

    def multi_select(
        self,
        title: str,
        description: str,
        options: Sequence[tuple[str, str]],
        *,
        selected_values: Optional[Iterable[str]] = None,
    ) -> Optional[list[str]]:
        selected = {
            idx for idx, (value, _) in enumerate(options) if value in set(selected_values or [])
        }
        index = 0
        self._safe_cursor(0)
        while True:
            labels = [label for _, label in options]
            footer = "↑ ↓ 选择 | Space 勾选 | Enter 确认 | Esc 返回"
            self._draw_lines(
                title,
                self._wrap_lines(description),
                footer=footer,
                options=labels,
                selected_index=index,
                multi_selected=selected,
            )
            key = self._wait_key()
            if key in ("\n", "\r") or key == curses.KEY_ENTER:
                return [options[idx][0] for idx in sorted(selected)]
            if key == "\x1b":
                return None
            if key in (curses.KEY_UP, "k"):
                index = (index - 1) % len(options)
                continue
            if key in (curses.KEY_DOWN, "j"):
                index = (index + 1) % len(options)
                continue
            if key == " ":
                if index in selected:
                    selected.remove(index)
                else:
                    selected.add(index)

    def view_text(self, title: str, text: str) -> None:
        scroll = 0
        self._safe_cursor(0)
        while True:
            footer = "↑ ↓ 滚动 | Enter 返回 | Esc 返回"
            self._draw_lines(title, self._wrap_lines(text), scroll=scroll, footer=footer)
            key = self._wait_key()
            if key in ("\n", "\r", "\x1b") or key == curses.KEY_ENTER:
                return
            if key == curses.KEY_UP:
                scroll = max(0, scroll - 1)
                continue
            if key == curses.KEY_DOWN:
                scroll += 1
                continue
            if key == curses.KEY_PPAGE:
                scroll = max(0, scroll - 5)
                continue
            if key == curses.KEY_NPAGE:
                scroll += 5

    def confirm(self, title: str, text: str, *, yes_label: str = "确认", no_label: str = "返回") -> bool:
        result = self.menu(
            title,
            text,
            [("yes", yes_label), ("no", no_label)],
            default=0,
        )
        return result == "yes"


class InitTuiWizard:
    def __init__(
        self,
        form: InitForm,
        *,
        init_func: Optional[Callable[..., None]] = None,
    ) -> None:
        self.form = form
        self.init_func = init_func or init_project_module.init_project
        self.ui: Optional[TerminalUI] = None

    def run(self) -> int:
        return int(curses.wrapper(self._run_curses))

    def _run_curses(self, stdscr: curses.window) -> int:
        stdscr.keypad(True)
        self.ui = TerminalUI(stdscr)
        while True:
            selection = self.ui.menu(
                "webnovel-init TUI",
                "使用 ↑ ↓ 选择分区，Enter 进入。\nEsc 默认返回上一层；在主菜单按 Esc 可退出。\n\n"
                + format_summary(self.form),
                self._menu_options(),
                default=0,
            )
            if selection is None:
                if self.ui.confirm("退出初始化", "放弃当前 TUI 初始化流程？"):
                    return 1
                continue

            if selection in SECTION_ORDER:
                if self._run_section_sequence(selection):
                    return 0
                continue
            if selection == "review":
                if self._review_and_generate():
                    return 0
                continue
            if selection == "quit":
                if self.ui.confirm("退出初始化", "放弃当前 TUI 初始化流程？"):
                    return 1

    def _menu_options(self) -> list[tuple[str, str]]:
        return [
            ("basic", self._section_label("basic", self._basic_complete())),
            ("protagonist", self._section_label("protagonist", self._protagonist_complete())),
            ("golden_finger", self._section_label("golden_finger", self._golden_finger_complete())),
            ("world", self._section_label("world", self._world_complete())),
            ("rag_config", self._section_label("rag_config", self._rag_config_complete())),
            ("review", self._review_label()),
            ("quit", "退出"),
        ]

    def _section_label(self, section: str, completed: bool) -> str:
        marker = "✓" if completed else "·"
        mode = "系统协助" if is_system_assisted(self.form, section) else "手动填写"
        return f"{marker} {SECTION_TITLES[section]} [{mode}]"

    def _review_label(self) -> str:
        ready = "✓" if not missing_required_fields(self.form) else "·"
        return f"{ready} 预览并生成"

    def _basic_complete(self) -> bool:
        if is_system_assisted(self.form, "basic"):
            return True
        return bool(
            self.form.title.strip()
            and self.form.project_dir.strip()
            and resolve_genre_value(self.form)
            and self.form.target_words > 0
            and self.form.target_chapters > 0
        )

    def _protagonist_complete(self) -> bool:
        if is_system_assisted(self.form, "protagonist"):
            return True
        return bool(
            self.form.protagonist_name.strip()
            and self.form.protagonist_desire.strip()
            and self.form.protagonist_flaw.strip()
            and (
                self.form.protagonist_structure != "多主角" or self.form.co_protagonists.strip()
            )
            and (self.form.heroine_config == "无女主" or self.form.heroine_names.strip())
        )

    def _golden_finger_complete(self) -> bool:
        if is_system_assisted(self.form, "golden_finger"):
            return True
        return bool(self.form.golden_finger_type.strip())

    def _world_complete(self) -> bool:
        if is_system_assisted(self.form, "world"):
            return True
        return bool(self.form.world_scale.strip() and self.form.power_system_type.strip())

    def _rag_config_complete(self) -> bool:
        return True

    def _section_header(self, section: str, text: str) -> str:
        mode = "系统协助我填写" if is_system_assisted(self.form, section) else "手动填写"
        note = str(self.form.assist_notes.get(section, "") or "").strip()
        note_line = f"\n当前系统提示: {note}" if note else ""
        return (
            f"{text}\n\n"
            f"当前模式: {mode}\n"
            "每个分区底部都可以切换“系统协助我填写 / 手动填写”。\n"
            "Esc 默认返回上一级。"
            f"{note_line}"
        )

    def _run_section_sequence(self, start_section: str) -> bool:
        start_index = SECTION_ORDER.index(start_section)
        handlers: dict[str, Callable[[], bool]] = {
            "basic": self._edit_basic,
            "protagonist": self._edit_protagonist,
            "golden_finger": self._edit_golden_finger,
            "world": self._edit_world,
            "rag_config": self._edit_rag_config,
        }
        for section in SECTION_ORDER[start_index:]:
            completed = handlers[section]()
            if not completed:
                return False
        return self._review_and_generate()

    def _display_value(self, value: str, fallback: str = "未填写") -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        if len(text) > 26:
            return text[:23] + "..."
        return text

    def _set_section_mode(self, section: str, mode: str) -> None:
        assert self.ui is not None
        self.form.assist_modes[section] = mode
        if mode == "system":
            note = self.ui.text_input(
                f"{SECTION_TITLES[section]} / 系统协助",
                "可选：告诉 Codex 你希望它优先优化什么。\n"
                "例如“偏男频爽感”“设定要克制”“女主别套路化”。",
                default=self.form.assist_notes.get(section, ""),
            )
            if note is not None:
                self.form.assist_notes[section] = note.strip()
        else:
            self.form.assist_notes[section] = ""

    def _select_or_custom(
        self,
        title: str,
        text: str,
        options: Iterable[str],
        *,
        current: str,
    ) -> Optional[str]:
        assert self.ui is not None
        option_list = list(options)
        labels = [(value, value) for value in option_list] + [(CUSTOM_VALUE, "自定义输入")]
        default_idx = 0
        if current in option_list:
            default_idx = option_list.index(current)
        elif current:
            default_idx = len(labels) - 1
        selected = self.ui.menu(title, text, labels, default=default_idx)
        if selected is None:
            return None
        if selected == CUSTOM_VALUE:
            custom = self.ui.text_input(title, "请输入自定义内容", default=current if current not in option_list else "")
            if custom is None:
                return None
            return custom.strip()
        return selected

    def _refresh_project_dir_if_needed(self, old_workspace: str, old_title: str) -> None:
        old_suggested_dir = suggest_project_dir(old_workspace, old_title) if old_title else ""
        new_suggested_dir = suggest_project_dir(self.form.workspace_root, self.form.title)
        if not self.form.project_dir or self.form.project_dir == old_suggested_dir:
            self.form.project_dir = new_suggested_dir

    def _prompt_text(self, title: str, prompt: str, default: str = "") -> Optional[str]:
        assert self.ui is not None
        return self.ui.text_input(title, prompt, default=default)

    def _prompt_positive_int(self, title: str, prompt: str, default: int) -> Optional[int]:
        assert self.ui is not None
        while True:
            raw = self.ui.text_input(title, prompt, default=str(default))
            if raw is None:
                return None
            value = str(raw).strip()
            if value.isdigit() and int(value) > 0:
                return int(value)
            self.ui.view_text("输入错误", f"请输入大于 0 的整数，当前收到：{value or '空值'}")

    def _prompt_section_mode(self, section: str) -> bool:
        assert self.ui is not None
        current = "assist_system" if is_system_assisted(self.form, section) else "assist_manual"
        default = 1 if current == "assist_system" else 0
        selection = self.ui.menu(
            SECTION_TITLES[section],
            "本分区填写完毕。\n请选择本分区最终模式。\n"
            "如果选择“系统协助我填写”，后续 Codex 会根据本分区记录给出优化建议。",
            [
                ("assist_manual", "手动填写"),
                ("assist_system", "系统协助我填写"),
            ],
            default=default,
        )
        if selection is None:
            return False
        self._set_section_mode(section, "system" if selection == "assist_system" else "manual")
        return True

    def _edit_basic(self) -> bool:
        assert self.ui is not None
        old_workspace = self.form.workspace_root
        old_title = self.form.title
        value = self._prompt_text("基础信息", self._section_header("basic", "问题 1/9：工作区根目录"), self.form.workspace_root)
        if value is None:
            return False
        if value.strip():
            self.form.workspace_root = value.strip()
            self._refresh_project_dir_if_needed(old_workspace, old_title)

        old_workspace = self.form.workspace_root
        old_title = self.form.title
        value = self._prompt_text("基础信息", self._section_header("basic", "问题 2/9：书名"), self.form.title)
        if value is None:
            return False
        self.form.title = value.strip()
        self._refresh_project_dir_if_needed(old_workspace, old_title)

        value = self._prompt_text(
            "基础信息",
            self._section_header("basic", "问题 3/9：项目目录\n默认按书名生成，也可以手改。"),
            self.form.project_dir or suggest_project_dir(self.form.workspace_root, self.form.title or "webnovel-project"),
        )
        if value is None:
            return False
        self.form.project_dir = value.strip()

        selected = self.ui.multi_select(
            "基础信息",
            self._section_header("basic", "问题 4/9：题材选择\nSpace 勾选，Enter 确认；多个题材会自动拼成复合题材。"),
            [*((item, item) for item in GENRE_OPTIONS), (CUSTOM_VALUE, "自定义题材")],
            selected_values=self.form.genres,
        )
        if selected is None:
            return False
        self.form.genres = selected
        if CUSTOM_VALUE in self.form.genres or self.form.custom_genre:
            custom = self._prompt_text(
                "基础信息",
                self._section_header("basic", "问题 4.1/9：自定义题材\n多个题材可用 + 或逗号分隔。"),
                self.form.custom_genre,
            )
            if custom is None:
                return False
            self.form.custom_genre = custom.strip()
        else:
            self.form.custom_genre = ""

        target_words = self._prompt_positive_int("基础信息", self._section_header("basic", "问题 5/9：目标总字数"), self.form.target_words)
        if target_words is None:
            return False
        self.form.target_words = target_words

        target_chapters = self._prompt_positive_int("基础信息", self._section_header("basic", "问题 6/9：目标总章节数"), self.form.target_chapters)
        if target_chapters is None:
            return False
        self.form.target_chapters = target_chapters

        value = self._select_or_custom("基础信息", self._section_header("basic", "问题 7/9：发布平台"), PLATFORM_OPTIONS, current=self.form.platform)
        if value is None:
            return False
        self.form.platform = value

        value = self._prompt_text(
            "基础信息",
            self._section_header("basic", "问题 8/9：目标读者\n例如：男频升级流、女频情绪流、悬疑向读者。"),
            self.form.target_reader,
        )
        if value is None:
            return False
        self.form.target_reader = value.strip()

        value = self._prompt_text(
            "基础信息",
            self._section_header("basic", "问题 9/9：核心卖点\n建议 1-3 条，用逗号分隔。"),
            self.form.core_selling_points,
        )
        if value is None:
            return False
        self.form.core_selling_points = value.strip()
        return self._prompt_section_mode("basic")

    def _edit_protagonist(self) -> bool:
        assert self.ui is not None
        prompt_map = [
            ("protagonist_name", "问题 1/10：主角名"),
            ("protagonist_desire", "问题 2/10：主角欲望\n主角最想得到什么？"),
            ("protagonist_flaw", "问题 3/10：主角缺陷\n什么弱点会让他付出代价？"),
            ("protagonist_archetype", "问题 4/10：主角人设类型\n例如：成长型 / 复仇型 / 天才流。"),
        ]
        for attr, prompt in prompt_map:
            value = self._prompt_text("角色与冲突", self._section_header("protagonist", prompt), getattr(self.form, attr))
            if value is None:
                return False
            setattr(self.form, attr, value.strip())

        value = self._select_or_custom(
            "角色与冲突",
            self._section_header("protagonist", "问题 5/10：主角结构"),
            PROTAGONIST_STRUCTURE_OPTIONS,
            current=self.form.protagonist_structure,
        )
        if value is None:
            return False
        self.form.protagonist_structure = value
        if value != "多主角":
            self.form.co_protagonists = ""
            self.form.co_protagonist_roles = ""

        value = self._select_or_custom(
            "角色与冲突",
            self._section_header("protagonist", "问题 6/10：女主配置"),
            HEROINE_CONFIG_OPTIONS,
            current=self.form.heroine_config,
        )
        if value is None:
            return False
        self.form.heroine_config = value
        if value == "无女主":
            self.form.heroine_names = ""
            self.form.heroine_role = ""

        if self.form.heroine_config != "无女主":
            value = self._prompt_text("角色与冲突", self._section_header("protagonist", "问题 7/10：女主姓名\n多个名字用逗号分隔。"), self.form.heroine_names)
            if value is None:
                return False
            self.form.heroine_names = value.strip()

            value = self._prompt_text("角色与冲突", self._section_header("protagonist", "问题 8/10：女主定位\n例如：事业线 / 情感线 / 对抗线。"), self.form.heroine_role)
            if value is None:
                return False
            self.form.heroine_role = value.strip()
        else:
            self.form.heroine_names = ""
            self.form.heroine_role = ""

        if self.form.protagonist_structure == "多主角":
            value = self._prompt_text("角色与冲突", self._section_header("protagonist", "问题 9/10：多主角名单\n多个名字用逗号分隔。"), self.form.co_protagonists)
            if value is None:
                return False
            self.form.co_protagonists = value.strip()

            value = self._prompt_text("角色与冲突", self._section_header("protagonist", "问题 10/10：多主角分工\n多个角色分工可用逗号分隔。"), self.form.co_protagonist_roles)
            if value is None:
                return False
            self.form.co_protagonist_roles = value.strip()
        else:
            self.form.co_protagonists = ""
            self.form.co_protagonist_roles = ""

        value = self._prompt_text("角色与冲突", self._section_header("protagonist", "补充：反派等级概述"), self.form.antagonist_level)
        if value is None:
            return False
        self.form.antagonist_level = value.strip()

        value = self._prompt_text("角色与冲突", self._section_header("protagonist", "补充：反派分层\n格式示例：小反派:张三;中反派:李四;大反派:王五"), self.form.antagonist_tiers)
        if value is None:
            return False
        self.form.antagonist_tiers = value.strip()
        return self._prompt_section_mode("protagonist")

    def _edit_golden_finger(self) -> bool:
        assert self.ui is not None
        value = self._select_or_custom(
            "金手指",
            self._section_header("golden_finger", "问题 1/5：金手指类型"),
            GF_TYPE_OPTIONS,
            current=self.form.golden_finger_type,
        )
        if value is None:
            return False
        self.form.golden_finger_type = value
        if value == "无金手指":
            self.form.golden_finger_name = ""

        value = self._prompt_text(
            "金手指",
            self._section_header("golden_finger", "问题 2/5：金手指名称\n例如：系统名、器灵名、外挂代号。"),
            self.form.golden_finger_name,
        )
        if value is None:
            return False
        self.form.golden_finger_name = value.strip()

        value = self._prompt_text(
            "金手指",
            self._section_header("golden_finger", "问题 3/5：金手指风格\n例如：冷漠工具型 / 毒舌吐槽型。"),
            self.form.golden_finger_style,
        )
        if value is None:
            return False
        self.form.golden_finger_style = value.strip()

        value = self._select_or_custom(
            "金手指",
            self._section_header("golden_finger", "问题 4/5：金手指可见度"),
            GF_VISIBILITY_OPTIONS,
            current=self.form.gf_visibility,
        )
        if value is None:
            return False
        self.form.gf_visibility = value

        value = self._prompt_text(
            "金手指",
            self._section_header("golden_finger", "问题 5/5：不可逆代价\n没有的话也建议写清原因。"),
            self.form.gf_irreversible_cost,
        )
        if value is None:
            return False
        self.form.gf_irreversible_cost = value.strip()
        return self._prompt_section_mode("golden_finger")

    def _edit_world(self) -> bool:
        assert self.ui is not None
        value = self._select_or_custom(
            "世界观与规则",
            self._section_header("world", "问题 1/9：世界规模"),
            WORLD_SCALE_OPTIONS,
            current=self.form.world_scale,
        )
        if value is None:
            return False
        self.form.world_scale = value

        fields = [
            ("power_system_type", "问题 2/9：力量体系类型\n例如：修仙境界制 / 异能序列制 / 规则代价制。"),
            ("factions", "问题 3/9：核心势力格局\n例如：三大仙门、皇朝、地下商会。"),
            ("social_class", "问题 4/9：社会阶层"),
            ("resource_distribution", "问题 5/9：资源分配规则"),
            ("currency_system", "问题 6/9：货币体系"),
            ("currency_exchange", "问题 7/9：货币兑换规则"),
            ("sect_hierarchy", "问题 8/9：宗门 / 组织层级"),
            ("cultivation_chain", "问题 9/9：典型境界链"),
            ("cultivation_subtiers", "补充：小境界划分"),
        ]
        for attr, prompt in fields:
            value = self._prompt_text("世界观与规则", self._section_header("world", prompt), getattr(self.form, attr))
            if value is None:
                return False
            setattr(self.form, attr, value.strip())
        return self._prompt_section_mode("world")

    def _edit_rag_config(self) -> bool:
        assert self.ui is not None
        selection = self.ui.menu(
            "Embedding / Reranker",
            self._section_header(
                "rag_config",
                "问题 1/6：项目级配置写入方式\n默认配置已预填好；API Key 会直接在下面询问。",
            ),
            [
                ("write_env", "现在写入项目级 .env"),
                ("example_only", "只保留 .env.example，稍后再配"),
            ],
            default=0 if self.form.write_env_file else 1,
        )
        if selection is None:
            return False
        self.form.write_env_file = selection == "write_env"

        if self.form.write_env_file:
            value = self._prompt_text(
                "Embedding / Reranker",
                self._section_header(
                    "rag_config",
                    "问题 2/6：EMBED_API_KEY\n直接填你的 Embedding API Key。可留空，后续再补。",
                ),
                self.form.embed_api_key,
            )
            if value is None:
                return False
            self.form.embed_api_key = value.strip()

            value = self._prompt_text(
                "Embedding / Reranker",
                self._section_header(
                    "rag_config",
                    "问题 3/6：RERANK_API_KEY\n直接填你的 Reranker API Key。可留空，后续再补。",
                ),
                self.form.rerank_api_key,
            )
            if value is None:
                return False
            self.form.rerank_api_key = value.strip()

            advanced_choice = self.ui.menu(
                "Embedding / Reranker",
                self._section_header(
                    "rag_config",
                    "问题 4/6：高级配置\n默认值已经填好。只有你想换服务地址或模型时，才需要进入修改。",
                ),
                [
                    ("keep_defaults", "保持默认 URL / 模型"),
                    ("edit_advanced", "修改高级配置"),
                ],
                default=0,
            )
            if advanced_choice is None:
                return False

            if advanced_choice == "edit_advanced":
                advanced_fields = [
                    ("embed_base_url", "高级配置 1/4：EMBED_BASE_URL", self.form.embed_base_url),
                    ("embed_model", "高级配置 2/4：EMBED_MODEL", self.form.embed_model),
                    ("rerank_base_url", "高级配置 3/4：RERANK_BASE_URL", self.form.rerank_base_url),
                    ("rerank_model", "高级配置 4/4：RERANK_MODEL", self.form.rerank_model),
                ]
                for attr, prompt, current in advanced_fields:
                    value = self._prompt_text(
                        "Embedding / Reranker",
                        self._section_header("rag_config", prompt),
                        current,
                    )
                    if value is None:
                        return False
                    setattr(self.form, attr, value.strip())

        return self._prompt_section_mode("rag_config")

    def _review_and_generate(self) -> bool:
        assert self.ui is not None
        self.ui.view_text("初始化预览", format_summary(self.form))
        missing = missing_required_fields(self.form)
        if missing:
            self.ui.view_text(
                "仍有必填项未完成",
                "请先补齐以下字段后再生成：\n\n- " + "\n- ".join(missing),
            )
            return False

        kwargs = build_init_kwargs(self.form)
        if not self.ui.confirm(
            "确认生成项目",
            "将初始化项目目录：\n"
            f"{kwargs['project_dir']}\n\n"
            "如果某个分区启用了“系统协助我填写”，会自动写入提示元数据供后续 Codex 优化建议使用。",
        ):
            return False

        try:
            self.init_func(**kwargs)
            write_assist_metadata(str(kwargs["project_dir"]), self.form, kwargs)
        except Exception as exc:
            self.ui.view_text("初始化失败", f"{type(exc).__name__}: {exc}")
            return False

        self.ui.view_text(
            "初始化完成",
            "项目已创建。\n\n"
            f"项目目录: {kwargs['project_dir']}\n"
            f"题材: {kwargs['genre']}\n"
            f"主角: {kwargs['protagonist_name']}\n\n"
            "如果你启用了“系统协助我填写”，相关提示已经写入 `.webnovel/state.json` 和 `设定集/初始化偏好.md`。",
        )
        return True


def _initial_genres(raw: str) -> tuple[list[str], str]:
    selected: list[str] = []
    custom: list[str] = []
    known = set(GENRE_OPTIONS)
    for item in _split_multi_values(raw):
        if item in known:
            selected.append(item)
        else:
            custom.append(item)
    if custom:
        selected.append(CUSTOM_VALUE)
    return selected, "+".join(custom)


def build_initial_form(args: argparse.Namespace) -> InitForm:
    workspace_root = str(Path(args.workspace_root).expanduser().resolve())
    genres, custom_genre = _initial_genres(args.genre)
    project_dir = args.project_dir or (suggest_project_dir(workspace_root, args.title) if args.title else "")
    return InitForm(
        workspace_root=workspace_root,
        title=args.title or "",
        project_dir=project_dir,
        genres=genres,
        custom_genre=custom_genre,
        target_words=int(args.target_words),
        target_chapters=int(args.target_chapters),
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TUI wizard for webnovel-init")
    parser.add_argument("--workspace-root", default=str(Path.cwd()), help="小说工作区根目录")
    parser.add_argument("--project-dir", default="", help="预填项目目录")
    parser.add_argument("--title", default="", help="预填书名")
    parser.add_argument("--genre", default="", help="预填题材，支持 A+B")
    parser.add_argument("--target-words", type=int, default=2_000_000, help="预填目标总字数")
    parser.add_argument("--target-chapters", type=int, default=600, help="预填目标总章节数")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit("TUI 模式需要在真实终端中运行。请在 shell 中执行 `python webnovel.py init --tui`。")
    if sys.platform == "win32":
        raise SystemExit("当前 TUI 版本依赖 curses，暂不支持 Windows 终端。")

    args = parse_args(argv)
    form = build_initial_form(args)
    wizard = InitTuiWizard(form)
    return int(wizard.run())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
