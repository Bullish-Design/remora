# Remora Codebase Cleanup Review

Post-launch-plan and post-Pydantic-consolidation audit of the Remora codebase.

**Date:** 2026-03-02
**Baseline:** 659 passed, 2 xfailed, 0 failures
**Last commit:** Pydantic Consolidation Refactor (`2b45f7a`)

## Severity Key

- **FIX NOW** — Broken code, import errors, or things that will crash at runtime
- **SHOULD FIX** — Dead code, confusing duplication, or tech debt that hinders maintenance
- **COSMETIC** — Style nits, naming consistency, minor improvements

---

## Table of Contents

1. [Broken / Stale Files](#1-broken--stale-files) — Files referencing deleted modules
2. [Dead Imports & Duplicate Imports](#2-dead-imports--duplicate-imports) — Unused or shadowed imports
3. [Dead Code / Unused Definitions](#3-dead-code--unused-definitions) — Classes, functions, error types never used
4. [Dual Event Systems](#4-dual-event-systems) — `lsp/models.py` vs `core/events.py` overlap
5. [CairnExternals vs AgentContext Coexistence](#5-cairnexternals-vs-agentcontext-coexistence)
6. [Missing Exports from `__init__.py`](#6-missing-exports-from-__init__py)
7. [TODO/FIXME Comments](#7-todofixme-comments)
8. [Testing Gaps](#8-testing-gaps)
9. [Prioritized Action Plan](#9-prioritized-action-plan)

---

## 1. Broken / Stale Files

### 1.1 `demo-trigger.py` imports deleted modules — **FIX NOW**

**File:** `demo-trigger.py` (project root)
**Problem:** Imports `SwarmState` and `AgentMetadata` from `remora.core.swarm_state` — a module
deleted in Batch 5 (commit `9b9171a`). This file will crash with `ModuleNotFoundError` on import.
**LOC to fix:** ~5 lines — either delete the file or rewrite to use `EventStore` + `NodeDiscoveredEvent`.
**Recommendation:** Delete. This was a one-off manual test script. If manual event injection is
needed, write a fresh script using the current API.

### 1.2 `tests/test_mock_llm.py` imports from `remora_demo` — **COSMETIC**

**File:** `tests/test_mock_llm.py`
**Problem:** Imports from `remora_demo.neovim.mock_llm`. This is an external demo package, not
part of `src/remora/`. The test is already in the ignored test list (not run in CI). If
`remora_demo` isn't installed, the test fails with `ModuleNotFoundError`.
**LOC to fix:** 0 — already ignored. Consider adding a `pytest.importorskip("remora_demo")` guard
or moving to `remora_demo/tests/`.

---

## 2. Dead Imports & Duplicate Imports

### 2.1 `remora/__init__.py` — `ConfigError` imported twice — **SHOULD FIX**

**File:** `src/remora/__init__.py`
**Lines:** 7 and 19
**Problem:** `ConfigError` is imported from `remora.core.config` (line 7) and again from
`remora.core.errors` (line 19). They resolve to the same class (config re-exports from errors),
but the second import shadows the first. Confusing and unnecessary.
**LOC to fix:** 1 — remove `ConfigError` from the `core.config` import block (line 7).

### 2.2 `lsp/notifications.py` — unused `AgentMessageEvent` import — **SHOULD FIX**

**File:** `src/remora/lsp/notifications.py:3`
**Problem:** `AgentMessageEvent` is imported from `remora.lsp.models` but never used in the
module body. Only `HumanChatEvent` and `RewriteRejectedEvent` are actually referenced.
**LOC to fix:** 1 — remove `AgentMessageEvent` from the import statement.

---

## 3. Dead Code / Unused Definitions

### 3.1 `SwarmError` — defined but never raised — **SHOULD FIX**

**File:** `src/remora/core/errors.py:45`
**Problem:** `SwarmError` is defined in `errors.py` and re-exported from `remora/__init__.py`,
but it is **never raised anywhere** in the codebase. No code catches it either. It exists solely
as an unused error class.
**LOC to fix:** ~4 — remove class from `errors.py`, remove from `remora/__init__.py` `__all__`
and import block.

### 3.2 `GraphError` — defined but never raised — **SHOULD FIX**

**File:** `src/remora/core/errors.py:27`
**Problem:** `GraphError` is defined and exported from `errors.py` `__all__`, but is never raised,
caught, or imported anywhere else in the codebase. No code references it.
**LOC to fix:** ~4 — remove class from `errors.py` and its `__all__` entry.

### 3.3 `_from_mapping()` — dead helper function — **SHOULD FIX**

**File:** `src/remora/models/__init__.py:12`
**Problem:** `_from_mapping()` is defined but never called. It was likely a helper for an earlier
version of `SwarmEmitRequest.from_dict()` but was superseded.
**LOC to fix:** 2 — delete the function.

### 3.4 `DummyKernel` / `DummyResult` — unused test fixtures — **COSMETIC**

**File:** `tests/conftest.py:78-111`
**Problem:** `DummyKernel` class and `DummyResult` class are defined, along with a
`dummy_kernel` fixture, but no test ever uses the `dummy_kernel` fixture. All tests use either
the real kernel via `create_kernel()` or their own mocks.
**LOC to fix:** ~30 — delete `DummyKernel`, `DummyResult`, and the `dummy_kernel` fixture.

### 3.5 `remora.testing` package — never imported by any test — **SHOULD FIX**

**File:** `src/remora/testing/__init__.py` and `src/remora/testing/fakes.py`
**Problem:** The `remora.testing` package defines 8 fake classes (`FakeAsyncOpenAI`,
`FakeChatCompletions`, `FakeCompletionChoice`, `FakeCompletionMessage`,
`FakeCompletionResponse`, `FakeGrailExecutor`, `FakeToolCall`, `FakeToolCallFunction`).
**No test file anywhere imports from `remora.testing`.** The package is completely dead code.
**LOC to fix:** ~145 — delete `src/remora/testing/` directory entirely. Or keep and start
using it (would require migrating inline test fakes to use it).
**Recommendation:** If the fakes are intended for future use, keep but document. If not, delete.

---

## 4. Dual Event Systems

### 4.1 `lsp/models.py` vs `core/events.py` — **SHOULD FIX** (medium-term)

**Background:**
- `core/events.py` defines the **unified Remora event system**: frozen Pydantic models inheriting
  from `_FrozenEvent`. This is the canonical source. Events: `AgentStartEvent`,
  `AgentCompleteEvent`, `AgentErrorEvent`, `AgentMessageEvent`, etc.
- `lsp/models.py` defines an **older LSP-specific event system**: Pydantic models inheriting
  from `AgentEvent` (which has `event_id`, `event_type`, `timestamp`, `correlation_id`, etc.).
  Events: `AgentMessageEvent`, `AgentErrorEvent`, `HumanChatEvent`, `RewriteProposalEvent`, etc.

**Name collisions:**
- `AgentMessageEvent` exists in BOTH modules with **different schemas** (different fields, different bases)
- `AgentErrorEvent` exists in BOTH modules with **different schemas**

**Current usage:**
- `core/events.py` types are used by: `swarm_executor.py`, `tools/swarm.py`, `service/handlers.py`,
  `cli/main.py`, subscriptions, event store, projections — the **entire core runtime**.
- `lsp/models.py` types are used by: `lsp/runner.py`, `lsp/server.py`, `lsp/notifications.py`,
  `lsp/handlers/*.py` — the **LSP server layer only**.

**Assessment:** The two systems serve different layers but the naming collision is a maintenance
hazard. The `lsp/models.py` events are LSP protocol events (stored in the LSP DB, used for
diagnostics/proposals). The `core/events.py` events are domain events (stored in EventStore,
used for subscriptions/routing). They coexist legitimately but should be disambiguated.

**Recommendation:** Either:
- Rename `lsp/models.py` events to add an `Lsp` prefix (e.g., `LspAgentMessageEvent`) — ~15 LOC
- Or add a clear docstring to both modules explaining the distinction — ~5 LOC

---

## 5. CairnExternals vs AgentContext Coexistence

### 5.1 Both coexist legitimately — **No action needed**

**`CairnExternals`** (`core/cairn_externals.py`): A `@dataclass` that wraps Cairn workspace
APIs with path normalization. Used by `CairnWorkspaceService.get_externals()` to build
file-system callbacks.

**`AgentContext`** (`core/agent_context.py`): A Pydantic `BaseModel` that carries typed
swarm callbacks (emit, subscribe, broadcast, query) + optional `cairn_externals: dict`.
Used by `SwarmExecutor` and swarm tools.

**Relationship:** `AgentContext.cairn_externals` is populated from `CairnExternals.as_externals()`.
They are complementary, not redundant:
- `CairnExternals` = file-system layer (Cairn-specific)
- `AgentContext` = execution context layer (framework-agnostic)

**Status:** Correct architecture. No cleanup needed.

### 5.2 `CairnWorkspaceService` / `cairn_bridge.py` — still actively used — **No action needed**

Used by: `chat.py`, `swarm_executor.py`, `service/api.py`, `service/handlers.py`,
`cli/main.py` (via re-exports), and 20+ integration tests. Not superseded.

---

## 6. Missing Exports from `__init__.py`

### 6.1 `FileSavedEvent` not exported from `remora/__init__.py` — **COSMETIC**

**File:** `src/remora/__init__.py`
**Problem:** `ContentChangedEvent` is exported but `FileSavedEvent` is not, even though both
are defined in `core/events.py` and used in tests. This may confuse users who expect symmetric
exports for all event types.
**LOC to fix:** 2 — add import and `__all__` entry.

### 6.2 `ManualTriggerEvent` not exported from `remora/__init__.py` — **COSMETIC**

**File:** `src/remora/__init__.py`
**Problem:** Same as above. `ManualTriggerEvent` is defined in `core/events.py`, used in
`demo-trigger.py`, tests, and `cli/main.py` but not exported from the top-level package.
**LOC to fix:** 2 — add import and `__all__` entry.

### 6.3 `NodeDiscoveredEvent`/`NodeRemovedEvent` not exported from `remora/__init__.py` — **COSMETIC**

**File:** `src/remora/__init__.py`
**Problem:** These are exported from `remora.core` but not from `remora`. They are used
heavily (reconciler, projections, tests). Consumers must import from `remora.core.events` directly.
**LOC to fix:** 4 — add imports and `__all__` entries.

### 6.4 `AgentContext` not exported from `remora/__init__.py` — **COSMETIC**

**File:** `src/remora/__init__.py`
**Problem:** Exported from `remora.core` but not from `remora`. Used by swarm tools and tests.
**LOC to fix:** 2.

---

## 7. TODO/FIXME Comments

### 7.1 Single TODO in codebase — **COSMETIC**

**File:** `src/remora/lsp/handlers/documents.py:80`
**Comment:** `# TODO: persist extra_tools on agent node if needed`
**Assessment:** Low priority. The extra_tools feature works without persistence currently.
Resolve or convert to a tracked issue.

---

## 8. Testing Gaps

### 8.1 `remora.testing` fakes not exercised — **SHOULD FIX**

As noted in 3.5, the entire `remora.testing` package is unused. Either delete or write tests
that use the fakes instead of inline mocks.

### 8.2 Type checker diagnostics — **SHOULD FIX**

The project diagnostics show type errors in several files:
- `core/swarm_executor.py:324` — `str` passed where `Literal['system', ...]` expected
- `core/chat.py:162,256-261` — same `str` vs `Literal` issue; also `Tool.from_function` not found
- `core/agent_node.py:50+` — `lsp` not defined (likely a `TYPE_CHECKING` guard issue)
- `core/event_store.py:218+` — `.execute` on possibly-None connection
- `core/discovery.py:92,195` — `Traversable` / `Query.captures` type issues

These are static analysis warnings, not runtime failures (the test suite passes). But they
indicate potential brittleness and should be addressed.

---

## 9. Prioritized Action Plan

### Immediate (FIX NOW)

| # | Finding | Section | Est. LOC | Effort |
|---|---------|---------|----------|--------|
| 1 | Delete `demo-trigger.py` (imports deleted modules) | 1.1 | 1 (delete) | 1 min |

### Short-term (SHOULD FIX)

| # | Finding | Section | Est. LOC | Effort |
|---|---------|---------|----------|--------|
| 2 | Remove duplicate `ConfigError` import in `__init__.py` | 2.1 | 1 | 1 min |
| 3 | Remove unused `AgentMessageEvent` import in notifications.py | 2.2 | 1 | 1 min |
| 4 | Delete `SwarmError` (never raised) | 3.1 | 4 | 2 min |
| 5 | Delete `GraphError` (never raised) | 3.2 | 4 | 2 min |
| 6 | Delete `_from_mapping()` dead function | 3.3 | 2 | 1 min |
| 7 | Delete `DummyKernel`/`DummyResult` from conftest.py | 3.4 | 30 | 2 min |
| 8 | Delete or document `remora.testing` package | 3.5 | 145 | 5 min |
| 9 | Disambiguate dual event systems (docstrings or rename) | 4.1 | 5-15 | 10 min |
| 10 | Address type checker diagnostics | 8.2 | ~20 | 15 min |

### Nice-to-have (COSMETIC)

| # | Finding | Section | Est. LOC | Effort |
|---|---------|---------|----------|--------|
| 11 | Export `FileSavedEvent` from `remora/__init__.py` | 6.1 | 2 | 1 min |
| 12 | Export `ManualTriggerEvent` from `remora/__init__.py` | 6.2 | 2 | 1 min |
| 13 | Export `NodeDiscoveredEvent`/`NodeRemovedEvent` from `remora/__init__.py` | 6.3 | 4 | 1 min |
| 14 | Export `AgentContext` from `remora/__init__.py` | 6.4 | 2 | 1 min |
| 15 | Resolve or track the TODO in documents.py | 7.1 | 1 | 1 min |
| 16 | Add `importorskip` guard to `test_mock_llm.py` | 1.2 | 1 | 1 min |

**Total estimated effort:** ~45 minutes for all items.
Items 1-8 can be done in a single commit (~10 minutes of actual work).
