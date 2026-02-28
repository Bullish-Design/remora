-- Remora Bridge: JSON-RPC client with push notification support

local M = {}

M.client = nil
M.callbacks = {}
M.next_id = 1
M.current_subscription = nil
M.notification_handlers = {}

-- ============================================================================
-- Connection Management
-- ============================================================================

function M.setup(socket_path)
    M.client = vim.loop.new_pipe(false)

    M.client:connect(socket_path, function(err)
        if err then
            vim.schedule(function()
                vim.notify("Remora: Failed to connect to " .. socket_path .. ": " .. err, vim.log.levels.ERROR)
            end)
            return
        end

        M.client:read_start(function(read_err, data)
            if read_err then
                vim.schedule(function()
                    vim.notify("Remora: Read error: " .. read_err, vim.log.levels.ERROR)
                end)
                return
            end
            if data then
                M.handle_incoming(data)
            end
        end)

        vim.schedule(function()
            vim.notify("Remora: Connected!", vim.log.levels.INFO)
        end)
    end)
end

-- ============================================================================
-- RPC Calls
-- ============================================================================

function M.call(method, params, callback)
    if not M.client then
        vim.notify("Remora: Not connected", vim.log.levels.WARN)
        return
    end

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

-- ============================================================================
-- Handle Incoming Data (Responses + Notifications)
-- ============================================================================

function M.handle_incoming(data)
    for line in data:gmatch("[^\n]+") do
        local ok, msg = pcall(vim.fn.json_decode, line)
        if ok and msg then
            if msg.id and M.callbacks[msg.id] then
                vim.schedule(function()
                    M.callbacks[msg.id](msg.result)
                    M.callbacks[msg.id] = nil
                end)
            elseif msg.method then
                vim.schedule(function()
                    M.handle_notification(msg.method, msg.params)
                end)
            end
        end
    end
end

-- ============================================================================
-- Notification Handling
-- ============================================================================

function M.handle_notification(method, params)
    if method == "event.push" then
        local agent_id = params.agent_id
        local event_type = params.event_type
        local event_data = params.data or {}

        require("remora_nvim.sidepanel").on_event_push(agent_id, event_type, event_data)
    end
end

-- ============================================================================
-- Subscription Management
-- ============================================================================

function M.subscribe_to_agent(agent_id)
    if M.current_subscription == agent_id then
        return
    end

    M.current_subscription = agent_id

    M.call("agent.subscribe", { agent_id = agent_id }, function(result)
        if result and result.subscribed then
            -- Subscription confirmed
        end
    end)
end

-- ============================================================================
-- Convenience Methods
-- ============================================================================

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

        if callback then
            callback(result)
        end
    end)
end

function M.send_chat(agent_id, message, callback)
    M.call("agent.chat", { agent_id = agent_id, message = message }, callback)
end

function M.get_agent_events(agent_id, callback)
    M.call("agent.get_events", { agent_id = agent_id }, callback)
end

return M
