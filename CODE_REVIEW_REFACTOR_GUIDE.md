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

## Phase 4: Replace Storage with FSdantic KV

This is the key new phase. Instead of writing a custom `RemoraStore` with raw SQL, use the FSdantic KV store that's already a dependency.

### Step 4.1: Create SwarmStore — FSdantic KV Wrapper

**Create**: `src/remora/core/swarm_store.py` (~120 LOC)

This replaces `SwarmState`, `SubscriptionRegistry`, and `AgentState` with a single FSdantic workspace + KV namespaces.

```python
# src/remora/core/swarm_store.py
"""Unified Remora state storage via FSdantic KV.

Replaces SwarmState, SubscriptionRegistry, and AgentState with
namespaced KV operations on a single FSdantic workspace.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any

from fsdantic import Fsdantic
from pydantic import BaseModel

from remora.core.events import RemoraEvent


class AgentRecord(BaseModel):
    """Agent metadata stored in KV."""
    agent_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    parent_id: str | None = None
    start_line: int = 0
    end_line: int = 0
    status: str = "active"
    created_at: float = 0.0
    updated_at: float = 0.0


class AgentStateRecord(BaseModel):
    """Per-agent persistent state stored in KV."""
    chat_history: list[dict[str, Any]] = []
    connections: dict[str, str] = {}
    custom_subscriptions: list[dict[str, Any]] = []
    last_updated: float = 0.0


class SubscriptionRecord(BaseModel):
    """A single subscription pattern stored in KV."""
    agent_id: str
    pattern: dict[str, Any]
    is_default: bool = False
    created_at: float = 0.0


class SwarmStore:
    """Unified state storage using FSdantic KV.

    Namespaces:
        agents:    → AgentRecord (keyed by agent_id)
        state:     → AgentStateRecord (keyed by agent_id)
        subs:      → SubscriptionRecord (keyed by sub_id)
        sub_index: → list of sub_ids (keyed by agent_id)
    """

    def __init__(self, workspace_id: str = "remora-swarm"):
        self._workspace_id = workspace_id
        self._workspace = None
        self._agents = None  # KV namespace
        self._state = None   # KV namespace
        self._subs = None    # KV namespace

    async def initialize(self) -> None:
        self._workspace = await Fsdantic.open(id=self._workspace_id)
        self._agents = self._workspace.kv.repository(
            prefix="agents:", model_type=AgentRecord
        )
        self._state = self._workspace.kv.repository(
            prefix="state:", model_type=AgentStateRecord
        )
        self._subs = self._workspace.kv.namespace("subs")

    # ── Agent Registry ──

    async def upsert_agent(self, record: AgentRecord) -> None:
        record.updated_at = time.time()
        if not record.created_at:
            record.created_at = record.updated_at
        await self._agents.save(record.agent_id, record)

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        try:
            return await self._agents.load(agent_id)
        except Exception:
            return None

    async def list_agents(self, status: str | None = None) -> list[AgentRecord]:
        all_agents = await self._agents.list_all()
        if status:
            return [a for a in all_agents if a.status == status]
        return all_agents

    async def mark_orphaned(self, agent_id: str) -> None:
        agent = await self.get_agent(agent_id)
        if agent:
            agent.status = "orphaned"
            await self._agents.save(agent_id, agent)

    # ── Agent State ──

    async def save_state(self, agent_id: str, state: AgentStateRecord) -> None:
        state.last_updated = time.time()
        await self._state.save(agent_id, state)

    async def load_state(self, agent_id: str) -> AgentStateRecord:
        try:
            return await self._state.load(agent_id)
        except Exception:
            return AgentStateRecord()

    # ── Subscriptions ──

    async def register_subscription(
        self,
        agent_id: str,
        pattern: dict[str, Any],
        is_default: bool = False,
    ) -> str:
        sub_id = f"{agent_id}:{int(time.time() * 1000)}"
        record = SubscriptionRecord(
            agent_id=agent_id,
            pattern=pattern,
            is_default=is_default,
            created_at=time.time(),
        )
        await self._subs.set(sub_id, record.model_dump())

        # Update index
        index_key = f"idx:{agent_id}"
        existing = await self._subs.get(index_key, default=[])
        existing.append(sub_id)
        await self._subs.set(index_key, existing)
        return sub_id

    async def unregister_all(self, agent_id: str) -> None:
        index_key = f"idx:{agent_id}"
        sub_ids = await self._subs.get(index_key, default=[])
        for sub_id in sub_ids:
            await self._subs.delete(sub_id)
        await self._subs.delete(index_key)

    async def get_matching_agents(self, event: RemoraEvent) -> list[str]:
        """Get agents whose subscriptions match this event."""
        from remora.core.subscriptions import SubscriptionPattern

        all_subs = await self._subs.list(prefix="")
        matching = set()

        for item in all_subs:
            key = item.get("key", "")
            if key.startswith("idx:"):
                continue  # Skip index entries
            try:
                record = SubscriptionRecord(**item.get("value", {}))
                pattern = SubscriptionPattern(**record.pattern)
                if pattern.matches(event):
                    matching.add(record.agent_id)
            except Exception:
                continue

        return list(matching)

    async def get_subscriptions(self, agent_id: str) -> list[SubscriptionRecord]:
        index_key = f"idx:{agent_id}"
        sub_ids = await self._subs.get(index_key, default=[])
        results = []
        for sub_id in sub_ids:
            try:
                data = await self._subs.get(sub_id)
                results.append(SubscriptionRecord(**data))
            except Exception:
                continue
        return results

    # ── Lifecycle ──

    async def close(self) -> None:
        if self._workspace:
            await self._workspace.close()
            self._workspace = None
```

### Step 4.2: Simplify EventStore

**File**: `src/remora/core/event_store.py`

Remove:
- `EventSourcedBus` (already done in Phase 1.5)
- `get_graph_ids()` — unused in reactive model
- `delete_graph()` — unused in reactive model
- `_migrate_routing_fields()` — no legacy data
- `set_subscriptions()` / `set_event_bus()` — set in constructor only

Merge EventBus notification inline into `append()`:

```python
async def append(self, graph_id: str, event) -> int:
    event_id = await self._persist(event, graph_id)
    
    # Notify in-memory subscribers (UI, etc.)
    if self._event_bus:
        await self._event_bus.emit(event)
    
    # Queue triggers for matching subscriptions
    if self._swarm_store and self._trigger_queue:
        matching = await self._swarm_store.get_matching_agents(event)
        for agent_id in matching:
            await self._trigger_queue.put((agent_id, event_id, event))
    
    return event_id
```

**Target**: ~200 LOC (down from 382).

### Step 4.3: Update AgentRunner

**File**: `src/remora/core/agent_runner.py`

Replace three separate constructor params with one `SwarmStore`:

```python
# Before:
def __init__(self, event_store, subscriptions, swarm_state, config, event_bus):

# After:
def __init__(self, event_store: EventStore, store: SwarmStore, config: Config):
```

Update all calls:
- `self._subscriptions.*` → `self._store.*`
- `self._swarm_state.*` → `self._store.*`
- Use `config.swarm_id` instead of hardcoded `"swarm"`

### Step 4.4: Update Reconciler

**File**: `src/remora/core/reconciler.py`

Replace `swarm_state` + `subscriptions` params with single `SwarmStore`:

```python
# Before:
async def reconcile(swarm_state, subscriptions, project_root, config):

# After:
async def reconcile(store: SwarmStore, project_root: Path, config: Config):
```

### Step 4.5: Update SwarmExecutor

**File**: `src/remora/core/swarm_executor.py`

Use `SwarmStore` for agent state load/save instead of `AgentState` JSONL files.

### Step 4.6: Delete Old Storage Files

```bash
rm src/remora/core/swarm_state.py      # Replaced by SwarmStore
rm src/remora/core/subscriptions.py     # Replaced by SwarmStore  
rm src/remora/core/agent_state.py       # Replaced by SwarmStore
```

Keep `SubscriptionPattern` — move the dataclass + `matches()` method into `swarm_store.py` or a small `models.py`.

---

## Phase 5: Simplify Cairn Bridge → FSdantic

### Step 5.1: Refactor CairnWorkspaceService

**File**: `src/remora/core/cairn_bridge.py`

Replace low-level `cairn.runtime.workspace_manager` usage with `Fsdantic.open()`:

```python
# Before:
from cairn.runtime import workspace_manager as cairn_workspace_manager
workspace = await cairn_workspace_manager._open_workspace(path, readonly=False)

# After:
from fsdantic import Fsdantic
workspace = await Fsdantic.open(id=agent_id)
```

This gives us the full FSdantic API (files, kv, overlay, materialize) instead of raw workspace handles.

### Step 5.2: Simplify AgentWorkspace

**File**: `src/remora/core/workspace.py`

Since FSdantic handles concurrency internally, remove the dual-lock pattern:

```python
class AgentWorkspace:
    """Thin wrapper around FSdantic workspace for agent execution."""
    
    def __init__(self, workspace: Workspace, agent_id: str):
        self._workspace = workspace
        self._agent_id = agent_id
    
    @property
    def files(self): return self._workspace.files
    
    @property 
    def kv(self): return self._workspace.kv
    
    async def read(self, path): return await self._workspace.files.read(path)
    async def write(self, path, content): await self._workspace.files.write(path, content)
    async def close(self): await self._workspace.close()
```

---

## Phase 6: Flatten Service Layer

### Step 6.1: Simplify RemoraService

**File**: `src/remora/service/api.py`

Replace separate `EventStore`, `SwarmState`, `SubscriptionRegistry` creation with `SwarmStore`:

```python
# Before (in create_default):
event_store = EventStore(store_path)
subscriptions = SubscriptionRegistry(subscriptions_path)
swarm_state = SwarmState(swarm_state_path)

# After:
event_store = EventStore(store_path)
store = SwarmStore(workspace_id="remora-swarm")
```

The `__init__` reduces from 10 params to ~5.

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
- [ ] `grep -r "from remora.core.swarm_state\|from remora.core.agent_state\|from remora.core.subscriptions" src/` only shows `SubscriptionPattern` import if kept
- [ ] `python -c "from remora.core.swarm_store import SwarmStore"` succeeds
- [ ] `python -c "from remora.core.event_store import EventStore"` succeeds
- [ ] `pytest tests/` passes
- [ ] Only 2 storage concerns exist: `events.db` (SQLite) and FSdantic KV workspace

---

## Summary of Changes

| Phase | Description | LOC Removed | LOC Added |
|-------|-------------|-------------|-----------|
| 1 | Remove legacy code | ~1,100 | 0 |
| 2 | Fix critical bugs | ~5 | ~15 |
| 3 | Fix config issues | ~5 | ~5 |
| 4 | FSdantic KV storage | ~500 | ~120 |
| 5 | Simplify Cairn bridge | ~100 | ~50 |
| 6 | Flatten service layer | ~50 | ~10 |
| 7 | Fix remaining issues | ~20 | ~30 |
| 8 | Tests | 0 | ~120 |
| **Total** | | **~1,780** | **~350** |

**Net reduction**: ~1,430 LOC while gaining:
- 2 storage concerns instead of 6
- FSdantic KV for typed, namespaced state access
- No custom SQL for agent/subscription/state management
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
