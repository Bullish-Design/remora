# Panel Redesign: Right-side Agent Panel

## Problem

The current panel.lua is a global dashboard showing all ~3,500 workspace nodes in a floating nui-components window. It should be a focused single-agent interface that shows the agent at cursor, its tools, chat history, and allows inline chatting. LLM responses currently have nowhere to display.

## Design

### Layout

Real `vsplit` on the right edge, ~25% of editor width. Not a floating window.

```
+-------------------------------+----------+
|                               | [Header] |
|    Editor windows             |  name,   |
|    (reflow normally,          |  type,   |
|     Ctrl+hjkl navigates       |  status  |
|     to/from panel)            |----------|
|                               | [Tools]  |  (collapsible, hidden by default)
|                               |----------|
|                               |  Chat    |
|                               |  history |
|                               |  (scroll)|
|                               |----------|
|                               | > input  |
+-------------------------------+----------+
         ~75%                      ~25%
```

- `botright vsplit` creates split, width set to `floor(vim.o.columns * 0.25)`
- Single scratch buffer (`buftype=nofile, bufhidden=wipe`) for header + chat history
- Content rendered via `nvim_buf_set_lines` + `nui.line` for highlights
- Input is a 1-line prompt buffer in a small horizontal split at the bottom of the panel column
- Ctrl+h/j/k/l window navigation works naturally

### Data Flow

**On open (`<space>ra`):**
1. Client sends `workspace/executeCommand` with `remora.getAgentPanel` + `{uri, line}`
2. Server resolves agent at cursor, gathers tools + recent events
3. Returns `{agent: {id, name, node_type, status, start_line, end_line}, tools: [...], events: [...]}`
4. Client renders panel content

**Auto-refresh (persistent):**
- `CursorHold` + `BufEnter` autocmds send `remora.getAgentPanel` with new cursor position
- If agent_id changed, re-render panel; if same agent, no-op

**Chat send (`<CR>` in input buffer):**
- Client sends `$/remora/submitInput` notification with `{agent_id, input}`
- Appends user message to chat display immediately
- Server processes, emits `$/remora/event` notifications
- Client's `$/remora/event` handler appends to chat history if agent_id matches

**Live event updates:**
- `$/remora/event` handler checks `event.agent_id == panel.current_agent_id`
- If match, append formatted event to chat buffer

### Server-side Addition

New command `remora.getAgentPanel` in `commands.py`:
- Takes `{uri, line}` args (same as existing cursor_context)
- Uses `db.get_node_at_position()` for agent info
- Uses `runner.get_agent_tools()` for tool list
- Uses `db.get_recent_events(agent_id, limit=50)` for history
- Returns combined dict

### Input Handling

- `<CR>` in insert mode in input buffer: send message, clear input
- `<Esc>` in input buffer: return to normal mode (not close panel)
- `q` in normal mode in chat buffer: close panel
- `t` in normal mode in chat buffer: toggle tools section
- Panel auto-closes via autocmd when last editor window is closed

### Keymaps

Panel-local:
- `q` — close panel
- `t` — toggle tools visibility
- `<CR>` (insert, input buffer) — send message
- `<Esc>` (insert, input buffer) — back to normal mode

Global (nixvim config):
- `<C-h>` — move to left window
- `<C-j>` — move to down window
- `<C-k>` — move to up window
- `<C-l>` — move to right window

### Files Changed

- `panel.lua` — full rewrite (drop nui-components Renderer, use vsplit + nui.line)
- `init.lua` — update panel open/close calls, update event handler
- `commands.py` — add `remora.getAgentPanel` command
- `nixvim keymaps.lua` — add Ctrl+hjkl window navigation
