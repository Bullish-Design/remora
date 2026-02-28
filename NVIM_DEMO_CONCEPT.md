# Remora.nvim - CST Agent Swarm Neovim Plugin

## Executive Summary

**Remora.nvim** transforms Neovim into an agent-native IDE where every code construct (file, function, class, import) is an autonomous agent. The editor becomes the swarm visualization - navigating treesitter objects IS navigating agents. A sidepanel reveals the current agent's state, subscriptions, and chat interface.

This design is built on the **reactive swarm architecture**:
- Agents are dormant files (`state.jsonl` + `workspace.db`)
- Event-driven via SubscriptionRegistry
- Agents trigger immediately when subscribed events arrive
- Neovim subscribes to swarm events for live updates

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ remora.nvim                                                                  │
├──────────────────────────────────────────┬──────────────────────────────────┤
│                                          │  Agent: format_date              │
│  def format_date(dt: datetime) -> str:   │  Type: function                  │
│      """Format datetime for display."""  │  Status: DORMANT                 │
│  ┌─────────────────────────────────────┐ │                                  │
│  │    if dt is None:                   │ │  ─────────────────────────────── │
│  │        return "N/A"                 │ │  SUBSCRIPTIONS                   │
│  │    return dt.strftime("%Y-%m-%d")   │ │  ├─ to_agent: self (direct msg)  │
│  └─────────────────────────────────────┘ │  └─ path: utils/dates.py         │
│                                          │                                  │
│  def parse_date(s: str) -> datetime:     │  RECENT TRIGGERS (2)             │
│      """Parse date from string."""       │  ├─ test_agent: "add edge case"  │
│      return datetime.strptime(...)       │  └─ linter: "line too long"      │
│                                          │                                  │
│                                          │  CHAT                            │
│                                          │  ┌──────────────────────────────┐│
│                                          │  │ > Add timezone support       ││
│                                          │  │                              ││
│                                          │  │ I'll need to import pytz.    ││
│                                          │  │ Sending request to parent... ││
│                                          │  └──────────────────────────────┘│
│                                          │                                  │
│                                          │  [Chat] [Trigger] [Subscriptions]│
└──────────────────────────────────────────┴──────────────────────────────────┘
```

---

## Part 1: Core Concepts

### 1.1 Editor-as-Swarm-Visualization

The code itself IS the visualization. Each syntactic construct is an agent, and navigating code is navigating agents.

| Traditional | Remora.nvim |
|------------|-------------|
| Graph view with agent nodes | Code view with agent highlights |
| Click node to select agent | Navigate treesitter object to select agent |
| Separate agent inspector | Sidepanel reveals current agent |
| External event stream | Inline live indicators |

### 1.2 Navigation-as-Selection

Using [nvim-treesitter-textobjects](https://github.com/nvim-treesitter/nvim-treesitter-textobjects), cursor movement through code structures selects agents:

```
Keybindings (example):
  ]f  → Next function (select function agent)
  [f  → Previous function
  ]c  → Next class (select class agent)
  [[  → Parent node (select parent agent)
  ]]  → First child (select child agent)
```

When the cursor enters a treesitter node, that node's agent is selected and the sidepanel updates to show its state.

### 1.3 Reactive Event Model

The swarm is fully reactive - Neovim participates as both event source and subscriber.

```
┌─────────────────────────────────────────────────────────────────┐
│               NEOVIM IN THE REACTIVE SWARM                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  NEOVIM AS EVENT SOURCE                                          │
│  ──────────────────────                                          │
│  • User saves buffer → FileSavedEvent                            │
│  • User chats with agent → UserChatEvent                         │
│  • User triggers agent → ManualTriggerEvent                      │
│                                                                  │
│  NEOVIM AS SUBSCRIBER                                            │
│  ────────────────────                                            │
│  • Subscribes to: AgentTurnComplete, ContentChanged              │
│  • Daemon pushes events via RPC notification                     │
│  • UI updates immediately                                        │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    FLOW                                  │    │
│  │                                                          │    │
│  │  Neovim ──event──► EventStore ──match──► Subscriptions   │    │
│  │                         │                     │          │    │
│  │                         ▼                     ▼          │    │
│  │                   Persist event        Trigger agents    │    │
│  │                         │                     │          │    │
│  │                         ▼                     ▼          │    │
│  │  Neovim ◄──notify── EventBus ◄──emit── AgentRunner      │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.4 Agent State Display

The sidepanel shows agent state, subscriptions, and recent triggers:

```
╭─────────────────────────────────╮
│ Agent: format_date              │
│ Type: function                  │
│ File: src/utils.py:15-25        │
│ Status: DORMANT                 │
│ Last Run: 2 min ago             │
╰─────────────────────────────────╯

SUBSCRIPTIONS (2)
─────────────────────────────────
├─ [default] to_agent: self
│  "Direct messages to me"
└─ [default] path: src/utils.py
   "Changes to my source file"

RECENT TRIGGERS (2)
─────────────────────────────────
├─ [2m ago] test_format_date
│  AgentMessage: "Function sig
│   changed, update test cases"
│
└─ [5m ago] linter_agent
   AgentMessage: "Line 18 > 88"

CONNECTIONS (learned)
─────────────────────────────────
├─ parent → file_utils_py
├─ test → test_format_date
└─ User → class_User (models.py)

CHAT HISTORY
─────────────────────────────────
> Add timezone support
< I'll need pytz. Sending request
  to parent for import...

[c]hat  [t]rigger  [s]ubscriptions
```

---

## Part 2: Architecture

### 2.1 System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Neovim                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         remora.nvim (Lua)                            │    │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────────────┐   │    │
│  │  │ Navigation    │  │ Sidepanel     │  │ Buffer Sync           │   │    │
│  │  │ (treesitter)  │  │ (agent UI)    │  │ (event emission)      │   │    │
│  │  └───────┬───────┘  └───────┬───────┘  └───────────┬───────────┘   │    │
│  │          │                  │                      │               │    │
│  │  ┌───────┴──────────────────┴──────────────────────┴───────────┐   │    │
│  │  │                    Bridge (JSON-RPC over socket)             │   │    │
│  │  │  • Sends events to daemon                                    │   │    │
│  │  │  • Receives notifications (subscribed events)                │   │    │
│  │  └──────────────────────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                         │                                    │
│                                         │ Unix Socket / TCP                  │
│                                         ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                       Remora Daemon (Python)                         │    │
│  │  ┌──────────────────┐  ┌───────────────┐  ┌───────────────────┐    │    │
│  │  │ SubscriptionReg  │  │ EventStore    │  │ AgentRunner       │    │    │
│  │  │ (pattern match)  │  │ (message bus) │  │ (reactive turns)  │    │    │
│  │  └──────────────────┘  └───────────────┘  └───────────────────┘    │    │
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────────────┐  │    │
│  │  │ SwarmState    │  │ Discovery     │  │ NvimSubscriber       │  │    │
│  │  │ (agent registry)│ │ (tree-sitter) │  │ (push to Neovim)     │  │    │
│  │  └───────────────┘  └───────────────┘  └───────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                         │                                    │
│                                         │ HTTP (OpenAI-compatible)           │
│                                         ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         LLM Server (vLLM)                            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Breakdown

#### Neovim Plugin (Lua)

| Component | Responsibility |
|-----------|----------------|
| **Navigation Module** | Treesitter object navigation, agent ID computation |
| **Sidepanel** | Agent details, subscriptions, triggers, chat interface |
| **Buffer Sync** | Emit FileSavedEvent on save |
| **Bridge** | JSON-RPC client, handle incoming notifications |

#### Remora Daemon (Python)

| Component | Responsibility |
|-----------|----------------|
| **SubscriptionRegistry** | Pattern matching, trigger queuing |
| **EventStore** | Event persistence, subscription integration |
| **AgentRunner** | Reactive turn execution |
| **NvimSubscriber** | Push events to connected Neovim clients |

### 2.3 Communication Protocol

```
┌─────────────────────────────────────────────────────────────────┐
│                    RPC Protocol (JSON-RPC 2.0)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Neovim → Daemon (Events/Requests)                              │
│  ─────────────────────────────────                              │
│  swarm.emit(event)           → Emit event into swarm            │
│  agent.select(node_id)       → Get agent state for display      │
│  agent.chat(node_id, msg)    → Emit UserChatEvent, run turn     │
│  agent.subscribe(pattern)    → Add custom subscription          │
│  agent.get_subscriptions()   → List agent's subscriptions       │
│                                                                  │
│  Daemon → Neovim (Pushed Notifications)                         │
│  ──────────────────────────────────────                         │
│  event.triggered(agent_id, event)   → Agent was triggered       │
│  event.turn_complete(agent_id, result) → Turn finished          │
│  event.content_changed(path, diff)  → Code was modified         │
│  event.subscribed(event)            → Event you subscribed to   │
│                                                                  │
│  Neovim's Implicit Subscription:                                │
│  ───────────────────────────────                                │
│  On connect, Neovim subscribes to:                              │
│  • AgentTurnComplete (all)                                      │
│  • ContentChangedEvent (all)                                    │
│  • AgentMessageEvent (to currently selected agent)              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 3: Neovim Plugin Design

### 3.1 Plugin Structure

```
lua/remora/
├── init.lua              # Plugin entry point, setup()
├── config.lua            # User configuration
├── navigation.lua        # Treesitter navigation, agent ID computation
├── sidepanel.lua         # Agent UI panel (state, subscriptions, triggers)
├── chat.lua              # Chat interface within sidepanel
├── indicators.lua        # Inline indicators (trigger badges)
├── bridge.lua            # JSON-RPC client + notification handler
├── buffer.lua            # Buffer change tracking, event emission
└── health.lua            # :checkhealth support
```

### 3.2 Core Modules

#### Navigation (`navigation.lua`)

```lua
local M = {}

-- Compute agent ID from treesitter node (matches daemon's ID generation)
function M.compute_agent_id(node, bufnr)
  local file_path = vim.api.nvim_buf_get_name(bufnr)
  local node_type = node:type()
  local start_row, start_col = node:start()

  -- Extract name if available
  local name = M.extract_node_name(node)

  -- ID format: type_name_file_line (must match daemon)
  return string.format("%s_%s_%s_%d",
    node_type,
    name or "anonymous",
    vim.fn.fnamemodify(file_path, ":t:r"),
    start_row + 1
  )
end

-- Find the "interesting" node at cursor (function, class, etc.)
function M.get_agent_node_at_cursor()
  local ts_utils = require("nvim-treesitter.ts_utils")
  local node = ts_utils.get_node_at_cursor()

  while node do
    if M.is_agent_node_type(node:type()) then
      return node
    end
    node = node:parent()
  end
  return nil
end

function M.is_agent_node_type(node_type)
  local agent_types = {
    "function_definition", "class_definition", "method_definition",
    "import_statement", "import_from_statement", "module",
    "decorated_definition", "async_function_definition",
  }
  return vim.tbl_contains(agent_types, node_type)
end

-- Called on cursor move - update sidepanel if agent changed
function M.on_cursor_moved()
  local node = M.get_agent_node_at_cursor()
  if not node then
    return
  end

  local agent_id = M.compute_agent_id(node, 0)
  if agent_id ~= M.current_agent_id then
    M.current_agent_id = agent_id
    require("remora.sidepanel").show_agent(agent_id)
    -- Update subscription to this agent's events
    require("remora.bridge").subscribe_to_agent(agent_id)
  end
end

function M.setup()
  vim.api.nvim_create_autocmd("CursorMoved", {
    callback = M.on_cursor_moved,
  })
end

return M
```

#### Sidepanel (`sidepanel.lua`)

```lua
local M = {}

M.win = nil
M.buf = nil
M.current_agent = nil
M.agent_state = nil

function M.setup()
  M.buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_option(M.buf, "buftype", "nofile")
  vim.api.nvim_buf_set_option(M.buf, "filetype", "remora")

  -- Keymaps for sidepanel buffer
  vim.api.nvim_buf_set_keymap(M.buf, "n", "c", "<cmd>lua require('remora.chat').open()<cr>", {})
  vim.api.nvim_buf_set_keymap(M.buf, "n", "t", "<cmd>lua require('remora.sidepanel').trigger()<cr>", {})
  vim.api.nvim_buf_set_keymap(M.buf, "n", "s", "<cmd>lua require('remora.sidepanel').show_subscriptions()<cr>", {})
end

function M.toggle()
  if M.win and vim.api.nvim_win_is_valid(M.win) then
    M.close()
  else
    M.open()
  end
end

function M.open()
  vim.cmd("vsplit")
  vim.cmd("wincmd L")
  M.win = vim.api.nvim_get_current_win()
  vim.api.nvim_win_set_buf(M.win, M.buf)
  vim.api.nvim_win_set_width(M.win, 40)

  vim.api.nvim_win_set_option(M.win, "number", false)
  vim.api.nvim_win_set_option(M.win, "signcolumn", "no")
  vim.api.nvim_win_set_option(M.win, "winfixwidth", true)

  vim.cmd("wincmd p")

  if M.current_agent then
    M.render()
  end
end

function M.show_agent(agent_id)
  M.current_agent = agent_id

  -- Request state from daemon
  require("remora.bridge").call("agent.select", { agent_id }, function(state)
    M.agent_state = state
    M.render()
  end)
end

function M.render()
  if not M.win or not vim.api.nvim_win_is_valid(M.win) then
    return
  end

  local state = M.agent_state or {}
  local lines = {}

  -- Header
  table.insert(lines, "╭─────────────────────────────────╮")
  table.insert(lines, string.format("│ Agent: %-25s│", state.name or "?"))
  table.insert(lines, string.format("│ Type: %-26s│", state.node_type or "?"))
  table.insert(lines, string.format("│ Status: %-24s│", state.status or "DORMANT"))
  if state.last_activated then
    local ago = M.time_ago(state.last_activated)
    table.insert(lines, string.format("│ Last Run: %-22s│", ago))
  end
  table.insert(lines, "╰─────────────────────────────────╯")
  table.insert(lines, "")

  -- Subscriptions
  local sub_count = #(state.subscriptions or {})
  table.insert(lines, string.format("SUBSCRIPTIONS (%d)", sub_count))
  table.insert(lines, "─────────────────────────────────")
  if sub_count > 0 then
    for _, sub in ipairs(state.subscriptions) do
      local tag = sub.is_default and "[default]" or "[custom]"
      table.insert(lines, string.format("├─ %s %s", tag, sub.description:sub(1, 25)))
    end
  else
    table.insert(lines, "  (no subscriptions)")
  end
  table.insert(lines, "")

  -- Recent triggers
  local trigger_count = #(state.recent_triggers or {})
  table.insert(lines, string.format("RECENT TRIGGERS (%d)", trigger_count))
  table.insert(lines, "─────────────────────────────────")
  if trigger_count > 0 then
    for i, trigger in ipairs(state.recent_triggers) do
      if i <= 3 then  -- Show max 3
        local ago = M.time_ago(trigger.timestamp)
        table.insert(lines, string.format("├─ [%s] %s",
          ago,
          trigger.from_agent:sub(1, 15)
        ))
        table.insert(lines, string.format("│  %s: %s",
          trigger.event_type,
          (trigger.summary or ""):sub(1, 20)
        ))
      end
    end
    if trigger_count > 3 then
      table.insert(lines, string.format("└─ ... and %d more", trigger_count - 3))
    end
  else
    table.insert(lines, "  (none)")
  end
  table.insert(lines, "")

  -- Connections
  table.insert(lines, "CONNECTIONS")
  table.insert(lines, "─────────────────────────────────")
  if state.connections and next(state.connections) then
    for name, id in pairs(state.connections) do
      table.insert(lines, string.format("├─ %s → %s", name, id:sub(1, 12)))
    end
  else
    table.insert(lines, "  (none learned)")
  end
  table.insert(lines, "")

  -- Recent chat
  table.insert(lines, "CHAT")
  table.insert(lines, "─────────────────────────────────")
  if state.chat_history and #state.chat_history > 0 then
    -- Show last 2 exchanges
    local start = math.max(1, #state.chat_history - 3)
    for i = start, #state.chat_history do
      local msg = state.chat_history[i]
      local prefix = msg.role == "user" and "> " or "< "
      for _, line in ipairs(vim.split(msg.content:sub(1, 100), "\n")) do
        table.insert(lines, prefix .. line)
        prefix = "  "
      end
    end
  else
    table.insert(lines, "  (no history)")
  end
  table.insert(lines, "")

  -- Actions
  table.insert(lines, "─────────────────────────────────")
  table.insert(lines, " [c]hat  [t]rigger  [s]ubscriptions")

  vim.api.nvim_buf_set_lines(M.buf, 0, -1, false, lines)
end

function M.trigger()
  if not M.current_agent then
    vim.notify("No agent selected", vim.log.levels.WARN)
    return
  end

  vim.notify("Triggering agent...", vim.log.levels.INFO)

  -- Emit a ManualTriggerEvent
  require("remora.bridge").call("swarm.emit", {
    event_type = "ManualTrigger",
    to_agent = M.current_agent,
    source = "neovim",
  }, function(result)
    vim.notify("Event emitted, waiting for turn...", vim.log.levels.INFO)
    -- Turn completion will come via notification
  end)
end

function M.time_ago(timestamp)
  local diff = os.time() - timestamp
  if diff < 60 then return "just now"
  elseif diff < 3600 then return string.format("%dm ago", diff // 60)
  elseif diff < 86400 then return string.format("%dh ago", diff // 3600)
  else return string.format("%dd ago", diff // 86400)
  end
end

-- Called when daemon notifies us of a turn completion
function M.on_turn_complete(agent_id, result)
  if agent_id == M.current_agent then
    vim.notify("Turn complete", vim.log.levels.INFO)
    M.show_agent(agent_id)  -- Refresh
  end
end

return M
```

#### Chat (`chat.lua`)

```lua
local M = {}

function M.open()
  local sidepanel = require("remora.sidepanel")
  if not sidepanel.current_agent then
    vim.notify("No agent selected", vim.log.levels.WARN)
    return
  end

  vim.ui.input({ prompt = "Chat with agent: " }, function(input)
    if input and input ~= "" then
      M.send_message(sidepanel.current_agent, input)
    end
  end)
end

function M.send_message(agent_id, message)
  vim.notify("Sending to agent...", vim.log.levels.INFO)

  -- Emit UserChatEvent - this will trigger the agent's subscription
  require("remora.bridge").call("swarm.emit", {
    event_type = "UserChat",
    to_agent = agent_id,
    content = { message = message },
    source = "neovim",
  }, function(response)
    -- The actual turn result will come via notification
    -- But we get immediate confirmation the event was emitted
    vim.notify("Message sent, agent triggered", vim.log.levels.INFO)
  end)
end

return M
```

#### Buffer Sync (`buffer.lua`)

```lua
local M = {}

function M.setup()
  -- Emit FileSavedEvent when buffer is saved
  vim.api.nvim_create_autocmd("BufWritePost", {
    pattern = {"*.py", "*.js", "*.ts", "*.go", "*.rs"},
    callback = function(ev)
      local path = vim.api.nvim_buf_get_name(ev.buf)
      M.emit_file_saved(path)
    end
  })
end

function M.emit_file_saved(path)
  -- Emit event into the swarm - subscriptions will handle the rest
  require("remora.bridge").call("swarm.emit", {
    event_type = "FileSaved",
    path = path,
    source = "neovim",
  }, function(result)
    if result.triggered_agents and #result.triggered_agents > 0 then
      vim.notify(
        string.format("%d agents triggered", #result.triggered_agents),
        vim.log.levels.INFO
      )
    end
  end)
end

function M.apply_changes(changes)
  -- changes = { path: string, content: string } or list of changes
  if not changes then return end

  if changes.path then
    changes = { changes }
  end

  for _, change in ipairs(changes) do
    local bufnr = vim.fn.bufnr(change.path)
    if bufnr ~= -1 then
      -- Buffer is open - update it
      local lines = vim.split(change.content, "\n")
      vim.api.nvim_buf_set_lines(bufnr, 0, -1, false, lines)
      vim.notify("Updated: " .. vim.fn.fnamemodify(change.path, ":t"), vim.log.levels.INFO)
    end
  end
end

return M
```

#### Bridge (`bridge.lua`)

```lua
local M = {}

M.client = nil
M.callbacks = {}
M.next_id = 1
M.current_agent_subscription = nil

function M.setup(config)
  local socket_path = config.socket or "/tmp/remora.sock"

  M.client = vim.loop.new_pipe(false)
  M.client:connect(socket_path, function(err)
    if err then
      vim.schedule(function()
        vim.notify("Failed to connect to Remora daemon: " .. err, vim.log.levels.ERROR)
      end)
      return
    end

    M.client:read_start(function(err, data)
      if err then return end
      if data then
        M.handle_response(data)
      end
    end)

    vim.schedule(function()
      vim.notify("Connected to Remora daemon", vim.log.levels.INFO)
      -- Subscribe to global events
      M.subscribe_global()
    end)
  end)
end

function M.subscribe_global()
  -- Subscribe to events we always want
  M.call("nvim.subscribe", {
    patterns = {
      { event_types = {"AgentTurnComplete"} },
      { event_types = {"ContentChangedEvent"} },
    }
  })
end

function M.subscribe_to_agent(agent_id)
  -- When user selects an agent, also subscribe to events TO that agent
  if M.current_agent_subscription then
    M.call("nvim.unsubscribe", { subscription_id = M.current_agent_subscription })
  end

  M.call("nvim.subscribe", {
    patterns = {
      { to_agent = agent_id }
    }
  }, function(result)
    M.current_agent_subscription = result.subscription_id
  end)
end

function M.call(method, params, callback)
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
    if ok then
      if msg.id and M.callbacks[msg.id] then
        -- RPC response
        vim.schedule(function()
          M.callbacks[msg.id](msg.result)
          M.callbacks[msg.id] = nil
        end)
      elseif msg.method then
        -- Notification from daemon (pushed event)
        vim.schedule(function()
          M.handle_notification(msg.method, msg.params)
        end)
      end
    end
  end
end

function M.handle_notification(method, params)
  if method == "event.subscribed" then
    -- An event we subscribed to arrived
    local event = params.event
    if event.event_type == "ContentChangedEvent" then
      require("remora.buffer").apply_changes(params.changes)
    elseif event.event_type == "AgentTurnComplete" then
      require("remora.sidepanel").on_turn_complete(params.agent_id, params.result)
    end
    -- Update indicators for any event
    require("remora.indicators").on_event(event)
  end
end

return M
```

#### Indicators (`indicators.lua`)

```lua
local M = {}

M.ns = vim.api.nvim_create_namespace("remora_indicators")
M.trigger_counts = {}  -- agent_id -> count of recent triggers

function M.setup()
  -- Refresh indicators when buffer is displayed
  vim.api.nvim_create_autocmd("BufWinEnter", {
    callback = M.refresh_buffer_indicators,
  })
end

function M.on_event(event)
  -- Track triggers per agent
  if event.to_agent then
    M.trigger_counts[event.to_agent] = (M.trigger_counts[event.to_agent] or 0) + 1
    M.refresh_buffer_indicators()

    -- Decay after 5 seconds
    vim.defer_fn(function()
      M.trigger_counts[event.to_agent] = (M.trigger_counts[event.to_agent] or 1) - 1
      M.refresh_buffer_indicators()
    end, 5000)
  end
end

function M.refresh_buffer_indicators()
  local bufnr = vim.api.nvim_get_current_buf()
  vim.api.nvim_buf_clear_namespace(bufnr, M.ns, 0, -1)

  -- Get treesitter root
  local parser = vim.treesitter.get_parser(bufnr)
  if not parser then return end

  local tree = parser:parse()[1]
  if not tree then return end

  local root = tree:root()
  local nav = require("remora.navigation")

  -- Walk tree and add indicators for agents with recent triggers
  M.walk_tree(root, bufnr, function(node)
    if nav.is_agent_node_type(node:type()) then
      local agent_id = nav.compute_agent_id(node, bufnr)
      local count = M.trigger_counts[agent_id]

      if count and count > 0 then
        local row = node:start()
        vim.api.nvim_buf_set_extmark(bufnr, M.ns, row, 0, {
          virt_text = { { string.format(" [%d]", count), "DiagnosticInfo" } },
          virt_text_pos = "eol",
        })
      end
    end
  end)
end

function M.walk_tree(node, bufnr, callback)
  callback(node)
  for child in node:iter_children() do
    M.walk_tree(child, bufnr, callback)
  end
end

return M
```

### 3.3 Keybindings

```lua
local function setup_keymaps()
  local opts = { noremap = true, silent = true }

  -- Sidepanel
  vim.keymap.set("n", "<leader>ra", "<cmd>lua require('remora.sidepanel').toggle()<cr>", opts)

  -- Agent navigation (supplements treesitter-textobjects)
  vim.keymap.set("n", "[[", function()
    require("remora.navigation").go_to_parent()
  end, opts)

  vim.keymap.set("n", "]]", function()
    require("remora.navigation").go_to_first_child()
  end, opts)

  -- Chat with current agent
  vim.keymap.set("n", "<leader>rc", function()
    require("remora.chat").open()
  end, opts)

  -- Trigger current agent
  vim.keymap.set("n", "<leader>rt", function()
    require("remora.sidepanel").trigger()
  end, opts)

  -- View subscriptions
  vim.keymap.set("n", "<leader>rs", function()
    require("remora.sidepanel").show_subscriptions()
  end, opts)
end
```

---

## Part 4: Daemon RPC Server

The daemon exposes a JSON-RPC server with subscription support:

```python
# remora/nvim/server.py

import asyncio
import json
from pathlib import Path
from dataclasses import dataclass

@dataclass
class NvimClient:
    """Connected Neovim client with its subscriptions."""
    writer: asyncio.StreamWriter
    subscriptions: list[SubscriptionPattern]
    subscription_ids: dict[str, SubscriptionPattern]

class NvimRpcServer:
    """JSON-RPC server for Neovim plugin communication."""

    def __init__(
        self,
        swarm_state: SwarmState,
        event_store: EventStore,
        subscriptions: SubscriptionRegistry,
        agent_runner: AgentRunner,
        socket_path: str = "/tmp/remora.sock",
    ):
        self.swarm_state = swarm_state
        self.event_store = event_store
        self.subscriptions = subscriptions
        self.runner = agent_runner
        self.socket_path = socket_path
        self.clients: list[NvimClient] = []

        # Subscribe to all events so we can forward to Neovim
        self._setup_event_forwarding()

    def _setup_event_forwarding(self):
        """Forward matching events to connected Neovim clients."""
        async def forward_handler(event):
            for client in self.clients:
                for pattern in client.subscriptions:
                    if pattern.matches(event):
                        await self._notify_client(client, "event.subscribed", {
                            "event": self._serialize_event(event),
                        })
                        break  # One match is enough

        # Subscribe to all events
        self.event_store.event_bus.subscribe_all(forward_handler)

    async def start(self) -> None:
        Path(self.socket_path).unlink(missing_ok=True)
        server = await asyncio.start_unix_server(
            self._handle_client,
            path=self.socket_path,
        )
        async with server:
            await server.serve_forever()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        client = NvimClient(writer, [], {})
        self.clients.append(client)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                request = json.loads(line.decode())
                response = await self._handle_request(client, request)
                if request.get("id"):
                    writer.write(json.dumps(response).encode() + b"\n")
                    await writer.drain()
        finally:
            self.clients.remove(client)
            writer.close()

    async def _handle_request(self, client: NvimClient, request: dict) -> dict:
        method = request.get("method", "")
        params = request.get("params", {})

        handlers = {
            "agent.select": self._select_agent,
            "swarm.emit": lambda p: self._emit_event(p),
            "nvim.subscribe": lambda p: self._nvim_subscribe(client, p),
            "nvim.unsubscribe": lambda p: self._nvim_unsubscribe(client, p),
            "agent.get_subscriptions": self._get_subscriptions,
        }

        handler = handlers.get(method)
        if handler:
            try:
                result = await handler(params)
                return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {"code": -1, "message": str(e)},
                }
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    async def _select_agent(self, params: dict) -> dict:
        """Get agent state for display."""
        agent_id = params.get("agent_id") or params[0]
        metadata = await self.swarm_state.get_agent(agent_id)
        if not metadata:
            return {"error": "Agent not found"}

        state = AgentState.load(self._state_path(agent_id))
        subs = await self.subscriptions.get_subscriptions(agent_id)
        recent = await self._get_recent_triggers(agent_id)

        return {
            "id": agent_id,
            "name": metadata.name,
            "node_type": metadata.node_type,
            "file_path": metadata.file_path,
            "status": "DORMANT",
            "last_activated": state.last_activated,
            "subscriptions": [
                {
                    "id": s.id,
                    "description": self._describe_pattern(s.pattern),
                    "is_default": s.id.endswith("_default"),
                }
                for s in subs
            ],
            "recent_triggers": recent,
            "connections": state.connections,
            "chat_history": state.chat_history[-10:],
        }

    async def _emit_event(self, params: dict) -> dict:
        """Emit an event into the swarm."""
        event_type = params.get("event_type")
        event = self._create_event(params)

        event_id = await self.event_store.append(event)

        # Get which agents were triggered
        triggered = await self.subscriptions.get_matching_agents(event)

        return {
            "event_id": event_id,
            "triggered_agents": triggered,
        }

    async def _nvim_subscribe(self, client: NvimClient, params: dict) -> dict:
        """Add subscriptions for this Neovim client."""
        patterns = params.get("patterns", [])
        sub_ids = []

        for p in patterns:
            pattern = SubscriptionPattern(**p)
            sub_id = f"nvim_{id(client)}_{len(client.subscriptions)}"
            client.subscriptions.append(pattern)
            client.subscription_ids[sub_id] = pattern
            sub_ids.append(sub_id)

        return {"subscription_ids": sub_ids}

    async def _nvim_unsubscribe(self, client: NvimClient, params: dict) -> dict:
        """Remove a subscription for this Neovim client."""
        sub_id = params.get("subscription_id")
        if sub_id in client.subscription_ids:
            pattern = client.subscription_ids.pop(sub_id)
            client.subscriptions.remove(pattern)
            return {"success": True}
        return {"success": False, "error": "Subscription not found"}

    async def _notify_client(self, client: NvimClient, method: str, params: dict) -> None:
        """Send notification to a Neovim client."""
        data = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }).encode() + b"\n"
        try:
            client.writer.write(data)
            await client.writer.drain()
        except Exception:
            pass
```

---

## Part 5: User Experience

### 5.1 Typical Workflow

```
1. User opens Python file
   → Daemon has already parsed and registered agents
   → Neovim connects, subscribes to global events

2. User navigates to function (]f or cursor move)
   → Sidepanel shows function agent state
   → Neovim subscribes to events for this agent
   → Recent triggers shown (not "inbox" - events were already delivered)

3. User opens chat (<leader>rc)
   → Types: "add timezone support"
   → UserChatEvent emitted to swarm
   → Agent's subscription matches → turn triggered
   → Agent runs, emits message to parent
   → Parent's subscription matches → parent triggered
   → Eventually, content change emitted
   → Neovim receives notification, updates buffer

4. User saves file (:w)
   → FileSavedEvent emitted to swarm
   → Matching agents triggered (immediate, not polled)
   → Indicators flash briefly showing triggered agents

5. Agent completes turn
   → AgentTurnComplete event emitted
   → Neovim receives notification (subscribed)
   → Sidepanel refreshes with results
```

### 5.2 Visual Feedback

```
Code Buffer                          Sidepanel
───────────────────────────────────  ─────────────────────────
def format_date(dt):  [2]           │ Agent: format_date
    """Format date."""               │ Status: DORMANT
    if dt is None:                   │
        return "N/A"                 │ SUBSCRIPTIONS (2)
    return dt.strftime(...)          │ ├─ [default] to_agent: self
                                     │ └─ [default] path: utils.py
def parse_date(s):                   │
    ...                              │ RECENT TRIGGERS (2)
                                     │ ├─ [2m] test: sig changed
                                     │ └─ [5m] linter: line 18
```

The `[2]` indicator shows recent trigger count (decays after 5s). Sidepanel shows full details.

### 5.3 Commands

```vim
" Core commands
:RemoraToggle          " Toggle sidepanel
:RemoraStatus          " Show daemon/swarm status
:RemoraConnect         " Reconnect to daemon

" Agent interaction
:RemoraChat            " Open chat with current agent
:RemoraTrigger         " Emit manual trigger event
:RemoraSubscriptions   " Show current agent's subscriptions

" Navigation
:RemoraParent          " Go to parent agent
:RemoraChildren        " List child agents
```

---

## Part 6: Configuration

### 6.1 Plugin Configuration

```lua
require("remora").setup({
  -- Daemon connection
  socket = "/tmp/remora.sock",
  auto_connect = true,

  -- UI
  sidepanel = {
    position = "right",  -- "right", "left", "float"
    width = 40,
  },

  -- Indicators
  indicators = {
    trigger_badge = true,   -- Show [N] for recent triggers
    decay_ms = 5000,        -- How long to show trigger badge
  },

  -- Keybindings
  keymaps = {
    toggle = "<leader>ra",
    chat = "<leader>rc",
    trigger = "<leader>rt",
    subscriptions = "<leader>rs",
    parent = "[[",
    child = "]]",
  },

  -- Auto behavior
  auto = {
    emit_on_save = true,     -- Emit FileSavedEvent on :w
    refresh_on_focus = true, -- Refresh sidepanel on window focus
  },
})
```

### 6.2 Daemon Configuration (`remora.yaml`)

```yaml
daemon:
  socket: /tmp/remora.sock
  log_level: info

model:
  base_url: http://localhost:8000/v1
  api_key: EMPTY
  default_model: Qwen/Qwen3-4B

swarm:
  workspace_path: ~/.cache/remora/swarm
  auto_reconcile: true

# Cascade prevention
triggers:
  max_depth: 10
  cooldown_ms: 100

jujutsu:
  enabled: false
  auto_commit: false
```

---

## Part 7: Implementation Summary

### What's Needed (Plugin Side)

| Module | Lines | Description |
|--------|-------|-------------|
| `init.lua` | ~30 | Setup, health check |
| `config.lua` | ~40 | Configuration handling |
| `navigation.lua` | ~80 | Treesitter integration, agent ID |
| `sidepanel.lua` | ~160 | Agent UI panel (state, subs, triggers) |
| `chat.lua` | ~30 | Chat interface |
| `indicators.lua` | ~70 | Trigger badges |
| `bridge.lua` | ~100 | JSON-RPC client + subscription mgmt |
| `buffer.lua` | ~40 | Event emission on save |
| **Total** | **~550** | |

### What's Needed (Daemon Side)

| Module | Lines | Description |
|--------|-------|-------------|
| `nvim/server.py` | ~250 | JSON-RPC server with subscription forwarding |
| **Total** | **~250** | |

### Dependencies

**Neovim Plugin:**
- `nvim-treesitter` (for parsing)
- `nvim-treesitter-textobjects` (optional, for navigation)

**Daemon:**
- Existing Remora infrastructure
- Swarm components from REMORA_CST_DEMO_ANALYSIS.md

---

## Appendix A: Treesitter Node Types by Language

```lua
local agent_node_types = {
  python = {
    "module", "function_definition", "async_function_definition",
    "class_definition", "decorated_definition",
    "import_statement", "import_from_statement",
  },
  javascript = {
    "program", "function_declaration", "arrow_function",
    "class_declaration", "method_definition", "import_statement",
  },
  typescript = {
    "program", "function_declaration", "arrow_function",
    "class_declaration", "method_definition",
    "interface_declaration", "type_alias_declaration",
    "import_statement",
  },
  go = {
    "source_file", "function_declaration", "method_declaration",
    "type_declaration", "import_declaration",
  },
  rust = {
    "source_file", "function_item", "impl_item",
    "struct_item", "enum_item", "trait_item", "use_declaration",
  },
}
```

---

*Document version: 3.0*
*Status: Reactive Architecture - Ready for Implementation*
