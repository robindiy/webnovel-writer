#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-source command registry for Codex and shell fallback entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
import re
from typing import Dict, Iterable, Sequence, Tuple


COMMAND_PREFIX = "/webnovel-writer:"


@dataclass(frozen=True)
class CommandSpec:
    name: str
    skill_name: str
    requires_project: bool = True
    shell_aliases: Tuple[str, ...] = ()

    @property
    def slash_name(self) -> str:
        return f"{COMMAND_PREFIX}{self.name}"


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: Tuple[str, ...]
    slash_command: str
    skill_name: str
    skill_path: Path
    requires_project: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _skills_root() -> Path:
    return _repo_root() / "skills"


def _codex_skills_root() -> Path:
    return _repo_root().parent / "codex-skills"


COMMAND_SPECS: Dict[str, CommandSpec] = {
    "webnovel-init": CommandSpec("webnovel-init", "webnovel-init", requires_project=False, shell_aliases=("init",)),
    "webnovel-plan": CommandSpec("webnovel-plan", "webnovel-plan", shell_aliases=("plan",)),
    "webnovel-write": CommandSpec("webnovel-write", "webnovel-write", shell_aliases=("write",)),
    "webnovel-review": CommandSpec("webnovel-review", "webnovel-review", shell_aliases=("review",)),
    "webnovel-dashboard": CommandSpec("webnovel-dashboard", "webnovel-dashboard", shell_aliases=("dashboard",)),
    "webnovel-query": CommandSpec("webnovel-query", "webnovel-query", shell_aliases=("query",)),
    "webnovel-resume": CommandSpec("webnovel-resume", "webnovel-resume", shell_aliases=("resume",)),
    "webnovel-learn": CommandSpec("webnovel-learn", "webnovel-learn", requires_project=False, shell_aliases=("learn",)),
    "webnovel-controller-demo": CommandSpec(
        "webnovel-controller-demo",
        "webnovel-writer",
        shell_aliases=("controller-demo",),
    ),
}


def _alias_map() -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for name, spec in COMMAND_SPECS.items():
        aliases[name] = name
        for alias in spec.shell_aliases:
            aliases[alias] = name
    return aliases


def _build_parsed_command(spec: CommandSpec, args: Iterable[str]) -> ParsedCommand:
    normalized_args = tuple(str(arg) for arg in args)
    slash_command = " ".join([spec.slash_name, *normalized_args]).strip()
    skill_root = _codex_skills_root() if spec.skill_name == "webnovel-writer" else _skills_root()
    return ParsedCommand(
        name=spec.name,
        args=normalized_args,
        slash_command=slash_command,
        skill_name=spec.skill_name,
        skill_path=skill_root / spec.skill_name / "SKILL.md",
        requires_project=spec.requires_project,
    )


def _extract_range_arg(raw: str, unit: str) -> Tuple[str, ...]:
    text = str(raw or "")
    range_match = re.search(rf"第?\s*(\d+)\s*(?:到|至|\-|—|~)\s*(\d+)\s*{unit}", text)
    if range_match:
        return (f"{range_match.group(1)}-{range_match.group(2)}",)

    single_match = re.search(rf"第?\s*(\d+)\s*{unit}", text)
    if single_match:
        return (single_match.group(1),)

    return ()


def _contains_command_name(raw: str, command_name: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9_-]){re.escape(command_name)}(?![A-Za-z0-9_-])"
    return re.search(pattern, str(raw or ""), flags=re.IGNORECASE) is not None


def _parse_natural_language_text(text: str) -> ParsedCommand:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Missing webnovel command text")

    explicit_map = (
        ("webnovel-init", ()),
        ("webnovel-dashboard", ()),
        ("webnovel-resume", ()),
        ("webnovel-learn", ()),
    )
    for command_name, args in explicit_map:
        if _contains_command_name(raw, command_name):
            return _build_parsed_command(COMMAND_SPECS[command_name], args)

    if _contains_command_name(raw, "webnovel-write"):
        return _build_parsed_command(COMMAND_SPECS["webnovel-write"], _extract_range_arg(raw, "章"))
    shorthand_match = re.fullmatch(r"webnovel-writer\s+(\d+)(?:\s+--(fast|minimal))?", raw, flags=re.IGNORECASE)
    if shorthand_match:
        extra = tuple(filter(None, (shorthand_match.group(1), f"--{shorthand_match.group(2)}" if shorthand_match.group(2) else None)))
        return _build_parsed_command(COMMAND_SPECS["webnovel-write"], extra)
    if _contains_command_name(raw, "webnovel-review"):
        return _build_parsed_command(COMMAND_SPECS["webnovel-review"], _extract_range_arg(raw, "章"))
    if _contains_command_name(raw, "webnovel-plan"):
        return _build_parsed_command(COMMAND_SPECS["webnovel-plan"], _extract_range_arg(raw, "卷"))
    if _contains_command_name(raw, "webnovel-query"):
        return _build_parsed_command(COMMAND_SPECS["webnovel-query"], ())

    normalized = raw.casefold()
    if "初始化" in raw and any(keyword in raw for keyword in ("小说", "项目", "书")):
        return _build_parsed_command(COMMAND_SPECS["webnovel-init"], ())
    if any(keyword in raw for keyword in ("规划", "计划")) and "卷" in raw:
        return _build_parsed_command(COMMAND_SPECS["webnovel-plan"], _extract_range_arg(raw, "卷"))
    if any(keyword in raw for keyword in ("写", "生成")) and "章" in raw:
        return _build_parsed_command(COMMAND_SPECS["webnovel-write"], _extract_range_arg(raw, "章"))
    if any(keyword in raw for keyword in ("审查", "审核", "复查", "review")) and "章" in raw:
        return _build_parsed_command(COMMAND_SPECS["webnovel-review"], _extract_range_arg(raw, "章"))
    if "dashboard" in normalized or "面板" in raw:
        return _build_parsed_command(COMMAND_SPECS["webnovel-dashboard"], ())
    if any(phrase in raw for phrase in ("开始控制器测试", "运行控制器验证")) or "controller demo" in normalized:
        return _build_parsed_command(COMMAND_SPECS["webnovel-controller-demo"], ())
    if any(keyword in raw for keyword in ("查询", "检索")):
        return _build_parsed_command(COMMAND_SPECS["webnovel-query"], ())
    if any(keyword in raw for keyword in ("恢复", "继续")) and any(keyword in raw for keyword in ("任务", "流程", "工作流")):
        return _build_parsed_command(COMMAND_SPECS["webnovel-resume"], ())

    raise ValueError(f"Unknown webnovel command: {raw}")


def parse_command_text(text: str) -> ParsedCommand:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Missing webnovel command text")

    if not raw.startswith(COMMAND_PREFIX):
        return _parse_natural_language_text(raw)

    tokens = shlex.split(raw)
    if not tokens:
        raise ValueError("Missing webnovel command name")

    command_token = tokens[0][len(COMMAND_PREFIX):]
    spec = COMMAND_SPECS.get(command_token)
    if spec is None:
        raise ValueError(f"Unknown webnovel command: {command_token}")

    return _build_parsed_command(spec, tokens[1:])


def parse_argv(argv: Sequence[str]) -> ParsedCommand:
    if not argv:
        raise ValueError("Missing webnovel command")

    first = str(argv[0]).strip()
    if not first:
        raise ValueError("Missing webnovel command")

    if first.startswith(COMMAND_PREFIX):
        return parse_command_text(" ".join(str(part) for part in argv if str(part).strip()))

    lowered_first = first.casefold()
    if lowered_first == "webnovel-writer" and len(argv) > 1:
        second = str(argv[1]).strip()
        if second.isdigit():
            return _build_parsed_command(COMMAND_SPECS["webnovel-write"], argv[1:])

    canonical_name = _alias_map().get(first)
    if canonical_name is None:
        return _parse_natural_language_text(" ".join(str(part) for part in argv if str(part).strip()))

    return _build_parsed_command(COMMAND_SPECS[canonical_name], argv[1:])
