# Bootstrap V6 — Implementation Guide

> Actionable engineering spec for implementing `PHASE2_V6_BOOTSTRAP_CONCEPT.md`
> against the existing remora v1 codebase.
>
> Every V6 concept maps to a specific v1 class, method, or file.
> New code is minimal: we wrap, extend, and wire — not rewrite.

---

## Table of Contents

1. [V1 → V6 Wire-Up Map](#1-v1--v6-wire-up-map)
   Quick reference: every bootstrap concept mapped to its v1 counterpart.
   Which v1 classes are reused as-is, which are extended, which are new.

2. [Module Layout](#2-module-layout)
   New files in `src/remora/bootstrap/`. Tach module boundaries.
   What the bootstrap module imports from v1 (and what it must not import).

3. [M0: The Bedrock Layer](#3-m0-the-bedrock-layer)
   `src/remora/bootstrap/bedrock.py`. The six async functions.
   `BootstrapGraphStore` in `src/remora/bootstrap/graph_store.py`.
   Schema additions to `event_store_schema.py`.
   `build_bedrock()` factory and per-agent closure construction.

4. [M1: System Tools (.pym)](#4-m1-system-tools-pym)
   All nine `bootstrap/tools/*.pym` files with exact content.
   How `discover_grail_tools()` is extended to accept both system
   and workspace tool directories. Externals dict construction.

5. [M2: Turn Executor](#5-m2-turn-executor)
   `TurnSchema` Pydantic model (schema_loader.py).
   `DEFAULT_SCHEMA` YAML constant. `extends:` resolution.
   Template variable namespaces `{node.*}` and `{{name}}`.
   `TurnExecutor.run()` — context pipeline → LLM → tool dispatch → termination.

6. [M3: Self-Bootstrapping Loop](#6-m3-self-bootstrapping-loop)
   `bootstrap/agents/DEFAULT_SCHEMA.yaml` and `base_code_agent.yaml`.
   How an empty workspace progresses to a self-defined agent.
   Bootstrap coordinator: scan graph → emit AgentNeededEvent → spawn agents.

7. [M4: Graph Seeding](#7-m4-graph-seeding)
   `src/remora/bootstrap/seed_graph.py`.
   Walking the Remora source tree. Writing bootstrap_nodes + bootstrap_edges.
   Node kinds and edge kinds for the initial code topology.

8. [M5: Companion Visibility](#8-m5-companion-visibility)
   Extending the companion sidebar to display workspace files.
   Five workspace panels: ROLE, SCHEMA, NOTES, TODO, LOG, TOOLS.
   No new protocol — reads workspace files via the existing Cairn workspace API.

9. [M6: Tool Synthesis](#9-m6-tool-synthesis)
   Writing `.pym` tools from within an agent turn.
   Extending `discover_grail_tools()` with workspace scan.
   @external boundary: synthesized tools reach system tools, not bedrock.
   Compilation at activation time and error handling.

10. [Testing Plan](#10-testing-plan)
    Unit + integration tests per milestone. Key invariants to verify.
    How to run with the devenv shell.

---

## 1. V1 → V6 Wire-Up Map

### Core concept mapping

| V6 Bootstrap Concept | V1 Implementation | Action |
|---|---|---|
| `_cairn_read(path)` | `CairnExternals.read_file(path)` | wrap in bedrock closure |
| `_cairn_write(path, content)` | `CairnExternals.write_file(path, content)` | wrap in bedrock closure |
| `_graph_read(selector)` | `BootstrapGraphStore.read(selector)` | **new class** (extends NodeStore pattern) |
| `_graph_write(op, data)` | `BootstrapGraphStore.write(op, data)` | **new class** |
| `_event_read(selector)` | `EventStore.get_recent_events()` | wrap in bedrock closure |
| `_event_write(event_type, payload)` | `EventStore.append(swarm_id, event)` | wrap in bedrock closure |
| `workspace` store | `CairnWorkspaceService` per-agent DB | reuse as-is |
| `graph` store | `BootstrapGraphStore` + EventStore DB | **new tables** in existing DB |
| `events` store | `EventStore` (WAL SQLite) | reuse as-is |
| `SubscriptionRegistry` | `SubscriptionRegistry` | reuse as-is |
| `RemoraGrailTool` | `RemoraGrailTool` | reuse as-is |
| `discover_grail_tools()` | `discover_grail_tools()` | **extend** with workspace dir param |
| `schema.yaml` | `BundleManifest` / `load_manifest()` | **new** `TurnSchema` + `schema_loader.py` |
| `TurnExecutor` | `execute_agent_turn()` | **new** parallel implementation |
| `create_kernel()` | `create_kernel()` | reuse as-is |
| Companion sidebar workspace view | — | **new** sidebar panels |

### What is NOT changed in v1

- `EventStore` — no schema changes except adding bootstrap tables
- `CairnWorkspaceService` — unchanged
- `CairnExternals` — unchanged; bedrock closures call its methods
- `SubscriptionRegistry` / `SubscriptionPattern` — unchanged
- `RemoraGrailTool` — unchanged
- `execute_agent_turn()` — unchanged; bootstrap TurnExecutor runs alongside it
- `AgentNode` / `NodeStore` — unchanged; BootstrapGraphStore is a sibling class

### The bootstrap externals dict

The bootstrap bedrock constructs one externals dict per agent activation.
This dict is injected into Grail tool execution in place of the v1
`AgentContext.as_externals()`:

```python
{
    # Workspace channel
    "_cairn_read":  async (path: str) -> str,
    "_cairn_write": async (path: str, content: str) -> None,

    # Graph channel
    "_graph_read":  async (selector: dict) -> str,
    "_graph_write": async (op: str, data: dict) -> str,

    # Event channel
    "_event_read":  async (selector: dict) -> str,
    "_event_write": async (event_type: str, payload: dict) -> str,
}
```

System tool `.pym` files declare `@external` on exactly the bedrock functions
they need from this dict. No other keys are accessible to Grail scripts.

---

## 2. Module Layout

### New directory: `src/remora/bootstrap/`

```
src/remora/bootstrap/
  __init__.py
  bedrock.py          # build_bedrock() factory — the six async closures
  graph_store.py      # BootstrapGraphStore — new tables on EventStore DB
  schema_loader.py    # TurnSchema, load_schema(), DEFAULT_SCHEMA constant
  turn_executor.py    # TurnExecutor class — context pipeline + LLM dispatch
  seed_graph.py       # One-time seeding script for code topology
```

### New directory: `bootstrap/tools/` (repo root, not in src/)

```
bootstrap/
  tools/
    read_file.pym
    write_file.pym
    graph_node.pym
    graph_neighbors.pym
    graph_find_nodes.pym
    graph_add_node.pym
    graph_add_edge.pym
    read_recent_events.pym
    emit_event.pym
  agents/
    DEFAULT_SCHEMA.yaml      # Base template — mirrors DEFAULT_SCHEMA constant
    base_code_agent.yaml     # Extended schema for code module agents
```

### Tach module boundaries

Add to `tach.toml`:

```toml
[[modules]]
path = "remora.bootstrap"
depends_on = [
  { path = "remora.core" },
  { path = "remora.utils" },
]
```

The bootstrap module imports from:
- `remora.core.agents.cairn_bridge` — `CairnWorkspaceService`, `CairnExternals`
- `remora.core.tools.grail` — `RemoraGrailTool`, `discover_grail_tools`
- `remora.core.store.event_store` — `EventStore`
- `remora.core.store.event_store_schema` — `create_tables` (to add bootstrap tables)
- `remora.core.agents.kernel_factory` — `create_kernel`
- `remora.core.events.subscriptions` — `SubscriptionRegistry`
- `remora.utils` — `PathLike`, `normalize_path`

The bootstrap module must NOT import from:
- `remora.lsp` — LSP is an adapter layer, not a core dependency
- `remora.runner` — runner is an adapter layer
- `remora.service` — service is an adapter layer
- `remora.companion` — companion reads bootstrap output; it does not feed it

### What v1 files are modified

| File | Change |
|---|---|
| `core/store/event_store_schema.py` | Add `create_bootstrap_tables()` called from `create_tables()` |
| `core/store/event_store.py` | Expose `BootstrapGraphStore` via `event_store.bootstrap_graph` property (like `event_store.nodes`) |
| `core/tools/grail.py` | Add optional `workspace_tools_dir` parameter to `discover_grail_tools()` |

Everything else in v1 is unchanged.

---

## 3. M0: The Bedrock Layer

### 3.1 Schema additions: `core/store/event_store_schema.py`

Add a new function `create_bootstrap_tables()` and call it from `create_tables()`:

```python
def create_bootstrap_tables(conn: sqlite3.Connection) -> None:
    """Create bootstrap-specific tables: generic graph nodes and edges."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bootstrap_nodes (
            id          TEXT PRIMARY KEY,
            kind        TEXT NOT NULL,
            attrs_json  TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_bnode_kind ON bootstrap_nodes(kind);

        CREATE TABLE IF NOT EXISTS bootstrap_edges (
            from_id     TEXT NOT NULL,
            to_id       TEXT NOT NULL,
            kind        TEXT NOT NULL,
            attrs_json  TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (from_id, to_id, kind)
        );

        CREATE INDEX IF NOT EXISTS idx_bedge_from ON bootstrap_edges(from_id);
        CREATE INDEX IF NOT EXISTS idx_bedge_to   ON bootstrap_edges(to_id);
    """)
```

Call it at the end of `create_tables()`:
```python
def create_tables(conn: sqlite3.Connection) -> None:
    # ... existing tables ...
    create_bootstrap_tables(conn)
```

Also add migration in `migrate()`:
```python
# bootstrap_nodes and bootstrap_edges are created fresh — no migration needed
# (create_bootstrap_tables uses IF NOT EXISTS)
```

### 3.2 BootstrapGraphStore: `src/remora/bootstrap/graph_store.py`

```python
"""Bootstrap property graph store.

Lives in the same SQLite DB as EventStore but in separate tables.
Follows the same read_conn / write_conn pattern as NodeStore.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from typing import Any

from remora.utils import PathLike


class BootstrapGraphStore:
    """Shared property graph for bootstrap agents.

    Tables: bootstrap_nodes(id, kind, attrs_json)
            bootstrap_edges(from_id, to_id, kind, attrs_json)

    read_conn is a dedicated read-only connection (WAL mode: no blocking).
    write_conn is the main EventStore write connection, protected by write_lock.
    Both are passed in by EventStore after initialize().
    """

    def __init__(
        self,
        read_conn: sqlite3.Connection,
        read_lock: asyncio.Lock,
        write_conn: sqlite3.Connection,
        write_lock: asyncio.Lock,
    ) -> None:
        self._read_conn = read_conn
        self._read_lock = read_lock
        self._write_conn = write_conn
        self._write_lock = write_lock

    # ── Reads ──────────────────────────────────────────────────────────────

    async def read(self, selector: dict) -> str:
        """Dispatch a read selector to the appropriate query.

        Selector shapes:
          {"node": node_id}                   → get one node
          {"neighbors": node_id, "dir": str}  → get neighbors (in/out/both)
          {"match": {"kind": str, ...}}        → find nodes by attrs
        """
        if "node" in selector:
            return await self._get_node(selector["node"])
        if "neighbors" in selector:
            return await self._get_neighbors(selector["neighbors"], selector.get("dir", "both"))
        if "match" in selector:
            return await self._find_nodes(selector["match"])
        raise ValueError(f"Unknown graph read selector: {selector!r}")

    async def _get_node(self, node_id: str) -> str:
        def _fetch(conn: sqlite3.Connection) -> dict | None:
            with conn.execute(
                "SELECT id, kind, attrs_json FROM bootstrap_nodes WHERE id = ?",
                (node_id,),
            ) as cursor:
                row = cursor.fetchone()
            if row is None:
                return None
            return {"id": row[0], "kind": row[1], "attrs": json.loads(row[2])}

        async with self._read_lock:
            result = await asyncio.to_thread(_fetch, self._read_conn)
        return json.dumps(result)

    async def _get_neighbors(self, node_id: str, direction: str) -> str:
        def _fetch(conn: sqlite3.Connection) -> list[dict]:
            if direction == "out":
                query = """
                    SELECT n.id, n.kind, n.attrs_json, e.kind as edge_kind
                    FROM bootstrap_edges e
                    JOIN bootstrap_nodes n ON e.to_id = n.id
                    WHERE e.from_id = ?
                """
            elif direction == "in":
                query = """
                    SELECT n.id, n.kind, n.attrs_json, e.kind as edge_kind
                    FROM bootstrap_edges e
                    JOIN bootstrap_nodes n ON e.from_id = n.id
                    WHERE e.to_id = ?
                """
            else:  # both
                query = """
                    SELECT n.id, n.kind, n.attrs_json, e.kind as edge_kind
                    FROM bootstrap_edges e
                    JOIN bootstrap_nodes n ON (e.to_id = n.id AND e.from_id = ?)
                    UNION
                    SELECT n.id, n.kind, n.attrs_json, e.kind as edge_kind
                    FROM bootstrap_edges e
                    JOIN bootstrap_nodes n ON (e.from_id = n.id AND e.to_id = ?)
                """
                with conn.execute(query, (node_id, node_id)) as cursor:
                    rows = cursor.fetchall()
                return [{"id": r[0], "kind": r[1], "attrs": json.loads(r[2]), "edge_kind": r[3]} for r in rows]

            with conn.execute(query, (node_id,)) as cursor:
                rows = cursor.fetchall()
            return [{"id": r[0], "kind": r[1], "attrs": json.loads(r[2]), "edge_kind": r[3]} for r in rows]

        async with self._read_lock:
            result = await asyncio.to_thread(_fetch, self._read_conn)
        return json.dumps(result)

    async def _find_nodes(self, match: dict) -> str:
        kind = match.get("kind")

        def _fetch(conn: sqlite3.Connection) -> list[dict]:
            if kind:
                with conn.execute(
                    "SELECT id, kind, attrs_json FROM bootstrap_nodes WHERE kind = ?",
                    (kind,),
                ) as cursor:
                    rows = cursor.fetchall()
            else:
                with conn.execute("SELECT id, kind, attrs_json FROM bootstrap_nodes") as cursor:
                    rows = cursor.fetchall()

            results = []
            for row in rows:
                attrs = json.loads(row[2])
                # Filter by additional attrs (equality)
                if all(attrs.get(k) == v for k, v in match.items() if k != "kind"):
                    results.append({"id": row[0], "kind": row[1], "attrs": attrs})
            return results

        async with self._read_lock:
            result = await asyncio.to_thread(_fetch, self._read_conn)
        return json.dumps(result)

    # ── Writes ─────────────────────────────────────────────────────────────

    async def write(self, op: str, data: dict) -> str:
        """Dispatch a write operation.

        Op shapes:
          "add_node"  data = {"kind": str, "attrs": dict, "id"?: str}
          "add_edge"  data = {"from": str, "to": str, "kind": str, "attrs"?: dict}
        """
        if op == "add_node":
            return await self._add_node(data)
        if op == "add_edge":
            return await self._add_edge(data)
        raise ValueError(f"Unknown graph write op: {op!r}")

    async def _add_node(self, data: dict) -> str:
        node_id = data.get("id") or str(uuid.uuid4())
        kind = data["kind"]
        attrs = data.get("attrs", {})
        attrs_json = json.dumps(attrs)

        def _exec(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO bootstrap_nodes (id, kind, attrs_json) VALUES (?, ?, ?)",
                (node_id, kind, attrs_json),
            )

        async with self._write_lock:
            await asyncio.to_thread(_exec, self._write_conn)

        return json.dumps({"id": node_id, "kind": kind})

    async def _add_edge(self, data: dict) -> str:
        from_id = data["from"]
        to_id = data["to"]
        kind = data["kind"]
        attrs = data.get("attrs", {})
        attrs_json = json.dumps(attrs)

        def _exec(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO bootstrap_edges (from_id, to_id, kind, attrs_json) VALUES (?, ?, ?, ?)",
                (from_id, to_id, kind, attrs_json),
            )

        async with self._write_lock:
            await asyncio.to_thread(_exec, self._write_conn)

        return json.dumps({"from": from_id, "to": to_id, "kind": kind})
```

### 3.3 Expose BootstrapGraphStore on EventStore

In `core/store/event_store.py`, after the `NodeStore` initialization block inside
`initialize()`, add:

```python
# After: self._node_store = NodeStore(...)
from remora.bootstrap.graph_store import BootstrapGraphStore
self._bootstrap_graph = BootstrapGraphStore(
    read_conn=self._read_conn,
    read_lock=self._read_lock,
    write_conn=self._conn,
    write_lock=self._lock,
)
```

Add a property (alongside the `nodes` property):
```python
@property
def bootstrap_graph(self) -> "BootstrapGraphStore":
    if self._bootstrap_graph is None:
        raise RuntimeError("EventStore not initialized")
    return self._bootstrap_graph
```

Also add the type annotation in `__init__`: `self._bootstrap_graph: BootstrapGraphStore | None = None`

And clear it in `close()`: `self._bootstrap_graph = None`

### 3.4 Build the bedrock: `src/remora/bootstrap/bedrock.py`

```python
"""Bootstrap bedrock: the six async functions.

build_bedrock() is called once per agent activation.
It returns a dict of six async callables that form the
bedrock layer for that agent's Grail tool execution.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from remora.core.agents.cairn_externals import CairnExternals
from remora.bootstrap.graph_store import BootstrapGraphStore


@dataclass
class BootstrapEvent:
    """Minimal event model for bootstrap-emitted events."""
    event_type: str
    node_id: str | None = None
    payload: dict = field(default_factory=dict)
    from_agent: str | None = None
    timestamp: float = field(default_factory=time.time)


def build_bedrock(
    *,
    agent_id: str,
    cairn_externals: CairnExternals,
    graph_store: BootstrapGraphStore,
    event_store: Any,   # EventStore — Any to avoid circular import
    swarm_id: str,
) -> dict[str, Any]:
    """Build the six bedrock functions for one agent activation.

    Returns a dict suitable for injection as the Grail externals dict.
    Bootstrap .pym tools declare @external on these names.
    """

    # ── Workspace channel ──────────────────────────────────────────────────

    async def _cairn_read(path: str) -> str:
        result = await cairn_externals.read_file(path)
        # CairnExternals.read_file returns str; empty string if not found
        return result or ""

    async def _cairn_write(path: str, content: str) -> str:
        await cairn_externals.write_file(path, content)
        return "ok"

    # ── Graph channel ──────────────────────────────────────────────────────

    async def _graph_read(selector: dict) -> str:
        return await graph_store.read(selector)

    async def _graph_write(op: str, data: dict) -> str:
        return await graph_store.write(op, data)

    # ── Event channel ──────────────────────────────────────────────────────

    async def _event_read(selector: dict) -> str:
        node_id = selector.get("node_id", agent_id)
        limit = selector.get("limit", 10)
        events = await event_store.get_recent_events(node_id, limit=limit)
        return json.dumps(events)

    async def _event_write(event_type: str, payload: dict) -> str:
        event = BootstrapEvent(
            event_type=event_type,
            node_id=payload.get("node_id"),
            payload=payload,
            from_agent=agent_id,
        )
        event_id = await event_store.append(swarm_id, event)
        return json.dumps({"event_id": event_id})

    return {
        "_cairn_read":  _cairn_read,
        "_cairn_write": _cairn_write,
        "_graph_read":  _graph_read,
        "_graph_write": _graph_write,
        "_event_read":  _event_read,
        "_event_write": _event_write,
    }
```

---

## 4. M1: System Tools (.pym)

### 4.1 How discover_grail_tools() is extended

In `core/tools/grail.py`, extend `discover_grail_tools()` to accept an optional
second directory:

```python
def discover_grail_tools(
    agents_dir: Path,
    *,
    context: AgentContext | None = None,      # None when using bootstrap bedrock
    externals: dict[str, Any] | None = None,  # NEW: bootstrap externals dict
    files_provider: FilesProvider,
    workspace_tools_dir: Path | None = None,  # NEW: agent's workspace/tools/
    limits: grail.Limits | None = None,
    grail_dir: str | Path | None = None,
) -> list[RemoraGrailTool | SwarmTool]:
```

When `externals` is provided directly (bootstrap mode), skip the
`context.as_externals()` call. When `workspace_tools_dir` is provided,
scan it after `agents_dir` (workspace tools may shadow system tools by name).

Bootstrap callers pass:
```python
tools = discover_grail_tools(
    bootstrap_tools_dir,
    externals=bedrock_dict,
    files_provider=files_provider,
    workspace_tools_dir=agent_workspace_path / "tools",
)
```

### 4.2 System tool files

Each tool has one public function (the tool name), one or more `@external`
declarations on bedrock names, and a docstring the LLM sees.

**`bootstrap/tools/read_file.pym`**
```python
@external
async def _cairn_read(path: str) -> str: ...

async def read_file(path: str) -> str:
    """Read a file from this agent's workspace.
    Falls back to the stable (shared) workspace if the file is not in the
    agent's own workspace. Returns empty string if not found."""
    return await _cairn_read(path)
```

**`bootstrap/tools/write_file.pym`**
```python
@external
async def _cairn_write(path: str, content: str) -> str: ...

async def write_file(path: str, content: str) -> str:
    """Write a file to this agent's workspace.
    Creates the file if it does not exist; overwrites if it does.
    Returns 'ok'."""
    return await _cairn_write(path, content)
```

**`bootstrap/tools/graph_node.pym`**
```python
@external
async def _graph_read(selector: dict) -> str: ...

import json

async def graph_node(node_id: str) -> str:
    """Get a single node from the shared graph by ID.
    Returns JSON: {"id": str, "kind": str, "attrs": dict} or null if not found."""
    return await _graph_read({"node": node_id})
```

**`bootstrap/tools/graph_neighbors.pym`**
```python
@external
async def _graph_read(selector: dict) -> str: ...

async def graph_neighbors(node_id: str, direction: str) -> str:
    """Get the neighbors of a node.
    direction: 'in' | 'out' | 'both'
    Returns JSON array of {id, kind, attrs, edge_kind} objects."""
    return await _graph_read({"neighbors": node_id, "dir": direction})
```

**`bootstrap/tools/graph_find_nodes.pym`**
```python
@external
async def _graph_read(selector: dict) -> str: ...

async def graph_find_nodes(kind: str) -> str:
    """Find all nodes in the graph with the given kind.
    Returns JSON array of {id, kind, attrs} objects."""
    return await _graph_read({"match": {"kind": kind}})
```

**`bootstrap/tools/graph_add_node.pym`**
```python
@external
async def _graph_write(op: str, data: dict) -> str: ...

async def graph_add_node(kind: str, attrs: dict) -> str:
    """Add a node to the shared graph.
    kind: the node type (e.g. 'module', 'agent', 'task')
    attrs: arbitrary JSON attributes
    Returns JSON: {"id": str, "kind": str} with the generated ID."""
    return await _graph_write("add_node", {"kind": kind, "attrs": attrs})
```

**`bootstrap/tools/graph_add_edge.pym`**
```python
@external
async def _graph_write(op: str, data: dict) -> str: ...

async def graph_add_edge(from_id: str, to_id: str, kind: str) -> str:
    """Add a directed edge to the shared graph.
    from_id, to_id: node IDs (must already exist)
    kind: edge type (e.g. 'calls', 'imports', 'assigned_to')
    Returns JSON: {"from": str, "to": str, "kind": str}."""
    return await _graph_write("add_edge", {"from": from_id, "to": to_id, "kind": kind})
```

**`bootstrap/tools/read_recent_events.pym`**
```python
@external
async def _event_read(selector: dict) -> str: ...

async def read_recent_events(node_id: str, limit: int) -> str:
    """Read recent events involving a node (as sender or target).
    Returns JSON array of event dicts, newest first."""
    return await _event_read({"node_id": node_id, "limit": limit})
```

**`bootstrap/tools/emit_event.pym`**
```python
@external
async def _event_write(event_type: str, payload: dict) -> str: ...

async def emit_event(event_type: str, payload: dict) -> str:
    """Emit an event to the shared event log.
    Notifies any agents subscribed to this event_type + node_id.
    Returns JSON: {"event_id": int}."""
    return await _event_write(event_type, payload)
```

### 4.3 Files provider for bootstrap tools

Bootstrap tools do not need the Cairn virtual filesystem for their own
execution (they use bedrock externals). The `files_provider` passed to
`RemoraGrailTool` should return the agent's workspace files for any tool
that might read from the Grail virtual FS:

```python
async def _make_files_provider(cairn_externals: CairnExternals):
    async def files_provider() -> dict[str, str | bytes]:
        # List all files in the agent workspace and return them
        # For bootstrap tools this is rarely used but required by RemoraGrailTool
        try:
            paths = await cairn_externals.list_dir(".")
            files = {}
            for path in paths:
                try:
                    content = await cairn_externals.read_file(path)
                    files[path] = content
                except Exception:
                    pass
            return files
        except Exception:
            return {}
    return files_provider
```

---

## 5. M2: Turn Executor

### 5.1 TurnSchema and schema_loader: `src/remora/bootstrap/schema_loader.py`

```python
"""Bootstrap schema.yaml loader.

TurnSchema is the Pydantic model for a schema.yaml file.
load_schema() reads workspace/schema.yaml, resolves extends:, falls back to DEFAULT_SCHEMA.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# ── DEFAULT_SCHEMA ─────────────────────────────────────────────────────────
# Embedded — never relies on an external file being present.

DEFAULT_SCHEMA_YAML = """
version: "1"
name: bootstrap_default

system: |
  You are a Remora bootstrap agent. Your workspace is empty.

  Read your activation context. Decide what you are responsible for.
  Then do the following before ending your turn:
    1. Call write_file("role.md", <your role description>).
    2. Call write_file("notes.md", <initial notes about this node>).
    3. Call write_file("schema.yaml", <your turn definition for future activations>).

  When you have completed these three writes, output: DONE

context: []

tools:
  - read_file
  - write_file

max_turns: 5
termination: "DONE"
""".strip()


# ── Pydantic models ────────────────────────────────────────────────────────


class ContextStep(BaseModel):
    """One step in the context pipeline."""
    name: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False


class SubscriptionSpec(BaseModel):
    """One event subscription declared in schema.yaml."""
    event_type: str
    node_id: str | None = None


class TurnSchema(BaseModel):
    """Parsed and validated schema.yaml."""
    version: str = "1"
    name: str = "unnamed"
    system: str = ""
    context: list[ContextStep] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    subscriptions: list[SubscriptionSpec] = Field(default_factory=list)
    max_turns: int = 5
    termination: str = "DONE"
    extends: str | None = None


# ── Loader ─────────────────────────────────────────────────────────────────


def _load_yaml(text: str) -> dict:
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def _merge_schemas(base: dict, child: dict) -> dict:
    """Shallow merge: child overrides base. context/tools lists are appended."""
    merged = dict(base)
    for key, value in child.items():
        if key == "extends":
            continue
        if key in ("context", "tools", "subscriptions") and key in merged:
            base_list = merged[key] if isinstance(merged[key], list) else []
            child_list = value if isinstance(value, list) else []
            merged[key] = base_list + child_list
        else:
            merged[key] = value
    return merged


def load_schema(
    workspace_root: Path,
    *,
    system_agents_dir: Path | None = None,
) -> TurnSchema:
    """Load schema.yaml from the agent workspace.

    Resolution order:
    1. workspace_root / schema.yaml  (agent-written)
    2. Resolve extends: one level from system_agents_dir
    3. DEFAULT_SCHEMA if no schema.yaml present

    Returns a validated TurnSchema.
    """
    schema_path = workspace_root / "schema.yaml"

    if not schema_path.exists():
        return TurnSchema.model_validate(_load_yaml(DEFAULT_SCHEMA_YAML))

    child_data = _load_yaml(schema_path.read_text(encoding="utf-8"))

    extends = child_data.get("extends")
    if extends and system_agents_dir:
        base_path = system_agents_dir / f"{extends}.yaml"
        if base_path.exists():
            base_data = _load_yaml(base_path.read_text(encoding="utf-8"))
            child_data = _merge_schemas(base_data, child_data)

    return TurnSchema.model_validate(child_data)
```

### 5.2 Template variable resolution

Template variables are resolved in two passes:

**Pass 1 — `{node.*}` variables** (resolved before context pipeline runs):
```python
def _resolve_node_vars(text: str, node_attrs: dict[str, Any]) -> str:
    """Replace {node.field} with values from the graph node's attrs dict."""
    import re
    def replacer(m: re.Match) -> str:
        field = m.group(1)
        return str(node_attrs.get(field, m.group(0)))
    return re.sub(r'\{node\.([^}]+)\}', replacer, text)
```

**Pass 2 — `{{name}}` variables** (resolved after context pipeline):
```python
def _resolve_context_vars(text: str, context_values: dict[str, str]) -> str:
    """Replace {{name}} with values from the assembled context pipeline."""
    import re
    def replacer(m: re.Match) -> str:
        key = m.group(1)
        return context_values.get(key, "")
    return re.sub(r'\{\{([^}]+)\}\}', replacer, text)
```

### 5.3 TurnExecutor: `src/remora/bootstrap/turn_executor.py`

```python
"""Bootstrap turn executor.

Loads schema.yaml, runs context pipeline, dispatches to LLM kernel,
handles tool calls using the bootstrap bedrock externals.
Runs in parallel to v1's execute_agent_turn() — not a replacement.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from structured_agents import Message, build_client

from remora.core.agents.kernel_factory import create_kernel
from remora.bootstrap.schema_loader import TurnSchema, load_schema

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    response_text: str
    context_values: dict[str, str] = field(default_factory=dict)
    events_emitted: int = 0


class TurnExecutor:
    """Run one agent activation using schema.yaml + bootstrap bedrock.

    Usage:
        executor = TurnExecutor(
            agent_id="my-module-agent",
            workspace_root=Path("/path/to/workspace"),
            tools=tools,          # list[RemoraGrailTool] from discover_grail_tools
            bedrock=bedrock_dict, # from build_bedrock()
            node_attrs={...},     # from graph_node query (or activation event)
            config=config,
        )
        result = await executor.run(activation_event)
    """

    def __init__(
        self,
        *,
        agent_id: str,
        workspace_root: Path,
        tools: list[Any],
        bedrock: dict[str, Any],
        node_attrs: dict[str, Any],
        config: Any,               # remora.core.config.Config
        system_agents_dir: Path | None = None,
        client: Any | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._workspace_root = workspace_root
        self._tools = tools
        self._bedrock = bedrock
        self._node_attrs = node_attrs
        self._config = config
        self._system_agents_dir = system_agents_dir
        self._client = client

    async def run(self, activation_event: Any = None) -> TurnResult:
        """Execute one agent turn."""
        schema = load_schema(
            self._workspace_root,
            system_agents_dir=self._system_agents_dir,
        )

        context_values = await self._run_context_pipeline(schema)
        system_prompt = self._build_system_prompt(schema, context_values)
        user_prompt = self._build_user_prompt(activation_event)

        tool_schemas = [t.schema for t in self._tools
                        if t.schema.name in schema.tools]

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        if self._client is None:
            self._client = build_client({
                "base_url": self._config.model_base_url,
                "api_key": self._config.model_api_key or "EMPTY",
                "model": self._config.model_default,
                "timeout": self._config.timeout_s,
            })

        kernel = create_kernel(
            model_name=self._config.model_default,
            base_url=self._config.model_base_url,
            api_key=self._config.model_api_key or "EMPTY",
            timeout=self._config.timeout_s,
            tools=self._tools,
            observer=None,
        )

        try:
            result = await kernel.run(messages, tool_schemas, max_turns=schema.max_turns)
        finally:
            await kernel.close()

        response_text = self._extract_response(result)
        return TurnResult(
            response_text=response_text,
            context_values=context_values,
        )

    async def _run_context_pipeline(self, schema: TurnSchema) -> dict[str, str]:
        """Execute context pipeline steps, collecting named values."""
        values: dict[str, str] = {}
        tool_map = {t.schema.name: t for t in self._tools}

        for step in schema.context:
            tool = tool_map.get(step.tool)
            if tool is None:
                if not step.optional:
                    logger.warning("Context pipeline: tool %r not found", step.tool)
                values[step.name] = ""
                continue

            # Resolve {node.*} in args
            resolved_args = {
                k: self._resolve_node_vars(str(v)) if isinstance(v, str) else v
                for k, v in step.args.items()
            }

            try:
                result = await tool.execute(resolved_args, context=None)
                values[step.name] = result.output if not result.is_error else ""
            except Exception:
                if not step.optional:
                    logger.warning("Context pipeline step %r failed", step.name, exc_info=True)
                values[step.name] = ""

        return values

    def _build_system_prompt(self, schema: TurnSchema, context_values: dict[str, str]) -> str:
        text = self._resolve_node_vars(schema.system)
        text = _resolve_context_vars(text, context_values)
        return text

    def _build_user_prompt(self, activation_event: Any) -> str:
        if activation_event is None:
            return "Begin your turn."
        event_type = getattr(activation_event, "event_type", type(activation_event).__name__)
        node_id = getattr(activation_event, "node_id", None)
        parts = [f"Activation event: {event_type}"]
        if node_id:
            parts.append(f"Node: {node_id}")
        return "\n".join(parts)

    def _resolve_node_vars(self, text: str) -> str:
        def replacer(m: re.Match) -> str:
            field = m.group(1)
            return str(self._node_attrs.get(field, m.group(0)))
        return re.sub(r'\{node\.([^}]+)\}', replacer, text)

    @staticmethod
    def _extract_response(result: Any) -> str:
        if hasattr(result, "final_message") and result.final_message:
            msg = result.final_message
            return msg.content if hasattr(msg, "content") and msg.content else str(result)
        if hasattr(result, "content") and result.content:
            return result.content
        return str(result)


def _resolve_context_vars(text: str, context_values: dict[str, str]) -> str:
    def replacer(m: re.Match) -> str:
        key = m.group(1)
        return context_values.get(key, "")
    return re.sub(r'\{\{([^}]+)\}\}', replacer, text)
```

---

## 6. M3: Self-Bootstrapping Loop

### 6.1 Base YAML schemas

**`bootstrap/agents/DEFAULT_SCHEMA.yaml`** (mirrors the embedded DEFAULT_SCHEMA constant):
```yaml
version: "1"
name: bootstrap_default

system: |
  You are a Remora bootstrap agent. Your workspace is empty.

  Read your activation context. Decide what you are responsible for.
  Then do the following before ending your turn:
    1. Call write_file("role.md", <your role description>).
    2. Call write_file("notes.md", <initial notes about this node>).
    3. Call write_file("schema.yaml", <your turn definition for future activations>).

  When you have completed these three writes, output: DONE

context: []

tools:
  - read_file
  - write_file

max_turns: 5
termination: "DONE"
```

**`bootstrap/agents/base_code_agent.yaml`**:
```yaml
version: "1"
name: base_code_agent

system: |
  You are a Remora code agent responsible for {node.full_name}.
  {{role}}
  {{notes}}

context:
  - name: role
    tool: read_file
    args:
      path: role.md
    optional: true

  - name: notes
    tool: read_file
    args:
      path: notes.md
    optional: true

  - name: source
    tool: read_file
    args:
      path: "{node.file_path}"
    optional: true

tools:
  - read_file
  - write_file
  - graph_node
  - graph_neighbors
  - emit_event

subscriptions:
  - event_type: ContentChangedEvent
    node_id: "{node.id}"

max_turns: 8
termination: "DONE"
```

### 6.2 Bootstrap loop: activation flow

The self-bootstrapping loop is driven by the existing `SubscriptionRegistry` +
`EventStore` trigger queue (already in v1). The bootstrap adds two pieces:

**Step A — New agent workspace creation**

When the bootstrap runtime processes an `AgentNeededEvent`, it:
1. Creates an agent workspace via `CairnWorkspaceService.get_agent_workspace(agent_id)`
2. Registers default subscriptions via `SubscriptionRegistry.register_defaults(agent_id, node_id)`
3. Activates the agent with DEFAULT_SCHEMA (because workspace is empty)

```python
# In bootstrap runtime (not yet built — placeholder for M3)
async def handle_agent_needed(event: Any, workspace_service, subscriptions, ...) -> None:
    agent_id = event.payload["agent_id"]
    node_id  = event.payload["node_id"]

    workspace = await workspace_service.get_agent_workspace(agent_id)
    await subscriptions.register(agent_id, SubscriptionPattern(
        event_types=["ContentChangedEvent"],
        # node_id matching via tags or a custom field — see §6.3
    ))

    # Activate with TurnExecutor — workspace is empty so DEFAULT_SCHEMA kicks in
    bedrock = build_bedrock(
        agent_id=agent_id,
        cairn_externals=workspace_service.get_externals(agent_id, workspace),
        graph_store=event_store.bootstrap_graph,
        event_store=event_store,
        swarm_id=swarm_id,
    )
    tools = discover_grail_tools(
        bootstrap_tools_dir,
        externals=bedrock,
        files_provider=_make_files_provider(workspace_service.get_externals(agent_id, workspace)),
        workspace_tools_dir=workspace.path / "tools",
    )
    executor = TurnExecutor(
        agent_id=agent_id,
        workspace_root=workspace.path,
        tools=tools,
        bedrock=bedrock,
        node_attrs={"id": node_id, ...},
        config=config,
    )
    await executor.run(event)
```

**Step B — Subsequent activations**

On subsequent activations the same flow runs, but `load_schema()` now finds
`schema.yaml` in the workspace (written by the agent in its first activation)
and loads it instead of DEFAULT_SCHEMA. The agent runs as it defined itself.

### 6.3 Coordinator agent: schema.yaml

The coordinator is seeded with this schema.yaml (written to its workspace
after graph seeding completes):

```yaml
version: "1"
name: coordinator

system: |
  You are the Remora bootstrap coordinator.
  You survey the code graph and ensure every module node has an assigned agent.
  {{notes}}

context:
  - name: notes
    tool: read_file
    args:
      path: notes.md
    optional: true

  - name: unassigned
    tool: graph_find_nodes
    args:
      kind: module

tools:
  - read_file
  - write_file
  - graph_find_nodes
  - graph_add_node
  - graph_add_edge
  - emit_event

subscriptions:
  - event_type: AgentNeededEvent
  - event_type: ToolSynthesizedEvent

max_turns: 10
termination: "DONE"
```

The coordinator inspects `{{unassigned}}` (JSON list of module nodes), checks
which ones lack an `assigned_agent` attr, and emits `AgentNeededEvent` for each.

---

## 7. M4: Graph Seeding

### 7.1 `src/remora/bootstrap/seed_graph.py`

A one-time script that populates `bootstrap_nodes` and `bootstrap_edges` from
the Remora source tree. It calls `BootstrapGraphStore.write()` directly — this
is the one place where bedrock is called outside of a Grail tool.

```python
"""Bootstrap graph seeding.

Walks the remora source tree and populates bootstrap_nodes + bootstrap_edges.
Run once before starting the bootstrap swarm.

Usage:
    devenv shell -- python -m remora.bootstrap.seed_graph
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from remora.bootstrap.graph_store import BootstrapGraphStore
from remora.core.store.event_store import EventStore

logger = logging.getLogger(__name__)


async def seed_from_node_store(
    event_store: EventStore,
    *,
    swarm_id: str,
) -> int:
    """Seed bootstrap_nodes + bootstrap_edges from the v1 NodeStore.

    Reads existing AgentNode entries from the nodes table and mirrors
    them into bootstrap_nodes with kind=node_type. Also mirrors caller/callee
    relationships as bootstrap_edges with kind='calls'.

    Returns the number of nodes seeded.
    """
    graph = event_store.bootstrap_graph
    node_store = event_store.nodes

    nodes = await node_store.list_nodes()
    count = 0

    for node in nodes:
        await graph.write("add_node", {
            "id": node.node_id,
            "kind": node.node_type,
            "attrs": {
                "name":      node.name,
                "full_name": node.full_name,
                "file_path": node.file_path,
                "start_line": node.start_line,
                "end_line":   node.end_line,
            },
        })
        count += 1

    # Mirror call edges
    for node in nodes:
        for callee_id in node.callee_ids:
            try:
                await graph.write("add_edge", {
                    "from": node.node_id,
                    "to":   callee_id,
                    "kind": "calls",
                })
            except Exception:
                logger.debug("Edge add failed %s -> %s", node.node_id, callee_id)

    logger.info("Seeded %d bootstrap nodes from NodeStore", count)
    return count


async def seed_from_filesystem(
    event_store: EventStore,
    project_root: Path,
    *,
    swarm_id: str,
) -> int:
    """Fallback seeder: walk the filesystem and create module-level nodes.

    Used when the v1 NodeStore has not yet been populated (fresh install).
    Creates one 'module' node per Python file.
    """
    graph = event_store.bootstrap_graph
    count = 0

    for py_file in sorted(project_root.rglob("*.py")):
        # Skip virtual environments and build artifacts
        parts = py_file.relative_to(project_root).parts
        if any(p in (".venv", ".devenv", "__pycache__", "dist", "build") for p in parts):
            continue

        rel_path = py_file.relative_to(project_root).as_posix()
        # Derive module full_name from file path
        module_path = rel_path.replace("/", ".").removesuffix(".py").removeprefix("src.")
        node_id = rel_path.replace("/", "_").replace(".", "_")

        await graph.write("add_node", {
            "id": node_id,
            "kind": "module",
            "attrs": {
                "name":      py_file.stem,
                "full_name": module_path,
                "file_path": rel_path,
            },
        })
        count += 1

    logger.info("Seeded %d module nodes from filesystem", count)
    return count


if __name__ == "__main__":
    import sys
    from remora.core.config import Config
    from remora.core.store.event_store import EventStore

    logging.basicConfig(level=logging.INFO)
    project_root = Path.cwd()
    db_path = project_root / ".remora" / "event_store.db"

    async def main() -> None:
        event_store = EventStore(db_path)
        await event_store.initialize()
        try:
            n = await seed_from_node_store(event_store, swarm_id="bootstrap")
            if n == 0:
                n = await seed_from_filesystem(event_store, project_root, swarm_id="bootstrap")
            print(f"Seeded {n} nodes.")
        finally:
            await event_store.close()

    asyncio.run(main())
```

### 7.2 Node kinds and edge kinds for code topology

| Kind | Used for | Key attrs |
|------|----------|-----------|
| `module` | Python file | `name`, `full_name`, `file_path` |
| `class` | Python class | `name`, `full_name`, `file_path`, `start_line`, `end_line` |
| `function` | Python function/method | `name`, `full_name`, `file_path`, `start_line`, `end_line` |
| `agent` | Bootstrap agent | `agent_id`, `role`, `node_id` (assigned module) |
| `task` | Work item | `title`, `status`, `assigned_to` |

| Edge kind | Meaning |
|-----------|---------|
| `calls` | function A calls function B |
| `imports` | module A imports module B |
| `parent_of` | class/module A contains function B |
| `assigned_to` | agent A is assigned to node B |
| `produced` | agent A produced task B |

---

## 8. M5: Companion Visibility

### 8.1 The workspace sidebar

The companion sidebar needs a new section that shows the agent's workspace
files. This is workspace-as-identity made visible: developers see exactly
what the agent knows and how it defines itself.

No new protocol is required. The companion already has access to the
`CairnWorkspaceService` at runtime. Reading workspace files is `read_file`
on the agent's cairn workspace.

### 8.2 Sidebar panels

Add to `companion/sidebar/composer.py` (or create `companion/sidebar/workspace.py`):

```python
"""Bootstrap workspace panels for the companion sidebar.

Five panels reading from the agent's cairn workspace:
  ROLE    — role.md (plain text)
  SCHEMA  — schema.yaml (parsed, key sections highlighted)
  NOTES   — notes.md (plain text, scrollable)
  TODO    — todo.md (markdown checklist)
  LOG     — log.jsonl (last N entries, newest first)
  TOOLS   — workspace/tools/*.pym (list + content on expand)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class WorkspacePanel:
    key: str          # "role" | "schema" | "notes" | "todo" | "log" | "tools"
    title: str
    content: str      # Rendered markdown or plain text for display
    is_empty: bool    # True when backing file is absent


async def build_workspace_panels(
    cairn_externals: Any,   # CairnExternals for the agent
) -> list[WorkspacePanel]:
    """Build all workspace panels for one agent."""
    panels = []

    async def _read(path: str) -> tuple[str, bool]:
        try:
            content = await cairn_externals.read_file(path)
            return content or "", not bool(content)
        except Exception:
            return "", True

    # ROLE
    content, empty = await _read("role.md")
    panels.append(WorkspacePanel("role", "Role", content, empty))

    # SCHEMA
    content, empty = await _read("schema.yaml")
    panels.append(WorkspacePanel("schema", "Schema", content, empty))

    # NOTES
    content, empty = await _read("notes.md")
    panels.append(WorkspacePanel("notes", "Notes", content, empty))

    # TODO
    content, empty = await _read("todo.md")
    panels.append(WorkspacePanel("todo", "Todo", content, empty))

    # LOG — last 20 lines of log.jsonl
    content, empty = await _read("log.jsonl")
    if not empty:
        lines = [l for l in content.splitlines() if l.strip()]
        content = "\n".join(lines[-20:])
    panels.append(WorkspacePanel("log", "Log", content, empty))

    # TOOLS — list workspace/tools/*.pym names
    try:
        tool_files = await cairn_externals.list_dir("tools")
        pym_files = [f for f in (tool_files or []) if f.endswith(".pym")]
        if pym_files:
            tool_content = "\n".join(f"- `{f}`" for f in sorted(pym_files))
        else:
            tool_content = ""
        panels.append(WorkspacePanel("tools", "Tools", tool_content, not bool(pym_files)))
    except Exception:
        panels.append(WorkspacePanel("tools", "Tools", "", True))

    return panels
```

### 8.3 Sidebar refresh

Workspace panels refresh when:
- An agent turn completes (activation end event)
- The developer explicitly selects a different agent

The existing event bus (`EventBus`) already notifies the companion on relevant
events. Add a handler for `AgentActivationEndEvent` (or the equivalent v1
event) to trigger a sidebar refresh.

### 8.4 ASCII mockup

```
┌────────────────────────────────────────────────────┐
│  REMORA COMPANION                      [agent id]  │
├────────────────────────────────────────────────────┤
│  ● ROLE                                            │
│  I am responsible for core/events/events.py.       │
│  My job is to monitor changes and update the       │
│  bootstrap graph when the event taxonomy changes.  │
├────────────────────────────────────────────────────┤
│  ● SCHEMA                           [schema.yaml]  │
│  name: events_module_agent                         │
│  tools: read_file, write_file, graph_neighbors...  │
│  subscriptions: ContentChangedEvent                │
├────────────────────────────────────────────────────┤
│  ● NOTES                                           │
│  2026-03-07: This module has 33 callers. Primary   │
│  consumers are runner and companion. High in-deg.  │
├────────────────────────────────────────────────────┤
│  ● TODO                                            │
│  [x] Write role.md                                 │
│  [x] Write schema.yaml                             │
│  [ ] Emit GraphUpdatedEvent after next change      │
├────────────────────────────────────────────────────┤
│  ● LOG  (last 3)                                   │
│  {"activation": 4, "event": "ContentChangedEvent"} │
│  {"activation": 3, "event": "ContentChangedEvent"} │
│  {"activation": 2, "event": "ContentChangedEvent"} │
├────────────────────────────────────────────────────┤
│  ● TOOLS                                           │
│  - `event_context.pym`                             │
└────────────────────────────────────────────────────┘
```

---

## 9. M6: Tool Synthesis

### 9.1 Writing a synthesized tool from within a turn

An agent writes a `.pym` file to `tools/<name>.pym` in its workspace using
the `write_file` tool. The Grail syntax and `@external` constraints are the
same as system tools, except the declarations reference system tool function
names (not bedrock names):

```python
# Agent writes this to workspace/tools/node_context.pym

@external
async def read_file(path: str) -> str: ...

@external
async def graph_node(node_id: str) -> str: ...

@external
async def graph_neighbors(node_id: str, direction: str) -> str: ...

import json

async def node_context(node_id: str) -> str:
    """Return full context for a node: source code, graph metadata, callers, callees.
    Returns JSON with keys: source, node, callers, callees."""
    node    = json.loads(await graph_node(node_id))
    source  = await read_file(node["attrs"]["file_path"])
    callers = json.loads(await graph_neighbors(node_id, "in"))
    callees = json.loads(await graph_neighbors(node_id, "out"))
    return json.dumps({
        "source":  source,
        "node":    node,
        "callers": callers,
        "callees": callees,
    })
```

On the NEXT activation, `discover_grail_tools()` scans `workspace/tools/` and
compiles `node_context.pym`. The externals dict passed at that time will contain
the resolved `read_file`, `graph_node`, and `graph_neighbors` functions (compiled
system tools). `node_context` becomes available as a callable tool.

### 9.2 The @external boundary for synthesized tools

Synthesized tools live at the **system tool layer**, not the bedrock layer.
They must declare `@external` on system tool names, not on `_cairn_read`,
`_graph_write`, etc.

The Grail externals dict passed to synthesized tools contains ONLY the system
tool callables (the compiled `RemoraGrailTool.execute` functions, wrapped as
plain async callables). The bedrock names are NOT present in this dict.

This means the compiler enforces the boundary: a synthesized tool that tries
to declare `@external` on `_cairn_read` will compile but fail at runtime
(key not in externals). The convention is documented in `schema.yaml` comments
and in the DEFAULT_SCHEMA system prompt.

### 9.3 Extending discover_grail_tools()

The extended signature (described in §4.1):

```python
def discover_grail_tools(
    agents_dir: Path,
    *,
    context: AgentContext | None = None,
    externals: dict[str, Any] | None = None,
    files_provider: FilesProvider,
    workspace_tools_dir: Path | None = None,
    limits: grail.Limits | None = None,
    grail_dir: str | Path | None = None,
) -> list[RemoraGrailTool | SwarmTool]:
```

Implementation changes:
1. If `externals` is provided, use it directly; else use `context.as_externals()`
2. After scanning `agents_dir`, if `workspace_tools_dir` exists:
   - Build a second externals dict containing only the system tools (not bedrock)
   - Scan `workspace_tools_dir/*.pym` and compile each with this second dict
   - Append to tools list; workspace tools shadow system tools by name if same name

```python
# After loading system tools:
if workspace_tools_dir and workspace_tools_dir.exists():
    # Build system-tool externals: name -> async callable wrapper
    system_externals = {
        tool.schema.name: _make_tool_callable(tool)
        for tool in tools
        if isinstance(tool, RemoraGrailTool)
    }
    for pym_file in sorted(workspace_tools_dir.glob("*.pym")):
        try:
            tools.append(RemoraGrailTool(
                pym_file,
                externals=system_externals,
                files_provider=files_provider,
                limits=limits,
                grail_dir=grail_dir,
            ))
        except Exception as exc:
            logger.warning("Failed to load workspace tool %s: %s", pym_file, exc)
```

Where `_make_tool_callable(tool)` wraps `tool.execute()` as a plain async function
that takes positional args matching the tool's schema:

```python
def _make_tool_callable(tool: RemoraGrailTool):
    async def _call(**kwargs) -> str:
        result = await tool.execute(kwargs, context=None)
        return result.output
    return _call
```

### 9.4 ToolSynthesizedEvent

When an agent writes a new `.pym` tool, it should emit a `ToolSynthesizedEvent`
so the coordinator can log it and potentially promote it to a system tool:

```python
# Agent calls:
await emit_event("ToolSynthesizedEvent", {
    "node_id":   "{node.id}",
    "tool_name": "node_context",
    "file_path": "tools/node_context.pym",
})
```

The coordinator's schema.yaml subscribes to `ToolSynthesizedEvent`.
Promotion to a system tool = the coordinator copies the `.pym` content
(via `read_file`) and records it in a graph node for future reference.
Actual file promotion to `bootstrap/tools/` requires a human decision.

---

## 10. Testing Plan

Run all tests with:
```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

### M0 tests: `tests/unit/bootstrap/test_bedrock.py`

```python
# Key invariants to test:

# 1. _cairn_read round-trip via CairnExternals mock
async def test_cairn_read_delegates_to_externals():
    ...

# 2. _cairn_write round-trip
async def test_cairn_write_delegates_to_externals():
    ...

# 3. _graph_read dispatches by selector shape
async def test_graph_read_get_node():
async def test_graph_read_get_neighbors_in():
async def test_graph_read_get_neighbors_out():
async def test_graph_read_find_nodes():

# 4. _graph_write dispatches by op
async def test_graph_write_add_node_generates_id():
async def test_graph_write_add_edge():

# 5. _event_read calls event_store.get_recent_events
async def test_event_read_calls_get_recent_events():

# 6. _event_write appends event and returns event_id
async def test_event_write_appends_and_returns_id():
```

### M0 tests: `tests/unit/bootstrap/test_graph_store.py`

```python
# Test BootstrapGraphStore against a live SQLite connection

async def test_add_node_and_get_node():
    # add_node returns {"id": ..., "kind": ...}
    # get_node returns the node with attrs
    ...

async def test_add_node_id_generated_if_absent():
    ...

async def test_add_node_id_preserved_if_provided():
    ...

async def test_get_neighbors_in():
    ...

async def test_get_neighbors_out():
    ...

async def test_get_neighbors_both():
    ...

async def test_find_nodes_by_kind():
    ...

async def test_find_nodes_by_attrs():
    ...
```

### M1 tests: `tests/unit/bootstrap/test_system_tools.py`

```python
# Each .pym file compiles successfully
def test_all_pym_files_compile():
    for pym_file in Path("bootstrap/tools").glob("*.pym"):
        script = grail.load(str(pym_file))
        assert script is not None

# Each tool declares @external on only bedrock names
def test_pym_externals_are_bedrock_names():
    bedrock_names = {"_cairn_read", "_cairn_write", "_graph_read",
                     "_graph_write", "_event_read", "_event_write"}
    for pym_file in Path("bootstrap/tools").glob("*.pym"):
        script = grail.load(str(pym_file))
        assert set(script.externals).issubset(bedrock_names), \
            f"{pym_file.name} declares non-bedrock external: {script.externals}"

# Full round-trip: tool callable with mocked bedrock
async def test_read_file_tool_calls_cairn_read():
    ...

async def test_emit_event_tool_calls_event_write():
    ...
```

### M2 tests: `tests/unit/bootstrap/test_schema_loader.py`

```python
# DEFAULT_SCHEMA parses without error
def test_default_schema_parses():
    schema = load_schema(Path("/nonexistent"))
    assert schema.termination == "DONE"
    assert "read_file" in schema.tools

# Agent-written schema.yaml is loaded
def test_agent_schema_loaded_when_present(tmp_path):
    (tmp_path / "schema.yaml").write_text("""
version: "1"
name: test_agent
system: "You are test."
tools: [read_file]
max_turns: 3
termination: "DONE"
""")
    schema = load_schema(tmp_path)
    assert schema.name == "test_agent"
    assert schema.max_turns == 3

# extends: merges base correctly
def test_extends_merges_base(tmp_path, bootstrap_agents_dir):
    (tmp_path / "schema.yaml").write_text("""
extends: base_code_agent
tools:
  - graph_add_edge
termination: "DONE"
""")
    schema = load_schema(tmp_path, system_agents_dir=bootstrap_agents_dir)
    # base_code_agent tools + graph_add_edge
    assert "read_file" in schema.tools
    assert "graph_add_edge" in schema.tools

# Malformed YAML returns validation error
def test_invalid_schema_raises(tmp_path):
    (tmp_path / "schema.yaml").write_text("not: yaml: valid: ??? [")
    with pytest.raises(Exception):
        load_schema(tmp_path)
```

### M2 tests: `tests/integration/bootstrap/test_turn_executor.py`

```python
# Full turn with mocked LLM: context assembled, tools called, turn ends
async def test_turn_executor_full_turn_mocked_llm(tmp_path, mock_client):
    # Write a simple schema.yaml
    # Run TurnExecutor
    # Assert context pipeline executed
    # Assert termination detected
    ...

# DEFAULT_SCHEMA used when workspace has no schema.yaml
async def test_turn_executor_uses_default_schema_for_empty_workspace(tmp_path, mock_client):
    # tmp_path has no schema.yaml
    # Run executor
    # Assert system prompt contains bootstrap default text
    ...

# Context pipeline skips optional missing steps
async def test_context_pipeline_optional_step_missing(tmp_path, mock_client):
    ...
```

### M3 tests: `tests/integration/bootstrap/test_bootstrap_loop.py`

```python
# Empty workspace → DEFAULT_SCHEMA → agent writes schema.yaml → next activation uses it
async def test_self_bootstrapping_loop(event_store, workspace_service, config):
    agent_id = "test-module-agent"
    # Activation 1: DEFAULT_SCHEMA, agent writes schema.yaml
    # Activation 2: load_schema() finds schema.yaml — not DEFAULT_SCHEMA
    ...
```

### M4 tests: `tests/unit/bootstrap/test_seed_graph.py`

```python
async def test_seed_from_filesystem_creates_module_nodes(tmp_path, event_store):
    (tmp_path / "foo.py").write_text("x = 1")
    (tmp_path / "bar.py").write_text("y = 2")
    n = await seed_from_filesystem(event_store, tmp_path, swarm_id="test")
    assert n == 2
    result = json.loads(await event_store.bootstrap_graph.read({"match": {"kind": "module"}}))
    assert len(result) == 2
```

### Summary: test file locations

```
tests/
  unit/
    bootstrap/
      test_bedrock.py
      test_graph_store.py
      test_system_tools.py
      test_schema_loader.py
      test_seed_graph.py
  integration/
    bootstrap/
      test_turn_executor.py
      test_bootstrap_loop.py
```

---

*End of IMPLEMENTATION_GUIDE.md*
