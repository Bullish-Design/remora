# Architecture Overview & Reassessment

> **Date:** 2026-03-03
> **Context:** Post gap-refactoring (all 5 workstreams complete, zero regressions)
> **Reference:** `docs/EventBased_Concept.md` (authoritative design document)

---

## Part 1: Current Architecture Overview

### What Remora Is

Remora is a reactive agent swarm system embedded in your editor via LSP. Every discoverable code element (function, class, method, file, markdown section, TOML table) is paired with an LLM-powered agent that can react to events, propose code rewrites, and communicate with other agents.

### Data Flow (Post-Refactoring)

```
Source Files → tree-sitter discovery → CSTNode objects
    → NodeDiscoveredEvent → EventStore.append()
    → NodeProjection writes/upserts → `nodes` table
    → AgentNode.from_row() hydrates the read model

Editor Actions (save, cursor, didChange) → LSP handlers
    → emit domain events (FileSavedEvent, ContentChangedEvent, CursorFocusEvent)
    → EventStore.append() → subscription matching → trigger queue
    → AgentRunner.trigger() → AgentRunner.execute_turn()
    → execute_agent_turn() → kernel → kernel events → EventStore
    → may trigger more agents (reactive loop)
```

### Key Abstractions

**Core Layer** (`src/remora/core/`):

| Component | File | Role |
|-----------|------|------|
| `CSTNode` | `discovery.py` | Frozen Pydantic model from tree-sitter. Raw discovery output. |
| `AgentNode` | `agent_node.py` | Unified read model: DB row, LLM prompt, LSP protocol. Single class, no subclasses. |
| `EventStore` | `event_store.py` | SQLite append-only event log + `nodes` table + subscription matching + projection. The single source of truth. |
| `EventBus` | `event_bus.py` | In-memory pub/sub. Now downstream of EventStore (forwarding only). Used for SSE/UI streaming. |
| `SubscriptionRegistry` | `subscriptions.py` | SQLite-backed pattern matching. 5-dimension `SubscriptionPattern`. In-memory cache indexed by event_type. |
| `NodeProjection` | `projections.py` | Synchronous projection: `NodeDiscoveredEvent` → nodes table upsert, agent lifecycle events → status updates. Runs in same SQLite transaction as event INSERT. |
| `execute_agent_turn()` | `execution.py` | THE ONE execution path. Bundle resolution, workspace, tools, kernel, observer — all in one function. Both LSP and CLI delegate here. |
| `reconcile_on_startup()` | `reconciler.py` | Startup diff: discover → compare with nodes table → emit NodeDiscovered/NodeRemoved events → register default subscriptions. |
| Events | `events.py` | All 13 Remora event types + 7 kernel re-exports + `RemoraEvent` union. 4 categories: agent lifecycle, human-in-the-loop, reactive swarm, node lifecycle. |

**LSP Layer** (`src/remora/lsp/`):

| Component | File | Role |
|-----------|------|------|
| `RemoraLanguageServer` | `server.py` | pygls server. Holds EventStore, DB, runner. Debounce infrastructure for reparse/cursor. |
| `AgentRunner` | `runner.py` | Trigger queue consumer. Cascade safety (depth, cooldown, semaphore). Delegates execution to `execute_agent_turn()`. |
| `RemoraDB` | `db.py` | LSP operational tables (proposals, activation_chain, cursor_focus, command_queue). Shares SQLite with EventStore. |
| `ASTWatcher` | `watcher.py` | File watcher that delegates to `parse_content()` from core discovery. |
| Handlers | `handlers/` | LSP protocol handlers: documents (didOpen/didSave/didChange), hover, lens, actions, commands, capabilities. |

**Extension System** (`extensions.py`):

Extensions are `.yaml` configs in `.remora/models/` that match node patterns and inject specialization data (custom_system_prompt, extra_tools, mounted_workspaces). Matching runs twice: at projection time (when NodeDiscoveredEvent writes the nodes table) and at execution time (`apply_extensions()` in runner).

### How the Pieces Fit Together

1. **Startup**: `reconcile_on_startup()` scans the project, diffs against the nodes table, emits `NodeDiscoveredEvent`/`NodeRemovedEvent`, registers default subscriptions.

2. **Steady-state**: Editor actions flow through LSP handlers → domain events → EventStore → subscription matching → triggers → AgentRunner → `execute_agent_turn()` → kernel → more events → possibly more triggers.

3. **Execution pipeline** (`execute_agent_turn()`): Resolves bundle → loads manifest → sets up Cairn workspace → builds `AgentContext` with callbacks → loads files → builds prompt → discovers Grail tools → creates kernel with `_CompositeObserver` that writes kernel events back to EventStore → runs kernel → returns `ExecutionResult`.

4. **Agent identity**: `CSTNode` → `NodeDiscoveredEvent` → `NodeProjection` → nodes table row → `AgentNode.from_row()`. The `AgentNode` model unifies DB schema, LLM prompt (`to_system_prompt()`), and LSP protocol (`to_code_lens()`, `to_hover()`, `to_code_actions()`, `to_document_symbol()`).

---

## Part 2: Reassessment Against EventBased_Concept.md

### §1.1 The EventLog — Single Source of Truth

**Concept**: EventLog is a single SQLite append-only `events` table. It replaces `EventBus`, `EventStore`, and `SwarmState`.

**Current state**: **Largely aligned.**
- `EventStore` (`event_store.py:27-748`) implements the append-only `events` table with monotonic IDs, timestamps, and JSON payloads. It also manages the `nodes` table (replacing SwarmState), `subscriptions`, `edges`, `activation_chain`, `proposals`, `cursor_focus`, and `command_queue` tables.
- `EventBus` (`event_bus.py`) still exists but is now **downstream** of EventStore. `EventStore.append()` calls `self._event_bus.emit(event)` at line 331 as a forwarding mechanism. EventBus is only used for SSE streaming to the UI sidebar — it is no longer the primary routing mechanism.
- `SwarmState` is fully replaced by the `nodes` table + `AgentNode.from_row()`.

**Gap**: The concept says EventLog "replaces" EventBus. EventBus still exists as a component, though its role has been correctly demoted to UI forwarding. This is a **reasonable architectural choice** — the EventBus provides streaming/pub-sub semantics for SSE that EventStore's SQLite-based append doesn't naturally support. No action needed unless you want to remove EventBus and replace it with EventStore's own streaming mechanism (e.g., the existing `get_triggers()` async iterator pattern could be generalized).

**Verdict**: Aligned (minor cosmetic divergence).

---

### §1.2 Events

**Concept**: 4 categories of frozen Pydantic events. Kernel events receive "full event treatment" — subscription matching runs on them.

**Current state**: **Fully aligned.**
- All 4 categories implemented in `events.py`:
  - Agent lifecycle: `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent` (lines 53-79)
  - Human-in-the-loop: `HumanInputRequestEvent`, `HumanInputResponseEvent` (lines 87-103)
  - Reactive swarm: `AgentMessageEvent`, `FileSavedEvent`, `ContentChangedEvent`, `CursorFocusEvent`, `ManualTriggerEvent` (lines 111-151)
  - Node lifecycle: `NodeDiscoveredEvent`, `ScaffoldRequestEvent`, `NodeRemovedEvent` (lines 159-195)
- Kernel events re-exported (lines 22-30) and included in `RemoraEvent` union (lines 224-232).
- `_CompositeObserver` in `execution.py:213-217` appends kernel events to EventStore via `await self.store.append(self.swarm_id, event)`. EventStore.append() runs subscription matching at lines 318-328. So kernel events DO get full subscription treatment.

**Gap**: `AgentCompleteEvent` is missing a `tags` field. The concept (§1.2) shows `AgentCompleteEvent(agent_id="scaffold_1", tags=["scaffold"])` — the `tags` field enables chained agent workflows where downstream agents subscribe to `AgentCompleteEvent` with specific tags (e.g., "scaffold → interface → impl → test"). Current `AgentCompleteEvent` only has `graph_id`, `agent_id`, `result_summary`, `response`, `timestamp`. Adding `tags: tuple[str, ...] = ()` would close this gap.

**Also note**: `CursorFocusEvent` uses `focused_agent_id` instead of `agent_id` because EventStore's `_row_to_dict()` strips `agent_id` from replay payload via `_META_KEYS` (line 481). This is a known design constraint documented in our workstream D implementation.

**Verdict**: Aligned, with one actionable gap (`tags` on `AgentCompleteEvent`).

---

### §1.3 Subscriptions

**Concept**: `SubscriptionPattern` with 5 dimensions, SQLite-backed, default subscriptions (direct message + source file), dynamic subscribe/unsubscribe tools.

**Current state**: **Fully aligned on the registry; partially aligned on tools.**
- `SubscriptionPattern` in `subscriptions.py:27-74`: 5 dimensions (`event_types`, `from_agents`, `to_agent`, `path_glob`, `tags`). Conjunctive matching with disjunctive lists. Exact match.
- SQLite-backed `SubscriptionRegistry` with shared connection mode (lines 88-356). In-memory cache indexed by event_type (lines 313-340).
- Default subscriptions registered in `register_defaults()` (lines 202-219): direct message + ContentChangedEvent for source file. Exact match.
- Dynamic subscribe/unsubscribe: `AgentContext` in `execution.py:303-313` wires `register_subscription` and `unsubscribe_subscription` callbacks. These are available to Grail tools. However, the actual `.pym` Grail tool scripts that expose `subscribe`/`unsubscribe` to the LLM may not exist in bundle directories.

**Gap**: Whether actual Grail `.pym` tool scripts for `subscribe`/`unsubscribe` exist in the default bundles is unclear. The plumbing is there (AgentContext callbacks → SubscriptionRegistry), but the LLM-facing tool definitions may need to be authored.

**Verdict**: Aligned on infrastructure; needs verification that LLM-facing tools exist.

---

### §1.4 Discovery

**Concept**: `CSTNode` frozen dataclass, `discover()` with thread pool, tree-sitter queries for Python/Markdown/TOML, file-level nodes always created, `CSTNode → NodeDiscoveredEvent → EventLog → projection → AgentNode.from_row()` pipeline.

**Current state**: **Fully aligned.**
- `CSTNode` in `discovery.py:46-75`: frozen Pydantic model (not a dataclass, but functionally equivalent) with all specified fields. Custom `__hash__` on `node_id` only (lines 66-74).
- `discover()` uses `ThreadPoolExecutor` for parallel parsing.
- Language support: Python, Markdown, TOML (with extension points for JS/TS/Go/Rust).
- `parse_content()` added in Workstream C for the LSP in-memory parsing path (no disk I/O required).
- Pipeline fully implemented: `discover()` → `CSTNode` → `reconcile_on_startup()` → `NodeDiscoveredEvent` → `EventStore.append()` → `NodeProjection.apply()` → nodes table upsert → `AgentNode.from_row()` hydrates read model.

**Verdict**: Fully aligned.

---

### §1.5 The Reactive Loop (14 Steps)

**Concept**: A 14-step closed loop from event → EventLog → subscription matching → trigger → AgentRunner → bundle → manifest → prompt → tools → kernel → kernel events → EventLog → may trigger more agents.

**Current state**: **Steps 1-14 all implemented, but the LSP path has a trigger flow gap.**

Step-by-step assessment:

| Step | Description | Status |
|------|-------------|--------|
| 1-2 | Event → EventLog | **Done.** `did_save()` emits `ContentChangedEvent`/`FileSavedEvent` via `EventStore.append()`. `_CompositeObserver` writes kernel events. |
| 3 | Subscription matching | **Done.** `EventStore.append()` calls `self._subscriptions.get_matching_agents(event)` at line 319. |
| 4 | Trigger enqueued | **Done.** Matched agents put into `self._trigger_queue` at line 328. |
| 5 | AgentRunner picks up trigger | **Partially.** This is where the gap is. |
| 6 | Load AgentNode | **Done.** `execute_turn()` calls `event_store.get_node(agent_id)` at line 353. |
| 7-8 | Bundle resolution + manifest | **Done.** `execute_agent_turn()` calls `_resolve_bundle_path()` + `load_manifest()` at lines 280-282. |
| 9 | Build prompt | **Done.** Split across `AgentNode.to_system_prompt()` (system message) + `_build_prompt()` (user message with trigger, history, context). |
| 10 | Discover tools | **Done.** Grail tools + extra_tools (LSP-specific) at lines 389-405. |
| 11 | Kernel runs | **Done.** `kernel.run()` at line 458. |
| 12-13 | Kernel events → EventLog → subscription matching | **Done.** `_CompositeObserver.emit()` → `EventStore.append()` → subscription matching → trigger queue. |
| 14 | AgentComplete → may trigger others | **Done.** `runner.py` emits `AgentCompleteEvent` to EventStore at lines 471-478. |

**The gap (Step 5)**: In the LSP path, `AgentRunner.run_forever()` reads from `self.queue` (its own `asyncio.Queue` at line 164), NOT from `EventStore._trigger_queue`. The `run_from_event_store()` bridge at line 207 exists but is labeled "for CLI / headless mode." In the LSP path:

- `did_save()` emits events to EventStore → subscription matching runs → triggers go into `EventStore._trigger_queue`
- But nobody is consuming `EventStore._trigger_queue` in the LSP path
- Instead, the LSP watcher or handler must manually call `runner.trigger()` for each agent

This means the reactive loop's subscription-based trigger routing **works for kernel events** (because `_CompositeObserver` → EventStore → subscription matching → trigger queue), but those queued triggers are never consumed in LSP mode. The LSP path relies on manual `runner.trigger()` calls from handlers (e.g., `message_node()` at line 551 calls `self.trigger(to_id, correlation_id)`).

**What's needed to close this gap**: Start an `asyncio.create_task(runner.run_from_event_store(event_store))` alongside `run_forever()` in the LSP server startup. Or refactor `run_forever()` to also consume from `EventStore._trigger_queue`. This would make the reactive loop fully closed — subscription-matched triggers would automatically flow to the runner without manual wiring.

**Verdict**: 13 of 14 steps implemented. Step 5 (trigger consumption) has a gap in the LSP path. The infrastructure exists but isn't wired.

---

### §1.6 Cascade Safety

**Concept**: Correlation ID tracking, depth limits, cooldown, concurrency semaphore.

**Current state**: **Fully aligned.**
- Correlation ID tracking: `_correlation_depth` dict in `runner.py:119` tracks `(depth, timestamp)` per `agent_id:correlation_id` key.
- Depth limits: In-memory check at `_check_depth_limit()` (line 181) + DB-backed chain check at `get_activation_chain()` (line 309). Both use `MAX_CHAIN_DEPTH = 10`.
- Cooldown: `_check_cooldown()` (line 187) with `trigger_cooldown_ms` (default 1000ms).
- Concurrency semaphore: `asyncio.Semaphore(max_concurrency)` (line 121), acquired at `execute_turn()` line 348.
- Stale depth cleanup: `_cleanup_stale_depths()` (line 196) with 300s TTL.

**Verdict**: Fully aligned.

---

### §1.7 The AgentNode Model

**Concept**: Single Pydantic BaseModel with three roles (DB schema, LLM prompt, LSP protocol). No subclasses. Specialization via data fields.

**Current state**: **Fully aligned.**
- `AgentNode` in `agent_node.py:67-280`: all fields match the concept exactly.
- Three roles:
  - DB: `to_row()` (line 107), `from_row()` (line 118)
  - LLM: `to_system_prompt()` (line 142) — includes identity, source code, graph context, rules, specialization, workspaces
  - LSP: `to_code_lens()` (line 176), `to_hover()` (line 197), `to_code_actions()` (line 224), `to_document_symbol()` (line 260)
- `ToolSchema` (line 36) with `to_llm_tool()` and `to_code_action()`.
- Extension matching via data: `extension_name`, `custom_system_prompt`, `mounted_workspaces`, `extra_tools`, `extra_subscriptions` — all populated by projection at discovery time and re-applied by `apply_extensions()` at execution time.

**Minor note**: The concept shows `to_system_prompt()` including trigger event details and recent chat history. In the implementation, these are in `_build_prompt()` in `execution.py` (the user message), not in `to_system_prompt()` (the system message). This is a **reasonable divergence** — system prompt = static agent identity, user prompt = dynamic trigger context.

**Verdict**: Fully aligned.

---

### §2-6 Perspectives (User, Developer, Agent, Node, Environment)

These sections describe the UX and conceptual model. They're largely aspirational descriptions of what the system feels like when running. The implementation supports the described mechanics:

- **User perspective**: Code lenses showing agent status, hover cards with recent events, code actions for chat/rewrite/message — all implemented via `AgentNode.to_code_lens()`, `to_hover()`, `to_code_actions()`.
- **Developer perspective**: Extension configs in `.remora/models/`, bundle YAML, Grail `.pym` tools — infrastructure exists.
- **Agent perspective**: System prompt with identity/source/graph/specialization, tools (rewrite_self, message_node, read_node), event-driven triggering — all working.
- **Node perspective**: Discovery → idle → triggered → running → complete/error lifecycle — implemented via `NodeProjection` status transitions.

**Gap**: The concept describes rich scaffold lifecycle (scaffold → interface → impl → test → validate → docs chain). Current implementation detects stubs (`_is_stub()` in projections.py) and sets `status = "scaffold"`, and `ScaffoldRequestEvent` exists in events.py, but the scaffold → interface → impl chain isn't wired as an automated flow. The events and data model are in place; the trigger logic that actually runs the chain isn't.

---

### §7 LSP Integration

**Concept**: LSP server as the primary integration point. textDocument/didOpen, didSave, didChange, hover, codeLens, codeAction, documentSymbol, executeCommand.

**Current state**: **Fully aligned.**
- All LSP handlers implemented in `handlers/` directory.
- `textDocument/didChange` added in Workstream D with 500ms debounced reparse.
- Debounce infrastructure in `server.py`: `schedule_reparse()`, `schedule_cursor_update()`.
- Code lenses refresh on status changes.

---

### §8 Future: Custom CSTNode Types

**Concept**: Describes future support for custom node types (e.g., SQL migrations, protobuf messages) via plugin tree-sitter queries.

**Current state**: The query loading infrastructure exists (`_load_queries()` in discovery.py with language-specific `.scm` files). Adding a new language is straightforward: add `.scm` query files to `queries/{language}/remora_core/` and add the extension mapping. This section is explicitly marked "Future" in the concept doc.

---

## Summary: Gap Matrix

| Area | Alignment | Key Gap | Priority |
|------|-----------|---------|----------|
| §1.1 EventLog as SSOT | **Aligned** | EventBus still exists (but downstream-only) | Low |
| §1.2 Events | **Aligned** | `tags` field missing on `AgentCompleteEvent` | Medium |
| §1.3 Subscriptions | **Aligned** | LLM-facing subscribe/unsubscribe tool scripts may be missing | Medium |
| §1.4 Discovery | **Fully aligned** | — | — |
| §1.5 Reactive Loop | **13/14 steps** | LSP path doesn't consume EventStore trigger queue | **High** |
| §1.6 Cascade Safety | **Fully aligned** | — | — |
| §1.7 AgentNode Model | **Fully aligned** | — | — |
| §2-6 Perspectives | **Mostly aligned** | Scaffold lifecycle chain not wired as automated flow | Medium |
| §7 LSP Integration | **Fully aligned** | — | — |

## Recommended Next Steps (ordered by impact)

1. **Wire EventStore trigger consumption in LSP mode** — Start `run_from_event_store()` as a background task in the LSP server startup so that subscription-matched triggers automatically flow to AgentRunner. This closes the reactive loop completely.

2. **Add `tags: tuple[str, ...] = ()` to `AgentCompleteEvent`** — Small change, enables the chained agent workflow pattern described in the concept.

3. **Author subscribe/unsubscribe Grail tool scripts** — The plumbing exists via AgentContext callbacks; the LLM-facing tool definitions need to be written as `.pym` scripts in the default bundles.

4. **Wire scaffold lifecycle** — Connect `ScaffoldRequestEvent` to a trigger chain that runs the scaffold → implementation flow using the existing event infrastructure.
