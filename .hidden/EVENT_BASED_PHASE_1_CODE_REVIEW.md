# EventBased Phase 1: Code Review

> **Scope:** All files created or modified during the Phase 1 AgentNode implementation (Tasks 1-11 of `docs/plans/2026-03-02-agentnode-implementation.md`).
>
> **Reference:** `docs/EventBased_Concept.md` (authoritative design document)
>
> **Date:** 2026-03-02

---

## Table of Contents

1. [Summary of What Phase 1 Implemented](#1-summary)
2. [File-by-File Review](#2-file-by-file-review)
3. [Categorized Issues](#3-categorized-issues)
4. [Alignment with EventBased Concept](#4-alignment-with-eventbased-concept)
5. [Prioritized Improvement Recommendations](#5-prioritized-improvement-recommendations)

---

## 1. Summary

Phase 1 introduced the **AgentNode unified model** -- the single Pydantic object that replaces `AgentState`, `ASTAgentNode`, `ExtensionNode`, and `AgentMetadata` from the old architecture. It serves three roles:

1. **DB row** -- serialized to/from the `nodes` SQLite table via `to_row()`/`from_row()`.
2. **LLM prompt source** -- `to_system_prompt()` generates the full system prompt for the agent's LLM kernel.
3. **LSP protocol data** -- `to_code_lens()`, `to_hover()`, `to_code_actions()`, `to_document_symbol()` produce lsprotocol objects for the Neovim UI.

Supporting infrastructure:

- **`NodeProjection`** processes events and writes to the `nodes` table (upsert on discovery, status transitions on agent lifecycle events, delete on removal).
- **`NodeDiscoveredEvent` / `NodeRemovedEvent`** are new frozen dataclass events for the node lifecycle.
- **`AgentExtension`** base class and `load_extensions()` provide the "specialization is data" mechanism.
- **`EventStore`** was extended with: `nodes` table creation, projection wiring in `append()`, and `get_node()`/`list_nodes()` query methods.

All Phase 1 tasks (1-11) were completed with TDD. 8 test files were created covering unit, projection, and integration scenarios.

### Files Created
| File | Lines | Role |
|------|-------|------|
| `src/remora/core/agent_node.py` | 254 | Core model + serialization + LSP/LLM conversions |
| `src/remora/core/projections.py` | 130 | Event -> nodes table projection |
| `src/remora/extensions.py` | 89 | Extension base class + mtime-cached loader |
| `tests/unit/test_agent_node.py` | 225 | AgentNode creation, serialization, prompt, LSP |
| `tests/unit/test_extensions.py` | 109 | Extension base class + loader |
| `tests/unit/test_node_events.py` | 51 | NodeDiscoveredEvent / NodeRemovedEvent |
| `tests/unit/test_nodes_table.py` | 70 | Schema + indexes verification |
| `tests/unit/test_projections.py` | 162 | Projection logic for all event types |
| `tests/unit/test_event_store_projection.py` | 104 | EventStore.append() -> projection wiring |
| `tests/unit/test_event_store_nodes_query.py` | 72 | get_node() / list_nodes() queries |
| `tests/integration/test_agent_node_pipeline.py` | 144 | Full lifecycle: discover -> run -> complete -> LSP -> remove |

### Files Modified
| File | Change |
|------|--------|
| `src/remora/core/events.py` | Added `NodeDiscoveredEvent`, `NodeRemovedEvent`, updated union type + `__all__` |
| `src/remora/core/event_store.py` | Added `nodes` table DDL, `projection` parameter, projection call in `append()`, `get_node()`, `list_nodes()` |
| `src/remora/core/__init__.py` | Added exports for `AgentNode`, `AgentToolSchema`, `NodeDiscoveredEvent`, `NodeRemovedEvent`, `NodeProjection` |

---

## 2. File-by-File Review

### 2.1 `src/remora/core/agent_node.py` (254 lines)

**Purpose:** Core `AgentNode` Pydantic model and `ToolSchema` dataclass.

**Strengths:**
- Clean single-file design that genuinely unifies three responsibilities without subclassing.
- `from_row()` / `to_row()` properly handle the SQLite JSON-in-TEXT-column pattern.
- Lazy `lsprotocol` imports inside each LSP method avoid loading the heavy dependency at import time.
- `to_system_prompt()` is well-structured and includes graph context, extension specialization, and mounted workspaces.

**Issues:**

| # | Severity | Line(s) | Issue |
|---|----------|---------|-------|
| 1 | Low | 9 | `hashlib` is imported but never used. Dead import. |
| 2 | Medium | 38 | `to_code_action()` return type annotation references `lsp.CodeAction` but `lsp` is not in scope at annotation-evaluation time. Works because of `from __future__ import annotations` (all annotations are strings), but any runtime type inspection (e.g. `get_type_hints()`) would fail. This pattern repeats on lines 117, 158, 179, 200, 236. |
| 3 | Medium | 92-98 | `to_row()` uses `model_dump()` but then manually overrides JSON fields. The `model_dump()` call serializes `extra_tools` as a list of dicts (Pydantic serializes nested dataclasses), but the manual override on line 95 re-serializes via `t.__dict__`. This is redundant and inconsistent -- `model_dump()` already produced dicts for the `ToolSchema` fields, but since `ToolSchema` is a plain dataclass (not a Pydantic model), `model_dump()` actually returns the raw dataclass objects. So the `__dict__` fallback is necessary, but the interaction is confusing. |
| 4 | Medium | 95 | `to_row()` serializes `ToolSchema` via `t.__dict__`, but `from_row()` (line 108) deserializes via `ToolSchema(**t)`. If `ToolSchema` ever has computed properties, class variables, or non-init fields, `__dict__` will include them and `ToolSchema(**t)` will reject them. Use `dataclasses.asdict(t)` instead for correctness. |
| 5 | Medium | 96-97 | `to_row()` serializes `SubscriptionPattern` via `s.__dict__`. `SubscriptionPattern` is a dataclass, so `__dict__` works, but this bypasses any custom serialization. `from_row()` uses `SubscriptionPattern(**s)` to reconstruct -- same fragility as issue #4. |
| 6 | Low | 58 | `model_config = ConfigDict(frozen=False)` -- explicitly setting `frozen=False` is the default. Not harmful, but unnecessary. If `AgentNode` instances should be mutable (they are -- status changes), this is fine, but worth a comment explaining why mutability is needed. |
| 7 | Low | 161-166 | Status icon map in `to_code_lens()` is hardcoded. If a new status is added (the concept doc mentions `"pending_approval"`), the fallback is `"?"` which is functional but not obvious to users. |
| 8 | Info | 127-154 | `to_system_prompt()` hardcodes `"Python"` in the prompt template (line 129: `"a Python {self.node_type}"`). The concept doc supports non-Python languages via tree-sitter. This will need parameterizing. |
| 9 | Info | 129 | The system prompt uses f-string with triple-quote, embedding `self.source_code` directly. No sanitization. If the source code itself contains triple-backtick markdown, the prompt will have broken fencing. Unlikely in practice but technically a rendering bug. |

### 2.2 `src/remora/core/projections.py` (130 lines)

**Purpose:** `NodeProjection` class that processes events into the `nodes` table.

**Strengths:**
- Clean event dispatch with clear per-event-type methods.
- Upsert correctly preserves `status`, `last_trigger_event`, and `last_completed_at` on re-discovery.
- Extension matching is straightforward (first match wins, consistent with `load_extensions` alphabetical ordering).

**Issues:**

| # | Severity | Line(s) | Issue |
|---|----------|---------|-------|
| 10 | **High** | 76 | `json.dumps(value, default=lambda o: o.__dict__)` -- the `lambda` captures `o` generically. If an extension's `get_extension_data()` returns objects with non-serializable nested attributes (e.g., Pydantic models, objects with `__slots__`), this will either produce incorrect output or raise. `__dict__` doesn't work for slotted classes. Should use `dataclasses.asdict()` for dataclasses or `.model_dump()` for Pydantic models. |
| 11 | **High** | 104, 108, 115, 122, 129 | Every projection method calls `conn.commit()` individually. When called from `EventStore.append()`, the event has already been committed to the `events` table (line 195 of `event_store.py`). This means: (a) redundant I/O (extra fsync per event), (b) if the projection fails mid-way, the event is committed but the node table is inconsistent, violating the "EventLog is the single source of truth" principle. The projection should not commit -- the caller should manage the transaction boundary. |
| 12 | Medium | 31-42 | `apply()` uses `isinstance()` dispatch. Every new event type that affects nodes requires adding a new `elif` branch. Consider a registry/dispatch-dict pattern. |
| 13 | Medium | 44-103 | `_project_node_discovered()` builds the full row dict every time, including all 20 columns. The upsert's `ON CONFLICT` clause explicitly lists 14 columns. If a column is added to the `nodes` table but not to the upsert's update list, it will silently use the default value on conflict instead of being updated. The column lists are not derived from a shared source. |
| 14 | Medium | 110-114 | `_project_agent_start()` updates status to `'running'` but does NOT update `last_trigger_event`. The `AgentNode` model has a `last_trigger_event` field, the `nodes` table has the column, but no projection method ever writes to it. It's always `""`. This is dead schema. |
| 15 | Low | 31 | `apply()` accepts `event: RemoraEvent` but `RemoraEvent` is a union of ~15+ types. Most events are silently ignored (no `else` clause, no logging). This is correct behavior but makes debugging difficult -- a typo in event type or a new event type will silently pass through. |

### 2.3 `src/remora/core/event_store.py` (449 lines)

**Purpose:** SQLite-backed event store with reactive trigger queue, now extended with `nodes` table and projection wiring.

**Strengths:**
- Clean async interface with `asyncio.Lock` for thread safety.
- `nodes` table DDL is well-designed with proper indexes.
- `get_node()` and `list_nodes()` correctly use `asyncio.to_thread()` for DB access.
- `list_nodes()` supports filtering by `file_path` and `node_type` with proper parameterized queries.

**Issues:**

| # | Severity | Line(s) | Issue |
|---|----------|---------|-------|
| 16 | **High** | 186-200 | Transaction boundary problem. The `append()` method does: (1) `INSERT INTO events` + `conn.commit()` (line 195), then (2) `self._projection.apply(conn, event)` which does its own `conn.commit()`. If the projection fails (e.g., malformed event data), the event is committed but the nodes table is not updated. The event and its projection should be in the same transaction. |
| 17 | Medium | 200 | `asyncio.to_thread(self._projection.apply, self._conn, event)` runs the projection in a thread. This is correct for avoiding blocking the event loop, but the projection's `conn.commit()` calls happen inside the `self._lock` context, so the commit is safe. However, if projection is ever made async (e.g., to support async extensions), this `to_thread` wrapper will need restructuring. |
| 18 | Medium | 30-35 | Constructor accepts `projection: "NodeProjection | None" = None` as an optional parameter. This means an `EventStore` without a projection will silently not maintain the `nodes` table, even though the table is always created. Querying `get_node()` or `list_nodes()` on a projection-less store returns empty results -- no error, no warning. This could confuse callers. |
| 19 | Low | 373-389 | `get_node()` does a lazy import of `AgentNode` (line 375). This is fine for avoiding circular imports, but `list_nodes()` also does the same lazy import (line 398). Both could be moved to module level under `TYPE_CHECKING` (which is already done on line 21) and resolved at runtime via `if TYPE_CHECKING` pattern. Actually, the lazy import IS needed at runtime since `TYPE_CHECKING` is `False`. The current approach is correct but worth a comment explaining why. |
| 20 | Low | 405-418 | `list_nodes()` builds queries with string concatenation (`query += " WHERE " + ...`). While the values are parameterized (safe from SQL injection), the pattern is fragile for maintenance. A query builder or at least a helper would be cleaner. |
| 21 | Info | 61-65 | `sqlite3.connect(..., check_same_thread=False)` -- necessary because the connection is used from `asyncio.to_thread()`, but this disables SQLite's thread-safety check entirely. The `asyncio.Lock` provides mutual exclusion, but only within the same event loop. If two event loops somehow share an `EventStore` instance, there's no protection. Low risk in practice. |

### 2.4 `src/remora/core/events.py` (224 lines)

**Purpose:** All frozen dataclass event types for the Remora system.

**Strengths:**
- Consistent use of `@dataclass(frozen=True, slots=True)` across all event types.
- `timestamp` field with `default_factory=time.time` is consistent across all events.
- Clean categorization with section headers.
- `RemoraEvent` union type enables exhaustive pattern matching.

**Issues:**

| # | Severity | Line(s) | Issue |
|---|----------|---------|-------|
| 22 | Medium | 139-153 | `NodeDiscoveredEvent` is missing `start_byte` and `end_byte` fields. `CSTNode` (from `discovery.py`) includes these fields, but they're dropped when converting CSTNode -> NodeDiscoveredEvent. This data loss means precise byte-offset LSP ranges are impossible. The concept doc doesn't explicitly require byte offsets, but `lsprotocol` supports character-level positioning which would benefit from this data. |
| 23 | Medium | 103 | `AgentMessageEvent.tags` is `list[str]` but frozen dataclasses with mutable default fields are a known footgun. The `field(default_factory=list)` is correct here (each instance gets its own list), and `frozen=True` prevents reassignment, but the list *contents* are still mutable: `event.tags.append("x")` would succeed. This violates the "immutable event" contract. Should be `tuple[str, ...]`. |
| 24 | Low | 168-196 | `RemoraEvent` is a union type alias, not a base class. `isinstance(event, RemoraEvent)` doesn't work in Python. The projection's `apply()` accepts `event: RemoraEvent` as a type annotation but can't use `isinstance` to check if something is "a RemoraEvent". This is fine since the projection uses `isinstance` on specific event types, but the annotation could be misleading. |
| 25 | Info | 14-22 | Re-exported structured-agents events are included in the `RemoraEvent` union. If `structured_agents` adds new event types, they won't automatically be included in the union. This is explicit and correct, but worth noting. |

### 2.5 `src/remora/extensions.py` (89 lines)

**Purpose:** `AgentExtension` base class and `load_extensions()` file loader with mtime-based caching.

**Strengths:**
- Clean two-method interface (`matches()`, `get_extension_data()`).
- mtime-based cache invalidation is a pragmatic choice for development workflow.
- Alphabetical file ordering gives developers explicit control over match priority.

**Issues:**

| # | Severity | Line(s) | Issue |
|---|----------|---------|-------|
| 26 | **High** | 27 | `matches()` only receives `node_type: str` and `name: str`. The concept doc describes extensions matching on things like "functions decorated with `@app.route`" or "classes inheriting from `BaseModel`". These require access to `source_code`, `file_path`, or even the full `CSTNode`. The current 2-parameter API can only match by naming conventions, which is severely limiting. |
| 27 | Medium | 38 | Module-level `_cache` dict is mutable global state. Tests that call `load_extensions()` from different tmp directories can interfere with each other because the cache persists across test cases. The `test_mtime_caching` test works only because it uses a unique `tmp_path`. Any test that happens to reuse a path (e.g., via monkeypatching) would get stale cache results. Should use a class or pass cache as parameter. |
| 28 | Medium | 74-78 | `importlib.util.spec_from_file_location` + `exec_module()` loads arbitrary Python code. There's no sandboxing. An extension file could import anything, modify global state, or crash the process. This is by design (extensions are user code), but there's no error isolation -- a broken extension prevents all subsequent extensions from loading in the same file (the `continue` on line 85 only skips the current file). |
| 29 | Medium | 80-81 | Extension class detection iterates `module.__dict__.values()` and checks `issubclass(obj, AgentExtension)`. If an extension file imports other `AgentExtension` subclasses (e.g., a utility base class), those will also be collected. There's no mechanism to mark a class as "not an extension" short of making it not inherit from `AgentExtension`. |
| 30 | Low | 66 | Cache validity check: `if current_mtimes == cached_mtimes and cached_mtimes`. The `and cached_mtimes` check means empty directories bypass the cache and always return `[]`. This is correct behavior (empty dir = no extensions), but the empty-dict truthiness check is subtle. |

### 2.6 `src/remora/core/__init__.py` (120 lines)

**Purpose:** Re-exports for the `remora.core` package.

**Issues:**

| # | Severity | Line(s) | Issue |
|---|----------|---------|-------|
| 31 | Medium | 3, 57-58 | Old types (`AgentState`, `SwarmState`, `AgentMetadata`) are still exported alongside new types (`AgentNode`, `NodeProjection`). During Phase 2 migration this is necessary, but there should be deprecation warnings or at minimum a comment marking which exports are legacy. |
| 32 | Low | 49-54 | Old modules (`reconciler`, `swarm_state`, `agent_state`) are still imported at module level. If any of these have import-time side effects, they affect every `from remora.core import AgentNode`. |

### 2.7 Test Files

#### `tests/unit/test_agent_node.py` (225 lines)

**Strengths:** Good coverage of creation, serialization round-trip, prompt generation, and all LSP methods.

**Issues:**

| # | Severity | Issue |
|---|----------|-------|
| 33 | Medium | No negative/error path tests. What happens when `from_row()` gets malformed JSON in `extra_tools`? What if `to_row()` is called with a `ToolSchema` whose `parameters` is not JSON-serializable? |
| 34 | Medium | No test for `ToolSchema.to_llm_tool()` -- the LLM tool conversion method is completely untested. |
| 35 | Low | `_make_node()` helper doesn't match the actual CSTNode -> AgentNode conversion path. Test nodes are manually constructed, so there's no validation that real discovery output produces valid `AgentNode` instances. |
| 36 | Low | `test_from_row_round_trip` creates an in-memory SQLite DB to simulate the round-trip, but the table schema is inferred from `to_row()` keys rather than using the actual `nodes` table DDL. If the DDL diverges from `to_row()` output, the test won't catch it. |

#### `tests/unit/test_projections.py` (162 lines)

**Strengths:** Tests all five event handlers (discover, remove, start, complete, error) plus extension matching and hydration.

**Issues:**

| # | Severity | Issue |
|---|----------|-------|
| 37 | Medium | Extension matching test only tests `extension_name` and `custom_system_prompt`. No test where an extension returns `extra_tools`, `extra_subscriptions`, or `mounted_workspaces`. The JSON serialization of these complex fields in the projection path is untested. |
| 38 | Medium | Upsert test doesn't verify that status is preserved on re-discovery. It checks `source_hash` changed but doesn't first change status to `"running"` and then verify it survives the upsert. (The integration test does cover this, but the unit test doesn't.) |
| 39 | Low | Tests access `store._conn` directly (private attribute). This couples tests to internal implementation. |

#### `tests/unit/test_extensions.py` (109 lines)

**Strengths:** Tests base class, loading, caching, and ordering.

**Issues:**

| # | Severity | Issue |
|---|----------|-------|
| 40 | Medium | No test for error handling (malformed Python file, extension that raises in `matches()`). |
| 41 | Low | `test_mtime_caching` doesn't assert cache identity (`exts1 is exts2`), only length equality. Can't confirm the cache is actually returning the cached list vs. reloading. |

#### `tests/unit/test_event_store_projection.py` (104 lines)

Good coverage. No significant issues.

#### `tests/unit/test_event_store_nodes_query.py` (72 lines)

Good coverage. No significant issues.

#### `tests/unit/test_node_events.py` (51 lines)

Minimal but adequate for Phase 1. Could use more edge cases.

#### `tests/unit/test_nodes_table.py` (70 lines)

Good schema verification. No significant issues.

#### `tests/integration/test_agent_node_pipeline.py` (144 lines)

**Strengths:** Tests the complete lifecycle (discover -> start -> complete -> prompt -> LSP -> remove) and re-discovery status preservation.

**Issues:**

| # | Severity | Issue |
|---|----------|-------|
| 42 | Medium | Events are manually constructed. There's no test that `discover()` output (CSTNode) can be correctly transformed into `NodeDiscoveredEvent`. The CSTNode -> Event conversion doesn't exist yet (it's a Phase 2 task in the reconciler rewrite), but the integration test should note this gap. |
| 43 | Low | The integration test lives in `tests/integration/` but doesn't integrate with anything external (no file system, no Neovim, no LLM). It's really a "pipeline unit test" -- testing that multiple internal components work together correctly. True integration tests would exercise the LSP server or the full reactive loop. |

---

## 3. Categorized Issues

### 3.1 Bugs / Correctness (fix before Phase 2)

| # | File | Issue | Priority |
|---|------|-------|----------|
| B1 | `projections.py:76` | `json.dumps` with `lambda o: o.__dict__` fails for slotted classes and produces wrong output for Pydantic models. | **P1** |
| B2 | `projections.py` / `event_store.py` | Double-commit: projection commits inside EventStore's already-committed transaction. Event and projection can be inconsistent on projection failure. | **P1** |
| B3 | `agent_node.py:95-97` | `to_row()` uses `__dict__` for ToolSchema/SubscriptionPattern. Should use `dataclasses.asdict()` for dataclasses. | **P2** |
| B4 | `events.py:103` | `AgentMessageEvent.tags` is `list[str]` (mutable) inside a frozen dataclass. Contents can be mutated, violating immutability contract. | **P2** |
| B5 | `agent_node.py:9` | Dead import: `hashlib` is unused. | **P3** |

### 3.2 Design Concerns (address during Phase 2)

| # | File | Issue | Priority |
|---|------|-------|----------|
| D1 | `extensions.py:27` | `matches()` API too narrow (only `node_type` + `name`). Cannot match on source code, decorators, or file path. | **P1** |
| D2 | `projections.py:14` | `last_trigger_event` column exists in schema but is never written. Dead schema. | **P2** |
| D3 | `events.py:139-153` | `NodeDiscoveredEvent` missing `start_byte`/`end_byte` from CSTNode. Data loss in discovery pipeline. | **P2** |
| D4 | `projections.py:31-42` | `isinstance()` dispatch requires manual update for every new node-affecting event type. | **P2** |
| D5 | `extensions.py:38` | Module-level `_cache` dict is global mutable state. Problematic for testing. | **P2** |
| D6 | `event_store.py:18` | EventStore without projection silently returns empty `get_node()`/`list_nodes()`. No warning. | **P3** |
| D7 | `agent_node.py:129` | System prompt hardcodes `"Python"`. Needs language parameterization. | **P3** |
| D8 | `__init__.py` | Old types (`AgentState`, `SwarmState`, `AgentMetadata`) still exported without deprecation notice. | **P3** |

### 3.3 Testing Gaps (address immediately)

| # | Gap | Priority |
|---|-----|----------|
| T1 | No test for `ToolSchema.to_llm_tool()`. | **P1** |
| T2 | No test for extension returning `extra_tools`/`extra_subscriptions` through projection. | **P1** |
| T3 | No error path tests for `from_row()` with malformed JSON. | **P2** |
| T4 | No concurrency test for multiple `append()` calls racing on same node_id. | **P2** |
| T5 | No test for CSTNode -> NodeDiscoveredEvent conversion (doesn't exist yet, but gap is tracked). | **P2** |
| T6 | No test for extension `matches()` raising an exception. | **P2** |
| T7 | Shared `conftest.py` fixtures still use old `AgentState`/`SwarmState` -- no fixtures for new `AgentNode`/`NodeProjection` pattern. | **P3** |

### 3.4 Performance

| # | Issue | Priority |
|---|-------|----------|
| P1 | Projection commits per-event inside an already-committed transaction. Extra fsync per event. | **P1** (same as B2) |
| P2 | `list_nodes()` fetches all columns including `source_code` (which can be large). No projection/column selection. For LSP operations that only need node_id + status + line range, this is wasteful. | **P3** |
| P3 | Extension matching in projection iterates all extensions for every `NodeDiscoveredEvent`. With many extensions, this is O(n) per discovery event. Fine for now, but consider indexing by `node_type` if extension count grows. | **P3** |

---

## 4. Alignment with EventBased Concept

### What's Aligned

1. **"EventLog is the single source of truth"** -- Events are appended to the `events` table, and the `nodes` table is a derived materialized view. The projection pattern is correct.

2. **"AgentNode serves three roles"** -- The unified model correctly implements DB row, LLM prompt, and LSP protocol data in a single object.

3. **"No subclasses. Specialization is data."** -- Extensions inject data fields rather than creating `AgentNode` subclasses. Correct.

4. **"Discovery -> Event -> Projection"** -- The pipeline architecture matches the concept doc's description of CSTNode -> NodeDiscoveredEvent -> NodeProjection -> nodes table.

5. **"Upsert preserves runtime state"** -- The `ON CONFLICT` clause correctly updates source data while preserving `status`, `last_trigger_event`, and `last_completed_at`.

### What's Missing or Divergent

1. **`edges` table** -- The concept doc describes an `edges` table for graph context (caller/callee relationships). `AgentNode` has `caller_ids`/`callee_ids` fields but they're always `[]`. No edges projection exists. (Expected -- Phase 2+.)

2. **Extension matching depth** -- The concept doc describes extensions matching on decorators, inheritance, and file context. The current `matches(node_type, name)` API can only do name-based matching. This is a significant gap.

3. **Cascade safety** -- The concept doc describes correlation IDs, depth limits, cooldowns, and concurrency semaphores. None of these are implemented in Phase 1. (Expected -- these are reactive loop features, not AgentNode features.)

4. **`last_trigger_event`** -- The concept doc implies agents track what triggered them. The field exists but is never populated.

5. **Byte offsets** -- CSTNode includes `start_byte`/`end_byte` which are dropped in the event pipeline. The concept doc doesn't explicitly require them, but LSP character-level precision would benefit.

6. **`pending_approval` status** -- Listed in the status icon map and the concept doc's human-in-the-loop flow, but no projection method transitions to this status. (Expected -- Phase 2.)

### Assessment

Phase 1 is well-aligned with the concept doc for its stated scope. The two areas of concern are: (1) the transaction boundary issue between event append and projection (which violates the "EventLog is the source of truth" principle if they can become inconsistent), and (2) the narrow extension matching API which will need a breaking change to support the concept doc's richer matching patterns.

---

## 5. Prioritized Improvement Recommendations

### P1 -- Fix Before Proceeding to Phase 2

1. **Fix the transaction boundary (B2/P1).** Remove `conn.commit()` from all `NodeProjection` methods. Have `EventStore.append()` manage a single transaction that covers both the event insert and the projection update. If the projection fails, roll back the event insert too.

   ```python
   # event_store.py append() -- proposed
   async with self._lock:
       await asyncio.to_thread(self._conn.execute, "BEGIN")
       try:
           cursor = await asyncio.to_thread(self._conn.execute, INSERT_SQL, params)
           if self._projection is not None:
               await asyncio.to_thread(self._projection.apply, self._conn, event)
           await asyncio.to_thread(self._conn.commit)
       except Exception:
           await asyncio.to_thread(self._conn.rollback)
           raise
   ```

2. **Fix the `__dict__` serialization (B1/B3).** Replace `o.__dict__` with `dataclasses.asdict(o)` for dataclasses and `.model_dump()` for Pydantic models. In `to_row()`, use `dataclasses.asdict(t)` for `ToolSchema` and `dataclasses.asdict(s)` for `SubscriptionPattern`.

3. **Add test for `ToolSchema.to_llm_tool()` (T1).** This is a critical conversion for the LLM integration path.

4. **Add test for extension with complex fields through projection (T2).** Create an extension that returns `extra_tools` and `extra_subscriptions`, then verify the full round-trip through projection -> from_row().

### P2 -- Address During Phase 2 Tasks

5. **Widen the `AgentExtension.matches()` API (D1).** Add `file_path`, `source_code`, and optionally `parent_id` parameters. This is a breaking change to all existing extensions, so do it before the ecosystem grows.

   ```python
   @staticmethod
   def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
   ```

6. **Either populate or remove `last_trigger_event` (D2).** If it's planned for Phase 2's reactive loop, add a TODO comment. If not, remove the field and column.

7. **Add `start_byte`/`end_byte` to `NodeDiscoveredEvent` (D3).** These are available from CSTNode and cheap to carry.

8. **Fix `AgentMessageEvent.tags` mutability (B4).** Change `list[str]` to `tuple[str, ...]` with `default_factory=tuple`.

9. **Add error path tests (T3).** Test `from_row()` with `extra_tools = "not-json"`, `extra_tools = "[{\"bad\": true}]"`, etc.

10. **Add concurrency tests (T4).** Use `asyncio.gather()` to fire multiple `append()` calls for the same `node_id` and verify the final state is consistent.

### P3 -- Nice to Have / Cleanup

11. **Remove dead `hashlib` import (B5).**

12. **Parameterize language in system prompt (D7).** Add a `language: str = "Python"` field to `AgentNode` or derive it from `file_path`.

13. **Add deprecation comments/warnings for old exports (D8).**

14. **Refactor extension cache to avoid module-level mutable state (D5).** Consider making `load_extensions` a method on a class that owns its cache, or accept a cache dict parameter.

15. **Add `conftest.py` fixtures for new types (T7).** Create `make_agent_node()`, `make_discovered_event()`, and `store_with_projection` fixtures for reuse across test files.

16. **Consider column selection in `list_nodes()` (P2).** Add an optional `columns` parameter for lightweight queries.

---

*End of Phase 1 Code Review*
