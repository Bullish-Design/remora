# Event Architecture Alignment

> Reactive agent-to-agent communication is the whole point of Remora.
> This document defines the all-event architecture that makes it the
> central organizing principle rather than an afterthought.

**Date:** 2026-03-01
**Status:** Design — awaiting implementation plan
**Supersedes:** The `change_counter` polling approach in `2026-03-01-architectural-unification.md`

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Current State Analysis](#current-state-analysis)
3. [Design Principles](#design-principles)
4. [Target Architecture](#target-architecture)
5. [EventLog — The Single Write Path](#eventlog--the-single-write-path)
6. [Materialized Views](#materialized-views)
7. [Subscription Routing](#subscription-routing)
8. [Cascade Safety](#cascade-safety)
9. [Cross-Process Readers](#cross-process-readers)
10. [Dual Event Model Unification](#dual-event-model-unification)
11. [Database Consolidation](#database-consolidation)
12. [Migration Map](#migration-map)
13. [Trade-offs and Mitigations](#trade-offs-and-mitigations)
14. [Open Questions](#open-questions)

---

## Problem Statement

Remora's architecture has the right idea — code nodes are agents, events
route between them, subscriptions determine who reacts to what — but the
implementation is split across four databases, two event systems, and
three notification mechanisms that don't compose.

The result: reactive agent-to-agent communication works, but through an
accidental Rube Goldberg machine where a single `emit_event` call
dual-writes to `RemoraDB.events` and `EventStore.events`, the EventBus
broadcasts to in-memory subscribers, the SubscriptionRegistry does
pattern matching to find triggered agents, and the trigger queue feeds
the AgentRunner. Meanwhile, web UIs poll a separate fingerprint of DB
state because they can't tap into any of these notification paths.

This document proposes collapsing all of that into one thing: the
**EventLog**. Every state change is an event. Every event is persisted.
Every persistence notifies. One write path, one notification path, one
source of truth.

---

## Current State Analysis

### The Four Databases

| Database | Location | Owner | Purpose |
|---|---|---|---|
| RemoraDB | `.remora/indexer.db` | LSP server | nodes, edges, events, proposals, cursor_focus, command_queue, activation_chain |
| EventStore | `.remora/events/events.db` | Service layer | Append-only event log with routing fields (from_agent, to_agent, correlation_id, tags) |
| SwarmState | `.remora/swarm_state.db` | Service layer | Agent metadata registry (agent_id, node_type, name, file_path, parent_id, status) |
| SubscriptionRegistry | `.remora/subscriptions.db` | Service layer | Pattern-based event subscriptions per agent |

### The Two Event Systems

**System 1: LSP Pydantic events** (`src/remora/lsp/models.py`)

Pydantic BaseModel subclasses: `AgentEvent`, `HumanChatEvent`,
`AgentMessageEvent`, `RewriteProposalEvent`, `RewriteAppliedEvent`,
`RewriteRejectedEvent`, `AgentErrorEvent`. Each has a `to_core_event()`
method that converts to...

**System 2: Core frozen dataclasses** (`src/remora/core/events.py`)

Frozen dataclass events: `AgentStartEvent`, `AgentCompleteEvent`,
`AgentErrorEvent`, `HumanInputRequestEvent`, `HumanInputResponseEvent`,
`AgentMessageEvent`, `FileSavedEvent`, `ContentChangedEvent`,
`ManualTriggerEvent`. Plus re-exports from structured-agents:
`KernelStartEvent`, `KernelEndEvent`, `ToolCallEvent`,
`ToolResultEvent`, `ModelRequestEvent`, `ModelResponseEvent`,
`TurnCompleteEvent`.

The LSP server's `emit_event()` (`server.py:55-70`) stores the Pydantic
event in RemoraDB, converts it to a core event via `to_core_event()`,
and appends that to EventStore. This is a lossy conversion — the
Pydantic model has fields like `to_agent` and `message` that survive
only if the `to_core_event()` implementation maps them correctly.

### The Three Notification Paths

1. **EventBus** (`event_bus.py`) — In-memory pub/sub. Type-based
   subscriptions, `stream()` for SSE, `wait_for()` for blocking waits.
   Used by: `service/api.py` (SSE stream), `agent_runner.py` (lifecycle
   event emission — `AgentStartEvent`, `AgentCompleteEvent`,
   `AgentErrorEvent`).

2. **EventStore trigger queue** (`event_store.py:162-176`) — After
   appending an event, if SubscriptionRegistry is configured, calls
   `get_matching_agents(event)` and puts `(agent_id, event_id, event)`
   tuples into an `asyncio.Queue`. AgentRunner consumes this via
   `get_triggers()`. This is the *actual* reactive agent triggering
   mechanism.

3. **DB fingerprint polling** (`graph/state.py:149-172`) — The graph
   viewer computes a string fingerprint from `count(*)`, `max(rowid)`,
   and cursor_focus timestamp, then compares to the previous fingerprint
   every 500ms. No events, no notifications — pure state diffing.

### What Actually Triggers Agents

Following the full path of an agent-to-agent message:

```
1. Agent A calls emit_event() in SwarmExecutor._run_kernel
   → SwarmExecutor._emit_event (line 101-102)
   → EventStore.append("swarm", event_obj)

2. EventStore.append():
   a. INSERT INTO events (its own events.db)
   b. SubscriptionRegistry.get_matching_agents(event)
      → Loads ALL subscriptions from subscriptions.db
      → Tests each SubscriptionPattern.matches(event)
      → Returns list of agent_ids
   c. For each matching agent: trigger_queue.put((agent_id, event_id, event))
   d. EventBus.emit(event) — for UI updates only

3. AgentRunner.run_forever():
   → async for agent_id, event_id, event in event_store.get_triggers():
   → Checks cooldown (trigger_cooldown_ms = 1000)
   → Checks depth limit (max_trigger_depth = 5)
   → Creates task: _process_trigger → _execute_turn → SwarmExecutor.run_agent

4. SwarmExecutor.run_agent():
   → Builds prompt including trigger event context
   → Runs LLM kernel with tools
   → Agent can emit more events → cycle back to step 1
```

**Key observation:** The EventBus is NOT in this path. Agent triggering
goes through `EventStore.append() → trigger_queue → AgentRunner`. The
EventBus only carries lifecycle notifications (start/complete/error) for
UI display. It's a notification sidecar, not a control plane.

### What the SwarmExecutor Gives Agents

Each agent turn receives these event-related capabilities as externals
(`swarm_executor.py:167-171`):

- `emit_event(event_type, event_obj)` — Appends to EventStore
- `register_subscription(agent_id, pattern)` — Adds a subscription
- `unsubscribe_subscription(subscription_id)` — Removes a subscription
- `broadcast(to_pattern, content)` — Sends AgentMessageEvent to multiple agents
  (children, siblings, or file-based targeting)
- `query_agents(filter_type)` — Lists agents from SwarmState

### Default Subscriptions

When agents are registered, `SubscriptionRegistry.register_defaults()`
(`subscriptions.py:164-181`) creates two subscriptions per agent:

1. **Direct message**: `SubscriptionPattern(to_agent=agent_id)` —
   matches any event with `to_agent` field equal to this agent
2. **Source file change**: `SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob=file_path)` —
   matches when the agent's source file is modified

---

## Design Principles

1. **Events are the source of truth.** The `events` table is an
   append-only log. Everything else — nodes, edges, proposals, agent
   status — is derived from events. If it's not in the event log, it
   didn't happen.

2. **One write path.** `EventLog.append()` is the only way to change
   state. No direct SQL mutations of materialized views outside of
   projections.

3. **Instant in-process, eventual cross-process.** Same-process
   subscribers (AgentRunner, LSP handlers) get synchronous notification
   on append. Cross-process readers (web servers) tail the event log by
   rowid with configurable polling intervals.

4. **Subscriptions are routing.** The SubscriptionRegistry pattern
   matcher is the routing table for the entire system. Event → pattern
   match → agent trigger. This is already the case; we're just removing
   the indirection layers around it.

5. **Materialized views for read performance.** The `nodes`, `edges`,
   `proposals` tables are projections updated transactionally inside
   `append()`. Queries hit these tables, not the event log. This avoids
   read amplification while preserving the event log as source of truth.

6. **Single database.** All four current databases consolidate into
   `indexer.db`. One WAL journal, one set of locks, one backup target.

---

## Target Architecture

```
                    REMORA — All-Event Architecture
 ═══════════════════════════════════════════════════════════════

                     ┌──────────────────┐
                     │    Human User    │
                     └──┬───────────┬───┘
                        │           │
               edits code│           │ opens browser
                        │           │
          ┌─────────────▼──┐   ┌────▼───────────────────────┐
          │    Neovim       │   │        Browser(s)           │
          │                 │   │                             │
          │  CodeLens       │   │  Dashboard    Graph Viewer  │
          │  Hover          │   │  (Datastar)   (Datastar+d3) │
          │  Diagnostics    │   │                             │
          │  Actions        │   │  HTML morph   HTML+signals  │
          └────────┬────────┘   └────────┬──────────┬────────┘
                   │                     │          │
          LSP      │             SSE     │   SSE    │
          protocol │         patch_      │  patch_  │
          (jsonrpc)│         elements    │  elements│
                   │                     │          │
 ═══════════ SERVER PROCESSES ═══════════════════════════════

  ┌────────────────┴────────────────────────────────────────┐
  │                                                          │
  │  ┌───────────────────────┐   ┌────────────────────────┐  │
  │  │  LSP Server (pygls)   │   │ Web Server (Starlette) │  │
  │  │                       │   │                        │  │
  │  │  EventLog ◄───────────┼───┼── EventLog (reader)    │  │
  │  │    │                  │   │     │                   │  │
  │  │    ├── append()       │   │     ├── tail()          │  │
  │  │    │   writes event   │   │     │   SELECT rowid>?  │  │
  │  │    │   + projection   │   │     │                   │  │
  │  │    │   + notify       │   │     ├── read views      │  │
  │  │    │                  │   │     │   (nodes, edges,   │  │
  │  │    ├── on_event()     │   │     │    proposals)     │  │
  │  │    │   in-process     │   │     │                   │  │
  │  │    │   subscribers    │   │  POST /command           │  │
  │  │    │                  │   │   → INSERT command_queue │  │
  │  │    ▼                  │   │                        │  │
  │  │  AgentRunner          │   └────────────┬───────────┘  │
  │  │    │                  │                │              │
  │  │    ├── get_triggers() │                │              │
  │  │    │   (in-process    │                │              │
  │  │    │    queue, not    │                │              │
  │  │    │    DB polling)   │                │              │
  │  │    │                  │                │              │
  │  │    └── run_agent()    │                │              │
  │  │        → append()     │                │              │
  │  │          (cycle)      │                │              │
  │  │                       │                │              │
  │  │  CommandProcessor     │                │              │
  │  │    polls command_queue│                │              │
  │  │    → dispatches       │                │              │
  │  └───────────┬───────────┘                │              │
  │              │                            │              │
  └──────────────┼────────────────────────────┼──────────────┘
                 │                            │
                 │  WRITES ▼       READS ▼    │
                 │                            │
 ═══════════ SINGLE DATABASE ════════════════════════════════

  ┌──────────────────────────────────────────────────────────┐
  │                                                          │
  │           .remora/indexer.db  (SQLite WAL)               │
  │                                                          │
  │  ┌─────────────────────────────────────────────────────┐ │
  │  │ events (append-only log — SOURCE OF TRUTH)          │ │
  │  │                                                     │ │
  │  │ rowid  INTEGER PRIMARY KEY  (auto, used for tail)   │ │
  │  │ event_id     TEXT UNIQUE                            │ │
  │  │ event_type   TEXT NOT NULL                          │ │
  │  │ timestamp    REAL NOT NULL                          │ │
  │  │ agent_id     TEXT           (who emitted)           │ │
  │  │ from_agent   TEXT           (routing: source)       │ │
  │  │ to_agent     TEXT           (routing: target)       │ │
  │  │ correlation_id TEXT         (cascade tracking)      │ │
  │  │ tags         TEXT           (JSON array, matching)  │ │
  │  │ payload      TEXT NOT NULL  (JSON, full event data) │ │
  │  │ created_at   REAL NOT NULL                          │ │
  │  └─────────────────────────────────────────────────────┘ │
  │                                                          │
  │  MATERIALIZED VIEWS (updated transactionally on append): │
  │                                                          │
  │  ┌────────────┐ ┌──────────┐ ┌──────────────────────┐   │
  │  │   nodes     │ │  edges   │ │   proposals          │   │
  │  │ (agents)    │ │          │ │                      │   │
  │  │ id TEXT PK  │ │ from_id  │ │ proposal_id TEXT PK  │   │
  │  │ node_type   │ │ to_id    │ │ agent_id             │   │
  │  │ name        │ │ edge_type│ │ old/new_source       │   │
  │  │ file_path   │ │          │ │ diff                 │   │
  │  │ source_code │ │          │ │ status               │   │
  │  │ status      │ │          │ │ created_at           │   │
  │  │ parent_id   │ │          │ │                      │   │
  │  └─────────────┘ └──────────┘ └──────────────────────┘   │
  │                                                          │
  │  ┌───────────────┐ ┌──────────────────┐                  │
  │  │ subscriptions  │ │  command_queue    │                 │
  │  │                │ │                  │                  │
  │  │ id INTEGER PK  │ │ id INTEGER PK    │                 │
  │  │ agent_id       │ │ command_type     │                 │
  │  │ pattern_json   │ │ agent_id         │                 │
  │  │ is_default     │ │ payload          │                 │
  │  │ created_at     │ │ status           │                 │
  │  │ updated_at     │ │ created_at       │                 │
  │  └────────────────┘ └──────────────────┘                 │
  │                                                          │
  │  ┌──────────────┐ ┌──────────────────┐                   │
  │  │ cursor_focus  │ │ activation_chain │                  │
  │  │ (singleton)   │ │                  │                  │
  │  │ agent_id      │ │ correlation_id   │                  │
  │  │ file_path     │ │ agent_id         │                  │
  │  │ line          │ │ depth            │                  │
  │  │ timestamp     │ │ timestamp        │                  │
  │  └───────────────┘ └──────────────────┘                  │
  │                                                          │
  └──────────────────────────────────────────────────────────┘
```

---

## EventLog — The Single Write Path

The `EventLog` class replaces both `EventBus` and `EventStore`. It is
the only way to mutate state in Remora.

### Interface

```python
class EventLog:
    """Append-only event log with materialized view projections
    and in-process subscriber notification."""

    def __init__(self, db: RemoraDB, subscriptions: SubscriptionMatcher) -> None:
        ...

    async def append(self, event: RemoraEvent, *, graph_id: str = "swarm") -> int:
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
        ...

    def subscribe(self, handler: EventHandler) -> None:
        """Register an in-process event handler.
        Called synchronously after each append (step 5)."""
        ...

    def subscribe_typed(self, event_type: type, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        ...

    def unsubscribe(self, handler: EventHandler) -> None:
        ...

    async def get_triggers(self) -> AsyncIterator[tuple[str, int, RemoraEvent]]:
        """Yield (agent_id, event_rowid, event) for subscription matches.
        Consumed by AgentRunner. In-process queue, not DB polling."""
        ...

    async def tail(self, *, after_rowid: int = 0) -> AsyncIterator[dict]:
        """Yield events with rowid > after_rowid.
        For cross-process readers (web servers)."""
        ...

    async def replay(
        self,
        graph_id: str,
        *,
        event_types: list[str] | None = None,
        since: float | None = None,
        after_id: int | None = None,
    ) -> AsyncIterator[dict]:
        """Replay historical events. For debugging and time travel."""
        ...
```

### The append() Transaction

This is the heart of the system. Every state mutation goes through here:

```python
async def append(self, event: RemoraEvent, *, graph_id: str = "swarm") -> int:
    event_type = type(event).__name__
    payload = serialize_event(event)
    timestamp = getattr(event, "timestamp", None) or time.time()
    now = time.time()

    # Extract routing fields
    from_agent = getattr(event, "from_agent", None)
    to_agent = getattr(event, "to_agent", None)
    agent_id = getattr(event, "agent_id", None)
    correlation_id = getattr(event, "correlation_id", None)
    tags = getattr(event, "tags", None)

    async with self._lock:
        # Steps 1-2: Insert event + apply projection in one transaction
        cursor = self._db.conn.cursor()
        cursor.execute("BEGIN")
        try:
            cursor.execute(
                """INSERT INTO events
                   (event_id, event_type, timestamp, agent_id,
                    from_agent, to_agent, correlation_id, tags,
                    payload, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (generate_id(), event_type, timestamp, agent_id,
                 from_agent, to_agent, correlation_id,
                 json.dumps(tags) if tags else None,
                 payload, now),
            )
            rowid = cursor.lastrowid

            # Step 2b: Apply projection
            self._apply_projection(cursor, event)

            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise

    # Step 4: Match subscriptions (outside transaction)
    matching_agents = self._subscriptions.get_matching_agents(event)
    for matched_agent_id in matching_agents:
        await self._trigger_queue.put((matched_agent_id, rowid, event))

    # Step 5: Notify in-process subscribers
    await self._notify(event)

    return rowid
```

### Projections

Projections update materialized views based on event type. They run
inside the same SQLite transaction as the event INSERT, so views are
always consistent with the log.

```python
def _apply_projection(self, cursor: sqlite3.Cursor, event: RemoraEvent) -> None:
    """Update materialized views based on event type.

    Only events that change persistent state need projections.
    Lifecycle events (AgentStartEvent, ToolCallEvent, etc.) are
    recorded in the log but don't update any view.
    """
    match event:
        case NodeCreatedEvent():
            cursor.execute(
                "INSERT OR REPLACE INTO nodes (...) VALUES (...)",
                ...
            )
        case EdgeAddedEvent():
            cursor.execute(
                "INSERT OR REPLACE INTO edges (...) VALUES (...)",
                ...
            )
        case ProposalCreatedEvent():
            cursor.execute(
                "INSERT INTO proposals (...) VALUES (...)",
                ...
            )
        case ProposalStatusChanged():
            cursor.execute(
                "UPDATE proposals SET status = ? WHERE proposal_id = ?",
                ...
            )
        case AgentStatusChanged():
            cursor.execute(
                "UPDATE nodes SET status = ? WHERE id = ?",
                ...
            )
        case CursorFocusChanged():
            cursor.execute(
                "INSERT OR REPLACE INTO cursor_focus (...) VALUES (...)",
                ...
            )
        case _:
            # Most events (AgentMessageEvent, ToolCallEvent,
            # ModelResponseEvent, etc.) don't need projections.
            # They're recorded in the log and that's enough.
            pass
```

**Which events need projections:** Only events that change the state of
materialized views. The vast majority of events (agent messages, LLM
interactions, lifecycle notifications) only need to be in the log.

The current code already has all the projection logic — it's just
scattered across `RemoraDB.upsert_nodes()`, `RemoraDB.update_edges()`,
`RemoraDB.store_proposal()`, etc. We're consolidating it into one place.

---

## Materialized Views

The `nodes`, `edges`, `proposals`, `cursor_focus`, and
`activation_chain` tables are materialized views. They are NOT the
source of truth — the events table is. But they exist for read
performance: web servers and LSP handlers query these tables directly
instead of replaying events.

### Consistency Guarantee

Because projections run in the same SQLite transaction as the event
INSERT, materialized views are always consistent with the event log at
any point in time. There is no window where an event exists but its
projection hasn't been applied.

### Rebuild Capability

A `rebuild_views()` method can replay all events and reconstruct
materialized views from scratch. This is a safety net for projection
bugs, not a routine operation.

```python
async def rebuild_views(self) -> None:
    """Nuclear option: replay all events, rebuild all views."""
    cursor = self._db.conn.cursor()
    cursor.execute("BEGIN")
    try:
        # Clear all views
        cursor.execute("DELETE FROM nodes")
        cursor.execute("DELETE FROM edges")
        cursor.execute("DELETE FROM proposals")
        cursor.execute("DELETE FROM cursor_focus")
        cursor.execute("DELETE FROM activation_chain")

        # Replay all events in order
        cursor.execute("SELECT * FROM events ORDER BY rowid ASC")
        for row in cursor.fetchall():
            event = deserialize_event(row)
            self._apply_projection(cursor, event)

        cursor.execute("COMMIT")
    except Exception:
        cursor.execute("ROLLBACK")
        raise
```

This is not expected to be needed in normal operation. It exists as a
debugging tool and as proof that the event log is authoritative.

---

## Subscription Routing

The `SubscriptionRegistry` pattern matching logic is already correct and
well-tested. It stays mostly as-is, with these changes:

1. **Storage moves into indexer.db** — The `subscriptions` table
   migrates from `subscriptions.db` into `indexer.db`.

2. **SubscriptionMatcher extracted** — The `SubscriptionPattern.matches()`
   logic and `get_matching_agents()` become a pure function that the
   EventLog calls after each append. No separate DB connection needed.

3. **Subscription mutations are events** — Registering or removing a
   subscription emits a `SubscriptionRegisteredEvent` or
   `SubscriptionRemovedEvent`. The projection inserts/deletes from the
   `subscriptions` table.

### Pattern Matching (unchanged)

The `SubscriptionPattern` dataclass already handles the five matching
dimensions correctly:

- `event_types: list[str] | None` — Match by event class name
- `from_agents: list[str] | None` — Match by source agent
- `to_agent: str | None` — Match by target agent (direct messages)
- `path_glob: str | None` — Match by file path pattern
- `tags: list[str] | None` — Match by event tags

All fields are optional; `None` means "match anything." This is a
sound design that doesn't need changing.

### Default Subscriptions (unchanged)

Every agent gets two default subscriptions on creation:

1. Direct messages: `SubscriptionPattern(to_agent=agent_id)`
2. Source file changes: `SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob=file_path)`

These are created by `register_defaults()` and marked with
`is_default=True` so they can be distinguished from agent-created
subscriptions.

### Agent-Created Subscriptions

Agents can create their own subscriptions at runtime via the
`register_subscription` external. This allows agents to dynamically
opt into event streams they care about. For example, a module-level
agent might subscribe to all `AgentCompleteEvent` events from its
child functions.

---

## Cascade Safety

Reactive chains (A triggers B triggers C) need circuit breakers. The
current implementation already has these; they stay as-is:

### Depth Limiting

`AgentRunner._check_depth_limit()` tracks cascade depth per
`(agent_id, correlation_id)` pair. `Config.max_trigger_depth` (default:
5) caps how deep a chain can go. This prevents infinite loops where A
triggers B triggers A triggers B...

### Cooldown

`AgentRunner._check_cooldown()` enforces a minimum interval between
triggers for the same agent. `Config.trigger_cooldown_ms` (default:
1000ms) prevents rapid re-triggering.

### Concurrency Limiting

`AgentRunner._semaphore` (initialized from `Config.max_concurrency`,
default: 4) limits how many agents can execute simultaneously. This
prevents resource exhaustion from cascade storms.

### Correlation ID Propagation

Every event chain starts with a correlation ID (generated by
`RemoraLanguageServer.generate_correlation_id()`). As agents trigger
other agents, the correlation ID is propagated through the
`SwarmExecutor.externals["correlation_id"]`. This enables:

- Tracing a complete chain of activations through the event log
- Depth tracking per-chain (not global)
- Debugging which event triggered which agent

The `activation_chain` table records the causal chain for each
correlation ID, providing a queryable trace of agent activation
sequences.

---

## Cross-Process Readers

Web servers (Dashboard, Graph Viewer) run in a separate process from
the LSP server. They cannot receive in-process notifications. Instead,
they tail the events table by rowid.

### Event Tailing

```python
class EventTailReader:
    """Cross-process reader that tails the events table."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA query_only=ON")
        self._conn.row_factory = sqlite3.Row
        self._last_rowid: int = 0

    def poll(self) -> list[dict]:
        """Read new events since last poll."""
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT rowid, * FROM events WHERE rowid > ? ORDER BY rowid ASC",
            (self._last_rowid,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        if rows:
            self._last_rowid = rows[-1]["rowid"]
        return rows
```

### Why Tailing Beats Fingerprinting

The current graph viewer fingerprints the DB state by querying
`count(*)`, `max(rowid)` across multiple tables
(`graph/state.py:149-172`). This has several problems:

1. **Multiple queries per poll** — 5 separate SELECT statements per
   cycle (nodes count, edges count, cursor_focus, events max, proposals
   max).
2. **No information about what changed** — You know *something* changed
   but not *what*. The viewer must re-read all nodes and edges every
   time.
3. **Race conditions** — Between the fingerprint check and the snapshot
   read, more changes can arrive.

Event tailing solves all three:

1. **One query per poll** — `SELECT rowid, * FROM events WHERE rowid > ?`
2. **Event-grained changes** — You know exactly which events occurred.
   You could (eventually) send targeted patches for just the affected
   nodes.
3. **No races** — The rowid cursor is monotonic. You never miss or
   double-process an event.

### Web Server SSE Loop

```python
async def sse_loop(reader: EventTailReader, render_fn):
    """SSE stream that pushes HTML patches when events arrive."""
    while True:
        await asyncio.sleep(0.5)
        new_events = await asyncio.to_thread(reader.poll)
        if new_events:
            # Read current state from materialized views
            state = await asyncio.to_thread(reader.read_state)
            yield render_patch(state)
```

**Future optimization:** Instead of re-reading all state on every event
batch, use the event types to determine which part of the page to
re-render. A `CursorFocusChangedEvent` only needs to update the
cursor indicator, not the full node list. This is a follow-up, not a
launch requirement.

---

## Dual Event Model Unification

The current system has two parallel event type systems (see
[Current State Analysis](#current-state-analysis)). This creates a
translation layer (`to_core_event()`) that is fragile and lossy.

### The Problem

The LSP server uses Pydantic models (`lsp/models.py`): `HumanChatEvent`,
`AgentMessageEvent`, `RewriteProposalEvent`, etc. These have rich fields
like `to_agent`, `message`, `proposal_id`, `diff`.

The core system uses frozen dataclasses (`core/events.py`):
`AgentStartEvent`, `AgentCompleteEvent`, `AgentMessageEvent`, etc.
These overlap partially but not completely with the Pydantic models.

`server.py:emit_event()` stores the Pydantic event in RemoraDB (with
full model), then converts to a core event via `to_core_event()` and
appends that to EventStore. The conversion is lossy — some Pydantic
fields don't survive the trip.

### The Solution

**One event type system.** The core frozen dataclasses become the
canonical event types. The LSP Pydantic models (`AgentEvent`,
`HumanChatEvent`, etc.) become thin wrappers that:

1. Accept input from LSP handlers (Pydantic validation)
2. Convert to the canonical core event
3. Pass the core event to `EventLog.append()`

The `to_core_event()` method stays, but it becomes the *only* path for
event creation from LSP handlers. No more dual-write where the Pydantic
model goes to RemoraDB and the core event goes to EventStore — there's
only one destination.

### New Event Types Needed

The current event types don't cover all state mutations. We need:

| Event | Purpose | Projection |
|---|---|---|
| `NodeUpsertedEvent` | Node created or updated by AST watcher | INSERT/UPDATE nodes |
| `NodeOrphanedEvent` | Node no longer found in source | UPDATE nodes SET status='orphaned' |
| `EdgeUpdatedEvent` | Call graph edge added/removed | INSERT/DELETE edges |
| `ProposalCreatedEvent` | Agent proposed a rewrite | INSERT proposals |
| `ProposalAcceptedEvent` | Human approved proposal | UPDATE proposals SET status='accepted' |
| `ProposalRejectedEvent` | Human rejected proposal | UPDATE proposals SET status='rejected' |
| `CursorFocusChangedEvent` | User moved cursor in Neovim | UPDATE cursor_focus |
| `SubscriptionRegisteredEvent` | Agent registered a subscription | INSERT subscriptions |
| `SubscriptionRemovedEvent` | Subscription removed | DELETE subscriptions |

These events don't need to participate in subscription routing (no agent
needs to react to `CursorFocusChangedEvent`). They exist so that:

1. The event log captures all state changes (source of truth)
2. Cross-process readers can see what changed without re-reading views
3. `rebuild_views()` can reconstruct everything from the log

### Events That Stay Unchanged

All the current core events (`core/events.py`) stay as-is:

- `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent` — lifecycle
- `AgentMessageEvent` — agent-to-agent communication
- `FileSavedEvent`, `ContentChangedEvent` — file system events
- `ManualTriggerEvent` — user-initiated triggers
- `HumanInputRequestEvent`, `HumanInputResponseEvent` — HITL flow
- structured-agents re-exports (`ToolCallEvent`, `ModelResponseEvent`, etc.)

---

## Database Consolidation

### Tables Migrated into indexer.db

| Source | Table | Target |
|---|---|---|
| `events.db` | events | indexer.db events (schema unified, see below) |
| `swarm_state.db` | agents | **Deleted** — nodes table serves this purpose |
| `subscriptions.db` | subscriptions | indexer.db subscriptions |

### Events Table Schema Unification

Currently, RemoraDB's `events` table and EventStore's `events` table
have different schemas:

**RemoraDB events:**
```sql
event_id TEXT PRIMARY KEY, event_type TEXT, timestamp REAL,
correlation_id TEXT, agent_id TEXT, payload JSON
```

**EventStore events:**
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT, graph_id TEXT, event_type TEXT,
payload TEXT, timestamp REAL, created_at REAL, from_agent TEXT,
to_agent TEXT, correlation_id TEXT, tags TEXT
```

The unified schema keeps the best of both:

```sql
CREATE TABLE IF NOT EXISTS events (
    rowid         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id      TEXT UNIQUE NOT NULL,
    event_type    TEXT NOT NULL,
    timestamp     REAL NOT NULL,
    created_at    REAL NOT NULL,
    agent_id      TEXT,
    from_agent    TEXT,
    to_agent      TEXT,
    correlation_id TEXT,
    tags          TEXT,
    payload       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id);
CREATE INDEX IF NOT EXISTS idx_events_to_agent ON events(to_agent);
CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
```

**Dropped:** `graph_id` column — in the unified architecture, everything
is one graph. The `correlation_id` field provides chain grouping, which
is what `graph_id` was actually used for.

**Added:** `rowid` as explicit autoincrement for event tailing.
`event_id` stays as a unique human-readable ID for external reference.

### SwarmState Elimination

The `SwarmState` class (`swarm_state.py`) maintains an `agents` table
with: `agent_id, node_type, name, full_name, file_path, parent_id,
start_line, end_line, status, created_at, updated_at`.

The `nodes` table in RemoraDB already has: `id, node_type, name,
file_path, start_line, end_line, start_col, end_col, source_code,
source_hash, status, pending_proposal_id, parent_id`.

These are the same data with slightly different columns. The `nodes`
table is a superset — it has `source_code`, `source_hash`, column
positions, and `pending_proposal_id` that `agents` doesn't.

**Resolution:** Delete `SwarmState`. The `nodes` table is the agent
registry. Code that calls `swarm_state.list_agents()` uses
`SELECT * FROM nodes WHERE status != 'orphaned'` instead. The
`full_name` field (present in SwarmState but not nodes) gets added to
the nodes table.

The `SwarmExecutor` methods that use SwarmState (`_broadcast` at line
118, `_query_agents` at line 159) are updated to query the nodes table
directly.

---

## Migration Map

### What Gets Deleted

| Module | Why |
|---|---|
| `src/remora/core/event_bus.py` | Replaced by EventLog in-process subscribers |
| `src/remora/core/event_store.py` | Replaced by EventLog |
| `src/remora/core/swarm_state.py` | Replaced by nodes table in RemoraDB |
| `src/remora/ui/projector.py` | Replaced by direct DB reads from materialized views |
| `.remora/events/events.db` | Consolidated into indexer.db |
| `.remora/swarm_state.db` | Consolidated into indexer.db |
| `.remora/subscriptions.db` | Consolidated into indexer.db |

### What Gets Transformed

| Module | From | To |
|---|---|---|
| `EventStore` → `EventLog` | Separate DB, dual-write with EventBus | Single DB, single write path, in-process notification |
| `SubscriptionRegistry` | Separate DB, loaded fresh each match | Same DB, pattern matching extracted as pure function |
| `RemoraService` | EventBus/EventStore/SwarmState/Projector deps | DBReader (or EventTailReader) only |
| `GraphState` | Fingerprint polling, own DB connection | EventTailReader, shared schema |
| `RemoraLanguageServer.emit_event()` | Dual-write: RemoraDB + EventStore | Single call: EventLog.append() |
| `SwarmExecutor.externals` | Uses SwarmState for query_agents/broadcast | Queries nodes table directly |

### What Stays Unchanged

| Module | Why |
|---|---|
| `src/remora/core/events.py` | Canonical event types — stays as-is, extended with new types |
| `src/remora/core/subscriptions.py` (pattern logic) | Pattern matching is correct, just storage moves |
| `src/remora/lsp/graph.py` (LazyGraph) | Hard keep — rustworkx cycle detection |
| `src/remora/lsp/db.py` (RemoraDB) | The surviving DB — gains subscriptions table, enhanced events schema |
| `src/remora/core/agent_runner.py` (logic) | Cascade safety, cooldown, depth — stays as-is. Just swap EventStore for EventLog |
| `src/remora/core/config.py` | No changes needed |
| `src/remora/lsp/models.py` (Pydantic) | `to_core_event()` becomes the primary path rather than a secondary one |

---

## Trade-offs and Mitigations

### Event Schema is Load-Bearing

**Trade-off:** Adding new state mutations requires defining a new event
type and writing its projection. This is more ceremony than a direct SQL
UPDATE.

**Mitigation:** Most state mutations already have event types. The new
ones (`NodeUpsertedEvent`, `ProposalCreatedEvent`, etc.) are simple
mechanical additions. The projection logic already exists in scattered
`RemoraDB` methods — we're just consolidating it.

**Escape hatch:** For truly ephemeral state that doesn't need event
sourcing (e.g., cursor_focus is borderline), a direct DB write is
acceptable as a pragmatic choice. The design accommodates this — the
events table doesn't need to be 100% of all writes, just 100% of all
writes that agents or external processes need to observe.

### Read Amplification

**Trade-off:** If we only had the event log, every read would require
replaying events. This is N-squared for dashboards that render on every
change.

**Mitigation:** Materialized views. Reads go to `nodes`, `edges`,
`proposals` tables — standard indexed SQL queries. The event log is
only read for: tailing (cross-process), replay (debugging), and rebuild
(recovery). Normal operation never scans the full event log.

### Projection Bugs

**Trade-off:** If a projection has a bug, the materialized view drifts
from the event log. The events table says X happened, but the nodes
table doesn't reflect it.

**Mitigation:**
1. Projections are simple INSERT/UPDATE/DELETE — minimal logic, easy to
   audit.
2. `rebuild_views()` can reconstruct from scratch.
3. Events and projections are in the same transaction — there's no
   partial application. Either both succeed or neither does.
4. Tests can verify: append event, read view, assert consistency.

### In-Memory Queue Durability

**Trade-off:** The trigger queue (`asyncio.Queue`) is in-memory. If the
process crashes between event persistence and trigger delivery, the
trigger is lost.

**Mitigation:** This is the same trade-off the current system makes
(`EventStore._trigger_queue` is an `asyncio.Queue` today). On restart,
the AgentRunner can scan recent events and re-check subscriptions to
recover missed triggers. This is a follow-up enhancement, not a launch
blocker — the current system doesn't have it either.

### SQLite Write Contention

**Trade-off:** Single SQLite database means all writes serialize through
one WAL writer.

**Mitigation:** Remora's write volume is low — events are generated by
LLM responses (seconds apart, not milliseconds) and human interactions.
SQLite WAL handles thousands of writes per second. The bottleneck is
LLM latency, not DB throughput. If this ever becomes a problem (it
won't), the event tailing design is compatible with migrating to
PostgreSQL's LISTEN/NOTIFY.

### Increased Disk Usage

**Trade-off:** Event log grows monotonically. Old events are never
deleted.

**Mitigation:** Events are small (few KB each). A year of heavy usage
might produce 100K events — maybe 50MB. SQLite handles this trivially.
If needed, a compaction strategy can archive events older than N days
while preserving the materialized views.

---

## Decisions (Resolved)

### 1. Cursor Focus — Debounced Event (Decision: C)

`CursorFocusChanged` fires on every cursor movement in Neovim — thousands
of events per minute during active editing.

**Decision:** Debounced event. Only emit `CursorFocusChangedEvent` after
the cursor is stable for 200ms. This balances event-log consistency
with practical volume concerns. The debounce happens in the LSP server
layer (Neovim-side or `server.py`), not in EventLog.

**Rationale:** Cursor focus is mostly UI state, but debounced events
keep it in the unified timeline without overwhelming the log. If an
agent later wants to react to cursor position (e.g. "user is reading
this function"), the data is there.

### 2. structured-agents Events — Full Event Treatment (Decision: C)

The structured-agents library emits fine-grained kernel events
(`ToolCallEvent`, `ModelResponseEvent`, `TurnCompleteEvent`, etc.).
Currently, SwarmExecutor's `_EventStoreObserver` appends ALL of them to
EventStore.

**Decision:** Full event treatment. Kernel events go through the
complete `EventLog.append()` pipeline INCLUDING subscription matching.
No fast path, no kernel flag bypass.

**Rationale:** Agents reacting to other agents' behavior is core to the
Remora vision, not speculative. Use cases:

- A monitoring agent watches cursor location, triggers scripts to build
  a "maximum context node" by searching a wikipedia graph
- Meta-agents watch those wikipedia graph searches, do web searches to
  find more data, and pass refined article selections downstream
- Debugging/observability agents that watch for error patterns in tool
  call results

This means subscription matching runs on every event type. The existing
cascade safety mechanisms (depth limits, cooldown, concurrency caps)
apply equally to meta-agent chains, preventing infinite loops of agents
watching agents. Subscription matching is pattern-matching (cheap), so
the per-event cost is negligible.

### 3. Event Schema Versioning — Defaults on Missing (Decision: A)

**Decision:** JSON payloads, missing fields get defaults during
deserialization. No formal versioning system.

**Rationale:** We never change the meaning of existing fields — we only
add new ones. `replay()` and `rebuild_views()` use the dataclass
constructors which handle missing fields via defaults. If we ever need
formal versioning, we can add a `schema_version` field later (YAGNI).

### 4. command_queue — Keep as Work Queue (Decision: A)

**Decision:** Keep `command_queue` as a separate table with its existing
lifecycle (pending → processing → done → failed). CommandProcessor
processes commands and emits domain events about what happened.

**Rationale:** Commands are imperative ("do this") and consumed exactly
once. Events are descriptive ("this happened") and broadcast. Mixing
them muddies event log semantics and adds correlation complexity for no
real gain. The audit trail lives in the domain events that CommandProcessor
emits as a result of processing commands.

---

## Relationship to Existing Plan

This document supersedes `docs/plans/2026-03-01-architectural-unification.md`.
That plan has been revised to follow the EventLog-first approach described here.
See the revised plan for the current implementation sequence.
