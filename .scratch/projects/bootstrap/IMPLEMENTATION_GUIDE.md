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
   `NodeStore` extended with generic graph methods and `graph_nodes` + `graph_edges` tables.
   Schema additions to `event_store_schema.py`. `build_bedrock()` factory.

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
   Why code topology requires no seeding — it's live in `NodeStore`.
   `src/remora/bootstrap/seed_graph.py` for non-code bootstrap nodes only.
   Node kinds and edge kinds reference.

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
| `_graph_read(selector)` | `NodeStore.read_graph(selector)` | **extend** NodeStore |
| `_graph_write(op, data)` | `NodeStore.write_graph(op, data)` | **extend** NodeStore |
| `_event_read(selector)` | `EventStore.get_recent_events()` | wrap in bedrock closure |
| `_event_write(event_type, payload)` | `EventStore.append(swarm_id, event)` | wrap in bedrock closure |
| `workspace` store | `CairnWorkspaceService` per-agent DB | reuse as-is |
| `graph` store — code nodes | `NodeStore` existing `nodes` table | **extend** with graph read methods |
| `graph` store — generic nodes | new `graph_nodes` + `graph_edges` tables in event_store.db | **extend** NodeStore |
| `events` store | `EventStore` (WAL SQLite) | reuse as-is |
| `SubscriptionRegistry` | `SubscriptionRegistry` | reuse as-is |
| `RemoraGrailTool` | `RemoraGrailTool` | reuse as-is |
| `discover_grail_tools()` | `discover_grail_tools()` | **extend** with workspace dir param |
| `schema.yaml` | `BundleManifest` / `load_manifest()` | **new** `TurnSchema` + `schema_loader.py` |
| `TurnExecutor` | `execute_agent_turn()` | **new** parallel implementation |
| `create_kernel()` | `create_kernel()` | reuse as-is |
| Companion sidebar workspace view | — | **new** sidebar panels |

### The unified graph: one NodeStore, two tables

The graph is accessible through a single object: `event_store.nodes` (the
existing `NodeStore`). It routes queries to the appropriate table:

```
NodeStore
  ├─ nodes table          ← code nodes (functions, classes, modules)
  │   Populated by v1 LSP scanner via NodeDiscoveredEvent projection.
  │   Read with: get_node(), list_nodes(), get_node_at_position()  [existing]
  │   Also readable via: read_graph({"match": {"kind": "function"}})  [new]
  │
  └─ graph_nodes table    ← generic nodes (agents, tasks, custom kinds)
      Populated by bootstrap agents via graph_add_node tool.
      Read with: read_graph({"node": id}), read_graph({"match": ...})  [new]

graph_edges table         ← edges for generic nodes only
  Code node topology uses caller_ids / callee_ids columns in the nodes table.
  Bootstrap coordination edges (assigned_to, produced, etc.) go here.
```

**Key routing rule**: `kind in CODE_NODE_KINDS` → query `nodes` table.
Everything else → query `graph_nodes` table.

```python
CODE_NODE_KINDS = frozenset({"function", "class", "method", "module", "file", "section"})
```

### What is NOT changed in v1

- `EventStore` — no logic changes; only new tables added to schema
- `CairnWorkspaceService` — unchanged
- `CairnExternals` — unchanged; bedrock closures call its methods
- `SubscriptionRegistry` / `SubscriptionPattern` — unchanged
- `RemoraGrailTool` — unchanged
- `AgentNode` — unchanged; still drives LSP features
- `execute_agent_turn()` — unchanged; bootstrap TurnExecutor runs alongside it

### What IS changed in v1

| File | Change |
|---|---|
| `core/store/event_store_schema.py` | Add `graph_nodes` + `graph_edges` tables |
| `core/store/node_store.py` | Add `read_graph()`, `write_graph()`, and private helpers |
| `core/tools/grail.py` | Add `workspace_tools_dir` + `externals` params to `discover_grail_tools()` |

### The bootstrap externals dict

Built once per agent activation by `build_bedrock()`. Injected as the Grail
externals dict instead of the v1 `AgentContext.as_externals()`:

```python
{
    "_cairn_read":  async (path: str) -> str,
    "_cairn_write": async (path: str, content: str) -> str,
    "_graph_read":  async (selector: dict) -> str,
    "_graph_write": async (op: str, data: dict) -> str,
    "_event_read":  async (selector: dict) -> str,
    "_event_write": async (event_type: str, payload: dict) -> str,
}
```

System tool `.pym` files declare `@external` on exactly the bedrock names they
need from this dict. No other keys are accessible to Grail scripts.

---

## 2. Module Layout

### New directory: `src/remora/bootstrap/`

```
src/remora/bootstrap/
  __init__.py
  bedrock.py          # build_bedrock() factory — the six async closures
  schema_loader.py    # TurnSchema, load_schema(), DEFAULT_SCHEMA constant
  turn_executor.py    # TurnExecutor class — context pipeline + LLM dispatch
  seed_graph.py       # One-time seeder for non-code bootstrap nodes
```

Note: no `graph_store.py` — the graph lives in `core/store/node_store.py`.

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
- `remora.core.store.node_store` — `NodeStore` (for type hints only; accessed via `event_store.nodes`)
- `remora.core.agents.kernel_factory` — `create_kernel`
- `remora.core.events.subscriptions` — `SubscriptionRegistry`
- `remora.utils` — `PathLike`, `normalize_path`

The bootstrap module must NOT import from:
- `remora.lsp` — LSP is an adapter layer
- `remora.runner` — runner is an adapter layer
- `remora.service` / `remora.companion` — these consume bootstrap output

### V1 files modified (three only)

| File | Change summary |
|---|---|
| `core/store/event_store_schema.py` | Add `create_graph_tables()` → called from `create_tables()` |
| `core/store/node_store.py` | Add `read_graph()`, `write_graph()`, routing helpers, `CODE_NODE_KINDS` |
| `core/tools/grail.py` | Add `workspace_tools_dir` + `externals` kwargs to `discover_grail_tools()` |

---

## 3. M0: The Bedrock Layer

### 3.1 Schema additions: `core/store/event_store_schema.py`

Add `create_graph_tables()` and call it from the end of `create_tables()`:

```python
def create_graph_tables(conn: sqlite3.Connection) -> None:
    """Create generic property graph tables for bootstrap agents."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS graph_nodes (
            id          TEXT PRIMARY KEY,
            kind        TEXT NOT NULL,
            attrs_json  TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_gnode_kind ON graph_nodes(kind);

        CREATE TABLE IF NOT EXISTS graph_edges (
            from_id     TEXT NOT NULL,
            to_id       TEXT NOT NULL,
            kind        TEXT NOT NULL,
            attrs_json  TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (from_id, to_id, kind)
        );

        CREATE INDEX IF NOT EXISTS idx_gedge_from ON graph_edges(from_id);
        CREATE INDEX IF NOT EXISTS idx_gedge_to   ON graph_edges(to_id);
    """)


def create_tables(conn: sqlite3.Connection) -> None:
    # ... existing events, nodes, subscriptions tables ...
    create_graph_tables(conn)  # add at end
```

No migration needed — `IF NOT EXISTS` handles existing databases.

### 3.2 NodeStore extension: `core/store/node_store.py`

Add generic graph methods to the existing `NodeStore` class. The existing
`get_node()`, `list_nodes()`, and `get_node_at_position()` are untouched.

#### Constants and helpers

```python
import json
import uuid

# Kinds that live in the v1 `nodes` table (populated by LSP scanner)
CODE_NODE_KINDS: frozenset[str] = frozenset({
    "function", "class", "method", "module", "file", "section", "table"
})


def _agent_node_to_graph_dict(node: "AgentNode") -> dict:
    """Project an AgentNode to the generic graph node shape."""
    return {
        "id":   node.node_id,
        "kind": node.node_type,
        "attrs": {
            "name":       node.name,
            "full_name":  node.full_name,
            "file_path":  node.file_path,
            "start_line": node.start_line,
            "end_line":   node.end_line,
            "status":     node.status,
        },
    }
```

#### Public graph API (new methods on NodeStore)

```python
async def read_graph(self, selector: dict) -> str:
    """Unified graph read. Dispatches by selector shape.

    {"node": node_id}                   → get one node (code or generic)
    {"neighbors": node_id, "dir": str}  → get neighbors (in/out/both)
    {"match": {"kind": str, ...}}        → find nodes by kind + attrs
    """
    if "node" in selector:
        return await self._graph_get_node(selector["node"])
    if "neighbors" in selector:
        return await self._graph_get_neighbors(
            selector["neighbors"], selector.get("dir", "both")
        )
    if "match" in selector:
        return await self._graph_find_nodes(selector["match"])
    raise ValueError(f"Unknown graph read selector: {selector!r}")


async def write_graph(self, op: str, data: dict) -> str:
    """Unified graph write. Always targets generic graph_nodes/graph_edges.

    "add_node"  data = {"kind": str, "attrs": dict, "id"?: str}
    "add_edge"  data = {"from": str, "to": str, "kind": str, "attrs"?: dict}
    """
    if op == "add_node":
        return await self._graph_add_node(data)
    if op == "add_edge":
        return await self._graph_add_edge(data)
    raise ValueError(f"Unknown graph write op: {op!r}")
```

#### Private read helpers

```python
async def _graph_get_node(self, node_id: str) -> str:
    """Get one node — checks code nodes first, then generic."""
    # Try code nodes table
    node = await self.get_node(node_id)
    if node:
        return json.dumps(_agent_node_to_graph_dict(node))

    # Fall back to graph_nodes table
    def _fetch(conn: sqlite3.Connection) -> dict | None:
        with conn.execute(
            "SELECT id, kind, attrs_json FROM graph_nodes WHERE id = ?",
            (node_id,),
        ) as cursor:
            row = cursor.fetchone()
        if row is None:
            return None
        return {"id": row[0], "kind": row[1], "attrs": json.loads(row[2])}

    async with self._read_lock:
        result = await asyncio.to_thread(_fetch, self._read_conn)
    return json.dumps(result)


async def _graph_find_nodes(self, match: dict) -> str:
    """Find nodes by kind + optional attr filters. Routes by kind."""
    kind = match.get("kind")
    extra_filters = {k: v for k, v in match.items() if k != "kind"}

    if kind in CODE_NODE_KINDS:
        # Query v1 nodes table
        nodes = await self.list_nodes(node_type=kind)
        results = [_agent_node_to_graph_dict(n) for n in nodes]
        if extra_filters:
            results = [
                r for r in results
                if all(r["attrs"].get(k) == v for k, v in extra_filters.items())
            ]
        return json.dumps(results)

    # Query graph_nodes table
    def _fetch(conn: sqlite3.Connection) -> list[dict]:
        if kind:
            with conn.execute(
                "SELECT id, kind, attrs_json FROM graph_nodes WHERE kind = ?",
                (kind,),
            ) as cursor:
                rows = cursor.fetchall()
        else:
            with conn.execute(
                "SELECT id, kind, attrs_json FROM graph_nodes"
            ) as cursor:
                rows = cursor.fetchall()

        results = []
        for row in rows:
            attrs = json.loads(row[2])
            if all(attrs.get(k) == v for k, v in extra_filters.items()):
                results.append({"id": row[0], "kind": row[1], "attrs": attrs})
        return results

    async with self._read_lock:
        result = await asyncio.to_thread(_fetch, self._read_conn)
    return json.dumps(result)


async def _graph_get_neighbors(self, node_id: str, direction: str) -> str:
    """Get neighbors of a node. Routing depends on whether it's a code node."""
    # Check if it's a code node
    node = await self.get_node(node_id)
    if node:
        # Code node: derive neighbors from caller_ids / callee_ids
        if direction == "in":
            neighbor_ids = node.caller_ids
            edge_kind = "calls"
        elif direction == "out":
            neighbor_ids = node.callee_ids
            edge_kind = "calls"
        else:  # both
            neighbor_ids = node.caller_ids + node.callee_ids
            edge_kind = "calls"

        neighbors = []
        for nid in neighbor_ids:
            raw = await self._graph_get_node(nid)
            n = json.loads(raw)
            if n:
                n["edge_kind"] = edge_kind
                neighbors.append(n)
        return json.dumps(neighbors)

    # Generic node: query graph_edges table
    def _fetch(conn: sqlite3.Connection) -> list[dict]:
        if direction == "out":
            query = """
                SELECT n.id, n.kind, n.attrs_json, e.kind as edge_kind
                FROM graph_edges e
                JOIN graph_nodes n ON e.to_id = n.id
                WHERE e.from_id = ?
            """
        elif direction == "in":
            query = """
                SELECT n.id, n.kind, n.attrs_json, e.kind as edge_kind
                FROM graph_edges e
                JOIN graph_nodes n ON e.from_id = n.id
                WHERE e.to_id = ?
            """
        else:  # both
            with conn.execute("""
                SELECT n.id, n.kind, n.attrs_json, e.kind as edge_kind
                FROM graph_edges e
                JOIN graph_nodes n ON (e.to_id = n.id AND e.from_id = ?)
                UNION
                SELECT n.id, n.kind, n.attrs_json, e.kind as edge_kind
                FROM graph_edges e
                JOIN graph_nodes n ON (e.from_id = n.id AND e.to_id = ?)
            """, (node_id, node_id)) as cursor:
                rows = cursor.fetchall()
            return [
                {"id": r[0], "kind": r[1], "attrs": json.loads(r[2]), "edge_kind": r[3]}
                for r in rows
            ]

        with conn.execute(query, (node_id,)) as cursor:
            rows = cursor.fetchall()
        return [
            {"id": r[0], "kind": r[1], "attrs": json.loads(r[2]), "edge_kind": r[3]}
            for r in rows
        ]

    async with self._read_lock:
        result = await asyncio.to_thread(_fetch, self._read_conn)
    return json.dumps(result)
```

#### Private write helpers

```python
async def _graph_add_node(self, data: dict) -> str:
    node_id = data.get("id") or str(uuid.uuid4())
    kind = data["kind"]
    attrs_json = json.dumps(data.get("attrs", {}))

    def _exec(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO graph_nodes (id, kind, attrs_json) VALUES (?, ?, ?)",
            (node_id, kind, attrs_json),
        )

    async with self._write_lock:
        await asyncio.to_thread(_exec, self._write_conn)
    return json.dumps({"id": node_id, "kind": kind})


async def _graph_add_edge(self, data: dict) -> str:
    from_id   = data["from"]
    to_id     = data["to"]
    kind      = data["kind"]
    attrs_json = json.dumps(data.get("attrs", {}))

    def _exec(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO graph_edges (from_id, to_id, kind, attrs_json) VALUES (?, ?, ?, ?)",
            (from_id, to_id, kind, attrs_json),
        )

    async with self._write_lock:
        await asyncio.to_thread(_exec, self._write_conn)
    return json.dumps({"from": from_id, "to": to_id, "kind": kind})
```

### 3.3 Build the bedrock: `src/remora/bootstrap/bedrock.py`

The bedrock closures now call `event_store.nodes.read_graph()` and
`event_store.nodes.write_graph()` — the same `NodeStore` that drives LSP.

```python
"""Bootstrap bedrock: the six async functions.

build_bedrock() is called once per agent activation.
Returns a dict of six async callables for that agent's Grail execution.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from remora.core.agents.cairn_externals import CairnExternals
from structured_agents.events import Event as StructuredEvent


@dataclass
class BootstrapEvent(StructuredEvent):
    """Minimal event model for bootstrap-emitted events.

    Inherits from StructuredEvent so EventStore.append() type-checks cleanly.
    All fields are read via getattr by EventStore, so the inheritance is
    sufficient — no method overrides required.
    """
    event_type: str
    node_id: str | None = None
    payload: dict = field(default_factory=dict)
    from_agent: str | None = None
    timestamp: float = field(default_factory=time.time)


def build_bedrock(
    *,
    agent_id: str,
    cairn_externals: CairnExternals,
    event_store: Any,   # EventStore — Any to avoid circular import
    swarm_id: str,
) -> dict[str, Any]:
    """Build the six bedrock functions for one agent activation.

    _graph_read / _graph_write delegate to event_store.nodes (NodeStore),
    which routes to the nodes table (code) or graph_nodes table (generic).
    """
    node_store = event_store.nodes  # NodeStore — unified graph access

    # ── Workspace channel ──────────────────────────────────────────────────

    async def _cairn_read(path: str) -> str:
        return await cairn_externals.read_file(path) or ""

    async def _cairn_write(path: str, content: str) -> str:
        await cairn_externals.write_file(path, content)
        return "ok"

    # ── Graph channel ──────────────────────────────────────────────────────

    async def _graph_read(selector: dict) -> str:
        return await node_store.read_graph(selector)

    async def _graph_write(op: str, data: dict) -> str:
        return await node_store.write_graph(op, data)

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

Replace `discover_grail_tools()` in `core/tools/grail.py` in full. Also add the
`_make_tool_callable` helper (used for synthesized tool loading in §9.3):

```python
def discover_grail_tools(
    agents_dir: Path,
    *,
    context: AgentContext | None = None,      # None when using bootstrap bedrock
    externals: dict[str, Any] | None = None,  # NEW: bootstrap externals dict
    files_provider: FilesProvider,
    workspace_tools_dir: Path | None = None,  # NEW: real filesystem dir of .pym files
    limits: grail.Limits | None = None,
    grail_dir: str | Path | None = None,
) -> list[RemoraGrailTool | SwarmTool]:
    """Discover and load .pym tools from a directory.

    Bootstrap mode: pass externals=bedrock_dict, context=None.
    V1 mode: pass context=AgentContext, externals=None.
    workspace_tools_dir must be a real filesystem directory (see §9.3 for
    how to extract synthesized tools from Cairn to a temp dir).
    """
    if externals is not None:
        externals_dict = externals
    elif context is not None:
        externals_dict = context.as_externals()
    else:
        raise ValueError("Either context or externals must be provided")

    tools: list[RemoraGrailTool | SwarmTool] = []
    if not agents_dir.exists():
        logger.warning("Agents directory does not exist: %s", agents_dir)
        return tools

    for pym_file in sorted(agents_dir.glob("*.pym")):
        try:
            tools.append(
                RemoraGrailTool(
                    pym_file,
                    externals=externals_dict,
                    files_provider=files_provider,
                    limits=limits,
                    grail_dir=grail_dir,
                )
            )
            logger.debug("Loaded tool: %s", pym_file.name)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", pym_file, exc)

    # Workspace tools — must be a real filesystem directory, not a Cairn path
    if workspace_tools_dir and workspace_tools_dir.exists():
        system_externals = {
            tool.schema.name: _make_tool_callable(tool)
            for tool in tools
            if isinstance(tool, RemoraGrailTool)
        }
        for pym_file in sorted(workspace_tools_dir.glob("*.pym")):
            try:
                tools.append(
                    RemoraGrailTool(
                        pym_file,
                        externals=system_externals,
                        files_provider=files_provider,
                        limits=limits,
                        grail_dir=grail_dir,
                    )
                )
            except Exception as exc:
                logger.warning("Failed to load workspace tool %s: %s", pym_file, exc)

    # Swarm tools only available in v1 mode (require AgentContext)
    if context is not None:
        tools.extend(build_swarm_tools(context))

    return tools


def _make_tool_callable(tool: RemoraGrailTool):
    """Wrap a RemoraGrailTool as a plain async callable for use as @external."""
    async def _call(**kwargs) -> str:
        result = await tool.execute(kwargs, context=None)
        return result.output
    return _call
```

Bootstrap callers pass:
```python
tools = discover_grail_tools(
    bootstrap_tools_dir,
    externals=bedrock_dict,
    files_provider=files_provider,
    workspace_tools_dir=extracted_tools_dir,  # real fs dir, see §9.3
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

async def graph_node(node_id: str) -> str:
    """Get a single node from the shared graph by ID.
    Works for both code nodes (functions, classes, modules) and
    generic nodes (agents, tasks, etc.).
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
    For code nodes, neighbors are callers/callees from the code topology.
    For generic nodes, neighbors are connected via graph_edges.
    Returns JSON array of {id, kind, attrs, edge_kind} objects."""
    return await _graph_read({"neighbors": node_id, "dir": direction})
```

**`bootstrap/tools/graph_find_nodes.pym`**
```python
@external
async def _graph_read(selector: dict) -> str: ...

async def graph_find_nodes(kind: str) -> str:
    """Find all nodes in the graph with the given kind.
    Works for both code kinds (function, class, module, method, file)
    and custom kinds (agent, task, etc.).
    Returns JSON array of {id, kind, attrs} objects."""
    return await _graph_read({"match": {"kind": kind}})
```

**`bootstrap/tools/graph_add_node.pym`**
```python
@external
async def _graph_write(op: str, data: dict) -> str: ...

async def graph_add_node(kind: str, attrs: dict) -> str:
    """Add a node to the shared graph.
    kind: the node type (e.g. 'agent', 'task') — not a code node kind
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
    from_id, to_id: node IDs (at least one must exist)
    kind: edge type (e.g. 'assigned_to', 'produced', 'depends_on')
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

```python
async def _make_files_provider(cairn_externals: CairnExternals):
    async def files_provider() -> dict[str, str | bytes]:
        try:
            paths = await cairn_externals.list_dir(".")
            files = {}
            for path in paths or []:
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
"""Bootstrap schema.yaml loader."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

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


class ContextStep(BaseModel):
    name: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False


class SubscriptionSpec(BaseModel):
    event_type: str
    node_id: str | None = None


class TurnSchema(BaseModel):
    version: str = "1"
    name: str = "unnamed"
    system: str = ""
    context: list[ContextStep] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    subscriptions: list[SubscriptionSpec] = Field(default_factory=list)
    max_turns: int = 5
    termination: str = "DONE"
    extends: str | None = None


def _load_yaml(text: str) -> dict:
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def _merge_schemas(base: dict, child: dict) -> dict:
    """Shallow merge: child overrides base. Lists are appended."""
    merged = dict(base)
    for key, value in child.items():
        if key == "extends":
            continue
        if key in ("context", "tools", "subscriptions") and key in merged:
            merged[key] = (merged[key] or []) + (value or [])
        else:
            merged[key] = value
    return merged


async def load_schema(
    cairn_externals: "CairnExternals",
    *,
    system_agents_dir: Path | None = None,
) -> TurnSchema:
    """Load schema.yaml from the agent's Cairn workspace.

    Falls back to DEFAULT_SCHEMA if schema.yaml is absent.
    Resolves extends: one level from system_agents_dir (real filesystem).

    NOTE: Takes CairnExternals, not a Path — agent workspaces are Cairn
    virtual filesystems (SQLite-backed), not real directories. schema.yaml
    written by an agent via write_file() lives in Cairn, not on disk.
    """
    content = await cairn_externals.read_file("schema.yaml")

    if not content:
        return TurnSchema.model_validate(_load_yaml(DEFAULT_SCHEMA_YAML))

    child_data = _load_yaml(content)

    extends = child_data.get("extends")
    if extends and system_agents_dir:
        base_path = system_agents_dir / f"{extends}.yaml"
        if base_path.exists():
            base_data = _load_yaml(base_path.read_text(encoding="utf-8"))
            child_data = _merge_schemas(base_data, child_data)

    return TurnSchema.model_validate(child_data)
```

### 5.2 Template variable resolution

Two passes, applied in order:

**Pass 1 — `{node.*}` before context pipeline**:
```python
import re

def _resolve_node_vars(text: str, node_attrs: dict[str, Any]) -> str:
    def replacer(m: re.Match) -> str:
        return str(node_attrs.get(m.group(1), m.group(0)))
    return re.sub(r'\{node\.([^}]+)\}', replacer, text)
```

**Pass 2 — `{{name}}` after context pipeline**:
```python
def resolve_context_vars(text: str, context_values: dict[str, str]) -> str:
    def replacer(m: re.Match) -> str:
        return context_values.get(m.group(1), "")
    return re.sub(r'\{\{([^}]+)\}\}', replacer, text)
```

### 5.3 TurnExecutor: `src/remora/bootstrap/turn_executor.py`

```python
"""Bootstrap turn executor.

Parallel to v1's execute_agent_turn(). Uses schema.yaml instead of manifest.yaml.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from structured_agents import Message, build_client

from remora.core.agents.cairn_externals import CairnExternals
from remora.core.agents.kernel_factory import create_kernel
from remora.bootstrap.schema_loader import TurnSchema, load_schema, resolve_context_vars

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    response_text: str
    context_values: dict[str, str] = field(default_factory=dict)


class TurnExecutor:
    def __init__(
        self,
        *,
        agent_id: str,
        cairn_externals: CairnExternals,  # replaces workspace_root: Path
        tools: list[Any],
        node_attrs: dict[str, Any],
        config: Any,
        system_agents_dir: Path | None = None,
        client: Any | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._cairn_externals = cairn_externals  # used by load_schema (Cairn VFS)
        self._tools = tools
        self._node_attrs = node_attrs
        self._config = config
        self._system_agents_dir = system_agents_dir
        self._client = client

    async def run(self, activation_event: Any = None) -> TurnResult:
        schema = await load_schema(
            self._cairn_externals,
            system_agents_dir=self._system_agents_dir,
        )

        context_values = await self._run_context_pipeline(schema)
        system_prompt = resolve_context_vars(
            self.resolve_node_vars(schema.system), context_values
        )
        user_prompt = self._build_user_prompt(activation_event)

        tool_map = {t.schema.name: t for t in self._tools}
        active_tools = [tool_map[name] for name in schema.tools if name in tool_map]
        tool_schemas = [t.schema for t in active_tools]

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
            tools=active_tools,
            observer=None,
            client=self._client,  # reuse the built client
        )

        try:
            result = await kernel.run(messages, tool_schemas, max_turns=schema.max_turns)
        finally:
            await kernel.close()

        return TurnResult(
            response_text=self._extract_response(result),
            context_values=context_values,
        )

    async def _run_context_pipeline(self, schema: TurnSchema) -> dict[str, str]:
        values: dict[str, str] = {}
        tool_map = {t.schema.name: t for t in self._tools}

        for step in schema.context:
            tool = tool_map.get(step.tool)
            if tool is None:
                if not step.optional:
                    logger.warning("Context step %r: tool %r not found", step.name, step.tool)
                values[step.name] = ""
                continue

            resolved_args = {
                k: self.resolve_node_vars(str(v)) if isinstance(v, str) else v
                for k, v in step.args.items()
            }
            try:
                result = await tool.execute(resolved_args, context=None)
                values[step.name] = result.output if not result.is_error else ""
            except Exception:
                if not step.optional:
                    logger.warning("Context step %r failed", step.name, exc_info=True)
                values[step.name] = ""

        return values

    def resolve_node_vars(self, text: str) -> str:
        def replacer(m: re.Match) -> str:
            return str(self._node_attrs.get(m.group(1), m.group(0)))
        return re.sub(r'\{node\.([^}]+)\}', replacer, text)

    def _build_user_prompt(self, activation_event: Any) -> str:
        if activation_event is None:
            return "Begin your turn."
        event_type = getattr(activation_event, "event_type", type(activation_event).__name__)
        node_id = getattr(activation_event, "node_id", None)
        parts = [f"Activation event: {event_type}"]
        if node_id:
            parts.append(f"Node: {node_id}")
        return "\n".join(parts)

    @staticmethod
    def _extract_response(result: Any) -> str:
        if hasattr(result, "final_message") and result.final_message:
            msg = result.final_message
            return msg.content if hasattr(msg, "content") and msg.content else str(result)
        return getattr(result, "content", None) or str(result)
```

---

## 6. M3: Self-Bootstrapping Loop

### 6.1 Base YAML schemas

**`bootstrap/agents/DEFAULT_SCHEMA.yaml`**:
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
    args: {path: role.md}
    optional: true

  - name: notes
    tool: read_file
    args: {path: notes.md}
    optional: true

  - name: source
    tool: read_file
    args: {path: "{node.file_path}"}
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

### 6.2 Activation flow

**Step A — New agent workspace creation** (runtime, not yet built — placeholder):

```python
import json
import tempfile

async def handle_agent_needed(event, workspace_service, subscriptions, event_store,
                               config, swarm_id, bootstrap_tools_dir) -> None:
    agent_id = event.payload["agent_id"]
    node_id  = event.payload["node_id"]

    workspace = await workspace_service.get_agent_workspace(agent_id)
    await subscriptions.register(agent_id, SubscriptionPattern(to_agent=agent_id))

    # Build CairnExternals directly — workspace_service.get_externals() returns
    # the Grail externals dict, not the CairnExternals object itself.
    cairn_ext = CairnExternals(
        agent_id=agent_id,
        agent_fs=workspace.cairn,
        stable_fs=workspace_service._stable_workspace,
        resolver=workspace_service.resolver,
    )

    bedrock = build_bedrock(
        agent_id=agent_id,
        cairn_externals=cairn_ext,
        event_store=event_store,
        swarm_id=swarm_id,
    )
    files_provider = await _make_files_provider(cairn_ext)

    # Synthesized tools live in Cairn's virtual FS (a SQLite DB), not on disk.
    # Extract .pym files to a temp directory so discover_grail_tools() can find them.
    with tempfile.TemporaryDirectory() as tmp:
        extracted_tools_dir = await _extract_workspace_tools(cairn_ext, Path(tmp))
        tools = discover_grail_tools(
            bootstrap_tools_dir,
            externals=bedrock,
            files_provider=files_provider,
            workspace_tools_dir=extracted_tools_dir,
        )

        # Fetch node attrs from the unified graph
        node_raw = await event_store.nodes.read_graph({"node": node_id})
        node_attrs = (json.loads(node_raw) or {}).get("attrs", {})
        node_attrs["id"] = node_id

        executor = TurnExecutor(
            agent_id=agent_id,
            cairn_externals=cairn_ext,
            tools=tools,
            node_attrs=node_attrs,
            config=config,
            system_agents_dir=bootstrap_tools_dir.parent / "agents",
        )
        await executor.run(event)
    # temp dir cleaned up on exit
```

**Step B — Subsequent activations**: same flow. `load_schema()` finds
`schema.yaml` written by the agent in activation 1 — DEFAULT_SCHEMA is
no longer used.

### 6.3 Coordinator schema.yaml

```yaml
version: "1"
name: coordinator

system: |
  You are the Remora bootstrap coordinator.
  Survey the code graph and ensure every module node has an assigned agent.
  {{notes}}

context:
  - name: notes
    tool: read_file
    args: {path: notes.md}
    optional: true

  - name: modules
    tool: graph_find_nodes
    args: {kind: module}

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

The coordinator reads `{{modules}}` (JSON list), checks which lack an
`assigned_agent` attr, and emits `AgentNeededEvent` for each unassigned module.

---

## 7. M4: Graph Seeding

### 7.1 Why code topology requires no seeding

The v1 LSP scanner (background scanner + `NodeDiscoveredEvent` projection)
already populates the `nodes` table in `event_store.db` with code nodes for
every function, class, module, and file in the project. `caller_ids` and
`callee_ids` are maintained by the same projection as the scanner discovers
call relationships.

Because `NodeStore.read_graph()` routes `kind in CODE_NODE_KINDS` to the
`nodes` table, bootstrap agents can query live code topology immediately —
no seeding required:

```python
# Agent calls graph_find_nodes(kind="module") →
# NodeStore._graph_find_nodes({"kind": "module"}) →
# NodeStore.list_nodes(node_type="module") →
# reads from nodes table populated by LSP scanner
```

**M4 is only needed for two cases:**
1. Non-code bootstrap nodes that have no v1 equivalent (e.g. `agent` nodes
   representing bootstrap agents themselves, or `task` nodes)
2. A fresh install before the LSP scanner has run — a lightweight filesystem
   seeder creates module-level nodes so the coordinator can start immediately

### 7.2 `src/remora/bootstrap/seed_graph.py`

```python
"""Bootstrap graph seeder.

Seeds non-code bootstrap nodes. Code nodes are live in NodeStore
via the v1 LSP scanner — no mirroring needed.

Usage:
    devenv shell -- python -m remora.bootstrap.seed_graph
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from remora.core.store.event_store import EventStore

logger = logging.getLogger(__name__)


async def seed_module_nodes_from_filesystem(
    event_store: EventStore,
    project_root: Path,
    *,
    swarm_id: str,
) -> int:
    """Lightweight fallback: create module nodes in graph_nodes from filesystem.

    Only needed when the v1 LSP scanner has not yet run. Creates one
    'module' node per Python file in the graph_nodes table. These will be
    superseded/complemented by the NodeStore's live nodes table once scanning
    completes, but they allow the coordinator to start immediately.
    """
    node_store = event_store.nodes
    count = 0
    skip_dirs = {".venv", ".devenv", "__pycache__", "dist", "build", ".git"}

    for py_file in sorted(project_root.rglob("*.py")):
        parts = set(py_file.relative_to(project_root).parts)
        if parts & skip_dirs:
            continue

        rel_path = py_file.relative_to(project_root).as_posix()
        # e.g. src/remora/core/events/events.py → remora.core.events.events
        module_path = (
            rel_path
            .removeprefix("src/")
            .replace("/", ".")
            .removesuffix(".py")
        )
        node_id = f"module:{rel_path}"

        await node_store.write_graph("add_node", {
            "id":   node_id,
            "kind": "module",
            "attrs": {
                "name":      py_file.stem,
                "full_name": module_path,
                "file_path": rel_path,
            },
        })
        count += 1

    logger.info("Seeded %d module nodes from filesystem (fallback)", count)
    return count


async def seed_coordinator_node(
    event_store: EventStore,
    *,
    coordinator_id: str = "coordinator",
) -> None:
    """Create the coordinator agent node in the graph."""
    await event_store.nodes.write_graph("add_node", {
        "id":   coordinator_id,
        "kind": "agent",
        "attrs": {
            "name":    "coordinator",
            "role":    "Surveys the graph and assigns agents to modules",
            "status":  "pending",
        },
    })
    logger.info("Seeded coordinator node: %s", coordinator_id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db_path = Path.cwd() / ".remora" / "event_store.db"

    async def main() -> None:
        event_store = EventStore(db_path)
        await event_store.initialize()
        try:
            await seed_coordinator_node(event_store)

            # Only seed module nodes if LSP scanner hasn't run yet
            node_count = len(await event_store.nodes.list_nodes(node_type="module"))
            if node_count == 0:
                logger.info("LSP scanner nodes not found — seeding from filesystem")
                await seed_module_nodes_from_filesystem(
                    event_store, Path.cwd(), swarm_id="bootstrap"
                )
            else:
                logger.info("LSP scanner has %d module nodes — skipping filesystem seed", node_count)
        finally:
            await event_store.close()

    asyncio.run(main())
```

### 7.3 Node and edge kind reference

| Kind | Table | Used for | Key attrs |
|------|-------|----------|-----------|
| `module` | `nodes` (live) or `graph_nodes` (fallback) | Python file | `name`, `full_name`, `file_path` |
| `function` | `nodes` (live) | Python function | `name`, `full_name`, `file_path`, `start_line`, `end_line` |
| `class` | `nodes` (live) | Python class | same as function |
| `method` | `nodes` (live) | Python method | same as function |
| `agent` | `graph_nodes` | Bootstrap agent | `name`, `role`, `status`, `assigned_node_id` |
| `task` | `graph_nodes` | Work item | `title`, `status`, `assigned_to` |

| Edge kind | Table | Meaning |
|-----------|-------|---------|
| `calls` | derived from `caller_ids`/`callee_ids` | function A calls function B |
| `assigned_to` | `graph_edges` | agent A is responsible for node B |
| `produced` | `graph_edges` | agent A created task B |
| `depends_on` | `graph_edges` | task A depends on task B |

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
"""Bootstrap workspace panels for the companion sidebar."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WorkspacePanel:
    key: str          # "role" | "schema" | "notes" | "todo" | "log" | "tools"
    title: str
    content: str
    is_empty: bool


async def build_workspace_panels(
    cairn_externals: Any,  # CairnExternals for the agent
) -> list[WorkspacePanel]:
    """Build all workspace panels for one agent."""
    panels = []

    async def _read(path: str) -> tuple[str, bool]:
        try:
            content = await cairn_externals.read_file(path)
            return content or "", not bool(content)
        except Exception:
            return "", True

    content, empty = await _read("role.md")
    panels.append(WorkspacePanel("role", "Role", content, empty))

    content, empty = await _read("schema.yaml")
    panels.append(WorkspacePanel("schema", "Schema", content, empty))

    content, empty = await _read("notes.md")
    panels.append(WorkspacePanel("notes", "Notes", content, empty))

    content, empty = await _read("todo.md")
    panels.append(WorkspacePanel("todo", "Todo", content, empty))

    content, empty = await _read("log.jsonl")
    if not empty:
        lines = [l for l in content.splitlines() if l.strip()]
        content = "\n".join(lines[-20:])
    panels.append(WorkspacePanel("log", "Log", content, empty))

    try:
        tool_files = await cairn_externals.list_dir("tools")
        pym_files = [f for f in (tool_files or []) if f.endswith(".pym")]
        tool_content = "\n".join(f"- `{f}`" for f in sorted(pym_files)) if pym_files else ""
        panels.append(WorkspacePanel("tools", "Tools", tool_content, not bool(pym_files)))
    except Exception:
        panels.append(WorkspacePanel("tools", "Tools", "", True))

    return panels
```

### 8.3 Sidebar refresh

Workspace panels refresh on activation end (existing event bus notifications).
No polling needed — the companion is already notified by the `EventBus` when
agent turns complete.

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
the `write_file` tool. `@external` declarations reference system tool names:

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
    """Return full context for a node: source, graph metadata, callers, callees.
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

On the next activation, `discover_grail_tools()` compiles `node_context.pym`
with system tool callables injected as externals. `node_context` becomes
available as a single tool call.

### 9.2 The @external boundary for synthesized tools

Synthesized tools declare `@external` on **system tool names**, not bedrock names.

The Grail externals dict passed to synthesized tools contains ONLY the system
tool callables (wrapped `RemoraGrailTool.execute` functions). The `_cairn_read`,
`_graph_write`, etc. names are NOT present. A synthesized tool attempting to
call `_cairn_read` directly will fail at runtime (key not in externals dict).

### 9.3 Extracting synthesized tools from Cairn

Agent workspaces are Cairn virtual filesystems (SQLite-backed). When an agent
writes `tools/node_context.pym` via `write_file()`, the content lives in Cairn —
not on the real filesystem. `discover_grail_tools()` uses `Path.glob()`, which
only works on real paths.

Add `_extract_workspace_tools()` to `src/remora/bootstrap/bedrock.py`. This is
called in `handle_agent_needed()` (§6.2) before tool discovery:

```python
async def _extract_workspace_tools(cairn_externals: CairnExternals, tmp_dir: Path) -> Path:
    """Extract .pym files from Cairn virtual FS to a real temp directory.

    Returns the tools subdirectory path (may be empty if no tools yet).
    Called once per activation; the caller's tempfile.TemporaryDirectory()
    context manager handles cleanup.
    """
    tools_dir = tmp_dir / "tools"
    tools_dir.mkdir()
    try:
        files = await cairn_externals.list_dir("tools")
        for fname in (files or []):
            if fname.endswith(".pym"):
                content = await cairn_externals.read_file(f"tools/{fname}")
                if content:
                    (tools_dir / fname).write_text(content, encoding="utf-8")
    except Exception:
        pass  # no workspace/tools dir yet — tools_dir stays empty
    return tools_dir
```

The workspace tools scan in `discover_grail_tools()` (§4.1) is already correct
— it receives this real filesystem path. `_make_tool_callable` is defined in
`grail.py` alongside `discover_grail_tools` (see §4.1).

### 9.4 ToolSynthesizedEvent

When an agent writes a new `.pym` tool:

```python
await emit_event("ToolSynthesizedEvent", {
    "node_id":   "{node.id}",
    "tool_name": "node_context",
    "file_path": "tools/node_context.pym",
})
```

The coordinator subscribes to `ToolSynthesizedEvent`. Promotion to a system
tool requires a human decision — the coordinator can record the tool in the
graph but not auto-copy to `bootstrap/tools/`.

---

## 10. Testing Plan

Run all tests with:
```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

### M0 tests: `tests/unit/bootstrap/test_bedrock.py`

```python
# 1. _cairn_read delegates to CairnExternals.read_file
async def test_cairn_read_delegates():
    ...

# 2. _cairn_write delegates to CairnExternals.write_file
async def test_cairn_write_delegates():
    ...

# 3. _graph_read delegates to event_store.nodes.read_graph
async def test_graph_read_delegates_to_node_store():
    ...

# 4. _graph_write delegates to event_store.nodes.write_graph
async def test_graph_write_delegates_to_node_store():
    ...

# 5. _event_read calls get_recent_events
async def test_event_read_calls_get_recent_events():
    ...

# 6. _event_write appends BootstrapEvent and returns event_id
async def test_event_write_returns_event_id():
    ...
```

### M0 tests: `tests/unit/test_node_store.py` (extend existing test file)

```python
# New graph methods — all against live SQLite (same pattern as existing tests)

async def test_read_graph_get_code_node(node_store_with_data):
    # graph_find_nodes(kind="function") returns AgentNode projected to dict
    result = json.loads(await node_store.read_graph({"match": {"kind": "function"}}))
    assert all(r["kind"] == "function" for r in result)

async def test_read_graph_get_generic_node(node_store):
    await node_store.write_graph("add_node", {"kind": "agent", "attrs": {"name": "test"}})
    result = json.loads(await node_store.read_graph({"match": {"kind": "agent"}}))
    assert len(result) == 1 and result[0]["attrs"]["name"] == "test"

async def test_write_graph_add_node_generates_id(node_store):
    result = json.loads(await node_store.write_graph("add_node", {"kind": "task", "attrs": {}}))
    assert "id" in result and result["kind"] == "task"

async def test_write_graph_add_node_preserves_provided_id(node_store):
    result = json.loads(await node_store.write_graph("add_node",
        {"id": "my-id", "kind": "agent", "attrs": {}}))
    assert result["id"] == "my-id"

async def test_read_graph_code_node_neighbors_from_caller_ids(node_store_with_data):
    # neighbor query on a function node returns callers from caller_ids column
    ...

async def test_read_graph_generic_node_neighbors_from_graph_edges(node_store):
    # neighbor query on an agent node returns entries from graph_edges table
    ...

async def test_code_node_kinds_not_written_to_graph_nodes(node_store):
    # write_graph("add_node", {"kind": "function", ...}) should raise or be rejected
    # code nodes are read-only from the bootstrap perspective
    ...
```

### M0 tests: `tests/unit/test_event_store_schema.py`

```python
def test_create_tables_creates_graph_tables(tmp_path):
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    create_tables(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "graph_nodes" in tables
    assert "graph_edges" in tables
```

### M1 tests: `tests/unit/bootstrap/test_system_tools.py`

```python
def test_all_pym_files_compile():
    for pym_file in Path("bootstrap/tools").glob("*.pym"):
        script = grail.load(str(pym_file))
        assert script is not None

def test_pym_externals_are_bedrock_names():
    bedrock_names = {"_cairn_read", "_cairn_write", "_graph_read",
                     "_graph_write", "_event_read", "_event_write"}
    for pym_file in Path("bootstrap/tools").glob("*.pym"):
        script = grail.load(str(pym_file))
        assert set(script.externals).issubset(bedrock_names)

async def test_read_file_tool_calls_cairn_read():
    ...

async def test_graph_find_nodes_routes_to_graph_read():
    ...
```

### M2 tests: `tests/unit/bootstrap/test_schema_loader.py`

```python
def test_default_schema_parses():
    schema = load_schema(Path("/nonexistent"))
    assert schema.termination == "DONE"
    assert "read_file" in schema.tools

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

def test_extends_merges_base(tmp_path, bootstrap_agents_dir):
    (tmp_path / "schema.yaml").write_text("""
extends: base_code_agent
tools:
  - graph_add_edge
termination: "DONE"
""")
    schema = load_schema(tmp_path, system_agents_dir=bootstrap_agents_dir)
    assert "read_file" in schema.tools
    assert "graph_add_edge" in schema.tools
```

### M4 tests: `tests/unit/bootstrap/test_seed_graph.py`

```python
async def test_seed_from_filesystem_creates_module_nodes(tmp_path, event_store):
    (tmp_path / "foo.py").write_text("x = 1")
    (tmp_path / "bar.py").write_text("y = 2")
    n = await seed_module_nodes_from_filesystem(event_store, tmp_path, swarm_id="test")
    assert n == 2
    result = json.loads(await event_store.nodes.read_graph({"match": {"kind": "module"}}))
    assert len(result) == 2

async def test_seed_skips_when_live_nodes_exist(event_store_with_nodes):
    # seed_graph main() should skip filesystem seed if nodes table has entries
    ...
```

### Summary: test file locations

```
tests/
  unit/
    test_node_store.py          # extend existing — add graph method tests
    test_event_store_schema.py  # extend existing — add graph table assertions
    bootstrap/
      test_bedrock.py
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
