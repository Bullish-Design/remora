# LSP Layer Analysis Notes

## Files Read
- `lsp/__init__.py` - clean re-exports
- `lsp/__main__.py` - server startup, background scan, LLM client init
- `lsp/server.py` - RemoraLanguageServer class, module-level singleton
- `lsp/models.py` - Pydantic models: ASTAgentNode, RewriteProposal, event hierarchy
- `lsp/db.py` - SQLite persistence with async_db decorator
- `lsp/graph.py` - LazyGraph with optional rustworkx
- `lsp/watcher.py` - AST parsing via tree-sitter with fallback
- `lsp/runner.py` - AgentRunner + LLMClient + tool call loop
- `lsp/extensions.py` - ExtensionNode dynamic loading from .remora/models/
- `lsp/notifications.py` - $/remora/cursorMoved and $/remora/submitInput handlers
- `lsp/handlers/` - documents, hover, lens, actions, commands, capabilities

## V2.1 Alignment Assessment

### STRONG alignment:
1. **LSP IS the spine** - pygls LanguageServer, proper LSP protocol. YES.
2. **Pydantic models as bridge** - ASTAgentNode, RewriteProposal, all events. YES.
3. **CodeLens = agent IDs** - `to_code_lens()` on ASTAgentNode. YES.
4. **Hover = agent details** - `to_hover()` with events, graph context. YES.
5. **CodeAction = tools** - `to_code_actions()` + proposal accept/reject. YES.
6. **Diagnostics = proposals** - `to_diagnostic()` on RewriteProposal. YES.
7. **WorkspaceEdit = apply changes** - `to_workspace_edit()` on RewriteProposal. YES.
8. **Custom $/remora/* notifications** - event, requestInput, submitInput, cursorMoved, agentsUpdated, agentSelected. YES.
9. **Minimal Lua client** - init.lua is setup + handlers, panel.lua is UI. YES.

### Architecture quality:
- **models.py** is excellent. Pydantic models with LSP conversion methods.
  Clean hierarchy: AgentEvent base, typed subclasses with model_validators.
- **db.py** solid SQLite with WAL mode, proper schema, async_db decorator.
  Good: separate tables for nodes, edges, events, proposals, activation_chain, cursor_focus, command_queue.
- **server.py** clean but has module-level singleton `server = RemoraLanguageServer()` and free functions wrapping methods. This is pragmatic for pygls but could be cleaner.
- **runner.py** is the most complex. Tool call loop with MAX_TOOL_ROUNDS. Handles rewrite_self, message_node, read_node. Extension tool dispatch.
- **watcher.py** tree-sitter parsing + fallback regex parser. Clean separation.
- **graph.py** LazyGraph with rustworkx optional dependency. Good graceful degradation.
- **extensions.py** Dynamic loading from `.remora/models/*.py`. File-mtime cache.

### Issues / Concerns:

1. **__main__.py hardcodes LLM config:**
   ```python
   llm = LLMClient(
       base_url="http://remora-server:8000/v1",
       model="Qwen/Qwen3-4B-Instruct-2507-FP8",
   )
   ```
   Should come from config or env vars.

2. **`_notify_agents_updated` monkey-patched onto server:**
   `server._notify_agents_updated = _notify_agents_updated` in __main__.py
   Then `hasattr(server, "_notify_agents_updated")` checks in handlers.
   This is fragile. Should be a proper method on RemoraLanguageServer.

3. **Module-level singleton pattern:**
   `server = RemoraLanguageServer()` at module scope, then `register_handlers()` called immediately.
   Free functions `refresh_code_lenses()`, `publish_diagnostics()`, `emit_event()` wrap singleton.
   This works but makes testing harder. The V2.1 concept envisions cleaner DI.

4. **runner.py `_load_agent_state` returns None always:**
   ```python
   async def _load_agent_state(self, agent_id: str) -> Any:
       return None
   ```
   The SwarmExecutor path is stubbed out. Dead code path.

5. **Duplicate ID reassignment in did_save:**
   `documents.py:did_save` re-does the ID matching that watcher.parse_and_inject_ids already does (lines 82-87). This is redundant and could cause bugs.

6. **LazyGraph opens its OWN sqlite connection** separate from RemoraDB.
   Two connections to the same DB. WAL mode makes this safe but it's unnecessary complexity.

7. **`_extract_text_tool_calls` in runner.py** parses `<tool_call>` XML tags.
   Model-specific workaround for Qwen. Should be documented/configurable.

8. **did_save injects IDs back into files:**
   `inject_ids(file_path, new_nodes)` writes `# rm_xxx` comments into Python files.
   This is invasive. The V2.1 concept suggests IDs should be virtual (in DB/LSP only).

9. **`async_db` decorator** wraps sync sqlite in threads. Works but means every DB call goes through `asyncio.to_thread`. For a local SQLite this is fine but adds overhead. Could use aiosqlite.

10. **Event reconstruction from DB is lossy:**
    `_reconstruct_event` creates base `AgentEvent` not the original subclass.
    Summary and extra fields are stuffed into `payload`. This means round-tripping events through DB loses type information.

11. **`poll_commands` and `push_command` are sync (not decorated with @async_db):**
    `push_command` and `poll_commands` are called from different contexts.
    `poll_command_queue` in runner wraps them in `asyncio.to_thread`.
    `push_command` is called directly (sync) from web server. Inconsistent.

## Lua Plugin Quality

### init.lua
- Clean setup function with opts handling
- Good: checks for vim.lsp.config (Neovim 0.11+)
- Good: LSP config via vim.lsp.config["remora"]
- Clean notification handlers for $/remora/* events
- User commands map well to LSP commands
- CursorHold autocmd for cursor tracking
- Logging throughout

### panel.lua
- Full agent panel implementation: header, tools, chat, input
- NuiLine-based rendering with highlights
- Debounced cursor-driven refresh
- Local event accumulation (optimistic UI)
- Clean lifecycle: open/close/cleanup with autocmds
- Input handling with send_message
- Good event type rendering with icons + highlighting

### Issues:
- `nui.line` dependency - not standard, needs nui.nvim plugin
- Panel is purely functional/procedural (module table as state). Works but all state is mutable globals.
- `send_message` optimistically appends HumanChatEvent, then `on_event` skips it. This avoids dupes but the dedup logic is by event_type, not by content. Could show stale events.

## plugin/remora_nvim.lua
- This is a DIFFERENT, OLDER plugin (`remora_nvim` module).
- References `remora_nvim.sidepanel`, `remora_nvim.chat` - different from the LSP-native plugin.
- **This is dead code / legacy.** Should be removed or clearly deprecated.
