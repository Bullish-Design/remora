# Phase 2 Implementation Plan: Architectural Concerns

## Goal Description
Address critical architectural tech debt identified in Code Review 0005. The primary goals are to eliminate god-objects ([EventStore](file:///home/andrew/Documents/Projects/remora/src/remora/core/store/event_store.py#36-760) and `AgentRunner`) and unify parallel event hierarchies. 

## Proposed Changes

### 1. Proxy Removals (Completed)
Deleted the 20 lazy-import proxies in `src/remora/core/` (e.g. `discovery.py`, `agent_node.py`). We verified that all existing code already imports from the canonical locations (e.g., `remora.core.code.discovery`).

---

### 2. EventStore Separation of Concerns (Completed)
Extract Node read-model logic from the write-ahead log.
#### [MODIFY] src/remora/core/store/event_store.py
- Remove Node CRUD methods (`get_node`, `list_nodes`, `set_node_status`, `remove_nodes_for_file`, `get_node_at_position`).
- Remove `NodeProjection` dependency from `EventStore` initialization.
#### [NEW] src/remora/core/store/node_store.py
- Create a `NodeStore` class dedicated to querying the `nodes` SQLite table.
- Move the extracted CRUD methods here.
- It will take a SQLite connection or pool rather than wrapping `EventStore`.
#### [MODIFY] src/remora/lsp/__main__.py & src/remora/lsp/server.py
- Initialize `NodeStore` alongside `EventStore`.
- Update `RemoraLanguageServer` and `AgentRunner` to use `NodeStore` for node queries.

---

### 3. AgentRunner Refactoring (Completed)
Reduce `AgentRunner` from an 800+ line god-object.
#### [NEW] src/remora/runner/event_emitter.py
- Extract the 7 `_emit_*` helper methods (which duplicate server methods) from `AgentRunner` into a dedicated `EventEmitter` or `LspNotifier` class.
#### [MODIFY] src/remora/runner/agent_runner.py
- Remove the boilerplate `emit_*` methods.
- Delegate event emission to the new class.
- *Note: Further splitting (e.g. `BackgroundScanner`) was requested in the review but part of it was already done in `__main__.py`. We will focus on the runner itself.*

---

### 4. Unify Event Models (Completed)
Merge `CoreEvent` and `LspAgentEvent`.
#### [DELETE] src/remora/runner/events.py
- Delete this file entirely. It contains the duplicate `LspAgentEvent` hierarchy.
#### [MODIFY] src/remora/core/events/events.py
- Ensure `CoreEvent` encapsulates all necessary fields (like `correlation_id` if needed, though they already have deterministic IDs and timestamps).
#### [MODIFY] src/remora/runner/agent_runner.py & service handlers
- Update all references from `LspAgentEvent` to `CoreEvent` subtypes.

## Verification Plan

### Automated Tests
```bash
devenv shell -- pytest tests/unit/test_event_store.py -v
devenv shell -- pytest tests/unit/test_unified_runner.py -v
devenv shell -- pytest tests/ -m "not benchmark" -q
```
*Note: Due to known pre-existing issues in `test_concurrent_safety.py`, we will focus on unit test regressions first.*
