#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke-test the source-backed init chat controller via codex_cli JSON mode."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "webnovel-writer" / "scripts" / "codex_cli.py"


def _run(workspace_root: Path, *command: str) -> dict:
    env = dict(os.environ)
    env.setdefault("WEBNOVEL_CLAUDE_HOME", str((workspace_root / "fake-home").resolve()))
    proc = subprocess.run(
        [sys.executable, str(CLI_PATH), "--mode", "codex", "--json", "--workspace-root", str(workspace_root), *command],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="codex-init-smoke-") as tmpdir:
        workspace_root = Path(tmpdir).resolve()
        sequence = [
            ("/webnovel-writer:webnovel-init",),
            ("1",),
            ("\n".join(
                [
                    "书名=控制器冒烟测试",
                    "题材=修仙+规则怪谈",
                    "目标规模=80万字 / 240章",
                    "一句话故事=一个底层修士被迫修补失控天道。",
                    "核心冲突=他想活命回家，却不断卷入规则灾难。",
                    "目标读者=男频",
                    "平台=起点",
                ]
            ),),
            ("\n".join(
                [
                    "主角姓名=林观",
                    "主角欲望=活下去并查清真相",
                    "主角缺陷=过度谨慎",
                    "主角结构=单主角",
                    "感情线配置=无",
                    "主角原型=苟道流",
                    "反派分层=小反派:巡检使;中反派:执法堂;大反派:裂天主宰",
                    "反派镜像=黑化同路人：他走成了你最可能变成的样子",
                ]
            ),),
            ("\n".join(
                [
                    "金手指类型=无金手指",
                    "不可逆代价=没有外挂，代价是每次活下来都要失去现实资源",
                    "成长节奏=中速",
                ]
            ),),
            ("\n".join(
                [
                    "世界规模=单城",
                    "力量体系=规则修真",
                    "势力格局=坊市、巡检司、黑市三足鼎立",
                    "社会阶层与资源分配=上层修士垄断资源，底层只能拿寿命换机会",
                    "货币体系=灵石",
                    "兑换规则=一枚上品灵石=100中品=10000下品",
                    "宗门/组织层级=外门、内门、真传、长老",
                    "境界链=炼气-筑基-金丹-元婴",
                    "小境界=初期/中期/后期/圆满",
                ]
            ),),
            ("1",),
            ("1",),
            ("1",),
        ]
        payload = {}
        for item in sequence:
            payload = _run(workspace_root, *item)

        action = payload.get("action") or {}
        if action.get("type") != "controller_step" or not action.get("done"):
            raise SystemExit(f"controller did not finish: {json.dumps(payload, ensure_ascii=False, indent=2)}")

        project_root = workspace_root / "控制器冒烟测试"
        expected = [
            project_root / ".webnovel" / "state.json",
            project_root / ".webnovel" / "idea_bank.json",
            project_root / "大纲" / "总纲.md",
            project_root / ".env.example",
            project_root / ".env",
        ]
        missing = [str(path) for path in expected if not path.is_file()]
        if missing:
            raise SystemExit("missing artifacts: " + ", ".join(missing))

        print(json.dumps({
            "status": "ok",
            "workspace_root": str(workspace_root),
            "project_root": str(project_root),
            "step_id": action.get("step_id"),
            "done": action.get("done"),
        }, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
