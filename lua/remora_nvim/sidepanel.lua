-- Remora Sidepanel: Agent info + streaming event log

local M = {}

M.win = nil
M.buf = nil
M.current_agent = nil
M.current_state = nil
M.event_log = {}
M.max_events = 50

function M.setup()
    M.buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_buf_set_option(M.buf, "buftype", "nofile")
    vim.api.nvim_buf_set_option(M.buf, "filetype", "remora")
    vim.api.nvim_buf_set_option(M.buf, "modifiable", true)
    vim.api.nvim_buf_set_option(M.buf, "bufhidden", "hide")

    local opts = { buffer = M.buf, noremap = true, silent = true }
    vim.keymap.set("n", "c", function() require("remora_nvim.chat").open() end, opts)
    vim.keymap.set("n", "q", function() M.close() end, opts)
    vim.keymap.set("n", "r", function() M.refresh() end, opts)
end

function M.toggle()
    if M.win and vim.api.nvim_win_is_valid(M.win) then
        M.close()
        return
    end
    M.open()
end

function M.open()
    if M.win and vim.api.nvim_win_is_valid(M.win) then
        return
    end

    vim.cmd("vsplit")
    vim.cmd("wincmd L")
    M.win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(M.win, M.buf)
    vim.api.nvim_win_set_width(M.win, 45)
    vim.api.nvim_win_set_option(M.win, "number", false)
    vim.api.nvim_win_set_option(M.win, "relativenumber", false)
    vim.api.nvim_win_set_option(M.win, "signcolumn", "no")
    vim.api.nvim_win_set_option(M.win, "wrap", true)
    vim.cmd("wincmd p")

    if M.current_agent then
        M.render()
    end
end

function M.close()
    if M.win and vim.api.nvim_win_is_valid(M.win) then
        vim.api.nvim_win_close(M.win, true)
    end
    M.win = nil
end

function M.show_agent(agent_id, file_path, node_type, start_line)
    M.current_agent = agent_id
    M.event_log = {}

    require("remora_nvim.bridge").call("agent.select", { id = agent_id }, function(state)
        M.current_state = state
        M.render()

        require("remora_nvim.bridge").get_agent_events(agent_id, function(result)
            if result and result.events then
                for _, ev in ipairs(result.events) do
                    M.add_event_to_log(ev.event_type, ev.payload or {})
                end
                M.render()
            end
        end)
    end)
end

function M.refresh()
    if M.current_agent then
        M.show_agent(M.current_agent, nil, nil, nil)
    end
end

function M.on_event_push(agent_id, event_type, event_data)
    if agent_id ~= M.current_agent then
        return
    end

    M.add_event_to_log(event_type, event_data)
    M.render()
end

function M.add_event_to_log(event_type, event_data)
    local entry = {
        type = event_type,
        data = event_data,
        time = os.time(),
    }

    table.insert(M.event_log, entry)
    while #M.event_log > M.max_events do
        table.remove(M.event_log, 1)
    end
end

function M.render()
    if not M.buf or not vim.api.nvim_buf_is_valid(M.buf) then
        return
    end

    local lines = {}
    local state = M.current_state or {}

    table.insert(lines, "╭───────────────────────────────────────────╮")
    table.insert(lines, string.format("│ Agent: %-35s│", (state.name or M.current_agent or "?"):sub(1, 35)))
    table.insert(lines, string.format("│ Type: %-36s│", (state.node_type or "unknown"):sub(1, 36)))
    table.insert(lines, string.format("│ Status: %-34s│", (state.status or "UNKNOWN"):sub(1, 34)))

    if state.file_path then
        local short_path = vim.fn.fnamemodify(state.file_path, ":t")
        local location = string.format("%s:%d", short_path, state.start_line or 0)
        table.insert(lines, string.format("│ Location: %-32s│", location:sub(1, 32)))
    end

    table.insert(lines, "╰───────────────────────────────────────────╯")
    table.insert(lines, "")

    table.insert(lines, "SUBSCRIPTIONS")
    table.insert(lines, "───────────────────────────────────────────")
    if state.subscriptions and #state.subscriptions > 0 then
        for _, sub in ipairs(state.subscriptions) do
            local tag = sub.is_default and "[default]" or "[custom]"
            local pattern_desc = M.describe_pattern(sub.pattern)
            table.insert(lines, string.format("├─ %s %s", tag, pattern_desc:sub(1, 30)))
        end
    else
        table.insert(lines, "  (none)")
    end

    table.insert(lines, "")
    table.insert(lines, "PLAY-BY-PLAY")
    table.insert(lines, "───────────────────────────────────────────")

    if #M.event_log > 0 then
        local start = math.max(1, #M.event_log - 15)
        for i = #M.event_log, start, -1 do
            local ev = M.event_log[i]
            local formatted = M.format_event(ev)
            for _, line in ipairs(formatted) do
                table.insert(lines, line)
            end
        end
    else
        table.insert(lines, "  (no events yet)")
        table.insert(lines, "")
        table.insert(lines, "  Press 'c' to chat with this agent")
    end

    table.insert(lines, "")
    table.insert(lines, "───────────────────────────────────────────")
    table.insert(lines, " [c]hat  [r]efresh  [q]uit")

    vim.api.nvim_buf_set_option(M.buf, "modifiable", true)
    vim.api.nvim_buf_set_lines(M.buf, 0, -1, false, lines)
    vim.api.nvim_buf_set_option(M.buf, "modifiable", false)
end

function M.describe_pattern(pattern)
    if not pattern then
        return "unknown"
    end

    if pattern.to_agent then
        return "to_agent: self"
    elseif pattern.path_glob then
        return "path: " .. pattern.path_glob
    elseif pattern.event_types then
        return "events: " .. table.concat(pattern.event_types, ", ")
    else
        return "custom"
    end
end

function M.format_event(ev)
    local lines = {}
    local time_str = os.date("%H:%M:%S", ev.time)
    local icon = M.get_event_icon(ev.type)

    table.insert(lines, string.format("├─ %s [%s] %s", icon, time_str, ev.type))

    if ev.type == "AgentMessageEvent" then
        local content = ev.data.content or ""
        table.insert(lines, string.format("│  From: %s", (ev.data.from_agent or "?"):sub(1, 20)))
        for _, line in ipairs(M.wrap_text(content, 38)) do
            table.insert(lines, "│  " .. line)
        end
    elseif ev.type == "ToolCallEvent" then
        local tool = ev.data.tool_name or "unknown"
        table.insert(lines, string.format("│  Tool: %s", tool))
    elseif ev.type == "ModelResponseEvent" then
        local content = ev.data.content or ""
        for _, line in ipairs(M.wrap_text(content:sub(1, 200), 38)) do
            table.insert(lines, "│  " .. line)
        end
    elseif ev.type == "AgentStartEvent" then
        table.insert(lines, "│  Agent execution started")
    elseif ev.type == "AgentCompleteEvent" then
        local summary = ev.data.result_summary or ""
        table.insert(lines, "│  Completed: " .. summary:sub(1, 30))
    elseif ev.type == "AgentErrorEvent" then
        local err = ev.data.error or "unknown"
        table.insert(lines, "│  Error: " .. err:sub(1, 35))
    end

    table.insert(lines, "│")
    return lines
end

function M.get_event_icon(event_type)
    local icons = {
        AgentMessageEvent = "[MSG]",
        ToolCallEvent = "[TOOL]",
        ToolResultEvent = "[RES]",
        ModelRequestEvent = "[REQ]",
        ModelResponseEvent = "[RESP]",
        AgentStartEvent = "[START]",
        AgentCompleteEvent = "[DONE]",
        AgentErrorEvent = "[ERROR]",
        ManualTriggerEvent = "[TRIG]",
    }
    return icons[event_type] or "[EVT]"
end

function M.wrap_text(text, width)
    local lines = {}
    local line = ""

    for word in text:gmatch("%S+") do
        if #line + #word + 1 <= width then
            line = line == "" and word or (line .. " " .. word)
        else
            if line ~= "" then
                table.insert(lines, line)
            end
            line = word
        end
    end

    if line ~= "" then
        table.insert(lines, line)
    end

    if #lines > 5 then
        lines = { lines[1], lines[2], lines[3], lines[4], "..." }
    end

    return lines
end

return M
