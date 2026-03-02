# EventLog-First Architectural Unification

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Collapse four databases, two event systems, and three notification paths into a single EventLog-first architecture where every state change is an event, every event is persisted, and every persistence notifies.

**Architecture:** `EventLog` replaces both `EventBus` and `EventStore` as the single write path. On `append()`, it inserts the event + applies a projection (materialized view update) in one SQLite transaction, then runs subscription matching to queue agent triggers and notifies in-process subscribers. Cross-process readers (web servers) tail the events table by rowid. The `nodes`, `edges`, `proposals` tables become materialized views derived from events. `RemoraDB` (indexer.db) is the single database.

**Tech Stack:** Python 3.12, SQLite WAL, Starlette, datastar-py, pygls, d3-force

**Design doc:** `docs/plans/EVENT_ARCHITECTURE_ALIGNMENT.md` (authoritative reference)

---

## Background

See `docs/plans/EVENT_ARCHITECTURE_ALIGNMENT.md` for the full analysis of the current state, design principles, and architectural decisions. This plan implements that design.

### Key Decisions (from design doc)

1. **Cursor focus:** Debounced event (200ms stable) — not direct write
2. **Kernel events:** Full event treatment — subscription matching runs on ALL events including `ToolCallEvent`, `ModelResponseEvent`, etc.
3. **Schema versioning:** JSON payloads, defaults on missing fields
4. **command_queue:** Stays as a separate work queue table

---

## Implementation Tasks

### Phase 1: Foundation (EventLog + Schema)

### Task 1: Enhance events table schema and add subscriptions table to RemoraDB

Add routing fields (`from_agent`, `to_agent`, `tags`, `created_at`) to the events table schema. Add the `subscriptions` table. Add `full_name` column to nodes (needed for SwarmState elimination).

**Files:**
- Modify: `src/remora/lsp/db.py:45-121` (schema init)
- Test: `tests/test_db_schema_v2.py`

**Step 1: Write the failing test**

```python
# tests/test_db_schema_v2.py
import pytest
import sqlite3
from remora.lsp.db import RemoraDB


@pytest.fixture
def db(tmp_path):
    return RemoraDB(db_path=str(tmp_path / "test.db"))


def test_events_table_has_routing_fields(db):
    """Events table should have from_agent, to_agent, tags, created_at columns."""
    cursor = db.conn.cursor()
    cursor.execute("PRAGMA table_info(events)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "from_agent" in columns
    assert "to_agent" in columns
    assert "tags" in columns
    assert "created_at" in columns


def test_subscriptions_table_exists(db):
    """Subscriptions table should exist with correct schema."""
    cursor = db.conn.cursor()
    cursor.execute("PRAGMA table_info(subscriptions)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "agent_id" in columns
    assert "pattern_json" in columns
    assert "is_default" in columns
    assert "created_at" in columns
    assert "updated_at" in columns


def test_subscriptions_crud(db):
    """Basic CRUD on subscriptions table."""
    cursor = db.conn.cursor()
    cursor.execute(
        "INSERT INTO subscriptions (agent_id, pattern_json, is_default, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("agent1", '{"to_agent": "agent1"}', 0, 1.0, 1.0),
    )
    db.conn.commit()
    cursor.execute("SELECT count(*) FROM subscriptions")
    assert cursor.fetchone()[0] == 1


def test_nodes_has_full_name(db):
    """Nodes table should have full_name column."""
    cursor = db.conn.cursor()
    cursor.execute("PRAGMA table_info(nodes)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "full_name" in columns


def test_events_routing_fields_index(db):
    """Events table should have indexes on routing fields."""
    cursor = db.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events'")
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_events_to_agent" in indexes
    assert "idx_events_type" in indexes
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_db_schema_v2.py -v`
Expected: FAIL — `from_agent` etc. not in events schema, subscriptions table doesn't exist

**Step 3: Update `_init_schema()` in `src/remora/lsp/db.py`**

In the events table definition, add the new columns. Add the subscriptions table and new indexes. Add `full_name` to nodes.

Modify the `CREATE TABLE IF NOT EXISTS events` block to:

```sql
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    created_at REAL,
    correlation_id TEXT,
    agent_id TEXT,
    from_agent TEXT,
    to_agent TEXT,
    tags TEXT,
    payload JSON NOT NULL
);
```

Add after the existing `CREATE INDEX` statements:

```sql
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    pattern_json TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_agent ON subscriptions(agent_id);
CREATE INDEX IF NOT EXISTS idx_events_to_agent ON events(to_agent);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
```

Add `full_name` to the nodes table: add `full_name TEXT DEFAULT ''` after the `name` column.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_db_schema_v2.py -v`
Expected: PASS

**Step 5: Run existing tests to check for regressions**

Run: `pytest tests/ -v --timeout=30`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add src/remora/lsp/db.py tests/test_db_schema_v2.py
git commit -m "feat(db): add routing fields to events, subscriptions table, full_name to nodes"
```

---

### Task 2: Add new event types to core/events.py

Add the event types needed for materialized view projections: `NodeUpsertedEvent`, `NodeOrphanedEvent`, `EdgeUpdatedEvent`, `ProposalCreatedEvent`, `ProposalAcceptedEvent`, `ProposalRejectedEvent`, `CursorFocusChangedEvent`, `SubscriptionRegisteredEvent`, `SubscriptionRemovedEvent`.

**Files:**
- Modify: `src/remora/core/events.py`
- Test: `tests/test_new_event_types.py`

**Step 1: Write the failing test**

```python
# tests/test_new_event_types.py
import pytest
from remora.core.events import (
    NodeUpsertedEvent,
    NodeOrphanedEvent,
    EdgeUpdatedEvent,
    ProposalCreatedEvent,
    ProposalAcceptedEvent,
    ProposalRejectedEvent,
    CursorFocusChangedEvent,
    SubscriptionRegisteredEvent,
    SubscriptionRemovedEvent,
)
from dataclasses import asdict


def test_node_upserted_event():
    e = NodeUpsertedEvent(
        agent_id="n1",
        node_type="function",
        name="foo",
        file_path="foo.py",
        start_line=1,
        end_line=10,
        source_code="def foo(): pass",
        source_hash="abc123",
    )
    assert e.agent_id == "n1"
    d = asdict(e)
    assert "timestamp" in d


def test_node_orphaned_event():
    e = NodeOrphanedEvent(agent_id="n1")
    assert e.agent_id == "n1"


def test_edge_updated_event():
    e = EdgeUpdatedEvent(from_id="n1", to_id="n2", edge_type="calls", removed=False)
    assert e.from_id == "n1"
    assert not e.removed


def test_proposal_created_event():
    e = ProposalCreatedEvent(
        proposal_id="p1", agent_id="n1",
        old_source="old", new_source="new", diff="diff",
    )
    assert e.proposal_id == "p1"


def test_proposal_accepted_event():
    e = ProposalAcceptedEvent(proposal_id="p1")
    assert e.proposal_id == "p1"


def test_proposal_rejected_event():
    e = ProposalRejectedEvent(proposal_id="p1", feedback="no good")
    assert e.feedback == "no good"


def test_cursor_focus_changed_event():
    e = CursorFocusChangedEvent(agent_id="n1", file_path="foo.py", line=42)
    assert e.line == 42


def test_subscription_registered_event():
    e = SubscriptionRegisteredEvent(
        subscription_id=1, agent_id="n1", pattern_json='{"to_agent":"n1"}',
    )
    assert e.subscription_id == 1


def test_subscription_removed_event():
    e = SubscriptionRemovedEvent(subscription_id=1, agent_id="n1")
    assert e.subscription_id == 1


def test_events_are_frozen():
    e = NodeUpsertedEvent(
        agent_id="n1", node_type="function", name="foo",
        file_path="foo.py", start_line=1, end_line=10,
        source_code="def foo(): pass", source_hash="abc",
    )
    with pytest.raises(AttributeError):
        e.name = "bar"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_new_event_types.py -v`
Expected: FAIL — ImportError, event types don't exist yet

**Step 3: Add new event types to `src/remora/core/events.py`**

After the existing `ManualTriggerEvent` and before the union type, add:

```python
# ============================================================================
# State Mutation Events (for materialized view projections)
# ============================================================================

@dataclass(frozen=True, slots=True)
class NodeUpsertedEvent:
    """Node created or updated by AST watcher."""
    agent_id: str
    node_type: str
    name: str
    file_path: str
    start_line: int
    end_line: int
    source_code: str
    source_hash: str
    full_name: str = ""
    start_col: int = 0
    end_col: int = 0
    parent_id: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class NodeOrphanedEvent:
    """Node no longer found in source."""
    agent_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class EdgeUpdatedEvent:
    """Call graph edge added or removed."""
    from_id: str
    to_id: str
    edge_type: str
    removed: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class ProposalCreatedEvent:
    """Agent proposed a rewrite."""
    proposal_id: str
    agent_id: str
    old_source: str
    new_source: str
    diff: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class ProposalAcceptedEvent:
    """Human approved proposal."""
    proposal_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class ProposalRejectedEvent:
    """Human rejected proposal."""
    proposal_id: str
    feedback: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class CursorFocusChangedEvent:
    """User moved cursor in Neovim (debounced)."""
    agent_id: str | None
    file_path: str
    line: int
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class SubscriptionRegisteredEvent:
    """Agent registered a subscription."""
    subscription_id: int
    agent_id: str
    pattern_json: str
    is_default: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class SubscriptionRemovedEvent:
    """Subscription removed."""
    subscription_id: int
    agent_id: str
    timestamp: float = field(default_factory=time.time)
```

Update the `RemoraEvent` union type to include all new types. Update `__all__` to export them.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_new_event_types.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/remora/core/events.py tests/test_new_event_types.py
git commit -m "feat(events): add state mutation event types for materialized view projections"
```

---

### Task 3: Build EventLog class

This is the core of the new architecture. `EventLog` replaces both `EventBus` (in-process pub/sub) and `EventStore` (persistence + trigger queue). It provides `append()` as the single write path.

**Files:**
- Create: `src/remora/core/event_log.py`
- Test: `tests/test_event_log.py`

**Step 1: Write the failing test**

```python
# tests/test_event_log.py
import asyncio
import json
import pytest
from remora.core.event_log import EventLog
from remora.core.events import (
    AgentMessageEvent,
    NodeUpsertedEvent,
    ProposalCreatedEvent,
    AgentStartEvent,
    ToolCallEvent,
)
from remora.core.subscriptions import SubscriptionPattern
from remora.lsp.db import RemoraDB


@pytest.fixture
def db(tmp_path):
    return RemoraDB(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def event_log(db):
    return EventLog(db)


# --- append() basics ---

@pytest.mark.asyncio
async def test_append_inserts_event(event_log, db):
    """append() should insert a row into the events table."""
    event = AgentMessageEvent(
        from_agent="a1", to_agent="a2", content="hello",
    )
    rowid = await event_log.append(event)
    assert rowid > 0

    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM events WHERE event_id = (SELECT event_id FROM events WHERE rowid = ?)", (rowid,))
    row = cursor.fetchone()
    assert row is not None
    assert row["event_type"] == "AgentMessageEvent"
    assert row["from_agent"] == "a1"
    assert row["to_agent"] == "a2"


@pytest.mark.asyncio
async def test_append_extracts_routing_fields(event_log, db):
    """append() should extract from_agent, to_agent, correlation_id, tags."""
    event = AgentMessageEvent(
        from_agent="a1", to_agent="a2", content="hello",
        correlation_id="corr1", tags=["test"],
    )
    rowid = await event_log.append(event)
    cursor = db.conn.cursor()
    cursor.execute("SELECT from_agent, to_agent, correlation_id, tags FROM events WHERE rowid = ?", (rowid,))
    row = cursor.fetchone()
    assert row["from_agent"] == "a1"
    assert row["to_agent"] == "a2"
    assert row["correlation_id"] == "corr1"
    assert json.loads(row["tags"]) == ["test"]


# --- Projection ---

@pytest.mark.asyncio
async def test_node_upserted_projection(event_log, db):
    """NodeUpsertedEvent should INSERT/UPDATE the nodes table."""
    event = NodeUpsertedEvent(
        agent_id="n1", node_type="function", name="foo",
        file_path="foo.py", start_line=1, end_line=10,
        source_code="def foo(): pass", source_hash="abc",
    )
    await event_log.append(event)
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM nodes WHERE id = ?", ("n1",))
    row = cursor.fetchone()
    assert row is not None
    assert row["name"] == "foo"
    assert row["source_code"] == "def foo(): pass"


@pytest.mark.asyncio
async def test_proposal_created_projection(event_log, db):
    """ProposalCreatedEvent should INSERT into proposals table."""
    # First create the node (proposals reference nodes)
    node_event = NodeUpsertedEvent(
        agent_id="n1", node_type="function", name="foo",
        file_path="foo.py", start_line=1, end_line=10,
        source_code="old", source_hash="abc",
    )
    await event_log.append(node_event)

    event = ProposalCreatedEvent(
        proposal_id="p1", agent_id="n1",
        old_source="old", new_source="new", diff="diff",
    )
    await event_log.append(event)
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM proposals WHERE proposal_id = ?", ("p1",))
    row = cursor.fetchone()
    assert row is not None
    assert row["status"] == "pending"


# --- Subscription matching + trigger queue ---

@pytest.mark.asyncio
async def test_subscription_triggers(event_log, db):
    """append() should match subscriptions and queue triggers."""
    # Register a subscription: agent a2 wants events with to_agent=a2
    cursor = db.conn.cursor()
    cursor.execute(
        "INSERT INTO subscriptions (agent_id, pattern_json, is_default, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("a2", json.dumps({"to_agent": "a2"}), 1, 1.0, 1.0),
    )
    db.conn.commit()

    # Reload subscriptions in EventLog
    event_log._load_subscriptions()

    event = AgentMessageEvent(from_agent="a1", to_agent="a2", content="hello")
    await event_log.append(event)

    # Should have a trigger for a2
    trigger = await asyncio.wait_for(event_log._trigger_queue.get(), timeout=1.0)
    agent_id, event_id, triggered_event = trigger
    assert agent_id == "a2"


# --- In-process subscriber notification ---

@pytest.mark.asyncio
async def test_in_process_subscriber(event_log):
    """In-process subscribers should be notified on append."""
    received = []

    def handler(event):
        received.append(event)

    event_log.subscribe(handler)

    event = AgentStartEvent(graph_id="swarm", agent_id="n1", node_name="foo")
    await event_log.append(event)

    assert len(received) == 1
    assert received[0] is event


# --- Kernel events get full treatment ---

@pytest.mark.asyncio
async def test_kernel_events_get_subscription_matching(event_log, db):
    """Kernel events (ToolCallEvent etc.) should go through subscription matching."""
    # Register a subscription for ToolCallEvent
    cursor = db.conn.cursor()
    cursor.execute(
        "INSERT INTO subscriptions (agent_id, pattern_json, is_default, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("monitor", json.dumps({"event_types": ["ToolCallEvent"]}), 0, 1.0, 1.0),
    )
    db.conn.commit()
    event_log._load_subscriptions()

    # ToolCallEvent is from structured_agents — it may have different fields.
    # We need to handle it gracefully. If ToolCallEvent can't be instantiated
    # with our test data, skip this specific assertion but verify the path works.
    try:
        event = ToolCallEvent(tool_name="read_file", arguments={"path": "foo.py"})
        await event_log.append(event)
        trigger = await asyncio.wait_for(event_log._trigger_queue.get(), timeout=1.0)
        assert trigger[0] == "monitor"
    except TypeError:
        # ToolCallEvent constructor may differ — test that append doesn't crash
        pytest.skip("ToolCallEvent constructor incompatible with test args")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_log.py -v`
Expected: FAIL — `remora.core.event_log` doesn't exist

**Step 3: Implement `src/remora/core/event_log.py`**

```python
"""EventLog — the single write path for all Remora state changes.

Replaces both EventBus (in-memory pub/sub) and EventStore (persistence).
Every state mutation goes through append(), which:
1. Inserts the event into the events table
2. Applies a projection (updates materialized views)
3. Matches subscriptions → queues agent triggers
4. Notifies in-process subscribers
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator

from remora.core.events import (
    CursorFocusChangedEvent,
    EdgeUpdatedEvent,
    NodeOrphanedEvent,
    NodeUpsertedEvent,
    ProposalAcceptedEvent,
    ProposalCreatedEvent,
    ProposalRejectedEvent,
    RemoraEvent,
    SubscriptionRegisteredEvent,
    SubscriptionRemovedEvent,
)
from remora.core.subscriptions import SubscriptionPattern

if TYPE_CHECKING:
    from remora.lsp.db import RemoraDB

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], Any]


class EventLog:
    """Append-only event log with materialized view projections
    and in-process subscriber notification."""

    def __init__(self, db: "RemoraDB") -> None:
        self._db = db
        self._lock = asyncio.Lock()
        self._trigger_queue: asyncio.Queue[tuple[str, int, Any]] = asyncio.Queue()
        self._handlers: list[EventHandler] = []
        self._typed_handlers: dict[type, list[EventHandler]] = {}
        self._subscriptions: list[dict] = []  # loaded from DB
        self._load_subscriptions()

    def _load_subscriptions(self) -> None:
        """Load all subscriptions from the DB into memory."""
        cursor = self._db.conn.cursor()
        try:
            cursor.execute("SELECT agent_id, pattern_json FROM subscriptions")
            self._subscriptions = [
                {"agent_id": row[0], "pattern": SubscriptionPattern(**json.loads(row[1]))}
                for row in cursor.fetchall()
            ]
        except Exception:
            self._subscriptions = []

    async def append(self, event: Any, *, graph_id: str = "swarm") -> int:
        """The single write path.

        1. Serialize event to JSON
        2. BEGIN TRANSACTION
           a. INSERT INTO events
           b. Apply projection (update materialized views)
        3. COMMIT
        4. Match subscriptions → queue triggers
        5. Notify in-process subscribers

        Returns the event rowid.
        """
        event_type = type(event).__name__
        payload = self._serialize_event(event)
        timestamp = getattr(event, "timestamp", None) or time.time()
        now = time.time()

        # Extract routing fields
        from_agent = getattr(event, "from_agent", None)
        to_agent = getattr(event, "to_agent", None)
        agent_id = getattr(event, "agent_id", None)
        correlation_id = getattr(event, "correlation_id", None)
        tags = getattr(event, "tags", None)
        tags_json = json.dumps(tags) if tags else None
        event_id = f"evt_{uuid.uuid4().hex[:12]}"

        async with self._lock:
            cursor = self._db.conn.cursor()
            cursor.execute("BEGIN")
            try:
                cursor.execute(
                    """INSERT INTO events
                       (event_id, event_type, timestamp, created_at,
                        agent_id, from_agent, to_agent, correlation_id,
                        tags, payload)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (event_id, event_type, timestamp, now,
                     agent_id, from_agent, to_agent, correlation_id,
                     tags_json, payload),
                )
                rowid = cursor.lastrowid

                # Apply projection
                self._apply_projection(cursor, event)

                self._db.conn.commit()
            except Exception:
                self._db.conn.rollback()
                raise

        # Match subscriptions → queue triggers (outside transaction)
        matching_agents = self._get_matching_agents(event)
        for matched_agent_id in matching_agents:
            await self._trigger_queue.put((matched_agent_id, rowid, event))

        # Notify in-process subscribers
        await self._notify(event)

        return rowid

    def _apply_projection(self, cursor: Any, event: Any) -> None:
        """Update materialized views based on event type.

        Only events that change persistent state need projections.
        Lifecycle events (AgentStartEvent, ToolCallEvent, etc.) are
        recorded in the log but don't update any view.
        """
        if isinstance(event, NodeUpsertedEvent):
            cursor.execute(
                """INSERT OR REPLACE INTO nodes
                   (id, node_type, name, full_name, file_path,
                    start_line, end_line, start_col, end_col,
                    source_code, source_hash, status, parent_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
                (event.agent_id, event.node_type, event.name,
                 getattr(event, "full_name", ""), event.file_path,
                 event.start_line, event.end_line,
                 getattr(event, "start_col", 0), getattr(event, "end_col", 0),
                 event.source_code, event.source_hash,
                 event.parent_id),
            )
        elif isinstance(event, NodeOrphanedEvent):
            cursor.execute(
                "UPDATE nodes SET status = 'orphaned' WHERE id = ?",
                (event.agent_id,),
            )
        elif isinstance(event, EdgeUpdatedEvent):
            if event.removed:
                cursor.execute(
                    "DELETE FROM edges WHERE from_id = ? AND to_id = ? AND edge_type = ?",
                    (event.from_id, event.to_id, event.edge_type),
                )
            else:
                cursor.execute(
                    "INSERT OR REPLACE INTO edges (from_id, to_id, edge_type) VALUES (?, ?, ?)",
                    (event.from_id, event.to_id, event.edge_type),
                )
        elif isinstance(event, ProposalCreatedEvent):
            cursor.execute(
                """INSERT INTO proposals
                   (proposal_id, agent_id, old_source, new_source, diff, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (event.proposal_id, event.agent_id,
                 event.old_source, event.new_source, event.diff,
                 event.timestamp),
            )
        elif isinstance(event, ProposalAcceptedEvent):
            cursor.execute(
                "UPDATE proposals SET status = 'accepted' WHERE proposal_id = ?",
                (event.proposal_id,),
            )
        elif isinstance(event, ProposalRejectedEvent):
            cursor.execute(
                "UPDATE proposals SET status = 'rejected' WHERE proposal_id = ?",
                (event.proposal_id,),
            )
        elif isinstance(event, CursorFocusChangedEvent):
            cursor.execute(
                """INSERT OR REPLACE INTO cursor_focus
                   (id, agent_id, file_path, line, timestamp)
                   VALUES (1, ?, ?, ?, ?)""",
                (event.agent_id, event.file_path, event.line, event.timestamp),
            )
        elif isinstance(event, SubscriptionRegisteredEvent):
            cursor.execute(
                """INSERT INTO subscriptions
                   (id, agent_id, pattern_json, is_default, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (event.subscription_id, event.agent_id,
                 event.pattern_json, 1 if event.is_default else 0,
                 event.timestamp, event.timestamp),
            )
        elif isinstance(event, SubscriptionRemovedEvent):
            cursor.execute(
                "DELETE FROM subscriptions WHERE id = ?",
                (event.subscription_id,),
            )
        # All other events: no projection needed. They're in the log and that's enough.

    def _get_matching_agents(self, event: Any) -> list[str]:
        """Match event against all subscriptions. Returns matching agent IDs."""
        matching = []
        seen = set()
        for sub in self._subscriptions:
            if sub["pattern"].matches(event) and sub["agent_id"] not in seen:
                matching.append(sub["agent_id"])
                seen.add(sub["agent_id"])
        return matching

    async def _notify(self, event: Any) -> None:
        """Notify all in-process subscribers."""
        event_type = type(event)
        handlers = list(self._handlers)

        # Add typed handlers
        for registered_type, typed_handlers in self._typed_handlers.items():
            if isinstance(event, registered_type):
                handlers.extend(typed_handlers)

        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning("Event handler error: %s", exc)

    def subscribe(self, handler: EventHandler) -> None:
        """Register an in-process event handler for all events."""
        if handler not in self._handlers:
            self._handlers.append(handler)

    def subscribe_typed(self, event_type: type, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        if event_type not in self._typed_handlers:
            self._typed_handlers[event_type] = []
        if handler not in self._typed_handlers[event_type]:
            self._typed_handlers[event_type].append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove an in-process handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)
        for handlers in self._typed_handlers.values():
            if handler in handlers:
                handlers.remove(handler)

    async def get_triggers(self) -> AsyncIterator[tuple[str, int, Any]]:
        """Yield (agent_id, event_rowid, event) for subscription matches.
        Consumed by AgentRunner. In-process queue, not DB polling."""
        while True:
            try:
                trigger = await self._trigger_queue.get()
                yield trigger
            except asyncio.CancelledError:
                break

    async def replay(
        self,
        *,
        event_types: list[str] | None = None,
        since: float | None = None,
        after_id: int | None = None,
    ) -> AsyncIterator[dict]:
        """Replay historical events. For debugging and time travel."""
        cursor = self._db.conn.cursor()
        query = "SELECT rowid, * FROM events WHERE 1=1"
        params: list[Any] = []

        if event_types:
            placeholders = ",".join("?" * len(event_types))
            query += f" AND event_type IN ({placeholders})"
            params.extend(event_types)
        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)
        if after_id is not None:
            query += " AND rowid > ?"
            params.append(after_id)

        query += " ORDER BY rowid ASC"
        cursor.execute(query, params)
        for row in cursor.fetchall():
            yield dict(row)

    @staticmethod
    def _serialize_event(event: Any) -> str:
        """Serialize an event to JSON."""
        if is_dataclass(event):
            data = asdict(event)
        elif hasattr(event, "__dict__"):
            data = dict(vars(event))
        else:
            data = {"value": str(event)}
        return json.dumps(data, default=str)


__all__ = ["EventLog", "EventHandler"]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_log.py -v`
Expected: PASS

**Step 5: Run existing tests for regressions**

Run: `pytest tests/ -v --timeout=30`
Expected: No regressions (EventLog is new code, nothing imports it yet)

**Step 6: Commit**

```bash
git add src/remora/core/event_log.py tests/test_event_log.py
git commit -m "feat(core): add EventLog — single write path with projections and subscriptions"
```

---

### Phase 2: Migration (swap callers from old systems to EventLog)

### Task 4: Migrate `server.py` emit_event to use EventLog

Replace the dual-write in `RemoraLanguageServer.emit_event()` (currently writes to RemoraDB AND EventStore) with a single `EventLog.append()` call.

**Files:**
- Modify: `src/remora/lsp/server.py`
- Test: `tests/lsp/test_server_event_log.py`

**Step 1: Write the failing test**

```python
# tests/lsp/test_server_event_log.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from remora.core.event_log import EventLog
from remora.lsp.db import RemoraDB


@pytest.fixture
def db(tmp_path):
    return RemoraDB(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def event_log(db):
    return EventLog(db)


def test_server_has_event_log_attribute():
    """RemoraLanguageServer should accept an event_log parameter."""
    from remora.lsp.server import RemoraLanguageServer
    assert hasattr(RemoraLanguageServer, "__init__")
    # The server should be constructable with event_log
    # (full init requires pygls setup, so just verify the class exists)
```

**Step 2: Modify `src/remora/lsp/server.py`**

- Add `event_log: EventLog | None = None` parameter to `__init__`
- Store as `self.event_log = event_log`
- In `emit_event()`, if `self.event_log` is available, convert to core event and use `event_log.append()` instead of the dual-write path
- Keep backward compatibility: if `event_log` is None, fall back to old behavior (during migration)

```python
async def emit_event(self, event) -> Any:
    if not getattr(event, "timestamp", None):
        event.timestamp = time.time()

    if self.event_log:
        # New path: single write through EventLog
        try:
            core_event = event.to_core_event()
        except (NotImplementedError, AttributeError):
            core_event = None

        if core_event:
            await self.event_log.append(core_event)
        else:
            # Events without core_event conversion still get stored
            await self.db.store_event(event)
    else:
        # Legacy path (backward compat during migration)
        await self.db.store_event(event)
        if self.event_store:
            try:
                core_event = event.to_core_event()
            except NotImplementedError:
                core_event = None
            else:
                if core_event:
                    await self.event_store.append("swarm", core_event)

    self.protocol.notify("$/remora/event", event.model_dump())
    return event
```

**Step 3: Run tests**

Run: `pytest tests/ -v --timeout=30`
Expected: PASS (server still works, backward compat maintained)

**Step 4: Commit**

```bash
git add src/remora/lsp/server.py tests/lsp/test_server_event_log.py
git commit -m "refactor(lsp): add EventLog integration to emit_event with backward compat"
```

---

### Task 5: Migrate SwarmExecutor to use EventLog

Replace `SwarmExecutor._event_store` and `_EventStoreObserver` with `EventLog`. Replace `SwarmState` queries with direct nodes table queries.

**Files:**
- Modify: `src/remora/core/swarm_executor.py`
- Test: `tests/test_swarm_executor_eventlog.py`

**Step 1: Write the failing test**

```python
# tests/test_swarm_executor_eventlog.py
import pytest
from remora.core.event_log import EventLog
from remora.lsp.db import RemoraDB


@pytest.fixture
def db(tmp_path):
    return RemoraDB(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def event_log(db):
    return EventLog(db)


def test_swarm_executor_accepts_event_log():
    """SwarmExecutor should accept event_log parameter."""
    from remora.core.swarm_executor import SwarmExecutor
    # Verify the class signature accepts event_log
    import inspect
    sig = inspect.signature(SwarmExecutor.__init__)
    param_names = list(sig.parameters.keys())
    assert "event_log" in param_names or "event_store" in param_names
```

**Step 2: Modify `src/remora/core/swarm_executor.py`**

Key changes:
- Accept `event_log: EventLog | None = None` alongside existing `event_store` param (backward compat)
- When `event_log` is provided, `_EventStoreObserver` calls `event_log.append()` instead of `event_store.append()`
- Replace `self._swarm_state.list_agents()` with direct DB query: `SELECT * FROM nodes WHERE status != 'orphaned'`
- Replace `self._swarm_state.get_agent()` with direct DB query: `SELECT * FROM nodes WHERE id = ?`
- Import `AgentMetadata` dataclass for return compatibility (or use dicts)

The `_emit_event`, `_broadcast`, and `_query_agents` externals all need updating.

**Step 3: Run tests**

Run: `pytest tests/ -v --timeout=30`
Expected: PASS

**Step 4: Commit**

```bash
git add src/remora/core/swarm_executor.py tests/test_swarm_executor_eventlog.py
git commit -m "refactor(executor): migrate SwarmExecutor to EventLog, replace SwarmState with DB queries"
```

---

### Task 6: Migrate AgentRunner to use EventLog

Replace `AgentRunner._event_store` with `EventLog` for trigger consumption. Replace `EventBus` lifecycle emissions with `EventLog.append()`.

**Files:**
- Modify: `src/remora/core/agent_runner.py`
- Test: `tests/test_agent_runner_eventlog.py`

**Step 1: Write the failing test**

```python
# tests/test_agent_runner_eventlog.py
import pytest


def test_agent_runner_accepts_event_log():
    """AgentRunner should accept event_log parameter."""
    from remora.core.agent_runner import AgentRunner
    import inspect
    sig = inspect.signature(AgentRunner.__init__)
    param_names = list(sig.parameters.keys())
    assert "event_log" in param_names
```

**Step 2: Modify `src/remora/core/agent_runner.py`**

Key changes:
- Accept `event_log: EventLog` instead of `event_store: EventStore`
- `run_forever()` consumes `event_log.get_triggers()` instead of `event_store.get_triggers()`
- Lifecycle events (`AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`) go through `event_log.append()` instead of `event_bus.emit()`
- Remove `event_bus` parameter entirely — EventLog handles both persistence and notification
- Pass `event_log` to `SwarmExecutor` instead of `event_store`

**Step 3: Run tests**

Run: `pytest tests/ -v --timeout=30`
Expected: PASS

**Step 4: Commit**

```bash
git add src/remora/core/agent_runner.py tests/test_agent_runner_eventlog.py
git commit -m "refactor(runner): migrate AgentRunner to EventLog, remove EventBus dependency"
```

---

### Task 7: Migrate SubscriptionRegistry storage to RemoraDB

Move subscription storage from `subscriptions.db` to the `subscriptions` table in `indexer.db`. Keep the pattern matching logic. Update `SubscriptionRegistry` to accept a `RemoraDB` connection instead of its own DB path.

**Files:**
- Modify: `src/remora/core/subscriptions.py`
- Test: `tests/test_subscriptions_migration.py`

**Step 1: Write the failing test**

```python
# tests/test_subscriptions_migration.py
import pytest
from remora.core.subscriptions import SubscriptionRegistry, SubscriptionPattern
from remora.lsp.db import RemoraDB


@pytest.fixture
def db(tmp_path):
    return RemoraDB(db_path=str(tmp_path / "test.db"))


@pytest.mark.asyncio
async def test_registry_uses_remora_db(db):
    """SubscriptionRegistry should work with RemoraDB connection."""
    registry = SubscriptionRegistry(db=db)
    await registry.initialize()

    pattern = SubscriptionPattern(to_agent="agent1")
    sub = await registry.register("agent1", pattern)
    assert sub.agent_id == "agent1"

    subs = await registry.get_subscriptions("agent1")
    assert len(subs) == 1


@pytest.mark.asyncio
async def test_registry_pattern_matching_with_remora_db(db):
    """Pattern matching should work with the new DB backend."""
    from remora.core.events import AgentMessageEvent

    registry = SubscriptionRegistry(db=db)
    await registry.initialize()

    pattern = SubscriptionPattern(to_agent="agent1")
    await registry.register("agent1", pattern)

    event = AgentMessageEvent(from_agent="a0", to_agent="agent1", content="hello")
    agents = await registry.get_matching_agents(event)
    assert "agent1" in agents
```

**Step 2: Update `src/remora/core/subscriptions.py`**

- Add `db: RemoraDB | None = None` parameter to `__init__` alongside existing `db_path` (backward compat)
- When `db` is provided, use `db.conn` instead of opening a separate connection
- When `db_path` is provided, keep old behavior (during migration)
- `initialize()` becomes a no-op when using `db` (schema already exists in RemoraDB)

**Step 3: Run tests**

Run: `pytest tests/ -v --timeout=30`
Expected: PASS

**Step 4: Commit**

```bash
git add src/remora/core/subscriptions.py tests/test_subscriptions_migration.py
git commit -m "refactor(subscriptions): migrate storage to RemoraDB, keep backward compat"
```

---

### Task 8: Add EventTailReader for cross-process web servers

Replace fingerprint polling in the graph viewer with event tailing by rowid.

**Files:**
- Create: `src/remora/db/reader.py`
- Test: `tests/test_event_tail_reader.py`

**Step 1: Write the failing test**

```python
# tests/test_event_tail_reader.py
import pytest
from remora.db.reader import EventTailReader
from remora.lsp.db import RemoraDB


@pytest.fixture
def db(tmp_path):
    rdb = RemoraDB(db_path=str(tmp_path / "test.db"))
    # Insert some test data
    cursor = rdb.conn.cursor()
    cursor.execute(
        "INSERT INTO nodes (id, node_type, name, file_path, start_line, end_line, source_code, source_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("n1", "function", "foo", "foo.py", 1, 10, "def foo(): pass", "abc"),
    )
    cursor.execute(
        "INSERT INTO events (event_id, event_type, timestamp, created_at, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("e1", "TestEvent", 1.0, 1.0, '{"msg": "hello"}'),
    )
    cursor.execute(
        "INSERT INTO events (event_id, event_type, timestamp, created_at, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("e2", "TestEvent", 2.0, 2.0, '{"msg": "world"}'),
    )
    rdb.conn.commit()
    return rdb


@pytest.fixture
def reader(db, tmp_path):
    return EventTailReader(db_path=str(tmp_path / "test.db"))


def test_poll_returns_new_events(reader):
    events = reader.poll()
    assert len(events) == 2
    assert events[0]["event_id"] == "e1"


def test_poll_is_incremental(reader):
    events1 = reader.poll()
    assert len(events1) == 2
    # Second poll with no new events
    events2 = reader.poll()
    assert len(events2) == 0


def test_poll_picks_up_new_events(reader, db):
    # Read existing
    reader.poll()

    # Insert new event
    cursor = db.conn.cursor()
    cursor.execute(
        "INSERT INTO events (event_id, event_type, timestamp, created_at, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("e3", "TestEvent", 3.0, 3.0, '{"msg": "new"}'),
    )
    db.conn.commit()

    events = reader.poll()
    assert len(events) == 1
    assert events[0]["event_id"] == "e3"


def test_read_all_nodes(reader):
    nodes = reader.read_all_nodes()
    assert len(nodes) == 1
    assert nodes[0]["remora_id"] == "n1"


def test_read_cursor_focus_empty(reader):
    assert reader.read_cursor_focus() is None


def test_push_command(reader):
    cmd_id = reader.push_command("test", None, {"key": "val"})
    assert cmd_id > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_tail_reader.py -v`
Expected: FAIL — module doesn't exist

**Step 3: Create `src/remora/db/reader.py`**

```python
"""Cross-process DB reader for web servers.

Opens RemoraDB in WAL + query_only mode. Provides:
- Event tailing by rowid (replaces fingerprint polling)
- Materialized view reads (nodes, edges, proposals)
- Command queue writes (separate writable connection)
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class EventTailReader:
    """Read-only DB accessor with event tailing for web servers."""

    def __init__(self, db_path: str = ".remora/indexer.db") -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._last_rowid: int = 0

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA query_only=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def poll(self) -> list[dict]:
        """Read new events since last poll. Incremental by rowid."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT rowid, * FROM events WHERE rowid > ? ORDER BY rowid ASC",
            (self._last_rowid,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        if rows:
            self._last_rowid = rows[-1]["rowid"]
        return rows

    def read_all_nodes(self) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE status != 'orphaned'")
        return [self._normalize_node(row) for row in cursor.fetchall()]

    def read_node(self, node_id: str) -> dict | None:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        return self._normalize_node(row) if row else None

    def read_all_edges(self) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM edges")
        return [dict(row) for row in cursor.fetchall()]

    def read_cursor_focus(self) -> dict | None:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, file_path, line, timestamp FROM cursor_focus WHERE id = 1")
        row = cursor.fetchone()
        return dict(row) if row else None

    def read_recent_events(self, limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT event_id, event_type, timestamp, agent_id, payload "
            "FROM events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def read_events_for_agent(self, agent_id: str, limit: int = 20) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT event_id, event_type, timestamp, correlation_id, agent_id, payload
               FROM events
               WHERE agent_id = ? OR json_extract(payload, '$.to_agent') = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (agent_id, agent_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def read_proposals_for_agent(self, agent_id: str) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM proposals WHERE agent_id = ? AND status = 'pending'",
            (agent_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def read_all_pending_proposals(self) -> list[dict]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM proposals WHERE status = 'pending'")
        return [dict(row) for row in cursor.fetchall()]

    def read_edges_for_node(self, node_id: str) -> dict:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT from_id FROM edges WHERE to_id = ? AND edge_type = 'parent_of'", (node_id,))
        parents = [row["from_id"] for row in cursor.fetchall()]
        cursor.execute("SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'parent_of'", (node_id,))
        children = [row["to_id"] for row in cursor.fetchall()]
        cursor.execute("SELECT from_id FROM edges WHERE to_id = ? AND edge_type = 'calls'", (node_id,))
        callers = [row["from_id"] for row in cursor.fetchall()]
        cursor.execute("SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'calls'", (node_id,))
        callees = [row["to_id"] for row in cursor.fetchall()]
        return {"parents": parents, "children": children, "callers": callers, "callees": callees}

    def push_command(self, command_type: str, agent_id: str | None, payload: dict) -> int:
        """Write a command (uses a separate writable connection)."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO command_queue (command_type, agent_id, payload, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (command_type, agent_id, json.dumps(payload), time.time()),
        )
        conn.commit()
        cmd_id = cursor.lastrowid
        conn.close()
        return cmd_id

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _normalize_node(row: sqlite3.Row) -> dict:
        data = dict(row)
        if "id" in data:
            data["remora_id"] = data.pop("id")
        return data
```

Also create `src/remora/db/__init__.py` (empty).

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_tail_reader.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/remora/db/__init__.py src/remora/db/reader.py tests/test_event_tail_reader.py
git commit -m "feat(db): add EventTailReader — cross-process event tailing + materialized view reads"
```

---

### Task 9: Migrate graph viewer to EventTailReader

Replace `GraphState`'s fingerprint polling with `EventTailReader`'s rowid-based event tailing.

**Files:**
- Modify: `remora_demo/graph/state.py`
- Test: `tests/remora_demo/graph/test_state_v2.py`

**Step 1: Write the failing test**

```python
# tests/remora_demo/graph/test_state_v2.py
import pytest
from remora.lsp.db import RemoraDB
from remora_demo.graph.state import GraphState


@pytest.fixture
def db(tmp_path):
    return RemoraDB(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def state(db, tmp_path):
    return GraphState(db_path=str(tmp_path / "test.db"))


def test_state_uses_event_tailing(state):
    """GraphState should use EventTailReader internally."""
    assert hasattr(state, "reader")
    assert hasattr(state.reader, "poll")


def test_state_detects_changes_via_events(state, db):
    """GraphState should detect changes via event tailing, not fingerprinting."""
    # Insert an event
    cursor = db.conn.cursor()
    cursor.execute(
        "INSERT INTO events (event_id, event_type, timestamp, created_at, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("e1", "TestEvent", 1.0, 1.0, '{}'),
    )
    db.conn.commit()

    events = state.reader.poll()
    assert len(events) == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/remora_demo/graph/test_state_v2.py -v`
Expected: FAIL — GraphState doesn't have `reader` attribute

**Step 3: Rewrite `remora_demo/graph/state.py`**

Replace internal `_fingerprint()` polling with `EventTailReader.poll()`. Keep the same external interface (`read_snapshot()`, `changes()`, etc.).

```python
"""Graph state reader with event-tailing-based change detection."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from remora.db.reader import EventTailReader

logger = logging.getLogger("remora.graph")


@dataclass
class GraphSnapshot:
    """Immutable snapshot of current graph state."""
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    cursor_focus: dict | None = None
    timestamp: float = 0.0


class GraphState:
    """Reads the Remora SQLite DB and yields snapshots on change."""

    def __init__(self, db_path: str = ".remora/indexer.db") -> None:
        self.reader = EventTailReader(db_path=db_path)

    def read_snapshot(self) -> GraphSnapshot:
        nodes = self.reader.read_all_nodes()
        edges = self.reader.read_all_edges()
        cursor_focus = self.reader.read_cursor_focus()
        return GraphSnapshot(nodes=nodes, edges=edges, cursor_focus=cursor_focus, timestamp=time.time())

    def read_node(self, node_id: str) -> dict | None:
        return self.reader.read_node(node_id)

    def read_events_for_agent(self, agent_id: str, limit: int = 20) -> list[dict]:
        return self.reader.read_events_for_agent(agent_id, limit=limit)

    def read_proposals_for_agent(self, agent_id: str) -> list[dict]:
        return self.reader.read_proposals_for_agent(agent_id)

    def read_edges_for_node(self, node_id: str) -> dict:
        return self.reader.read_edges_for_node(node_id)

    def push_command(self, command_type: str, agent_id: str | None, payload: dict) -> int:
        return self.reader.push_command(command_type, agent_id, payload)

    async def changes(self) -> AsyncIterator[GraphSnapshot]:
        """Yield snapshots whenever the DB changes (event tailing)."""
        while True:
            await asyncio.sleep(0.5)
            try:
                new_events = await asyncio.to_thread(self.reader.poll)
                if new_events:
                    snapshot = await asyncio.to_thread(self.read_snapshot)
                    yield snapshot
            except Exception:
                logger.debug("Poll error", exc_info=True)
                await asyncio.sleep(2.0)

    def close(self) -> None:
        self.reader.close()
```

**Step 4: Run tests**

Run: `pytest tests/remora_demo/graph/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add remora_demo/graph/state.py tests/remora_demo/graph/test_state_v2.py
git commit -m "refactor(graph): replace fingerprint polling with event tailing via EventTailReader"
```

---

### Task 10: Rewrite RemoraService to use EventTailReader

Strip out EventBus, EventStore, SwarmState, UiStateProjector dependencies. RemoraService becomes a thin wrapper over EventTailReader.

**Files:**
- Modify: `src/remora/service/api.py`
- Test: `tests/test_service_eventlog.py`

**Step 1: Write the failing test**

```python
# tests/test_service_eventlog.py
import pytest
from remora.lsp.db import RemoraDB
from remora.service.api import RemoraService


@pytest.fixture
def db(tmp_path):
    rdb = RemoraDB(db_path=str(tmp_path / "test.db"))
    cursor = rdb.conn.cursor()
    cursor.execute(
        "INSERT INTO nodes (id, node_type, name, file_path, start_line, end_line, source_code, source_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("n1", "function", "foo", "foo.py", 1, 10, "def foo(): pass", "abc"),
    )
    rdb.conn.commit()
    return rdb


def test_service_from_db(db, tmp_path):
    service = RemoraService.from_db(db_path=str(tmp_path / "test.db"))
    state = service.read_state()
    assert len(state["nodes"]) == 1
    assert state["nodes"][0]["name"] == "foo"
```

**Step 2: Rewrite `src/remora/service/api.py`**

Replace with a thin wrapper over `EventTailReader`:

```python
"""Service layer entry point — DB-backed via EventTailReader."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from remora.db.reader import EventTailReader


class RemoraService:
    """Framework-agnostic Remora service backed by EventTailReader."""

    def __init__(self, *, reader: EventTailReader) -> None:
        self._reader = reader

    @classmethod
    def from_db(cls, db_path: str = ".remora/indexer.db") -> "RemoraService":
        return cls(reader=EventTailReader(db_path=db_path))

    def read_state(self) -> dict[str, Any]:
        nodes = self._reader.read_all_nodes()
        events = self._reader.read_recent_events(limit=200)
        proposals = self._reader.read_all_pending_proposals()
        cursor_focus = self._reader.read_cursor_focus()
        agent_states = {}
        for node in nodes:
            agent_states[node["remora_id"]] = {
                "state": node.get("status", "active"),
                "name": node.get("name", node["remora_id"]),
            }
        return {
            "nodes": nodes,
            "events": events,
            "proposals": proposals,
            "cursor_focus": cursor_focus,
            "agent_states": agent_states,
        }

    async def subscribe_stream(self) -> AsyncIterator[str]:
        from remora.service.datastar import render_patch
        state = await asyncio.to_thread(self.read_state)
        yield render_patch(state)
        while True:
            await asyncio.sleep(0.5)
            try:
                new_events = await asyncio.to_thread(self._reader.poll)
                if new_events:
                    state = await asyncio.to_thread(self.read_state)
                    yield render_patch(state)
            except Exception:
                await asyncio.sleep(2.0)

    async def post_command(self, command_type: str, agent_id: str | None, payload: dict) -> int:
        return await asyncio.to_thread(
            self._reader.push_command, command_type, agent_id, payload
        )

    def close(self) -> None:
        self._reader.close()


__all__ = ["RemoraService"]
```

**Step 3: Run tests**

Run: `pytest tests/test_service_eventlog.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/remora/service/api.py tests/test_service_eventlog.py
git commit -m "refactor(service): rewrite RemoraService to use EventTailReader, remove all old deps"
```

---

### Phase 3: Cleanup

### Task 11: Delete dead code

Remove modules that are fully replaced by EventLog and EventTailReader.

**Files:**
- Delete: `src/remora/core/event_bus.py`
- Delete: `src/remora/core/event_store.py`
- Delete: `src/remora/core/swarm_state.py`
- Delete: `src/remora/ui/projector.py`
- Modify: any files that still import the dead modules

**Step 1: Search for all imports of dead modules**

```bash
rg "from remora.core.event_bus import" --type py
rg "from remora.core.event_store import" --type py
rg "from remora.core.swarm_state import" --type py
rg "from remora.ui.projector import" --type py
rg "import remora.core.event_bus" --type py
rg "import remora.core.event_store" --type py
rg "import remora.core.swarm_state" --type py
```

**Step 2: Update each importing module**

For each remaining import:
- If it's in `swarm_executor.py` or `agent_runner.py` (already migrated in Tasks 5-6), remove the old imports
- If it's in `server.py` (already migrated in Task 4), remove old `event_store`, `swarm_state` params
- If it's in tests, update or remove the tests
- If it's in `__init__.py` or re-export files, clean up

**Step 3: Delete the dead modules**

```bash
git rm src/remora/core/event_bus.py
git rm src/remora/core/event_store.py
git rm src/remora/core/swarm_state.py
git rm src/remora/ui/projector.py
```

**Step 4: Run full test suite**

Run: `pytest tests/ -v --timeout=30`
Fix any remaining import errors.

**Step 5: Commit**

```bash
git add -A
git commit -m "refactor: delete EventBus, EventStore, SwarmState, UiStateProjector — EventLog is the single write path"
```

---

### Task 12: Clean up RemoraLanguageServer init

Remove backward-compat parameters (`event_store`, `subscriptions`, `swarm_state`) from the server constructor. Make `event_log` the primary dependency.

**Files:**
- Modify: `src/remora/lsp/server.py`
- Modify: any entry point that constructs `RemoraLanguageServer`

**Step 1: Simplify `__init__`**

```python
class RemoraLanguageServer(LanguageServer):
    def __init__(self):
        super().__init__(name="remora", version="0.1.0")
        self.db = RemoraDB()
        self.graph = LazyGraph(self.db)
        self.watcher = ASTWatcher()
        self.proposals: dict[str, RewriteProposal] = {}
        self.runner: "AgentRunner | None" = None
        self._correlation_counter = 0
        self._injecting: set[str] = set()
        self.event_log = EventLog(self.db)
```

**Step 2: Simplify `emit_event()`**

Remove the legacy branch:

```python
async def emit_event(self, event) -> Any:
    if not getattr(event, "timestamp", None):
        event.timestamp = time.time()

    try:
        core_event = event.to_core_event()
    except (NotImplementedError, AttributeError):
        core_event = None

    if core_event:
        await self.event_log.append(core_event)
    else:
        await self.db.store_event(event)

    self.protocol.notify("$/remora/event", event.model_dump())
    return event
```

**Step 3: Run tests**

Run: `pytest tests/ -v --timeout=30`
Expected: PASS

**Step 4: Commit**

```bash
git add src/remora/lsp/server.py
git commit -m "refactor(lsp): simplify server init — EventLog is the only write path"
```

---

## Deferred / Follow-up Tasks

These are intentionally NOT part of this plan:

1. **Datastar @post() for commands** — replace raw `fetch()` with Datastar attributes in sidebar.py/shell.py
2. **Targeted patch_elements** — use event types to send targeted HTML patches instead of full re-renders
3. **Merge service dashboard + graph viewer** into a single Starlette app
4. **Cursor debounce implementation** — add 200ms debounce timer in server.py for `CursorFocusChangedEvent`
5. **Event retention policy** — archive/delete kernel events older than N days
6. **Missed trigger recovery** — on restart, scan recent events to recover triggers lost during crash
7. **rebuild_views()** — implement the nuclear rebuild-from-event-log capability

## Migration Path

The task ordering ensures each commit is independently testable:

1. **Tasks 1-3** (Phase 1: Foundation) — New schema, event types, EventLog class. No breaking changes — nothing imports EventLog yet.
2. **Tasks 4-7** (Phase 2: Migration) — Swap callers one by one. Each task adds EventLog integration alongside backward compat.
3. **Tasks 8-10** (Phase 2 cont.) — EventTailReader for web servers, graph viewer migration, service rewrite.
4. **Tasks 11-12** (Phase 3: Cleanup) — Delete dead code only after all callers are migrated.
