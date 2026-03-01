-- lua/remora/init.lua
local M = {}

M.sidepanel = nil

function M.setup(opts)
    opts = opts or {}

    vim.lsp.config["remora"] = {
        cmd = { "remora-lsp" },
        filetypes = { "python" },
        root_markers = { ".remora", ".git" },
        settings = {},
    }

    vim.lsp.enable("remora")

    vim.lsp.handlers["$/remora/event"] = M.on_event
    vim.lsp.handlers["$/remora/requestInput"] = M.on_request_input
    vim.lsp.handlers["$/remora/agentSelected"] = M.on_agent_selected

    M.setup_commands()
end

function M.on_event(err, result, ctx)
    if err then
        vim.notify("Remora error: " .. vim.inspect(err), vim.log.levels.ERROR)
        return
    end

    local event = result

    if event.event_type == "RewriteProposalEvent" then
        vim.notify(
            string.format("Agent %s proposes rewrite", event.agent_id),
            vim.log.levels.INFO
        )
    elseif event.event_type == "AgentErrorEvent" then
        vim.notify(
            string.format("Agent error: %s", event.error),
            vim.log.levels.ERROR
        )
    elseif event.event_type == "RewriteAppliedEvent" then
        vim.notify(
            string.format("Proposal %s accepted", event.proposal_id),
            vim.log.levels.INFO
        )
    end

    if M.sidepanel then
        M.sidepanel.add_event(event)
    end
end

function M.on_request_input(err, result, ctx)
    if err then
        vim.notify("Remora input error: " .. vim.inspect(err), vim.log.levels.ERROR)
        return
    end

    local prompt = result.prompt
    local agent_id = result.agent_id
    local proposal_id = result.proposal_id

    vim.ui.input({ prompt = prompt }, function(input)
        if input then
            vim.lsp.buf_notify(0, "$/remora/submitInput", {
                agent_id = agent_id,
                proposal_id = proposal_id,
                input = input
            })
        end
    end)
end

function M.on_agent_selected(err, result, ctx)
    if err then
        vim.notify("Remora selection error: " .. vim.inspect(err), vim.log.levels.ERROR)
        return
    end

    local agent_id = result.agent_id
    M.show_agent_panel(agent_id)
end

function M.setup_commands()
    vim.api.nvim_create_user_command("RemoraChat", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.chat"
            end,
            apply = true
        })
    end, {})

    vim.api.nvim_create_user_command("RemoraRewrite", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.requestRewrite"
            end,
            apply = true
        })
    end, {})

    vim.api.nvim_create_user_command("RemoraAccept", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.acceptProposal"
            end,
            apply = true
        })
    end, {})

    vim.api.nvim_create_user_command("RemoraReject", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.rejectProposal"
            end,
            apply = true
        })
    end, {})

    vim.api.nvim_create_user_command("RemoraTogglePanel", function()
        M.toggle_panel()
    end, {})
end

function M.show_agent_panel(agent_id)
    if not M.sidepanel then
        M.toggle_panel()
    end
    if M.sidepanel then
        M.sidepanel.select_agent(agent_id)
    end
end

function M.toggle_panel()
    if M.sidepanel and M.sidepanel.is_open then
        M.sidepanel.close()
    else
        M.sidepanel = require("remora_nvim.panel")
        M.sidepanel.open()
    end
end

return M
