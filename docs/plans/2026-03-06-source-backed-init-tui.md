> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

# Source-Backed Init TUI Implementation Plan

## Goal

实现一个由上游 `webnovel-init/SKILL.md` 驱动的终端初始化向导，并把它接入 Codex shell fallback，使初始化流程不再依赖自然语言漂移。

## Task 1: Add tests for source-backed init parsing

**Files:**
- Create: `webnovel-writer/scripts/data_modules/tests/test_init_source_loader.py`
- Create: `webnovel-writer/scripts/init_source_loader.py`

**Step 1: Write the failing test**

Add tests covering:

- loading `skills/webnovel-init/SKILL.md`
- extracting Step 1 ~ Step 6 titles
- extracting Step 1 genre categories and options from source text
- extracting Step 2/3/4 enumerable options from source bullet text

**Step 2: Run test to verify it fails**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_init_source_loader.py -q
```

Expected:
- module missing or extraction behavior failing

**Step 3: Write minimal implementation**

- add a loader that reads `SKILL.md`
- parse step sections by heading
- parse bullet items and inline option groups
- expose a structured spec object

**Step 4: Run test to verify it passes**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_init_source_loader.py -q
```

Expected:
- parsing tests pass

## Task 2: Add tests for terminal wizard flow

**Files:**
- Create: `webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py`
- Create: `webnovel-writer/scripts/init_terminal_ui.py`

**Step 1: Write the failing test**

Add tests covering:

- wizard walks steps in the same order as `SKILL.md`
- wizard uses source-backed option labels for genre and structured enum fields
- wizard builds a backend payload matching `init_project.py` inputs
- wizard stops before generation if final confirmation is rejected

**Step 2: Run test to verify it fails**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q
```

Expected:
- module missing or behavior failing

**Step 3: Write minimal implementation**

- build a wizard engine with injectable IO
- add a shell adapter for text/choice/confirm
- map collected answers to `init_project.py` arguments

**Step 4: Run test to verify it passes**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py -q
```

Expected:
- wizard behavior tests pass

## Task 3: Wire shell init into the Codex adapter

**Files:**
- Modify: `webnovel-writer/scripts/codex_cli.py`
- Modify: `codex-skills/webnovel-writer/scripts/run_webnovel_command.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_codex_cli.py`

**Step 1: Write the failing test**

Add tests covering:

- `webnovel-init` in `shell` mode starts the interactive wizard instead of only printing a payload
- non-init commands keep existing behavior
- `--json` still returns machine-readable payload without launching the wizard

**Step 2: Run test to verify it fails**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_codex_cli.py -q
```

Expected:
- shell init dispatch behavior failing

**Step 3: Write minimal implementation**

- add shell-init execution path
- keep current payload behavior for Codex mode and JSON mode

**Step 4: Run test to verify it passes**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_codex_cli.py -q
```

Expected:
- adapter tests pass

## Task 4: Update user docs for the new recommended path

**Files:**
- Modify: `README.md`
- Modify: `docs/codex-install.md`
- Modify: `docs/commands.md`

**Step 1: Write docs updates**

- make shell init the recommended deterministic path
- explain that Codex chat can help, but structured init is best started from terminal
- keep original `/webnovel-writer:*` literal command examples where shell can preserve them

**Step 2: Verify docs examples**

Run:

```bash
python3 scripts/smoke_test_codex_support.py
```

Expected:
- smoke test still passes

## Task 5: Full verification

Run:

```bash
python3 -m py_compile \
  webnovel-writer/scripts/init_source_loader.py \
  webnovel-writer/scripts/init_terminal_ui.py \
  webnovel-writer/scripts/codex_cli.py \
  codex-skills/webnovel-writer/scripts/run_webnovel_command.py

pytest --no-cov \
  webnovel-writer/scripts/data_modules/tests/test_init_source_loader.py \
  webnovel-writer/scripts/data_modules/tests/test_init_terminal_ui.py \
  webnovel-writer/scripts/data_modules/tests/test_codex_cli.py \
  webnovel-writer/scripts/data_modules/tests/test_codex_command_registry.py \
  webnovel-writer/scripts/data_modules/tests/test_install_codex_support.py \
  codex-skills/webnovel-writer/scripts/test_install_skill_smoke.py -q
```

Expected:
- all targeted tests pass
- no syntax errors
