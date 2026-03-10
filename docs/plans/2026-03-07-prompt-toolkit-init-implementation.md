# Prompt Toolkit Init TUI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current handwritten ANSI shell init UI with a stable `prompt_toolkit` full-screen TUI for `webnovel-init`.

**Architecture:** Keep `InitWizard` as the source-backed business workflow and replace only the shell interaction host. Add a `PromptToolkitIO` adapter with fixed-height scrollable menus, candidate-to-manual-input transitions, and back/cancel navigation. Preserve `init_project.py` payload mapping and keep a minimal non-TTY fallback.

**Tech Stack:** Python 3, `prompt_toolkit`, pytest

---

### Task 1: Add dependency and guard rails

**Files:**
- Modify: `webnovel-writer/scripts/requirements.txt`
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`

**Step 1: Write the failing test**

Add tests asserting:

- `prompt_toolkit` path is preferred when available in TTY mode
- non-TTY mode still uses plain fallback

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q -k prompt_toolkit
```

Expected:
- FAIL because `PromptToolkitIO` path does not exist yet

**Step 3: Write minimal implementation**

- add `prompt_toolkit>=3.0.0` to `webnovel-writer/scripts/requirements.txt`
- add runtime import guard in `init_terminal_ui.py`
- keep plain fallback path for non-TTY / missing dependency

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q -k prompt_toolkit
```

Expected:
- PASS

### Task 2: Build fixed-height menu screen

**Files:**
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`

**Step 1: Write the failing test**

Add tests covering:

- menu renders in a fixed-height viewport
- long option lists scroll inside the viewport
- moving selection does not append duplicate menu frames to shell history strings

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q -k viewport
```

Expected:
- FAIL because current menu host still redraws frame-by-frame into stdout

**Step 3: Write minimal implementation**

- introduce `PromptToolkitIO.choose()`
- use `prompt_toolkit` full-screen application
- implement fixed-height radio-list style selector with internal scrolling

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q -k viewport
```

Expected:
- PASS

### Task 3: Implement candidate-to-manual-input transition

**Files:**
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`

**Step 1: Write the failing test**

Add tests covering:

- `choose_or_enter` style fields first show candidate list
- selecting `手动输入` opens a text input screen
- the input screen keeps field title and guidance text visible

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q -k manual_input
```

Expected:
- FAIL because current implementation still splits text vs. choose in a simpler host

**Step 3: Write minimal implementation**

- add prompt-toolkit text input view
- pass source-backed hint lines into the input screen
- wire `手动输入` to transition into text entry

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q -k manual_input
```

Expected:
- PASS

### Task 4: Add back/cancel navigation

**Files:**
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`

**Step 1: Write the failing test**

Add tests covering:

- `Esc` returns from manual input to candidate selection
- back navigation preserves current answers
- cancel exits once, without duplicate cancellation output

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q -k back
```

Expected:
- FAIL because current UI path is one-shot stdin based

**Step 3: Write minimal implementation**

- add back stack inside `PromptToolkitIO`
- handle `Esc` and `Ctrl+C`
- keep current outer helper cancellation behavior intact

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q -k back
```

Expected:
- PASS

### Task 5: Reconnect `InitWizard` to the new host

**Files:**
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_codex_cli.py`

**Step 1: Write the failing test**

Add tests covering:

- `run_shell_init_wizard()` uses prompt-toolkit host in normal TTY mode
- `InitWizard.collect()` still returns the same payload shape
- `webnovel-init` shell path still dispatches correctly

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py webnovel-writer/scripts/data_modules/tests/test_codex_cli.py -q
```

Expected:
- FAIL because the new host is not fully wired

**Step 3: Write minimal implementation**

- instantiate `PromptToolkitIO` from `run_shell_init_wizard()`
- keep fake IO testability for `InitWizard`
- leave codex JSON / non-init behavior unchanged

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py webnovel-writer/scripts/data_modules/tests/test_codex_cli.py -q
```

Expected:
- PASS

### Task 6: Update docs for the new TUI host

**Files:**
- Modify: `README.md`
- Modify: `docs/codex-install.md`
- Modify: `docs/commands.md`

**Step 1: Write doc updates**

Document:

- shell init now uses `prompt_toolkit` TUI
- first install requires Python dependencies from `requirements.txt`
- fallback behavior when dependency is missing

**Step 2: Verify doc examples**

Run:

```bash
python3 scripts/smoke_test_codex_support.py
```

Expected:
- PASS

### Task 7: Full verification

**Files:**
- Verify: `webnovel-writer/scripts/init_terminal_ui.py`
- Verify: `webnovel-writer/scripts/init_source_loader.py`
- Verify: `webnovel-writer/scripts/codex_cli.py`
- Verify: `codex-skills/webnovel-writer/scripts/run_webnovel_command.py`

**Step 1: Run syntax verification**

```bash
python3 -m py_compile \
  webnovel-writer/scripts/init_source_loader.py \
  webnovel-writer/scripts/init_terminal_ui.py \
  webnovel-writer/scripts/codex_cli.py \
  webnovel-writer/scripts/runtime_compat.py \
  codex-skills/webnovel-writer/scripts/run_webnovel_command.py
```

**Step 2: Run targeted tests**

```bash
python3 -m pytest --no-cov \
  webnovel-writer/scripts/data_modules/tests/test_runtime_compat.py \
  webnovel-writer/scripts/data_modules/tests/test_init_source_loader.py \
  webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py \
  webnovel-writer/scripts/data_modules/tests/test_codex_cli.py \
  webnovel-writer/scripts/data_modules/tests/test_codex_command_registry.py \
  webnovel-writer/scripts/data_modules/tests/test_install_codex_support.py \
  codex-skills/webnovel-writer/scripts/test_install_skill_smoke.py -q
```

**Step 3: Run smoke test**

```bash
python3 scripts/smoke_test_codex_support.py
```

Expected:
- all pass

