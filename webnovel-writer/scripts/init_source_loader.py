#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load init workflow structure directly from upstream skill sources."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Optional


SCRIPTS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPTS_DIR.parent
SKILL_ROOT = PACKAGE_ROOT / "skills" / "webnovel-init"
SKILL_PATH = SKILL_ROOT / "SKILL.md"
CREATIVITY_ROOT = SKILL_ROOT / "references" / "creativity"
GOLDEN_FINGER_TEMPLATE_PATH = PACKAGE_ROOT / "templates" / "golden-finger-templates.md"


FIELD_KEYWORDS = [
    ("目标读者/平台", "target_reader_platform"),
    ("社会阶层与资源分配", "social_class_resource"),
    ("反派分层与镜像对抗一句话", "antagonist_mirror"),
    ("主角原型标签", "protagonist_archetype"),
    ("多主角分工", "co_protagonist_roles"),
    ("不可逆代价", "gf_irreversible_cost"),
    ("成长节奏", "growth_pacing"),
    ("世界规模", "world_scale"),
    ("力量体系类型", "power_system_type"),
    ("势力格局", "factions"),
    ("货币体系与兑换规则", "currency_system"),
    ("宗门/组织层级", "sect_hierarchy"),
    ("境界链与小境界", "cultivation_chain"),
    ("主角姓名", "protagonist_name"),
    ("主角欲望", "protagonist_desire"),
    ("主角缺陷", "protagonist_flaw"),
    ("主角结构", "protagonist_structure"),
    ("感情线配置", "heroine_config"),
    ("金手指类型", "golden_finger_type"),
    ("名称/系统名", "golden_finger_name"),
    ("系统名", "golden_finger_name"),
    ("风格", "golden_finger_style"),
    ("可见度", "gf_visibility"),
    ("书名", "project_title"),
    ("题材", "genre"),
    ("目标规模", "story_scale"),
    ("一句话故事", "one_liner"),
    ("核心冲突", "core_conflict"),
]


@dataclass
class FieldSpec:
    key: str
    label: str
    required: bool
    options: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class CreativityPackTemplate:
    pack_id: str
    title: str
    rule_constraint: str
    character_conflict: str
    hook: str
    cool_point: str
    section: str


@dataclass
class GenreGuidance:
    genre: str
    selling_point: str = ""
    premise_candidates: list[str] = field(default_factory=list)
    conflict_candidates: list[str] = field(default_factory=list)


@dataclass
class StepSpec:
    id: str
    title: str
    fields: list[FieldSpec] = field(default_factory=list)
    source_text: str = ""


@dataclass
class InitWorkflowSpec:
    steps: list[StepSpec]
    genre_categories: dict[str, list[str]]
    golden_finger_types: list[str]
    golden_finger_visibility_options: list[str]
    constraint_pack_sections: dict[str, list[CreativityPackTemplate]]
    genre_guidance: dict[str, GenreGuidance]
    target_reader_options: list[str]
    platform_options: list[str]
    protagonist_desire_options: list[str]
    protagonist_flaw_options: list[str]
    protagonist_archetype_options: list[str]
    antagonist_mirror_options: list[str]
    power_system_options: list[str]
    faction_options: list[str]
    golden_finger_cost_options: list[str]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_option(value: str) -> str:
    cleaned = value.strip().strip("“”\"'`")
    cleaned = re.sub(r"[，。；;、]+$", "", cleaned)
    if cleaned.endswith("等"):
        cleaned = cleaned[:-1].strip()
    return cleaned


def _extract_note(line: str) -> str:
    match = re.search(r"[（(]([^）)]+)[）)]", line)
    if not match:
        return ""
    return _normalize_spaces(match.group(1))


def _extract_inline_options(line: str) -> list[str]:
    note = _extract_note(line)
    if not note:
        return []
    if "/" not in note and "|" not in note:
        return []
    return [_clean_option(token) for token in re.split(r"[/|]", note) if _clean_option(token)]


def _display_label(line: str) -> str:
    content = line.strip()
    if content.startswith("- "):
        content = content[2:]
    content = re.sub(r"[（(][^）)]+[）)]", "", content)
    return _normalize_spaces(content.strip().rstrip("：:"))


def _field_key_for_label(label: str) -> str:
    for keyword, key in FIELD_KEYWORDS:
        if keyword in label:
            return key
    return re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")


def _section_slices(text: str) -> list[tuple[str, str, str]]:
    matches = list(re.finditer(r"^### (Step \d+)：(.+)$", text, re.MULTILINE))
    sections: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(1), match.group(2).strip(), text[start:end].strip()))
    return sections


def _parse_genre_categories(section_text: str) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {}
    start_match = re.search(r"题材集合（用于归一化与映射）[:：]\s*", section_text)
    if not start_match:
        return categories
    for line in section_text[start_match.end():].splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("交互方式"):
            break
        if not stripped.startswith("- "):
            continue
        body = stripped[2:]
        if "：" not in body:
            continue
        category, values = body.split("：", 1)
        categories[_normalize_spaces(category)] = [
            _clean_option(token)
            for token in values.split("|")
            if _clean_option(token)
        ]
    return categories


def _parse_fields(section_text: str) -> list[FieldSpec]:
    fields: list[FieldSpec] = []
    current_required = True
    for raw_line in section_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("收集项（必收）"):
            current_required = True
            continue
        if stripped.startswith("收集项（可选）"):
            current_required = False
            continue
        if stripped.startswith("收集项（条件必收）"):
            current_required = True
            continue
        if stripped.startswith("题材集合") or stripped.startswith("交互方式") or stripped.startswith("流程") or stripped.startswith("备注"):
            continue
        if not stripped.startswith("- "):
            continue
        label = _display_label(stripped)
        if not label:
            continue
        fields.append(
            FieldSpec(
                key=_field_key_for_label(label),
                label=label,
                required=current_required,
                options=_extract_inline_options(stripped),
                note=_extract_note(stripped),
            )
        )
    return fields


def _parse_markdown_table(table_lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in table_lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        rows.append([part.strip() for part in stripped.strip("|").split("|")])
    if len(rows) < 3:
        return []
    return rows


def _table_after_heading(lines: list[str], start_index: int) -> list[list[str]]:
    for index in range(start_index + 1, len(lines)):
        if lines[index].strip().startswith("|"):
            return _parse_markdown_table(lines[index:])
    return []


def _extract_golden_finger_types() -> list[str]:
    text = _read_text(GOLDEN_FINGER_TEMPLATE_PATH)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "## 📌 类型速查表" not in line:
            continue
        table = _table_after_heading(lines, index)
        return [row[0] for row in table[2:] if row and row[0]]
    return []


def _extract_golden_finger_visibility_options() -> list[str]:
    text = _read_text(GOLDEN_FINGER_TEMPLATE_PATH)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "## ✅ 金手指模板字段（必填）" not in line:
            continue
        table = _table_after_heading(lines, index)
        for row in table[2:]:
            if row and row[0] == "可见度":
                return [_clean_option(part) for part in row[2].split("/") if _clean_option(part)]
    return []


def _parse_constraint_pack_sections() -> dict[str, list[CreativityPackTemplate]]:
    text = _read_text(CREATIVITY_ROOT / "category-constraint-packs.md")
    sections: dict[str, list[CreativityPackTemplate]] = {}
    current_section: Optional[str] = None
    current_pack: Optional[dict[str, str]] = None

    def flush_current_pack() -> None:
        nonlocal current_pack
        if current_section is None or current_pack is None:
            current_pack = None
            return
        sections.setdefault(current_section, []).append(
            CreativityPackTemplate(
                pack_id=current_pack.get("pack_id", ""),
                title=current_pack.get("title", ""),
                rule_constraint=current_pack.get("规则限制", ""),
                character_conflict=current_pack.get("角色矛盾", ""),
                hook=current_pack.get("钩子", ""),
                cool_point=current_pack.get("爽点", ""),
                section=current_section,
            )
        )
        current_pack = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("### "):
            flush_current_pack()
            current_section = stripped[4:].strip()
            continue
        match = re.match(r"^\*\*Pack\s+(\S+)\s+(.+?)\*\*$", stripped)
        if match:
            flush_current_pack()
            current_pack = {"pack_id": match.group(1), "title": match.group(2).strip()}
            continue
        if current_pack and stripped.startswith("- ") and "：" in stripped:
            key, value = stripped[2:].split("：", 1)
            current_pack[_normalize_spaces(key)] = _normalize_spaces(value)
    flush_current_pack()
    return sections


def _dedupe_options(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        cleaned = _clean_option(str(value or ""))
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


def _extract_parenthetical_samples(text: str, keyword: str) -> list[str]:
    pattern = rf"{re.escape(keyword)}.*?:.*?[（(]([^）)]+)[）)]"
    match = re.search(pattern, text)
    if not match:
        return []
    return _dedupe_options(re.split(r"[？?／/、，,]", match.group(1)))


def _extract_market_guidance(skill_root: Path) -> tuple[list[str], list[str]]:
    market_path = skill_root / "references" / "creativity" / "market-positioning.md"
    text = _read_text(market_path)
    platform_matches = re.findall(r"^### 1\.\d+ ([^\n]+)$", text, re.MULTILINE)
    platform_options = []
    for platform in platform_matches:
        normalized = platform.replace("中文网", "").replace("文学城", "").replace("小说", "").strip()
        if normalized:
            platform_options.append(normalized)
    reader_options: list[str] = []
    reader_match = re.search(r"男频（[^）]+）/\s*女频（[^）]+）/\s*通吃型", text)
    if reader_match:
        reader_options = ["男频", "女频", "通吃型"]
    return _dedupe_options(reader_options), _dedupe_options(platform_options)


def _extract_character_guidance(skill_root: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    character_path = skill_root / "references" / "worldbuilding" / "character-design.md"
    text = _read_text(character_path)
    desire_options = _extract_parenthetical_samples(text, "Desire")
    flaw_options = _extract_parenthetical_samples(text, "Flaw")

    archetype_options: list[str] = []
    archetype_match = re.search(r"### 人设模板：网文经典款(.*?)(?:\n## |\Z)", text, re.S)
    if archetype_match:
        archetype_options = re.findall(r"- \*\*([^*]+)\*\*:", archetype_match.group(1))

    mirror_options = _dedupe_options(
        [
            "利益冲突：为争夺资源或地位与你对立",
            "理念之争：与你目标相似，但手段完全相反",
            "宿命之敌：与你互为镜像，深层羁绊",
            "黑化同路人：他走成了你最可能变成的样子",
        ]
    )
    return desire_options, flaw_options, _dedupe_options(archetype_options), mirror_options


def _extract_world_guidance(skill_root: Path) -> tuple[list[str], list[str]]:
    power_path = skill_root / "references" / "worldbuilding" / "power-systems.md"
    faction_path = skill_root / "references" / "worldbuilding" / "faction-systems.md"
    power_text = _read_text(power_path)
    faction_text = _read_text(faction_path)

    power_options = re.findall(r"^### 模板 [A-Z]: ([^\n(]+)", power_text, re.MULTILINE)
    if "## 7. 系统流设计" in power_text:
        power_options.append("系统流")
    faction_options = re.findall(r"^### 模板 \d+: ([^\n]+)$", faction_text, re.MULTILINE)
    return _dedupe_options(power_options), _dedupe_options(faction_options)


def _extract_golden_finger_cost_options() -> list[str]:
    text = _read_text(GOLDEN_FINGER_TEMPLATE_PATH)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "## 📌 类型速查表" not in line:
            continue
        table = _table_after_heading(lines, index)
        return _dedupe_options([row[2] for row in table[2:] if len(row) > 2])
    return []


def _extract_genre_template_guidance() -> dict[str, GenreGuidance]:
    templates_dir = PACKAGE_ROOT / "templates" / "genres"
    guidance: dict[str, GenreGuidance] = {}
    if not templates_dir.exists():
        return guidance

    for path in sorted(templates_dir.glob("*.md")):
        text = _read_text(path)
        selling_point_match = re.search(r">\s+\*\*核心卖点\*\*:\s*(.+)", text)
        selling_point = _normalize_spaces(selling_point_match.group(1)) if selling_point_match else ""

        premise_candidates: list[str] = []
        flow_match = re.search(r"## 1\.[^\n]*\n(.*?)(?:\n## |\Z)", text, re.S)
        if flow_match:
            block = flow_match.group(1)
            section_matches = list(re.finditer(r"^### ([^\n]+)$", block, re.MULTILINE))
            for index, section_match in enumerate(section_matches):
                start = section_match.end()
                end = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(block)
                section_body = block[start:end]
                trait_match = re.search(r"- \*\*(?:特点|核心)\*\*:\s*(.+)", section_body)
                if trait_match:
                    premise_candidates.append(
                        f"{_normalize_spaces(section_match.group(1))}：{_normalize_spaces(trait_match.group(1))}"
                    )

        conflict_candidates = re.findall(r"- \*\*核心冲突\*\*:\s*(.+)", text)
        genre = path.stem
        guidance[genre] = GenreGuidance(
            genre=genre,
            selling_point=selling_point,
            premise_candidates=_dedupe_options(premise_candidates),
            conflict_candidates=_dedupe_options(conflict_candidates),
        )

    return guidance


def load_init_workflow_spec(skill_root: Optional[Path] = None) -> InitWorkflowSpec:
    resolved_skill_root = Path(skill_root).resolve() if skill_root else SKILL_ROOT
    skill_text = _read_text(resolved_skill_root / "SKILL.md")
    steps: list[StepSpec] = []
    genre_categories: dict[str, list[str]] = {}

    for step_id, title, body in _section_slices(skill_text):
        if step_id == "Step 0":
            continue
        fields = _parse_fields(body)
        if step_id == "Step 1":
            genre_categories = _parse_genre_categories(body)
            flattened = [value for values in genre_categories.values() for value in values]
            for field in fields:
                if field.key == "genre":
                    field.options = flattened
        steps.append(StepSpec(id=step_id, title=title, fields=fields, source_text=body))

    golden_finger_types = _extract_golden_finger_types()
    golden_finger_visibility = _extract_golden_finger_visibility_options()
    golden_finger_cost_options = _extract_golden_finger_cost_options()
    constraint_pack_sections = _parse_constraint_pack_sections()
    genre_guidance = _extract_genre_template_guidance()
    target_reader_options, platform_options = _extract_market_guidance(resolved_skill_root)
    protagonist_desire_options, protagonist_flaw_options, protagonist_archetype_options, antagonist_mirror_options = (
        _extract_character_guidance(resolved_skill_root)
    )
    power_system_options, faction_options = _extract_world_guidance(resolved_skill_root)

    for step in steps:
        for field in step.fields:
            if field.key == "golden_finger_type" and golden_finger_types:
                field.options = _dedupe_options(["无金手指", *golden_finger_types])
            if field.key == "gf_visibility" and golden_finger_visibility:
                field.options = golden_finger_visibility

    return InitWorkflowSpec(
        steps=steps,
        genre_categories=genre_categories,
        golden_finger_types=golden_finger_types,
        golden_finger_visibility_options=golden_finger_visibility,
        constraint_pack_sections=constraint_pack_sections,
        genre_guidance=genre_guidance,
        target_reader_options=target_reader_options,
        platform_options=platform_options,
        protagonist_desire_options=protagonist_desire_options,
        protagonist_flaw_options=protagonist_flaw_options,
        protagonist_archetype_options=protagonist_archetype_options,
        antagonist_mirror_options=antagonist_mirror_options,
        power_system_options=power_system_options,
        faction_options=faction_options,
        golden_finger_cost_options=golden_finger_cost_options,
    )
