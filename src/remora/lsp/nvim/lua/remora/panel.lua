local n = require("nui-components")
local Line = require("nui.line")
local Renderer = require("nui-components.renderer")
local Signal = require("nui-components.signal")

local M = {}

-- ---------------------------------------------------------------------------
-- State
-- ---------------------------------------------------------------------------

M.state = Signal.create({
    expanded = false,
    selected_agent = nil,
    agents = {},        -- { [id] = { id, name, status, parent_id } }
    events = {},        -- list, newest first
    active_tab = "state",
    is_open = false,
})

M.renderer = nil

-- ---------------------------------------------------------------------------
-- Icon / highlight tables
-- ---------------------------------------------------------------------------

local status_icons = {
    active = " ",
    running = " ",
    pending_approval = " ",
    orphaned = " ",
}

local status_hls = {
    active = "RemoraActive",
    running = "RemoraRunning",
    pending_approval = "RemoraPending",
    orphaned = "RemoraOrphaned",
}

local event_icons = {
    AgentStartEvent = " ",
    AgentCompleteEvent = " ",
    AgentErrorEvent = " ",
    RewriteProposalEvent = " ",
    RewriteAppliedEvent = " ",
    RewriteRejectedEvent = " ",
    HumanChatEvent = " ",
    AgentMessageEvent = " ",
}

local event_hls = {
    AgentStartEvent = "DiagnosticInfo",
    AgentCompleteEvent = "DiagnosticOk",
    AgentErrorEvent = "DiagnosticError",
    RewriteProposalEvent = "DiagnosticWarn",
    RewriteAppliedEvent = "DiagnosticOk",
    RewriteRejectedEvent = "DiagnosticError",
    HumanChatEvent = "Title",
    AgentMessageEvent = "Comment",
}

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

local function get_selected_agent()
    local selected = M.state.selected_agent:get_value()
    if not selected then return nil end
    return M.state.agents:get_value()[selected]
end

local function format_time(timestamp)
    if not timestamp then return "" end
    return os.date("%H:%M:%S", timestamp)
end

-- ---------------------------------------------------------------------------
-- Line builders  (return tables of NuiLine for n.paragraph)
-- ---------------------------------------------------------------------------

--- Build lines for the collapsed agent-icon sidebar.
local function build_agent_icon_lines()
    local agents = M.state.agents:get_value()
    local lines = {}
    for _, agent in pairs(agents) do
        local icon = status_icons[agent.status] or "?"
        local hl = status_hls[agent.status] or "Normal"
        local line = Line()
        line:append(icon, hl)
        line:append(" " .. (agent.name or agent.id), hl)
        table.insert(lines, line)
    end
    if #lines == 0 then
        local line = Line()
        line:append("No agents", "Comment")
        table.insert(lines, line)
    end
    return lines
end

--- Build lines for the agent header (shown when expanded).
local function build_header_lines()
    local agent = get_selected_agent()
    local lines = {}
    if not agent then
        local line = Line()
        line:append("No agent selected", "Comment")
        table.insert(lines, line)
        return lines
    end

    local title = Line()
    title:append(agent.name or agent.id, "Title")
    table.insert(lines, title)

    local status_line = Line()
    local hl = status_hls[agent.status] or "Normal"
    local icon = status_icons[agent.status] or "?"
    status_line:append(icon .. " " .. (agent.status or "unknown"), hl)
    status_line:append("  ID: " .. agent.id, "Comment")
    table.insert(lines, status_line)

    local parent_line = Line()
    parent_line:append("Parent: " .. (agent.parent_id or "none"), "Comment")
    table.insert(lines, parent_line)

    return lines
end

--- Build lines for the State tab.
local function build_state_lines()
    local agent = get_selected_agent()
    if not agent then
        local line = Line()
        line:append("Select an agent to see details.", "Comment")
        return { line }
    end
    local lines = {}
    local s = Line()
    s:append("Status: " .. (agent.status or "unknown"), "Comment")
    table.insert(lines, s)

    local r = Line()
    r:append("Range: " .. (agent.range or "unknown"), "Comment")
    table.insert(lines, r)
    return lines
end

--- Build lines for the Events tab.
local function build_event_lines()
    local events = M.state.events:get_value()
    if #events == 0 then
        local line = Line()
        line:append("No events yet.", "Comment")
        return { line }
    end

    local lines = {}
    for i, ev in ipairs(events) do
        if i > 30 then break end  -- cap display
        local icon = event_icons[ev.event_type] or "?"
        local hl = event_hls[ev.event_type] or "Normal"
        local line = Line()
        line:append(icon, hl)
        line:append(" " .. (ev.summary or ev.event_type), hl)
        local ts = format_time(ev.timestamp)
        if ts ~= "" then
            line:append("  " .. ts, "Comment")
        end
        table.insert(lines, line)

        -- Show diff snippet for rewrite proposals
        if ev.event_type == "RewriteProposalEvent" and ev.diff then
            for _, diff_line in ipairs(vim.split(ev.diff, "\n")) do
                local dl = Line()
                dl:append("  " .. diff_line, "DiffText")
                table.insert(lines, dl)
            end
        end
    end
    return lines
end

--- Build lines for the Chat tab.
local function build_chat_lines()
    local events = M.state.events:get_value()
    local lines = {}
    for _, ev in ipairs(events) do
        if ev.event_type == "HumanChatEvent" or ev.event_type == "AgentMessageEvent" then
            local is_human = ev.event_type == "HumanChatEvent"
            local prefix = is_human and "You: " or "Agent: "
            local hl = is_human and "Title" or "Comment"
            local line = Line()
            line:append(prefix, hl)
            line:append(ev.message or ev.summary or "")
            table.insert(lines, line)
        end
    end
    if #lines == 0 then
        local line = Line()
        line:append("No messages yet.", "Comment")
        table.insert(lines, line)
    end
    return lines
end

-- ---------------------------------------------------------------------------
-- Component tree
-- ---------------------------------------------------------------------------

function M.create_panel()
    local state = M.state

    -- Map signal values to lines for paragraphs.
    -- The `hidden` prop accepts a signal value, so collapsed/expanded is driven
    -- directly by the `expanded` signal.

    local collapsed_hidden = state.expanded  -- hidden when expanded == true
    local expanded_hidden = state.expanded:dup():negate()  -- hidden when expanded == false

    -- Which tab is active? Drive tab visibility via active_tab signal.
    local state_tab_hidden = state.active_tab:dup():map(function(t) return t ~= "state" end)
    local events_tab_hidden = state.active_tab:dup():map(function(t) return t ~= "events" end)
    local chat_tab_hidden = state.active_tab:dup():map(function(t) return t ~= "chat" end)

    return n.rows(
        -- ── Collapsed view: agent icon list ──────────────────────
        n.paragraph({
            id = "agent_list",
            hidden = collapsed_hidden,
            lines = build_agent_icon_lines(),
            border_label = "Agents",
            border_style = "rounded",
            flex = 1,
        }),

        -- ── Expanded view ────────────────────────────────────────
        n.rows(
            { hidden = expanded_hidden, flex = 1 },

            -- Header
            n.paragraph({
                id = "agent_header",
                lines = build_header_lines(),
                border_label = "Agent",
                border_style = "rounded",
                size = 5,
            }),

            -- Tab bar (buttons)
            n.columns(
                { size = 1 },
                n.button({
                    id = "tab_state",
                    label = " State ",
                    on_press = function()
                        state.active_tab = "state"
                    end,
                    is_active = n.is_active_factory(state.active_tab)("state"),
                }),
                n.button({
                    id = "tab_events",
                    label = " Events ",
                    on_press = function()
                        state.active_tab = "events"
                    end,
                    is_active = n.is_active_factory(state.active_tab)("events"),
                }),
                n.button({
                    id = "tab_chat",
                    label = " Chat ",
                    on_press = function()
                        state.active_tab = "chat"
                    end,
                    is_active = n.is_active_factory(state.active_tab)("chat"),
                })
            ),

            -- State tab content
            n.paragraph({
                id = "tab_state_content",
                hidden = state_tab_hidden,
                lines = build_state_lines(),
                flex = 1,
            }),

            -- Events tab content
            n.paragraph({
                id = "tab_events_content",
                hidden = events_tab_hidden,
                lines = build_event_lines(),
                flex = 1,
            }),

            -- Chat tab content
            n.rows(
                { hidden = chat_tab_hidden, flex = 1 },
                n.paragraph({
                    id = "tab_chat_messages",
                    lines = build_chat_lines(),
                    flex = 1,
                }),
                n.text_input({
                    id = "chat_input",
                    border_label = "Message",
                    border_style = "rounded",
                    placeholder = "Message agent...",
                    size = 1,
                    autofocus = true,
                    on_change = function(value, component)
                        -- Store current value for submit
                        M._pending_chat = value
                    end,
                })
            ),

            -- Help line
            n.paragraph({
                id = "help_line",
                lines = "[Esc] close  [Tab] navigate  [1] state  [2] events  [3] chat",
                size = 1,
            })
        )
    )
end

-- ---------------------------------------------------------------------------
-- Refresh paragraph content (called when state changes)
-- ---------------------------------------------------------------------------

local function update_paragraphs()
    if not M.renderer then return end

    local function update_component(id, lines)
        local comp = M.renderer:get_component_by_id(id)
        if not comp then return end
        -- Props are read-only via metatable; use rawset to bypass.
        pcall(function()
            rawset(comp._private.props, "lines", lines)
            comp:redraw()
        end)
    end

    update_component("agent_list", build_agent_icon_lines())
    update_component("agent_header", build_header_lines())
    update_component("tab_state_content", build_state_lines())
    update_component("tab_events_content", build_event_lines())
    update_component("tab_chat_messages", build_chat_lines())
end

-- ---------------------------------------------------------------------------
-- Lifecycle
-- ---------------------------------------------------------------------------

function M.open()
    if M.renderer then
        return
    end

    M.renderer = Renderer.create({
        width = 60,
        height = 30,
        position = "50%",
        relative = "editor",
        keymap = {
            close = "<Esc>",
            focus_next = "<Tab>",
            focus_prev = "<S-Tab>",
        },
        on_unmount = function()
            M.renderer = nil
            M.state.is_open = false
        end,
    })

    M.renderer:render(function()
        return M.create_panel()
    end)
    M.state.is_open = true

    -- Add global keymaps for tab switching & chat submit
    M.renderer:add_mappings({
        {
            mode = { "n" },
            key = "1",
            handler = function() M.state.active_tab = "state" end,
        },
        {
            mode = { "n" },
            key = "2",
            handler = function() M.state.active_tab = "events" end,
        },
        {
            mode = { "n" },
            key = "3",
            handler = function() M.state.active_tab = "chat" end,
        },
        {
            mode = { "n" },
            key = "e",
            handler = function()
                M.state.expanded = not M.state.expanded:get_value()
            end,
        },
        {
            mode = { "i" },
            key = "<C-CR>",
            handler = function()
                local value = M._pending_chat
                if value and value ~= "" then
                    local agent = get_selected_agent()
                    if agent then
                        vim.lsp.buf_notify(0, "$/remora/submitInput", {
                            agent_id = agent.id,
                            input = value,
                        })
                        M._pending_chat = ""
                        -- Clear the text input
                        local input = M.renderer:get_component_by_id("chat_input")
                        if input and input.bufnr and vim.api.nvim_buf_is_valid(input.bufnr) then
                            vim.api.nvim_buf_set_lines(input.bufnr, 0, -1, false, { "" })
                        end
                    end
                end
            end,
        },
    })
end

function M.close()
    if not M.renderer then
        return
    end
    M.renderer:close()
    M.renderer = nil
    M.state.is_open = false
end

function M.toggle_panel()
    if M.renderer then
        M.close()
    else
        M.open()
    end
end

function M.is_open()
    return M.state.is_open:get_value()
end

-- ---------------------------------------------------------------------------
-- External API  (called from init.lua LSP handlers)
-- ---------------------------------------------------------------------------

function M.add_event(event)
    local events = vim.deepcopy(M.state.events:get_value())
    table.insert(events, 1, event)
    if #events > 50 then
        table.remove(events)
    end
    M.state.events = events
    update_paragraphs()
end

function M.select_agent(agent_id)
    local agents = M.state.agents:get_value()
    if agents[agent_id] then
        M.state.selected_agent = agent_id
        M.state.expanded = true
        update_paragraphs()
    end
end

function M.update_agents(agent_list)
    local mapping = {}
    for _, agent in ipairs(agent_list or {}) do
        mapping[agent.remora_id] = {
            id = agent.remora_id,
            name = agent.name,
            status = agent.status,
            parent_id = agent.parent_id,
        }
    end
    M.state.agents = mapping
    update_paragraphs()
end

return M
