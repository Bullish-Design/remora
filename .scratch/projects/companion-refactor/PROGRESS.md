# Companion Refactor — Progress

> **CRITICAL RULES:**
> - **NO SUBAGENTS** — Do ALL work directly.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.

---

## Phase 1: Event Model Migration

| # | Task | Status |
|---|------|--------|
| 1.1 | Create `src/remora/companion/events.py` with Pydantic event models | pending |
| 1.2 | Add companion events to `RemoraEvent` union | pending |
| 1.3 | Write tests for new event models | pending |
| 1.4 | Create compatibility aliases in old location | pending |
| 1.5 | Update agents to import from new location | pending |

## Phase 2: Subscription Integration

| # | Task | Status |
|---|------|--------|
| 2.1 | Design companion subscription patterns | pending |
| 2.2 | Add `subscriptions()` to each agent | pending |
| 2.3 | Write subscription matching tests | pending |
| 2.4 | Update `AgentBase` to use `SubscriptionPattern` | pending |

## Phase 3: EventStore-Backed Workspace

| # | Task | Status |
|---|------|--------|
| 3.1 | Create `EventStoreWorkspace` class | pending |
| 3.2 | Add workspace projection for replay | pending |
| 3.3 | Write workspace tests | pending |
| 3.4 | Keep `InMemoryWorkspace` for unit tests | pending |

## Phase 4: Runtime Refactor

| # | Task | Status |
|---|------|--------|
| 4.1 | Create agent registry | pending |
| 4.2 | Add `@companion_agent` decorator | pending |
| 4.3 | Refactor `CompanionRuntime.start()` | pending |
| 4.4 | Refactor event dispatch | pending |
| 4.5 | Eliminate `_on_path_change()` | pending |
| 4.6 | Wire activation tracking | pending |
| 4.7 | Write runtime tests | pending |

## Phase 5: Package Relocation

| # | Task | Status |
|---|------|--------|
| 5.1 | Create `src/remora/companion/` package | pending |
| 5.2 | Move core modules | pending |
| 5.3 | Update all imports | pending |
| 5.4 | Update `pyproject.toml` | pending |
| 5.5 | Add compatibility shims | pending |
| 5.6 | Update test imports | pending |
| 5.7 | Keep demo code in `remora_demo/` | pending |

## Phase 6: Test Migration and Cleanup

| # | Task | Status |
|---|------|--------|
| 6.1 | Remove compatibility aliases | pending |
| 6.2 | Remove old subscription matching code | pending |
| 6.3 | Remove `_on_path_change()` dead code | pending |
| 6.4 | Add integration test | pending |
| 6.5 | Update documentation | pending |
| 6.6 | Final test run | pending |
