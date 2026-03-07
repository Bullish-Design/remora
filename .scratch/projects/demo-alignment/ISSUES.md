# Issues

No active blockers.

## Confirmed Bugs (pending implementation)

### Issue A: `panel.lua` — `AgentMessageEvent` live events silently dropped
File: `src/remora/lsp/nvim/lua/remora/panel.lua`
Severity: High (inter-agent messages invisible to user during live session)
See: GUIDE_NEOVIM.md Bug 1

### Issue B: `panel.lua` — `AgentMessageEvent` direction always "unknown" in history
File: `src/remora/lsp/nvim/lua/remora/panel.lua`
Severity: Medium (from/to display shows "unknown" for all agent messages)
See: GUIDE_NEOVIM.md Bug 2

### Issue C: `panel.lua` — duplicate HumanChatEvent after panel refresh
File: `src/remora/lsp/nvim/lua/remora/panel.lua`
Severity: Low (visual artifact — user message appears twice after refresh)
See: GUIDE_NEOVIM.md Bug 3

### Issue D: `state.py` — stale SQL schema (event_id, agent_id, nodes.id)
File: `remora_demo/web/graph/state.py`
Severity: Critical (causes sqlite3.OperationalError at runtime)
See: GUIDE_WEB_UI.md Bug 1, Bug 2

### Issue E: `tests/test_bridge.py` — stale test schema
File: `tests/test_bridge.py`
Severity: High (false confidence — tests pass with old schema)
See: GUIDE_WEB_UI.md

### Issue F: `chat_service.py` — module-level singleton anti-pattern
File: `src/remora/service/chat_service.py`
Severity: Medium (import side-effects, shared state between tests)
See: GUIDE_AGENT_CHAT.md
