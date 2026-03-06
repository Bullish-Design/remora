# Remora Refactor Implementation Guide

**Based on:** [FINAL_REVIEW.md](file:///home/andrew/Documents/Projects/remora/.scratch/projects/final_refactor/FINAL_REVIEW.md)  
**No backwards compatibility.** Every change targets the cleanest possible codebase.

---

## Table of Contents

1. [Prerequisites & Verification Baseline](#1-prerequisites--verification-baseline)  
   Run the full test suite before any changes to establish a green baseline.

2. [Step 1: Add `parent_id` to `CSTNode` + Compute in `_assign_semantic_identity`](#2-step-1-add-parent_id-to-cstnode)  
   The foundational change. Adds `parent_id` field and populates it during containment resolution.  
   **Files:** `discovery.py`

3. [Step 2: Add `NodeDiscoveredEvent.from_cst_node()` Factory](#3-step-2-add-nodediscoveredeventfrom_cst_node-factory)  
   Eliminates all 4+ manual event construction sites with a single factory method.  
   **Files:** `events.py`

4. [Step 3: Delete `watcher.py` — Inline Remaining Logic](#4-step-3-delete-watcherpy)  
   Removes the module entirely. Moves function/method dedup into `discovery.py`. Updates all consumers to use `parse_content()` + `CSTNode` directly.  
   **Files:** `watcher.py` (DELETE), `server.py`, `documents.py`, `__main__.py`, tests

5. [Step 4: Update `RemoraDB.update_edges` to Accept `CSTNode`](#5-step-4-update-remoradbupdate_edges)  
   Type-safe edge updates — no more raw dicts in the data pipeline.  
   **Files:** `db.py`, `documents.py`, `server.py`, `__main__.py`

6. [Step 5: Move LSP Tables Out of `EventStore`](#6-step-5-move-lsp-tables-out-of-eventstore)  
   Restores layer isolation. `core/` no longer knows about LSP-specific tables.  
   **Files:** `event_store.py`, `db.py`

7. [Step 6: Refactor `LazyGraph` to Use `EventStore` API](#7-step-6-refactor-lazygraph)  
   Removes raw SQLite coupling. LazyGraph queries nodes through the EventStore API.  
   **Files:** `graph.py`, `server.py`

8. [Step 7: Fix `CompanionDispatcher` EventBus Subscription Bug](#8-step-7-fix-companiondispatcher-eventbus-bug)  
   One-line fix for broken event routing in the companion layer.  
   **Files:** `companion/dispatcher.py`

9. [Step 8: Cleanup — Duplicated Section Headers, Dead Imports](#9-step-8-cleanup)  
   Minor hygiene pass over files touched by the refactor.  
   **Files:** various

10. [Final Verification](#10-final-verification)  
    Full test suite + manual smoke test to confirm everything is green.


## 1. Prerequisites & Verification Baseline

Before starting, establish a green baseline:

```bash
devenv shell -- uv sync --extra dev
devenv shell -- uv run pytest tests/ -x -q
```

All tests must pass. Keep this output as a reference.

**Key test files that will be affected:**

| Test File | Why |
|-----------|-----|
| `tests/test_discovery.py` | CSTNode model gains `parent_id` field |
| `tests/unit/test_lsp_watcher.py` | Module will be **deleted** |
| `tests/unit/test_lsp_graph.py` | LazyGraph changes from raw SQL to EventStore API |
| `tests/integration/test_event_store_integration.py` | EventStore schema loses LSP tables |

---

## 2. Step 1: Add `parent_id` to `CSTNode`

**Goal:** Make `CSTNode` carry `parent_id` from discovery, eliminating the need for the watcher to recompute containment.

### 2.1 Add the field

In [discovery.py L46-64](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#L46-L64), add `parent_id`:

```diff
 class CSTNode(BaseModel):
     model_config = ConfigDict(frozen=True)

     node_id: str
     node_type: str
     name: str
     full_name: str
     file_path: str
     text: str
     start_line: int
     end_line: int
     start_byte: int
     end_byte: int
+    parent_id: str | None = None
```

### 2.2 Rewrite `_assign_semantic_identity` to populate `parent_id`

Replace [discovery.py L340-406](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#L340-L406). The current implementation finds parents for `full_name` but never records `parent_id`. The new implementation caches the parent index from the first pass and reuses it:

```python
def _assign_semantic_identity(file_path: str, nodes: list[CSTNode]) -> list[CSTNode]:
    """Assign semantic full_name, node_id, and parent_id using containment."""
    if not nodes:
        return nodes

    stem = Path(file_path).stem

    # Build work items: mutable dicts with room for full_name and parent index
    work: list[dict[str, int | str | None]] = []
    for node in nodes:
        work.append(
            {
                "node_type": node.node_type,
                "name": node.name,
                "file_path": node.file_path,
                "text": node.text,
                "start_line": node.start_line,
                "end_line": node.end_line,
                "start_byte": node.start_byte,
                "end_byte": node.end_byte,
                "full_name": "",
                "_parent_idx": None,  # track parent index for parent_id
            }
        )

    # First pass: compute full_name and cache parent index
    for i, item in enumerate(work):
        if item["node_type"] == "file":
            item["full_name"] = stem
            continue

        node_start = int(item["start_line"])
        node_end = int(item["end_line"])
        node_span = node_end - node_start
        best_j: int | None = None
        best_span = float("inf")
        for j, candidate in enumerate(work):
            if j == i:
                continue
            cand_start = int(candidate["start_line"])
            cand_end = int(candidate["end_line"])
            cand_span = cand_end - cand_start
            if (
                cand_start <= node_start
                and cand_end >= node_end
                and cand_span > node_span
                and cand_span < best_span
            ):
                best_j = j
                best_span = cand_span

        if best_j is not None:
            item["full_name"] = f"{work[best_j]['full_name']}.{item['name']}"
            item["_parent_idx"] = best_j
        else:
            item["full_name"] = f"{stem}.{item['name']}"

    # Second pass: compute node_ids (needs full_name), then resolve parent_id
    node_ids: list[str] = []
    for item in work:
        node_ids.append(
            compute_node_id(file_path, str(item["node_type"]), str(item["full_name"]))
        )

    resolved: list[CSTNode] = []
    for i, item in enumerate(work):
        parent_idx = item["_parent_idx"]
        parent_id = node_ids[parent_idx] if parent_idx is not None else None

        resolved.append(
            CSTNode(
                node_id=node_ids[i],
                node_type=str(item["node_type"]),
                name=str(item["name"]),
                full_name=str(item["full_name"]),
                file_path=str(item["file_path"]),
                text=str(item["text"]),
                start_line=int(item["start_line"]),
                end_line=int(item["end_line"]),
                start_byte=int(item["start_byte"]),
                end_byte=int(item["end_byte"]),
                parent_id=parent_id,
            )
        )

    return resolved
```

> **Key improvement over current code:** Parent-finding runs once instead of twice. The `_parent_idx` cache avoids the second O(n²) scan that the watcher separately does.

### 2.3 Add function/method deduplication to `parse_content` and `_parse_file`

Currently the watcher deduplicates when tree-sitter captures both `function` and `method` for the same span ([watcher.py L44-49](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#L44-L49)). Move this into discovery.

In [discovery.py L575-579](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#L575-L579), before `_assign_semantic_identity`:

```diff
     if not any(n.node_type == "file" for n in nodes):
         nodes.insert(0, _create_file_node_from_content(file_path, content))

+    # Deduplicate: when both "function" and "method" exist for the same
+    # (name, start_line, end_line), keep only "method".
+    method_keys = {
+        (n.name, n.start_line, n.end_line) for n in nodes if n.node_type == "method"
+    }
+    nodes = [
+        n for n in nodes
+        if not (n.node_type == "function" and (n.name, n.start_line, n.end_line) in method_keys)
+    ]
+
     return _assign_semantic_identity(file_path, nodes)
```

Apply the same dedup in `_parse_file` ([discovery.py L205-209](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#L205-L209)), before `_assign_semantic_identity`.

### 2.4 Write tests

Add to `tests/test_discovery.py`:

```python
class TestCSTNodeParentId:
    """CSTNode should carry parent_id after semantic identity resolution."""

    def test_method_has_class_parent(self):
        content = "class Foo:\n    def bar(self):\n        pass\n"
        nodes = parse_content("test.py", content)
        by_name = {n.name: n for n in nodes}
        assert by_name["bar"].parent_id == by_name["Foo"].node_id

    def test_class_has_file_parent(self):
        content = "class Foo:\n    pass\n"
        nodes = parse_content("test.py", content)
        by_name = {n.name: n for n in nodes}
        file_node = [n for n in nodes if n.node_type == "file"][0]
        assert by_name["Foo"].parent_id == file_node.node_id

    def test_file_node_has_no_parent(self):
        content = "x = 1\n"
        nodes = parse_content("test.py", content)
        file_node = [n for n in nodes if n.node_type == "file"][0]
        assert file_node.parent_id is None

    def test_function_method_dedup_keeps_method(self):
        content = "class Foo:\n    def bar(self):\n        pass\n"
        nodes = parse_content("test.py", content)
        names_types = [(n.name, n.node_type) for n in nodes]
        assert ("bar", "method") in names_types
        assert ("bar", "function") not in names_types
```

### 2.5 Verify

```bash
devenv shell -- uv run pytest tests/test_discovery.py -x -v
```

---

## 3. Step 2: Add `NodeDiscoveredEvent.from_cst_node()` Factory

**Goal:** Eliminate boilerplate event construction at 4+ call sites.

### 3.1 Add the factory method

In [events.py L160-175](file:///home/andrew/Documents/Projects/remora/src/remora/core/events.py#L160-L175), add a classmethod:

```diff
 class NodeDiscoveredEvent(_FrozenEvent):
     """Emitted when a code node is discovered or re-discovered."""
     node_id: str
     node_type: str
     name: str
     full_name: str
     file_path: str
     start_line: int
     end_line: int
     source_code: str
     source_hash: str
     parent_id: str | None = None
     start_byte: int = 0
     end_byte: int = 0
     timestamp: float = Field(default_factory=time.time)
+
+    @classmethod
+    def from_cst_node(cls, node: "CSTNode") -> "NodeDiscoveredEvent":
+        """Create from a CSTNode — single source of truth for field mapping."""
+        from remora.core.discovery import compute_source_hash
+        return cls(
+            node_id=node.node_id,
+            node_type=node.node_type,
+            name=node.name,
+            full_name=node.full_name,
+            file_path=node.file_path,
+            start_line=node.start_line,
+            end_line=node.end_line,
+            start_byte=node.start_byte,
+            end_byte=node.end_byte,
+            source_code=node.text,
+            source_hash=compute_source_hash(node.text),
+            parent_id=node.parent_id,
+        )
```

> Import is deferred to avoid circular imports (`events.py` ← `discovery.py`).

### 3.2 Write a test

```python
def test_node_discovered_event_from_cst_node():
    from remora.core.discovery import CSTNode, compute_node_id, compute_source_hash
    from remora.core.events import NodeDiscoveredEvent

    node = CSTNode(
        node_id=compute_node_id("test.py", "function", "test.foo"),
        node_type="function", name="foo", full_name="test.foo",
        file_path="test.py", text="def foo(): pass",
        start_line=1, end_line=1, start_byte=0, end_byte=15,
        parent_id="abc123",
    )
    event = NodeDiscoveredEvent.from_cst_node(node)
    assert event.node_id == node.node_id
    assert event.source_code == node.text
    assert event.source_hash == compute_source_hash(node.text)
    assert event.parent_id == "abc123"
```

### 3.3 Verify

```bash
devenv shell -- uv run pytest tests/ -k "node_discovered_event_from_cst" -x -v
```

---

## 4. Step 3: Delete `watcher.py`

**Goal:** Remove the entire module. All consumers call `parse_content()` directly and work with `CSTNode` objects.

### 4.1 Update `server.py`

In [server.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py):

**Remove** the import and field:
```diff
-from remora.lsp.watcher import ASTWatcher
```
```diff
-        self.watcher = ASTWatcher()
```

**Rewrite `_do_reparse`** ([L77-114](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py#L77-L114)) to use `parse_content` + `NodeDiscoveredEvent.from_cst_node()`:

```python
    async def _do_reparse(self, uri: str, text: str) -> None:
        """Execute the actual debounced reparse for *uri*."""
        from remora.core.discovery import parse_content
        from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent

        self._reparse_timers.pop(uri, None)
        try:
            cst_nodes = parse_content(uri, text)
            logger.debug("_do_reparse: %d nodes for %s", len(cst_nodes), uri)

            if self.event_store:
                old_agents = await self.event_store.list_nodes(file_path=uri)
                new_ids = {n.node_id for n in cst_nodes}
                old_ids = {a.node_id for a in old_agents}

                for orphan_id in old_ids - new_ids:
                    await self.event_store.append("nodes", NodeRemovedEvent(node_id=orphan_id))

                for node in cst_nodes:
                    await self.event_store.append("nodes", NodeDiscoveredEvent.from_cst_node(node))

            await self.refresh_code_lenses()
            await self.notify_agents_updated()
        except Exception:
            logger.exception("Error in _do_reparse for %s", uri)
```

### 4.2 Update `documents.py`

In [documents.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py):

**Rewrite `_emit_node_events`** to accept `list[CSTNode]`:

```python
from remora.core.discovery import CSTNode

async def _emit_node_events(uri: str, new_nodes: list[CSTNode]) -> None:
    """Emit NodeDiscovered/NodeRemoved events for a file's parse results."""
    if not server.event_store:
        return

    old_agents = await server.event_store.list_nodes(file_path=uri)
    old_ids = {a.node_id for a in old_agents}
    new_ids = {n.node_id for n in new_nodes}

    for orphan_id in old_ids - new_ids:
        await server.event_store.append("nodes", NodeRemovedEvent(node_id=orphan_id))

    for node in new_nodes:
        await server.event_store.append("nodes", NodeDiscoveredEvent.from_cst_node(node))
```

Update `did_open` and `did_save` — replace `server.watcher.parse(uri, text)` with:
```python
from remora.core.discovery import parse_content
new_nodes = parse_content(uri, text)
```

All downstream code changes from dict keys (`nd["node_id"]`) to attribute access (`node.node_id`).

### 4.3 Update `__main__.py` background scanner

In [__main__.py L251](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#L251):

```diff
-nodes = await asyncio.to_thread(server.watcher.parse, uri, text)
+from remora.core.discovery import parse_content
+nodes = await asyncio.to_thread(parse_content, uri, text)
```

Replace the manual `NodeDiscoveredEvent` construction ([L262-278](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#L262-L278)):

```python
batch_events = [NodeDiscoveredEvent.from_cst_node(n) for n in nodes]
```

Update `new_ids` construction:
```diff
-new_ids = {n["node_id"] for n in nodes}
+new_ids = {n.node_id for n in nodes}
```

### 4.4 Delete watcher.py and its tests

```bash
rm src/remora/lsp/watcher.py
rm tests/unit/test_lsp_watcher.py
```

The equivalent parent_id/full_name coverage now lives in `tests/test_discovery.py` via the `TestCSTNodeParentId` class from Step 1.

### 4.5 Verify

```bash
devenv shell -- uv run pytest tests/ -x -q
```

---

## 5. Step 4: Update `RemoraDB.update_edges`

**Goal:** Accept `CSTNode` directly — no more raw dicts.

### 5.1 Update the method signature

In [db.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/db.py):

```python
from remora.core.discovery import CSTNode

@async_db
def update_edges(self, nodes: list[CSTNode]) -> None:
    with contextlib.closing(self.conn.cursor()) as cursor:
        cursor.execute("BEGIN IMMEDIATE")
        try:
            for node in nodes:
                if node.parent_id:
                    cursor.execute(
                        "INSERT OR REPLACE INTO edges (from_id, to_id, edge_type) VALUES (?, ?, 'parent_of')",
                        (node.parent_id, node.node_id),
                    )
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise
```

### 5.2 Update call sites

All sites already have `list[CSTNode]` after watcher deletion:
```diff
-await server.db.update_edges(new_dicts)
+await server.db.update_edges(new_nodes)
```

### 5.3 Verify

```bash
devenv shell -- uv run pytest tests/ -x -q
```

---

## 6. Step 5: Move LSP Tables Out of `EventStore`

**Goal:** `core/event_store.py` should not create any LSP-specific tables.

### 6.1 Remove LSP tables from `EventStore.initialize()`

Delete the block at [event_store.py L200-251](file:///home/andrew/Documents/Projects/remora/src/remora/core/event_store.py#L200-L251) that creates `edges`, `activation_chain`, `proposals`, `cursor_focus`, and `command_queue`.

Keep `events`, `nodes`, and `subscriptions` table creation.

### 6.2 Remove proposals migration from `_migrate_routing_fields()`

Delete [event_store.py L427-433](file:///home/andrew/Documents/Projects/remora/src/remora/core/event_store.py#L427-L433):

```diff
-        proposal_columns = await asyncio.to_thread(_get_columns, "proposals")
-        if "file_path" not in proposal_columns:
-            await asyncio.to_thread(
-                self._conn.execute,
-                "ALTER TABLE proposals ADD COLUMN file_path TEXT",
-            )
```

### 6.3 Update `RemoraDB` to always call `_init_schema()`

In [db.py L48-72](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/db.py#L48-L72), the shared-connection mode currently skips `_init_schema()`. Change it:

```diff
         if connection is not None:
             self.db_path: Path | None = None
             self.conn = connection
             self.conn.row_factory = sqlite3.Row
             self._lock = lock if lock is not None else threading.Lock()
             self._shared = True
+            self._init_schema()  # Always create LSP tables — idempotent with IF NOT EXISTS
         else:
```

The `CREATE TABLE IF NOT EXISTS` statements are idempotent — safe even if tables already exist.

### 6.4 Verify

```bash
devenv shell -- uv run pytest tests/ -x -q
```

---

## 7. Step 6: Refactor `LazyGraph`

**Goal:** Remove raw SQLite coupling. LazyGraph queries nodes through the `EventStore` API.

### 7.1 Change constructor

In [graph.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/graph.py):

```python
class LazyGraph:
    """Graph topology backed by RemoraDB (edges) and EventStore (nodes)."""

    def __init__(self, db: RemoraDB, event_store=None):
        # Edges connection — RemoraDB
        self._edges_conn = sqlite3.connect(str(db.db_path), check_same_thread=False)
        self._edges_conn.row_factory = sqlite3.Row

        # Node queries go through EventStore API
        self._event_store = event_store

        self._lock = threading.Lock()
        self.graph = rx.PyDiGraph()
        self.node_indices: dict[str, int] = {}
        self.loaded_files: set[str] = set()
        self._expanded: set[str] = set()
```

### 7.2 Rewrite node query methods

Replace `_get_node` and `_get_nodes_for_file` to use EventStore synchronously. Since these are called from sync methods, use the `EventStore._read_conn` directly (it's a dedicated read connection):

```python
    def _get_nodes_for_file(self, file_path: str) -> list[dict]:
        if not self._event_store:
            return []
        agents = self._event_store.list_nodes_sync(file_path=file_path)
        return [self._agent_to_dict(a) for a in agents]

    def _get_node(self, node_id: str) -> dict | None:
        if not self._event_store:
            return None
        agent = self._event_store.get_node_sync(node_id)
        return self._agent_to_dict(agent) if agent else None

    @staticmethod
    def _agent_to_dict(agent) -> dict:
        return {"node_id": agent.node_id, "id": agent.node_id, **agent.to_row()}
```

> **Note:** You'll need to add `get_node_sync` and `list_nodes_sync` to `EventStore` — simple wrappers that query `_read_conn` directly without async. OR use the existing sync read connection pattern already in `EventStore._read_conn`.

### 7.3 Update `server.py` constructor

[server.py L33-34](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py#L33-L34):

```diff
-        es_db_path = str(event_store._db_path) if event_store else None
-        self.graph = LazyGraph(self.db, event_store_db_path=es_db_path)
+        self.graph = LazyGraph(self.db, event_store=event_store)
```

### 7.4 Update `close()`

Remove `self._nodes_conn.close()` — no more raw node connection.

### 7.5 Update tests

In `tests/unit/test_lsp_graph.py`, fixtures pass `event_store_db_path` — change to `event_store`:

```diff
-graph = LazyGraph(db, event_store_db_path=str(store._db_path))
+graph = LazyGraph(db, event_store=store)
```

### 7.6 Verify

```bash
devenv shell -- uv run pytest tests/unit/test_lsp_graph.py tests/test_integration_graph.py -x -v
```

---

## 8. Step 7: Fix `CompanionDispatcher` EventBus Subscription Bug

**Goal:** Fix broken event routing in the companion layer.

### 8.1 The bug

In [dispatcher.py L72](file:///home/andrew/Documents/Projects/remora/src/remora/companion/dispatcher.py#L72):

```python
self._bus.subscribe(event_type.__name__, handler_callback)
```

`EventBus.subscribe()` ([event_bus.py L64](file:///home/andrew/Documents/Projects/remora/src/remora/core/event_bus.py#L64)) expects `event_type: type[Any]`. The `._handlers` dict is keyed by **types**, and `emit()` uses `isinstance(event, registered_type)` to match. Passing a **string** means:
- The handler is stored under key `"CursorFocusEvent"` (a string)
- `isinstance(event, "CursorFocusEvent")` always returns `False`
- **No companion events are ever dispatched**

### 8.2 The fix

```diff
-            self._bus.subscribe(event_type.__name__, handler_callback)
+            self._bus.subscribe(event_type, handler_callback)
```

### 8.3 Also fix `_bus.publish` → `_bus.emit`

At [dispatcher.py L86](file:///home/andrew/Documents/Projects/remora/src/remora/companion/dispatcher.py#L86):

```diff
-            await self._bus.publish(new_event)
+            await self._bus.emit(new_event)
```

`EventBus` has no `publish` method — it has `emit`. This would raise `AttributeError` whenever a companion handler produces a new event.

### 8.4 Write a test

```python
import pytest
from unittest.mock import AsyncMock
from remora.core.event_bus import EventBus
from remora.core.events import CursorFocusEvent

@pytest.mark.asyncio
async def test_companion_dispatcher_subscribes_with_types():
    """CompanionDispatcher must subscribe with event types, not strings."""
    bus = EventBus()
    # After fix, CursorFocusEvent should be a type key in bus._handlers
    # ...construct dispatcher with bus, call start()...
    assert CursorFocusEvent in bus._handlers
    assert "CursorFocusEvent" not in bus._handlers
```

### 8.5 Verify

```bash
devenv shell -- uv run pytest tests/companion/ -x -v
```

---

## 9. Step 8: Cleanup

### 9.1 Duplicated section header in `events.py`

[events.py L204-210](file:///home/andrew/Documents/Projects/remora/src/remora/core/events.py#L204-L210) has the same comment block duplicated:

```python
# ============================================================================
# Union Type for Pattern Matching
# ============================================================================

# ============================================================================
# Union Type for Pattern Matching
# ============================================================================
```

Delete one copy.

### 9.2 Remove dead imports

After deleting `watcher.py`, grep for any remaining imports:

```bash
devenv shell -- grep -rn "from remora.lsp.watcher" src/
devenv shell -- grep -rn "import watcher" src/
```

Remove any hits.

### 9.3 `NodeRemovedEvent.file_path` consistency

[__main__.py L281](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#L281) passes `file_path=uri` to `NodeRemovedEvent`, but the model at [events.py L197-201](file:///home/andrew/Documents/Projects/remora/src/remora/core/events.py#L197-L201) does not declare a `file_path` field. Either add it to the model or remove it from call sites — choose consistency.

---

## 10. Final Verification

### 10.1 Full test suite

```bash
devenv shell -- uv run pytest tests/ -x -q --tb=short
```

### 10.2 Import smoke test

```bash
devenv shell -- python -c "
from remora.core.discovery import CSTNode, parse_content, compute_node_id
from remora.core.events import NodeDiscoveredEvent
from remora.lsp.server import RemoraLanguageServer
from remora.lsp.graph import LazyGraph
from remora.lsp.db import RemoraDB
from remora.companion.dispatcher import CompanionDispatcher
print('All imports OK')
"
```

### 10.3 Verify watcher is fully gone

```bash
devenv shell -- grep -rn "watcher" src/remora/ --include="*.py" | grep -v __pycache__
```

Expected: zero hits on `ASTWatcher` or `from remora.lsp.watcher`.

### 10.4 Summary of net changes

| Change | Files Modified | Files Deleted | Net LOC |
|--------|---------------|---------------|---------|
| CSTNode `parent_id` | `discovery.py` | — | +20 |
| `from_cst_node()` factory | `events.py` | — | +15 |
| Delete watcher | `server.py`, `documents.py`, `__main__.py` | `watcher.py`, `test_lsp_watcher.py` | **−245** |
| `update_edges` CSTNode | `db.py` | — | 0 |
| LSP table migration | `event_store.py`, `db.py` | — | **−58** |
| LazyGraph refactor | `graph.py`, `server.py` | — | −5 |
| Companion fixes | `dispatcher.py` | — | 0 |
| Cleanup | `events.py` + misc | — | −5 |

**Net effect:** ~275 lines deleted, 1 module eliminated, 2 architectural violations resolved, 1 data corruption bug fixed, 1 event routing bug fixed.
