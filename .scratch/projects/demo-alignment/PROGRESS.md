# Progress

## Phase 1: Analysis — COMPLETE

- [x] Read architecture_refactor PROGRESS.md (all phases complete)
- [x] Read architecture-mental-model-simplification PROGRESS.md (W0-W7 complete, 0 cycles)
- [x] Read CRITICAL_RULES.md
- [x] Read Lua plugin: init.lua, panel.lua — understood full plugin architecture
- [x] Read server.py, server_setup.py, notifications.py, handlers/commands.py
- [x] Read agent_runner.py, event_emitter.py, runner/tools.py
- [x] Read agent_events.py, interaction_events.py — confirmed AgentMessageEvent has no event_type
- [x] Read event_store_queries.py — confirmed row_to_event_dict() format
- [x] Read event_store.py — confirmed append() uses type(event).__name__ for event_type; emits to EventBus
- [x] Read event_bus.py — confirmed subscribe/emit API
- [x] Read runtime_ops.py — confirmed do_cursor_update() emits CursorFocusEvent via EventStore→EventBus
- [x] Read lsp/__main__.py — confirmed event_bus created but start_companion() NEVER CALLED
- [x] Read src/remora/companion/ — full production companion architecture understood
  - [x] startup.py, config.py, events.py, state.py, dispatcher.py, indexing_service.py
  - [x] handlers/: context_extractor, edit_summarizer, indexing_handler, search_handler,
         task_inferrer, claim_checker, connection_finder, sidebar_composer
- [x] Read remora_demo/companion/lsp/server.py — old standalone companion LSP (obsolete)
- [x] Read remora_demo/companion/nvim/lua/companion/init.lua — wrong architecture
- [x] Read remora_demo/web/graph/state.py — confirmed critical schema bugs
- [x] Read lsp/db.py — confirmed RemoraDB standalone at .remora/indexer.db
- [x] Read lsp/server.py — confirmed RemoraDB() no-arg → standalone mode
- [x] Read tests/test_bridge.py — confirmed stale schema

## Phase 2: Guide Files — COMPLETE (rewritten after deep analysis)

- [x] Rewrite GUIDE_COMPANION.md (complete: production architecture, integration gap, new plugin)
- [x] Rewrite GUIDE_NEOVIM.md (complete: two event formats, 3 confirmed bugs + fixes)
- [x] Rewrite GUIDE_WEB_UI.md (complete: two-DB architecture, column fixes, test schema)
- [x] Update REFACTORING_GUIDE.md (updated: two-DB, companion gap, priority order)
- [x] Update CONTEXT.md (complete architectural understanding)
- [x] GUIDE_AGENT_CHAT.md (unchanged — still accurate)

## Phase 3: Implement Fixes — NOT STARTED (guides only per user request)

Priority order:

### Companion (Critical — pipeline never runs)
- [ ] Call `start_companion()` in `src/remora/lsp/__main__.py`
- [ ] Add `companion.getSidebar` workspace/executeCommand in `server_setup.py`
- [ ] Subscribe `CompanionSidebarComposed` to push `$/remora/companionSidebarUpdated`
- [ ] Rewrite companion Neovim plugin (`remora_demo/companion/nvim/lua/companion/init.lua`)
- [ ] Delete `remora_demo/companion/lsp/server.py`, `runtime.py`, old agents/, models/

### Web UI (Critical — runtime SQL errors)
- [ ] Fix `state.py`: add `events_db_path` param, use two connections
- [ ] Fix `state.py`: fix all stale column names (`event_id`→`id`, `agent_id`→`from_agent`/`to_agent`, `nodes WHERE id`→`WHERE node_id`)
- [ ] Remove unnecessary `id`→`remora_id` rename in `read_snapshot()`
- [ ] Fix `tests/test_bridge.py`: create production-matching schema (two DB helpers)

### Neovim (High — live messages invisible)
- [ ] Fix `server.py`: `emit_agent_message_event()` → wrap in AgentEvent envelope
- [ ] Fix `panel.lua` Bug 2: historical AgentMessageEvent direction (`ev.from_agent or ev.payload.from_agent`)
- [ ] Fix `panel.lua` Bug 3: duplicate message dedup after refresh

### Agent Chat (Medium — test isolation)
- [ ] Fix `chat_service.py`: remove module-level singleton, fix DI
