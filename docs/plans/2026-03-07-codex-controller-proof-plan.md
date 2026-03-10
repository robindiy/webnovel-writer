# Codex Controller Proof Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build and verify a minimal Codex controller prototype that proves we can keep Codex inside a repo-owned 5-step flow instead of letting it drift into generic `brainstorming` / `writing-plans` behavior.

**Architecture:** Add a tiny stateful controller layer between command resolution and `follow_skill`. The prototype introduces one dedicated demo command that bypasses long-form skill execution, persists step state, returns `controller_step` payloads, writes only whitelisted demo artifacts, and can be resumed across Codex chat turns.

**Tech Stack:** Python, JSON, existing Codex adapter (`codex_cli.py`, `codex_command_registry.py`), top-level Codex skill (`codex-skills/webnovel-writer/SKILL.md`), pytest.

---

## Why This Exists

We already have enough evidence that the current architecture is only **half-controlled**:

- `init` is relatively stable because it has a real executable controller.
- `plan` / `write` / `review` still resolve to `follow_skill`, so Codex continues with its own generic process skills.
- This causes:
  - extra A/B/C questioning that the user never asked for
  - `docs/plans` being written into the user’s book project
  - internal template labels such as `AT-006` leaking into user-facing output
  - fallback behavior when Claude-only `Task` subagents are unavailable

This prototype is **not** trying to fix the whole product yet. It only needs to prove one thing:

> We can make Codex obey a repo-owned controller state machine across multiple turns.

---

## Non-Goals

- Do **not** migrate `webnovel-plan`, `webnovel-write`, `webnovel-review`, or `webnovel-resume` in this task.
- Do **not** redesign prompt content for fiction writing.
- Do **not** touch Dashboard behavior.
- Do **not** require real model writing, RAG, Jina, or Qwen integration yet.
- Do **not** write any `docs/plans` files into the user’s **book project** during the demo.

---

## Approaches Considered

### Approach A — Prompt-only guardrails

Keep the current `follow_skill` model, but add stricter wording to `SKILL.md`.

**Pros**
- Very small change
- Fast to test

**Cons**
- Still relies on Codex obeying long natural-language instructions
- Does not prevent generic skill injection
- Does not prove controller architecture

**Decision**
- Reject.

### Approach B — Minimal dedicated controller demo

Add one new demo command with a 5-step state machine and route it through a controller payload instead of `follow_skill`.

**Pros**
- Smallest real proof of architecture
- Isolates risk from production commands
- Lets us test multi-turn control, persistence, and whitelist writing

**Cons**
- Adds temporary demo-only code
- Does not directly fix current writing flow yet

**Decision**
- **Choose this approach.**

### Approach C — Directly rewrite `webnovel-write`

Skip the demo and immediately implement the full `write_controller`.

**Pros**
- Directly attacks a real user path

**Cons**
- Too much scope for a proof task
- Harder to isolate whether the controller architecture itself works
- Mixes product redesign with infrastructure validation

**Decision**
- Defer until after the proof passes.

---

## Prototype Contract

### New Demo Command

Introduce a dedicated proof command:

- slash form: `/webnovel-writer:webnovel-controller-demo`
- shell alias: `controller-demo`
- natural-language triggers:
  - `开始控制器测试`
  - `开始 controller demo`
  - `运行控制器验证`

### Hard Rules

When this command is active:

1. Codex must **not** open any downstream workflow skill such as `webnovel-plan` or `webnovel-write`.
2. Codex must **not** ask open-ended design questions.
3. Codex must only present the current controller step message and its allowed options.
4. All writes must stay inside:
   - `<project_root>/controller-demo/`
   - `<project_root>/.webnovel/controller_sessions/`
5. No `docs/plans` or unrelated artifacts may be written into the book project.

### What “Pass” Means

The proof is successful if a user can start the demo in Codex chat and complete all 5 steps without Codex drifting into generic planning behavior.

---

## 5-Step Demo Flow

This demo should be intentionally boring and deterministic.

### Step 1 — Start

Show:

- demo goal
- warning that this is only a controller proof
- two options:
  - `继续`
  - `取消`

### Step 2 — Choose Profile

Show exactly two fixed options:

- `标准模式`
- `严格模式`

No free-text design input.

### Step 3 — Confirm Execution Contract

Render a short normalized contract:

- selected profile
- output directory
- file whitelist
- step count

Options:

- `确认执行`
- `返回上一步`

### Step 4 — Generate Demo Artifacts

Write exactly three deterministic files:

- `controller-demo/01-session.md`
- `controller-demo/02-choice.json`
- `controller-demo/03-result.md`

File content should be template-driven, not model-creative.

### Step 5 — Verify and Finish

Run verification:

- all three files exist
- JSON is valid
- no `docs/plans` directory exists under the book project because of this demo

Then return a completion message with the generated file paths.

---

## Payload Design

`codex_cli.py` should stop treating this demo as `follow_skill`.

Expected payload shape:

```json
{
  "status": "ok",
  "mode": "codex",
  "command": {
    "name": "webnovel-controller-demo",
    "args": [],
    "slash_command": "/webnovel-writer:webnovel-controller-demo",
    "skill_name": "webnovel-writer",
    "requires_project": true
  },
  "project_root": "/abs/book/root",
  "action": {
    "type": "controller_step",
    "controller": "demo-proof",
    "session_id": "demo-proof-uuid",
    "step_id": "step-2",
    "done": false,
    "message": "[Controller Demo 2/5] 请选择运行模式：",
    "options": [
      {"id": "standard", "label": "标准模式"},
      {"id": "strict", "label": "严格模式"}
    ]
  }
}
```

### Important

The top-level skill must treat `controller_step` as **terminal for the turn**:

- present `message`
- present options
- stop

It must **not** read any additional planning or writing skill after receiving `controller_step`.

---

## Session Persistence Design

Persist active controller state under:

- `<project_root>/.webnovel/controller_sessions/demo-proof.json`

Suggested schema:

```json
{
  "controller": "demo-proof",
  "session_id": "demo-proof-uuid",
  "active": true,
  "step_id": "step-3",
  "profile": "standard",
  "project_root": "/abs/book/root",
  "artifacts": []
}
```

### Session Rules

- If an active demo session exists, the next user reply should be offered to the controller first.
- Explicit new slash commands may break out of the session.
- Invalid input should not fall back to generic Codex reasoning; it should re-render the current step with allowed options.

---

## Files To Touch

### Create

- `webnovel-writer/scripts/codex_controllers/__init__.py`
- `webnovel-writer/scripts/codex_controllers/engine.py`
- `webnovel-writer/scripts/codex_controllers/session_store.py`
- `webnovel-writer/scripts/codex_controllers/demo_flow.py`
- `webnovel-writer/scripts/data_modules/tests/test_codex_controller_demo.py`
- `scripts/smoke_test_codex_controller_demo.py`

### Modify

- `webnovel-writer/scripts/codex_command_registry.py`
- `webnovel-writer/scripts/codex_cli.py`
- `codex-skills/webnovel-writer/SKILL.md`
- `README.md`
- `docs/codex-install.md`

---

## Task Plan

### Task 1: Add controller runtime primitives

**Files:**
- Create: `webnovel-writer/scripts/codex_controllers/engine.py`
- Create: `webnovel-writer/scripts/codex_controllers/session_store.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_codex_controller_demo.py`

**Step 1: Write failing tests for session lifecycle**

Cover:
- create new session
- load existing session
- reject invalid option
- finish session and mark inactive

**Step 2: Run tests to confirm failure**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_codex_controller_demo.py -q
```

Expected:
- missing module / failing imports / failing assertions

**Step 3: Implement minimal engine and store**

Required primitives:
- `start_session(...)`
- `load_session(...)`
- `advance_session(...)`
- `finish_session(...)`

**Step 4: Re-run tests**

Expected:
- session lifecycle tests pass

### Task 2: Implement the 5-step demo flow

**Files:**
- Create: `webnovel-writer/scripts/codex_controllers/demo_flow.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_codex_controller_demo.py`

**Step 1: Write failing tests for the demo step machine**

Cover:
- initial payload is Step 1
- choosing `继续` advances to Step 2
- choosing profile advances to Step 3
- confirming writes the 3 files and advances to Step 5
- invalid input stays on current step

**Step 2: Implement the fixed 5-step flow**

Hard requirements:
- no creative generation
- no book-facing docs/plans writes
- all artifact content is deterministic

**Step 3: Re-run tests**

Expected:
- step transition tests pass

### Task 3: Wire the demo command into the adapter

**Files:**
- Modify: `webnovel-writer/scripts/codex_command_registry.py`
- Modify: `webnovel-writer/scripts/codex_cli.py`
- Test: `webnovel-writer/scripts/data_modules/tests/test_codex_controller_demo.py`

**Step 1: Add the command spec**

Add:
- `webnovel-controller-demo`
- shell alias `controller-demo`
- natural-language aliases for `开始控制器测试` and similar phrases

**Step 2: Add controller routing in `codex_cli.py`**

Required behavior:
- explicit demo command starts the controller
- active session replies go to controller first
- `action.type` returns `controller_step`
- this path never returns `follow_skill`

**Step 3: Re-run tests**

Expected:
- parsed command and routed payload tests pass

### Task 4: Teach the top-level Codex skill about controller steps

**Files:**
- Modify: `codex-skills/webnovel-writer/SKILL.md`

**Step 1: Extend action interpretation**

Add a new rule:
- If `action.type == "controller_step"`, present the message/options and stop.

**Step 2: Add explicit “do not open downstream skills” note**

The skill should clearly say:
- do not invoke `follow_skill`
- do not invoke `brainstorming`
- do not reinterpret the controller’s prompt

**Step 3: Manually inspect the updated wording**

Expected:
- next-session AI can follow the demo without improvisation

### Task 5: Add smoke test and manual verification guide

**Files:**
- Create: `scripts/smoke_test_codex_controller_demo.py`
- Modify: `README.md`
- Modify: `docs/codex-install.md`

**Step 1: Add a local smoke test**

Smoke test should:
- create a temporary book project
- install the demo path in temp `CODEX_HOME`
- start controller demo
- simulate 5-step answers
- verify artifacts

**Step 2: Document the manual Codex proof**

Add one short section:

```text
进入书项目目录后，在 Codex 中输入：
开始控制器测试
```

Expected:
- Codex stays inside the 5-step demo
- no extra design/planning docs are generated

**Step 3: Run full verification**

Run:

```bash
pytest webnovel-writer/scripts/data_modules/tests/test_codex_controller_demo.py -q
python3 scripts/smoke_test_codex_controller_demo.py
```

Expected:
- both commands pass

---

## Manual Acceptance Checklist

The prototype is acceptable only if all items below are true:

- Starting from Codex chat with `开始控制器测试` enters the controller immediately.
- Codex does not ask open-ended creative questions.
- Codex does not mention `brainstorming`, `writing-plans`, or `docs/plans`.
- The flow completes in exactly 5 user-visible steps.
- All outputs are written only to the whitelisted demo paths.
- Invalid replies stay inside the controller instead of drifting into generic chat.

---

## Prompt For The Next Conversation

Paste this into the new conversation:

```text
请按 docs/plans/2026-03-07-codex-controller-proof-plan.md 实现一个最小控制器原型，只做 demo proof，不要直接重构 webnovel-plan / webnovel-write / webnovel-review。目标是验证：在 Codex 聊天里输入“开始控制器测试”后，流程会被 repo 自己的 5 步控制器接管，不再漂移到 brainstorming、writing-plans 或 docs/plans。
```

