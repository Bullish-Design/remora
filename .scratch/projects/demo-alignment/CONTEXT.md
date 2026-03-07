# Context

## What Just Happened (2026-03-07)

Completed Phase 1 analysis and Phase 2 guide writing. The project originated from two completed architecture refactors (architecture_refactor + architecture-mental-model-simplification) that changed the event system, moved RewriteProposal to runner.models, and fixed all import cycles.

The user corrected the initial approach: these areas are **actual functional implementations** (not demo harnesses). Evaluation must treat them as real apps integrating with the remora library.

## Key Bugs Found

### panel.lua (Neovim integration) — CRITICAL
1. **Bug 1 (High)**: Live `AgentMessageEvent` events silently dropped. `on_event()` checks `event.agent_id` and `event.payload.to_agent`, but `AgentMessageEvent.model_dump()` has NEITHER (it extends `_FrozenEvent` not `AgentEvent`, so no `event_type`, `agent_id`, or `payload` wrapper). Fix: wrap live notification in `AgentEvent` envelope in `server.emit_agent_message_event()`.

2. **Bug 2 (Medium)**: Historical `AgentMessageEvent` direction always "unknown". `panel.lua` reads `ev.payload.from_agent`/`ev.payload.to_agent` but these are at top level (`ev.from_agent`/`ev.to_agent`). Fix: use `ev.from_agent or ev.payload.from_agent`.

3. **Bug 3 (Low)**: Duplicate user message after panel refresh. Locally-created HumanChatEvent (id=nil) is never deduplicated by the merge logic because `server_ids[nil]` is always falsy. Fix: assign local placeholder IDs.

### state.py (Web UI) — CRITICAL
4. **Schema bugs**: Queries use `event_id` (→ `id`), `agent_id` (→ `from_agent`/`to_agent`), `nodes.id` (→ `nodes.node_id`). These cause `sqlite3.OperationalError` at runtime.
5. **Tests are stale**: `tests/test_bridge.py` creates old schema — tests pass but don't verify against production.

### chat_service.py (Agent Chat)
6. Module-level `state = ChatServiceState()` and `app = create_app()` singletons. `create_app()` uses `globals()` fallback. Handler closures capture module-level state, not injected state.

## What's Next

Phase 3: Implement the fixes. Start with the critical ones first:
1. Fix `state.py` SQL queries (swap column names + use aliases)
2. Fix `tests/test_bridge.py` test schema
3. Then fix `panel.lua` Bug 1 (AgentMessageEvent routing in server.py)
4. Then panel.lua Bug 2 (direction display)
5. Then chat_service.py singleton

## Key Files

- `src/remora/lsp/nvim/lua/remora/panel.lua` — primary Neovim panel
- `src/remora/lsp/server.py` — `emit_agent_message_event()` needs wrapping fix
- `remora_demo/web/graph/state.py` — SQL schema bugs
- `tests/test_bridge.py` — stale test schema
- `src/remora/service/chat_service.py` — singleton anti-pattern

## Wire Protocol Summary

**Live events** (`$/remora/event`):
- `AgentEvent` subclasses: `{event_type, agent_id, payload={...}, summary, timestamp}`
- `AgentMessageEvent` raw (BUG): `{from_agent, to_agent, content, ...}` — no event_type!

**Historical events** (`row_to_event_dict()`):
- Always: `{id, event_type, from_agent, to_agent, payload={non-meta fields}, summary, timestamp}`

## Architecture Invariants

- `AgentEvent.payload` IS a dict field (unlike other _FrozenEvent subclasses)
- `_emit_tool_event` adds `result_summary` to payload before emitting → `ev.payload.result_summary` in panel.lua is CORRECT
- `meta_keys` in `row_to_event_dict()` excludes: `event_id, event_type, timestamp, correlation_id, agent_id, summary, payload, from_agent, to_agent, tags, graph_id, created_at, id`
- `tach check` passes, 0 cycles, all tests pass (except 3 known pre-existing failures)
