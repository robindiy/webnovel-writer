# Post-Init Clipboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** After a successful init, copy `cd "<project_dir>"` to the clipboard and guide the user to paste it, while updating docs to explain all six `.env` fields clearly.

**Architecture:** Keep init generation unchanged, but add a post-success handoff layer in `init_terminal_ui.py`. That layer will attempt system clipboard copy with a small helper, then print either a success hint or a fallback copyable command. Update user docs to align with that new flow and to fully explain `.env`.

**Tech Stack:** Python 3.9+, subprocess-based clipboard detection, pytest, Markdown docs.

---

### Task 1: Lock clipboard handoff behavior with tests

**Files:**
- Modify: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`

**Step 1: Write the failing test**

- Add a test that successful init triggers clipboard copy with `cd "<project_dir>"`.
- Add a test that clipboard failure prints a fallback command.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q`

Expected: FAIL because post-init clipboard handoff does not exist yet.

**Step 3: Write minimal implementation**

- Add a clipboard helper.
- Add a post-init handoff method in `InitWizard.run()`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q`

Expected: PASS.

### Task 2: Add clipboard helper with graceful fallback

**Files:**
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`

**Step 1: Write the failing test**

- Add tests for supported clipboard commands and fallback behavior.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q`

Expected: FAIL on missing helper behavior.

**Step 3: Write minimal implementation**

- Try `pbcopy`, `clip`, `wl-copy`, `xclip`, `xsel`.
- Return success/failure to the caller.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q`

Expected: PASS.

### Task 3: Update docs for copy-paste flow and `.env` explanation

**Files:**
- Modify: `README.md`
- Modify: `docs/codex-install.md`

**Step 1: Update post-init flow**

- Replace placeholder/path-reasoning wording with:
  - program copied `cd "..."` already
  - paste and press Enter

**Step 2: Expand `.env` section**

- Explain all 6 fields and how they map to provider URL/model/key.

**Step 3: Verify docs are aligned with runtime**

- Check that the runtime and README now describe the same steps in the same order.

### Task 4: Full verification and reinstall

**Files:**
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`
- Modify: `README.md`
- Modify: `docs/codex-install.md`

**Step 1: Run focused regression**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py webnovel-writer/scripts/data_modules/tests/test_init_source_loader.py webnovel-writer/scripts/data_modules/tests/test_codex_cli.py webnovel-writer/scripts/data_modules/tests/test_install_codex_support.py webnovel-writer/scripts/data_modules/tests/test_runtime_compat.py -q`

Expected: PASS.

**Step 2: Run compile check**

Run: `python3 -m py_compile webnovel-writer/scripts/init_terminal_ui.py webnovel-writer/scripts/init_source_loader.py webnovel-writer/scripts/codex_cli.py`

Expected: exit code 0.

**Step 3: Smoke + reinstall**

Run:

```bash
python3 scripts/smoke_test_codex_support.py
python3 scripts/install_codex_support.py
```

Expected: smoke status is `ok`, installed wrapper points to current worktree.
