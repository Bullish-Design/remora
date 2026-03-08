# Context

## Status (2026-03-07)

Deep study of remora library complete. All guide rewrites in progress. Read CRITICAL_RULES.md.

## Key Architecture Discovered

### Two-Database Architecture

The production LSP server uses TWO separate SQLite databases:

1. **EventStore** at `.remora/events/events.db`:
   - Tables: `events` (id PK INTEGER, graph_id, event_type, payload, timestamp, from_agent, to_agent, correlation_id, tags), `nodes` (node_id PK TEXT, node_type, name, full_name, file_path, start_line, end_line, source_code, source_hash, parent_id, status)
   - Created/owned by `EventStore` class

2. **RemoraDB** at `.remora/indexer.db` (standalone mode):
   - Tables: `edges`, `activation_chain`, `proposals`, `cursor_focus`, `command_queue`
   - `RemoraLanguageServer.__init__` creates `RemoraDB()` with NO args → standalone mode → `.remora/indexer.db`

`state.py` (Web UI) opens `.remora/indexer.db` but queries `nodes` and `events` tables which ONLY exist in `.remora/events/events.db`. This causes sqlite3.OperationalError ("no such table: nodes", "no such table: events").

### EventBus / EventStore Flow

`EventStore.append()` (line 239-240):
```python
if self._event_bus is not None:
    await self._event_bus.emit(event)
```

So: cursor move → `do_cursor_update()` → `event_store.append("cursor", CursorFocusEvent)` → `event_bus.emit(CursorFocusEvent)` → ALL registered subscribers are called.

### Production Companion (src/remora/companion/)

The production companion at `src/remora/companion/` is a COMPLETE, CORRECT implementation:
- Events extend `_FrozenEvent` (Pydantic, frozen) ✅
- `start_companion(event_store, event_bus, cairn_service, config)` wires everything ✅
- 8 handlers: ContextExtractor, EditSummarizer, IndexingHandler, SearchHandler, TaskInferrer, ClaimChecker, ConnectionFinder, SidebarComposer
- `CompanionDispatcher` subscribes handlers to EventBus (not polling!)
- Uses `CursorFocusEvent` from `remora.core.events.interaction_events` ✅

**Critical integration gap**: `lsp/__main__.py` creates `EventBus` and `EventStore` but NEVER calls `start_companion()`. The entire companion pipeline is dead code — nothing subscribes to CursorFocusEvent via EventBus.

### Old Demo Companion (remora_demo/companion/)

This is an OLD, OBSOLETE implementation that must be replaced:
- Uses old `CompanionRuntime` with custom dataclass events (not `_FrozenEvent`)
- Has its own standalone LSP server (`companion-lsp`) — wrong architecture
- Neovim companion plugin connects to WRONG server (companion-lsp instead of remora-lsp)
- `$/companion/cursorMoved` is redundant — cursor already tracked via `$/remora/cursorMoved`
- `$/companion/getSidebar` uses spec-violating `$/...` request pattern

### panel.lua Bugs (Confirmed)

1. **Bug 1 (High)**: AgentMessageEvent extends _FrozenEvent (not AgentEvent), so model_dump() has NO `event_type`, `agent_id`, or `payload`. on_event() checks `event.agent_id` → nil → DROPS the event.
   - Fix: wrap in AgentEvent envelope in `server.emit_agent_message_event()`

2. **Bug 2 (Medium)**: Historical AgentMessageEvent direction rendered as "unknown" because panel reads `ev.payload.from_agent`/`ev.payload.to_agent` but row_to_event_dict() puts these at TOP LEVEL (`ev.from_agent`, `ev.to_agent`).
   - Fix: use `ev.from_agent or ev.payload.from_agent`

3. **Bug 3 (Low)**: Duplicate user message after panel refresh. Local HumanChatEvent created with id=nil, dedup logic uses `server_ids[ev.id or ev.event_id]` — nil keys are not stored → duplicate shown.

### state.py Bugs (Confirmed)

Complete bug list:
1. **Wrong DB path**: Opens `.remora/indexer.db` but `nodes`/`events` are in `.remora/events/events.db`
2. `read_node()`: `WHERE id = ?` → should be `WHERE node_id = ?` (AND correct DB)
3. `read_events_for_agent()`: `SELECT event_id, agent_id` → `SELECT id, from_agent, to_agent`; `WHERE agent_id = ?` → `WHERE from_agent = ? OR to_agent = ?`
4. `read_recent_events()`: same column issues
5. `test_bridge.py`: creates old schema (event_id, agent_id, nodes.id as PK) — tests pass but don't catch production bugs

## What's Next

Rewrite all guides in this order:
1. GUIDE_COMPANION.md — comprehensive rewrite (biggest change)
2. GUIDE_NEOVIM.md — verify and tighten
3. GUIDE_WEB_UI.md — add two-DB architecture + column fixes
4. Update PROGRESS.md

## Key Files

- `src/remora/companion/startup.py` — `start_companion()` entry point
- `src/remora/companion/dispatcher.py` — CompanionDispatcher wiring
- `src/remora/lsp/__main__.py` — where `start_companion()` must be called
- `src/remora/lsp/server_setup.py` — where `companion.getSidebar` command handler goes
- `src/remora/lsp/server.py` — `emit_agent_message_event()` fix location (Bug 1)
- `remora_demo/web/graph/state.py` — SQL schema bugs (wrong DB + column names)
- `tests/test_bridge.py` — stale test schema
- `src/remora/lsp/nvim/lua/remora/panel.lua` — Bug 1/2/3 locations

## Confirmed Correct (No Changes)

- `ev.payload.result_summary` in panel.lua ✅ (agent_runner adds it before emitting)
- Production companion event imports (`_FrozenEvent`, bounded modules) ✅
- `CursorHold` autocmd in init.lua sends `$/remora/cursorMoved` ✅
- `EventStore.append()` → `EventBus.emit()` → companion subscriptions ✅ (IF wired)
- `tach check` passes, 0 cycles ✅
