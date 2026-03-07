# Neovim Integration — Refactoring Guide

**Area:** `src/remora/lsp/nvim/lua/remora/` (production Lua plugin)
**Also:** `remora_demo/neovim/mock_llm.py` (standalone demo harness)
**Priority:** 1 (bugs affect live agent session visibility)

---

## Overview

The Neovim integration is **not a demo harness** — it is a production Lua plugin that connects Neovim to the live `remora-lsp` server. It lives in `src/remora/lsp/nvim/lua/remora/` and consists of:

- **`init.lua`** — Neovim plugin entry: LSP config, commands, keymaps, notification handlers, retry logic
- **`panel.lua`** — Right-side vsplit panel: agent header, tools (collapsible), chat history, input buffer
- **`log.lua`** — Logging utilities

The plugin:
1. Tracks the `remora-lsp` LanguageServer process (reading `.remora/lsp.pid` for lock-owner metadata)
2. Sends `$/remora/cursorMoved` on `CursorHold` to debounce cursor tracking
3. Renders the agent at cursor in a sidebar panel with live-streamed events
4. Handles user input from both panel (chat) and VS Code-style request dialogs

`remora_demo/neovim/mock_llm.py` is a **separate** standalone demo harness with a scripted `MockLLMClient` for scenarios where a real LLM is unwanted. It is NOT wired into the Lua plugin.

---

## Event Wire Protocol — Two Formats

Events arrive at `panel.lua` via two paths with different structures:

### Path A: Live streaming — `$/remora/event` notification

The server calls `server.protocol.notify("$/remora/event", event.model_dump())`.

**For events that extend `AgentEvent`** (HumanChatEvent, RewriteProposalEvent, AgentTextResponse, etc.):
```lua
{
  event_type = "AgentTextResponse",   -- always present
  agent_id = "func_my_function",       -- always present
  summary = "This function does...",
  payload = { content = "..." },       -- model-specific fields in payload
  correlation_id = "corr_1_abc",
  timestamp = 1741234567.0,
}
```

**For `AgentMessageEvent`** (which extends `_FrozenEvent` directly, NOT `AgentEvent`):
```lua
{
  from_agent = "func_analyze",
  to_agent = "func_test",
  content = "Please check my rewrite",
  tags = {},
  correlation_id = "corr_1_abc",
  timestamp = 1741234567.0,
  -- NO event_type field!
  -- NO agent_id field!
  -- NO payload field!
}
```

### Path B: Historical — `remora.getAgentPanel` response

`cmd_get_agent_panel` calls `event_store.get_recent_events()` which uses `row_to_event_dict()`:
```lua
{
  id = 42,                              -- INTEGER, always present
  event_type = "AgentMessageEvent",    -- always present (from DB column)
  from_agent = "func_analyze",         -- always top-level
  to_agent = "func_test",              -- always top-level
  summary = "",
  payload = { content = "..." },       -- non-meta fields from stored JSON
  timestamp = 1741234567.0,
  correlation_id = "corr_1_abc",
}
```

The key difference: `from_agent`/`to_agent` are ALWAYS at the top level in both formats, never inside `payload`.

---

## Bug 1: Live `AgentMessageEvent` Events Are Silently Dropped (High)

### Location

`panel.lua:M.on_event()`, lines ~789-815

### Problem

`on_event()` routes events to the current agent using:
```lua
local to_agent = event.payload and event.payload.to_agent
if event.agent_id ~= agent_id and to_agent ~= agent_id then
    return  -- silently ignored
end
```

For a live `AgentMessageEvent`, both `event.agent_id` (nil) and `event.payload.to_agent` (nil — no `payload` field) evaluate to nil. The condition `nil ~= agent_id AND nil ~= agent_id` is always true, so **every live `AgentMessageEvent` is silently dropped**. Inter-agent messages are invisible during a live session.

### Root Cause

`AgentMessageEvent` extends `_FrozenEvent` directly (not `AgentEvent`). Its `model_dump()` has no `event_type`, `agent_id`, or `payload` field. The server's `emit_agent_message_event()` sends this raw `model_dump()` via `$/remora/event`.

### Fix Option A (Recommended): Fix server-side notification

In `src/remora/lsp/server.py`, change `emit_agent_message_event()` to notify with a consistent `AgentEvent` envelope:

```python
async def emit_agent_message_event(
    self, *, from_agent: str, to_agent: str, message: str, correlation_id: str
) -> None:
    event = AgentMessageEvent(
        from_agent=from_agent,
        to_agent=to_agent,
        content=message,
        correlation_id=correlation_id,
    )
    if self.event_store:
        await self.event_store.append("swarm", event)

    # Notify with AgentEvent envelope so panel.lua can route by agent_id
    self.protocol.notify("$/remora/event", AgentEvent(
        event_type="AgentMessageEvent",
        agent_id=to_agent,                    # panel routes by agent_id
        correlation_id=correlation_id,
        summary=message[:100],
        payload={
            "from_agent": from_agent,
            "to_agent": to_agent,
            "content": message,
        },
    ).model_dump())
```

This separates storage (using the domain `AgentMessageEvent` model) from notification (using the panel-friendly `AgentEvent` envelope). No changes to panel.lua needed for routing.

### Fix Option B: Fix panel.lua routing

Alternatively, extend the routing check in `on_event()` to handle events without `agent_id`:
```lua
function M.on_event(event)
    if not event then return end
    if not M._agent then return end
    local agent_id = M._agent.id

    -- AgentMessageEvent (no agent_id field) — route by from_agent/to_agent
    local event_to = event.to_agent or (event.payload and event.payload.to_agent)
    local event_from = event.from_agent or (event.agent_id)
    if event.agent_id ~= agent_id
        and event_to ~= agent_id
        and event_from ~= agent_id then
        return
    end
    ...
end
```

Fix A is cleaner (consistent wire format) but touches production server code. Fix B is isolated to panel.lua.

---

## Bug 2: Historical `AgentMessageEvent` Direction Shows "unknown" (Medium)

### Location

`panel.lua:build_lines()`, lines ~298-299

### Problem

```lua
local from = (ev.payload and ev.payload.from_agent) or "unknown"
local to   = (ev.payload and ev.payload.to_agent) or "unknown"
```

Both `from_agent` and `to_agent` are at the **top level** of the event dict (from `row_to_event_dict()`), not inside `payload`. So `ev.payload.from_agent` and `ev.payload.to_agent` are always nil. Every inter-agent message shows:
```
→ From: unknown
```

### Fix

```lua
local from = ev.from_agent or (ev.payload and ev.payload.from_agent) or "unknown"
local to   = ev.to_agent   or (ev.payload and ev.payload.to_agent)   or "unknown"
```

This also handles Fix Option A above (where the server wraps `from_agent`/`to_agent` inside payload), keeping it forwards-compatible with both server-side fix approaches.

---

## Bug 3: Duplicate User Message After Panel Refresh (Low)

### Location

`panel.lua:send_message()` (line ~580) and `do_fetch_agent_data()` merge logic (line ~498-513)

### Problem

When the user sends a message, `send_message()` immediately inserts a local event with **no `id`**:
```lua
table.insert(M._events, {
    event_type = "HumanChatEvent",
    timestamp = os.time(),
    payload = { message = text },
    -- id = nil  (not set)
})
```

The panel dedup logic at refresh:
```lua
local server_ids = {}
for _, ev in ipairs(result.events) do
    server_ids[ev.id or ev.event_id] = true  -- sets server_ids[42] = true, etc.
end
-- Keep live events not in server_ids
for _, ev in ipairs(M._events) do
    if not server_ids[ev.id or ev.event_id] then  -- local: server_ids[nil] = nil → always kept
        table.insert(new_events, ev)
    end
end
```

`ev.id or ev.event_id` for the local event = `nil or nil = nil`. Lua tables don't store nil keys, so `server_ids[nil]` is always nil → `not nil = true` → **the local event is always kept even after the server returns the same message with an ID**. Result: two identical-looking user messages in the chat.

Note: `on_event()` correctly skips live `HumanChatEvent` from the server (line ~808-811, intentional dedup). But this doesn't prevent the `getAgentPanel` refresh from returning the historical version while the local (id=nil) copy persists.

### Fix

Assign a client-side placeholder ID to locally-created events and remove them when the server version arrives:

```lua
-- In send_message():
M._pending_local_seq = (M._pending_local_seq or 0) + 1
local local_id = "local_" .. M._pending_local_seq
table.insert(M._events, {
    event_type = "HumanChatEvent",
    id = local_id,          -- client-side placeholder
    timestamp = os.time(),
    payload = { message = text },
})

-- In the merge logic, strip local events that have been superseded:
for _, ev in ipairs(M._events) do
    local ev_id = ev.id or ev.event_id
    local is_local = ev_id and tostring(ev_id):sub(1, 6) == "local_"
    local in_server = server_ids[ev_id]
    if not in_server and not (is_local and #result.events > 0) then
        table.insert(new_events, ev)
    end
end
```

Alternatively (simpler): remove all `id=nil` events on each refresh:
```lua
for _, ev in ipairs(M._events) do
    if (ev.id or ev.event_id) and not server_ids[ev.id or ev.event_id] then
        table.insert(new_events, ev)
    end
end
```
This drops local events once the server returns any events (assuming the server event is now included in `result.events`).

---

## `remora_demo/neovim/mock_llm.py` — Correct Purpose

`MockLLMClient` is a scripted LLM mock for standalone demo scenarios. It is NOT connected to the Lua plugin. Its purpose: run the `remora-lsp` server with a deterministic mock model to script demo beats (cursor focus → agent trigger → proposal) without a real LLM.

### Tool Name Alignment (Verified Correct)

The mock uses these tool names in `ToolCall.name`:
- `rewrite_self` ✅ matches `RewriteSelfTool` schema name
- `message_node` ✅ matches `MessageNodeTool` schema name
- `read_node` ✅ matches `ReadNodeTool` schema name

No changes needed here.

### MockLLMClient is Not Injectable into AgentRunner

`MockLLMClient.chat()` returns its own `LLMResponse` model, not `structured_agents` types. If someone tries to inject it into `AgentRunner` for integration testing, it will fail at the kernel boundary. Add a comment:

```python
# NOTE: MockLLMClient uses local response models, not structured_agents types.
# It is demo-only — not injectable into AgentRunner's kernel.
# Use only as a standalone demo LLM replacement.
```

---

## Summary of Changes

| Bug | File | Severity | Fix |
|-----|------|----------|-----|
| Live `AgentMessageEvent` silently dropped | `server.py` (preferred) or `panel.lua` | **High** | Wrap notification in `AgentEvent` envelope |
| `AgentMessageEvent` direction shows "unknown" | `panel.lua` lines ~298-299 | **Medium** | Use `ev.from_agent`/`ev.to_agent` |
| Duplicate user message after refresh | `panel.lua` merge logic ~498-513 | Low | Assign local IDs, strip on refresh |
| Document `MockLLMClient` injection limitation | `remora_demo/neovim/mock_llm.py` | Low | Add code comment |

---

## Verification

```bash
# Lua plugin: no automated tests — use a live Neovim session
# Verify the LSP server starts:
devenv shell -- python -m remora.lsp.__main__ --help

# Verify mock_llm imports cleanly:
devenv shell -- python -c "from remora_demo.neovim.mock_llm import MockLLMClient; print('OK')"
```

For live testing: open a Python file, start the Neovim plugin, trigger `RemoraChat`, send a message, and observe:
1. Message appears immediately (local event)
2. Agent response appears as `AgentTextResponse`
3. Tool calls appear as `ToolResultEvent` with `result_summary`
4. Inter-agent messages appear as `AgentMessageEvent` (requires Bug 1 fix)
