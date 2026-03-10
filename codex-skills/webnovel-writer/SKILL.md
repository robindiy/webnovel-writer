---
name: webnovel-writer
description: "Use when the user asks to initialize a novel project, plan a volume, write a chapter, review chapters, open the dashboard, resume a workflow, or references command names such as webnovel-init, webnovel-plan, webnovel-write, webnovel-review, webnovel-dashboard, webnovel-query, or webnovel-resume."
---

# Webnovel Writer for Codex

Use the installed helper to normalize the user's command before taking action.

## Command Resolution

1. Read the user's exact command text.
   - In Codex chat, users may describe the action in natural language or mention command names like `webnovel-init`.
   - Raw leading `/webnovel-writer:*` text may be intercepted by Codex before it reaches the model, so do not depend on literal slash input inside the Codex chat box.
2. Run:

```bash
python3 scripts/run_webnovel_command.py --json <original command tokens>
```

3. Interpret the JSON response:
   - If `status` is `needs_input`, present the numbered options to the user and wait.
   - If `action.type` is `external_init`, tell the user `webnovel-init` 已移到外部终端 TUI；直接展示 `action.command`，不要在 Codex 对话里继续初始化问答。
   - If `action.type` is `controller_step`, present `action.message` and the allowed options, then stop for this turn.
   - If `action.type` is `run_source_workflow`, run the provided `action.command_line` exactly as returned. Do not reinterpret the workflow or replace it with free-form skill execution. After the script finishes, report its structured result.
   - If `action.type` is `follow_skill`, open the returned `skill_path` from the repository and follow that workflow.
   - If `action.execution_model` is `desktop_strict_follow_skill`, the returned `action.desktop_contract` is mandatory. Run its `prepare_script` first and then follow the generated manifest/output files stage by stage. Do not start with free-form exploration.
   - If `action.type` is `start_dashboard`, the user likely wants the dashboard launched; rerun the helper with `--execute-dashboard` if they confirm.

## Compatibility Rules

- Preserve the original `/webnovel-writer:*` command wording in user-visible messages.
- Prefer `python3` or the resolved interpreter; do not rely on bare `python`.
- Treat the repository skill docs as the source of truth for creative workflow behavior.
- If helper returns `run_source_workflow`, the script is the source of truth; the skill doc becomes reference material only.
- If `run_source_workflow` has started, do not switch to free-form skill execution, artifact-chain fallback, manual chapter writing, or any other recovery path. The only allowed outcomes are: the script retries inside the same workflow, or the script exits with failure and you stop.
- If helper returns `follow_skill` with `execution_model=desktop_strict_follow_skill`, the repository skill doc plus `action.desktop_contract` are both mandatory. In this mode:
  - Do not directly invoke `review_agents_runner.py` in Codex Desktop.
  - Do not skip `prepare_script`; it defines the prompt/schema/output contract for the next stage.
  - Do not treat Step 2B / Step 4 / Step 5 as markers only; each step must leave the structured artifacts required by the repository skill.
- Use the helper's resolved `project_root` when a command requires an existing book project.
- `webnovel-init` now belongs to the external `prompt_toolkit` TUI. In Codex chat, do not improvise or continue init questionnaires; after init finishes, Codex only handles project-internal planning, writing, review, and补空缺.
- For `controller_step`, do not invoke `follow_skill`, `brainstorming`, or any downstream workflow skill.
- For `controller_step`, do not reinterpret the prompt or ask open-ended design questions; only echo the controller step and its fixed options.
