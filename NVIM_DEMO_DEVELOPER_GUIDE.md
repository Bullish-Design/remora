# Remora Neovim + Web UI Demo: Developer Implementation Guide

This guide provides step-by-step instructions for a junior developer to implement the MVP of the Remora Neovim plugin and its companion real-time Datastar Web UI. 

## 1. Project Context & MVP Scope

Our goal is to build a "wow" factor demo showcasing the Remora agent swarm. 

**The MVP Scope:**
1.  **Python Daemon:** A single Python process that hosts a FastAPI web server (for the Web UI) and a Unix socket server (for the Neovim JSON-RPC plugin).
2.  **Web UI:** A real-time nested filesystem tree built with HTML and the Datastar framework. It will display the agents and their logs.
3.  **Neovim Plugin:** A Lua plugin that tracks the cursor using `treesitter`. When the cursor enters an "agent" node (e.g., a python function), it sends an RPC request to the daemon to fetch the agent's state and displays it in a sidepanel.
4.  **LLMs:** Use vLLM running at `http://remora-server:8000/v1`.

---

## 2. Directory Structure Setup

First, set up the required directories and empty files in the `remora` repository root:

```bash
mkdir -p lua/remora_nvim
mkdir -p plugin
mkdir -p src/remora/demo/templates
touch lua/remora_nvim/init.lua
touch lua/remora_nvim/bridge.lua
touch lua/remora_nvim/navigation.lua
touch lua/remora_nvim/sidepanel.lua
touch plugin/remora_nvim.lua
touch src/remora/demo/nvim_server.py
touch src/remora/demo/templates/index.html
```

---

## 3. Step-by-Step Implementation

### Step 1: The Neovim Plugin Skeleton

**File: `plugin/remora_nvim.lua`**
This is the entry point that Neovim executes when the plugin is loaded.
```lua
-- Only load once
if vim.g.loaded_remora_nvim then
  return
end
vim.g.loaded_remora_nvim = true

-- Command to manually toggle the sidepanel
vim.api.nvim_create_user_command("RemoraToggle", function()
  require("remora_nvim.sidepanel").toggle()
end, {})

-- Command to manually connect
vim.api.nvim_create_user_command("RemoraConnect", function()
  require("remora_nvim").setup({})
end, {})
```

**File: `lua/remora_nvim/init.lua`**
```lua
local M = {}

function M.setup(config)
  config = config or {}
  local socket_path = config.socket or "/tmp/remora.sock"
  
  -- 1. Initialize the UI
  require("remora_nvim.sidepanel").setup()
  
  -- 2. Connect to the Daemon
  require("remora_nvim.bridge").setup(socket_path)
  
  -- 3. Start watching the cursor
  require("remora_nvim.navigation").setup()
end

return M
```

### Step 2: Neovim JSON-RPC Bridge

**File: `lua/remora_nvim/bridge.lua`**
This handles the raw TCP/Unix socket connection to the Python daemon.

```lua
local M = {}
M.client = nil
M.callbacks = {}
M.next_id = 1

function M.setup(socket_path)
  M.client = vim.loop.new_pipe(false)
  M.client:connect(socket_path, function(err)
    if err then
      vim.schedule(function()
        vim.notify("Remora Bridge: Failed to connect to " .. socket_path .. ": " .. err, vim.log.levels.ERROR)
      end)
      return
    end

    M.client:read_start(function(err, data)
      if err then return end
      if data then M.handle_response(data) end
    end)

    vim.schedule(function()
      vim.notify("Remora Bridge: Connected!", vim.log.levels.INFO)
    end)
  end)
end

function M.call(method, params, callback)
  if not M.client then return end
  local id = M.next_id
  M.next_id = M.next_id + 1

  local msg = vim.fn.json_encode({
    jsonrpc = "2.0",
    id = id,
    method = method,
    params = params,
  })

  if callback then
    M.callbacks[id] = callback
  end

  M.client:write(msg .. "\n")
end

function M.handle_response(data)
  for line in data:gmatch("[^\n]+") do
    local ok, msg = pcall(vim.fn.json_decode, line)
    if ok and msg.id and M.callbacks[msg.id] then
      vim.schedule(function()
        M.callbacks[msg.id](msg.result)
        M.callbacks[msg.id] = nil
      end)
    end
  end
end

return M
```

### Step 3: Treesitter Cursor Tracking

**File: `lua/remora_nvim/navigation.lua`**
Tracks cursor movement and figures out which agent the user is looking at.

```lua
local M = {}
M.current_agent_id = nil

function M.setup()
  vim.api.nvim_create_autocmd("CursorMoved", {
    callback = M.on_cursor_moved,
  })
end

function M.on_cursor_moved()
  local bufnr = vim.api.nvim_get_current_buf()
  local filetype = vim.api.nvim_buf_get_option(bufnr, 'filetype')
  -- Only attempt to parse supported languages to avoid "no parser" errors
  if filetype == '' or filetype == 'notify' or filetype == 'remora' then
      return
  end

  -- Use pcall because get_parser throws an error for unsupported filetypes
  local ok, parser = pcall(vim.treesitter.get_parser, bufnr)
  if not ok or not parser then return end

  -- A simple way to get the node at the cursor
  local win = vim.api.nvim_get_current_win()
  local cursor = vim.api.nvim_win_get_cursor(win)
  local row = cursor[1] - 1
  local col = cursor[2]
  
  local root_tree = parser:parse()[1]
  if not root_tree then return end
  local root = root_tree:root()
  if not root then return end
  local node = root:named_descendant_for_range(row, col, row, col)
  
  -- Walk up to find a class or function
  while node do
    local type = node:type()
    if type == "function_definition" or type == "class_definition" or type == "async_function_definition" then
        break
    end
    node = node:parent()
  end
  
  if not node then return end

  -- Create a stable ID. Must match how python generates IDs
  local start_row, _ = node:start()
  local file_path = vim.api.nvim_buf_get_name(bufnr)
  local file_name = vim.fn.fnamemodify(file_path, ":t:r")
  
  -- e.g. "function_definition_utils_15"
  local agent_id = string.format("%s_%s_%d", node:type(), file_name, start_row + 1)
  
  if agent_id ~= M.current_agent_id then
    M.current_agent_id = agent_id
    require("remora_nvim.sidepanel").show_agent(agent_id, file_path, node:type())
  end
end

return M
```

### Step 4: Sidepanel Rendering

**File: `lua/remora_nvim/sidepanel.lua`**
Displays the data fetched via RPC.

```lua
local M = {}
M.win = nil
M.buf = nil

function M.setup()
  M.buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_option(M.buf, "buftype", "nofile")
  vim.api.nvim_buf_set_option(M.buf, "filetype", "remora")
end

function M.toggle()
  if M.win and vim.api.nvim_win_is_valid(M.win) then
    vim.api.nvim_win_close(M.win, true)
    M.win = nil
  else
    vim.cmd("vsplit")
    vim.cmd("wincmd L")
    M.win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(M.win, M.buf)
    vim.api.nvim_win_set_width(M.win, 40)
    vim.api.nvim_win_set_option(M.win, "number", false)
    vim.api.nvim_win_set_option(M.win, "signcolumn", "no")
    vim.cmd("wincmd p") -- cursor back to main window
  end
end

function M.show_agent(agent_id, filepath, nodetype)
  -- Ask python for the state
  require("remora_nvim.bridge").call("agent.select", { id = agent_id, file = filepath }, function(state)
    if not M.win or not vim.api.nvim_win_is_valid(M.win) then return end
    
    local lines = {}
    table.insert(lines, "╭─────────────────────────────────╮")
    table.insert(lines, string.format("│ Agent ID: %-21s│", agent_id:sub(1, 21)))
    table.insert(lines, string.format("│ Type: %-25s│", nodetype))
    
    local status = state and state.status or "DORMANT"
    table.insert(lines, string.format("│ Status: %-23s│", status))
    table.insert(lines, "╰─────────────────────────────────╯")
    table.insert(lines, "")
    
    table.insert(lines, "RECENT TRIGGERS")
    table.insert(lines, "─────────────────────────────────")
    if state and state.triggers and #state.triggers > 0 then
        for _, t in ipairs(state.triggers) do
            table.insert(lines, "├─ " .. t)
        end
    else
        table.insert(lines, "  (none)")
    end
    
    vim.api.nvim_buf_set_lines(M.buf, 0, -1, false, lines)
  end)
end

return M
```

### Step 5: The Python Daemon (FastAPI + JSON-RPC + Datastar)

**File: `src/remora/demo/nvim_server.py`**
This script boots a FastAPI server. It mounts a Unix socket background task for Neovim and serves Datastar SSE streams for the Web UI. It is fully integrated with Remora's `SwarmState` and `EventStore`.

```python
import asyncio
import json
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from datastar_py.sse import ServerSentEventGenerator
import uvicorn

from remora.core.config import load_config
from remora.core.swarm_state import SwarmState
from remora.core.event_store import EventStore
from remora.core.event_bus import EventBus
from remora.core.events import RemoraEvent

# Initialize Core Remora Services
config = load_config()
db_path = Path(config.swarm_root) / config.swarm_id / "workspace.db"
swarm_state = SwarmState(db_path)
event_bus = EventBus()
event_store = EventStore(db_path, event_bus=event_bus)

app = FastAPI(title="Remora Swarm Dashboard")
templates = Jinja2Templates(directory="src/remora/demo/templates")
SOCKET_PATH = config.nvim_socket or "/tmp/remora.sock"

# ---- Neovim RPC Server (Unix Socket) ----
async def handle_nvim_client(reader, writer):
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            
            request = json.loads(line.decode())
            method = request.get("method")
            params = request.get("params", {})
            msg_id = request.get("id")
            
            if method == "agent.select":
                agent_id = params.get("id")
                
                # Fetch Real State from Remora SwarmState
                agent_meta = await swarm_state.get_agent(agent_id)
                status = agent_meta.status if agent_meta else "NOT_FOUND"
                
                # We could fetch real triggers by querying the EventStore in a production app
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "status": status,
                        "triggers": [] # Keep MVP simple
                    }
                }
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()
    except Exception as e:
        print(f"RPC Error: {e}")
    finally:
        writer.close()

async def start_rpc_server():
    Path(SOCKET_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(SOCKET_PATH).unlink(missing_ok=True)
    server = await asyncio.start_unix_server(handle_nvim_client, path=SOCKET_PATH)
    async with server:
        await server.serve_forever()

@app.on_event("startup")
async def startup_event():
    # Initialize Databases
    await swarm_state.initialize()
    await event_store.initialize()
    
    # Start Neovim tracking socket
    asyncio.create_task(start_rpc_server())

# ---- Datastar Web UI Server ----

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    # Pass initial state for the tree. In reality, read from actual projects.
    tree_data = [
        {"name": "src", "type": "dir", "children": [
            {"name": "utils.py", "type": "file", "agents": [
                {"id": "func_format_date_15", "name": "format_date", "status": "DORMANT"}
            ]}
        ]}
    ]
    return templates.TemplateResponse("index.html", {"request": request, "tree": tree_data})

@app.get("/stream-events")
async def stream_events(request: Request):
    """Datastar SSE endpoint for real-time updates."""
    async def sse_generator():
        # Yield the initial connection message
        yield ServerSentEventGenerator.patch_elements(
            '<div id="logs" data-prepend><li>Connected to Swarm EventBus...</li></div>'
        )
        
        # Subscribe to EventBus to receive all RemoraEvents asynchronously
        queue = asyncio.Queue()
        
        async def event_handler(event: RemoraEvent):
            await queue.put(event)
            
        event_bus.subscribe_all(event_handler)
        
        try:
            while True:
                # Wait for next event from Swarm
                event = await queue.get()
                
                # Format the log line based on the event type
                event_type = type(event).__name__
                agent_id = getattr(event, "agent_id", getattr(event, "to_agent", getattr(event, "from_agent", "System")))
                
                html_fragment = f'<div id="logs" data-prepend><li>[{event_type}] {agent_id}</li></div>'
                
                # Datastar merge_fragments tells the frontend to update specific HTML fragments
                yield ServerSentEventGenerator.patch_elements(
                    html_fragment
                )
        except asyncio.CancelledError:
             event_bus.unsubscribe_all(event_handler)
             
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(sse_generator(), media_type="text/event-stream", headers=headers)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

### Step 6: Datastar HTML Template

**File: `src/remora/demo/templates/index.html`**
This uses Datastar's custom data attributes for reactivity and SSE processing.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Remora Swarm Dashboard</title>
    <script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-beta.1/bundles/datastar.js"></script>
    <style>
        body { font-family: monospace; background: #1e1e1e; color: #d4d4d4; display: flex; height: 100vh; margin: 0; }
        .sidebar { width: 300px; border-right: 1px solid #333; padding: 1rem; overflow-y: auto; }
        .main { flex: 1; padding: 1rem; display: flex; flex-direction: column; }
        .logs { flex: 1; background: #000; border: 1px solid #333; overflow-y: auto; padding: 1rem; }
        ul { list-style: none; padding-left: 1rem; }
        .agent-node { color: #4CAF50; cursor: pointer; }
        .agent-node:hover { text-decoration: underline; }
    </style>
</head>
<body data-on-load="@get('/stream-events')">

    <div class="sidebar">
        <h3>Swarm Tree</h3>
        <ul id="agent-tree">
            <!-- Example hardcoded tree, ideally rendered by Jinja2 -->
            <li>📁 src
                <ul>
                    <li>📄 utils.py
                        <ul>
                            <li class="agent-node" id="agent-func_format_date_15">
                                [DORMANT] format_date (Function)
                            </li>
                        </ul>
                    </li>
                </ul>
            </li>
        </ul>
    </div>

    <div class="main">
        <h3>Live Swarm Logs</h3>
        <div class="logs">
            <ul id="logs">
                <!-- Logs prepend here via SSE -->
            </ul>
        </div>
    </div>

</body>
</html>
```

---

## 4. Running the Demo

1. **Start the vLLM Server:**
   Ensure vLLM is running locally or remotely at the configured endpoint.
   ```bash
   python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen3-4B --port 8000
   ```

2. **Start the Remora Daemon & Web Server:**
   ```bash
   uv run python src/remora/demo/nvim_server.py
   ```

3. **Open the Web UI:**
   Navigate to `http://localhost:8080` to view the Datastar UI.

4. **Connect Neovim:**
   Open a Python file in Neovim.
   Run the setup command:
   ```vim
   :lua require('remora_nvim').setup({})
   :source plugin/remora_nvim.lua
   :RemoraToggle
   ```
   Move your cursor around Python functions/classes and observe the right-hand panel updating via JSON-RPC.

## 5. End-to-End Execution and Testing

To verify this implementation end-to-end, execute a real action in Remora using a separate python script and observe the UI and sidepanel respond dynamically.

**1. Create a Test Script (`demo-trigger.py`)**

Create a short script to manually inject an event into the running event bus so that the Datastar web UI renders the log:

```python
import asyncio
from pathlib import Path
from remora.core.config import load_config
from remora.core.events import ManualTriggerEvent
from remora.core.event_store import EventStore
from remora.core.event_bus import EventBus
from remora.core.swarm_state import SwarmState, AgentMetadata

async def inject_event():
    config = load_config()
    db_path = Path(config.swarm_root) / config.swarm_id / "workspace.db"
    
    # 1. Connect to same DB
    event_bus = EventBus()
    event_store = EventStore(db_path, event_bus=event_bus)
    await event_store.initialize()
    
    swarm_state = SwarmState(db_path)
    await swarm_state.initialize()
    
    # 2. Add a mock agent so Neovim actually finds it when you hover
    await swarm_state.upsert(AgentMetadata(
        agent_id="function_definition_utils_15",
        node_type="function_definition",
        name="format_date",
        full_name="src.utils.format_date",
        file_path="src/utils.py",
        start_line=15,
        end_line=25,
        status="ACTIVE"
    ))
    
    # 3. Fire a manual trigger at the new agent
    event = ManualTriggerEvent(
        to_agent="function_definition_utils_15",
        reason="Testing End to End integration",
    )
    
    # Writing to the EventStore will broadcast to the EventBus
    await event_store.append("demo_graph", event)
    
    print("Test event injected. Check localhost dashboard!")

if __name__ == "__main__":
    asyncio.run(inject_event())
```

**2. Verify The Output**

1. Ensure the web server is running.
2. Open `http://localhost:8080`. You should see `Connected to Swarm EventBus...` in the logs.
3. Open a neovim pane. When you move the cursor into the mock `utils.py` bounds created in step 1, the `RemoraToggle` side panel should accurately query Python over the RPC socket and return `ACTIVE` via finding the ID in the SQLite database created in `SwarmState`.
4. Run the script: `python demo-trigger.py`.
5. Return to the browser. Thanks to Datastar's SSE streaming hooked into Remora's `EventBus`, the web UI logs list will instantly append: `[ManualTriggerEvent] function_definition_utils_15`.

You have now proven real-time observability across the core Remora database, a Neovim Editor instance, and a live web dashboard.
