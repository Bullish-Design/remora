# Web UI / Graph Viewer — Refactoring Guide

**Area:** `remora_demo/web/graph/`
**Priority:** 2 (after Agent Chat)

---

## Overview

The graph viewer is a Stario-based web app that reads the shared SQLite DB and renders a live force-directed graph of the agent swarm. It polls for changes via `DBBridge`, renders with SVG, and uses Datastar for DOM patching.

The app is architecturally clean — Stario handler pattern, closure-based DI, thin views — but has critical schema mismatches with the current EventStore that will cause runtime SQL errors.

---

## DB Schema Mismatches (Critical — Active Runtime Bugs)

`GraphState` reads from both `RemoraDB` tables and `EventStore` tables in the same shared SQLite file:
- **EventStore** (`src/remora/core/store/event_store_schema.py`): creates `nodes`, `events`, `subscriptions`
- **RemoraDB** (`src/remora/lsp/db.py`): creates `edges`, `proposals`, `cursor_focus`, `command_queue`, `activation_chain`

`state.py` was written against an older event schema and has column name mismatches that will cause `sqlite3.OperationalError` at runtime.

### Bug 1: `events` Table — Wrong Column Names

`state.py` queries `read_events_for_agent` and `read_recent_events` using:
```sql
SELECT event_id, event_type, timestamp, correlation_id, agent_id, payload FROM events
WHERE agent_id = ? OR json_extract(payload, '$.to_agent') = ?
```

**Actual EventStore `events` schema:**
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,   -- NOT `event_id`
graph_id TEXT, event_type TEXT, payload TEXT, timestamp REAL, created_at REAL,
from_agent TEXT, to_agent TEXT,          -- NOT `agent_id`
correlation_id TEXT, tags TEXT
```

The columns `event_id` and `agent_id` **do not exist**. Querying them raises `sqlite3.OperationalError: no such column: event_id`.

**Fix — update `read_events_for_agent`:**
```python
cursor.execute(
    """
    SELECT id AS event_id, event_type, timestamp, correlation_id,
           from_agent AS agent_id, payload
    FROM events
    WHERE from_agent = ? OR to_agent = ?
    ORDER BY timestamp DESC LIMIT ?
    """,
    (agent_id, agent_id, limit),
)
```

**Fix — update `read_recent_events`:**
```python
cursor.execute(
    """
    SELECT id AS event_id, event_type, timestamp, correlation_id,
           from_agent AS agent_id,
           json_extract(payload, '$.message') as message,
           json_extract(payload, '$.content') as content
    FROM events
    ORDER BY timestamp DESC LIMIT ?
    """,
    (limit,),
)
```

### Bug 2: `nodes` Table — Primary Key is `node_id`, not `id`

`state.py` does:
```python
cursor.execute("SELECT * FROM nodes WHERE status != 'orphaned'")
nodes = [dict(row) for row in cursor.fetchall()]
for n in nodes:
    if "id" in n:
        n["remora_id"] = n.pop("id")  # ← NEVER executes — there is no `id` column
```

**Actual EventStore `nodes` schema:**
```sql
node_id TEXT PRIMARY KEY,   -- NOT `id`
node_type TEXT, name TEXT, full_name TEXT, file_path TEXT,
start_line INTEGER, end_line INTEGER, source_code TEXT, source_hash TEXT,
parent_id TEXT, status TEXT DEFAULT 'idle', extension_name TEXT, ...
```

The primary key column is `node_id`. The `remora_id` rename code is dead — `n["id"]` never exists. Any downstream code relying on `remora_id` would receive an incorrect/missing value.

Also: `'orphaned'` is not a documented status value in the EventStore schema (known value: `'idle'`). Verify whether 'orphaned' is emitted by `AgentNode` state transitions, or remove the filter.

**Fix — update `read_snapshot` nodes section:**
```python
cursor.execute("SELECT * FROM nodes")  # or add actual status filter if needed
nodes = [dict(row) for row in cursor.fetchall()]
for n in nodes:
    if "node_id" in n:
        n["remora_id"] = n.pop("node_id")  # Alias for downstream SVG rendering code
```

**Fix — update `read_node`:**
```python
cursor.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
```

### Understanding the Two-DB Architecture

Update `state.py` module docstring:
```python
"""Graph state reader — reads the shared SQLite DB.

The DB at .remora/indexer.db is populated by two components writing to the same file:
  - EventStore (src/remora/core/store/event_store_schema.py):
      Tables: nodes (PK=node_id), events (PK=id, cols: from_agent/to_agent), subscriptions
  - RemoraDB (src/remora/lsp/db.py):
      Tables: edges, proposals, cursor_focus, command_queue, activation_chain

Both use WAL mode. This viewer opens the DB read-only (PRAGMA query_only=ON).
The LSP server must be running with enable_event_store=True to populate all tables.
"""
```

---

## Private API Access in `DBBridge` (Medium)

`bridge.py:_read_fingerprints()` calls `self.state._get_conn()` directly:

```python
def _read_fingerprints(self) -> dict[str, str]:
    conn = self.state._get_conn()  # ← private method
```

This is a layering violation: the bridge reaches into `GraphState`'s internals for a connection, then runs raw queries on it. If `GraphState` ever changes its connection strategy, the bridge breaks silently.

**Fix:** Move fingerprint logic to a public `GraphState.fingerprint()` method:

```python
# In GraphState (state.py):
def fingerprint(self) -> dict[str, str]:
    """Return lightweight change-detection fingerprints for all watched tables."""
    conn = self._get_conn()
    # ... existing _read_fingerprints logic moved here ...

# In DBBridge._poll_once() (bridge.py):
fp = await asyncio.to_thread(self.state.fingerprint)
```

---

## `push_command` Dual-Connection Anti-Pattern (Low)

`GraphState.push_command()` opens a second, separate SQLite connection for writes:

```python
def push_command(self, command_type, agent_id, payload):
    conn = sqlite3.connect(str(self.db_path), ...)  # NEW connection per call
    ...
    conn.close()
    return cmd_id
```

Safe in WAL mode but wasteful. Since `RemoraDB.push_command()` already implements this correctly, the cleanest fix is to pass the `RemoraDB` instance to `GraphState`:

```python
class GraphState:
    def __init__(self, db_path: str = ".remora/indexer.db", db: RemoraDB | None = None) -> None:
        self.db_path = Path(db_path)
        self._db = db  # Optional: if provided, use for writes

    def push_command(self, command_type, agent_id, payload):
        if self._db:
            return self._db.push_command(command_type, agent_id, payload)
        # fallback: open a separate write connection (existing behavior)
```

---

## `proposals` Table — `file_path` Migration (Low)

`RemoraDB.store_proposal()` accepts `file_path` (added in a migration). `GraphState.read_proposals_for_agent()` does `SELECT *` — if the migration hasn't run on an older DB, the column may be absent. Document this dependency.

---

## `app.py` — JSON Parsing Guard (Low)

```python
payload = json.loads(signals.payload) if signals.payload else {}
```

If `signals.payload` is not valid JSON, this raises `json.JSONDecodeError` (unhandled → 500). Add:
```python
try:
    payload = json.loads(signals.payload) if signals.payload else {}
except json.JSONDecodeError:
    w.json({"error": "payload must be valid JSON"}, status=400)
    return
```

---

## Test Schema Also Stale (Critical — Tests Don't Catch Production Schema)

`tests/test_bridge.py`'s `_create_test_db()` creates a schema matching `state.py`'s old queries:
```python
CREATE TABLE nodes (id TEXT PRIMARY KEY, ...)        -- OLD: should be node_id
CREATE TABLE events (event_id TEXT, agent_id TEXT, ...) -- OLD: should be id + from_agent/to_agent
```

The tests pass because they use the old schema matching `state.py`'s old queries. **Neither matches the production EventStore schema.** The tests provide false confidence — they verify internal consistency of an already-stale API.

When fixing `state.py`, **update `tests/test_bridge.py` simultaneously** to use the current EventStore schema:
```python
def _create_test_db(path: str) -> sqlite3.Connection:
    """Create a DB schema matching the current EventStore + RemoraDB schemas."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            node_id TEXT PRIMARY KEY,       -- ← was `id`
            name TEXT, node_type TEXT DEFAULT 'function',
            status TEXT DEFAULT 'idle', file_path TEXT
        );
        CREATE TABLE IF NOT EXISTS edges (from_id TEXT, to_id TEXT, edge_type TEXT DEFAULT 'parent_of');
        CREATE TABLE IF NOT EXISTS cursor_focus (id INTEGER PRIMARY KEY, agent_id TEXT, file_path TEXT, line INTEGER, timestamp REAL);
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,  -- ← was `event_id TEXT`
            event_type TEXT, timestamp REAL, correlation_id TEXT,
            from_agent TEXT, to_agent TEXT,         -- ← was `agent_id`
            payload TEXT
        );
        CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY, agent_id TEXT, status TEXT DEFAULT 'pending', diff TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS command_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, command_type TEXT, agent_id TEXT, payload TEXT, status TEXT DEFAULT 'pending', created_at REAL);
    """)
    conn.commit()
    return conn
```

---

## Summary of Changes

| Issue | File | Priority | Work |
|-------|------|----------|------|
| Fix `events` table column names (`event_id`→`id`, `agent_id`→`from_agent/to_agent`) | `state.py` | **Critical** | Update 2 SQL queries |
| Fix `nodes` table primary key (`id`→`node_id`) | `state.py` | **Critical** | Update queries + rename logic |
| Update test schema to match production | `tests/test_bridge.py` | **Critical** | Update `_create_test_db()` + test fixtures |
| Document two-DB architecture in module docstring | `state.py` | High | Docstring update |
| Move fingerprinting to public `GraphState.fingerprint()` | `state.py`, `bridge.py` | Medium | Small refactor |
| Fix dual-connection `push_command` | `state.py` | Low | Accept optional `RemoraDB` |
| Document `proposals.file_path` migration dependency | `state.py` | Low | Code comment |
| Guard `json.loads` in `post_command` | `app.py` | Low | try/except |

---

## Verification

After changes:
```bash
devenv shell -- python -m pytest tests/test_bridge.py -v
devenv shell -- python -c "from remora_demo.web.graph.state import GraphState, GraphSnapshot; print('OK')"
devenv shell -- python -c "from remora_demo.web.graph.bridge import DBBridge; print('OK')"
# With a real DB running, verify no SQL errors:
# devenv shell -- python -c "
#   from remora_demo.web.graph.state import GraphState
#   gs = GraphState('.remora/indexer.db')
#   print(gs.read_snapshot())
# "
```
