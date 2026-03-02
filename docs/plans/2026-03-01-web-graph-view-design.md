# Web-Based Graph View for Remora Neovim Demo

**Date:** 2026-03-01
**Status:** Approved

## Overview

A web-based graph visualization that shows all Remora AST agent nodes in a hierarchical tree layout, with real-time cursor tracking from neovim and live agent status updates. Runs as a standalone Starlette app alongside the LSP, reading from the shared SQLite database.

## V1 Scope (Read-Only)

- Hierarchical tree visualization of all nodes (files -> classes -> functions/methods)
- Real-time cursor tracking (highlighted node follows neovim cursor)
- Real-time status updates (node colors reflect active/running/pending/orphaned)
- Node click shows agent detail sidebar (info, recent events)
- Zoom/pan via CSS transform + lightweight JS wheel handler
- Edge rendering (parent_of = solid, calls = dashed)

**Deferred to v2:** Web-to-agent chat, tool call triggering from web UI.

## Architecture

### Approach: Pure Datastar SSE

The server owns all state. The browser renders HTML fragments morphed via SSE patches. No client-side JS graph library.

- Standalone Starlette app in `remora_demo/web/`
- Reads shared `.remora/indexer.db` (SQLite WAL mode, concurrent-safe)
- Change detection via WAL file watching (watchfiles) with polling fallback
- Pure datastar SSE streaming -- patches sent only on actual changes
- Server-computed hierarchical layout, server-rendered HTML, browser morphs DOM via datastar

### Why This Approach

- 100% aligned with datastar philosophy: server owns state, browser just renders
- No JS graph library to manage or conflict with datastar DOM morphing
- Layout computed server-side (simple hierarchical algorithm)
- Real-time updates via SSE patches are trivial (re-render changed node divs)
- Consistent with existing Remora dashboard patterns (`src/remora/service/datastar.py`, `src/remora/adapters/starlette.py`)

### Alternatives Considered

1. **Hybrid Datastar + Canvas:** Better perf for large graphs but breaks pure datastar model. Client maintains render state, need custom canvas renderer (~300 lines JS), SSE patches can't morph canvas directly.
2. **Static Polling:** Dead simple but no real-time feel (1-2s lag), ignores existing datastar infrastructure, inconsistent with project patterns.

## Module Structure

```
remora_demo/web/
    __init__.py         -- exports create_app()
    __main__.py         -- CLI: python -m remora_demo.web [--port 8420]
    app.py              -- Starlette routes: /, /subscribe, /agent/{id}
    state.py            -- GraphState: DB reader + change detection
    layout.py           -- compute_hierarchical_layout()
    render.py           -- render_shell(), render_graph(), render_node(), render_agent_detail()
```

Entry point: `python -m remora_demo.web --port 8420`

## Cursor Tracking

Piggybacks on existing neovim `CursorHold` mechanism with minimal additions.

### Flow

1. Neovim `CursorHold` fires (built-in debounce via `updatetime`, typically 300-1000ms)
2. Always-on autocmd in `init.lua` sends `$/remora/cursorMoved` notification to LSP with `{uri, line}`
3. LSP handler resolves `agent_id` via `db.get_node_at_position()` (already exists)
4. LSP writes to `cursor_focus` table in SQLite (single row, always overwritten)
5. Web server detects WAL change, reads `cursor_focus`, sends SSE patch highlighting the active node

### Why This Doesn't Slow Neovim

- `CursorHold` only fires when cursor stops moving (debounced)
- `client.notify()` is fire-and-forget (no response expected, no callback)
- LSP handler runs one indexed SQL query + one single-row REPLACE in a background thread
- Net impact on neovim: zero

### Existing Code Leveraged

- `cursor_context()` function in `init.lua:112-118` already builds `{uri, line}`
- `db.get_node_at_position()` in `db.py:160-171` already resolves cursor to node
- Panel's `CursorHold` autocmd in `panel.lua:536` already demonstrates the pattern
- The new always-on autocmd is independent of the panel (works when panel is closed)

## SSE Streaming Model (Datastar-Idiomatic)

### Pattern

```python
async def subscribe(request):
    async def stream():
        yield SSE.patch_elements(render_graph(initial_state))
        async for change in graph_state.changes():
            yield SSE.patch_elements(render_graph(change))
    return DatastarResponse(stream())
```

### Change Detection

`GraphState` detects DB changes via:
1. **Primary:** Watch `.remora/indexer.db-wal` file for modifications using `watchfiles`
2. **Fallback:** Lightweight polling of `max(rowid)` on nodes/edges tables

Changes are pushed to an in-process `asyncio.Queue`. The SSE stream reads from this queue -- purely event-driven, not polling per connection.

### What Triggers Visual Updates

| Trigger | DB Change | Visual Update |
|---------|-----------|---------------|
| Cursor moves in neovim | `cursor_focus` row updated | Active node highlight moves |
| File saved in neovim | Nodes/edges upserted | Graph re-layout + re-render |
| Agent status changes | Node status field updated | Node color changes |
| Agent events (responses, errors) | Events table updated | Event count badge on node |

## Web UI Layout

### Three Areas

1. **Graph viewport (main area):** Container div with `overflow: hidden` and CSS `transform` for zoom/pan. Node divs absolutely positioned with `style="left: {x}px; top: {y}px"`. Edge SVG overlay with `<path>` elements.

2. **Agent detail sidebar (right):** Shown on node click via `@get('/agent/{id}')`. Displays agent info, recent events. Read-only in v1.

3. **Zoom/pan controls:** Wheel handler on viewport container adjusts CSS `transform: scale() translate()`. ~20 lines inline JS.

### Node Rendering

- Each node is a `<div id="node-{remora_id}">` with classes for `node_type` and `status`
- Focused node (from `cursor_focus`) gets additional `focused` class
- Colors: active=green, running=blue, pending=yellow, orphaned=gray (matches neovim highlights)

### Edge Rendering

- SVG overlay with same dimensions as graph container
- `parent_of` edges: solid lines
- `calls` edges: dashed lines
- Paths computed from node center positions

### Layout Algorithm

Hierarchical tree, computed server-side:
- Files are columns (spaced horizontally)
- Classes are groups within columns
- Functions/methods are leaf rows within class groups (or directly under file if module-level)
- Deterministic positions (same graph always produces same layout)
- No rustworkx dependency -- simple recursive positioning algorithm

## Changes to Existing Code

### 1. `src/remora/lsp/db.py`

Add `cursor_focus` table to schema:
```sql
CREATE TABLE IF NOT EXISTS cursor_focus (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    agent_id TEXT,
    file_path TEXT,
    line INTEGER,
    timestamp REAL
);
```

Add methods: `update_cursor_focus(agent_id, file_path, line)`, `get_cursor_focus() -> dict | None`

### 2. `src/remora/lsp/nvim/lua/remora/init.lua`

Add always-on `CursorHold` autocmd in `M.setup()`:
```lua
vim.api.nvim_create_autocmd("CursorHold", {
    callback = function()
        local client = get_client()
        if not client then return end
        local ctx = cursor_context()
        client.notify("$/remora/cursorMoved", ctx)
    end,
})
```

### 3. `src/remora/lsp/server.py` (or new handler file)

Add notification handler for `$/remora/cursorMoved`:
- Receives `{uri, line}`
- Calls `db.get_node_at_position(uri, line, 0)`
- Calls `db.update_cursor_focus(agent_id, uri, line)`

### 4. New module: `remora_demo/web/` (5 files)

As described in Module Structure section above.

## Dependencies

- `datastar-py` (already in pyproject.toml)
- `starlette` (already in pyproject.toml)
- `uvicorn` (already available)
- `watchfiles` (new, for WAL file watching -- optional, falls back to polling)

## Data Source

The web server reads directly from `.remora/indexer.db` -- the same SQLite database the LSP writes to. WAL mode enables concurrent readers without blocking the LSP writer.

### Tables Read

- `nodes` -- all AST agent nodes (id, node_type, name, file_path, start_line, end_line, status, parent_id)
- `edges` -- relationships (from_id, to_id, edge_type where edge_type is 'parent_of' or 'calls')
- `events` -- agent events for detail sidebar
- `cursor_focus` -- current neovim cursor position (new table)
