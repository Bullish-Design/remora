# Companion Refactor — Plan

> **CRITICAL RULES:**
> - **NO SUBAGENTS** — Do ALL work directly. No delegation. No exceptions.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.

---

## Table of Contents

1. [Overview](#overview)
2. [Phase 1: Event Model Migration](#phase-1-event-model-migration)
3. [Phase 2: Subscription Integration](#phase-2-subscription-integration)
4. [Phase 3: EventStore-Backed Workspace](#phase-3-eventstore-backed-workspace)
5. [Phase 4: Runtime Refactor](#phase-4-runtime-refactor)
6. [Phase 5: Package Relocation](#phase-5-package-relocation)
7. [Phase 6: Test Migration and Cleanup](#phase-6-test-migration-and-cleanup)

---

## Overview

Refactor the companion system from a standalone demo with parallel implementations to a first-class remora module that uses core primitives (EventStore, SubscriptionPattern, _FrozenEvent).

**Strategy:** Bottom-up, incremental. Each phase leaves tests green. No big-bang rewrite.

**Order rationale:**
- Events first (foundation everything else builds on)
- Subscriptions next (routing depends on events)
- Workspace next (depends on events + EventStore)
- Runtime last (wires everything together, depends on all above)
- Package relocation at the end (pure mechanical move, independent of logic changes)

---

## Phase 1: Event Model Migration

**Goal:** Replace frozen dataclasses with `_FrozenEvent` Pydantic models.

### Tasks

1.1. **Create `src/remora/companion/events.py`** with Pydantic equivalents of all companion events:
   - `CompanionCursorMoved` (replaces `CursorMoved`)
   - `CompanionContentEdited` (replaces `ContentEdited`)
   - `CompanionFileChanged` (replaces `FileChanged`)
   - `CompanionSessionTick` (replaces `SessionTick`)
   - `CompanionPathChanged` (replaces `PathChanged`)
   - `CompanionWorkspaceWrite` (new — for workspace state changes)
   - All inherit from `_FrozenEvent`, all have `timestamp` field

1.2. **Add companion events to `RemoraEvent` union** in `src/remora/core/events.py`

1.3. **Write tests** for the new event models (construction, immutability, serialization)

1.4. **Create compatibility aliases** — Make the old `remora_demo/companion/models/events.py` re-export the new Pydantic events so existing code doesn't break immediately

1.5. **Update agents one by one** to import from new location

### Acceptance Criteria
- All new events are `_FrozenEvent` subclasses
- All new events have `timestamp` field
- All 177 existing tests still pass (via compatibility aliases)
- New event model tests pass

---

## Phase 2: Subscription Integration

**Goal:** Replace companion's custom `Subscription` dataclass and `@subscribe` decorator with core `SubscriptionPattern` + `SubscriptionRegistry`.

### Tasks

2.1. **Design companion subscription patterns** — Map each agent's current subscriptions to `SubscriptionPattern`:
   - Event-type subscriptions: `SubscriptionPattern(event_types=["CompanionCursorMoved"])`
   - Path subscriptions: `SubscriptionPattern(event_types=["CompanionWorkspaceWrite"], path_glob="/companion/context/*")`

2.2. **Add `subscriptions()` class method to each agent** that returns `list[SubscriptionPattern]`

2.3. **Write tests** for subscription pattern matching with companion events

2.4. **Update `AgentBase`** to use `SubscriptionPattern` for matching instead of custom `Subscription` matching

### Acceptance Criteria
- Each agent declares its subscriptions as `SubscriptionPattern` objects
- `SubscriptionPattern.matches()` correctly routes companion events
- Manual `_on_path_change()` if/elif logic is reproducible via subscription patterns
- All existing tests pass

---

## Phase 3: EventStore-Backed Workspace

**Goal:** Create an `EventStoreWorkspace` implementation that persists workspace writes as events.

### Tasks

3.1. **Create `EventStoreWorkspace`** class implementing `WorkspaceInterface`:
   - `write()` → appends `CompanionWorkspaceWrite` event to EventStore
   - `read()` → reads from in-memory cache
   - `list()` → reads from in-memory cache
   - `delete()` → appends delete event to EventStore

3.2. **Add workspace projection** that rebuilds cache from events on startup (replay)

3.3. **Write tests** — EventStoreWorkspace reads/writes, projection replay, cache consistency

3.4. **Keep `InMemoryWorkspace`** for unit tests that don't need persistence

### Acceptance Criteria
- `EventStoreWorkspace` passes all `WorkspaceInterface` contract tests
- Workspace writes appear in EventStore as events
- Workspace state can be replayed from events
- Existing tests unaffected (they use InMemoryWorkspace)

---

## Phase 4: Runtime Refactor

**Goal:** Replace hardcoded agent wiring with registry-driven discovery and EventStore-based dispatch.

### Tasks

4.1. **Create agent registry** — Simple dict mapping agent name → agent factory

4.2. **Add `@companion_agent` decorator** (or explicit registration) for each agent class

4.3. **Refactor `CompanionRuntime.start()`**:
   - Iterate registry, instantiate agents
   - Register each agent's `SubscriptionPattern`s in `SubscriptionRegistry`
   - Start EventStore trigger loop

4.4. **Refactor event dispatch**:
   - Replace direct method calls with EventStore-mediated dispatch
   - Cursor events → `EventStore.append(CompanionCursorMoved)` → subscription match → agent handler
   - Workspace writes → `EventStore.append(CompanionWorkspaceWrite)` → subscription match → downstream agents

4.5. **Eliminate `_on_path_change()`** — All routing now goes through SubscriptionRegistry

4.6. **Wire activation tracking** — Agent activations become events in EventStore (or remain as in-memory records with an optional EventStore bridge)

4.7. **Write tests** — Runtime startup, agent discovery, event dispatch flow, full cascade test

### Acceptance Criteria
- No manual if/elif routing in runtime
- Adding a new agent requires only the agent class + registration (zero edits to runtime.py)
- Full agent cascade works: cursor → context → search → connections → sidebar
- All existing tests pass

---

## Phase 5: Package Relocation

**Goal:** Move companion from `remora_demo/companion/` to `src/remora/companion/`.

### Tasks

5.1. **Create `src/remora/companion/` package** with `__init__.py`

5.2. **Move core modules**:
   - `agents/` (all agent classes)
   - `models/` (now just re-exports from `remora.companion.events`)
   - `runtime.py`
   - `indexing/`

5.3. **Update all imports** across the codebase

5.4. **Update `pyproject.toml`** — package includes, entry points

5.5. **Add compatibility shims** in `remora_demo/companion/` that re-export from new location (temporary)

5.6. **Update test imports** in `tests/companion/`

5.7. **Keep demo-specific code in `remora_demo/`**:
   - `remora_demo/companion/demo/` (harness, scenarios, recording)
   - `remora_demo/companion/lsp/` (LSP server)
   - `remora_demo/companion/nvim/` (Neovim plugin)
   - `remora_demo/companion/timeline/` (web UI)

### Acceptance Criteria
- `from remora.companion import CompanionRuntime` works
- All 177+ tests pass with new imports
- `pyproject.toml` correctly includes new package
- Demo code still works via updated imports

---

## Phase 6: Test Migration and Cleanup

**Goal:** Remove compatibility shims, clean up old code, ensure full coverage.

### Tasks

6.1. **Remove compatibility aliases** from `remora_demo/companion/models/events.py`

6.2. **Remove old `AgentBase` subscription matching** code (replaced by SubscriptionRegistry)

6.3. **Remove `_on_path_change()` dead code** from runtime

6.4. **Add integration test** — Full companion pipeline using EventStore (not just InMemoryWorkspace)

6.5. **Update documentation** — If any docs reference old import paths

6.6. **Final test run** — All companion tests + core remora tests pass

### Acceptance Criteria
- No dead code remaining
- No compatibility shims remaining
- All tests pass
- Companion is fully first-class: uses EventStore, SubscriptionPattern, _FrozenEvent

---

## REMINDER — NO SUBAGENTS

**NEVER use the Task tool.** Do all work directly. This rule is absolute and non-negotiable.
