# Remora Full Codebase Architectural Review

This report presents findings from a comprehensive code review of the Remora codebase. The review assessed the codebase as a whole against the principles established in `docs/EventBased_Concept.md`, optimizing for elegance, cleanliness, composability, and architecture without concern for backwards compatibility.

## Executive Summary
The Remora codebase successfully implements a robust Event-Driven Architecture. The core triad of `EventStore`, `EventBus`, and `SubscriptionRegistry` forms a powerful Reactive loop. The centralized execution pipeline (`execute_agent_turn`) effectively unifies headless and LSP execution paths.

However, several architectural leaks and instances of tight coupling were identified, where domain boundaries are crossed or internal implementations are exposed. Addressing these issues will significantly improve the codebase's composability and elegance.

---

## Findings & Opportunities for Improvement

### 1. Core Event Infrastructure (`event_store.py`, `projections.py`, `event_bus.py`)

**Overall Status:** Strong. The `EventBus` provides a clean Observer pattern, and `EventStore` handles concurrent SQLite persistence gracefully with WAL mode.

**Opportunity A: Remove LSP Leakage from Core EventStore**
- **Issue:** `EventStore.__init__` creates LSP-specific tables: `proposals`, `command_queue`, `activation_chain`. The `EventStore` is in the `core` module and should be entirely generic. LSP-specific operational state belongs strictly in `remora.lsp.db.RemoraDB`.
- **Recommendation:** Migrate the schema definitions for `proposals`, `command_queue`, and `activation_chain` entirely out of `event_store.py` and into `lsp/db.py`. Ensure that the `EventStore` only manages `events`, `event_streams`, `nodes`, and `subscriptions`.

**Opportunity B: Optimize Node Projection Queries**
- **Issue:** The `nodes` projection currently performs full-text search by iterating over all nodes in memory and using Python `re` regex over the `source_code`.
- **Recommendation:** Since nodes are already parsed via TreeSitter, structural queries could leverage TreeSitter cursors instead of regex. Alternatively, `embeddy` could be utilized for semantic search or SQLite FTS5 could be enabled for the `nodes` table for scalable full-text search.

### 2. Core Execution (`execution.py`, `swarm_executor.py`, `state_manager.py`)

**Overall Status:** Very Strong. `execute_agent_turn` masterfully isolates the complex prompt building, workspace data provision (`CairnDataProvider`), tool binding, and kernel execution. `state_manager.py` offers a beautifully typed, clean wrapper over Cairn's key-value store.

### 3. LSP Runner & Graph (`runner.py`, `db.py`, `graph.py`)

**Overall Status:** Mixed. While functional, the LSP layer exhibits some architectural shortcuts that compromise composability.

**Opportunity C: Fix `LazyGraph` DB Coupling (Bypass of Abstraction)**
- **Issue:** `LazyGraph` (`src/remora/lsp/graph.py`) takes an `event_store_db_path` and creates a *new*, direct SQLite connection to the EventStore database just to perform `SELECT * FROM nodes`. This bypasses the `EventStore` API entirely and tightly couples the LSP graph to the internal physical storage implementation of the core projections.
- **Recommendation:** Refactor `LazyGraph` to accept an `EventStore` instance instead of a file path. It should use `await event_store.get_node()` or `list_nodes()` instead of executing raw SQL against the underlying node projection table.

**Opportunity D: Decouple `AgentRunner` from LSP-Specific Formatting**
- **Issue:** `src/remora/lsp/runner.py` is quite large (~740 lines) as it mixes generic execution queuing (trigger coordination, cooldowns, cascade limits) with intensive LSP-specific UI formatting (emitting `LspAgentEvent`, refreshing code lenses, creating diagnostics).
- **Recommendation:** Separate the concern of generic Swarm Orchestration (queuing, debouncing, limits) from LSP UI updating. `AgentRunner` could simply yield standard complete/error events, and a separate LSP-focused class could map those domain events into UI/LSP operations (like code lenses and diagnostics).

### 4. Service & Companion Integrations (`api.py`, `chat_service.py`, `companion/`)

**Overall Status:** Excellent. The companion app has a stellar pipeline design (`dispatcher.py`), elegantly chaining events (`CursorFocusEvent` -> `CompanionContextExtracted` -> `CompanionSearchCompleted`) through discrete handlers to compose the sidebar. `IndexingService` cleanly encapsulates `embeddy`. `chat_service.py` effectively uses Server-Sent Events (SSE) to stream events without coupling to the HTTP framework.

---

## Next Steps

To realize the "ideal, elegant" architecture envisioned in `EventBased_Concept.md`, the following actions are recommended as follow-up tasks:

1. **(Core/LSP):** Migrate `proposals`, `command_queue`, and `activation_chain` schemas from `core/event_store.py` to `lsp/db.py`.
2. **(LSP):** Refactor `lsp/graph.py` to remove direct SQLite connection to EventStore and use `EventStore.get_node()` APIs instead.
3. *(Optional)* **(Core):** Optimize `projections.py` graph querying logic to avoid full-memory regex scans.
4. *(Optional)* **(LSP):** Split `lsp/runner.py` to isolate generic swarm coordination from code-lens/diagnostic LSP mutations.
