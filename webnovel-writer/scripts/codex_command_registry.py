#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-source command registry for Codex and shell fallback entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
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


COMMAND_SPECS: Dict[str, CommandSpec] = {
    "webnovel-init": CommandSpec("webnovel-init", "webnovel-init", requires_project=False, shell_aliases=("init",)),
    "webnovel-plan": CommandSpec("webnovel-plan", "webnovel-plan", shell_aliases=("plan",)),
    "webnovel-write": CommandSpec("webnovel-write", "webnovel-write", shell_aliases=("write",)),
    "webnovel-review": CommandSpec("webnovel-review", "webnovel-review", shell_aliases=("review",)),
    "webnovel-dashboard": CommandSpec("webnovel-dashboard", "webnovel-dashboard", shell_aliases=("dashboard",)),
    "webnovel-query": CommandSpec("webnovel-query", "webnovel-query", shell_aliases=("query",)),
    "webnovel-resume": CommandSpec("webnovel-resume", "webnovel-resume", shell_aliases=("resume",)),
    "webnovel-learn": CommandSpec("webnovel-learn", "webnovel-learn", requires_project=False, shell_aliases=("learn",)),
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
    return ParsedCommand(
        name=spec.name,
        args=normalized_args,
        slash_command=slash_command,
        skill_name=spec.skill_name,
        skill_path=_skills_root() / spec.skill_name / "SKILL.md",
        requires_project=spec.requires_project,
    )


def parse_command_text(text: str) -> ParsedCommand:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Missing webnovel command text")

    if not raw.startswith(COMMAND_PREFIX):
        raise ValueError(f"Unsupported command format: {raw}")

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

    canonical_name = _alias_map().get(first)
    if canonical_name is None:
        raise ValueError(f"Unknown webnovel command: {first}")

    return _build_parsed_command(COMMAND_SPECS[canonical_name], argv[1:])
