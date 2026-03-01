-- src/remora/lsp/nvim/lua/remora/panel.lua
local nui_popup = require("nui.popup")

local M = {}

M.state = {
    expanded = false,
    width = 4,
    selected_agent = nil,
    agents = {},
    events = {},
    border_hl = "RemoraBorder",
    is_open = false,
}

local status_icons = {
    active = "●",
    running = "▶",
    pending_approval = "⏸",
    orphaned = "○",
}

local status_hls = {
    active = "RemoraActive",
    running = "RemoraRunning",
    pending_approval = "RemoraPending",
    orphaned = "RemoraOrphaned",
}

local event_icons = {
    AgentStartEvent = "▶",
    AgentCompleteEvent = "✓",
    AgentErrorEvent = "✗",
    RewriteProposalEvent = "✏",
    RewriteAppliedEvent = "✓",
    RewriteRejectedEvent = "✗",
    HumanChatEvent = "👤",
    AgentMessageEvent = "💬",
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

function M.status_icon(status)
    return status_icons[status] or "?"
end

function M.status_hl(status)
    return status_hls[status] or "Normal"
end

function M.event_icon(event_type)
    return event_icons[event_type] or "?"
end

function M.event_hl(event_type)
    return event_hls[event_type] or "Normal"
end

function M.format_time(timestamp)
    if not timestamp then return "" end
    local dt = os.date("*t", timestamp)
    return string.format("%02d:%02d:%02d", dt.hour, dt.min, dt.sec)
end

function M.open()
    if M.popup and M.state.is_open then
        return
    end

    M.popup = nui_popup({
        position = "50%",
        size = { width = 40, height = "80%" },
        relative = "editor",
        anchor = "NE",
        border = {
            style = "rounded",
            highlight = M.state.border_hl,
        },
        buf_options = {
            modifiable = false,
            readonly = true,
        },
    })

    M.state.is_open = true
    M.render()

    M.popup:map("n", "q", function()
        M.close()
    end, { noremap = true })

    M.popup:map("n", "c", function()
        vim.cmd("RemoraChat")
    end, { noremap = true })

    M.popup:map("n", "r", function()
        vim.cmd("RemoraRewrite")
    end, { noremap = true })

    M.popup:show()
end

function M.close()
    if M.popup then
        M.popup:unmount()
        M.popup = nil
    end
    M.state.is_open = false
end

function M.is_open()
    return M.state.is_open
end

function M.render()
    if not M.popup then return end

    local lines = {}
    local hl = {}

    local function add_line(text, highlight)
        table.insert(lines, text)
        table.insert(hl, highlight or "Normal")
    end

    add_line(" Remora Agents", "Title")
    add_line(string.rep("-", 30), "Separator")

    if #M.state.agents == 0 then
        add_line("No agents found", "Comment")
        add_line("", "Normal")
        add_line("Open a Python file to", "Comment")
        add_line("register agent nodes", "Comment")
    else
        for _, agent in ipairs(M.state.agents) do
            local icon = M.status_icon(agent.status)
            local is_selected = M.state.selected_agent == agent.id
            local prefix = is_selected and "> " or "  "
            add_line(
                string.format("%s%s %s", prefix, icon, agent.name),
                is_selected and "CursorLine" or M.status_hl(agent.status)
            )
            if is_selected then
                add_line(string.format("   ID: %s", agent.id), "Comment")
                add_line(string.format("   Status: %s", agent.status), "Comment")
                if agent.parent_id then
                    add_line(string.format("   Parent: %s", agent.parent_id), "Comment")
                end
            end
        end
    end

    add_line("", "Normal")
    add_line("--- Events ---", "Title")

    for _, event in ipairs(M.state.events) do
        local icon = M.event_icon(event.event_type)
        add_line(
            string.format("%s %s", icon, event.summary or event.event_type),
            M.event_hl(event.event_type)
        )
    end

    add_line("", "Normal")
    add_line("[q]uit [c]hat [r]efresh", "Comment")

    local buf = M.popup.bufnr
    vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)

    for i, hl_group in ipairs(hl) do
        local line_num = i - 1
        vim.api.nvim_buf_add_highlight(buf, -1, hl_group, line_num, 0, -1)
    end
end

function M.add_event(event)
    table.insert(M.state.events, 1, event)
    if #M.state.events > 50 then
        table.remove(M.state.events)
    end
    M.render()
end

function M.select_agent(agent_id)
    M.state.selected_agent = agent_id
    M.render()
end

function M.update_agents(agents)
    M.state.agents = agents
    M.render()
end

return M
