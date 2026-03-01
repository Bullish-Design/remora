# Remora Neovim Demo: Implementation Analysis & V3 Guide

## Executive Summary

This document provides a comprehensive analysis of the Remora Neovim demo implementation, identifies critical bugs preventing agent interactivity, and provides concrete fixes to achieve full functionality.

### Current Status: **NOT FUNCTIONAL** for agent chat/execution

**Root Causes Identified:**
1. **Agent ID mismatch** between Lua, `buffer.opened` RPC, and reconciler
2. **Missing AgentState files** when agents registered via `buffer.opened`
3. **Subscription patterns don't match** due to ID inconsistency
4. **Event routing chain broken** - triggers never reach AgentRunner

---

## Table of Contents

1. [Critical Bug Analysis](#1-critical-bug-analysis)
2. [Architecture Audit](#2-architecture-audit)
3. [Required Fixes](#3-required-fixes)
4. [Enhanced Implementation](#4-enhanced-implementation)
5. [Testing & Verification](#5-testing--verification)
6. [Future Improvements](#6-future-improvements)

---

## 1. Critical Bug Analysis

### 1.1 Agent ID Format Mismatch (CRITICAL)

There are **THREE different agent ID formats** in use across the codebase:

| Component | Format | Example |
|-----------|--------|---------|
| **Lua (navigation.lua:98)** | `{node_type}_{filename}_{line}` | `function_definition_utils_15` |
| **buffer.opened (nvim_server.py:315)** | `{node.node_type}_{file.stem}_{line}` | `function_utils_15` |
| **Reconciler (discovery.py)** | SHA256 hash (16 chars) | `a3f1b2c4d5e6f789` |

**Impact:** When Lua subscribes to `function_definition_utils_15`, but subscriptions were created for `a3f1b2c4d5e6f789`, **no events match**.

**Evidence:**

```lua
-- navigation.lua:98
agent_id = string.format("%s_%s_%d", node_type, file_name, start_line)
-- node_type = "function_definition" (full treesitter type)
```

```python
# nvim_server.py:314-315
def compute_agent_id(node: CSTNode, file_path: Path) -> str:
    return f"{node.node_type}_{file_path.stem}_{node.start_line}"
# node.node_type = "function" (shortened type from discovery.py)
```

```python
# discovery.py:42-45
def compute_node_id(file_path, name, start_line, end_line) -> str:
    content = f"{file_path}:{name}:{start_line}:{end_line}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

### 1.2 Missing AgentState Files (CRITICAL)

The `AgentRunner` requires agent state JSONL files to execute:

```python
# agent_runner.py:190-197
state_path = get_agent_state_path(self._project_root / ".remora", agent_id)
state = load_agent_state(state_path)
if state is None:
    logger.warning(f"No state found for agent {agent_id}")
    return  # SILENTLY EXITS - NO EXECUTION
```

**But `rpc_buffer_opened` does NOT create these files:**

```python
# nvim_server.py:262-291 (buffer.opened handler)
for node in nodes:
    agent_id = compute_agent_id(node, path)
    metadata = AgentMetadata(...)  # Only creates SwarmState metadata
    await swarm_state.upsert(metadata)
    await subscriptions.register_defaults(agent_id, str(path))
    # NO AgentState file created!
```

**The reconciler DOES create them:**
```python
# reconciler.py:107-115
state = AgentState(
    agent_id=node.node_id,
    node_type=node.node_type,
    ...
)
save_agent_state(get_agent_state_path(swarm_root, node.node_id), state)
```

### 1.3 Subscription Pattern Matching Fails

**Flow when user chats:**
1. User types message in Neovim
2. Lua sends `agent.chat` RPC with `agent_id = "function_definition_utils_15"`
3. Server creates `AgentMessageEvent(to_agent="function_definition_utils_15")`
4. EventStore calls `subscriptions.get_matching_agents(event)`
5. Subscription registry looks for patterns where `to_agent == "function_definition_utils_15"`
6. **No match found** - subscriptions have `to_agent = "function_utils_15"` or SHA256 hash
7. `get_matching_agents()` returns `[]`
8. Nothing added to trigger queue
9. AgentRunner receives nothing

### 1.4 Broken Data Flow Diagram

```
CURRENT (BROKEN):

Neovim                        Daemon                      AgentRunner
─────                         ──────                      ───────────

agent.chat
agent_id="func_def_utils_15" ──►  AgentMessageEvent
                                  to_agent="func_def_utils_15"
                                        │
                                        ▼
                                  subscriptions.get_matching_agents()
                                        │
                                  Subscriptions have:
                                  to_agent="func_utils_15"  (from buffer.opened)
                                  to_agent="a3f1b2...789"   (from reconciler)
                                        │
                                  NO MATCH! Returns []
                                        │
                                        ▼
                                  trigger_queue: empty
                                        │
                                        ▼                ────► run_forever()
                                                               │
                                                         Waits forever on
                                                         empty queue
```

---

## 2. Architecture Audit

### 2.1 Component Status Matrix

| Component | File | Status | Issues |
|-----------|------|--------|--------|
| **Lua - init.lua** | 42 lines | OK | None |
| **Lua - bridge.lua** | 154 lines | OK | No timeout, no reconnect |
| **Lua - navigation.lua** | 157 lines | **BUG** | Wrong agent ID format |
| **Lua - sidepanel.lua** | ~263 lines | OK | Full redraw inefficient |
| **Lua - chat.lua** | 49 lines | OK | No input validation |
| **Python - nvim_server.py** | 492 lines | **BUG** | Wrong ID, no state file |
| **Python - client_manager.py** | 107 lines | OK | Single subscription |
| **Python - agent_runner.py** | 274 lines | OK | Silent failure |
| **Python - event_store.py** | 344 lines | OK | None |
| **Python - subscriptions.py** | 277 lines | OK | None |
| **Python - swarm_state.py** | 197 lines | OK | None |
| **Python - reconciler.py** | 183 lines | OK | Uses SHA256 IDs |
| **Python - discovery.py** | 374 lines | OK | Uses SHA256 IDs |

### 2.2 Event Flow Analysis

**Correct flow should be:**

```
1. Neovim opens Python file
   └─► buffer.opened RPC
       └─► Register agents in SwarmState
       └─► Create AgentState files
       └─► Register default subscriptions

2. User moves cursor over function
   └─► Treesitter identifies node
   └─► Compute agent_id (MUST MATCH daemon)
   └─► Subscribe to events for this agent
   └─► Fetch and display agent state

3. User chats with agent
   └─► agent.chat RPC with correct agent_id
   └─► Create AgentMessageEvent
   └─► EventStore.append() → Subscription matching
   └─► Match found → trigger_queue.put()
   └─► AgentRunner picks up trigger
   └─► Load AgentState file
   └─► Execute via SwarmExecutor
   └─► Emit result events → Push to Neovim
```

### 2.3 ID Computation Decision

**Recommendation: Use the reconciler's SHA256 format everywhere.**

Reasons:
1. Most robust - includes full path, name, and range
2. Already used by reconciler which creates the AgentState files
3. Deterministic and collision-resistant
4. Works with agent bundles and workspace directories

---

## 3. Required Fixes

### 3.1 Fix Agent ID Computation (CRITICAL)

**Option A: Match Reconciler (SHA256) - RECOMMENDED**

All components must compute IDs identically:

```python
# Shared computation (add to remora/core/utils.py or discovery.py)
def compute_agent_id(file_path: str, name: str, start_line: int, end_line: int) -> str:
    """Compute deterministic agent ID from node attributes."""
    import hashlib
    content = f"{file_path}:{name}:{start_line}:{end_line}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

**Lua side (navigation.lua):**
```lua
-- Option A: Query daemon for ID
function M.get_agent_id_for_node(file_path, node)
    -- Call RPC to compute ID on server side
    -- This ensures exact match with daemon
end

-- Option B: Replicate hash in Lua (portable but more code)
local sha256 = require("sha256")  -- Need external library
local function compute_agent_id(file_path, name, start_line, end_line)
    local content = file_path .. ":" .. name .. ":" .. start_line .. ":" .. end_line
    return sha256.hash(content):sub(1, 16)
end
```

**Option B: Use Simple Format Everywhere**

Change reconciler and discovery to use simple format:
```python
def compute_agent_id(node_type: str, filename_stem: str, start_line: int) -> str:
    return f"{node_type}_{filename_stem}_{start_line}"
```

This is simpler but loses some uniqueness guarantees. Lets *not* use this.

### 3.2 Create AgentState Files in buffer.opened (CRITICAL)

```python
# nvim_server.py - Update rpc_buffer_opened

async def rpc_buffer_opened(params: dict) -> dict:
    file_path = params.get("path")
    # ... validation ...

    nodes = parse_file(path)
    swarm_root = project_root / ".remora"

    registered = []
    for node in nodes:
        agent_id = compute_agent_id(node, path)

        # 1. Create SwarmState metadata
        metadata = AgentMetadata(
            agent_id=agent_id,
            node_type=node.node_type,
            name=node.name,
            full_name=f"{path.stem}.{node.name}",
            file_path=str(path),
            parent_id=None,
            start_line=node.start_line,
            end_line=node.end_line,
            status="active",
        )
        await swarm_state.upsert(metadata)

        # 2. CREATE AGENT STATE FILE (THIS WAS MISSING!)
        state_path = get_agent_state_path(swarm_root, agent_id)
        if not state_path.exists():
            state = AgentState(
                agent_id=agent_id,
                node_type=node.node_type,
                name=node.name,
                full_name=f"{path.stem}.{node.name}",
                file_path=str(path),
                range=(node.start_line, node.end_line),
            )
            save_agent_state(state_path, state)

        # 3. Register default subscriptions
        await subscriptions.register_defaults(agent_id, str(path))

        registered.append({...})

    return {"agents": registered}
```

### 3.3 Add Logging/Debugging

```python
# agent_runner.py - Better error reporting
async def _execute_turn(self, agent_id: str, trigger_event: RemoraEvent) -> None:
    state_path = get_agent_state_path(self._project_root / ".remora", agent_id)
    logger.info(f"Looking for state at: {state_path}")

    state = load_agent_state(state_path)
    if state is None:
        logger.error(f"No state file found for agent {agent_id} at {state_path}")
        # Emit error event so user sees feedback
        if self._event_bus:
            await self._event_bus.emit(
                AgentErrorEvent(
                    graph_id=self._swarm_id,
                    agent_id=agent_id,
                    error=f"Agent state not found at {state_path}",
                )
            )
        return
    # ... rest of execution
```

```python
# event_store.py - Log subscription matching
async def append(self, graph_id: str, event) -> int:
    # ... insert event ...

    if self._trigger_queue is not None and self._subscriptions is not None:
        matching_agents = await self._subscriptions.get_matching_agents(event)
        logger.info(f"Event {type(event).__name__} matched {len(matching_agents)} agents: {matching_agents}")
        for agent_id in matching_agents:
            await self._trigger_queue.put((agent_id, event_id, event))
```

---

## 4. Enhanced Implementation

### 4.1 Unified Agent ID Module

Create `src/remora/core/agent_id.py`:

```python
"""Unified agent ID computation for all components."""

import hashlib
from pathlib import Path
from typing import NamedTuple


class AgentIdComponents(NamedTuple):
    file_path: str
    name: str
    start_line: int
    end_line: int


def compute_agent_id(
    file_path: str | Path,
    name: str,
    start_line: int,
    end_line: int,
) -> str:
    """Compute a stable, unique agent ID.

    Uses SHA256 hash of path:name:start:end for uniqueness.
    Returns first 16 hex characters.
    """
    path_str = str(Path(file_path).resolve())
    content = f"{path_str}:{name}:{start_line}:{end_line}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_simple_agent_id(
    node_type: str,
    file_stem: str,
    start_line: int,
) -> str:
    """Compute a human-readable agent ID.

    Format: {node_type}_{file_stem}_{line}
    Less unique but more readable.
    """
    return f"{node_type}_{file_stem}_{start_line}"


# For Lua compatibility: provide an RPC endpoint
async def rpc_compute_agent_id(params: dict) -> dict:
    """RPC handler to compute agent ID from node info."""
    file_path = params.get("file_path", "")
    name = params.get("name", "")
    start_line = params.get("start_line", 1)
    end_line = params.get("end_line", 1)

    agent_id = compute_agent_id(file_path, name, start_line, end_line)
    simple_id = compute_simple_agent_id(
        params.get("node_type", "unknown"),
        Path(file_path).stem,
        start_line,
    )

    return {
        "agent_id": agent_id,
        "simple_id": simple_id,
    }
```

### 4.2 Updated Navigation Module (Lua)

```lua
-- lua/remora_nvim/navigation.lua

local M = {}

M.current_agent_id = nil
M.registered_buffers = {}
M.agent_id_cache = {}  -- Cache computed IDs

function M.setup()
    vim.api.nvim_create_autocmd("CursorMoved", {
        callback = M.on_cursor_moved,
    })
    vim.api.nvim_create_autocmd("BufReadPost", {
        pattern = "*.py",
        callback = M.on_buffer_opened,
    })
    vim.api.nvim_create_autocmd("BufEnter", {
        pattern = "*.py",
        callback = M.on_buffer_entered,
    })
end

function M.on_buffer_opened(ev)
    local bufnr = vim.api.nvim_get_current_buf()
    local file_path = vim.api.nvim_buf_get_name(bufnr)

    if file_path == "" or M.registered_buffers[file_path] then
        return
    end

    M.registered_buffers[file_path] = true

    -- Notify daemon and cache the agent IDs it returns
    require("remora_nvim.bridge").notify_buffer_opened(file_path, function(result)
        if result and result.agents then
            for _, agent in ipairs(result.agents) do
                -- Cache: node_type_file_line -> actual_agent_id
                local cache_key = string.format("%s_%s_%d",
                    agent.type,
                    vim.fn.fnamemodify(file_path, ":t:r"),
                    agent.line
                )
                M.agent_id_cache[cache_key] = agent.agent_id
            end
        end
    end)
end

function M.on_buffer_entered(ev)
    -- Same as on_buffer_opened
    M.on_buffer_opened(ev)
end

function M.on_cursor_moved()
    local bufnr = vim.api.nvim_get_current_buf()
    local filetype = vim.bo[bufnr].filetype

    if filetype ~= "python" then
        return
    end

    local ok, parser = pcall(vim.treesitter.get_parser, bufnr)
    if not ok or not parser then
        return
    end

    local cursor = vim.api.nvim_win_get_cursor(0)
    local row = cursor[1] - 1
    local col = cursor[2]

    local tree = parser:parse()[1]
    if not tree then return end

    local root = tree:root()
    if not root then return end

    local node = root:named_descendant_for_range(row, col, row, col)

    local target_node = nil
    while node do
        local node_type = node:type()
        if M.is_agent_node_type(node_type) then
            target_node = node
            break
        end
        node = node:parent()
    end

    local file_path = vim.api.nvim_buf_get_name(bufnr)
    local file_name = vim.fn.fnamemodify(file_path, ":t:r")

    local node_type = "file"
    local start_line = 1
    local node_name = file_name

    if target_node then
        node_type = target_node:type()
        start_line, _ = target_node:start()
        start_line = start_line + 1
        node_name = M.get_node_name(target_node) or "unknown"
    end

    -- Compute cache key (matches what buffer.opened returns)
    local cache_key = string.format("%s_%s_%d", node_type, file_name, start_line)

    -- Look up cached agent ID, fall back to cache key
    local agent_id = M.agent_id_cache[cache_key] or cache_key

    if agent_id ~= M.current_agent_id then
        M.current_agent_id = agent_id

        require("remora_nvim.bridge").subscribe_to_agent(agent_id)
        require("remora_nvim.sidepanel").show_agent(agent_id, file_path, node_type, start_line)
    end
end

function M.get_node_name(node)
    -- Extract function/class name from treesitter node
    for child in node:iter_children() do
        if child:type() == "identifier" or child:type() == "name" then
            local bufnr = vim.api.nvim_get_current_buf()
            local start_row, start_col, end_row, end_col = child:range()
            local lines = vim.api.nvim_buf_get_text(bufnr, start_row, start_col, end_row, end_col, {})
            return lines[1]
        end
    end
    return nil
end

function M.is_agent_node_type(node_type)
    local agent_types = {
        "function_definition",
        "async_function_definition",
        "class_definition",
        "decorated_definition",
    }
    return vim.tbl_contains(agent_types, node_type)
end

function M.go_to_parent()
    -- ... existing implementation ...
end

return M
```

### 4.3 Updated Bridge with Callback Support

```lua
-- lua/remora_nvim/bridge.lua

function M.notify_buffer_opened(file_path, callback)
    M.call("buffer.opened", { path = file_path }, function(result)
        if result and result.agents then
            local count = #result.agents
            if count > 0 then
                vim.notify(
                    string.format("Remora: Registered %d agents from %s", count, vim.fn.fnamemodify(file_path, ":t")),
                    vim.log.levels.INFO
                )
            end
        elseif result and result.error then
            vim.notify("Remora: " .. result.error, vim.log.levels.WARN)
        end

        -- Call callback with result so navigation can cache IDs
        if callback then
            callback(result)
        end
    end)
end
```

### 4.4 Updated nvim_server.py

```python
# Add to imports
from remora.core.reconciler import get_agent_state_path
from remora.core.agent_state import AgentState, save as save_agent_state

# Replace compute_agent_id function
def compute_agent_id(node: CSTNode, file_path: Path) -> str:
    """Compute agent ID matching discovery.py's compute_node_id."""
    import hashlib
    # Use same format as discovery.py
    content = f"{str(file_path.resolve())}:{node.name}:{node.start_line}:{node.end_line}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# Update rpc_buffer_opened
async def rpc_buffer_opened(params: dict) -> dict:
    file_path = params.get("path")
    if not file_path:
        return {"error": "Missing path"}

    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}
    if path.suffix != ".py":
        return {"agents": [], "message": "Only Python files supported"}

    try:
        nodes = parse_file(path)
    except Exception as exc:
        logger.error("Failed to parse %s: %s", file_path, exc)
        return {"error": str(exc)}

    # Get swarm root for state files
    project_root = Path(config.project_path)
    swarm_root = project_root / ".remora"

    registered = []
    for node in nodes:
        agent_id = compute_agent_id(node, path)

        # 1. Create SwarmState metadata
        metadata = AgentMetadata(
            agent_id=agent_id,
            node_type=node.node_type,
            name=node.name,
            full_name=f"{path.stem}.{node.name}",
            file_path=str(path),
            parent_id=None,
            start_line=node.start_line,
            end_line=node.end_line,
            status="active",
        )
        await swarm_state.upsert(metadata)

        # 2. Create AgentState file if not exists
        state_path = get_agent_state_path(swarm_root, agent_id)
        if not state_path.exists():
            state = AgentState(
                agent_id=agent_id,
                node_type=node.node_type,
                name=node.name,
                full_name=f"{path.stem}.{node.name}",
                file_path=str(path),
                range=(node.start_line, node.end_line),
            )
            save_agent_state(state_path, state)
            logger.info(f"Created state file for agent {agent_id}")

        # 3. Register default subscriptions
        await subscriptions.register_defaults(agent_id, str(path))

        registered.append({
            "agent_id": agent_id,
            "name": node.name,
            "type": node.node_type,
            "line": node.start_line,
        })

    logger.info("Registered %d agents from %s", len(registered), file_path)

    return {"agents": registered}
```

### 4.5 Add RPC Method for ID Computation

```python
# nvim_server.py - Add new RPC method

async def handle_rpc_method(client: NvimClient, method: str, params: dict) -> dict:
    """Dispatch JSON-RPC requests from Neovim."""
    if method == "agent.select":
        return await rpc_agent_select(params)
    if method == "agent.subscribe":
        return await rpc_agent_subscribe(client, params)
    if method == "agent.chat":
        return await rpc_agent_chat(params)
    if method == "buffer.opened":
        return await rpc_buffer_opened(params)
    if method == "agent.get_events":
        return await rpc_get_events(params)
    if method == "agent.compute_id":  # NEW
        return await rpc_compute_agent_id(params)
    return {"error": f"Unknown method: {method}"}


async def rpc_compute_agent_id(params: dict) -> dict:
    """Compute agent ID from node info - for Lua compatibility."""
    file_path = params.get("file_path", "")
    name = params.get("name", "")
    start_line = params.get("start_line", 1)
    end_line = params.get("end_line", 1)
    node_type = params.get("node_type", "unknown")

    if not file_path:
        return {"error": "Missing file_path"}

    import hashlib
    path = Path(file_path)
    content = f"{str(path.resolve())}:{name}:{start_line}:{end_line}"
    agent_id = hashlib.sha256(content.encode()).hexdigest()[:16]

    return {
        "agent_id": agent_id,
        "simple_id": f"{node_type}_{path.stem}_{start_line}",
    }
```

---

## 5. Testing & Verification

### 5.1 Verification Checklist

After implementing fixes, verify each step:

- [ ] **Start daemon**: `uv run python src/remora/demo/nvim_server.py`
  - Check logs show "AgentRunner started"
  - Check "Neovim RPC server listening"

- [ ] **Connect Neovim**:
  ```vim
  :set runtimepath+=/path/to/remora
  :lua require('remora_nvim').setup()
  ```
  - Should see "Remora: Connected!"

- [ ] **Open Python file**:
  ```vim
  :e src/remora/core/swarm_state.py
  ```
  - Should see "Remora: Registered N agents from swarm_state.py"
  - Check daemon logs for agent IDs registered

- [ ] **Verify state files created**:
  ```bash
  ls -la .remora/agents/
  # Should see directories like a3/, b2/, etc.
  # Each containing state.jsonl
  ```

- [ ] **Check cursor tracking**:
  - Move cursor into a function
  - Open sidepanel `:RemoraToggle`
  - Agent info should display

- [ ] **Send chat message**:
  ```vim
  :RemoraChat
  > Hello agent
  ```
  - Check daemon logs: "Event AgentMessageEvent matched N agents"
  - Check "Running agent {id} with trigger AgentMessageEvent"
  - Sidepanel should show events streaming

### 5.2 Debug Logging Points

Add these log statements for debugging:

```python
# event_store.py append():
logger.info(f"Appending event {type(event).__name__} to_agent={getattr(event, 'to_agent', None)}")
logger.info(f"Matching agents: {matching_agents}")

# subscriptions.py get_matching_agents():
logger.debug(f"Checking {len(rows)} subscriptions for event {type(event).__name__}")
for row in rows:
    pattern = SubscriptionPattern(**json.loads(row["pattern_json"]))
    if pattern.matches(event):
        logger.debug(f"  Match: agent={row['agent_id']} pattern={row['pattern_json']}")

# agent_runner.py run_forever():
async for agent_id, event_id, event in self._event_store.get_triggers():
    logger.info(f"Trigger received: agent={agent_id} event_type={type(event).__name__}")
```

### 5.3 Manual Testing Script

```python
#!/usr/bin/env python3
"""Test the agent chat flow manually."""

import asyncio
import json
from pathlib import Path

async def test_chat():
    reader, writer = await asyncio.open_unix_connection("/run/user/1000/remora.sock")

    # 1. Register a file
    msg = {"jsonrpc": "2.0", "id": 1, "method": "buffer.opened", "params": {"path": "/path/to/test.py"}}
    writer.write(json.dumps(msg).encode() + b"\n")
    await writer.drain()

    response = await reader.readline()
    result = json.loads(response)
    print(f"Registered agents: {result}")

    # 2. Get first agent ID
    if result.get("result", {}).get("agents"):
        agent_id = result["result"]["agents"][0]["agent_id"]
        print(f"Using agent: {agent_id}")

        # 3. Send chat message
        msg = {"jsonrpc": "2.0", "id": 2, "method": "agent.chat", "params": {"agent_id": agent_id, "message": "Hello!"}}
        writer.write(json.dumps(msg).encode() + b"\n")
        await writer.drain()

        response = await reader.readline()
        print(f"Chat response: {json.loads(response)}")

        # 4. Wait for push notifications
        print("Waiting for events...")
        for _ in range(10):
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=2.0)
                print(f"Event: {line.decode()}")
            except asyncio.TimeoutError:
                break

    writer.close()
    await writer.wait_closed()

asyncio.run(test_chat())
```

---

## 6. Future Improvements

### 6.1 High Priority

1. **Socket Reconnection**
   - Auto-reconnect on disconnect
   - Exponential backoff
   - Connection state indicator in sidepanel

2. **RPC Timeout**
   - Add timeout to pending callbacks
   - Clean up stale callbacks

3. **Error Feedback Loop**
   - Show AgentErrorEvent in sidepanel prominently
   - Add retry button for failed executions

### 6.2 Medium Priority

4. **Incremental Sidepanel Updates**
   - Only update changed sections
   - Debounce rapid events

5. **Multi-Agent Subscription**
   - Allow watching multiple agents
   - Parent/child agent events

6. **Input Validation**
   - Validate chat messages
   - Length limits
   - Rate limiting

### 6.3 Nice-to-Have

7. **Event Replay**
   - Show historical events on agent select
   - Pagination for long event lists

8. **Agent State Viewer**
   - View/edit AgentState in sidepanel
   - Show chat history

9. **Metrics Dashboard**
   - Event throughput
   - Agent execution times
   - Error rates

---

## Summary of Required Changes

| File | Change | Priority |
|------|--------|----------|
| `src/remora/demo/nvim_server.py` | Fix `compute_agent_id` to match discovery.py | CRITICAL |
| `src/remora/demo/nvim_server.py` | Create AgentState files in `buffer.opened` | CRITICAL |
| `lua/remora_nvim/navigation.lua` | Cache agent IDs from daemon response | CRITICAL |
| `lua/remora_nvim/bridge.lua` | Add callback support to `notify_buffer_opened` | CRITICAL |
| `src/remora/core/agent_runner.py` | Better error logging for missing state | HIGH |
| `src/remora/core/event_store.py` | Add subscription matching debug logs | HIGH |

**Estimated effort:** 2-4 hours for critical fixes, +2 hours for high priority improvements.

---

*Document version: 3.0*
*Status: Analysis Complete - Implementation Pending*
*Date: 2026-02-28*
