# Neovim Integration — Refactoring Guide

**Area:** `src/remora/lsp/nvim/lua/remora/` (production Lua plugin)
**Also:** `remora_demo/neovim/mock_llm.py` (standalone demo harness — unrelated)
**Priority:** 1 (bugs affect live agent session visibility)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Event Wire Protocol — Two Formats](#2-event-wire-protocol--two-formats)
3. [Bug 1 — Live AgentMessageEvent Silently Dropped](#3-bug-1--live-agentmessageevent-silently-dropped)
4. [Bug 2 — Historical AgentMessageEvent Direction "unknown"](#4-bug-2--historical-agentmessageevent-direction-unknown)
5. [Bug 3 — Duplicate User Message After Panel Refresh](#5-bug-3--duplicate-user-message-after-panel-refresh)
6. [Verified Correct (No Changes)](#6-verified-correct-no-changes)
7. [MockLLMClient Demo Harness (Separate)](#7-mockllmclient-demo-harness-separate)
8. [Acceptance Criteria](#8-acceptance-criteria)

---

## 1. Overview

The Neovim integration is **not a demo harness** — it is a production Lua plugin that connects Neovim to the live `remora-lsp` server. It lives at:

- **`src/remora/lsp/nvim/lua/remora/init.lua`** — plugin entry: LSP config, commands, keymaps, notification handlers, retry/startup logic
- **`src/remora/lsp/nvim/lua/remora/panel.lua`** — right-side vsplit panel: agent header, tools (collapsible), chat history, input buffer
- **`src/remora/lsp/nvim/lua/remora/log.lua`** — logging utilities

### What it does:

1. Tracks the `remora-lsp` process via `.remora/lsp.pid` lock metadata
2. Sends `$/remora/cursorMoved` on `CursorHold` (debounced cursor tracking)
3. Renders the agent at cursor in a right-side panel with live-streamed events
4. Handles user input from the panel (chat) and `vim.ui.input` fallback
5. Handles `$/remora/requestInput` push for interactive proposals

### Command/notification map:

| Direction | Method | What happens |
|-----------|--------|--------------|
| Client → Server | `$/remora/cursorMoved` | Triggers cursor update + companion pipeline |
| Client → Server | `$/remora/submitInput` | User response to HumanInputRequestEvent |
| Client → Server | `workspace/executeCommand remora.chat` | Open panel, start agent session |
| Client → Server | `workspace/executeCommand remora.getAgentPanel` | Fetch agent history |
| Server → Client | `$/remora/event` | Live event streaming (see Bug 1) |
| Server → Client | `$/remora/requestInput` | Agent requesting user input |
| Server → Client | `$/remora/agentSelected` | Agent selection update |

---

## 2. Event Wire Protocol — Two Formats

Events arrive at `panel.lua` via TWO paths with different structures:

### Path A: Live streaming — `$/remora/event`

The server calls `server.protocol.notify("$/remora/event", event.model_dump())`.

**For events extending `AgentEvent`** (HumanChatEvent, RewriteProposalEvent, AgentTextResponse, ToolCallEvent, ToolResultEvent, etc.):

```lua
{
  event_type = "AgentTextResponse",    -- always present (model field)
  agent_id = "func_my_function",       -- always present (model field)
  summary = "...",
  payload = { content = "..." },       -- extra fields in payload dict
  correlation_id = "corr_1_abc",
  timestamp = 1741234567.0,
}
```

`AgentEvent` stores all event-specific data in `payload: dict[str, Any]`. The `model_dump()` call flattens `AgentEvent` fields at the top level and puts extra data in `payload`.

**For `AgentMessageEvent`** (extends `_FrozenEvent` directly, NOT `AgentEvent`):

```lua
{
  from_agent = "func_analyze",
  to_agent = "func_validate",
  content = "Please check this.",
  correlation_id = "corr_1_abc",
  timestamp = 1741234567.0,
  -- NO event_type field
  -- NO agent_id field
  -- NO payload field
}
```

`AgentMessageEvent` has no `event_type`, `agent_id`, or `payload` because it extends `_FrozenEvent` directly, not `AgentEvent`. This causes Bug 1.

### Path B: Historical — `remora.getAgentPanel` command response

The panel calls `workspace/executeCommand remora.getAgentPanel` and receives a list of events formatted by `row_to_event_dict()` in `event_store_queries.py`.

Historical format — ALWAYS structured as:

```lua
{
  id = 42,                            -- INTEGER PK from events table
  event_type = "AgentMessageEvent",   -- from DB column (not model field!)
  from_agent = "func_analyze",        -- TOP LEVEL, not in payload
  to_agent = "func_validate",         -- TOP LEVEL, not in payload
  payload = {                         -- only non-meta fields go here
    content = "Please check this.",
    -- (from_agent and to_agent are meta_keys → NOT in payload)
  },
  summary = "...",
  timestamp = 1741234567.0,
}
```

**Key invariant**: `meta_keys` in `row_to_event_dict()` excludes: `event_id, event_type, timestamp, correlation_id, agent_id, summary, payload, from_agent, to_agent, tags, graph_id, created_at, id`. These fields appear at the top level, never in `payload`.

---

## 3. Bug 1 — Live AgentMessageEvent Silently Dropped

### Impact: HIGH — inter-agent messages invisible during live sessions

### Root cause

`panel.lua`'s `on_event()` function routes live events by checking `event.agent_id`:

```lua
-- panel.lua, on_event():
local agent_id = event.agent_id or (event.payload and event.payload.to_agent)
if not agent_id then
    -- No routing target → event is DROPPED SILENTLY
    return
end
```

`AgentMessageEvent.model_dump()` produces:
```python
{
    "from_agent": "func_analyze",
    "to_agent": "func_validate",
    "content": "...",
    "timestamp": 1741234567.0,
    # NO "event_type" key
    # NO "agent_id" key
    # NO "payload" key
}
```

`event.agent_id` → nil, `event.payload` → nil, so the routing check fails and the event is silently dropped. The user never sees inter-agent messages during a live session.

### Fix: Server side — wrap in AgentEvent envelope

In `src/remora/lsp/server.py`, `emit_agent_message_event()` currently sends raw `AgentMessageEvent.model_dump()`. Change it to wrap in an `AgentEvent` envelope with `event_type="AgentMessageEvent"`:

```python
# src/remora/lsp/server.py

def emit_agent_message_event(
    self,
    from_agent: str,
    to_agent: str,
    message: str,
    correlation_id: str | None = None,
) -> None:
    """Emit an AgentMessageEvent wrapped in an AgentEvent envelope for panel.lua routing."""
    from remora.core.events.agent_events import AgentEvent

    envelope = AgentEvent(
        event_type="AgentMessageEvent",
        agent_id=to_agent,           # route to the recipient
        summary=f"Message from {from_agent} to {to_agent}",
        payload={
            "from_agent": from_agent,
            "to_agent": to_agent,
            "content": message,
        },
        correlation_id=correlation_id,
    )
    self.protocol.notify("$/remora/event", envelope.model_dump())
```

This ensures:
- `event.agent_id` = `to_agent` → panel routes to correct agent panel
- `event.event_type` = `"AgentMessageEvent"` → panel renders as message
- `event.payload.from_agent` / `event.payload.to_agent` → direction rendering works

### Fix: panel.lua side — render AgentMessageEvent from payload

When `event.event_type == "AgentMessageEvent"`, extract direction fields from `payload`:

```lua
-- panel.lua, in the event rendering section:
elseif ev.event_type == "AgentMessageEvent" then
    local from = ev.payload and ev.payload.from_agent or ev.from_agent or "?"
    local to   = ev.payload and ev.payload.to_agent   or ev.to_agent   or "?"
    local content = ev.payload and ev.payload.content or ev.content or ""
    -- render as inter-agent message
```

---

## 4. Bug 2 — Historical AgentMessageEvent Direction "unknown"

### Impact: MEDIUM — direction display wrong for historical messages

### Root cause

In `panel.lua`'s `build_lines()` function, when rendering historical `AgentMessageEvent` events:

```lua
-- WRONG (historical format has from_agent/to_agent at TOP LEVEL):
local from_a = ev.payload and ev.payload.from_agent or "unknown"
local to_a   = ev.payload and ev.payload.to_agent   or "unknown"
```

But `row_to_event_dict()` puts `from_agent`/`to_agent` at the TOP LEVEL (they are in `meta_keys`):

```lua
-- CORRECT:
local from_a = ev.from_agent or (ev.payload and ev.payload.from_agent) or "unknown"
local to_a   = ev.to_agent   or (ev.payload and ev.payload.to_agent)   or "unknown"
```

The `or` fallback handles both historical format (top-level) and live format (from payload after Bug 1 fix).

### Fix

In `panel.lua`, wherever `AgentMessageEvent` direction is read from historical events, use:

```lua
local from_a = ev.from_agent or (ev.payload and ev.payload.from_agent) or "unknown"
local to_a   = ev.to_agent   or (ev.payload and ev.payload.to_agent)   or "unknown"
```

---

## 5. Bug 3 — Duplicate User Message After Panel Refresh

### Impact: LOW — cosmetic duplicate in panel after refresh

### Root cause

When the user sends a message, `panel.lua`'s `send_message()` locally creates a `HumanChatEvent` table with `id = nil`:

```lua
-- Locally created placeholder event:
local local_event = {
    id = nil,               -- not yet stored in DB
    event_type = "HumanChatEvent",
    payload = { message = text },
    ...
}
table.insert(M._events, local_event)
```

Later, `do_fetch_agent_data()` fetches historical events from the server and merges them with local events. The dedup logic:

```lua
local server_ids = {}
for _, ev in ipairs(server_events) do
    server_ids[ev.id or ev.event_id] = true
end

for _, ev in ipairs(M._events) do
    if not server_ids[ev.id or ev.event_id] then
        table.insert(merged, ev)      -- keep local-only events
    end
end
```

Since `ev.id` is `nil` for local events, `server_ids[nil]` is always `false` (Lua tables don't store nil keys). The local placeholder is ALWAYS kept — even after the server-side event appears in the fetched history. Result: two copies of the user message.

### Fix

Assign local events a temporary placeholder ID that cannot collide with server IDs:

```lua
-- In send_message():
local local_id = "local_" .. tostring(os.time()) .. "_" .. tostring(math.random(10000))
local local_event = {
    id = local_id,
    event_type = "HumanChatEvent",
    payload = { message = text },
    ...
}
```

Then in the merge logic, local events with `local_*` IDs are always kept (server doesn't return them with that ID), but once the server event arrives with a real `id`, the duplicate check must match by content instead of ID for these local events:

```lua
-- Alternative simpler fix: clear local events after successful fetch
-- In do_fetch_agent_data() success callback:
M._local_events = {}  -- clear all local placeholders after server confirms receipt
```

The simplest fix is to clear `M._local_events` (or the local portion of `M._events`) whenever the server returns at least one new event after the user's message.

---

## 6. Verified Correct (No Changes)

These were suspected bugs but confirmed correct:

- **`ev.payload.result_summary` for ToolResultEvent** ✅
  `agent_runner.py`'s `_emit_tool_event()` adds `result_summary` to the payload dict BEFORE calling `emit_agent_event()`. The panel's access of `ev.payload.result_summary` is correct.

- **`remora.getAgentPanel` command** ✅
  Uses `workspace/executeCommand` — LSP spec compliant.

- **`$/remora/cursorMoved` cursor tracking** ✅
  `init.lua`'s `CursorHold` autocmd sends cursor position; server debounces and emits `CursorFocusEvent`.

- **`$/remora/requestInput` handler** ✅
  `init.lua` routes correctly: if panel is open for the requesting agent, focus the input window; else `vim.ui.input` fallback.

- **`$/remora/agentSelected` handler** ✅
  Logged but not used — acceptable for current implementation.

---

## 7. MockLLMClient Demo Harness (Separate)

`remora_demo/neovim/mock_llm.py` is a **completely separate standalone demo harness**. It:

- Uses a scripted `MockLLMClient` with a deterministic conversation
- Is NOT wired into or connected to the Lua plugin
- Tool names: `rewrite_self`, `message_node`, `read_node` ✅ (match production tools)
- Runs as a Python script, not as part of `remora-lsp`

No changes needed to `mock_llm.py`. It's a standalone test tool.

---

## 8. Acceptance Criteria

- [ ] Live `AgentMessageEvent` appears in panel during agent-to-agent communication
- [ ] `AgentMessageEvent` direction shows correct `from_agent`/`to_agent` in both live and historical views
- [ ] No duplicate user message after panel refresh
- [ ] All other live event types (HumanChatEvent, AgentTextResponse, ToolCallEvent, ToolResultEvent, RewriteProposalEvent) still render correctly
- [ ] `devenv shell -- tach check` passes
- [ ] Full test suite passes

## Verification

```bash
# Check that emit_agent_message_event exists and imports compile:
devenv shell -- python -c "from remora.lsp.server import RemoraLanguageServer; print('OK')"

# Confirm AgentEvent has the right fields:
devenv shell -- python -c "
from remora.core.events.agent_events import AgentEvent
e = AgentEvent(event_type='AgentMessageEvent', agent_id='x', payload={})
d = e.model_dump()
assert 'event_type' in d and 'agent_id' in d and 'payload' in d
print('AgentEvent envelope fields:', list(d.keys()))
"
```
