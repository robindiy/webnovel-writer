#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-init helpers shared by chat and shell driven init flows."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from data_modules.config import DataModulesConfig


DEFAULT_RAG_ENV = {
    "EMBED_BASE_URL": "https://api-inference.modelscope.cn/v1",
    "EMBED_MODEL": "Qwen/Qwen3-Embedding-8B",
    "EMBED_API_KEY": "your_embed_api_key",
    "RERANK_BASE_URL": "https://api.jina.ai/v1",
    "RERANK_MODEL": "jina-reranker-v3",
    "RERANK_API_KEY": "your_rerank_api_key",
}


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> Path:
    _ensure_parent(path)
    path.write_text(content, encoding="utf-8")
    return path


def build_default_rag_env(*, embed_api_key: str = "", rerank_api_key: str = "") -> dict[str, str]:
    env = dict(DEFAULT_RAG_ENV)
    env["EMBED_API_KEY"] = str(embed_api_key or "").strip()
    env["RERANK_API_KEY"] = str(rerank_api_key or "").strip()
    return env


def _parse_env_lines(raw_text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in str(raw_text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def parse_rag_key_block(raw_text: str) -> dict[str, str]:
    parsed = _parse_env_lines(raw_text)
    if "EMBED_API_KEY" in parsed or "RERANK_API_KEY" in parsed:
        embed_key = parsed.get("EMBED_API_KEY", "")
        rerank_key = parsed.get("RERANK_API_KEY", "")
    else:
        lines = [line.strip() for line in str(raw_text or "").splitlines() if line.strip()]
        if len(lines) < 2:
            raise ValueError("请至少提供两行，分别对应 EMBED_API_KEY 和 RERANK_API_KEY。")
        embed_key, rerank_key = lines[:2]
    return build_default_rag_env(embed_api_key=embed_key, rerank_api_key=rerank_key)


def parse_full_rag_env_block(raw_text: str) -> dict[str, str]:
    parsed = _parse_env_lines(raw_text)
    missing = [key for key in DEFAULT_RAG_ENV if key not in parsed]
    if missing:
        raise ValueError(f"缺少字段：{', '.join(missing)}")
    return {key: str(parsed.get(key, "")).strip() for key in DEFAULT_RAG_ENV}


def render_env_content(env_values: dict[str, str]) -> str:
    merged = dict(DEFAULT_RAG_ENV)
    merged.update({key: str(value or "").strip() for key, value in dict(env_values).items()})
    lines = [
        "# Webnovel Writer 项目级 RAG 配置",
        "# 由 Codex init controller 生成",
        "",
        "# Embedding",
        f"EMBED_BASE_URL={merged['EMBED_BASE_URL']}",
        f"EMBED_MODEL={merged['EMBED_MODEL']}",
        f"EMBED_API_KEY={merged['EMBED_API_KEY']}",
        "",
        "# Rerank",
        f"RERANK_BASE_URL={merged['RERANK_BASE_URL']}",
        f"RERANK_MODEL={merged['RERANK_MODEL']}",
        f"RERANK_API_KEY={merged['RERANK_API_KEY']}",
        "",
    ]
    return "\n".join(lines)


def write_project_env(project_root: str | Path, env_values: dict[str, str]) -> Path:
    root = Path(project_root).expanduser().resolve()
    return _write_text(root / ".env", render_env_content(env_values))


def read_project_env(project_root: str | Path) -> dict[str, str]:
    env_path = Path(project_root).expanduser().resolve() / ".env"
    if not env_path.is_file():
        return {}
    return _parse_env_lines(_read_text(env_path))


def build_idea_bank_payload(payload: dict[str, Any]) -> dict[str, Any]:
    project = payload.get("project") or {}
    protagonist = payload.get("protagonist") or {}
    relationship = payload.get("relationship") or {}
    constraints = payload.get("constraints") or {}
    package = constraints.get("selected_package") or {}
    return {
        "selected_idea": {
            "title": package.get("title") or project.get("title", ""),
            "one_liner": package.get("one_liner") or project.get("one_liner", ""),
            "anti_trope": constraints.get("anti_trope") or package.get("anti_trope", ""),
            "hard_constraints": list(constraints.get("hard_constraints") or package.get("hard_constraints") or []),
        },
        "constraints_inherited": {
            "anti_trope": constraints.get("anti_trope") or package.get("anti_trope", ""),
            "hard_constraints": list(constraints.get("hard_constraints") or package.get("hard_constraints") or []),
            "protagonist_flaw": protagonist.get("flaw", ""),
            "antagonist_mirror": relationship.get("antagonist_mirror", ""),
            "opening_hook": constraints.get("opening_hook") or package.get("opening_hook", ""),
        },
    }


def write_idea_bank(project_root: str | Path, payload: dict[str, Any]) -> Path:
    root = Path(project_root).expanduser().resolve()
    target = root / ".webnovel" / "idea_bank.json"
    _ensure_parent(target)
    target.write_text(json.dumps(build_idea_bank_payload(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


OUTLINE_SECTION_TITLE = "## 初始化锁定信息"


def _derive_outline_lines(payload: dict[str, Any]) -> list[str]:
    project = payload.get("project") or {}
    protagonist = payload.get("protagonist") or {}
    relationship = payload.get("relationship") or {}
    golden_finger = payload.get("golden_finger") or {}
    world = payload.get("world") or {}
    constraints = payload.get("constraints") or {}
    package = constraints.get("selected_package") or {}
    selling_points = list(constraints.get("core_selling_points") or [])[:3]
    core_dark_line = relationship.get("antagonist_mirror") or constraints.get("opening_hook") or "（待卷规划细化）"
    return [
        OUTLINE_SECTION_TITLE,
        "",
        f"- 故事一句话：{project.get('one_liner', '')}",
        f"- 核心主线：{project.get('core_conflict', '')}",
        f"- 核心暗线：{core_dark_line}",
        f"- 主角驱动力：{protagonist.get('desire', '')}｜缺陷：{protagonist.get('flaw', '')}",
        f"- 金手指：{golden_finger.get('type', '')}｜代价：{golden_finger.get('irreversible_cost', '')}",
        f"- 世界框架：{world.get('scale', '')}｜{world.get('power_system_type', '')}｜{world.get('factions', '')}",
        f"- 创意约束：反套路={constraints.get('anti_trope') or package.get('anti_trope', '')}",
        f"- 硬约束：{'；'.join(constraints.get('hard_constraints') or package.get('hard_constraints') or [])}",
        f"- 反派分层：{relationship.get('antagonist_tiers') or relationship.get('antagonist_level', '')}",
        "- 关键爽点里程碑：",
        *[f"  - {item}" for item in selling_points],
        "",
    ]


def patch_master_outline(project_root: str | Path, payload: dict[str, Any]) -> Path:
    root = Path(project_root).expanduser().resolve()
    outline_path = root / "大纲" / "总纲.md"
    if not outline_path.is_file():
        raise FileNotFoundError(f"Missing outline: {outline_path}")
    original = _read_text(outline_path)
    replacement = "\n".join(_derive_outline_lines(payload)).strip() + "\n"
    if OUTLINE_SECTION_TITLE in original:
        updated = re.sub(
            rf"{re.escape(OUTLINE_SECTION_TITLE)}\n.*?(?=\n## |\Z)",
            replacement.rstrip(),
            original,
            flags=re.S,
        )
    else:
        lines = original.splitlines()
        insert_idx = 1
        while insert_idx < len(lines) and (not lines[insert_idx].strip() or lines[insert_idx].lstrip().startswith(">")):
            insert_idx += 1
        updated_lines = lines[:insert_idx] + ["", replacement.rstrip(), ""] + lines[insert_idx:]
        updated = "\n".join(updated_lines).rstrip() + "\n"
    outline_path.write_text(updated, encoding="utf-8")
    return outline_path


def verify_init_outputs(project_root: str | Path) -> list[str]:
    root = Path(project_root).expanduser().resolve()
    errors: list[str] = []

    state_path = root / ".webnovel" / "state.json"
    if not state_path.is_file():
        errors.append("missing-state.json")
    else:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append("invalid-state.json")
        else:
            meta = state.get("project_meta") or state.get("project_info") or {}
            for key in ("title", "genre", "target_words", "target_chapters"):
                if not meta.get(key):
                    errors.append(f"missing-project-meta:{key}")

    for relative in (
        "设定集/世界观.md",
        "设定集/力量体系.md",
        "设定集/主角卡.md",
        "设定集/金手指设计.md",
        "大纲/总纲.md",
        ".webnovel/idea_bank.json",
        ".env.example",
        ".env",
    ):
        if not (root / relative).is_file():
            errors.append(f"missing-file:{relative}")

    outline_path = root / "大纲" / "总纲.md"
    if outline_path.is_file():
        outline_text = _read_text(outline_path)
        for token in ("故事一句话", "核心主线", "核心暗线", "创意约束", "反派分层", "关键爽点里程碑"):
            if token not in outline_text:
                errors.append(f"outline-missing:{token}")

    idea_bank_path = root / ".webnovel" / "idea_bank.json"
    if idea_bank_path.is_file():
        try:
            json.loads(idea_bank_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append("invalid-idea_bank.json")

    env_values = read_project_env(root)
    for key in DEFAULT_RAG_ENV:
        if key not in env_values:
            errors.append(f"env-missing:{key}")
    if env_values:
        cfg = DataModulesConfig.from_project_root(root)
        if cfg.embed_base_url != env_values.get("EMBED_BASE_URL", ""):
            errors.append("env-not-loaded:EMBED_BASE_URL")
        if cfg.embed_model != env_values.get("EMBED_MODEL", ""):
            errors.append("env-not-loaded:EMBED_MODEL")
        if cfg.rerank_base_url != env_values.get("RERANK_BASE_URL", ""):
            errors.append("env-not-loaded:RERANK_BASE_URL")
        if cfg.rerank_model != env_values.get("RERANK_MODEL", ""):
            errors.append("env-not-loaded:RERANK_MODEL")

    return errors
