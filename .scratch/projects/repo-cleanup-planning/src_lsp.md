# src/remora/lsp/ — Shadow Tree Notes

## Status: MODIFY (Option A migration in progress)

### Key files:
- `server.py` — RemoraLanguageServer. Already imports AgentNode from core. Partially migrated.
- `db.py` — RemoraDB (SQLite). Still has proposals, cursor_focus, events, activation_chain, edges, command_queue tables. KEEP (LSP-specific tables stay).
- `models.py` — ASTAgentNode was already REMOVED. Still has RewriteProposal, AgentEvent, ManualTriggerEvent re-exports. KEEP but slim down.
- `graph.py` — LazyGraph. MODIFY to use EventStore.
- `watcher.py` — ASTWatcher. MODIFY to emit NodeDiscoveredEvents to EventStore.
- `runner.py` — LSP runner. KEEP.
- `notifications.py` — LSP notifications. MODIFY.
- `handlers/` — LSP protocol handlers (actions, capabilities, commands, documents, hover, lens). MODIFY to use AgentNode from EventStore.
- `__main__.py`, `__init__.py` — Entry points. KEEP.
- `nvim/lua/remora/` — Lua plugin files bundled with LSP. KEEP.
- `py.typed` — PEP 561 marker. KEEP.
