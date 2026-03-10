#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal controller session engine for Codex-managed flows."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from . import demo_flow, init_flow, session_store


FLOW_REGISTRY = {
    demo_flow.CONTROLLER_NAME: demo_flow,
    init_flow.CONTROLLER_NAME: init_flow,
}


def _flow(controller: str):
    resolved = FLOW_REGISTRY.get(str(controller).strip())
    if resolved is None:
        raise ValueError(f"Unknown controller: {controller}")
    return resolved


def start_session(*, project_root: str | Path, controller: str = demo_flow.CONTROLLER_NAME) -> dict[str, Any]:
    flow = _flow(controller)
    session = flow.new_session(project_root)
    session_store.save_session(project_root, controller, session)
    return session


def load_session(*, project_root: str | Path, controller: str = demo_flow.CONTROLLER_NAME) -> Optional[dict[str, Any]]:
    return session_store.load_session(project_root, controller)


def load_active_session(project_root: str | Path) -> Optional[dict[str, Any]]:
    for controller in FLOW_REGISTRY:
        session = load_session(project_root=project_root, controller=controller)
        if session and session.get("active"):
            return session
    return None


def advance_session(
    *,
    project_root: str | Path,
    controller: str = demo_flow.CONTROLLER_NAME,
    user_input: object,
) -> dict[str, Any]:
    flow = _flow(controller)
    session = load_session(project_root=project_root, controller=controller)
    if session is None:
        raise FileNotFoundError(f"No controller session found for {controller}")
    updated = flow.apply_input(session, user_input)
    session_store.save_session(project_root, controller, updated)
    return updated


def finish_session(
    *,
    project_root: str | Path,
    controller: str = demo_flow.CONTROLLER_NAME,
    step_id: str = "finished",
) -> dict[str, Any]:
    flow = _flow(controller)
    session = load_session(project_root=project_root, controller=controller)
    if session is None:
        session = flow.new_session(project_root)
    finished = flow.force_finish(session, step_id=step_id)
    session_store.save_session(project_root, controller, finished)
    return finished


def build_action(session: dict[str, Any]) -> dict[str, Any]:
    flow = _flow(str(session.get("controller", "")).strip())
    return flow.build_controller_action(session)


def command_name(session: dict[str, Any]) -> str:
    flow = _flow(str(session.get("controller", "")).strip())
    return str(getattr(flow, "COMMAND_NAME", "")).strip()
