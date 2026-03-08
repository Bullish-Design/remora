# Web UI / Graph Viewer — Refactoring Guide

**Area:** `remora_demo/web/graph/`
**Priority:** 1 (runtime SQL errors on every query — complete failure)
**Files:** `remora_demo/web/graph/state.py`, `tests/test_bridge.py`

---

## Table of Contents

1. [Two-Database Architecture](#1-two-database-architecture)
2. [Bug: state.py Opens Wrong Database](#2-bug-statepy-opens-wrong-database)
3. [Bug: Stale Column Names](#3-bug-stale-column-names)
4. [Fix: GraphState with Two DB Connections](#4-fix-graphstate-with-two-db-connections)
5. [Bug: test_bridge.py Stale Schema](#5-bug-testbridgepy-stale-schema)
6. [Fix: Update test_bridge.py Schema](#6-fix-update-testbridgepy-schema)
7. [Acceptance Criteria](#7-acceptance-criteria)

---

## 1. Two-Database Architecture

The production Remora LSP server uses **two separate SQLite databases**:

### Database 1: EventStore — `.remora/events/events.db`

Created and owned by `remora.core.store.event_store.EventStore`. Tables:

```sql
events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    graph_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT,          -- JSON blob
    timestamp REAL,
    created_at REAL,
    from_agent TEXT,       -- source agent (was "agent_id" — CHANGED)
    to_agent TEXT,         -- target agent
    correlation_id TEXT,
    tags TEXT              -- JSON array
);

nodes (
    node_id TEXT PRIMARY KEY,    -- canonical PK (was "id" — CHANGED)
    node_type TEXT,
    name TEXT,
    full_name TEXT,
    file_path TEXT,
    start_line INTEGER,
    end_line INTEGER,
    source_code TEXT,
    source_hash TEXT,
    parent_id TEXT,
    status TEXT DEFAULT 'idle',
    -- ... additional columns
);
```

### Database 2: RemoraDB — `.remora/indexer.db`

Created and owned by `remora.lsp.db.RemoraDB` (standalone mode — `RemoraLanguageServer.__init__` calls `RemoraDB()` with no args). Tables:

```sql
edges (from_id TEXT, to_id TEXT, edge_type TEXT, PRIMARY KEY(from_id, to_id, edge_type));
activation_chain (correlation_id TEXT, agent_id TEXT, depth INTEGER, timestamp REAL, ...);
proposals (proposal_id TEXT PRIMARY KEY, agent_id TEXT, old_source TEXT, new_source TEXT, diff TEXT, status TEXT, created_at REAL, file_path TEXT);
cursor_focus (id INTEGER PRIMARY KEY CHECK (id = 1), agent_id TEXT, file_path TEXT, line INTEGER, timestamp REAL);
command_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, command_type TEXT, agent_id TEXT, payload JSON, status TEXT, created_at REAL, processed_at REAL);
```

### GraphState must connect to BOTH

`GraphState` currently opens only `.remora/indexer.db`. Queries against `nodes` and `events` tables fail at runtime with `sqlite3.OperationalError: no such table`.

---

## 2. Bug: state.py Opens Wrong Database

### Current code (WRONG)

```python
class GraphState:
    def __init__(self, db_path: str = ".remora/indexer.db") -> None:
        self.db_path = Path(db_path)   # Only opens indexer.db (RemoraDB)
```

Methods that query `nodes` or `events`:

| Method | Table queried | In which DB? | Actual DB opened |
|--------|---------------|--------------|-----------------|
| `read_snapshot()` | `nodes` | EventStore (events.db) | indexer.db ❌ |
| `read_node()` | `nodes` | EventStore (events.db) | indexer.db ❌ |
| `read_events_for_agent()` | `events` | EventStore (events.db) | indexer.db ❌ |
| `read_recent_events()` | `events` | EventStore (events.db) | indexer.db ❌ |
| `read_snapshot()` | `edges` | RemoraDB (indexer.db) | indexer.db ✅ |
| `read_snapshot()` | `cursor_focus` | RemoraDB (indexer.db) | indexer.db ✅ |
| `read_proposals_for_agent()` | `proposals` | RemoraDB (indexer.db) | indexer.db ✅ |
| `push_command()` | `command_queue` | RemoraDB (indexer.db) | indexer.db ✅ |

---

## 3. Bug: Stale Column Names

The `events` and `nodes` tables were renamed during the architecture refactor. `state.py` uses the old names:

### events table — stale names

| Old name (stale — DO NOT USE) | New name | Location in query |
|------------------------------|----------|-------------------|
| `event_id` | `id` | SELECT, WHERE |
| `agent_id` | `from_agent` / `to_agent` | SELECT, WHERE |

### nodes table — stale names

| Old name (stale — DO NOT USE) | New name | Location in query |
|------------------------------|----------|-------------------|
| `id` | `node_id` | WHERE, PRIMARY KEY |

### Affected queries in state.py

**`read_node()` (line 68):**
```python
# WRONG:
cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))

# CORRECT:
cursor.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
```

**`read_events_for_agent()` (lines 81-89):**
```python
# WRONG:
cursor.execute("""
    SELECT event_id, event_type, timestamp, correlation_id, agent_id, payload
    FROM events
    WHERE agent_id = ? OR json_extract(payload, '$.to_agent') = ?
    ORDER BY timestamp DESC LIMIT ?
    """, (agent_id, agent_id, limit))

# CORRECT:
cursor.execute("""
    SELECT id, event_type, timestamp, correlation_id, from_agent, to_agent, payload
    FROM events
    WHERE from_agent = ? OR to_agent = ?
    ORDER BY timestamp DESC LIMIT ?
    """, (agent_id, agent_id, limit))
```

**`read_recent_events()` (lines 137-147):**
```python
# WRONG:
cursor.execute("""
    SELECT event_id, event_type, timestamp, correlation_id, agent_id,
           json_extract(payload, '$.message') as message,
           json_extract(payload, '$.content') as content
    FROM events
    ORDER BY timestamp DESC LIMIT ?
    """, (limit,))

# CORRECT:
cursor.execute("""
    SELECT id, event_type, timestamp, correlation_id, from_agent, to_agent,
           json_extract(payload, '$.message') as message,
           json_extract(payload, '$.content') as content
    FROM events
    ORDER BY timestamp DESC LIMIT ?
    """, (limit,))
```

**`read_snapshot()` `id` → `remora_id` rename (lines 52-54):**

The rename was designed to avoid collision with an `id` column. Since `nodes` uses `node_id` as the PK (no `id` column), the rename does nothing. Remove it:

```python
# WRONG (unnecessary — nodes has node_id, not id):
for n in nodes:
    if "id" in n:
        n["remora_id"] = n.pop("id")

# CORRECT: remove the rename block entirely
# The node dict has node_id as the canonical identifier
```

---

## 4. Fix: GraphState with Two DB Connections

Rewrite `GraphState` to open both databases:

```python
class GraphState:
    """Reads Remora SQLite DBs and yields snapshots on change.

    Uses two connections:
    - db_path       (.remora/indexer.db):       edges, cursor_focus, proposals, command_queue
    - events_db_path (.remora/events/events.db): events, nodes
    """

    def __init__(
        self,
        db_path: str = ".remora/indexer.db",
        events_db_path: str = ".remora/events/events.db",
    ) -> None:
        self.db_path = Path(db_path)
        self.events_db_path = Path(events_db_path)
        self._conn: sqlite3.Connection | None = None
        self._events_conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        """RemoraDB connection (indexer.db): edges, cursor, proposals, commands."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA query_only=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _get_events_conn(self) -> sqlite3.Connection:
        """EventStore connection (events.db): events, nodes."""
        if self._events_conn is None:
            self._events_conn = sqlite3.connect(
                str(self.events_db_path), check_same_thread=False
            )
            self._events_conn.execute("PRAGMA journal_mode=WAL")
            self._events_conn.execute("PRAGMA query_only=ON")
            self._events_conn.row_factory = sqlite3.Row
        return self._events_conn

    def read_snapshot(self) -> GraphSnapshot:
        """Read nodes (EventStore) + edges + cursor_focus (RemoraDB)."""
        # nodes from EventStore
        events_conn = self._get_events_conn()
        cursor = events_conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE status != 'orphaned'")
        nodes = [dict(row) for row in cursor.fetchall()]
        # node_id is already the canonical identifier — no renaming needed

        # edges from RemoraDB
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM edges")
        edges = [dict(row) for row in cursor.fetchall()]

        # cursor_focus from RemoraDB
        cursor.execute(
            "SELECT agent_id, file_path, line, timestamp FROM cursor_focus WHERE id = 1"
        )
        row = cursor.fetchone()
        cursor_focus = dict(row) if row else None

        return GraphSnapshot(nodes=nodes, edges=edges, cursor_focus=cursor_focus, timestamp=time.time())

    def read_node(self, node_id: str) -> dict | None:
        """Read a single node by node_id from EventStore."""
        conn = self._get_events_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def read_events_for_agent(self, agent_id: str, limit: int = 20) -> list[dict]:
        """Read recent events for a specific agent from EventStore."""
        conn = self._get_events_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, event_type, timestamp, correlation_id, from_agent, to_agent, payload
            FROM events
            WHERE from_agent = ? OR to_agent = ?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (agent_id, agent_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def read_recent_events(self, limit: int = 30) -> list[dict]:
        """Read the most recent events across all agents from EventStore."""
        conn = self._get_events_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, event_type, timestamp, correlation_id, from_agent, to_agent,
                   json_extract(payload, '$.message') as message,
                   json_extract(payload, '$.content') as content
            FROM events
            ORDER BY timestamp DESC LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
        if self._events_conn:
            self._events_conn.close()
            self._events_conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
```

The `read_proposals_for_agent()`, `read_edges_for_node()`, and `push_command()` methods are unchanged — they already use `self._get_conn()` (RemoraDB) which is correct.

---

## 5. Bug: test_bridge.py Stale Schema

`tests/test_bridge.py`'s `_create_test_db()` creates a single database with the OLD schema:

```python
# STALE (wrong column names, single DB):
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,      -- wrong: should be node_id
    ...
);
CREATE TABLE events (
    event_id TEXT,            -- wrong: should be id INTEGER AUTOINCREMENT
    agent_id TEXT,            -- wrong: should be from_agent + to_agent
    ...
);
```

These tests pass but only verify behavior against a database schema that never matches production. All node/event queries against a real production DB would raise `sqlite3.OperationalError`.

---

## 6. Fix: Update test_bridge.py Schema

Split the test helper into two helpers matching the two production databases:

```python
def _create_test_indexer_db(path: str) -> sqlite3.Connection:
    """RemoraDB schema (indexer.db): edges, cursor_focus, proposals, command_queue."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS edges (
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            PRIMARY KEY (from_id, to_id, edge_type)
        );
        CREATE TABLE IF NOT EXISTS cursor_focus (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            agent_id TEXT,
            file_path TEXT,
            line INTEGER,
            timestamp REAL
        );
        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            old_source TEXT NOT NULL,
            new_source TEXT NOT NULL,
            diff TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at REAL NOT NULL,
            file_path TEXT
        );
        CREATE TABLE IF NOT EXISTS command_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_type TEXT NOT NULL,
            agent_id TEXT,
            payload JSON NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at REAL NOT NULL,
            processed_at REAL
        );
    """)
    conn.commit()
    return conn


def _create_test_events_db(path: str) -> sqlite3.Connection:
    """EventStore schema (events.db): events, nodes."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            graph_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT,
            timestamp REAL,
            created_at REAL,
            from_agent TEXT,
            to_agent TEXT,
            correlation_id TEXT,
            tags TEXT
        );
        CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY,
            node_type TEXT,
            name TEXT,
            full_name TEXT,
            file_path TEXT,
            start_line INTEGER,
            end_line INTEGER,
            source_code TEXT,
            source_hash TEXT,
            parent_id TEXT,
            status TEXT DEFAULT 'idle'
        );
    """)
    conn.commit()
    return conn
```

Update all `GraphState` instantiations in tests to pass both paths:

```python
def test_read_empty_snapshot(self, tmp_path: Path) -> None:
    indexer_path = str(tmp_path / "indexer.db")
    events_path = str(tmp_path / "events.db")
    _create_test_indexer_db(indexer_path).close()
    _create_test_events_db(events_path).close()

    state = GraphState(db_path=indexer_path, events_db_path=events_path)
    snapshot = state.read_snapshot()
    assert snapshot.nodes == []
    assert snapshot.edges == []
    assert snapshot.cursor_focus is None
    state.close()

def test_read_snapshot_with_nodes(self, tmp_path: Path) -> None:
    indexer_path = str(tmp_path / "indexer.db")
    events_path = str(tmp_path / "events.db")
    _create_test_indexer_db(indexer_path).close()
    conn = _create_test_events_db(events_path)
    conn.execute(
        "INSERT INTO nodes (node_id, name, node_type, status) VALUES ('a', 'func_a', 'function', 'idle')"
    )
    conn.commit()
    conn.close()

    state = GraphState(db_path=indexer_path, events_db_path=events_path)
    snapshot = state.read_snapshot()
    assert len(snapshot.nodes) == 1
    assert snapshot.nodes[0]["node_id"] == "a"  # was "remora_id" in old test
    state.close()
```

---

## 7. Acceptance Criteria

- [ ] `GraphState` constructor takes `events_db_path` parameter defaulting to `.remora/events/events.db`
- [ ] `read_snapshot()` reads nodes from EventStore and edges/cursor from RemoraDB
- [ ] `read_node()` queries `nodes WHERE node_id = ?` from EventStore
- [ ] `read_events_for_agent()` uses `from_agent`/`to_agent`, returns `id` not `event_id`
- [ ] `read_recent_events()` uses `from_agent`/`to_agent`, returns `id` not `event_id`
- [ ] No `sqlite3.OperationalError` at runtime when both DB files exist
- [ ] `test_bridge.py` creates production-matching schema for both databases
- [ ] All `TestGraphState` tests pass with updated schema
- [ ] Full test suite: `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`

## Verification

```bash
# Check state.py imports compile:
devenv shell -- python -c "from remora_demo.web.graph.state import GraphState; print('OK')"

# Run bridge tests:
devenv shell -- python -m pytest tests/test_bridge.py -v
```

---

## Appendix: Potential Future Simplification — Single EventStore DB

> **Not required now.** Documented here for future reference.

### The edges table is dead weight in the LSP server

Investigation revealed that `edges` is the only RemoraDB table the web UI reads that isn't also needed by production LSP functionality:

- `proposals` → read by LSP server (`did_open` loads them as diagnostics)
- `cursor_focus` → read by LSP server (`RemoraDB.get_cursor_focus()`)
- `command_queue` → written/read by LSP server
- `edges` → **populated by LSP server but never read by LSP server in practice**

`LazyGraph.get_parent()` and `get_callers()` are the only methods that read the edges table, and they are **never called from any production code** — only defined. The single live call to `LazyGraph` from outside `graph.py` is `ls.graph.invalidate(uri)`, which only touches the in-memory rustworkx graph via EventStore, not the edges table.

The full dead-code path: `update_edges()` (called in `documents.py` + `background_scanner.py`) → `edges` table → `LazyGraph._get_neighborhood()` → `get_parent()`/`get_callers()` (never called externally).

**The web UI is the only actual consumer of the edges table.**

### What a cleanup would look like

If this were addressed, the change set would be:

| File | Change |
|------|--------|
| `remora_demo/web/graph/state.py` | Derive edges from `nodes.parent_id` in EventStore; derive cursor from latest `CursorFocusEvent`; single DB connection |
| `src/remora/lsp/handlers/documents.py` | Remove two `await ls.db.update_edges(new_nodes)` calls |
| `src/remora/lsp/background_scanner.py` | Remove `update_edges()` call + timeout block |
| `src/remora/lsp/db.py` | Remove `edges` table from `_init_schema()`; remove `update_edges()` method |
| `src/remora/lsp/graph.py` | Remove `_edges_conn`, `_get_neighborhood()`, `_get_edges_for_nodes()`, `ensure_loaded()`, `get_parent()`, `get_callers()`; keep only `invalidate()` |
| `tests/test_bridge.py` | Remove `edges` table from test schema |

Deriving edges from `nodes.parent_id` in EventStore (for web UI `read_snapshot()`):

```python
# Instead of querying the edges table:
cursor.execute("""
    SELECT parent_id as from_id, node_id as to_id, 'parent_of' as edge_type
    FROM nodes
    WHERE parent_id IS NOT NULL AND status != 'orphaned'
""")
edges = [dict(row) for row in cursor.fetchall()]
```

Deriving cursor focus from EventStore (for web UI `read_snapshot()`):

```python
cursor.execute("""
    SELECT
        json_extract(payload, '$.focused_agent_id') as agent_id,
        json_extract(payload, '$.file_path') as file_path,
        json_extract(payload, '$.line') as line,
        timestamp
    FROM events
    WHERE event_type = 'CursorFocusEvent'
    ORDER BY timestamp DESC LIMIT 1
""")
```

After this, `GraphState` would need only a single connection to `.remora/events/events.db` for all read data, plus a separate write connection to `.remora/indexer.db` only for `push_command()`.
