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
   - If `action.type` is `follow_skill`, open the returned `skill_path` from the repository and follow that workflow.
   - If `action.type` is `start_dashboard`, the user likely wants the dashboard launched; rerun the helper with `--execute-dashboard` if they confirm.

## Compatibility Rules

- Preserve the original `/webnovel-writer:*` command wording in user-visible messages.
- Prefer `python3` or the resolved interpreter; do not rely on bare `python`.
- Treat the repository skill docs as the source of truth for creative workflow behavior.
- Use the helper's resolved `project_root` when a command requires an existing book project.
