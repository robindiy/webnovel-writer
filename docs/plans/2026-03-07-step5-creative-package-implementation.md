# Step 5 Creative Package Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend Step 5 so it keeps the dynamic 3 recommended packages, then adds `系统推荐` and `自定义`, with safe return-to-Step-5 behavior.

**Architecture:** Keep the existing source-backed package generation path intact and layer two action entries on top of the Step 5 menu. Route those actions through small helper methods in `init_terminal_ui.py`, reusing the already collected project/protagonist/world caches to build recommendation reasons and custom candidates.

**Tech Stack:** Python 3.9+, `prompt_toolkit`, existing shell/prompt abstraction, pytest.

---

### Task 1: Lock the new Step 5 menu behavior with tests

**Files:**
- Modify: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`

**Step 1: Write the failing tests**

- Add a test that Step 5 appends `系统推荐` and `自定义` after the dynamic package list.
- Add a test that choosing `系统推荐` shows a reason prompt and returns to Step 5 if rejected.
- Add a test that choosing `自定义` asks for one-line direction input and then shows 2-3 generated candidates.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q`

Expected: FAIL on missing Step 5 option expansion behavior.

**Step 3: Write minimal implementation**

- Add Step 5 helper methods for menu construction and branching.
- Reuse the existing caches to build reasons and custom candidates.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q`

Expected: PASS.

### Task 2: Implement system recommendation reasoning

**Files:**
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`

**Step 1: Write the failing test**

- Add a test that the recommendation reason includes current genre and at least one context factor such as conflict/flaw/world scale.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q`

Expected: FAIL because no recommendation reason builder exists yet.

**Step 3: Write minimal implementation**

- Implement a helper that picks the current best candidate and renders a short reason block.
- Add a confirmation branch with `采用该推荐` / `返回 Step 5`.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q`

Expected: PASS.

### Task 3: Implement custom-direction candidate generation

**Files:**
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`

**Step 1: Write the failing test**

- Add a test that custom mode asks for one-line direction and generates 2-3 labeled candidates.
- Add a test that rejecting custom candidates returns to the Step 5 main menu.

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q`

Expected: FAIL because custom candidate flow does not exist yet.

**Step 3: Write minimal implementation**

- Implement a deterministic local candidate generator using:
  - current genre
  - current one-liner
  - current conflict
  - protagonist flaw
  - user-provided direction
- Produce 2-3 options and feed them back through the existing `choose()` flow.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q`

Expected: PASS.

### Task 4: Verify full regression and wrapper install

**Files:**
- Modify: `webnovel-writer/scripts/init_terminal_ui.py`
- Modify: `docs/commands.md` (only if Step 5 behavior needs user-facing notes)
- Modify: `README.md` (only if Step 5 behavior needs user-facing notes)

**Step 1: Run focused regression**

Run: `python3 -m pytest --no-cov webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py webnovel-writer/scripts/data_modules/tests/test_init_source_loader.py webnovel-writer/scripts/data_modules/tests/test_codex_cli.py webnovel-writer/scripts/data_modules/tests/test_install_codex_support.py webnovel-writer/scripts/data_modules/tests/test_runtime_compat.py -q`

Expected: PASS.

**Step 2: Run compile smoke**

Run: `python3 -m py_compile webnovel-writer/scripts/init_terminal_ui.py webnovel-writer/scripts/init_source_loader.py webnovel-writer/scripts/codex_cli.py`

Expected: exit code 0.

**Step 3: Reinstall and smoke**

Run:

```bash
python3 scripts/smoke_test_codex_support.py
python3 scripts/install_codex_support.py
```

Expected: smoke JSON status is `ok`, wrapper points to the current worktree.

**Step 4: Manual verification note**

- Check Step 5 in shell mode:
  - dynamic 3 recommendations still exist
  - `系统推荐` exists
  - `自定义` exists
  - both routes can return to Step 5 safely
