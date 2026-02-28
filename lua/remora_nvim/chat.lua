-- Remora Chat: Send messages to agents

local M = {}

function M.open()
    local sidepanel = require("remora_nvim.sidepanel")
    local bridge = require("remora_nvim.bridge")

    if not sidepanel.current_agent then
        vim.notify("Remora: No agent selected", vim.log.levels.WARN)
        return
    end

    local agent_id = sidepanel.current_agent
    local agent_name = (sidepanel.current_state and sidepanel.current_state.name) or agent_id

    vim.ui.input({
        prompt = string.format("Chat with %s: ", agent_name),
    }, function(input)
        if input and input ~= "" then
            M.send(agent_id, input)
        end
    end)
end

function M.send(agent_id, message)
    local bridge = require("remora_nvim.bridge")
    local sidepanel = require("remora_nvim.sidepanel")

    vim.notify("Remora: Sending message...", vim.log.levels.INFO)

    sidepanel.add_event_to_log("AgentMessageEvent", {
        from_agent = "user",
        to_agent = agent_id,
        content = message,
    })
    sidepanel.render()

    bridge.send_chat(agent_id, message, function(result)
        if result and result.status == "sent" then
            vim.notify("Remora: Message sent, agent triggered", vim.log.levels.INFO)
        elseif result and result.error then
            vim.notify("Remora: " .. result.error, vim.log.levels.ERROR)
        end
    end)
end

return M
