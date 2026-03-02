# Architectural Unification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify the three parallel systems (LSP server, service dashboard, graph viewer) around a single SQLite DB as source of truth, with Datastar-aligned web UIs and the LSP server as primary writer.

**Architecture:** RemoraDB (`.remora/indexer.db`) becomes the single source of truth for all state. The service layer's separate DBs (events.db, swarm_state.db, subscriptions.db) and in-memory EventBus are eliminated. Web UIs use Datastar's CQRS pattern: one long-lived `GET /subscribe` SSE stream reads the DB and pushes `patch_elements` HTML fragments; short-lived `POST /command` writes to the command_queue table. The LSP server continues as the primary writer. The graph viewer keeps d3-force client-side but aligns all non-visualization concerns (sidebar, commands, status) to Datastar conventions.

**Tech Stack:** Python 3.12, SQLite WAL, Starlette, datastar-py, pygls, d3-force

---

## Background: Current State

### Three Parallel Systems

1. **LSP Server** (`src/remora/lsp/`) — RemoraLanguageServer + RemoraDB. Writes nodes, edges, events, proposals, cursor_focus, command_queue to `.remora/indexer.db`. Pushes to Neovim via LSP notifications.

2. **Service Dashboard** (`src/remora/service/` + `src/remora/adapters/starlette.py`) — RemoraService with its own EventBus, EventStore (`.remora/events/events.db`), SwarmState (`.remora/swarm_state.db`), SubscriptionRegistry (`.remora/subscriptions.db`), UiStateProjector. Serves a Datastar-powered dashboard.

3. **Graph Viewer** (`remora_demo/graph/`) — Standalone Starlette app. Reads `.remora/indexer.db` via GraphState (read-only WAL polling). Pushes graph data as Datastar signals. Heavy client-side d3 JS.

### Problems

- **4 SQLite databases** for what should be one source of truth
- **In-memory EventBus** duplicates what the DB already stores
- **UiStateProjector** is a redundant in-memory reducer — the DB already has this state
- **Graph viewer uses `patch_signals`** for app state (violates Datastar philosophy)
- **Raw `fetch()` calls** in graph viewer JS instead of Datastar `@get()`/`@post()`
- **Service dashboard re-renders entire page** on every event
- **No CQRS pattern** — reads and writes aren't cleanly separated

### Datastar Philosophy (The Tao)

1. Backend owns state. Signals are only for ephemeral UI interactions.
2. Patch elements, not signals — push HTML fragments via SSE.
3. CQRS: one long-lived GET (SSE read stream) + short-lived POSTs (commands).
4. Fat morph: send large HTML chunks, let Idiomorph diff.
5. No optimistic updates. Show loading state, confirm from server.
6. Minimal client JS.

## Target Architecture

```
.remora/indexer.db (single SQLite WAL database)
    |
    v reads/writes
LSP Server (primary writer)
    |--- LSP notifications --> Neovim (CodeLens, Diagnostics, Hover)
    |--- writes nodes, edges, events, proposals, cursor_focus
    |--- polls command_queue, processes commands
    |
    v reads (WAL snapshot isolation)
Web Server (thin Starlette reader)
    |--- GET /subscribe --> SSE patch_elements (HTML fragments) --> Browser
    |--- POST /command  --> INSERT INTO command_queue --> 200 OK
    |
    v reads (WAL snapshot isolation)
Graph Viewer (specialized Starlette reader)
    |--- GET /subscribe --> SSE patch_signals (graph data for d3) + patch_elements (sidebar/chrome)
    |--- POST /command  --> INSERT INTO command_queue --> 200 OK
```

### Full Architecture Diagram

```
                        REMORA — Unified Architecture
 ═══════════════════════════════════════════════════════════════════════

                         ┌──────────────────┐
                         │    Human User     │
                         └──┬───────────┬────┘
                            │           │
                   edits code│           │ opens browser
                            │           │
              ┌─────────────▼──┐   ┌────▼─────────────────────────┐
              │    Neovim       │   │         Browser(s)            │
              │                 │   │                               │
              │  ┌───────────┐  │   │  ┌────────────┐ ┌─────────┐  │
              │  │ CodeLens   │  │   │  │ Dashboard  │ │  Graph  │  │
              │  │ Hover      │  │   │  │ (Datastar) │ │ Viewer  │  │
              │  │ Diagnostics│  │   │  │            │ │(Datastar│  │
              │  │ Actions    │  │   │  │ HTML morph │ │ +d3)    │  │
              │  └─────▲──────┘  │   │  └─────▲──────┘ └───▲─────┘  │
              └────────┼─────────┘   └────────┼────────────┼────────┘
                       │                      │            │
              LSP      │              SSE     │     SSE    │
              protocol │         patch_elements   patch_signals
              (jsonrpc)│              +       │   (graph data)
                       │         patch_elements   +
                       │              │       patch_elements
                       │              │            │
 ═══════════════ SERVER PROCESSES ══════════════════════════════════════

  ┌────────────────────┴──────────────────────────────────────────────┐
  │                                                                    │
  │  ┌─────────────────────────────┐    ┌────────────────────────────┐ │
  │  │     LSP Server (pygls)      │    │  Web Server (Starlette)    │ │
  │  │                             │    │                            │ │
  │  │  RemoraLanguageServer       │    │  GET /subscribe → SSE      │ │
  │  │    │                        │    │  POST /command  → DB write  │ │
  │  │    ├── ASTWatcher           │    │                            │ │
  │  │    │   (file change → parse │    │  GET /agent/{id} → HTML    │ │
  │  │    │    → upsert nodes)     │    │                            │ │
  │  │    │                        │    │  Polls change_counter      │ │
  │  │    ├── AgentRunner          │    │  Reads via DBReader        │ │
  │  │    │   (LLM execution)      │    │  (read-only WAL conn)      │ │
  │  │    │                        │    │                            │ │
  │  │    ├── CommandProcessor     │    └──────────────┬─────────────┘ │
  │  │    │   (polls command_queue │                   │               │
  │  │    │    → dispatch)         │                   │               │
  │  │    │                        │                   │               │
  │  │    └── LSP Handlers         │                   │               │
  │  │        (hover, lens, etc.)  │                   │               │
  │  │                             │                   │               │
  │  │  WRITES to DB:              │    READS from DB: │               │
  │  │  ├── nodes, edges           │    ├── nodes, edges              │
  │  │  ├── events                 │    ├── events                    │
  │  │  ├── proposals              │    ├── proposals                 │
  │  │  ├── cursor_focus           │    ├── cursor_focus              │
  │  │  └── marks commands done    │    └── change_counter            │
  │  │                             │                   │               │
  │  └──────────────┬──────────────┘                   │               │
  │                 │                                   │               │
  └─────────────────┼───────────────────────────────────┼───────────────┘
                    │                                   │
                    │  WRITES ▼              READS ▼    │
                    │                                   │
 ═══════════════ SINGLE DATABASE ══════════════════════════════════════

  ┌────────────────────────────────────────────────────────────────────┐
  │                                                                    │
  │              .remora/indexer.db  (SQLite WAL)                       │
  │                                                                    │
  │  ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────────┐   │
  │  │   nodes     │ │  edges   │ │  events  │ │   proposals       │   │
  │  │             │ │          │ │          │ │                   │   │
  │  │ id          │ │ from_id  │ │ event_id │ │ proposal_id       │   │
  │  │ node_type   │ │ to_id    │ │ type     │ │ agent_id          │   │
  │  │ name        │ │ edge_type│ │ timestamp│ │ old/new_source    │   │
  │  │ file_path   │ │          │ │ agent_id │ │ diff              │   │
  │  │ source_code │ │          │ │ payload  │ │ status            │   │
  │  │ status      │ │          │ │          │ │                   │   │
  │  │ parent_id   │ │          │ │          │ │                   │   │
  │  └─────────────┘ └──────────┘ └──────────┘ └───────────────────┘   │
  │                                                                    │
  │  ┌──────────────┐ ┌──────────────────┐ ┌────────────────────────┐  │
  │  │ cursor_focus  │ │  command_queue    │ │  change_counter        │  │
  │  │               │ │                  │ │                        │  │
  │  │ agent_id      │ │ command_type     │ │  seq (auto-increment   │  │
  │  │ file_path     │ │ agent_id         │ │   via triggers on all  │  │
  │  │ line          │ │ payload          │ │   tables above)        │  │
  │  │ timestamp     │ │ status           │ │                        │  │
  │  │               │ │ created_at       │ │                        │  │
  │  └───────────────┘ └──────────────────┘ └────────────────────────┘  │
  │                                                                    │
  │  ┌──────────────────┐ ┌──────────────────┐                         │
  │  │ activation_chain  │ │  subscriptions    │                        │
  │  │                   │ │                  │                         │
  │  │ correlation_id    │ │ agent_id          │                        │
  │  │ agent_id          │ │ pattern_json      │                        │
  │  │ depth             │ │ is_default        │                        │
  │  └──────────────────┘ └──────────────────┘                         │
  │                                                                    │
  └────────────────────────────────────────────────────────────────────┘

 ═══════════════ DATA FLOW ════════════════════════════════════════════

  1. User edits code in Neovim
        │
        ▼
  2. LSP Server detects change (textDocument/didChange)
        │
        ▼
  3. ASTWatcher parses → upserts nodes/edges into DB
        │
        ▼
  4. change_counter increments (via SQLite trigger)
        │
        ▼
  5. Web Server's poll loop detects seq change
        │
        ▼
  6. Reads fresh state from DB
        │
        ▼
  7. Renders HTML fragments → pushes via SSE patch_elements
        │
        ▼
  8. Browser morphs DOM (Datastar/Idiomorph)

  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─

  1. User clicks "Approve" in browser
        │
        ▼
  2. POST /command → INSERT INTO command_queue
        │
        ▼
  3. LSP Server's CommandProcessor polls, finds command
        │
        ▼
  4. Dispatches to handler (applies proposal, emits event)
        │
        ▼
  5. DB updated → change_counter increments
        │
        ▼
  6. Web Server sees change → pushes updated HTML via SSE

 ═══════════════ WHAT'S GONE ══════════════════════════════════════════

  DELETED                          REPLACED BY
  ────────────────────────         ──────────────────────────
  EventBus (in-memory pubsub)      DB polling + change_counter
  EventStore (events.db)           RemoraDB events table
  SwarmState (swarm_state.db)      RemoraDB nodes table
  UiStateProjector (reducer)       Direct DB reads
  subscriptions.db                 RemoraDB subscriptions table
  GraphState._fingerprint()        change_counter seq read
```

### Note on LazyGraph (rustworkx)

`LazyGraph` (`src/remora/lsp/graph.py`) wraps an optional `rustworkx.PyDiGraph` as
an in-memory graph cache inside the LSP server. It lazy-loads neighborhoods from
the DB and provides `get_parent()` and `get_callers()` traversals.

**Current status:** Only used for 1-hop queries that are trivially served by SQL.
The recursive CTE in `RemoraDB.get_neighborhood()` already does multi-hop traversal.

**Decision: Hard keep.** Cycle detection is a requirement that SQLite CTEs handle
poorly — rustworkx provides this natively. LazyGraph stays as a permanent part of
the LSP server internals. Not shown in the architecture diagram because it's an
internal optimization detail, not an architectural boundary.

### What Gets Deleted

| Current Code | Fate |
|---|---|
| `src/remora/core/event_bus.py` (EventBus) | **Delete.** DB polling replaces in-memory pub/sub. |
| `src/remora/core/event_store.py` (EventStore) | **Delete.** RemoraDB.events table is the event store. |
| `src/remora/core/swarm_state.py` (SwarmState) | **Delete.** RemoraDB.nodes table is the swarm state. |
| `src/remora/core/subscriptions.py` (SubscriptionRegistry) | **Keep for now** — subscription matching logic is useful. Migrate its storage into RemoraDB. |
| `src/remora/ui/projector.py` (UiStateProjector) | **Delete.** Dashboard reads state directly from DB. |
| `src/remora/service/api.py` (RemoraService) | **Rewrite.** Becomes thin DB reader, no EventBus/EventStore/SwarmState deps. |
| `src/remora/service/datastar.py` | **Simplify.** Keep render_shell, simplify render_patch to target specific elements. |
| `.remora/events/events.db` | **Delete.** Events go in indexer.db. |
| `.remora/swarm_state.db` | **Delete.** Agent metadata goes in indexer.db nodes table. |
| `.remora/subscriptions.db` | **Migrate** into indexer.db as a subscriptions table. |

### What Gets Added to RemoraDB

The `nodes`, `edges`, `events`, `proposals`, `cursor_focus`, `command_queue`, `activation_chain` tables already exist. We add:

```sql
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    pattern_json TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

And add a `change_counter` table for efficient polling:

```sql
CREATE TABLE IF NOT EXISTS change_counter (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seq INTEGER NOT NULL DEFAULT 0
);

-- Triggers to auto-increment on writes
CREATE TRIGGER IF NOT EXISTS nodes_change AFTER INSERT ON nodes
BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS nodes_update_change AFTER UPDATE ON nodes
BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS edges_change AFTER INSERT ON edges
BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS events_change AFTER INSERT ON events
BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS proposals_change AFTER INSERT ON proposals
BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS cursor_focus_change AFTER UPDATE ON cursor_focus
BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

CREATE TRIGGER IF NOT EXISTS command_queue_change AFTER INSERT ON command_queue
BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
```

This replaces GraphState's fingerprint polling (`state.py:149-172`) with a single integer read.

---

## Implementation Tasks

### Task 1: Add change_counter and subscriptions tables to RemoraDB

**Files:**
- Modify: `src/remora/lsp/db.py:45-121` (schema init)

**Step 1: Write the failing test**

```python
# tests/test_db_change_counter.py
import pytest
from remora.lsp.db import RemoraDB

@pytest.fixture
def db(tmp_path):
    return RemoraDB(db_path=str(tmp_path / "test.db"))

def test_change_counter_starts_at_zero(db):
    cursor = db.conn.cursor()
    cursor.execute("SELECT seq FROM change_counter WHERE id = 1")
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == 0

def test_change_counter_increments_on_node_insert(db):
    cursor = db.conn.cursor()
    cursor.execute(
        "INSERT INTO nodes (id, node_type, name, file_path) VALUES (?, ?, ?, ?)",
        ("n1", "function", "foo", "foo.py"),
    )
    db.conn.commit()
    cursor.execute("SELECT seq FROM change_counter WHERE id = 1")
    assert cursor.fetchone()[0] == 1

def test_change_counter_increments_on_event_insert(db):
    cursor = db.conn.cursor()
    cursor.execute(
        "INSERT INTO events (event_id, event_type, timestamp, payload) VALUES (?, ?, ?, ?)",
        ("e1", "test", 1.0, "{}"),
    )
    db.conn.commit()
    cursor.execute("SELECT seq FROM change_counter WHERE id = 1")
    assert cursor.fetchone()[0] == 1

def test_subscriptions_table_exists(db):
    cursor = db.conn.cursor()
    cursor.execute("SELECT count(*) FROM subscriptions")
    assert cursor.fetchone()[0] == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_db_change_counter.py -v`
Expected: FAIL — `change_counter` table doesn't exist yet

**Step 3: Add change_counter and subscriptions tables to RemoraDB._init_schema**

In `src/remora/lsp/db.py`, inside `_init_schema()` after the existing `CREATE INDEX` statements (around line 120), add:

```python
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                pattern_json TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_subscriptions_agent
            ON subscriptions(agent_id);

            CREATE TABLE IF NOT EXISTS change_counter (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                seq INTEGER NOT NULL DEFAULT 0
            );

            INSERT OR IGNORE INTO change_counter (id, seq) VALUES (1, 0);

            CREATE TRIGGER IF NOT EXISTS trg_nodes_ins AFTER INSERT ON nodes
            BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

            CREATE TRIGGER IF NOT EXISTS trg_nodes_upd AFTER UPDATE ON nodes
            BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

            CREATE TRIGGER IF NOT EXISTS trg_edges_ins AFTER INSERT ON edges
            BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

            CREATE TRIGGER IF NOT EXISTS trg_events_ins AFTER INSERT ON events
            BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

            CREATE TRIGGER IF NOT EXISTS trg_proposals_ins AFTER INSERT ON proposals
            BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

            CREATE TRIGGER IF NOT EXISTS trg_proposals_upd AFTER UPDATE ON proposals
            BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

            CREATE TRIGGER IF NOT EXISTS trg_cursor_upd AFTER UPDATE ON cursor_focus
            BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

            CREATE TRIGGER IF NOT EXISTS trg_cursor_ins AFTER INSERT ON cursor_focus
            BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;

            CREATE TRIGGER IF NOT EXISTS trg_cmdq_ins AFTER INSERT ON command_queue
            BEGIN UPDATE change_counter SET seq = seq + 1 WHERE id = 1; END;
```

Also add a sync method to read the counter:

```python
def get_change_seq(self) -> int:
    """Read the current change sequence number (sync, for polling)."""
    cursor = self.conn.cursor()
    cursor.execute("SELECT seq FROM change_counter WHERE id = 1")
    row = cursor.fetchone()
    return row[0] if row else 0
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_db_change_counter.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/remora/lsp/db.py tests/test_db_change_counter.py
git commit -m "feat(db): add change_counter triggers and subscriptions table to RemoraDB"
```

---

### Task 2: Add DB reader module for web servers

Create a lightweight, read-only DB reader that both the service dashboard and graph viewer can use. This replaces `GraphState` and the `RemoraService` read paths.

**Files:**
- Create: `src/remora/db/reader.py`
- Test: `tests/test_db_reader.py`

**Step 1: Write the failing test**

```python
# tests/test_db_reader.py
import pytest
from remora.lsp.db import RemoraDB
from remora.db.reader import DBReader

@pytest.fixture
def populated_db(tmp_path):
    db = RemoraDB(db_path=str(tmp_path / "test.db"))
    cursor = db.conn.cursor()
    cursor.execute(
        "INSERT INTO nodes (id, node_type, name, file_path, start_line, end_line, source_code, source_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("n1", "function", "foo", "foo.py", 1, 10, "def foo(): pass", "abc123"),
    )
    cursor.execute(
        "INSERT INTO nodes (id, node_type, name, file_path, start_line, end_line, source_code, source_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("n2", "function", "bar", "bar.py", 1, 5, "def bar(): pass", "def456"),
    )
    cursor.execute(
        "INSERT INTO edges (from_id, to_id, edge_type) VALUES (?, ?, ?)",
        ("n1", "n2", "calls"),
    )
    cursor.execute(
        "INSERT INTO events (event_id, event_type, timestamp, agent_id, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("e1", "TestEvent", 1.0, "n1", '{"msg": "hello"}'),
    )
    db.conn.commit()
    return db

@pytest.fixture
def reader(populated_db, tmp_path):
    return DBReader(db_path=str(tmp_path / "test.db"))

def test_read_all_nodes(reader):
    nodes = reader.read_all_nodes()
    assert len(nodes) == 2
    assert nodes[0]["remora_id"] in ("n1", "n2")

def test_read_node(reader):
    node = reader.read_node("n1")
    assert node is not None
    assert node["name"] == "foo"

def test_read_all_edges(reader):
    edges = reader.read_all_edges()
    assert len(edges) == 1
    assert edges[0]["from_id"] == "n1"

def test_read_events_for_agent(reader):
    events = reader.read_events_for_agent("n1")
    assert len(events) == 1

def test_read_change_seq(reader):
    # After inserts via RemoraDB, the change counter should be > 0
    seq = reader.read_change_seq()
    assert seq > 0

def test_read_cursor_focus_empty(reader):
    focus = reader.read_cursor_focus()
    assert focus is None

def test_read_pending_commands(reader):
    cmds = reader.read_pending_commands()
    assert cmds == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_db_reader.py -v`
Expected: FAIL — `remora.db.reader` doesn't exist

**Step 3: Create the DBReader module**

```python
# src/remora/db/__init__.py
# (empty)
```

```python
# src/remora/db/reader.py
"""Read-only DB accessor for web servers.

Opens the RemoraDB in WAL + query_only mode. All methods are synchronous
and safe to call from asyncio.to_thread().
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class DBReader:
    """Lightweight read-only interface to RemoraDB for web server polling."""

    def __init__(self, db_path: str = ".remora/indexer.db") -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA query_only=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def read_change_seq(self) -> int:
        """Read the change_counter sequence number."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT seq FROM change_counter WHERE id = 1")
        row = cursor.fetchone()
        return row[0] if row else 0

    def read_all_nodes(self) -> list[dict]:
        """Read all non-orphaned nodes."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE status != 'orphaned'")
        return [self._normalize_node(row) for row in cursor.fetchall()]

    def read_node(self, node_id: str) -> dict | None:
        """Read a single node by ID."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        return self._normalize_node(row) if row else None

    def read_all_edges(self) -> list[dict]:
        """Read all edges."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM edges")
        return [dict(row) for row in cursor.fetchall()]

    def read_edges_for_node(self, node_id: str) -> dict:
        """Read connections for a node grouped by relationship type."""
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

    def read_events_for_agent(self, agent_id: str, limit: int = 20) -> list[dict]:
        """Read recent events for a specific agent."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_id, event_type, timestamp, correlation_id, agent_id, payload
            FROM events
            WHERE agent_id = ? OR json_extract(payload, '$.to_agent') = ?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (agent_id, agent_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def read_recent_events(self, limit: int = 50) -> list[dict]:
        """Read the most recent events across all agents."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT event_id, event_type, timestamp, agent_id, payload "
            "FROM events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def read_proposals_for_agent(self, agent_id: str) -> list[dict]:
        """Read pending proposals for a specific agent."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM proposals WHERE agent_id = ? AND status = 'pending'",
            (agent_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def read_all_pending_proposals(self) -> list[dict]:
        """Read all pending proposals."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM proposals WHERE status = 'pending'")
        return [dict(row) for row in cursor.fetchall()]

    def read_cursor_focus(self) -> dict | None:
        """Read the current cursor focus."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, file_path, line, timestamp FROM cursor_focus WHERE id = 1")
        row = cursor.fetchone()
        return dict(row) if row else None

    def read_pending_commands(self, limit: int = 10) -> list[dict]:
        """Read pending commands from the queue."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM command_queue WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def push_command(self, command_type: str, agent_id: str | None, payload: dict) -> int:
        """Write a command to the queue (opens a separate writable connection)."""
        import time
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

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_db_reader.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/remora/db/__init__.py src/remora/db/reader.py tests/test_db_reader.py
git commit -m "feat(db): add DBReader - read-only DB accessor for web servers"
```

---

### Task 3: Migrate graph viewer to use DBReader + change_counter polling

Replace `remora_demo/graph/state.py` (GraphState) with the new DBReader and change_counter-based polling.

**Files:**
- Modify: `remora_demo/graph/state.py` (rewrite to use DBReader)
- Modify: `remora_demo/graph/app.py` (update imports)
- Test: `tests/remora_demo/graph/test_state.py` (update existing tests)

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

def test_state_uses_change_counter(state, db):
    """GraphState should detect changes via change_counter, not fingerprinting."""
    seq1 = state.reader.read_change_seq()
    cursor = db.conn.cursor()
    cursor.execute(
        "INSERT INTO nodes (id, node_type, name, file_path) VALUES (?, ?, ?, ?)",
        ("n1", "function", "foo", "foo.py"),
    )
    db.conn.commit()
    seq2 = state.reader.read_change_seq()
    assert seq2 > seq1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/remora_demo/graph/test_state_v2.py -v`
Expected: FAIL — GraphState doesn't have a `reader` attribute

**Step 3: Rewrite GraphState to use DBReader**

Replace the internals of `remora_demo/graph/state.py`:

```python
"""Graph state reader with change_counter-based polling."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator

from remora.db.reader import DBReader

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
        self.reader = DBReader(db_path=db_path)
        self._last_seq: int = -1

    def read_snapshot(self) -> GraphSnapshot:
        """Read a full snapshot of nodes, edges, and cursor focus."""
        import time
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
        """Yield snapshots whenever the DB changes (change_counter polling)."""
        while True:
            await asyncio.sleep(0.5)
            try:
                seq = await asyncio.to_thread(self.reader.read_change_seq)
                if seq != self._last_seq:
                    self._last_seq = seq
                    snapshot = await asyncio.to_thread(self.read_snapshot)
                    yield snapshot
            except Exception:
                logger.debug("Poll error", exc_info=True)
                await asyncio.sleep(2.0)

    def close(self) -> None:
        self.reader.close()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/remora_demo/graph/ -v`
Expected: All existing graph tests PASS (the interface hasn't changed, only the internals)

**Step 5: Commit**

```bash
git add remora_demo/graph/state.py tests/remora_demo/graph/test_state_v2.py
git commit -m "refactor(graph): replace fingerprint polling with change_counter via DBReader"
```

---

### Task 4: Align graph viewer commands to Datastar @post()

Replace raw `fetch()` calls in `shell.py` JS with Datastar's `@post()` for commands (chat, approve, reject). Sidebar fetching stays as `fetch()` for now since it returns raw HTML outside the SSE stream.

**Files:**
- Modify: `remora_demo/graph/shell.py:474-499` (JS command helpers)
- Modify: `remora_demo/graph/shell.py:337-348` (sidebar fetch — convert to `@get()`)
- Modify: `remora_demo/graph/app.py:72-82` (POST /command needs to return SSE)

**Step 1: Update the JS command helpers in shell.py**

Replace the `sendChat`, `approveProposal`, `rejectProposal` functions and the sidebar fetch click handler. The sidebar fetch should use Datastar's `@get()` by morphing the sidebar content via `patch_elements`, and commands should use `@post()`.

For the sidebar, change the click handler from raw `fetch()` to setting a signal that triggers a Datastar `@get()`:

In `_js()`, replace the click handler (around line 337):
```javascript
enter.on('click', function(event, d) {
    selectedNodeId = d.id;
    document.querySelector('[data-signals]').__ds?.setSignal('selectedNode', d.id);
    render();
});
```

And add a Datastar-driven sidebar loader in the HTML body:
```html
<div id="sidebar-content"
     data-on-signal-change__selectedNode="@get('/agent/' + $selectedNode)">
```

For commands, replace `fetch('/command', ...)` with inline `@post()` calls on the sidebar action buttons (in `sidebar.py`).

**This is a larger refactor — defer to a later task.** For now, focus on the structural changes first.

**Step 2: Update sidebar.py to use Datastar attributes for commands**

In `render_sidebar()`, replace onclick handlers with Datastar `data-on-click` attributes:

```python
# Chat button: replace onclick with @post
parts.append(
    f'<button class="action-btn primary" style="margin-top:4px" '
    f'data-on-click="@post(\'/command\', {{body: JSON.stringify({{command_type: \'chat\', agent_id: \'{nid}\', payload: {{message: document.getElementById(\'chat-input\').value}}}})}})">Send</button>'
)

# Approve button
parts.append(
    f'<button class="action-btn" style="flex:1" '
    f'data-on-click="@post(\'/command\', {{body: JSON.stringify({{command_type: \'approve_proposal\', payload: {{proposal_id: \'{pid}\'}}}})}})">'
    f'Approve</button>'
)

# Reject button
parts.append(
    f'<button class="action-btn danger" style="flex:1" '
    f'data-on-click="@post(\'/command\', {{body: JSON.stringify({{command_type: \'reject_proposal\', payload: {{proposal_id: \'{pid}\'}}}})}})">'
    f'Reject</button>'
)
```

**NOTE:** This is a significant client-side change. The exact Datastar v1.0 RC7 `@post()` syntax should be verified against the docs. The pattern is:
```
data-on-click="@post('/command')"
data-header.Content-Type="application/json"
```

For now, keep the raw `fetch()` approach and mark this as a follow-up. The structural DB unification is the priority.

**Step 3: Skip this task for now — mark as follow-up**

This task is deferred. The Datastar attribute alignment is a UI polish concern that depends on the structural changes being complete first.

**Step 4: Commit — N/A (deferred)**

---

### Task 5: Rewrite RemoraService to use DBReader

Strip out EventBus, EventStore, SwarmState, UiStateProjector dependencies. RemoraService becomes a thin wrapper over DBReader.

**Files:**
- Modify: `src/remora/service/api.py` (rewrite)
- Modify: `src/remora/service/datastar.py` (simplify)
- Modify: `src/remora/adapters/starlette.py` (update subscribe route)
- Modify: `src/remora/ui/view.py` (accept DB data instead of projector snapshot)
- Test: `tests/test_service_api.py` (update)

**Step 1: Write the failing test**

```python
# tests/test_service_db_reader.py
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

def test_service_reads_from_db(db, tmp_path):
    service = RemoraService.from_db(db_path=str(tmp_path / "test.db"))
    snapshot = service.read_state()
    assert len(snapshot["nodes"]) == 1
    assert snapshot["nodes"][0]["name"] == "foo"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_service_db_reader.py -v`
Expected: FAIL — `from_db` and `read_state` don't exist

**Step 3: Rewrite RemoraService**

```python
# src/remora/service/api.py
"""Service layer entry point for Remora — DB-backed."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from remora.db.reader import DBReader
from remora.service.datastar import render_patch, render_shell
from remora.ui.view import render_dashboard


class RemoraService:
    """Framework-agnostic Remora service API backed by RemoraDB."""

    def __init__(self, *, reader: DBReader) -> None:
        self._reader = reader
        self._last_seq: int = -1

    @classmethod
    def from_db(cls, db_path: str = ".remora/indexer.db") -> "RemoraService":
        return cls(reader=DBReader(db_path=db_path))

    def read_state(self) -> dict[str, Any]:
        """Read the full UI state from the database."""
        nodes = self._reader.read_all_nodes()
        events = self._reader.read_recent_events(limit=200)
        proposals = self._reader.read_all_pending_proposals()
        cursor_focus = self._reader.read_cursor_focus()

        # Compute agent states from nodes
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

    def index_html(self) -> str:
        state = self.read_state()
        return render_shell(render_dashboard(state))

    async def subscribe_stream(self) -> AsyncIterator[str]:
        """SSE stream that pushes HTML patches when DB changes."""
        # Initial push
        state = await asyncio.to_thread(self.read_state)
        yield render_patch(state)

        # Poll for changes
        while True:
            await asyncio.sleep(0.5)
            try:
                seq = await asyncio.to_thread(self._reader.read_change_seq)
                if seq != self._last_seq:
                    self._last_seq = seq
                    state = await asyncio.to_thread(self.read_state)
                    yield render_patch(state)
            except Exception:
                await asyncio.sleep(2.0)

    async def post_command(self, command_type: str, agent_id: str | None, payload: dict) -> int:
        """Write a command to the DB queue."""
        return await asyncio.to_thread(
            self._reader.push_command, command_type, agent_id, payload
        )

    def close(self) -> None:
        self._reader.close()


__all__ = ["RemoraService"]
```

**NOTE:** This is a breaking change to the service API. The old `create_default()`, EventBus, EventStore, etc. are all removed. Callers must be updated. The `render_dashboard` function in `view.py` will need to accept the new state shape (it currently expects `events` as pre-normalized dicts, `blocked` list, `agent_states`, `progress`, `results`, `recent_targets`). That view function will need updating too, but that's a separate step.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_service_db_reader.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/remora/service/api.py tests/test_service_db_reader.py
git commit -m "refactor(service): rewrite RemoraService to use DBReader, remove EventBus/EventStore deps"
```

---

### Task 6: Update render_dashboard to accept DB state shape

The `render_dashboard` function currently expects the UiStateProjector's snapshot shape. Update it to accept the new DB-backed state shape.

**Files:**
- Modify: `src/remora/ui/view.py:38-116`
- Test: `tests/ui/test_view.py` (update)

**Step 1: Write the failing test**

```python
# tests/ui/test_view_db_state.py
from remora.ui.view import render_dashboard

def test_render_dashboard_with_db_state():
    state = {
        "nodes": [{"remora_id": "n1", "name": "foo", "node_type": "function", "status": "active"}],
        "events": [{"event_id": "e1", "event_type": "TestEvent", "timestamp": 1.0, "agent_id": "n1"}],
        "proposals": [],
        "cursor_focus": None,
        "agent_states": {"n1": {"state": "active", "name": "foo"}},
    }
    html = render_dashboard(state)
    assert "remora-root" in html
    assert "foo" in html
```

**Step 2: Run test to verify it fails (or passes — the shape may be compatible enough)**

Run: `pytest tests/ui/test_view_db_state.py -v`

If it passes already, the existing view code is flexible enough. If it fails, update `render_dashboard` to handle missing keys (`blocked`, `progress`, `results`, `recent_targets`) with defaults.

**Step 3: Add defensive defaults to render_dashboard**

In `src/remora/ui/view.py`, update `render_dashboard` to handle both old and new state shapes:

```python
def render_dashboard(state: dict[str, Any], *, bundle_default: str = "") -> str:
    events = state.get("events", [])
    blocked = state.get("blocked", [])
    agent_states = state.get("agent_states", {})
    progress = state.get("progress", {"total": 0, "completed": 0, "failed": 0})
    results = state.get("results", [])
    recent_targets = state.get("recent_targets", [])

    # Compute progress from agent_states if not provided
    if not progress.get("total") and agent_states:
        total = len(agent_states)
        completed = sum(1 for a in agent_states.values() if a.get("state") == "completed")
        failed = sum(1 for a in agent_states.values() if a.get("state") == "failed")
        progress = {"total": total, "completed": completed, "failed": failed}

    # ... rest of function unchanged
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/ui/test_view_db_state.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/remora/ui/view.py tests/ui/test_view_db_state.py
git commit -m "fix(ui): make render_dashboard accept DB state shape with defensive defaults"
```

---

### Task 7: Update Starlette adapter to use new RemoraService

**Files:**
- Modify: `src/remora/adapters/starlette.py`

**Step 1: Update create_app to use RemoraService.from_db**

```python
def create_app(service: RemoraService | None = None, db_path: str = ".remora/indexer.db") -> Starlette:
    service = service or RemoraService.from_db(db_path=db_path)

    async def index(_request: Request) -> HTMLResponse:
        return HTMLResponse(service.index_html())

    async def subscribe(_request: Request) -> DatastarResponse:
        return DatastarResponse(service.subscribe_stream())

    async def post_command(request: Request) -> JSONResponse:
        body = await request.json()
        command_type = body.get("command_type", "")
        agent_id = body.get("agent_id")
        payload = body.get("payload", {})
        if not command_type:
            return JSONResponse({"error": "command_type required"}, status_code=400)
        cmd_id = await service.post_command(command_type, agent_id, payload)
        return JSONResponse({"status": "queued", "command_id": cmd_id})

    routes = [
        Route("/", index),
        Route("/subscribe", subscribe),
        Route("/command", post_command, methods=["POST"]),
    ]

    return Starlette(routes=routes)
```

**NOTE:** This removes the old routes (`/events`, `/replay`, `/input`, `/config`, `/snapshot`, `/swarm/*`). If any of these are still needed, they can be added back as thin DB reads later. The core CQRS pattern is: GET /subscribe (SSE) + POST /command.

**Step 2: Run existing tests**

Run: `pytest tests/ -v -k starlette`
Expected: Some tests may fail if they depend on old RemoraService API. Update them.

**Step 3: Commit**

```bash
git add src/remora/adapters/starlette.py
git commit -m "refactor(starlette): simplify adapter to CQRS pattern (GET /subscribe + POST /command)"
```

---

### Task 8: Add command processor to LSP server

The LSP server needs to poll the command_queue table and process commands. This closes the loop: web UIs write commands to the DB, LSP server reads and acts on them.

**Files:**
- Modify: `src/remora/lsp/server.py` (add command polling loop)
- Create: `src/remora/lsp/command_processor.py`
- Test: `tests/lsp/test_command_processor.py`

**Step 1: Write the failing test**

```python
# tests/lsp/test_command_processor.py
import pytest
from remora.lsp.db import RemoraDB
from remora.lsp.command_processor import CommandProcessor

@pytest.fixture
def db(tmp_path):
    return RemoraDB(db_path=str(tmp_path / "test.db"))

@pytest.fixture
def processor(db):
    return CommandProcessor(db)

def test_poll_returns_pending_commands(db, processor):
    db.push_command("chat", "agent1", {"message": "hello"})
    commands = db.poll_commands()
    assert len(commands) == 1
    assert commands[0]["command_type"] == "chat"

def test_mark_command_done(db, processor):
    cmd_id = db.push_command("chat", "agent1", {"message": "hello"})
    db.mark_command_done(cmd_id)
    commands = db.poll_commands()
    assert len(commands) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lsp/test_command_processor.py -v`
Expected: FAIL — `command_processor` module doesn't exist

**Step 3: Create CommandProcessor**

```python
# src/remora/lsp/command_processor.py
"""Polls command_queue and dispatches to LSP server handlers."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.lsp.db import RemoraDB

logger = logging.getLogger("remora.lsp.commands")


class CommandProcessor:
    """Polls the command_queue table and processes commands."""

    def __init__(self, db: "RemoraDB") -> None:
        self.db = db
        self._handlers: dict[str, any] = {}

    def register(self, command_type: str, handler) -> None:
        """Register a handler for a command type."""
        self._handlers[command_type] = handler

    async def poll_loop(self, interval: float = 0.5) -> None:
        """Run the command polling loop."""
        while True:
            try:
                commands = self.db.poll_commands(limit=10)
                for cmd in commands:
                    await self._process(cmd)
            except Exception:
                logger.debug("Command poll error", exc_info=True)
            await asyncio.sleep(interval)

    async def _process(self, cmd: dict) -> None:
        """Process a single command."""
        cmd_id = cmd["id"]
        cmd_type = cmd["command_type"]
        agent_id = cmd.get("agent_id")
        payload = json.loads(cmd["payload"]) if isinstance(cmd["payload"], str) else cmd["payload"]

        handler = self._handlers.get(cmd_type)
        if handler:
            try:
                await handler(agent_id=agent_id, payload=payload)
            except Exception:
                logger.exception("Error processing command %s (id=%d)", cmd_type, cmd_id)
        else:
            logger.warning("No handler for command type: %s", cmd_type)

        self.db.mark_command_done(cmd_id)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lsp/test_command_processor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/remora/lsp/command_processor.py tests/lsp/test_command_processor.py
git commit -m "feat(lsp): add CommandProcessor for polling command_queue table"
```

---

### Task 9: Wire CommandProcessor into RemoraLanguageServer

**Files:**
- Modify: `src/remora/lsp/server.py:22-39` (add CommandProcessor init)

**Step 1: Add CommandProcessor to server init**

In `RemoraLanguageServer.__init__`, add:

```python
from remora.lsp.command_processor import CommandProcessor

# In __init__:
self.command_processor = CommandProcessor(self.db)
self.command_processor.register("chat", self._handle_chat_command)
self.command_processor.register("approve_proposal", self._handle_approve_command)
self.command_processor.register("reject_proposal", self._handle_reject_command)
```

And add the handler methods:

```python
async def _handle_chat_command(self, agent_id: str, payload: dict) -> None:
    """Handle a chat command from the web UI."""
    message = payload.get("message", "")
    if not message or not agent_id:
        return
    from remora.lsp.models import HumanChatEvent
    event = HumanChatEvent(
        to_agent=agent_id,
        message=message,
        correlation_id=self.generate_correlation_id(),
        timestamp=0,  # emit_event will set it
    )
    await self.emit_event(event)

async def _handle_approve_command(self, agent_id: str | None, payload: dict) -> None:
    """Handle a proposal approval from the web UI."""
    proposal_id = payload.get("proposal_id")
    if not proposal_id:
        return
    # Reuse existing approval logic from handlers/commands.py
    from remora.lsp.handlers.commands import _apply_proposal
    await _apply_proposal(self, proposal_id)

async def _handle_reject_command(self, agent_id: str | None, payload: dict) -> None:
    """Handle a proposal rejection from the web UI."""
    proposal_id = payload.get("proposal_id")
    if not proposal_id:
        return
    from remora.lsp.handlers.commands import _reject_proposal
    await _reject_proposal(self, proposal_id, feedback="Rejected from web UI")
```

**Step 2: Start the command poll loop when server starts**

Add to server startup (in the `initialized` handler or similar):

```python
asyncio.create_task(self.command_processor.poll_loop())
```

**Step 3: Run existing LSP tests**

Run: `pytest tests/lsp/ -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/remora/lsp/server.py
git commit -m "feat(lsp): wire CommandProcessor into RemoraLanguageServer"
```

---

### Task 10: Clean up — remove dead code

Remove the modules that are no longer needed.

**Files:**
- Delete: `src/remora/core/event_bus.py` — BUT check if anything still imports it
- Delete: `src/remora/core/event_store.py` — BUT check if anything still imports it
- Delete: `src/remora/core/swarm_state.py` — BUT check if anything still imports it
- Delete: `src/remora/ui/projector.py` — BUT check if anything still imports it

**Step 1: Search for all imports of the dead modules**

```bash
rg "from remora.core.event_bus import" --type py
rg "from remora.core.event_store import" --type py
rg "from remora.core.swarm_state import" --type py
rg "from remora.ui.projector import" --type py
```

**Step 2: For each import found, update the importing module**

- If it's in the old `RemoraService`, it's already been rewritten (Task 5)
- If it's in tests, update the tests
- If it's in `server.py` (EventStore/SwarmState are passed to LSP server), remove those params

**Step 3: Update RemoraLanguageServer.__init__**

Remove `event_store`, `subscriptions`, `swarm_state` parameters since RemoraDB handles everything:

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
        self.command_processor = CommandProcessor(self.db)
        # ... register command handlers
```

**Step 4: Delete the dead modules**

```bash
git rm src/remora/core/event_bus.py
git rm src/remora/core/event_store.py
git rm src/remora/core/swarm_state.py
git rm src/remora/ui/projector.py
```

**Step 5: Run full test suite**

Run: `pytest -v`
Fix any remaining import errors.

**Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove EventBus, EventStore, SwarmState, UiStateProjector — DB is source of truth"
```

---

## Deferred / Follow-up Tasks

These are intentionally NOT part of the initial implementation:

1. **Datastar @post() for graph viewer commands** (Task 4) — replace raw `fetch()` with Datastar attributes in sidebar.py/shell.py
2. **Datastar @get() for sidebar loading** — replace raw `fetch('/agent/...')` with Datastar-driven sidebar morphing
3. **Targeted patch_elements** — instead of re-rendering the entire dashboard, send targeted patches for specific `#id` elements
4. **Migrate SubscriptionRegistry** — move subscription matching logic to use the new `subscriptions` table in RemoraDB
5. **Merge service dashboard and graph viewer** into a single Starlette app with multiple views
6. **LSP server as HTTP host** (Approach B evolution) — run the Starlette web server as a sidecar within the LSP server process

## Migration Path

The implementation order above is designed so each task can be committed and tested independently:

1. Tasks 1-2: Foundation (DB schema + reader) — no breaking changes
2. Task 3: Graph viewer migration — internal refactor, same external behavior
3. Task 5-7: Service layer rewrite — breaking change to service API
4. Tasks 8-9: Command processor — new capability
5. Task 10: Cleanup — remove dead code

Tasks 1-3 can be done without touching the service layer at all. This means the graph viewer gets the benefit of the unified DB immediately, while the service dashboard migration can happen in a second pass.
