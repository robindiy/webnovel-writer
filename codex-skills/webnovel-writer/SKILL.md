---
name: webnovel-writer
description: "Codex adapter for the webnovel-writer plugin. Use when the user references or runs /webnovel-writer:webnovel-init, /webnovel-writer:webnovel-plan, /webnovel-writer:webnovel-write, /webnovel-writer:webnovel-review, /webnovel-writer:webnovel-dashboard, /webnovel-writer:webnovel-query, /webnovel-writer:webnovel-resume, or /webnovel-writer:webnovel-learn. Preserves original slash-command usage while delegating to the repository's existing workflow docs and scripts."
---

# Webnovel Writer for Codex

Use the installed helper to normalize the user's command before taking action.

## Command Resolution

1. Read the user's exact slash command or fallback command text.
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
