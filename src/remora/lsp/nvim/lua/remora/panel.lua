local n = require("nui-components")
local Renderer = require("nui-components.renderer")
local Signal = require("nui-components.signal")

local M = {}

M.state = Signal.create({
    expanded = false,
    selected_agent = nil,
    agents = {},
    events = {},
    border_hl = "RemoraBorder",
    is_open = false,
})

M.renderer = nil

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

local function get_selected_agent()
    local selected = M.state.selected_agent:get()
    if not selected then
        return nil
    end
    return M.state.agents:get()[selected]
end

local function refresh_renderer()
    if M.renderer then
        M.renderer:update()
    end
end

local function animate_border_for_event(event_type)
    if event_type == "RewriteProposalEvent" then
        M.state.border_hl:set("DiagnosticWarn")
        vim.defer_fn(function()
            M.state.border_hl:set("RemoraBorder")
            refresh_renderer()
        end, 2000)
    end
end

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
    if not timestamp then
        return ""
    end
    return os.date("%H:%M:%S", timestamp)
end

function M.agent_header(state)
    return n.rows({
        n.text({
            content = function()
                local agent = get_selected_agent()
                if not agent then
                    return "No agent selected"
                end
                return string.format("## %s", agent.name)
            end,
            hl_group = "Title",
        }),
        n.text({
            content = function()
                local agent = get_selected_agent()
                if not agent then
                    return ""
                end
                return string.format("ID: %s | %s", agent.id, agent.status)
            end,
            hl_group = function()
                local agent = get_selected_agent()
                return agent and M.status_hl(agent.status) or "Normal"
            end,
        }),
        n.separator(),
        n.text({
            content = function()
                local agent = get_selected_agent()
                if not agent then
                    return ""
                end
                return string.format("Parent: %s", agent.parent_id or "None")
            end,
            hl_group = "Comment",
        }),
    })
end

function M.state_tab(state)
    return n.rows({
        n.text({
            content = function()
                local agent = get_selected_agent()
                if not agent then
                    return "Select an agent to see more details."
                end
                return string.format("Status: %s", agent.status)
            end,
            hl_group = "Comment",
        }),
        n.text({
            content = function()
                local agent = get_selected_agent()
                if not agent then
                    return ""
                end
                return string.format("Range: %s", agent.range or "unknown")
            end,
            hl_group = "Comment",
        }),
    })
end

function M.events_tab(state)
    return n.rows({
        n.scroll({
            max_height = 15,
            content = n.each(state.events, function(event)
                return n.rows({
                    n.columns({
                        n.text({
                            content = M.event_icon(event.event_type),
                            hl_group = M.event_hl(event.event_type),
                            flex = 0,
                            size = 3,
                        }),
                        n.text({
                            content = event.summary or event.event_type,
                            flex = 1,
                        }),
                        n.text({
                            content = M.format_time(event.timestamp),
                            hl_group = "Comment",
                            flex = 0,
                            size = 8,
                        }),
                    }),
                    n.if_(
                        function()
                            return event.event_type == "RewriteProposalEvent"
                        end,
                        n.box({
                            border = "single",
                            content = n.text({
                                content = event.diff or "",
                                hl_group = "DiffText",
                            }),
                        })
                    ),
                })
            end),
        }),
    })
end

function M.chat_tab(state)
    local input_value = Signal.create("")
    return n.rows({
        n.scroll({
            max_height = 10,
            content = n.each(state.events, function(event)
                if event.event_type ~= "HumanChatEvent" and event.event_type ~= "AgentMessageEvent" then
                    return nil
                end

                local is_human = event.event_type == "HumanChatEvent"
                return n.box({
                    border = is_human and "rounded" or "single",
                    hl_group = is_human and "Normal" or "Comment",
                    content = n.text({ content = event.message or event.summary or "" }),
                })
            end),
        }),
        n.separator(),
        n.input({
            placeholder = "Message agent...",
            value = input_value,
            on_submit = function(value)
                if value and value ~= "" then
                    local agent = get_selected_agent()
                    if agent then
                        vim.lsp.buf_notify(0, "$/remora/submitInput", {
                            agent_id = agent.id,
                            input = value,
                        })
                        input_value:set("")
                    end
                end
            end,
        }),
    })
end

function M.create_panel()
    local state = M.state
    return n.rows({
        n.columns({
            n.if_(
                function()
                    return not state.expanded:get()
                end,
                n.rows({
                    n.each(state.agents, function(agent)
                        return n.text({
                            content = M.status_icon(agent.status),
                            hl_group = M.status_hl(agent.status),
                            on_click = function()
                                state.selected_agent:set(agent.id)
                                state.expanded:set(true)
                                refresh_renderer()
                            end,
                        })
                    end),
                })
            ),
            n.if_(
                function()
                    return state.expanded:get()
                end,
                n.rows({
                    M.agent_header(state),
                    n.tabs({
                        n.tab({ label = "State" }, M.state_tab(state)),
                        n.tab({ label = "Events" }, M.events_tab(state)),
                        n.tab({ label = "Chat" }, M.chat_tab(state)),
                    }),
                    n.text({
                        content = "[q]uit  [c]hat  [r]efresh",
                        hl_group = "Comment",
                    }),
                })
            ),
        }),
        {
            border = {
                style = "rounded",
                hl_group = function()
                    return state.border_hl:get()
                end,
            },
        },
    })
end

function M.open()
    if M.renderer then
        return
    end

    M.renderer = Renderer.new({
        render = function()
            return M.create_panel()
        end,
    })
    M.renderer:mount()
    M.state.is_open:set(true)
end

function M.close()
    if not M.renderer then
        return
    end

    M.renderer:unmount()
    M.renderer = nil
    M.state.is_open:set(false)
end

function M.toggle_panel()
    if M.renderer then
        M.close()
    else
        M.open()
    end
end

function M.is_open()
    return M.state.is_open:get()
end

function M.add_event(event)
    local events = vim.deepcopy(M.state.events:get())
    table.insert(events, 1, event)
    if #events > 50 then
        table.remove(events)
    end
    M.state.events:set(events)
    animate_border_for_event(event.event_type)
    refresh_renderer()
end

function M.select_agent(agent_id)
    local agents = M.state.agents:get()
    if agents[agent_id] then
        M.state.selected_agent:set(agent_id)
        refresh_renderer()
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
    M.state.agents:set(mapping)
    refresh_renderer()
end

return M
