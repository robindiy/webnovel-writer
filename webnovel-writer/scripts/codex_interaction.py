#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interaction helpers shared by Codex desktop and shell fallback flows."""

from __future__ import annotations

from typing import Iterable, Mapping


def render_numbered_options(title: str, prompt: str, options: Iterable[Mapping[str, str]]) -> str:
    lines = [title.strip(), "", prompt.strip()]
    for index, option in enumerate(options, start=1):
        label = str(option.get("label", "")).strip()
        description = str(option.get("description", "")).strip()
        if description:
            lines.append(f"{index}. {label} — {description}")
        else:
            lines.append(f"{index}. {label}")
    return "\n".join(lines).strip()
