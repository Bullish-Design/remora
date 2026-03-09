# Bootstrap Final Code Review

**Date:** 2026-03-09
**Scope:** All changes since `CODE_REVIEW.md` (2026-03-08); current state of
`src/remora/bootstrap/`, `bootstrap/tools/`, `bootstrap/agents/`,
`tests/unit/bootstrap/`, `tests/integration/test_bootstrap_loop.py`,
`src/remora/lsp/__main__.py`, `src/remora/lsp/handlers/documents.py`,
`src/remora/lsp/notifications.py`
**Test baseline:** 66 tests passing (up from 39)

---

## Table of Contents

1. [Overall Assessment](#1-overall-assessment)
2. [Refactoring Guide Compliance](#2-refactoring-guide-compliance)
3. [New Functionality: SME Workspace Seeding](#3-new-functionality-sme-workspace-seeding)
4. [New Functionality: Human-in-the-Loop Round-Trip](#4-new-functionality-human-in-the-loop-round-trip)
5. [LSP Integration Review](#5-lsp-integration-review)
6. [Remaining Issues](#6-remaining-issues)
7. [Test Suite Review (Current State)](#7-test-suite-review-current-state)
8. [Issues Summary](#8-issues-summary)

---

## 1. Overall Assessment

The implementation has advanced substantially. Every "Should Fix" item from the
original review has been applied, almost every "Nice to Fix" and structural item
is done, and 66 tests now pass. Significant new capability — the SME workspace
pre-seeding and the human-in-the-loop response cycle — was added correctly and
is tested.

**The system is architecturally sound and functionally correct for the happy
path.** Two gaps remain before it can be called fully functional in production:

1. The `run_for_file` call from the LSP `did_open` handler passes a raw
   file URI instead of a project-relative path. This means bootstrap agents are
   never triggered by file opens in the editor unless the paths happen to match
   exactly (they won't, unless seeding is bypassed).

2. There is no event-driven re-activation loop for bootstrap agents. Agents
   declare schema subscriptions (`ContentChangedEvent`, `CursorFocusEvent`,
   `HumanInputResponseEvent`) and these are registered in
   `SubscriptionRegistry` — but nothing watches those subscriptions and
   re-activates the agent when a matching event fires. The living-documentation
   loop is incomplete.

These are not theoretical concerns. They are the only two paths by which a
bootstrap agent gets re-run after initial activation, and neither works yet.

---

## 2. Refactoring Guide Compliance

### All "Should Fix" Issues — DONE ✓

| # | Issue | Status |
|---|-------|--------|
| S1 | Private functions renamed | `make_files_provider`, `extract_workspace_tools` — no underscore prefix, correctly in `__all__` |
| S2 | Double query eliminated | `_emit_events_for_plans` helper; `run_once` and `run_for_file` call it directly |
| S3 | `BootstrapEvent` Pydantic | Correct `BaseModel` + `ConfigDict(frozen=True)`; `dataclass` removed |

### All "Nice to Fix" Issues — DONE ✓

| # | Issue | Status |
|---|-------|--------|
| N1 | Readable comprehension | Explicit for-loop with named `attrs` variable |
| N2 | Flat listing documented | Docstring on `make_files_provider` explains non-recursive limitation |
| N3 | UNION ALL duplicate note | Added to `graph_neighbors.pym` docstring |
| N4 | Double encode | `source_bytes = source.encode("utf-8")` used for both hash and byte count |
| N5 | `coordinator.yaml` phase comment | Clear `# PHASE STATUS: ASPIRATIONAL` block at top of file |

### All Test Gaps — DONE ✓

| # | Gap | Status |
|---|-----|--------|
| T1 | `find_unassigned_nodes` with `file_path` | Test exists and passes |
| T2 | `emit_agent_needed_events_for_nodes` | Two tests covering file-filter and node-type-filter paths |
| T3 | Remaining 7 `.pym` tool execution tests | All 7 added and passing |
| T4 | `_extract_response` `final_message` branch | Four tests covering all branches, now on shared `extract_response_text` |
| T5 | `_build_user_prompt` | Three tests covering None, event-type-only, and node-id paths |
| T6 | `_SKIP_DIRS` exhaustiveness | Parametrized over all six skip dirs |

### All Structural Issues — DONE ✓

| # | Issue | Status |
|---|-------|--------|
| 16 | `extract_response_text` shared helper | In `kernel_factory.py`; both `execution.py` and `turn_executor.py` import it |
| 17 | `observer=None` documented | Inline comment explains unobserved bootstrap turns |
| 18 | Redundant LSP path params | Removed from `BootstrapRunner(...)` call in `__main__.py` |
| 19 | Dead `bootstrap/src/remora_bootstrap/` | Deleted |
| 20 | `DEFAULT_SCHEMA_YAML` consolidation | `load_schema` prefers filesystem default; constant is fallback; sync test added |
| 21 | `bootstrap/` README | Created at `bootstrap/README.md` |
| 22 | Phase-1 comments | Both `runner.py` module docstring and `run_once` docstring explain phase-1 nature |
| 23 | `node_types` configurable | `BootstrapRunner(node_types=...)` constructor parameter; `run_once` and `run_for_file` use it |
| 24 | `skip_dirs` configurable | `seed_module_nodes_from_filesystem(skip_dirs=...)` parameter; `_SKIP_DIRS` is `frozenset` |
| 25 | Phase-1 framing | Module docstrings on `runner.py` and `coordinator.py` |

---

## 3. New Functionality: SME Workspace Seeding

`activation.py` now pre-seeds the agent's Cairn workspace before the LLM
runs. This is a significant design addition not present in the original review.

### Flow

Before calling `TurnExecutor.run(event)`:

1. `_ensure_subject_matter_expert_workspace(cairn_externals, agent_id=..., node_attrs=...)` runs.
2. If `schema.yaml` is absent, it writes one that `extends: subject_matter_expert`.
3. If `summary.md` is absent, it writes a template with section headers and `_pending_` placeholders.

The LLM then runs with the `subject_matter_expert` schema already in place,
rather than the minimal `DEFAULT_SCHEMA` that instructs the agent to write its
own schema. This is the right design choice: agents immediately have access to
the full context pipeline (source_file, graph_node, graph_neighbors,
recent_events) on their very first activation.

### Issues

**`_ensure_subject_matter_expert_workspace` always writes the SME schema,
making `DEFAULT_SCHEMA` functionally dead for file-node agents.** The
`DEFAULT_SCHEMA` system prompt says "write role.md, notes.md, schema.yaml" but
since `schema.yaml` is now pre-written before the LLM runs, no agent ever
executes the DEFAULT_SCHEMA flow (the LLM reads the pre-seeded `schema.yaml`
on its first turn). This is intentional — the SME schema is better — but it
means:

- `DEFAULT_SCHEMA.yaml` is only used as a true fallback for agents that
  somehow have no workspace pre-seeding (non-file nodes, or edge cases where
  `_ensure_subject_matter_expert_workspace` fails silently).
- The sync test `test_default_schema_yaml_matches_file` is still correct and
  useful as a drift guard.

**`_ensure_subject_matter_expert_workspace` uses `getattr(cairn_externals, ...)`
duck-typing guards.** This is a defensive pattern, but since `CairnExternals`
always has `read_file` and `write_file`, the guard never fires in production.
Minor: the guards could be removed to make the invariant explicit.

**The `_build_summary_template` creates a `# Node Guide: {node_name}` template
with `_pending_` placeholder sections.** This is correct, but the `full_name`
fallback chain (`full_name → name → id → node_id → "unknown-node"`) means some
nodes will get a generic heading. Not a bug but worth verifying that
`NodeDiscoveredEvent.full_name` is always populated for seeded nodes. It is:
`seed_module_nodes_from_filesystem` computes `_module_full_name` and assigns it.

### Verdict

The SME workspace seeding is well-implemented, idempotent, and correctly tested
in `test_activation.py`. The tests `test_ensure_subject_matter_expert_workspace_seeds_schema_and_summary`
and `test_ensure_subject_matter_expert_workspace_preserves_existing_files` are
real-function tests that verify the core invariants.

---

## 4. New Functionality: Human-in-the-Loop Round-Trip

The full human response cycle is now implemented end-to-end in code:

```
user_question.pym
  → _event_write("HumanInputRequestEvent")
  → EventBus._forward_user_question (lsp/__main__.py)
  → ls.protocol.notify("$/remora/requestInput", {...})
  → [editor UI]
  → "$/remora/submitInput" notification
  → notifications.py on_input_submitted
  → bootstrap_runner.handle_human_input_response(...)
  → EventStore.append(HumanInputResponseEvent)
  → handle_agent_needed(event, ...)
  → _extract_human_response_fields → _append_correction_notes
  → LLM runs with updated notes.md and summary.md
```

### Issues

**`_forward_user_question` subscribes to `BootstrapEvent` on the EventBus.**
This is the correct mechanism, but `BootstrapEvent` is not in the `CoreEvent`
union. `EventBus.subscribe(BootstrapEvent, handler)` works via MRO at runtime
but is invisible to static type analysis. Low risk in production; worth a
comment near the subscribe call.

**`_append_correction_notes` idempotency check uses `in` on text strings.**

```python
if notes_entry not in notes_text:
    notes_text += notes_entry
```

This guards against duplicate correction entries correctly. The `summary_entry`
check does the same. Both are safe for the current use case.

**`handle_human_input_response` re-activates via `handle_agent_needed`.**
The event passed is a `HumanInputResponseEvent` with `event_type="HumanInputResponseEvent"`.
`handle_agent_needed` is designed for `AgentNeededEvent` but works here because
the only required field is `payload.node_id`. The LLM receives a user prompt
`Activation event: HumanInputResponseEvent\nNode: <node_id>` and the
`_append_correction_notes` run before the LLM has already updated `notes.md`
and `summary.md`. This is correct.

**The `$/remora/submitInput` LSP notification is not registered in server.py.**
The handler in `notifications.py` (`on_input_submitted`) is imported and
presumably registered somewhere, but the connection from LSP method name to
handler function needs to be confirmed. This is a wiring concern, not a logic
concern.

### Verdict

The human-in-the-loop round-trip is the most significant new capability and is
implemented correctly. The test
`test_handle_human_input_response_appends_event_and_reactivates_agent` in
`test_runner.py` validates the full server-side flow.

---

## 5. LSP Integration Review

### `__main__.py` — BootstrapRunner wiring

Clean. `BootstrapRunner` is created with injected stores (no redundant path
params). The `run_forever` loop is started on `INITIALIZED`. The
`_forward_user_question` EventBus bridge is registered. The cleanup in the
`finally` block correctly stops and closes the bootstrap runner.

**One remaining concern:** `_run_async_cleanup(bootstrap_runner.close())` runs
synchronously after the pygls `start_io()` loop exits. In tests and some
shutdown paths, the event loop may already be closed at this point. Using
`_run_async_cleanup` is the right defensive pattern.

### `handlers/documents.py` — `run_for_file(uri)` call

**This is the critical remaining bug.** Line 61:

```python
await bootstrap_runner.run_for_file(uri)
```

`uri` is a raw LSP file URI, e.g., `file:///home/user/project/src/app.py`.

`run_for_file` calls `find_unassigned_nodes(event_store, file_path=uri)`, which
executes `SELECT ... WHERE file_path = 'file:///home/user/project/src/app.py'`.

But nodes created by `seed_module_nodes_from_filesystem` have `file_path =
'src/app.py'` (a project-relative POSIX path). The query returns no rows.

The bootstrap runner finds no unassigned nodes for the opened file and does
nothing, silently.

This effectively disables the "on file open, activate bootstrap agents for
newly-appeared nodes in that file" path. The `run_forever` polling loop (which
uses `find_unassigned_nodes` without a `file_path` filter) will eventually catch
these nodes, but the on-open fast path is broken.

### `notifications.py` — `handle_human_input_response`

Correct. The `$/remora/submitInput` handler correctly dispatches to
`bootstrap_runner.handle_human_input_response` with all required fields.

---

## 6. Remaining Issues

### Must Fix Before Production

| # | Location | Issue |
|---|----------|-------|
| M1 | `lsp/handlers/documents.py:61` | `run_for_file(uri)` passes raw URI; nodes stored with relative paths; query always returns empty |
| M2 | `src/remora/bootstrap/runner.py` | No event-driven re-activation bridge; agents subscribe to events but nothing watches those subscriptions and re-activates the agent |

### Should Fix

| # | Location | Issue |
|---|----------|-------|
| S1 | `src/remora/core/events/subscriptions.py` | `SubscriptionPattern` has no `node_id` field; schema subscriptions with `node_id: "{node.id}"` are silently dropped to event-type-only matching; when re-activation loop is added, all agents subscribed to ContentChangedEvent will fire on any file change |
| S2 | `src/remora/bootstrap/activation.py:323` | `getattr(workspace_service, "_stable_workspace", None)` accesses a private attribute; depends on `CairnWorkspaceService` internals |

### Nice to Fix

| # | Location | Issue |
|---|----------|-------|
| N1 | `bootstrap/agents/coordinator.yaml` | Subscriptions are never registered (coordinator is Python code); the aspirational comment is there, but the agent schema defines `AgentNeededEvent` and `ToolSynthesizedEvent` subscriptions that don't exist in the system |
| N2 | `lsp/__main__.py` | `_forward_user_question` subscribes `BootstrapEvent` on EventBus; this is correct at runtime but invisible to static typing; add a comment noting the intentional duck-type subscription |
| N3 | `src/remora/bootstrap/activation.py` | `_ensure_subject_matter_expert_workspace` `getattr` guards for `read_file`/`write_file` can never fail with real `CairnExternals`; remove to make the invariant explicit |

---

## 7. Test Suite Review (Current State)

### Grading Scale
- **REAL** — uses real components, high confidence
- **PARTIAL** — some real, targeted mocks for external boundaries
- **MOCKED** — primarily mocked, tests orchestration logic

### test_seed_graph.py — REAL ✓✓

Six tests including parametrized `test_skip_dirs_are_excluded` over all six
skip dirs. This is comprehensive and correct.

### test_coordinator.py — REAL ✓✓

Five tests, including `test_emit_agent_needed_events_for_nodes_filters_by_file`
and `test_emit_agent_needed_events_for_nodes_filters_by_node_type`. All general
API paths are covered.

### test_system_tools.py — REAL ✓✓

All 10 tool files have compile tests and all have execution tests with real
async functions. Full coverage. The `graph_add_node` test passes `attrs` as a
dict (not JSON-string), which correctly validates the tool's input handling.

### test_schema_loader.py — PARTIAL ✓✓

Five tests including the new `test_default_schema_yaml_matches_file` which
prevents drift between the embedded constant and the filesystem default. Solid.

### test_turn_executor.py — PARTIAL ✓✓

Nine tests. All `extract_response_text` branches covered (imported from
`kernel_factory` as the shared helper). `_build_user_prompt` fully covered.
`FakeKernel.result` exercises the `final_message` path in the first test.

### test_bedrock.py — MOCKED ✓

Alias presence test and per-function delegation tests. Unchanged and correct.

### test_activation.py — PARTIAL ✓✓

**Significantly expanded.** Now covers eight scenarios:
1. Full orchestration (subscription count, graph writes, result fields)
2. Agent ID generation when missing from payload
3. Tool synthesis event emission
4. **NEW**: `_ensure_subject_matter_expert_workspace` seeds schema and summary
5. **NEW**: `_ensure_subject_matter_expert_workspace` preserves existing files
6. **NEW**: `_append_correction_notes` writes notes.md and summary.md
7. **NEW**: `default_agent_id` stability and filesystem safety
8. **NEW**: `_extract_human_response_fields` correctly parses event

These are real-function tests for the new workspace pre-seeding functions —
the right level of coverage.

### test_runner.py — MOCKED ✓✓

**Significantly expanded.** Now covers six scenarios:
1. Default path derivation from Config
2. `run_once` orchestration with `_emit_events_for_plans` mock
3. `run_forever` stops cleanly
4. `run_for_file` fans out to N agents in parallel with correct file_path args
5. **NEW**: `handle_human_input_response` appends event and re-activates agent
6. **NEW**: `run_once` respects custom `node_types` parameter

The `test_run_once_uses_configured_node_types` test correctly verifies that
`find_unassigned_nodes` is called with the configured `node_types` set.

### test_agent_schemas.py — REAL ✓

Validates all YAML files with the real `TurnSchema` pydantic model. The
`subject_matter_expert.yaml` schema is included in this validation.

### test_bootstrap_loop.py (integration) — MOSTLY REAL ✓✓

Unchanged and correct. Still the most realistic test in the suite.

### Missing Tests

| # | Gap | Priority |
|---|-----|----------|
| TM1 | URI-to-relative-path conversion in `run_for_file` | High — critical bug path |
| TM2 | `run_from_event_store` (once added) — verify re-activation on ContentChangedEvent | High |
| TM3 | `$/remora/submitInput` handler wiring in `notifications.py` | Medium |
| TM4 | `_forward_user_question` bridge in `__main__.py` | Medium |

---

## 8. Issues Summary

### Must Fix (blocks production use)

| # | Location | Issue |
|---|----------|-------|
| M1 | `lsp/handlers/documents.py:61` | `run_for_file(uri)` URI vs. relative path mismatch — on-file-open activation is silently broken |
| M2 | `bootstrap/runner.py` | No event-driven re-activation loop — agents subscribe to events but are never re-activated when those events fire |

### Should Fix

| # | Location | Issue |
|---|----------|-------|
| S1 | `core/events/subscriptions.py` | `SubscriptionPattern` lacks `node_id` field; all `ContentChangedEvent` subscriptions are unscoped |
| S2 | `bootstrap/activation.py:323` | Private `_stable_workspace` attribute access |

### Nice to Fix

| # | Location | Issue |
|---|----------|-------|
| N1 | `bootstrap/agents/coordinator.yaml` | Aspirational subscriptions never activated; aspirational comment is present but the schema still misleads readers |
| N2 | `lsp/__main__.py` | `BootstrapEvent` EventBus subscription needs a type comment |
| N3 | `bootstrap/activation.py` | Remove unreachable `getattr` guards in `_ensure_subject_matter_expert_workspace` |
