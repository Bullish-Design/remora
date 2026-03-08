# Demo Alignment Project

**Created:** 2026-03-07
**Context:** Post-`architecture_refactor` + `architecture-mental-model-simplification` cleanup

## Purpose

After two major architecture refactors completed on 2026-03-07, the functional demo areas contain drift relative to the current production architecture. This project documents all misalignments and provides refactoring guides for each area.

**Note:** These are not "demo harnesses" — they are demonstrations of actual functionality:
- The Neovim integration is a production Lua plugin connecting to the live `remora-lsp` server
- The web graph viewer is a standalone Stario app reading the shared SQLite DB
- The agent chat service is a production HTTP service in `src/remora/service/`
- The companion is a standalone product demo with its own agent pipeline and LSP server

## Files

- `REFACTORING_GUIDE.md` — Overview, layer reference, canonical import paths, priority order
- `GUIDE_WEB_UI.md` — Graph viewer: two-DB architecture + column name fixes (critical runtime bugs)
- `GUIDE_NEOVIM.md` — Lua plugin event wire protocol bugs (AgentMessageEvent routing)
- `GUIDE_COMPANION.md` — Production companion integration (complete replacement of old demo)
- `GUIDE_AGENT_CHAT.md` — Chat service singleton pattern, DI fixes
- `PLAN.md`, `CONTEXT.md`, `PROGRESS.md`, `DECISIONS.md`, `ASSUMPTIONS.md`, `ISSUES.md` — Project management

## Critical Bugs Found

### Critical Priority

1. **Companion pipeline never runs** (`src/remora/lsp/__main__.py`)
   - `start_companion(event_store, event_bus, cairn_service, config)` exists in `src/remora/companion/startup.py` but is **never called**
   - `CompanionDispatcher` is never instantiated → no handlers subscribed to EventBus
   - All cursor moves, content changes, file saves produce events that go unprocessed
   - `remora_demo/companion/lsp/server.py` (old standalone approach) is architecturally wrong — must be deleted
   - Fix: call `start_companion()` in `__main__.py`, add `companion.getSidebar` command, push sidebar updates via EventBus

2. **`state.py` — Wrong database + stale column names** (`remora_demo/web/graph/state.py`)
   - Production has TWO databases: `.remora/events/events.db` (EventStore: events, nodes) and `.remora/indexer.db` (RemoraDB: edges, proposals, cursor_focus)
   - `state.py` opens only `.remora/indexer.db` but queries `nodes` and `events` tables which ONLY exist in `events.db`
   - Causes `sqlite3.OperationalError: no such table: nodes` at runtime
   - Column names also stale: `event_id` → `id`, `agent_id` → `from_agent`/`to_agent`, `nodes WHERE id` → `WHERE node_id`
   - `tests/test_bridge.py` creates old schema → tests pass but don't catch production mismatch

### High Priority

3. **`panel.lua` — Live `AgentMessageEvent` silently dropped** (`src/remora/lsp/nvim/lua/remora/panel.lua`)
   - `AgentMessageEvent` extends `_FrozenEvent` (not `AgentEvent`), so `model_dump()` has no `event_type`, `agent_id`, or `payload` field
   - `on_event()` checks `event.agent_id` and `event.payload.to_agent` — both nil → event dropped
   - Result: **inter-agent messages are invisible to the user during live sessions**
   - Fix: wrap live notification in `AgentEvent` envelope in `server.emit_agent_message_event()`

### Medium Priority

4. **`panel.lua` — `AgentMessageEvent` direction always "unknown"**
   - `ev.payload.from_agent`/`ev.payload.to_agent` are nil in historical format; correct fields are `ev.from_agent`/`ev.to_agent`
   - Fix: use `ev.from_agent or ev.payload.from_agent`

5. **`chat_service.py` — Module-level singleton anti-pattern** (`src/remora/service/chat_service.py`)
   - Module import creates live `ChatServiceState` and `app` objects
   - `create_app()` uses `globals()` fallback — DI is incomplete

### Low Priority

6. **`panel.lua` — Duplicate user message after panel refresh** (local event id=nil not deduplicated)

## Verified Clean (No Changes Needed)

- `ev.payload.result_summary` in panel.lua for `ToolResultEvent` ✅ (runner adds it to payload)
- `remora_demo/neovim/mock_llm.py` tool names: `rewrite_self`, `message_node`, `read_node` ✅
- `remora.service.chat_service` event imports use bounded modules (`kernel_events`) ✅
- `src/remora/companion/` — correct architecture (all events extend `_FrozenEvent`, proper EventBus) ✅
- Both architecture refactors fully complete: tach check passes, 0 cycles, all tests pass ✅
- `$/remora/cursorMoved` cursor tracking → `CursorFocusEvent` → `EventBus.emit()` ✅ (just needs companion wired)
