# Graph Viewer v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a force-directed graph viewer at `remora_demo/graph/` that renders agent nodes as SVG circles with d3-force layout, a Datastar SSE data pipeline, and a server-rendered sidebar with full agent interaction (chat, proposals, tools).

**Architecture:** Server sends graph data as JSON signals via Datastar `patch_signals`, client owns all presentation via d3-force simulation + SVG rendering. Sidebar HTML fragments come via `patch_elements`. A new `command_queue` DB table enables the web UI to trigger LSP-side agent operations.

**Tech Stack:** Starlette, datastar-py, d3-force (CDN), SQLite WAL, SVG rendering in browser JS.

---

## Task 1: DB Schema — Add `command_queue` Table

**Files:**
- Modify: `src/remora/lsp/db.py:45-111` (add table to `_init_schema`)
- Modify: `src/remora/lsp/db.py` (add `push_command`, `poll_commands`, `mark_command_done` methods)
- Test: `tests/unit/test_command_queue.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_command_queue.py
"""Tests for the command_queue DB operations."""

import time
from remora.lsp.db import RemoraDB


class TestCommandQueue:
    def setup_method(self):
        self.db = RemoraDB(db_path=":memory:")

    def teardown_method(self):
        self.db.close()

    def test_table_exists(self):
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='command_queue'")
        assert cursor.fetchone() is not None

    def test_push_and_poll(self):
        self.db.push_command("chat", "agent_1", {"message": "hello"})
        commands = self.db.poll_commands(limit=10)
        assert len(commands) == 1
        assert commands[0]["command_type"] == "chat"
        assert commands[0]["agent_id"] == "agent_1"
        assert commands[0]["status"] == "pending"

    def test_poll_returns_only_pending(self):
        self.db.push_command("chat", "a1", {"message": "hi"})
        commands = self.db.poll_commands(limit=10)
        cmd_id = commands[0]["id"]
        self.db.mark_command_done(cmd_id)
        commands = self.db.poll_commands(limit=10)
        assert len(commands) == 0

    def test_mark_done_sets_processed_at(self):
        self.db.push_command("approve_proposal", "a1", {"proposal_id": "p1"})
        commands = self.db.poll_commands(limit=10)
        cmd_id = commands[0]["id"]
        self.db.mark_command_done(cmd_id)
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT status, processed_at FROM command_queue WHERE id = ?", (cmd_id,))
        row = cursor.fetchone()
        assert row["status"] == "done"
        assert row["processed_at"] is not None

    def test_push_multiple_poll_ordered(self):
        self.db.push_command("chat", "a1", {"message": "first"})
        self.db.push_command("chat", "a2", {"message": "second"})
        commands = self.db.poll_commands(limit=10)
        assert len(commands) == 2
        assert commands[0]["agent_id"] == "a1"
        assert commands[1]["agent_id"] == "a2"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_command_queue.py -v`
Expected: FAIL — `push_command` method does not exist.

**Step 3: Write minimal implementation**

Add to `_init_schema` in `db.py`, after the `cursor_focus` table and before the CREATE INDEX lines:

```sql
CREATE TABLE IF NOT EXISTS command_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_type TEXT NOT NULL,
    agent_id TEXT,
    payload JSON NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at REAL NOT NULL,
    processed_at REAL
);
```

Add three sync methods to `RemoraDB` (these are sync because the web server uses its own read-only connection, not the async LSP one):

```python
def push_command(self, command_type: str, agent_id: str | None, payload: dict) -> int:
    """Insert a command into the queue. Returns the command id."""
    cursor = self.conn.cursor()
    cursor.execute(
        """
        INSERT INTO command_queue (command_type, agent_id, payload, status, created_at)
        VALUES (?, ?, ?, 'pending', ?)
        """,
        (command_type, agent_id, json.dumps(payload), time.time()),
    )
    self.conn.commit()
    return cursor.lastrowid

def poll_commands(self, limit: int = 10) -> list[dict]:
    """Read pending commands in FIFO order."""
    cursor = self.conn.cursor()
    cursor.execute(
        "SELECT * FROM command_queue WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]

def mark_command_done(self, command_id: int) -> None:
    """Mark a command as processed."""
    cursor = self.conn.cursor()
    cursor.execute(
        "UPDATE command_queue SET status = 'done', processed_at = ? WHERE id = ?",
        (time.time(), command_id),
    )
    self.conn.commit()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_command_queue.py -v`
Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add tests/unit/test_command_queue.py src/remora/lsp/db.py
git commit -m "feat(db): add command_queue table for web->LSP command dispatch"
```

---

## Task 2: Graph State Reader for `remora_demo/graph/`

**Files:**
- Create: `remora_demo/graph/__init__.py`
- Create: `remora_demo/graph/state.py`
- Test: `tests/unit/test_graph_state.py`

This adapts `remora_demo/web/state.py` but adds: (a) `read_proposals_for_agent`, (b) `read_edges` separately, (c) `read_events_for_agent`, and (d) a fingerprint that includes `command_queue` and `proposals`.

**Step 1: Write the failing test**

```python
# tests/unit/test_graph_state.py
"""Tests for the graph viewer state reader."""

import sqlite3
import time
import json
import tempfile
from pathlib import Path

from remora_demo.graph.state import GraphState


def _init_test_db(db_path: str) -> sqlite3.Connection:
    """Create a test DB with the remora schema."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, node_type TEXT NOT NULL, name TEXT NOT NULL,
            file_path TEXT NOT NULL, start_line INTEGER, end_line INTEGER,
            start_col INTEGER DEFAULT 0, end_col INTEGER DEFAULT 0,
            source_code TEXT, source_hash TEXT, status TEXT DEFAULT 'active',
            pending_proposal_id TEXT, parent_id TEXT REFERENCES nodes(id)
        );
        CREATE TABLE IF NOT EXISTS edges (
            from_id TEXT NOT NULL, to_id TEXT NOT NULL, edge_type TEXT NOT NULL,
            PRIMARY KEY (from_id, to_id, edge_type)
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
            timestamp REAL NOT NULL, correlation_id TEXT,
            agent_id TEXT, payload JSON NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
            old_source TEXT NOT NULL, new_source TEXT NOT NULL,
            diff TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cursor_focus (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            agent_id TEXT, file_path TEXT, line INTEGER, timestamp REAL
        );
        CREATE TABLE IF NOT EXISTS command_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, command_type TEXT NOT NULL,
            agent_id TEXT, payload JSON NOT NULL, status TEXT DEFAULT 'pending',
            created_at REAL NOT NULL, processed_at REAL
        );
    """)
    conn.commit()
    return conn


class TestGraphState:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmpdir) / "test.db")
        self.conn = _init_test_db(self.db_path)
        self.state = GraphState(db_path=self.db_path)

    def teardown_method(self):
        self.state.close()
        self.conn.close()

    def test_read_snapshot_empty(self):
        snap = self.state.read_snapshot()
        assert snap.nodes == []
        assert snap.edges == []
        assert snap.cursor_focus is None

    def test_read_snapshot_with_nodes(self):
        self.conn.execute(
            "INSERT INTO nodes (id, node_type, name, file_path, start_line, end_line, source_code, source_hash) "
            "VALUES ('n1', 'file', 'test.py', '/a/test.py', 1, 10, 'code', 'hash')"
        )
        self.conn.commit()
        snap = self.state.read_snapshot()
        assert len(snap.nodes) == 1
        assert snap.nodes[0]["remora_id"] == "n1"

    def test_read_events_for_agent(self):
        self.conn.execute(
            "INSERT INTO events (event_id, event_type, timestamp, correlation_id, agent_id, payload) "
            "VALUES ('e1', 'HumanChatEvent', ?, 'c1', 'a1', ?)",
            (time.time(), json.dumps({"message": "hello"})),
        )
        self.conn.commit()
        events = self.state.read_events_for_agent("a1")
        assert len(events) == 1
        assert events[0]["event_type"] == "HumanChatEvent"

    def test_fingerprint_changes_on_insert(self):
        fp1 = self.state._fingerprint()
        self.conn.execute(
            "INSERT INTO nodes (id, node_type, name, file_path, start_line, end_line, source_code, source_hash) "
            "VALUES ('n1', 'file', 'test.py', '/a/test.py', 1, 10, 'code', 'hash')"
        )
        self.conn.commit()
        fp2 = self.state._fingerprint()
        assert fp1 != fp2

    def test_read_proposals_for_agent(self):
        self.conn.execute(
            "INSERT INTO proposals (proposal_id, agent_id, old_source, new_source, diff, status, created_at) "
            "VALUES ('p1', 'a1', 'old', 'new', 'diff text', 'pending', ?)",
            (time.time(),),
        )
        self.conn.commit()
        proposals = self.state.read_proposals_for_agent("a1")
        assert len(proposals) == 1
        assert proposals[0]["proposal_id"] == "p1"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_graph_state.py -v`
Expected: FAIL — `remora_demo.graph` module does not exist.

**Step 3: Write minimal implementation**

```python
# remora_demo/graph/__init__.py
"""Force-directed graph viewer for the Remora agent system."""

from __future__ import annotations

__all__: list[str] = []
```

```python
# remora_demo/graph/state.py
"""Graph state reader with WAL-based change detection for the graph viewer."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

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
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._last_fingerprint: str = ""

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA query_only=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def read_snapshot(self) -> GraphSnapshot:
        """Read a full snapshot of nodes, edges, and cursor focus."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM nodes WHERE status != 'orphaned'")
        nodes = [dict(row) for row in cursor.fetchall()]
        for n in nodes:
            if "id" in n:
                n["remora_id"] = n.pop("id")

        cursor.execute("SELECT * FROM edges")
        edges = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT agent_id, file_path, line, timestamp FROM cursor_focus WHERE id = 1")
        row = cursor.fetchone()
        cursor_focus = dict(row) if row else None

        return GraphSnapshot(
            nodes=nodes, edges=edges, cursor_focus=cursor_focus, timestamp=time.time()
        )

    def read_node(self, node_id: str) -> dict | None:
        """Read a single node by id."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        if "id" in d:
            d["remora_id"] = d.pop("id")
        return d

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

    def read_proposals_for_agent(self, agent_id: str) -> list[dict]:
        """Read pending proposals for a specific agent."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM proposals WHERE agent_id = ? AND status = 'pending'",
            (agent_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def read_edges_for_node(self, node_id: str) -> dict:
        """Read connections for a node: parents, children, callers, callees."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT from_id FROM edges WHERE to_id = ? AND edge_type = 'parent_of'",
            (node_id,),
        )
        parents = [row["from_id"] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'parent_of'",
            (node_id,),
        )
        children = [row["to_id"] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT from_id FROM edges WHERE to_id = ? AND edge_type = 'calls'",
            (node_id,),
        )
        callers = [row["from_id"] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'calls'",
            (node_id,),
        )
        callees = [row["to_id"] for row in cursor.fetchall()]

        return {"parents": parents, "children": children, "callers": callers, "callees": callees}

    def push_command(self, command_type: str, agent_id: str | None, payload: dict) -> int:
        """Write a command to the queue (uses a separate writable connection)."""
        # Open a new writable connection for command writes
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO command_queue (command_type, agent_id, payload, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (command_type, agent_id, json.dumps(payload), time.time()),
        )
        conn.commit()
        cmd_id = cursor.lastrowid
        conn.close()
        return cmd_id

    def _fingerprint(self) -> str:
        """Compute a lightweight fingerprint of DB state."""
        conn = self._get_conn()
        cursor = conn.cursor()
        parts = []

        cursor.execute("SELECT count(*), max(rowid) FROM nodes")
        row = cursor.fetchone()
        parts.append(f"n:{row[0]}:{row[1]}")

        cursor.execute("SELECT count(*) FROM edges")
        parts.append(f"e:{cursor.fetchone()[0]}")

        cursor.execute("SELECT timestamp FROM cursor_focus WHERE id = 1")
        cf = cursor.fetchone()
        parts.append(f"cf:{cf[0] if cf else 0}")

        cursor.execute("SELECT max(rowid) FROM events")
        parts.append(f"ev:{cursor.fetchone()[0]}")

        cursor.execute("SELECT max(rowid) FROM proposals")
        parts.append(f"pr:{cursor.fetchone()[0]}")

        return "|".join(parts)

    async def changes(self) -> AsyncIterator[GraphSnapshot]:
        """Yield snapshots whenever the DB changes (poll-based)."""
        while True:
            await asyncio.sleep(0.5)
            try:
                fp = await asyncio.to_thread(self._fingerprint)
                if fp != self._last_fingerprint:
                    self._last_fingerprint = fp
                    snapshot = await asyncio.to_thread(self.read_snapshot)
                    yield snapshot
            except Exception:
                logger.debug("Poll error", exc_info=True)
                await asyncio.sleep(2.0)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_graph_state.py -v`
Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add remora_demo/graph/__init__.py remora_demo/graph/state.py tests/unit/test_graph_state.py
git commit -m "feat(graph): add state reader with snapshot + fingerprint polling"
```

---

## Task 3: HTML Shell with d3-force + SVG Rendering

**Files:**
- Create: `remora_demo/graph/shell.py`
- Test: `tests/unit/test_graph_shell.py`

This is the biggest file — it contains the full HTML page: CSS, the Datastar init, d3-force simulation code, and SVG rendering logic. All client-side.

**Step 1: Write the failing test**

```python
# tests/unit/test_graph_shell.py
"""Tests for the graph viewer HTML shell."""

from remora_demo.graph.shell import render_shell


class TestShell:
    def test_returns_html(self):
        html = render_shell()
        assert "<!DOCTYPE html>" in html
        assert "<title>" in html

    def test_includes_datastar(self):
        html = render_shell()
        assert "datastar" in html.lower()

    def test_includes_d3_force(self):
        html = render_shell()
        assert "d3-force" in html or "d3.forceSimulation" in html

    def test_includes_svg_container(self):
        html = render_shell()
        assert "graph-svg" in html

    def test_includes_sidebar(self):
        html = render_shell()
        assert "sidebar" in html

    def test_includes_catppuccin_colors(self):
        html = render_shell()
        assert "#1e1e2e" in html  # base bg
        assert "#a6e3a1" in html  # green
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_graph_shell.py -v`
Expected: FAIL — module does not exist.

**Step 3: Write minimal implementation**

```python
# remora_demo/graph/shell.py
"""HTML shell for the force-directed graph viewer.

Renders the complete HTML page with:
- Catppuccin dark theme CSS
- Datastar for SSE data binding
- d3-force for simulation
- SVG rendering for nodes and edges
- Sidebar panel (populated via patch_elements)
"""

from __future__ import annotations


def render_shell() -> str:
    """Render the full HTML shell (initial page load)."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remora Graph</title>
    <script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js"></script>
    <style>{_css()}</style>
</head>
<body data-signals='{_initial_signals()}' data-on-load="@get('/subscribe')">
    <div class="app">
        <header class="header">
            <div class="header-title">Remora Graph</div>
            <div class="header-controls">
                <button class="header-btn" data-on-click="$viewMode = $viewMode === 'full' ? 'follow' : 'full'"
                        data-class-active="$viewMode === 'follow'">
                    Follow Cursor
                </button>
                <div class="header-status" id="connection-status">connecting...</div>
            </div>
        </header>
        <div class="main">
            <div class="graph-pane">
                <svg id="graph-svg" width="100%" height="100%"></svg>
            </div>
            <div class="sidebar" id="sidebar">
                <div id="sidebar-content">
                    <div class="sidebar-empty">Click a node to view details</div>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/d3-dispatch@3/dist/d3-dispatch.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-quadtree@3/dist/d3-quadtree.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-timer@3/dist/d3-timer.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-force@3/dist/d3-force.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-zoom@3/dist/d3-zoom.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-selection@3/dist/d3-selection.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-transition@3/dist/d3-transition.min.js"></script>
    <script>{_js()}</script>
</body>
</html>"""


def _initial_signals() -> str:
    """JSON for the initial Datastar signals."""
    import json

    return json.dumps(
        {
            "graph": {"nodes": [], "edges": [], "focus": None},
            "viewMode": "full",
            "selectedNode": None,
        }
    )


def _css() -> str:
    return """
:root {
    --bg: #1e1e2e;
    --surface: #313244;
    --surface2: #45475a;
    --overlay: #585b70;
    --text: #cdd6f4;
    --subtext: #a6adc8;
    --green: #a6e3a1;
    --blue: #89b4fa;
    --yellow: #f9e2af;
    --red: #f38ba8;
    --gray: #6c7086;
    --lavender: #b4befe;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    background: var(--bg);
    color: var(--text);
    overflow: hidden;
    height: 100vh;
}

.app { display: flex; flex-direction: column; height: 100vh; }

.header {
    background: var(--surface);
    padding: 10px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--surface2);
    flex-shrink: 0;
}

.header-title { font-size: 14px; font-weight: 600; letter-spacing: 0.5px; }

.header-controls { display: flex; align-items: center; gap: 10px; }

.header-btn {
    font-family: inherit; font-size: 11px; padding: 4px 12px;
    border: 1px solid var(--surface2); border-radius: 4px;
    background: var(--surface2); color: var(--text);
    cursor: pointer; transition: all 0.15s;
}

.header-btn:hover { background: var(--overlay); }
.header-btn.active { background: var(--blue); color: var(--bg); border-color: var(--blue); }

.header-status, #connection-status {
    font-size: 11px; color: var(--gray);
    padding: 2px 8px; border-radius: 4px; background: var(--surface2);
}

.status-connected { color: var(--green) !important; }

.main { display: flex; flex: 1; overflow: hidden; }

.graph-pane {
    flex: 1; position: relative; overflow: hidden;
    background: var(--bg);
}

#graph-svg { width: 100%; height: 100%; }

/* SVG node styles */
.node-circle { cursor: pointer; transition: stroke-width 0.15s; }
.node-circle:hover { stroke-width: 3px; }
.node-label {
    font-family: 'JetBrains Mono', monospace;
    fill: var(--text); pointer-events: none; text-anchor: middle;
}
.node-label-bg {
    fill: var(--bg); opacity: 0.7; pointer-events: none;
}

.edge-line { pointer-events: none; }

/* Sidebar */
.sidebar {
    width: 350px; background: var(--surface);
    border-left: 1px solid var(--surface2);
    overflow-y: auto; flex-shrink: 0;
}

.sidebar-empty {
    padding: 40px 20px; text-align: center;
    color: var(--gray); font-size: 13px;
}

/* Sidebar tab bar */
.sidebar-tabs {
    display: flex; border-bottom: 1px solid var(--surface2);
}

.sidebar-tab {
    flex: 1; padding: 8px 4px; text-align: center;
    font-family: inherit; font-size: 11px;
    background: none; border: none; border-bottom: 2px solid transparent;
    color: var(--subtext); cursor: pointer; transition: all 0.15s;
}

.sidebar-tab:hover { color: var(--text); }
.sidebar-tab.active { color: var(--blue); border-bottom-color: var(--blue); }

/* Sidebar content sections */
.sidebar-section { padding: 12px 16px; }

.node-info-header {
    display: flex; align-items: center; gap: 8px;
    padding: 12px 16px; border-bottom: 1px solid var(--surface2);
}

.node-info-name { font-weight: 600; font-size: 14px; flex: 1; }
.node-info-type { font-size: 11px; color: var(--subtext); text-transform: uppercase; }
.node-info-status { font-size: 10px; padding: 2px 6px; border-radius: 3px; }

.event-item {
    padding: 6px 0; border-bottom: 1px solid var(--surface2);
    font-size: 11px; display: flex; justify-content: space-between;
}

.event-badge {
    background: var(--surface2); padding: 1px 5px;
    border-radius: 3px; font-size: 10px;
}

.event-time { color: var(--gray); font-size: 10px; }

.source-block {
    background: var(--bg); border-radius: 4px;
    padding: 8px; font-size: 11px; overflow-x: auto;
    max-height: 300px; overflow-y: auto; white-space: pre;
}

.connection-item {
    padding: 4px 0; font-size: 11px; cursor: pointer;
    color: var(--blue); transition: color 0.15s;
}
.connection-item:hover { color: var(--lavender); }

.action-btn {
    display: block; width: 100%; padding: 6px 10px;
    margin-bottom: 6px; font-family: inherit; font-size: 11px;
    background: var(--surface2); border: 1px solid var(--overlay);
    border-radius: 4px; color: var(--text); cursor: pointer;
    transition: all 0.15s; text-align: left;
}
.action-btn:hover { background: var(--overlay); }
.action-btn.primary { background: var(--blue); color: var(--bg); border-color: var(--blue); }
.action-btn.danger { border-color: var(--red); color: var(--red); }
.action-btn.danger:hover { background: var(--red); color: var(--bg); }

.chat-input {
    width: 100%; padding: 6px 8px; font-family: inherit; font-size: 11px;
    background: var(--bg); border: 1px solid var(--surface2); border-radius: 4px;
    color: var(--text); resize: vertical; min-height: 60px;
}
.chat-input:focus { outline: none; border-color: var(--blue); }

.proposal-card {
    background: var(--bg); border: 1px solid var(--yellow);
    border-radius: 4px; padding: 8px; margin-bottom: 8px;
}
.proposal-diff { font-size: 10px; white-space: pre; overflow-x: auto; max-height: 200px; }
"""


def _js() -> str:
    """Client-side JS: d3-force simulation, SVG rendering, Datastar signal watch."""
    return """
(function() {
    'use strict';

    // --- Config ---
    const NODE_RADIUS = { file: 14, class: 11, function: 8, method: 8 };
    const STATUS_COLOR = {
        active: '#a6e3a1', running: '#89b4fa',
        pending_approval: '#f9e2af', orphaned: '#6c7086'
    };
    const EDGE_STYLE = {
        parent_of: { stroke: '#585b70', width: 1.5, dash: '', opacity: 0.5 },
        calls:     { stroke: '#89b4fa', width: 1,   dash: '6,4', opacity: 0.4 }
    };

    // --- State ---
    let simulation = null;
    let simNodes = [];
    let simLinks = [];
    let svgGroup = null;
    let zoom = null;
    let currentFocus = null;
    let selectedNodeId = null;

    const svg = d3.select('#graph-svg');
    const width = () => svg.node().clientWidth;
    const height = () => svg.node().clientHeight;

    // Create a group for zoom/pan
    svgGroup = svg.append('g').attr('class', 'zoom-group');

    // Setup zoom
    zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => {
            svgGroup.attr('transform', event.transform);
        });
    svg.call(zoom);

    // Edge and node groups (edges behind nodes)
    const edgeGroup = svgGroup.append('g').attr('class', 'edges');
    const nodeGroup = svgGroup.append('g').attr('class', 'nodes');

    // --- d3-force simulation ---
    function initSimulation() {
        simulation = d3.forceSimulation(simNodes)
            .force('link', d3.forceLink(simLinks)
                .id(d => d.id)
                .distance(d => d.edge_type === 'parent_of' ? 60 : 120)
                .strength(d => d.edge_type === 'parent_of' ? 0.7 : 0.2))
            .force('charge', d3.forceManyBody().strength(-100))
            .force('center', d3.forceCenter(width() / 2, height() / 2))
            .force('collide', d3.forceCollide()
                .radius(d => (NODE_RADIUS[d.node_type] || 8) + 20))
            .on('tick', render);
    }

    // --- Rendering ---
    function render() {
        // Edges
        const lines = edgeGroup.selectAll('line').data(simLinks, d => d.source.id + '-' + d.target.id + '-' + d.edge_type);
        lines.enter()
            .append('line')
            .attr('class', 'edge-line')
            .merge(lines)
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y)
            .each(function(d) {
                const style = EDGE_STYLE[d.edge_type] || EDGE_STYLE.parent_of;
                const touching = (currentFocus && (d.source.id === currentFocus || d.target.id === currentFocus))
                    || (selectedNodeId && (d.source.id === selectedNodeId || d.target.id === selectedNodeId));
                d3.select(this)
                    .attr('stroke', style.stroke)
                    .attr('stroke-width', touching ? style.width + 1 : style.width)
                    .attr('stroke-dasharray', style.dash)
                    .attr('opacity', touching ? 0.9 : style.opacity);
            });
        lines.exit().remove();

        // Nodes
        const groups = nodeGroup.selectAll('g.node-group').data(simNodes, d => d.id);

        const enter = groups.enter().append('g').attr('class', 'node-group');
        enter.append('circle').attr('class', 'node-circle');
        enter.append('text').attr('class', 'node-label').attr('dy', d => (NODE_RADIUS[d.node_type] || 8) + 14);
        enter.append('title');  // tooltip

        // Click handler
        enter.on('click', function(event, d) {
            selectedNodeId = d.id;
            // Fetch sidebar via Datastar
            const sidebarEl = document.getElementById('sidebar-content');
            if (sidebarEl) {
                sidebarEl.setAttribute('data-on-load', "@get('/agent/" + d.id + "')");
                // Trigger Datastar to process the new attribute
                fetch('/agent/' + encodeURIComponent(d.id))
                    .then(r => r.text())
                    .then(html => { sidebarEl.innerHTML = html; })
                    .catch(() => {});
            }
            render();  // re-render to update highlight
        });

        const merged = enter.merge(groups);

        merged.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');

        merged.select('circle')
            .attr('r', d => NODE_RADIUS[d.node_type] || 8)
            .attr('fill', d => STATUS_COLOR[d.status] || '#6c7086')
            .attr('stroke', d => {
                if (d.id === currentFocus) return '#89b4fa';
                if (d.id === selectedNodeId) return '#b4befe';
                return 'none';
            })
            .attr('stroke-width', d => (d.id === currentFocus || d.id === selectedNodeId) ? 3 : 0)
            .style('filter', d => d.id === currentFocus ? 'drop-shadow(0 0 6px rgba(137,180,250,0.6))' : 'none');

        merged.select('text')
            .text(d => d.name.length > 16 ? d.name.slice(0, 14) + '..' : d.name)
            .attr('font-size', d => d.node_type === 'file' ? '10px' : '9px');

        merged.select('title')
            .text(d => d.name + ' (' + d.node_type + ') [' + d.status + ']');

        groups.exit().remove();
    }

    // --- Data update from Datastar signals ---
    function updateGraph(graphData) {
        if (!graphData || !graphData.nodes) return;

        const nodeMap = new Map(simNodes.map(n => [n.id, n]));

        // Update nodes — preserve positions for existing nodes
        const newNodes = graphData.nodes.map(n => {
            const existing = nodeMap.get(n.remora_id);
            return {
                id: n.remora_id,
                name: n.name,
                node_type: n.node_type,
                status: n.status || 'active',
                file_path: n.file_path,
                x: existing ? existing.x : width() / 2 + (Math.random() - 0.5) * 100,
                y: existing ? existing.y : height() / 2 + (Math.random() - 0.5) * 100,
                vx: existing ? existing.vx : 0,
                vy: existing ? existing.vy : 0,
            };
        });

        const newLinks = graphData.edges.map(e => ({
            source: e.from_id,
            target: e.to_id,
            edge_type: e.edge_type,
        }));

        simNodes = newNodes;
        simLinks = newLinks;

        // Update focus
        currentFocus = graphData.focus;

        if (simulation) {
            simulation.nodes(simNodes);
            simulation.force('link').links(simLinks);
            simulation.alpha(0.3).restart();
        } else {
            initSimulation();
        }

        // Follow mode: zoom to focused node
        const viewMode = document.body.dataset.signals
            ? JSON.parse(document.body.dataset.signals).viewMode
            : 'full';
        if (viewMode === 'follow' && currentFocus) {
            const focusNode = simNodes.find(n => n.id === currentFocus);
            if (focusNode && focusNode.x && focusNode.y) {
                const t = d3.zoomIdentity.translate(width() / 2, height() / 2).scale(1.5).translate(-focusNode.x, -focusNode.y);
                svg.transition().duration(500).call(zoom.transform, t);
            }
        }
    }

    // --- Datastar signal integration ---
    // Watch for signal changes via MutationObserver on body data-signals
    let lastGraphJSON = '';
    const observer = new MutationObserver(() => {
        try {
            const raw = document.body.dataset.signals;
            if (!raw) return;
            const signals = JSON.parse(raw);
            const graphJSON = JSON.stringify(signals.graph);
            if (graphJSON !== lastGraphJSON) {
                lastGraphJSON = graphJSON;
                updateGraph(signals.graph);
                // Update connection status
                const status = document.getElementById('connection-status');
                if (status) { status.textContent = 'live'; status.className = 'status-connected'; }
            }
        } catch(e) { console.error('Signal parse error:', e); }
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ['data-signals'] });

    // Initial fit
    window.addEventListener('resize', () => {
        if (simulation) {
            simulation.force('center', d3.forceCenter(width() / 2, height() / 2));
            simulation.alpha(0.1).restart();
        }
    });
})();
"""
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_graph_shell.py -v`
Expected: All 6 tests PASS.

**Step 5: Commit**

```bash
git add remora_demo/graph/shell.py tests/unit/test_graph_shell.py
git commit -m "feat(graph): add HTML shell with d3-force simulation and SVG rendering"
```

---

## Task 4: Sidebar Renderer

**Files:**
- Create: `remora_demo/graph/sidebar.py`
- Test: `tests/unit/test_graph_sidebar.py`

Server-rendered HTML fragments for the sidebar panel, sent via `patch_elements`.

**Step 1: Write the failing test**

```python
# tests/unit/test_graph_sidebar.py
"""Tests for the graph viewer sidebar renderer."""

from remora_demo.graph.sidebar import render_sidebar


class TestSidebar:
    def test_renders_node_header(self):
        node = {
            "remora_id": "n1", "name": "my_func", "node_type": "function",
            "status": "active", "file_path": "/a/b.py",
            "start_line": 10, "end_line": 20, "source_code": "def my_func(): pass",
        }
        html = render_sidebar(node, events=[], proposals=[], connections={})
        assert "my_func" in html
        assert "function" in html

    def test_renders_events(self):
        node = {
            "remora_id": "n1", "name": "f", "node_type": "function",
            "status": "active", "file_path": "/a.py",
            "start_line": 1, "end_line": 5, "source_code": "",
        }
        events = [{"event_type": "HumanChatEvent", "timestamp": 1000000, "event_id": "e1", "agent_id": "n1", "payload": "{}"}]
        html = render_sidebar(node, events=events, proposals=[], connections={})
        assert "HumanChatEvent" in html

    def test_renders_source_code(self):
        node = {
            "remora_id": "n1", "name": "f", "node_type": "function",
            "status": "active", "file_path": "/a.py",
            "start_line": 1, "end_line": 5, "source_code": "def f():\n    return 42",
        }
        html = render_sidebar(node, events=[], proposals=[], connections={})
        assert "return 42" in html

    def test_renders_connections(self):
        node = {
            "remora_id": "n1", "name": "f", "node_type": "function",
            "status": "active", "file_path": "/a.py",
            "start_line": 1, "end_line": 5, "source_code": "",
        }
        connections = {"parents": ["p1"], "children": [], "callers": ["c1"], "callees": []}
        html = render_sidebar(node, events=[], proposals=[], connections=connections)
        assert "p1" in html
        assert "c1" in html

    def test_renders_pending_proposals(self):
        node = {
            "remora_id": "n1", "name": "f", "node_type": "function",
            "status": "pending_approval", "file_path": "/a.py",
            "start_line": 1, "end_line": 5, "source_code": "",
        }
        proposals = [{"proposal_id": "pr1", "diff": "-old\n+new", "status": "pending"}]
        html = render_sidebar(node, events=[], proposals=proposals, connections={})
        assert "pr1" in html

    def test_not_found(self):
        html = render_sidebar(None, events=[], proposals=[], connections={})
        assert "not found" in html.lower() or "Not found" in html
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_graph_sidebar.py -v`
Expected: FAIL — module does not exist.

**Step 3: Write minimal implementation**

```python
# remora_demo/graph/sidebar.py
"""Server-rendered sidebar HTML fragments for the graph viewer."""

from __future__ import annotations

import datetime
import html


STATUS_COLORS = {
    "active": "#a6e3a1",
    "running": "#89b4fa",
    "pending_approval": "#f9e2af",
    "orphaned": "#6c7086",
}


def render_sidebar(
    node: dict | None,
    events: list[dict],
    proposals: list[dict],
    connections: dict,
) -> str:
    """Render the full sidebar HTML for a selected node."""
    if not node:
        return '<div id="sidebar-content"><div class="sidebar-empty">Node not found</div></div>'

    nid = html.escape(node.get("remora_id", ""))
    name = html.escape(node.get("name", "unknown"))
    node_type = node.get("node_type", "unknown")
    status = node.get("status", "active")
    file_path = html.escape(node.get("file_path", ""))
    start_line = node.get("start_line", "?")
    end_line = node.get("end_line", "?")
    source = node.get("source_code", "")
    color = STATUS_COLORS.get(status, "#6c7086")

    parts = ['<div id="sidebar-content">']

    # Header
    parts.append(f'<div class="node-info-header">')
    parts.append(f'<span class="node-info-name">{name}</span>')
    parts.append(f'<span class="node-info-type">{node_type}</span>')
    parts.append(f'<span class="node-info-status" style="background:{color};color:#1e1e2e">{status}</span>')
    parts.append(f'</div>')

    # Meta
    parts.append(f'<div class="sidebar-section">')
    parts.append(f'<div style="font-size:11px;color:#a6adc8;margin-bottom:4px"><strong>ID:</strong> <code>{nid}</code></div>')
    parts.append(f'<div style="font-size:11px;color:#a6adc8;margin-bottom:4px"><strong>File:</strong> {file_path}</div>')
    parts.append(f'<div style="font-size:11px;color:#a6adc8"><strong>Lines:</strong> {start_line}-{end_line}</div>')
    parts.append(f'</div>')

    # Tabs: Log | Source | Connections | Actions
    parts.append(f'<div class="sidebar-tabs">')
    for tab in ["Log", "Source", "Connections", "Actions"]:
        parts.append(f'<button class="sidebar-tab" onclick="switchTab(this, \'{tab.lower()}\')">{tab}</button>')
    parts.append(f'</div>')

    # Log tab
    parts.append(f'<div class="sidebar-section tab-content" data-tab="log">')
    if events:
        for ev in events[:15]:
            et = html.escape(str(ev.get("event_type", "")))
            ts = ev.get("timestamp", 0)
            parts.append(f'<div class="event-item">')
            parts.append(f'<span class="event-badge">{et}</span>')
            parts.append(f'<span class="event-time">{_format_time(ts)}</span>')
            parts.append(f'</div>')
    else:
        parts.append(f'<div class="sidebar-empty" style="padding:12px">No events yet</div>')
    parts.append(f'</div>')

    # Source tab
    parts.append(f'<div class="sidebar-section tab-content" data-tab="source" style="display:none">')
    if source:
        parts.append(f'<pre class="source-block"><code>{html.escape(source)}</code></pre>')
    else:
        parts.append(f'<div class="sidebar-empty" style="padding:12px">No source code</div>')
    parts.append(f'</div>')

    # Connections tab
    parts.append(f'<div class="sidebar-section tab-content" data-tab="connections" style="display:none">')
    if connections:
        for label, key in [("Parents", "parents"), ("Children", "children"), ("Callers", "callers"), ("Callees", "callees")]:
            items = connections.get(key, [])
            if items:
                parts.append(f'<div style="font-size:11px;color:#a6adc8;margin:6px 0 2px;font-weight:600">{label}</div>')
                for item_id in items:
                    escaped_id = html.escape(item_id)
                    parts.append(f'<div class="connection-item" onclick="selectNode(\'{escaped_id}\')">{escaped_id}</div>')
        if not any(connections.get(k) for k in ("parents", "children", "callers", "callees")):
            parts.append(f'<div class="sidebar-empty" style="padding:12px">No connections</div>')
    else:
        parts.append(f'<div class="sidebar-empty" style="padding:12px">No connections</div>')
    parts.append(f'</div>')

    # Actions tab
    parts.append(f'<div class="sidebar-section tab-content" data-tab="actions" style="display:none">')

    # Chat
    parts.append(f'<div style="margin-bottom:12px">')
    parts.append(f'<div style="font-size:11px;color:#a6adc8;margin-bottom:4px;font-weight:600">Send Message</div>')
    parts.append(f'<textarea class="chat-input" id="chat-input" placeholder="Message to agent..."></textarea>')
    parts.append(f'<button class="action-btn primary" style="margin-top:4px" '
                 f'onclick="sendChat(\'{nid}\')">Send</button>')
    parts.append(f'</div>')

    # Proposals
    if proposals:
        parts.append(f'<div style="font-size:11px;color:#a6adc8;margin-bottom:4px;font-weight:600">Pending Proposals</div>')
        for p in proposals:
            pid = html.escape(str(p.get("proposal_id", "")))
            diff = html.escape(str(p.get("diff", "")))
            parts.append(f'<div class="proposal-card">')
            parts.append(f'<div style="font-size:10px;color:#a6adc8;margin-bottom:4px">ID: {pid}</div>')
            parts.append(f'<pre class="proposal-diff">{diff}</pre>')
            parts.append(f'<div style="display:flex;gap:4px;margin-top:6px">')
            parts.append(f'<button class="action-btn" style="flex:1" '
                         f'onclick="approveProposal(\'{pid}\')">Approve</button>')
            parts.append(f'<button class="action-btn danger" style="flex:1" '
                         f'onclick="rejectProposal(\'{pid}\')">Reject</button>')
            parts.append(f'</div>')
            parts.append(f'</div>')

    parts.append(f'</div>')

    parts.append(f'</div>')
    return "\n".join(parts)


def _format_time(ts: float) -> str:
    if not ts:
        return ""
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_graph_sidebar.py -v`
Expected: All 6 tests PASS.

**Step 5: Commit**

```bash
git add remora_demo/graph/sidebar.py tests/unit/test_graph_sidebar.py
git commit -m "feat(graph): add server-rendered sidebar with tabs for log/source/connections/actions"
```

---

## Task 5: Starlette App with Routes

**Files:**
- Create: `remora_demo/graph/app.py`
- Test: `tests/unit/test_graph_app.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_graph_app.py
"""Tests for the graph viewer Starlette app routes."""

import tempfile
import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from remora_demo.graph.app import create_app


def _init_test_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, node_type TEXT, name TEXT, file_path TEXT,
            start_line INTEGER, end_line INTEGER, start_col INTEGER DEFAULT 0,
            end_col INTEGER DEFAULT 0, source_code TEXT, source_hash TEXT,
            status TEXT DEFAULT 'active', pending_proposal_id TEXT,
            parent_id TEXT
        );
        CREATE TABLE IF NOT EXISTS edges (
            from_id TEXT, to_id TEXT, edge_type TEXT,
            PRIMARY KEY (from_id, to_id, edge_type)
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, event_type TEXT, timestamp REAL,
            correlation_id TEXT, agent_id TEXT, payload JSON
        );
        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id TEXT PRIMARY KEY, agent_id TEXT, old_source TEXT,
            new_source TEXT, diff TEXT, status TEXT DEFAULT 'pending',
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS cursor_focus (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            agent_id TEXT, file_path TEXT, line INTEGER, timestamp REAL
        );
        CREATE TABLE IF NOT EXISTS command_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, command_type TEXT,
            agent_id TEXT, payload JSON, status TEXT DEFAULT 'pending',
            created_at REAL, processed_at REAL
        );
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def client():
    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "test.db")
    _init_test_db(db_path)
    app = create_app(db_path=db_path)
    return TestClient(app)


class TestRoutes:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text

    def test_command_post(self, client):
        resp = client.post("/command", json={
            "command_type": "chat",
            "agent_id": "a1",
            "payload": {"message": "hello"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert "command_id" in data
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_graph_app.py -v`
Expected: FAIL — module does not exist.

**Step 3: Write minimal implementation**

```python
# remora_demo/graph/app.py
"""Starlette app for the Remora force-directed graph viewer.

Routes:
    GET /            -> HTML shell (initial page load)
    GET /subscribe   -> SSE: patch_signals with graph data
    GET /agent/{id}  -> HTML sidebar fragment for selected node
    POST /command    -> Queue a command for the LSP server
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from remora_demo.graph.shell import render_shell
from remora_demo.graph.sidebar import render_sidebar
from remora_demo.graph.state import GraphState

logger = logging.getLogger("remora.graph")


def create_app(db_path: str = ".remora/indexer.db") -> Starlette:
    """Create the Starlette ASGI app for the graph viewer."""
    state = GraphState(db_path=db_path)

    async def index(_request: Request) -> HTMLResponse:
        return HTMLResponse(render_shell())

    async def subscribe(_request: Request) -> DatastarResponse:
        async def stream() -> AsyncIterator[str]:
            # Initial data push
            try:
                snapshot = await asyncio.to_thread(state.read_snapshot)
                graph_data = _snapshot_to_signals(snapshot)
                yield SSE.patch_signals(json.dumps({"graph": graph_data}))
            except Exception:
                logger.exception("Error reading initial snapshot")

            # Stream changes
            async for snapshot in state.changes():
                try:
                    graph_data = _snapshot_to_signals(snapshot)
                    yield SSE.patch_signals(json.dumps({"graph": graph_data}))
                except Exception:
                    logger.debug("Error streaming snapshot", exc_info=True)

        return DatastarResponse(stream())

    async def agent_detail(request: Request) -> HTMLResponse:
        agent_id = request.path_params["id"]

        def _read():
            node = state.read_node(agent_id)
            events = state.read_events_for_agent(agent_id) if node else []
            proposals = state.read_proposals_for_agent(agent_id) if node else []
            connections = state.read_edges_for_node(agent_id) if node else {}
            return node, events, proposals, connections

        node, events, proposals, connections = await asyncio.to_thread(_read)
        html = render_sidebar(node, events, proposals, connections)
        return HTMLResponse(html)

    async def post_command(request: Request) -> JSONResponse:
        body = await request.json()
        command_type = body.get("command_type", "")
        agent_id = body.get("agent_id")
        payload = body.get("payload", {})

        if not command_type:
            return JSONResponse({"error": "command_type required"}, status_code=400)

        cmd_id = await asyncio.to_thread(
            state.push_command, command_type, agent_id, payload
        )
        return JSONResponse({"status": "queued", "command_id": cmd_id})

    async def on_shutdown() -> None:
        state.close()

    routes = [
        Route("/", index),
        Route("/subscribe", subscribe),
        Route("/agent/{id:path}", agent_detail),
        Route("/command", post_command, methods=["POST"]),
    ]

    return Starlette(routes=routes, on_shutdown=[on_shutdown])


def _snapshot_to_signals(snapshot) -> dict:
    """Convert a GraphSnapshot to the signal format the client expects."""
    nodes = []
    for n in snapshot.nodes:
        nodes.append({
            "remora_id": n.get("remora_id", ""),
            "name": n.get("name", ""),
            "node_type": n.get("node_type", ""),
            "status": n.get("status", "active"),
            "file_path": n.get("file_path", ""),
        })

    edges = []
    for e in snapshot.edges:
        edges.append({
            "from_id": e.get("from_id", ""),
            "to_id": e.get("to_id", ""),
            "edge_type": e.get("edge_type", ""),
        })

    focus = None
    if snapshot.cursor_focus:
        focus = snapshot.cursor_focus.get("agent_id")

    return {"nodes": nodes, "edges": edges, "focus": focus}
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_graph_app.py -v`
Expected: All 2 tests PASS.

**Step 5: Commit**

```bash
git add remora_demo/graph/app.py tests/unit/test_graph_app.py
git commit -m "feat(graph): add Starlette app with SSE subscribe, sidebar, and command routes"
```

---

## Task 6: CLI Entry Point

**Files:**
- Create: `remora_demo/graph/__main__.py`
- Update: `remora_demo/graph/__init__.py` (export `create_app`)

**Step 1: Write the failing test**

```python
# tests/unit/test_graph_cli.py
"""Tests for the graph viewer CLI entry point."""

import subprocess
import sys


class TestCLI:
    def test_help_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "remora_demo.graph", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "--port" in result.stdout
        assert "--db" in result.stdout
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_graph_cli.py -v`
Expected: FAIL — `__main__.py` does not exist.

**Step 3: Write minimal implementation**

```python
# remora_demo/graph/__main__.py
"""CLI entry point: python -m remora_demo.graph [--port 8420] [--db PATH]."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Remora force-directed graph viewer")
    parser.add_argument("--port", type=int, default=8420, help="HTTP port (default: 8420)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--db", default=".remora/indexer.db", help="Path to indexer.db")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required: pip install uvicorn", file=sys.stderr)
        sys.exit(1)

    from remora_demo.graph.app import create_app

    app = create_app(db_path=args.db)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
```

Update `__init__.py`:

```python
# remora_demo/graph/__init__.py
"""Force-directed graph viewer for the Remora agent system."""

from __future__ import annotations

from remora_demo.graph.app import create_app

__all__ = ["create_app"]
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_graph_cli.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add remora_demo/graph/__main__.py remora_demo/graph/__init__.py tests/unit/test_graph_cli.py
git commit -m "feat(graph): add CLI entry point and package exports"
```

---

## Task 7: LSP Command Queue Polling

**Files:**
- Modify: `src/remora/lsp/runner.py` (add `poll_command_queue` method and periodic task)
- Modify: `src/remora/lsp/db.py` (ensure `poll_commands` and `mark_command_done` have async variants)
- Test: `tests/unit/test_command_polling.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_command_polling.py
"""Tests for LSP command queue polling dispatch."""

import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remora.lsp.db import RemoraDB


class TestCommandPolling:
    def setup_method(self):
        self.db = RemoraDB(db_path=":memory:")

    def teardown_method(self):
        self.db.close()

    def test_push_and_poll_roundtrip(self):
        self.db.push_command("chat", "agent1", {"message": "hello"})
        cmds = self.db.poll_commands(limit=5)
        assert len(cmds) == 1
        assert cmds[0]["command_type"] == "chat"
        parsed = json.loads(cmds[0]["payload"])
        assert parsed["message"] == "hello"

    def test_mark_done_removes_from_poll(self):
        self.db.push_command("chat", "a1", {"msg": "hi"})
        cmds = self.db.poll_commands()
        self.db.mark_command_done(cmds[0]["id"])
        assert self.db.poll_commands() == []
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_command_polling.py -v`
Expected: Should pass if Task 1 is done. If Task 1 is not done yet, it will fail.

**Step 3: Add async polling to runner.py**

Add to `AgentRunner` class in `runner.py`:

```python
async def poll_command_queue(self) -> None:
    """Poll the command_queue table and dispatch commands."""
    while self._running:
        try:
            commands = await asyncio.to_thread(self.server.db.poll_commands, 10)
            for cmd in commands:
                await self._dispatch_command(cmd)
                await asyncio.to_thread(self.server.db.mark_command_done, cmd["id"])
        except Exception:
            logger.debug("Command queue poll error", exc_info=True)
        await asyncio.sleep(1.0)

async def _dispatch_command(self, cmd: dict) -> None:
    """Dispatch a single command from the queue."""
    from remora.lsp.server import emit_event

    cmd_type = cmd["command_type"]
    agent_id = cmd.get("agent_id")
    payload = json.loads(cmd["payload"]) if isinstance(cmd["payload"], str) else cmd["payload"]

    logger.info("Dispatching command: type=%s agent=%s", cmd_type, agent_id)

    if cmd_type == "chat" and agent_id:
        correlation_id = self.server.generate_correlation_id()
        from remora.lsp.models import HumanChatEvent
        await emit_event(
            HumanChatEvent(
                agent_id=agent_id,
                to_agent=agent_id,
                message=payload.get("message", ""),
                correlation_id=correlation_id,
                timestamp=0.0,
            )
        )
        await self.trigger(agent_id, correlation_id)

    elif cmd_type == "approve_proposal":
        proposal_id = payload.get("proposal_id", "")
        if proposal_id and proposal_id in self.server.proposals:
            from remora.lsp.handlers.commands import cmd_accept_proposal
            await cmd_accept_proposal(self.server, proposal_id)

    elif cmd_type == "reject_proposal":
        proposal_id = payload.get("proposal_id", "")
        feedback = payload.get("feedback", "")
        proposal = self.server.proposals.get(proposal_id)
        if proposal:
            from remora.lsp.models import RewriteRejectedEvent
            await emit_event(
                RewriteRejectedEvent(
                    agent_id=proposal.agent_id,
                    proposal_id=proposal_id,
                    feedback=feedback,
                    correlation_id=proposal.correlation_id or "",
                    timestamp=0.0,
                )
            )
            await self.trigger(
                proposal.agent_id,
                proposal.correlation_id,
                context={"rejection_feedback": feedback},
            )

    elif cmd_type == "execute_tool" and agent_id:
        tool_name = payload.get("tool_name", "")
        tool_params = payload.get("params", {})
        node = await self.server.db.get_node(agent_id)
        if node and tool_name:
            from remora.lsp.models import ASTAgentNode
            agent = ASTAgentNode(**node)
            await self.execute_extension_tool(
                agent, tool_name, tool_params, self.server.generate_correlation_id()
            )
    else:
        logger.warning("Unknown command type: %s", cmd_type)
```

Update `run_forever` to also start the polling task:

```python
async def run_forever(self) -> None:
    self._running = True
    logger.info("AgentRunner.run_forever: started, waiting for triggers")
    # Start command queue polling as a background task
    poll_task = asyncio.create_task(self.poll_command_queue())
    try:
        while self._running:
            trigger = await self.queue.get()
            logger.info(
                "AgentRunner.run_forever: dequeued trigger agent=%s corr=%s",
                trigger.agent_id, trigger.correlation_id,
            )
            await self.execute_turn(trigger)
    finally:
        poll_task.cancel()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_command_polling.py -v`
Expected: All 2 tests PASS.

**Step 5: Commit**

```bash
git add src/remora/lsp/runner.py tests/unit/test_command_polling.py
git commit -m "feat(lsp): add command queue polling to AgentRunner for web->LSP dispatch"
```

---

## Task 8: Integration Test — Full Stack

**Files:**
- Test: `tests/unit/test_graph_integration.py`

End-to-end test: create a DB with nodes, start the app, verify the subscribe endpoint returns graph data and the command endpoint queues properly.

**Step 1: Write the test**

```python
# tests/unit/test_graph_integration.py
"""Integration tests for the graph viewer full stack."""

import json
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from remora_demo.graph.app import create_app


def _init_test_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, node_type TEXT, name TEXT, file_path TEXT,
            start_line INTEGER, end_line INTEGER, start_col INTEGER DEFAULT 0,
            end_col INTEGER DEFAULT 0, source_code TEXT, source_hash TEXT,
            status TEXT DEFAULT 'active', pending_proposal_id TEXT, parent_id TEXT
        );
        CREATE TABLE IF NOT EXISTS edges (
            from_id TEXT, to_id TEXT, edge_type TEXT,
            PRIMARY KEY (from_id, to_id, edge_type)
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, event_type TEXT, timestamp REAL,
            correlation_id TEXT, agent_id TEXT, payload JSON
        );
        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id TEXT PRIMARY KEY, agent_id TEXT, old_source TEXT,
            new_source TEXT, diff TEXT, status TEXT DEFAULT 'pending', created_at REAL
        );
        CREATE TABLE IF NOT EXISTS cursor_focus (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            agent_id TEXT, file_path TEXT, line INTEGER, timestamp REAL
        );
        CREATE TABLE IF NOT EXISTS command_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, command_type TEXT,
            agent_id TEXT, payload JSON, status TEXT DEFAULT 'pending',
            created_at REAL, processed_at REAL
        );
    """)
    # Insert test data
    conn.execute(
        "INSERT INTO nodes VALUES ('f1','file','app.py','/src/app.py',1,50,0,0,'# app','hash1','active',NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('fn1','function','main','/src/app.py',10,30,0,0,'def main(): pass','hash2','active',NULL,'f1')"
    )
    conn.execute("INSERT INTO edges VALUES ('f1','fn1','parent_of')")
    conn.commit()
    conn.close()


@pytest.fixture
def client():
    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "test.db")
    _init_test_db(db_path)
    app = create_app(db_path=db_path)
    return TestClient(app)


class TestIntegration:
    def test_index_serves_shell(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "d3-force" in resp.text or "d3.forceSimulation" in resp.text

    def test_agent_detail(self, client):
        resp = client.get("/agent/fn1")
        assert resp.status_code == 200
        assert "main" in resp.text
        assert "function" in resp.text

    def test_agent_not_found(self, client):
        resp = client.get("/agent/nonexistent")
        assert resp.status_code == 200
        assert "not found" in resp.text.lower() or "Not found" in resp.text

    def test_command_queues_chat(self, client):
        resp = client.post("/command", json={
            "command_type": "chat",
            "agent_id": "fn1",
            "payload": {"message": "optimize this"},
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_command_rejects_empty_type(self, client):
        resp = client.post("/command", json={
            "command_type": "",
            "payload": {},
        })
        assert resp.status_code == 400
```

**Step 2: Run test**

Run: `python -m pytest tests/unit/test_graph_integration.py -v`
Expected: All 5 tests PASS (if tasks 1-6 are done).

**Step 3: Commit**

```bash
git add tests/unit/test_graph_integration.py
git commit -m "test(graph): add integration tests for full graph viewer stack"
```

---

## Task 9: Run Full Test Suite + Verify

**Step 1: Run all tests**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: All existing tests still pass + all new tests pass.

**Step 2: Run the app manually to verify it starts**

```bash
python -m remora_demo.graph --help
```

Expected: Prints help text showing `--port`, `--host`, `--db` options.

**Step 3: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: address test issues from full suite run"
```

---

## Summary

| Task | Component | Files Created/Modified | Tests |
|------|-----------|----------------------|-------|
| 1 | DB command_queue | `db.py` | 5 tests |
| 2 | State reader | `graph/state.py`, `graph/__init__.py` | 5 tests |
| 3 | HTML shell + d3-force | `graph/shell.py` | 6 tests |
| 4 | Sidebar renderer | `graph/sidebar.py` | 6 tests |
| 5 | Starlette app | `graph/app.py` | 2 tests |
| 6 | CLI entry point | `graph/__main__.py` | 1 test |
| 7 | LSP command polling | `runner.py` | 2 tests |
| 8 | Integration tests | - | 5 tests |
| 9 | Full suite verification | - | - |

**Total: 9 tasks, ~32 new tests, 7 new files, 2 modified files.**
