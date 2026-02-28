# Remora Refactoring Guide

This guide provides step-by-step instructions to complete the Remora refactor and align the codebase with the design documents.

---

## Phase 1: Remove Legacy Code

### Step 1.1: Delete executor.py

**File**: `src/remora/core/executor.py` (581 LOC)

**Action**: Delete the entire file.

```bash
rm src/remora/core/executor.py
```

**Update imports** - Search and remove references:

1. `src/remora/core/__init__.py` - Remove `GraphExecutor` export if present
2. Any test files referencing `GraphExecutor`

**Verification**: Run `grep -r "GraphExecutor\|from remora.core.executor" src/` to find remaining references.

---

### Step 1.2: Delete graph.py

**File**: `src/remora/core/graph.py` (217 LOC)

**Action**: Delete the entire file.

```bash
rm src/remora/core/graph.py
```

**Update imports**:

1. Remove from `src/remora/core/__init__.py`
2. Remove from any files importing `AgentNode`, `build_graph`, `get_execution_batches`

**Note**: The legacy `executor.py` was the only consumer of this module.

---

### Step 1.3: Delete context.py

**File**: `src/remora/core/context.py` (171 LOC)

**Action**: Delete the entire file.

```bash
rm src/remora/core/context.py
```

**Update imports**:

1. Remove from `src/remora/core/__init__.py`
2. The only consumer was `executor.py` (already deleted)

**Migration**: If any "prior analysis" context is needed, it's now handled by `AgentState.chat_history`.

---

## Phase 2: Fix Critical Bugs

### Step 2.1: Fix chat.py Syntax Error

**File**: `src/remora/core/chat.py`
**Issue**: Methods defined after `return` statement in function

**Current (broken)**:
```python
def build_chat_tools(agent_workspace: AgentWorkspace, project_root: Path) -> list[Tool]:
    # ... tool definitions ...
    return [
        Tool.from_function(read_file),
        # ...
    ]

    @property
    def history(self) -> list[Message]:  # UNREACHABLE
        ...
```

**Fix**: Move the methods into the `ChatSession` class where they belong.

**Replace lines 237-259 with**:
```python
    return [
        Tool.from_function(read_file),
        Tool.from_function(write_file),
        Tool.from_function(list_dir),
        Tool.from_function(file_exists),
        Tool.from_function(search_files),
        Tool.from_function(discover_symbols),
    ]
```

**Then add these methods inside the `ChatSession` class (before `build_chat_tools`)**:
```python
class ChatSession:
    # ... existing methods ...

    @property
    def history(self) -> list[Message]:
        """Get conversation history."""
        return self._history.copy()

    def reset(self) -> None:
        """Clear conversation history."""
        self._history.clear()

    async def close(self) -> None:
        """Clean up resources."""
        if self._workspace:
            await self._workspace.close()
```

---

### Step 2.2: Fix Double Event Emission in EventSourcedBus

**File**: `src/remora/core/event_store.py`
**Issue**: `EventSourcedBus.emit()` causes double emission

**Current (line 358-361)**:
```python
async def emit(self, event: StructuredEvent | RemoraEvent) -> None:
    """Emit and persist an event."""
    await self._store.append(self._graph_id, event)  # This calls _bus.emit()
    await self._bus.emit(event)  # Double emit!
```

**Fix**: Remove the duplicate emission. The store already emits to the bus.

```python
async def emit(self, event: StructuredEvent | RemoraEvent) -> None:
    """Emit and persist an event."""
    await self._store.append(self._graph_id, event)
    # Note: append() already emits to event_bus if configured
```

---

### Step 2.3: Fix File Handle Leak in AgentState

**File**: `src/remora/core/agent_state.py`
**Issue**: File handle not closed in `save()`

**Current (line 77-78)**:
```python
line = json.dumps(state.to_dict(), default=str) + "\n"
path.open("a", encoding="utf-8").write(line)  # Leak!
```

**Fix**: Use context manager.

```python
line = json.dumps(state.to_dict(), default=str) + "\n"
with path.open("a", encoding="utf-8") as f:
    f.write(line)
```

---

### Step 2.4: Fix AgentState.from_dict() Side Effect

**File**: `src/remora/core/agent_state.py`
**Issue**: `from_dict()` modifies input dict

**Current (line 43-45)**:
```python
@classmethod
def from_dict(cls, data: dict[str, Any]) -> "AgentState":
    """Create from dictionary."""
    subs_data = data.pop("custom_subscriptions", [])  # Mutates input!
    custom_subscriptions = [SubscriptionPattern(**sub) for sub in subs_data]
    return cls(custom_subscriptions=custom_subscriptions, **data)
```

**Fix**: Copy the dict first.

```python
@classmethod
def from_dict(cls, data: dict[str, Any]) -> "AgentState":
    """Create from dictionary."""
    data = dict(data)  # Don't mutate input
    subs_data = data.pop("custom_subscriptions", [])
    custom_subscriptions = [SubscriptionPattern(**sub) for sub in subs_data]
    return cls(custom_subscriptions=custom_subscriptions, **data)
```

---

## Phase 3: Standardize Async/Sync Patterns

### Step 3.1: Make SubscriptionRegistry Properly Async

**File**: `src/remora/core/subscriptions.py`
**Issue**: Methods are marked `async` but use sync SQLite

**Option A (Recommended)**: Use `asyncio.to_thread()` like EventStore does.

**Replace SQLite operations** - Example for `register()`:

**Current**:
```python
async def register(
    self,
    agent_id: str,
    pattern: SubscriptionPattern,
    is_default: bool = False,
) -> Subscription:
    if self._conn is None:
        await self.initialize()

    now = time.time()
    pattern_json = json.dumps(asdict(pattern))

    cursor = self._conn.execute(  # Sync!
        """
        INSERT INTO subscriptions ...
        """,
        (agent_id, pattern_json, ...),
    )
    self._conn.commit()  # Sync!
```

**Fixed**:
```python
async def register(
    self,
    agent_id: str,
    pattern: SubscriptionPattern,
    is_default: bool = False,
) -> Subscription:
    if self._conn is None:
        await self.initialize()

    now = time.time()
    pattern_json = json.dumps(asdict(pattern))

    async with self._lock:
        cursor = await asyncio.to_thread(
            self._conn.execute,
            """
            INSERT INTO subscriptions (agent_id, pattern_json, is_default, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (agent_id, pattern_json, 1 if is_default else 0, now, now),
        )
        await asyncio.to_thread(self._conn.commit)
        sub_id = cursor.lastrowid

    return Subscription(...)
```

**Apply the same pattern to**:
- `unregister_all()`
- `get_subscriptions()`
- `get_matching_agents()`
- `close()` - make it `async def close(self)` properly

---

### Step 3.2: Make SwarmState Async

**File**: `src/remora/core/swarm_state.py`
**Issue**: All methods are sync but called from async context

**Option A**: Convert to async pattern matching EventStore.
**Option B**: Keep sync but document it clearly.

**Recommended**: Option B - SwarmState is low-frequency, sync is acceptable.

**Add docstring clarification**:
```python
class SwarmState:
    """Registry for all agents in the swarm.

    Note: Methods are intentionally synchronous as they are called
    infrequently during reconciliation. For high-frequency operations,
    see SubscriptionRegistry which uses async.
    """
```

---

## Phase 4: Fix Config Issues

### Step 4.1: Fix Frozen Dataclass with Mutable Default

**File**: `src/remora/core/config.py`
**Issue**: `bundle_mapping: dict` with `field(default_factory=dict)` breaks frozen dataclass

**Current (line 46-47)**:
```python
@dataclass(frozen=True, slots=True)
class Config:
    bundle_mapping: dict[str, str] = field(default_factory=dict)  # Mutable!
```

**Fix**: Use `MappingProxyType` or convert to tuple of tuples.

**Option A - MappingProxyType**:
```python
from types import MappingProxyType

@dataclass(frozen=True, slots=True)
class Config:
    bundle_mapping: MappingProxyType[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
```

**Option B - Remove frozen** (simpler):
```python
@dataclass(slots=True)  # Remove frozen
class Config:
    bundle_mapping: dict[str, str] = field(default_factory=dict)
```

**Recommendation**: Option B - frozen provides little value for a config object loaded once at startup.

---

### Step 4.2: Remove Duplicate ConfigError

**File**: `src/remora/core/config.py`
**Issue**: Defines ConfigError dynamically when it exists in errors.py

**Current (line 154)**:
```python
ConfigError = type("ConfigError", (Exception,), {})
```

**Fix**: Import from errors.py instead.

**Remove line 154** and add import:
```python
from remora.core.errors import ConfigError
```

---

## Phase 5: Fix NvimServer Issues

### Step 5.1: Fix Missing asdict Import

**File**: `src/remora/nvim/server.py`
**Issue**: `asdict()` function defined at bottom, not imported

**Current (line 260-268)**:
```python
def asdict(obj: Any) -> Any:
    """Simple asdict for dataclasses."""
    ...
```

**Fix**: Import from dataclasses module instead.

**Add import at top**:
```python
from dataclasses import asdict
```

**Remove lines 260-268** (the local asdict function).

---

### Step 5.2: Fix EventBus.unsubscribe() Call

**File**: `src/remora/nvim/server.py`
**Issue**: Line 70 calls `unsubscribe()` but signature is wrong

**Current (line 69-70)**:
```python
if self._event_bus is not None:
    self._event_bus.unsubscribe(self._broadcast_event)
```

**Fix**: This is actually correct - `EventBus.unsubscribe()` takes a handler. The issue is that the handler was registered with `subscribe_all()`, and `unsubscribe()` does handle this case (line 68-69 in event_bus.py).

**No change needed** - code is correct.

---

### Step 5.3: Use Configured swarm_id

**File**: `src/remora/nvim/server.py`
**Issue**: Hardcoded `"nvim"` as graph_id

**Current (line 169)**:
```python
await self._event_store.append("nvim", event)
```

**Fix**: Add swarm_id parameter to NvimServer.

```python
def __init__(
    self,
    socket_path: PathLike,
    event_store: EventStore,
    subscriptions: SubscriptionRegistry,
    event_bus: "EventBus | None" = None,
    project_root: PathLike | None = None,
    swarm_id: str = "swarm",  # Add parameter
):
    # ...
    self._swarm_id = swarm_id

# Then use self._swarm_id:
await self._event_store.append(self._swarm_id, event)
```

---

## Phase 6: Fix AgentRunner Issues

### Step 6.1: Use Config swarm_id

**File**: `src/remora/core/agent_runner.py`
**Issue**: Line 68 hardcodes swarm_id

**Current**:
```python
self._swarm_id = "swarm"
```

**Fix**:
```python
self._swarm_id = config.swarm_id
```

---

### Step 6.2: Clean Up Correlation Depth Tracking

**File**: `src/remora/core/agent_runner.py`
**Issue**: `_correlation_depth` dict grows unbounded

**Current**: Entries are decremented but only removed when reaching 0 from a specific path.

**Fix**: Add periodic cleanup or use TTL-based dict.

```python
import time

# In __init__:
self._correlation_timestamps: dict[str, float] = {}
self._cleanup_interval = 60.0  # seconds
self._last_cleanup = time.time()

# Add cleanup method:
def _cleanup_old_correlations(self) -> None:
    """Remove correlation entries older than cleanup interval."""
    now = time.time()
    if now - self._last_cleanup < self._cleanup_interval:
        return

    cutoff = now - self._cleanup_interval
    old_keys = [k for k, t in self._correlation_timestamps.items() if t < cutoff]
    for key in old_keys:
        self._correlation_depth.pop(key, None)
        self._correlation_timestamps.pop(key, None)

    self._last_cleanup = now

# Call in run_forever() loop:
async def run_forever(self) -> None:
    self._running = True
    try:
        async for agent_id, event_id, event in self._event_store.get_triggers():
            if not self._running:
                break

            self._cleanup_old_correlations()  # Add this
            # ... rest of loop
```

---

## Phase 7: Optimize Performance

### Step 7.1: Cache Workspace Initialization

**File**: `src/remora/core/swarm_executor.py`
**Issue**: `workspace_service.initialize()` called every turn

**Current (line 77)**:
```python
await self._workspace_service.initialize()
```

**Fix**: Initialize in `__init__` or use lazy initialization with flag.

```python
def __init__(self, ...):
    # ...
    self._workspace_initialized = False

async def _ensure_workspace_initialized(self) -> None:
    if not self._workspace_initialized:
        await self._workspace_service.initialize()
        self._workspace_initialized = True

async def run_agent(self, state: AgentState, trigger_event: Any = None) -> str:
    # Replace line 77 with:
    await self._ensure_workspace_initialized()
    # ...
```

---

### Step 7.2: Optimize Subscription Matching

**File**: `src/remora/core/subscriptions.py`
**Issue**: `get_matching_agents()` loads all subscriptions

**Add SQL-based filtering**:

```python
async def get_matching_agents(self, event: RemoraEvent) -> list[str]:
    """Get all agent IDs whose subscriptions match the event."""
    if self._conn is None:
        await self.initialize()

    event_type = type(event).__name__
    to_agent = getattr(event, "to_agent", None)

    # Build dynamic query with SQL-level filtering
    query = "SELECT DISTINCT agent_id, pattern_json FROM subscriptions WHERE 1=1"
    params = []

    # If event has to_agent, we can filter in SQL
    if to_agent:
        # Include subscriptions that either:
        # 1. Have no to_agent filter (match any)
        # 2. Match this specific to_agent
        query += """ AND (
            json_extract(pattern_json, '$.to_agent') IS NULL
            OR json_extract(pattern_json, '$.to_agent') = ?
        )"""
        params.append(to_agent)

    async with self._lock:
        cursor = await asyncio.to_thread(
            self._conn.execute,
            query,
            params,
        )
        rows = await asyncio.to_thread(cursor.fetchall)

    # Still need Python filtering for complex patterns
    matching_agents = []
    seen_agents = set()

    for row in rows:
        pattern_data = json.loads(row["pattern_json"])
        pattern = SubscriptionPattern(**pattern_data)

        if pattern.matches(event):
            agent_id = row["agent_id"]
            if agent_id not in seen_agents:
                matching_agents.append(agent_id)
                seen_agents.add(agent_id)

    return matching_agents
```

---

## Phase 8: Add Missing Tests

### Step 8.1: AgentRunner Cascade Prevention Tests

**Create**: `tests/test_agent_runner_cascade.py`

```python
import pytest
import asyncio
from remora.core.agent_runner import AgentRunner
from remora.core.events import AgentMessageEvent

@pytest.fixture
def runner(event_store, subscriptions, swarm_state, config, event_bus):
    return AgentRunner(
        event_store=event_store,
        subscriptions=subscriptions,
        swarm_state=swarm_state,
        config=config,
        event_bus=event_bus,
    )

async def test_depth_limit_prevents_infinite_cascade(runner):
    """Verify cascade stops at max_trigger_depth."""
    # Setup: Create circular subscription
    # Agent A triggers Agent B triggers Agent A
    # ...

async def test_cooldown_prevents_rapid_retrigger(runner):
    """Verify cooldown prevents same agent from triggering too fast."""
    # ...
```

### Step 8.2: SubscriptionPattern Matching Tests

**Create**: `tests/test_subscription_patterns.py`

```python
import pytest
from remora.core.subscriptions import SubscriptionPattern
from remora.core.events import AgentMessageEvent, ContentChangedEvent

def test_pattern_matches_any_when_all_none():
    pattern = SubscriptionPattern()
    event = AgentMessageEvent(from_agent="a", to_agent="b", content="test")
    assert pattern.matches(event)

def test_pattern_filters_by_event_type():
    pattern = SubscriptionPattern(event_types=["AgentMessageEvent"])
    msg_event = AgentMessageEvent(from_agent="a", to_agent="b", content="test")
    content_event = ContentChangedEvent(path="foo.py")

    assert pattern.matches(msg_event)
    assert not pattern.matches(content_event)

def test_pattern_path_glob_matching():
    pattern = SubscriptionPattern(path_glob="src/**/*.py")
    event = ContentChangedEvent(path="src/core/agent.py")

    assert pattern.matches(event)
```

---

## Phase 9: Documentation Updates

### Step 9.1: Update Module Docstrings

After removing legacy files, update `src/remora/core/__init__.py`:

```python
"""Remora Core - Reactive Agent Swarm Framework.

Core Components:
- AgentRunner: Reactive event loop processing triggers
- SwarmExecutor: Single-agent turn execution
- SubscriptionRegistry: Event pattern matching and routing
- EventStore: SQLite-backed event sourcing with trigger queue
- AgentState: Per-agent persistent state (JSONL)
- SwarmState: Agent registry (SQLite)
- Reconciler: Startup discovery and state sync

Event Flow:
    Event → EventStore.append() → SubscriptionRegistry.match()
    → TriggerQueue → AgentRunner → SwarmExecutor → Agent Turn
"""
```

---

## Phase 10: Verification Checklist

After completing all phases, verify:

- [ ] `grep -r "GraphExecutor" src/` returns no results
- [ ] `grep -r "from remora.core.executor" src/` returns no results
- [ ] `grep -r "from remora.core.graph" src/` returns no results
- [ ] `grep -r "from remora.core.context" src/` returns no results
- [ ] `python -c "from remora.core.chat import ChatSession"` succeeds
- [ ] `python -c "from remora.core.config import Config; Config()"` succeeds
- [ ] `pytest tests/` passes
- [ ] `remora swarm start --help` works
- [ ] `remora swarm reconcile` works on a sample project

---

## Summary of Changes

| Phase | Files Changed | Lines Removed | Lines Added |
|-------|--------------|---------------|-------------|
| 1. Remove Legacy | 3 files deleted | ~970 | 0 |
| 2. Fix Critical Bugs | 3 files | ~5 | ~15 |
| 3. Async/Sync | 1 file | ~30 | ~50 |
| 4. Fix Config | 1 file | ~5 | ~5 |
| 5. Fix NvimServer | 1 file | ~10 | ~5 |
| 6. Fix AgentRunner | 1 file | ~5 | ~20 |
| 7. Optimize | 2 files | ~10 | ~30 |
| 8. Add Tests | 2 new files | 0 | ~100 |
| **Total** | ~13 files | ~1035 | ~225 |

**Net reduction**: ~810 lines of code while fixing bugs and adding test coverage.

---

## Order of Operations

**Critical path** (do these first in order):
1. Phase 1 - Remove legacy code (unblocks other changes)
2. Phase 2 - Fix critical bugs (unblocks testing)
3. Phase 4.1 - Fix Config frozen issue (unblocks running)

**Can be parallelized**:
- Phase 3 (Async/Sync)
- Phase 5 (NvimServer)
- Phase 6 (AgentRunner)

**Do after core fixes**:
- Phase 7 (Optimization)
- Phase 8 (Tests)
- Phase 9 (Documentation)

---

## Phase 11: Storage Consolidation

This phase consolidates the fragmented storage architecture into a unified database. See CODE_REVIEW.md Appendix A for full analysis.

### Step 11.1: Create Unified RemoraStore

**Create**: `src/remora/core/store.py`

```python
"""Unified Remora state storage.

Consolidates EventStore, SubscriptionRegistry, SwarmState, and AgentState
into a single SQLite database with proper transactions.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from remora.core.events import RemoraEvent
from remora.core.subscriptions import SubscriptionPattern, Subscription
from remora.core.swarm_state import AgentMetadata
from remora.utils import PathLike, normalize_path

if TYPE_CHECKING:
    from remora.core.event_bus import EventBus


class RemoraStore:
    """Unified storage for all Remora state.

    Combines:
    - Events (formerly EventStore)
    - Subscriptions (formerly SubscriptionRegistry)
    - Agents (formerly SwarmState)
    - Agent state (formerly JSONL files)
    """

    def __init__(
        self,
        db_path: PathLike,
        event_bus: "EventBus | None" = None,
    ):
        self._db_path = normalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._event_bus = event_bus
        self._trigger_queue: asyncio.Queue[tuple[str, int, RemoraEvent]] | None = None

    async def initialize(self) -> None:
        """Initialize the database with all tables."""
        async with self._lock:
            if self._conn is not None:
                return

            self._conn = await asyncio.to_thread(
                sqlite3.connect,
                str(self._db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row

            await asyncio.to_thread(
                self._conn.executescript,
                """
                -- Events table (formerly EventStore)
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    graph_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL,
                    from_agent TEXT,
                    to_agent TEXT,
                    correlation_id TEXT,
                    tags TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_graph_id ON events(graph_id);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_to_agent ON events(to_agent);

                -- Subscriptions table (formerly SubscriptionRegistry)
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    pattern_json TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_subscriptions_agent_id ON subscriptions(agent_id);

                -- Agents table (formerly SwarmState)
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    parent_id TEXT,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

                -- Agent state table (formerly JSONL files)
                CREATE TABLE IF NOT EXISTS agent_state (
                    agent_id TEXT PRIMARY KEY,
                    chat_history TEXT,
                    connections TEXT,
                    custom_subscriptions TEXT,
                    last_updated REAL NOT NULL,
                    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
                );
                """,
            )

            self._trigger_queue = asyncio.Queue()

    # ========== Event Methods ==========

    async def append_event(
        self,
        graph_id: str,
        event: RemoraEvent,
    ) -> int:
        """Append an event to the store."""
        if self._conn is None:
            await self.initialize()

        event_type = type(event).__name__
        payload = self._serialize_event(event)
        timestamp = getattr(event, "timestamp", time.time())
        created_at = time.time()

        from_agent = getattr(event, "from_agent", None)
        to_agent = getattr(event, "to_agent", None)
        correlation_id = getattr(event, "correlation_id", None)
        tags = getattr(event, "tags", None)
        tags_json = json.dumps(tags) if tags else None

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                """
                INSERT INTO events (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (graph_id, event_type, payload, timestamp, created_at, from_agent, to_agent, correlation_id, tags_json),
            )
            await asyncio.to_thread(self._conn.commit)
            event_id = cursor.lastrowid or 0

        # Queue triggers for matching subscriptions
        if self._trigger_queue is not None:
            matching_agents = await self.get_matching_agents(event)
            for agent_id in matching_agents:
                await self._trigger_queue.put((agent_id, event_id, event))

        # Emit to event bus for UI updates
        if self._event_bus is not None:
            await self._event_bus.emit(event)

        return event_id

    async def get_triggers(self) -> AsyncIterator[tuple[str, int, RemoraEvent]]:
        """Iterate over event triggers for matched subscriptions."""
        if self._trigger_queue is None:
            raise RuntimeError("Store not initialized")

        while True:
            try:
                trigger = await self._trigger_queue.get()
                yield trigger
            except asyncio.CancelledError:
                break

    # ========== Subscription Methods ==========

    async def register_subscription(
        self,
        agent_id: str,
        pattern: SubscriptionPattern,
        is_default: bool = False,
    ) -> Subscription:
        """Register a new subscription."""
        if self._conn is None:
            await self.initialize()

        now = time.time()
        pattern_json = json.dumps(asdict(pattern))

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                """
                INSERT INTO subscriptions (agent_id, pattern_json, is_default, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (agent_id, pattern_json, 1 if is_default else 0, now, now),
            )
            await asyncio.to_thread(self._conn.commit)
            sub_id = cursor.lastrowid

        return Subscription(
            id=sub_id,
            agent_id=agent_id,
            pattern=pattern,
            is_default=is_default,
            created_at=now,
            updated_at=now,
        )

    async def get_matching_agents(self, event: RemoraEvent) -> list[str]:
        """Get all agent IDs whose subscriptions match the event."""
        if self._conn is None:
            await self.initialize()

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                "SELECT agent_id, pattern_json FROM subscriptions ORDER BY id",
            )
            rows = await asyncio.to_thread(cursor.fetchall)

        matching_agents = []
        seen_agents = set()

        for row in rows:
            pattern_data = json.loads(row["pattern_json"])
            pattern = SubscriptionPattern(**pattern_data)

            if pattern.matches(event):
                agent_id = row["agent_id"]
                if agent_id not in seen_agents:
                    matching_agents.append(agent_id)
                    seen_agents.add(agent_id)

        return matching_agents

    # ========== Agent Registry Methods ==========

    async def upsert_agent(self, metadata: AgentMetadata) -> None:
        """Insert or update an agent."""
        if self._conn is None:
            await self.initialize()

        now = time.time()
        async with self._lock:
            await asyncio.to_thread(
                self._conn.execute,
                """
                INSERT INTO agents (agent_id, node_type, name, full_name, file_path, parent_id, start_line, end_line, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    node_type = excluded.node_type,
                    name = excluded.name,
                    full_name = excluded.full_name,
                    file_path = excluded.file_path,
                    parent_id = excluded.parent_id,
                    start_line = excluded.start_line,
                    end_line = excluded.end_line,
                    updated_at = excluded.updated_at,
                    status = 'active'
                """,
                (
                    metadata.agent_id,
                    metadata.node_type,
                    metadata.name,
                    metadata.full_name,
                    metadata.file_path,
                    metadata.parent_id,
                    metadata.start_line,
                    metadata.end_line,
                    now,
                    now,
                ),
            )
            await asyncio.to_thread(self._conn.commit)

    async def list_agents(self, status: str | None = None) -> list[dict[str, Any]]:
        """List all agents, optionally filtered by status."""
        if self._conn is None:
            await self.initialize()

        query = "SELECT * FROM agents"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)

        async with self._lock:
            cursor = await asyncio.to_thread(self._conn.execute, query, params)
            rows = await asyncio.to_thread(cursor.fetchall)

        return [dict(row) for row in rows]

    # ========== Agent State Methods ==========

    async def save_agent_state(
        self,
        agent_id: str,
        chat_history: list[dict[str, Any]],
        connections: dict[str, str],
        custom_subscriptions: list[SubscriptionPattern],
    ) -> None:
        """Save agent state to the database."""
        if self._conn is None:
            await self.initialize()

        now = time.time()
        chat_json = json.dumps(chat_history, default=str)
        conn_json = json.dumps(connections)
        subs_json = json.dumps([asdict(s) for s in custom_subscriptions])

        async with self._lock:
            await asyncio.to_thread(
                self._conn.execute,
                """
                INSERT INTO agent_state (agent_id, chat_history, connections, custom_subscriptions, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    chat_history = excluded.chat_history,
                    connections = excluded.connections,
                    custom_subscriptions = excluded.custom_subscriptions,
                    last_updated = excluded.last_updated
                """,
                (agent_id, chat_json, conn_json, subs_json, now),
            )
            await asyncio.to_thread(self._conn.commit)

    async def load_agent_state(self, agent_id: str) -> dict[str, Any] | None:
        """Load agent state from the database."""
        if self._conn is None:
            await self.initialize()

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                "SELECT * FROM agent_state WHERE agent_id = ?",
                (agent_id,),
            )
            row = await asyncio.to_thread(cursor.fetchone)

        if row is None:
            return None

        return {
            "agent_id": row["agent_id"],
            "chat_history": json.loads(row["chat_history"] or "[]"),
            "connections": json.loads(row["connections"] or "{}"),
            "custom_subscriptions": json.loads(row["custom_subscriptions"] or "[]"),
            "last_updated": row["last_updated"],
        }

    # ========== Utilities ==========

    def _serialize_event(self, event: RemoraEvent) -> str:
        """Serialize an event to JSON."""
        if is_dataclass(event):
            data = asdict(event)
        elif hasattr(event, "__dict__"):
            data = dict(vars(event))
        else:
            data = {"value": str(event)}
        return json.dumps(data, default=str)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            async with self._lock:
                await asyncio.to_thread(self._conn.close)
                self._conn = None
        self._trigger_queue = None


__all__ = ["RemoraStore"]
```

---

### Step 11.2: Update AgentRunner to Use RemoraStore

**File**: `src/remora/core/agent_runner.py`

**Current imports**:
```python
from remora.core.event_store import EventStore
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.swarm_state import SwarmState
```

**New imports**:
```python
from remora.core.store import RemoraStore
```

**Current `__init__`**:
```python
def __init__(
    self,
    event_store: EventStore,
    subscriptions: SubscriptionRegistry,
    swarm_state: SwarmState,
    config: Config,
    event_bus: "EventBus",
):
    self._event_store = event_store
    self._subscriptions = subscriptions
    self._swarm_state = swarm_state
    # ...
```

**New `__init__`**:
```python
def __init__(
    self,
    store: RemoraStore,
    config: Config,
    event_bus: "EventBus",
):
    self._store = store
    self._config = config
    self._event_bus = event_bus
    # ...
```

**Update all method calls**:
- `self._event_store.append()` → `self._store.append_event()`
- `self._event_store.get_triggers()` → `self._store.get_triggers()`
- `self._subscriptions.get_matching_agents()` → `self._store.get_matching_agents()`
- `self._swarm_state.list_agents()` → `await self._store.list_agents()`

---

### Step 11.3: Update Reconciler to Use RemoraStore

**File**: `src/remora/core/reconciler.py`

**Replace**:
```python
async def reconcile(
    swarm_state: SwarmState,
    subscriptions: SubscriptionRegistry,
    project_root: Path,
    config: Config,
) -> ReconcileResult:
```

**With**:
```python
async def reconcile(
    store: RemoraStore,
    project_root: Path,
    config: Config,
) -> ReconcileResult:
```

**Update all calls**:
- `swarm_state.list_agents()` → `await store.list_agents()`
- `swarm_state.upsert()` → `await store.upsert_agent()`
- `await subscriptions.register_defaults()` → `await store.register_subscription()` (loop)

---

### Step 11.4: Delete Old Storage Files

After migration is complete and tested:

```bash
rm src/remora/core/event_store.py
rm src/remora/core/subscriptions.py
rm src/remora/core/swarm_state.py
rm src/remora/core/agent_state.py
```

**Update `src/remora/core/__init__.py`**:
```python
# Remove old exports
# - EventStore, EventSourcedBus
# - SubscriptionRegistry, SubscriptionPattern, Subscription
# - SwarmState, AgentMetadata
# - AgentState, load, save

# Add new export
from remora.core.store import RemoraStore
```

---

### Step 11.5: Update Database Path in Config

**File**: `src/remora/core/config.py`

**Add/update field**:
```python
@dataclass(slots=True)
class Config:
    # ... existing fields ...

    # Storage - unified database
    db_path: str = ".remora/remora.db"

    # Remove these if present:
    # event_db_path: str
    # subscriptions_db_path: str
    # swarm_state_db_path: str
```

---

### Step 11.6: Migration Script for Existing Data

**Create**: `scripts/migrate_to_unified_db.py`

```python
#!/usr/bin/env python3
"""Migrate old Remora databases to unified format."""

import json
import sqlite3
from pathlib import Path

def migrate(remora_dir: Path) -> None:
    """Migrate old databases to unified remora.db."""

    new_db = remora_dir / "remora.db"

    # Skip if already migrated
    if new_db.exists():
        print(f"Unified database already exists: {new_db}")
        return

    conn = sqlite3.connect(str(new_db))

    # Create schema (same as RemoraStore.initialize)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (...);
        CREATE TABLE IF NOT EXISTS subscriptions (...);
        CREATE TABLE IF NOT EXISTS agents (...);
        CREATE TABLE IF NOT EXISTS agent_state (...);
    """)

    # Migrate events.db
    events_db = remora_dir / "events.db"
    if events_db.exists():
        print(f"Migrating events from {events_db}")
        src = sqlite3.connect(str(events_db))
        for row in src.execute("SELECT * FROM events"):
            conn.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        src.close()
        conn.commit()

    # Migrate subscriptions.db
    subs_db = remora_dir / "subscriptions.db"
    if subs_db.exists():
        print(f"Migrating subscriptions from {subs_db}")
        src = sqlite3.connect(str(subs_db))
        for row in src.execute("SELECT * FROM subscriptions"):
            conn.execute(
                "INSERT INTO subscriptions VALUES (?, ?, ?, ?, ?, ?)",
                row,
            )
        src.close()
        conn.commit()

    # Migrate swarm_state.db
    swarm_db = remora_dir / "swarm_state.db"
    if swarm_db.exists():
        print(f"Migrating agents from {swarm_db}")
        src = sqlite3.connect(str(swarm_db))
        for row in src.execute("SELECT * FROM agents"):
            conn.execute(
                "INSERT INTO agents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        src.close()
        conn.commit()

    # Migrate JSONL state files
    agents_dir = remora_dir / "agents"
    if agents_dir.exists():
        for state_file in agents_dir.rglob("state.jsonl"):
            agent_id = state_file.parent.name
            print(f"Migrating state for {agent_id}")

            lines = state_file.read_text().strip().split("\n")
            if lines:
                data = json.loads(lines[-1])
                conn.execute(
                    """
                    INSERT INTO agent_state (agent_id, chat_history, connections, custom_subscriptions, last_updated)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        json.dumps(data.get("chat_history", [])),
                        json.dumps(data.get("connections", {})),
                        json.dumps(data.get("custom_subscriptions", [])),
                        data.get("last_updated", 0),
                    ),
                )
        conn.commit()

    conn.close()
    print(f"Migration complete: {new_db}")


if __name__ == "__main__":
    import sys
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".remora")
    migrate(path)
```

---

### Step 11.7: Verification After Consolidation

```bash
# Verify unified database exists
ls -la .remora/remora.db

# Verify tables
sqlite3 .remora/remora.db ".tables"
# Expected: agent_state  agents  events  subscriptions

# Verify data migrated
sqlite3 .remora/remora.db "SELECT COUNT(*) FROM events"
sqlite3 .remora/remora.db "SELECT COUNT(*) FROM agents"
sqlite3 .remora/remora.db "SELECT COUNT(*) FROM subscriptions"

# Run tests
pytest tests/

# Test basic operations
remora swarm reconcile
remora swarm start --once
```

---

## Updated Summary After Consolidation

| Phase | Files Changed | Lines Removed | Lines Added |
|-------|--------------|---------------|-------------|
| 1-10. (Previous) | ~13 files | ~1035 | ~225 |
| 11. Storage Consolidation | 6 files | ~900 | ~350 |
| **Total** | ~19 files | ~1935 | ~575 |

**Net reduction**: ~1360 lines of code while gaining:
- Single database for all Remora state
- Atomic transactions across components
- Simplified mental model (2 storage concerns: state + workspaces)
- Better async consistency
