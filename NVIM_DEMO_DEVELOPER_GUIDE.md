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
  local parser = vim.treesitter.get_parser(bufnr)
  if not parser then return end

  -- A simple way to get the node at the cursor
  local win = vim.api.nvim_get_current_win()
  local cursor = vim.api.nvim_win_get_cursor(win)
  local row = cursor[1] - 1
  local col = cursor[2]
  
  local root_tree = parser:parse()[1]
  local root = root_tree:root()
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
This script boots a FastAPI server. It mounts a Unix socket background task for Neovim and serves Datastar SSE streams for the Web UI.

```python
import asyncio
import json
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datastar_py.sse import ServerSentEventGenerator
import uvicorn

app = FastAPI(title="Remora Swarm Dashboard")
templates = Jinja2Templates(directory="src/remora/demo/templates")
SOCKET_PATH = "/tmp/remora.sock"

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
                # Mock response - In full implementation, fetch from SwarmState
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "status": "DORMANT",
                        "triggers": ["FileSavedEvent (2m ago)"]
                    }
                }
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()
    except Exception as e:
        print(f"RPC Error: {e}")
    finally:
        writer.close()

async def start_rpc_server():
    Path(SOCKET_PATH).unlink(missing_ok=True)
    server = await asyncio.start_unix_server(handle_nvim_client, path=SOCKET_PATH)
    async with server:
        await server.serve_forever()

@app.on_event("startup")
async def startup_event():
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
        yield ServerSentEventGenerator.merge_fragments(
            fragments='<div id="logs" data-prepend><li>Connected to Swarm...</li></div>'
        )
        
        while True:
            await asyncio.sleep(2)
            # In MVP, simulate events. In full app, subscribe to EventStore.
            yield ServerSentEventGenerator.merge_fragments(
                fragments='<div id="logs" data-prepend><li>[Ping] Swarm idle...</li></div>'
            )
            
    return ServerSentEventGenerator(sse_generator())

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
   :RemoraToggle
   ```
   Move your cursor around Python functions/classes and observe the right-hand panel updating via JSON-RPC.

## 5. Connecting the Plumbings (Next Steps for the Junior Dev)

The above implements the bare minimum plumbing:
*   [x] Neovim Lua Cursor Tracking -> JSON-RPC -> Python Daemon
*   [x] Python Daemon -> Datastar SSE -> HTML UI
*   [x] Tree visualization

To fully realize the MVP, connect the `handle_nvim_client` inside `nvim_server.py` directly to the `remora` package's `SwarmState` to return real agent statuses instead of the mock dict, and wrap the `stream_events` generator around `EventStore.event_bus.subscribe_all()`.
