# Panel Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the floating nui-components global agent dashboard with a right-side vsplit panel focused on the agent at cursor, showing chat history and allowing inline messaging.

**Architecture:** Real vsplit window + scratch buffers. Header and chat rendered via `nvim_buf_set_lines` + `nui.line` highlights. Input via a small horizontal split at the bottom of the panel column. Server provides a new `remora.getAgentPanel` command returning agent info + tools + recent events.

**Tech Stack:** Lua (Neovim API + nui.line), Python (pygls 2.0 `@server.command`)

---

### Task 1: Add `remora.getAgentPanel` server command

**Files:**
- Modify: `src/remora/lsp/handlers/commands.py`

**Step 1: Add the command**

Add after the existing `cmd_chat` command:

```python
@server.command("remora.getAgentPanel")
async def cmd_get_agent_panel(ls, *args) -> dict | None:
    try:
        logger.info("cmd_get_agent_panel: args=%r", args)
        ctx = args[0] if args else None
        if not ctx or not isinstance(ctx, dict):
            return None
        uri = ctx.get("uri")
        line = ctx.get("line")
        if not uri or line is None:
            return None
        node = await ls.db.get_node_at_position(uri, line, 0)
        if not node:
            return None

        agent_id = node["remora_id"]

        # Get tools
        tools = []
        if ls.runner:
            agent_obj = ASTAgentNode(**node)
            agent_obj = ls.runner.apply_extensions(agent_obj)
            raw_tools = ls.runner.get_agent_tools(agent_obj)
            tools = [
                {"name": t["function"]["name"], "description": t["function"].get("description", "")}
                for t in raw_tools
            ]

        # Get recent events
        events = await ls.db.get_recent_events(agent_id, limit=50)
        event_dicts = [e.model_dump() for e in events]

        return {
            "agent": {
                "id": agent_id,
                "name": node["name"],
                "node_type": node["node_type"],
                "status": node["status"],
                "start_line": node["start_line"],
                "end_line": node["end_line"],
                "file_path": node["file_path"],
            },
            "tools": tools,
            "events": event_dicts,
        }
    except Exception:
        logger.exception("Error in remora.getAgentPanel")
        return None
```

### Task 2: Rewrite panel.lua as vsplit-based agent panel

**Files:**
- Rewrite: `src/remora/lsp/nvim/lua/remora/panel.lua`

Full rewrite. Drop all nui-components usage. Use native vsplit + nui.line.

### Task 3: Update init.lua for new panel API

**Files:**
- Modify: `src/remora/lsp/nvim/lua/remora/init.lua`

- `$/remora/event` handler: call `panel.on_event(result)` instead of `panel.add_event(result)`
- `$/remora/requestInput` handler: if panel is open and has matching agent, route input to panel instead of `vim.ui.input`
- Remove `$/remora/agentsUpdated` handler (no longer needed for panel)
- Update `toggle_panel` to pass `cursor_context()` and `exec_command` to panel
- Add `CursorHold`/`BufEnter` autocmds for auto-refresh

### Task 4: Add Ctrl+hjkl window navigation (DONE)

Already added to `/home/andrew/Documents/Projects/nixvim/nvim/lua/config/keymaps.lua`.
