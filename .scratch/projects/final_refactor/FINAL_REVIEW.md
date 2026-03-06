# Remora Final Refactor Review

**Reviewer:** Final review agent  
**Date:** 2026-03-06  
**Scope:** Complete codebase audit + treesitter-node-persistent-ids integration verification  
**Files Examined:** 17 source modules, 610+ lines of `discovery.py`, 1250 lines of `event_store.py`, full LSP/companion/service layers

---

## Table of Contents

1. [Treesitter Semantic Identity — Integration Verification](#1-treesitter-semantic-identity--integration-verification)
2. [Intern Report Evaluation](#2-intern-report-evaluation)
3. [Critical Findings — The Real Problems](#3-critical-findings--the-real-problems)
4. [Recommended Refactors — Ordered Implementation Plan](#4-recommended-refactors--ordered-implementation-plan)
5. [What NOT to Change](#5-what-not-to-change)

---

## 1. Treesitter Semantic Identity — Integration Verification

The [implementation_plan.md](file:///home/andrew/Documents/Projects/remora/.scratch/projects/treesitter-node-persistent-ids/implementation_plan.md) specified 8 components. Here's the verified status of each:

| Component | Status | Evidence |
|-----------|--------|----------|
| **1. Core Identity** (`discovery.py`) | ✅ Complete | `compute_node_id(file_path, node_type, full_name)` uses SHA256. `compute_source_hash` unified. `_assign_semantic_identity` computes containment-based `full_name`. ([L77-89](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#L77-L89)) |
| **2. LSP Watcher** (`watcher.py`) | ✅ Complete | `parse()` replaces `parse_and_inject_ids()`. No `old_nodes` parameter. Uses `cst.node_id` directly. No `generate_id()` calls. ([L23-31](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#L23-L31)) |
| **3. LSP Handlers** (`documents.py`) | ✅ Complete | `_emit_node_events` helper extracted. `watcher.parse(uri, text)` called without `old_dicts`. Orphan detection correctly diffs against EventStore. ([L12-39](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py#L12-L39)) |
| **4. LSP Server** (`server.py`) | ✅ Complete | `_do_reparse` uses `watcher.parse()`. No `_injecting` set. Orphan detection delegated to handler. ([L77-114](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py#L77-L114)) |
| **5. Background Scanner** (`__main__.py`) | ✅ Complete | Uses `watcher.parse(uri, text)` without `old_nodes`. ([L121-357](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#L121-L357)) |
| **6. Reconciler** (`reconciler.py`) | ✅ Complete | Imports `compute_source_hash` from `discovery`. No local hash functions. ([L17](file:///home/andrew/Documents/Projects/remora/src/remora/core/reconciler.py#L17)) |
| **7. Spawn Child** (`spawn_child.py`) | ✅ Complete | Imports `compute_node_id, compute_source_hash` from `discovery`. No local duplicates. Uses new signature `compute_node_id(file_path, node_type, full_name)`. ([L18](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#L18)) |
| **8. Exports** (`core/__init__.py`) | ✅ Complete | `compute_source_hash` exported alongside `compute_node_id`. |

**Verdict:** The semantic identity refactor is **fully implemented and integrated**. Every component listed in the plan is correctly migrated. ID determinism is mathematically guaranteed by `sha256(file_path:node_type:full_name)[:16]`.

**However**, the refactor revealed *follow-on cleanup opportunities* that were not executed. These are the real focus of this review.

---

## 2. Intern Report Evaluation

### Architectural Review Report — Grading

| Finding | Assessment | Notes |
|---------|-----------|-------|
| **Opp A: LSP tables in EventStore** | ✅ **Correct and critical.** | EventStore.initialize() creates `edges`, `activation_chain`, `proposals`, `cursor_focus`, `command_queue` ([L200-251](file:///home/andrew/Documents/Projects/remora/src/remora/core/event_store.py#L200-L251)). These are LSP-specific operational tables that violate layer isolation. The intern correctly identified this. |
| **Opp B: Node projection regex queries** | ⚠️ **Mislabeled.** | The intern references "regex over source_code" in projections.py, but the actual `projections.py` ([L82-236](file:///home/andrew/Documents/Projects/remora/src/remora/core/projections.py#L82-L236)) just has regex for *stub detection* (`_STUB_BODY_RE`, `_TRIVIAL_CONTENT_RE`). These are simple syntactic patterns used during projection to identify scaffold nodes — they are **not** full-text search queries. This is a low-priority concern at best. |
| **Opp C: LazyGraph DB coupling** | ✅ **Correct and critical.** | `LazyGraph.__init__` opens raw `sqlite3.connect()` to the EventStore DB path ([L19-35](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/graph.py#L19-L35)), then runs `SELECT * FROM nodes` directly. Bypasses `EventStore.get_node()` and `list_nodes()` API entirely. |
| **Opp D: Runner/LSP coupling** | ⚠️ **Correct idea, wrong emphasis.** | The intern suggests splitting runner.py into "generic swarm" vs "LSP UI", but the runner already has `_HeadlessServer` for CLI mode. The *real* problem isn't LSP-specific formatting — it's that runner.py at 743 lines mixes **cooldown/depth/concurrency logic** with **tool binding, proposal storage, and event emission**. The split should be along execution-orchestration vs agent-lifecycle boundaries, not LSP vs non-LSP. |

### Code Review Report — Grading

| Finding | Assessment | Notes |
|---------|-----------|-------|
| **Opp A: Delete watcher.py** | ✅ **Correct and the highest-priority item.** | The watcher's `_assign_parents` ([L89-129](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#L89-L129)) is a near-verbatim duplicate of `_assign_semantic_identity` in `discovery.py` ([L340-406](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#L340-L406)). Same containment algorithm, same O(n²) scan, same parent-resolution logic. CSTNode already has `full_name` and `node_id` — the watcher **re-computes** `full_name` from scratch and discards the one from `discovery.py`. |
| **Opp B: Truncated file node** | ✅ **Correct — silent data loss bug.** | [watcher.py L61](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#L61): `source_code = text[:200]` truncates file nodes to 200 chars. This means `NodeDiscoveredEvent.source_code` for file-type nodes stores incomplete content. The `_create_file_node` in `discovery.py` correctly stores the full content. |
| **Opp C: Direct CSTNode event flow** | ⚠️ **Direction is right, emphasis is wrong.** | The intern suggests updating `db.update_edges` to accept `list[CSTNode]`. That's the wrong layer to focus on. The real issue is the `CSTNode → dict → NodeDiscoveredEvent` pipeline that loses type safety. The fix should be: `CSTNode` fields should map directly to `NodeDiscoveredEvent` fields without an intermediate dict. `update_edges` should either accept `CSTNode` **or** the event objects, not raw dicts. |

---

## 3. Critical Findings — The Real Problems

### F1: Duplicated Containment Logic (CRITICAL — DRY violation)

**The core problem:** Two independent implementations of the exact same parent-assignment algorithm exist:

1. `discovery.py:_assign_semantic_identity` ([L340-406](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#L340-L406)) — computes `full_name` and `node_id` based on line-range containment. Returns `CSTNode` objects with correct `full_name`.

2. `watcher.py:ASTWatcher._assign_parents` ([L89-129](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#L89-L129)) — computes `full_name` and `parent_id` based on line-range containment. Operates on dicts.

The watcher receives `CSTNode` objects that already have correct `full_name` and `node_id`, then **throws away the `full_name`** (sets it to `""` on [L74](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#L74)), and recomputes it from scratch in `_assign_parents`. The only thing the watcher adds that discovery doesn't is `parent_id`. But `parent_id` could trivially be computed inside `_assign_semantic_identity` since it already finds the parent node.

**Impact:** Any behavioral difference between these two implementations would cause the LSP path to compute different `full_name` values than the core discovery path, leading to different `node_id` values (since `node_id = sha256(file_path:node_type:full_name)`). This would break the entire semantic identity model.

### F2: CSTNode Lacks `parent_id` (Root Cause of F1)

`CSTNode` has no `parent_id` field. This is the sole reason `watcher.py` exists — to compute and assign `parent_id`. If `CSTNode` gained a `parent_id` field and `_assign_semantic_identity` populated it, the watcher's only remaining purpose would be the `function`/`method` deduplication filter and the file-node name override (both trivial).

### F3: File Node Truncation Bug

[watcher.py L60-61](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#L60-L61):
```python
if node_type == "file":
    name = stem
    source_code = text[:200]
```

File nodes persisted through the LSP path carry only 200 chars of source. File nodes persisted through the CLI/reconciler path carry full source. This is inconsistent behavior between execution paths — the kind of subtle data corruption that causes hard-to-diagnose downstream failures.

### F4: Schema Ownership Split (Architectural)

LSP-specific tables are defined in **two** places:
1. `EventStore.initialize()` ([L200-251](file:///home/andrew/Documents/Projects/remora/src/remora/core/event_store.py#L200-L251)) — creates `edges`, `activation_chain`, `proposals`, `cursor_focus`, `command_queue`
2. `RemoraDB._init_schema()` ([L74-123](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/db.py#L74-L123)) — creates the exact same tables

The `RemoraDB` operates in two modes:
- **Shared mode:** receives a connection from EventStore (tables already exist)
- **Standalone mode:** creates its own connection and schema

This means the LSP table definitions are **duplicated** across both files. If one changes without the other, schema drift occurs. More importantly, `EventStore` — a **core** module — has hardcoded knowledge of LSP-layer tables. This violates the stated architecture: *"EventStore is in the core module and should be entirely generic"*.

### F5: LazyGraph Bypasses EventStore API

[graph.py L19-35](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/graph.py#L19-L35): `LazyGraph` opens its own raw SQLite connection to the EventStore database file and runs `SELECT * FROM nodes WHERE ...` directly. The EventStore exposes `get_node(node_id)`, `list_nodes(file_path=...)`, and `get_node_at_position(file_path, line)` — all of which LazyGraph should use. The raw connection:
- Ignores WAL/read-only connection setup that EventStore configures
- Could produce phantom reads or corrupt state under concurrent writes
- Tightly couples LSP graph topology to the physical schema of the nodes table

### F6: `NodeDiscoveredEvent` Construction is Tedious and Error-Prone

Every call site that emits a `NodeDiscoveredEvent` manually maps dict keys or CSTNode attributes into the event constructor. This pattern is repeated in:
- [documents.py:_emit_node_events](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py#L24-L38) — maps dict keys
- [reconciler.py](file:///home/andrew/Documents/Projects/remora/src/remora/core/reconciler.py#L97-L113) — maps CSTNode attributes with `getattr`
- [spawn_child.py](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#L113-L128) — manual construction
- [__main__.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py) — same pattern

A factory method like `NodeDiscoveredEvent.from_cst_node(node: CSTNode)` would eliminate all this boilerplate and ensure consistent field mapping.

### F7: EventBus Subscribe API Mismatch

`EventBus.subscribe` ([L64-68](file:///home/andrew/Documents/Projects/remora/src/remora/core/event_bus.py#L64-L68)) expects `event_type: type[Any]`. But `CompanionDispatcher.start()` at [L72](file:///home/andrew/Documents/Projects/remora/src/remora/companion/dispatcher.py#L72) calls `self._bus.subscribe(event_type.__name__, handler_callback)`, passing a **string** (the class name) instead of the type. The `EventBus.emit` method uses `isinstance(event, registered_type)` for matching — passing a string would cause `isinstance(event, "CursorFocusEvent")` which always returns `False`. This means **companion event routing may be completely broken** unless there's another registration path in play.

### F8: EventStore is Overgrown (1250 lines)

`event_store.py` handles:
- SQLite connection management + WAL setup
- Schema creation for 7+ tables
- Lock/retry/cancel-safety logic
- Event serialization
- Event append (single + batch)
- Trigger queue management
- Event replay
- Node CRUD (get_node, list_nodes, get_node_at_position, set_node_status, remove_nodes_for_file)
- WAL checkpoint management
- Graph ID management

This is too many responsibilities. The node CRUD section alone (~200 lines) should extracted — it's fundamentally a read API over the projected `nodes` table, not event-sourcing logic.

---

## 4. Recommended Refactors — Ordered Implementation Plan

These are dependency-ordered. Each builds on the previous.

### R1: Add `parent_id` to CSTNode, Compute in `_assign_semantic_identity`

**Files:** `discovery.py`

1. Add `parent_id: str | None = None` to `CSTNode`.
2. In `_assign_semantic_identity`, when a parent is found, store its `node_id` as the child's `parent_id`.
3. Return the resolved list with `parent_id` populated.

**Impact:** This is the foundational change. Everything else flows from it.

### R2: Delete `watcher.py`

**Files:** `watcher.py` (DELETE), `documents.py`, `server.py`, `__main__.py`

Once `CSTNode` has `parent_id`, the watcher's only remaining jobs are:
1. ~~Assign parent_id~~ (now in discovery)
2. ~~Compute full_name~~ (already in discovery)
3. `function`/`method` deduplication — move to `parse_content` in `discovery.py`
4. File-node name override (`stem` vs `name`) — move to `_create_file_node_from_content`

All consumers (`documents.py`, `server.py`, `__main__.py`) call `parse_content()` directly and iterate over `CSTNode` objects instead of dicts.

**Eliminates:** 130 lines, one entire module, duplicated O(n²) containment logic, file truncation bug.

### R3: Add `NodeDiscoveredEvent.from_cst_node()`

**Files:** `events.py`

```python
@classmethod
def from_cst_node(cls, node: CSTNode) -> "NodeDiscoveredEvent":
    return cls(
        node_id=node.node_id,
        node_type=node.node_type,
        name=node.name,
        full_name=node.full_name,
        file_path=node.file_path,
        start_line=node.start_line,
        end_line=node.end_line,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        source_code=node.text,
        source_hash=compute_source_hash(node.text),
        parent_id=node.parent_id,
    )
```

Replace all 4+ manual construction sites with `NodeDiscoveredEvent.from_cst_node(node)`.

### R4: Move LSP Tables Out of EventStore

**Files:** `event_store.py`, `db.py`

1. Remove `edges`, `activation_chain`, `proposals`, `cursor_focus`, `command_queue` creation from `EventStore.initialize()` (delete [L200-251](file:///home/andrew/Documents/Projects/remora/src/remora/core/event_store.py#L200-L251)).
2. Remove the proposals migration from `EventStore._migrate_routing_fields()` ([L427-433](file:///home/andrew/Documents/Projects/remora/src/remora/core/event_store.py#L427-L433)).
3. `RemoraDB` always creates its own tables in `_init_schema()` — even in shared-connection mode.
4. `RemoraDB.__init__` shared mode still receives the connection from EventStore, but now creates its own tables on it. The distinction between "shared" and "standalone" collapses to just "who owns the connection" rather than "who creates the schema".

**Impact:** EventStore drops from ~1250 lines. `core/` module no longer knows about LSP-specific tables.

### R5: Refactor LazyGraph to Use EventStore API

**Files:** `graph.py`, `server.py`

1. `LazyGraph.__init__` takes an `EventStore` instance instead of a raw DB path.
2. `_get_node()` calls `await event_store.get_node(node_id)` (or the sync equivalent via `to_thread`).
3. `_get_nodes_for_file()` calls `await event_store.list_nodes(file_path=...)`.
4. Edges still come from `RemoraDB` via the existing `_edges_conn`.

**Impact:** Removes raw SQL coupling. LazyGraph becomes resilient to nodes-table schema changes.

### R6: Fix CompanionDispatcher EventBus subscription

**Files:** `companion/dispatcher.py`

Change [L72](file:///home/andrew/Documents/Projects/remora/src/remora/companion/dispatcher.py#L72):
```diff
-self._bus.subscribe(event_type.__name__, handler_callback)
+self._bus.subscribe(event_type, handler_callback)
```

This is likely the reason companion features may not respond to events.

### R7: Update `db.update_edges` to accept `CSTNode` directly

**Files:** `db.py`, `documents.py`

After R2 (watcher deletion), the edge-update call sites will have `list[CSTNode]` instead of `list[dict]`. `update_edges` should accept `CSTNode` directly:

```python
def update_edges(self, nodes: list[CSTNode]) -> None:
    for node in nodes:
        if node.parent_id:
            # INSERT edge ...
```

This eliminates the last dict-based data flow in the LSP ingestion pipeline.

---

## 5. What NOT to Change

These modules are well-designed and should be preserved as-is:

| Module | Why It's Good |
|--------|---------------|
| **`core/event_bus.py`** (141L) | Clean Observer pattern. Type-based subscription, async streaming, `wait_for` with timeout — all in 141 lines. |
| **`core/events.py`** (279L) | Frozen Pydantic models with clear type hierarchy. Union type alias `RemoraEvent` enables pattern matching. |
| **`core/execution.py`** | Unified `execute_agent_turn` cleanly separates prompt building, workspace provision, tool binding, and kernel execution. |
| **`core/state_manager.py`** | Beautifully typed key-value wrapper over Cairn. |
| **`core/subscriptions.py`** | Clean pattern matching for event routing. |
| **`companion/dispatcher.py`** (99L, after F7 fix) | Elegant routing table + debounced dispatch. The architecture is right — just the EventBus call is wrong. |
| **`companion/startup.py`** | Clean pipeline assembly. |
| **`extensions.py`** | mtime-cached extension loader. Simple and correct. |
| **`core/agent_node.py`** | Single Pydantic model, no subclasses. Good adherence to the design spec. |

---

## Summary Priority Matrix

| Priority | Refactor | Effort | Impact |
|----------|----------|--------|--------|
| P0 | **R1+R2:** Add `parent_id` to CSTNode, delete watcher.py | Medium | Eliminates DRY violation, fixes truncation bug, removes 130 LOC |
| P0 | **R6:** Fix CompanionDispatcher subscribe bug | Trivial | May fix broken companion event routing |
| P1 | **R3:** `NodeDiscoveredEvent.from_cst_node()` | Small | Eliminates boilerplate at 4+ call sites |
| P1 | **R4:** Move LSP tables out of EventStore | Medium | Restores layer isolation in core |
| P2 | **R5:** LazyGraph uses EventStore API | Small | Removes raw SQL coupling |
| P2 | **R7:** `update_edges` accepts CSTNode | Small | Type safety improvement |

