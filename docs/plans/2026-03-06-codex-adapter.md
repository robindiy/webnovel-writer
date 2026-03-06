# Codex Webnovel Adapter Implementation Plan

> **Execution note:** Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Build a Codex-compatible adapter for `webnovel-writer` that preserves the original `/webnovel-writer:*` command contract while fixing interpreter and Python-version compatibility issues.

**Architecture:** Keep the existing Python data/workflow core as the execution engine, add a single-source command registry plus a Codex adapter CLI on top, and ship a Codex skill installer so users can invoke original slash commands from Codex desktop while using a shell fallback when needed.

**Tech Stack:** Python 3.9+, argparse, existing `webnovel-writer` scripts/data modules, Codex skills packaging, FastAPI/uvicorn dashboard.

---

### Task 1: Lock down runtime compatibility

**Files:**
- Modify: `webnovel-writer/scripts/runtime_compat.py`
- Modify: `webnovel-writer/dashboard/server.py`
- Modify: `webnovel-writer/dashboard/app.py`
- Modify: `webnovel-writer/dashboard/watcher.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_runtime_compat.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_dashboard_imports.py`

**Step 1: Write the failing test**

Add tests that:
- import `dashboard.server`, `dashboard.app`, and `dashboard.watcher` under Python 3.9
- verify a new interpreter resolver returns a usable Python executable path

**Step 2: Run test to verify it fails**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_runtime_compat.py \
  webnovel-writer/scripts/data_modules/tests/test_dashboard_imports.py -v
```

Expected:
- import failure or compatibility failure before the code change

**Step 3: Write minimal implementation**

- replace Python 3.10-only type annotations with `Optional`, `List`, `Union`
- add an interpreter resolution helper that prefers `sys.executable`, then `python3`, then `python`
- centralize subprocess interpreter usage through that helper

**Step 4: Run test to verify it passes**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_runtime_compat.py \
  webnovel-writer/scripts/data_modules/tests/test_dashboard_imports.py -v
```

Expected:
- all added tests pass

**Step 5: Checkpoint**

- Confirm dashboard modules import cleanly on Python 3.9
- Do not commit unless explicitly requested by the user

### Task 2: Add a single-source Codex command registry

**Files:**
- Create: `webnovel-writer/scripts/codex_command_registry.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_codex_command_registry.py`

**Step 1: Write the failing test**

Add tests covering:
- parsing `/webnovel-writer:webnovel-init`
- parsing `/webnovel-writer:webnovel-write 1`
- mapping shell fallback input to the same logical command
- rejecting unknown slash commands with a user-friendly error

**Step 2: Run test to verify it fails**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_codex_command_registry.py -v
```

Expected:
- module missing or parser behavior failing

**Step 3: Write minimal implementation**

- define a registry data structure for supported commands
- parse literal slash commands and shell fallback forms
- expose normalized command objects to the adapter layer

**Step 4: Run test to verify it passes**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_codex_command_registry.py -v
```

Expected:
- all command parsing tests pass

**Step 5: Checkpoint**

- Confirm the registry is the only place that knows slash/fallback mappings
- Do not commit unless explicitly requested by the user

### Task 3: Add the Codex adapter CLI

**Files:**
- Create: `webnovel-writer/scripts/codex_cli.py`
- Create: `webnovel-writer/scripts/codex_interaction.py`
- Modify: `webnovel-writer/scripts/webnovel.py` (only if shared helpers are needed)
- Test: `webnovel-writer/scripts/data_modules/tests/test_codex_cli.py`

**Step 1: Write the failing test**

Add tests covering:
- `codex_cli.py` dispatches normalized commands to the existing core
- interactive commands can return structured options for Codex dialogue mode
- shell mode can print fallback menus without requiring Codex UI support

**Step 2: Run test to verify it fails**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_codex_cli.py -v
```

Expected:
- module missing or dispatch behavior failing

**Step 3: Write minimal implementation**

- add a CLI that accepts either:
  - a literal slash command string
  - a normalized fallback command
- route execution into the existing `webnovel.py` / workflow scripts
- add a small interaction abstraction:
  - `mode=codex` returns numbered options
  - `mode=shell` prints numbered menus

**Step 4: Run test to verify it passes**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_codex_cli.py -v
```

Expected:
- dispatch and interaction tests pass

**Step 5: Checkpoint**

- Confirm adapter output is stable and user-facing
- Do not commit unless explicitly requested by the user

### Task 4: Package a Codex skill that understands original slash commands

**Files:**
- Create: `codex-skills/webnovel-writer/SKILL.md`
- Create: `codex-skills/webnovel-writer/agents/openai.yaml`
- Create: `codex-skills/webnovel-writer/scripts/run_webnovel_command.py`
- Test: `codex-skills/webnovel-writer/scripts/test_install_skill_smoke.py`

**Step 1: Write the failing test**

Add a smoke test that:
- resolves the installed repo root/config
- verifies the skill helper can invoke the Codex adapter CLI

**Step 2: Run test to verify it fails**

Run:

```bash
pytest codex-skills/webnovel-writer/scripts/test_install_skill_smoke.py -v
```

Expected:
- helper missing or configuration resolution failing

**Step 3: Write minimal implementation**

- create a Codex skill whose trigger text explicitly includes `/webnovel-writer:*`
- add a helper script that loads the stored repo root and delegates to `codex_cli.py`
- keep the skill concise and focused on command delegation, not business logic duplication

**Step 4: Run test to verify it passes**

Run:

```bash
pytest codex-skills/webnovel-writer/scripts/test_install_skill_smoke.py -v
```

Expected:
- skill helper smoke test passes

**Step 5: Checkpoint**

- Confirm skill trigger text mentions original slash commands
- Do not commit unless explicitly requested by the user

### Task 5: Add an installer and shell fallback wrapper

**Files:**
- Create: `scripts/install_codex_support.py`
- Create: `scripts/webnovel-codex`
- Test: `webnovel-writer/scripts/data_modules/tests/test_install_codex_support.py`

**Step 1: Write the failing test**

Add tests covering:
- install script writes the Codex skill files into a target directory
- install script records repo root/config for later invocation
- shell wrapper forwards a literal slash command string to `codex_cli.py`

**Step 2: Run test to verify it fails**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_install_codex_support.py -v
```

Expected:
- installer or wrapper missing

**Step 3: Write minimal implementation**

- create an installer that:
  - copies/symlinks the skill bundle
  - stores repo root metadata
  - installs or emits the shell wrapper path
- create `webnovel-codex` as the shell fallback entrypoint

**Step 4: Run test to verify it passes**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_install_codex_support.py -v
```

Expected:
- installer and wrapper tests pass

**Step 5: Checkpoint**

- Confirm a user can install without touching any upstream cache directories
- Do not commit unless explicitly requested by the user

### Task 6: Update docs and acceptance checks

**Files:**
- Modify: `README.md`
- Modify: `docs/commands.md`
- Modify: `docs/architecture.md`
- Modify: `docs/rag-and-config.md`

**Step 1: Write the failing doc checklist**

Create a checklist and verify the docs currently do not explain:
- Codex installation
- original slash compatibility in Codex
- shell fallback usage
- Python 3.9/3.10 compatibility expectations

**Step 2: Run the checklist manually**

Run:

```bash
rg -n "Codex|webnovel-codex|/webnovel-writer:" README.md docs/commands.md docs/architecture.md docs/rag-and-config.md
```

Expected:
- missing or incomplete Codex guidance

**Step 3: Write minimal documentation**

- document installation
- document Codex desktop slash usage
- document shell fallback usage
- document Python and RAG requirements

**Step 4: Run focused verification**

Run:

```bash
pytest \
  webnovel-writer/scripts/data_modules/tests/test_runtime_compat.py \
  webnovel-writer/scripts/data_modules/tests/test_dashboard_imports.py \
  webnovel-writer/scripts/data_modules/tests/test_codex_command_registry.py \
  webnovel-writer/scripts/data_modules/tests/test_codex_cli.py \
  webnovel-writer/scripts/data_modules/tests/test_install_codex_support.py -v
```

Expected:
- targeted Codex-adapter test suite passes

**Step 5: Run broader regression verification**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_webnovel_unified_cli.py \
  webnovel-writer/scripts/data_modules/tests/test_project_locator.py \
  webnovel-writer/scripts/data_modules/tests/test_workflow_manager.py -v
```

Expected:
- no regressions in shared CLI/project resolution paths

**Step 6: Checkpoint**

- Confirm docs match actual commands and install flow
- Do not commit unless explicitly requested by the user
