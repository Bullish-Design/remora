# Remora Refactoring Guide (Revised)

This guide provides step-by-step instructions to complete the full Remora refactor. The key change from the previous version: **use FSdantic KV for non-event state** instead of consolidating into a raw SQLite `RemoraStore`.

---

## Phase 1: Remove Legacy Code (~1,100 LOC)

### Step 1.1: Delete executor.py

**File**: `src/remora/core/executor.py` (581 LOC)

```bash
rm src/remora/core/executor.py
```

Remove all imports/references: `GraphExecutor`, `from remora.core.executor`.

### Step 1.2: Delete graph.py

**File**: `src/remora/core/graph.py` (217 LOC)

```bash
rm src/remora/core/graph.py
```

Remove all imports: `AgentNode`, `build_graph`, `get_execution_batches`.

### Step 1.3: Delete context.py

**File**: `src/remora/core/context.py` (171 LOC)

```bash
rm src/remora/core/context.py
```

Only consumer was `executor.py` (already deleted). `AgentState.chat_history` replaces its function.

### Step 1.4: Remove Dead Code from workspace.py

**File**: `src/remora/core/workspace.py`

Delete these classes (only used by deleted `executor.py`):
- `WorkspaceManager` (~40 LOC)
- `CairnDataProvider` (~35 LOC)
- `CairnResultHandler` (~18 LOC)

Keep only `AgentWorkspace`.

### Step 1.5: Delete EventSourcedBus from event_store.py

**File**: `src/remora/core/event_store.py`

Delete the `EventSourcedBus` class (lines 343-379, ~40 LOC). It wraps EventBus + EventStore and causes double event emission. The EventStore already has an `_event_bus` reference for notifications.

Update any imports/references to use `EventStore` directly.

### Step 1.6: Update `__init__.py` Exports

Remove exports for all deleted classes from `src/remora/core/__init__.py`.

**Verification**:
```bash
grep -r "GraphExecutor\|from remora.core.executor\|from remora.core.graph\|from remora.core.context\|EventSourcedBus\|WorkspaceManager\|CairnDataProvider\|CairnResultHandler" src/
```

---

## Phase 2: Fix Critical Bugs

### Step 2.1: Fix chat.py Syntax Error

**File**: `src/remora/core/chat.py`

Move the `history` property, `reset()`, and `close()` methods from after the `return` statement in `build_chat_tools()` back into the `ChatSession` class.

### Step 2.2: Fix Double Event Emission

Already addressed by deleting `EventSourcedBus` in Phase 1.5. Ensure all callers use `EventStore.append()` directly, which already emits to `_event_bus` if configured.

### Step 2.3: Fix File Handle Leak in AgentState

**File**: `src/remora/core/agent_state.py`

```python
# Before (leaks handle):
path.open("a", encoding="utf-8").write(line)

# After:
with path.open("a", encoding="utf-8") as f:
    f.write(line)
```

### Step 2.4: Fix AgentState.from_dict() Side Effect

```python
# Before (mutates input):
subs_data = data.pop("custom_subscriptions", [])

# After:
data = dict(data)  # Don't mutate input
subs_data = data.pop("custom_subscriptions", [])
```

---

## Phase 3: Fix Config Issues

### Step 3.1: Fix Frozen Dataclass with Mutable Default

**File**: `src/remora/core/config.py`

Remove `frozen=True` — it provides little value for a config loaded once at startup, and `bundle_mapping: dict` breaks it.

```python
@dataclass(slots=True)  # Remove frozen
class Config:
    bundle_mapping: dict[str, str] = field(default_factory=dict)
```

### Step 3.2: Remove Duplicate ConfigError

Delete the dynamic `ConfigError = type("ConfigError", ...)` and import from `errors.py` instead.

---

## Phase 4: Implement Reactive Storage (SQLite + JSONL)

This phase aligns storage with the CST Agent Swarm concept:
- `events.db` (SQLite): Event log and trigger queue.
- `swarm_state.db` (SQLite): Global agent registry.
- `subscriptions.db` (SQLite): Event routing rules.
- `state.jsonl` (JSONL): Per-agent persistent memory, stored in `agents/<id>/state.jsonl`.

### Step 4.1: Create SwarmState

**File**: `src/remora/core/swarm_state.py` (~100 LOC)

Implement SQLite-backed global agent registry (`swarm_state.db`):
- `register_agent(agent_id, metadata)`
- `get_agent(agent_id)`
- `list_agents(parent_id=None)`
- `mark_orphaned(agent_id)`

### Step 4.2: Create SubscriptionRegistry

**File**: `src/remora/core/subscriptions.py` (~150 LOC)

Implement SQLite-backed event routing rules (`subscriptions.db`):
- Migrate `SubscriptionPattern` from `event_store.py` (or keep it here).
- `register(agent_id, pattern)`
- `register_defaults(agent_id, metadata)` (Direct messages + File changes)
- `unregister_all(agent_id)`
- `get_matching_agents(event) -> list[str]`

### Step 4.3: Extend AgentState for JSONL Persistence

**File**: `src/remora/core/agent_state.py` (~80 LOC)

The current `agent_state.py` is close, but needs to be rigorously scoped to per-agent persistence using JSONL inside the agent's folder (`agents/<agent_id>/state.jsonl`). Keep `load` and `save` functions append-only for history.

### Step 4.4: Extend EventStore with Trigger Queue

**File**: `src/remora/core/event_store.py` (~250 LOC)

Update the existing `EventStore` class:
1.  **Add Dependencies**: Inject `SubscriptionRegistry` and `EventBus`.
2.  **Add Trigger Queue**: `self._trigger_queue = asyncio.Queue()`.
3.  **Update `append`**:
    - Persist the event to SQLite.
    - Call `self._subscriptions.get_matching_agents(event)`.
    - Push `(agent_id, event_id, event)` onto `_trigger_queue` for each match.
    - Emit to `_event_bus` for UI updates.
4.  **Add `get_triggers`**: `async def get_triggers() -> AsyncIterator[tuple[str, int, Event]]`.

### Step 4.5: Update AgentRunner

**File**: `src/remora/core/agent_runner.py` (~150 LOC)

Rewrite the main execution loop to be completely reactive:
- Remove polling (`last_seen_event_id`).
- Loop over `event_store.get_triggers()`.
- Implement cascade prevention (cooldowns + depth limits).
- When a turn runs, load `AgentState` from JSONL, generate prompt, run `AgentKernel`, and save state.

### Step 4.6: Update Reconciler

**File**: `src/remora/core/reconciler.py` (~100 LOC)

Update the startup reconciliation logic to use the new `SwarmState` and `SubscriptionRegistry`:
- Diff discovered CST nodes against `SwarmState`.
- Call `swarm_state.register_agent` and `subscriptions.register_defaults` for new nodes.
- Call `swarm_state.mark_orphaned` and `subscriptions.unregister_all` for deleted nodes.

---

## Phase 5: Maintain Cairn Workspaces

**File**: `src/remora/core/workspace.py` and `cairn_bridge.py`

We DO NOT swap `cairn.runtime.workspace_manager` for `Fsdantic.open()`. The concept demands nested Cairn workspaces (`.remora/agents/<id>/workspace.db`) mapped over a `stable.db` layer. 

- Keep `CairnWorkspaceService` largely as-is.
- Continue using Cairn dependencies to enforce copy-on-write functionality per agent.
- Ensure the agent's folder (`.remora/agents/<id>`) stores both `state.jsonl` (AgentState) and `workspace.db` (Cairn).

---

## Phase 6: Service Layer Integration

**File**: `src/remora/service/api.py`

Ensure that the main `create_default()` correctly wires up the separated SQLite/JSONL layers (`EventStore`, `SubscriptionRegistry`, `SwarmState`) with the `CairnWorkspaceService`.

---

## Phase 7: Fix Remaining Issues

### Step 7.1: Use Config swarm_id in AgentRunner

```python
self._swarm_id = config.swarm_id  # Not "swarm"
```

### Step 7.2: Clean Up Correlation Depth Tracking

Add periodic cleanup with TTL-based expiry for `_correlation_depth` dict entries.

### Step 7.3: Cache Workspace Initialization

```python
async def _ensure_workspace_initialized(self) -> None:
    if not self._workspace_initialized:
        await self._workspace_service.initialize()
        self._workspace_initialized = True
```

### Step 7.4: Fix NvimServer

- Import `asdict` from `dataclasses` instead of local function
- Use `self._swarm_id` instead of hardcoded `"nvim"`

### Step 7.5: Make SubscriptionPattern Matching Async-Safe

Since `SubscriptionPattern.matches()` is used in `SwarmStore.get_matching_agents()`, ensure it handles edge cases (None fields, missing event attrs) gracefully.

---

## Phase 8: Tests

### Step 8.1: AgentRunner Cascade Prevention Tests

Test depth limits, cooldowns, and concurrent trigger handling.

### Step 8.2: SwarmStore Integration Tests

Test KV-backed agent registry, subscription matching, and state persistence.

### Step 8.3: EventStore Trigger Queue Tests

Test concurrent event appending and subscription-based trigger delivery.

---

## Phase 9: Documentation

### Step 9.1: Update Module Docstrings

```python
"""Remora Core - Reactive Agent Swarm Framework.

Storage:
    EventStore     → SQLite append-only event log with trigger queue
    SwarmStore     → FSdantic KV for agents, subscriptions, state

Execution:
    AgentRunner    → Reactive event loop processing triggers  
    SwarmExecutor  → Single-agent turn execution

Event Flow:
    Event → EventStore.append() → SwarmStore.get_matching_agents()
    → TriggerQueue → AgentRunner → SwarmExecutor → Agent Turn
"""
```

---

## Verification Checklist

After completing all phases:

- [ ] `grep -r "GraphExecutor\|EventSourcedBus\|WorkspaceManager\|CairnDataProvider\|CairnResultHandler" src/` returns nothing
- [ ] `grep -r "from remora.core.executor\|from remora.core.graph\|from remora.core.context" src/` returns nothing
- [ ] `python -c "from remora.core.subscriptions import SubscriptionRegistry"` succeeds
- [ ] `python -c "from remora.core.swarm_state import SwarmState"` succeeds
- [ ] `python -c "from remora.core.event_store import EventStore"` succeeds
- [ ] `pytest tests/` passes
- [ ] Storage concerns correctly separated into `events.db`, `swarm_state.db`, `subscriptions.db`, and JSONL files.

---

## Summary of Changes

| Phase | Description | LOC Removed | LOC Added |
|-------|-------------|-------------|-----------|
| 1 | Remove legacy code | ~1,100 | 0 |
| 2 | Fix critical bugs | ~5 | ~15 |
| 3 | Fix config issues | ~5 | ~5 |
| 4 | SQLite & JSONL storage | - | ~250 |
| 5 | Retain Cairn Working | ~0 | ~0 |
| 6 | Service layer wiring | ~0 | ~10 |
| 7 | Fix remaining issues | ~20 | ~30 |
| 8 | Tests | 0 | ~120 |
| **Total** | | **~1,280** | **~480** |

**Net reduction**: ~800 LOC while gaining:
- Pure Reactive architecture aligned with CST Demo
- Dedicated SQLite databases for message bus & state tracking
- Per-agent isolated `state.jsonl` files stored alongside `workspace.db`
- Cleaner mental model

---

## Order of Operations

**Critical path** (do first, in order):
1. Phase 1 — Remove legacy code (unblocks everything)
2. Phase 2 — Fix critical bugs (unblocks testing)
3. Phase 3 — Fix config (unblocks running)
4. Phase 4 — FSdantic KV storage (core architectural change)

**After core changes**:
5. Phase 5 — Simplify Cairn bridge
6. Phase 6 — Flatten service layer
7. Phase 7 — Fix remaining issues
8. Phase 8 — Tests
9. Phase 9 — Documentation
