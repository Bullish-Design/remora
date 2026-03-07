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
- [x] Read event_store.py — confirmed append() uses type(event).__name__ for event_type
- [x] Read remora_demo/web/graph/state.py, bridge.py — confirmed critical schema bugs
- [x] Read service/chat_service.py — confirmed singleton anti-pattern
- [x] Read companion lsp/server.py, runtime.py — understood pattern divergence

## Phase 2: Guide Files — COMPLETE

- [x] Create GUIDE_WEB_UI.md (critical schema bugs + test schema staleness)
- [x] Create GUIDE_AGENT_CHAT.md (singleton anti-pattern, closure gap)
- [x] Rewrite GUIDE_NEOVIM.md (was wrong — now covers actual Lua plugin bugs)
- [x] Rewrite GUIDE_COMPANION.md (added Neovim plugin, timeline server, protocol issues)
- [x] Update REFACTORING_GUIDE.md (corrected area descriptions + protocol reference)
- [x] Update README.md with corrected findings
- [x] Create scaffold files: PLAN.md, CONTEXT.md, ASSUMPTIONS.md, DECISIONS.md, ISSUES.md

## Phase 3: Implement Fixes — NOT STARTED (guides only per user request)

- [ ] Fix state.py schema (critical — runtime SQL errors)
- [ ] Fix tests/test_bridge.py schema (critical — false test confidence)
- [ ] Fix panel.lua Bug 1: AgentMessageEvent routing (High — live messages invisible)
- [ ] Fix panel.lua Bug 2: AgentMessageEvent direction (Medium)
- [ ] Fix panel.lua Bug 3: duplicate message after refresh (Low)
- [ ] Fix chat_service.py singleton anti-pattern (Medium)
- [ ] Add MockLLMClient comment (Low)
