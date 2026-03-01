-- src/remora/lsp/nvim/lua/remora/init.lua
-- This IS the remora module. Export the panel + setup.
local M = {}

local panel = require("remora.panel")

M.panel = panel

function M.setup(opts)
    opts = opts or {}

    if not vim.lsp or not vim.lsp.config then
        vim.notify(
            "[Remora] Neovim 0.11+ required for LSP integration",
            vim.log.levels.ERROR
        )
        return
    end

    vim.lsp.config["remora"] = {
        cmd = opts.cmd or { "remora-lsp" },
        filetypes = opts.filetypes or { "python" },
        root_markers = opts.root_markers or { ".remora", ".git" },
        settings = opts.settings or {},
    }

    vim.lsp.enable("remora")

    local function setup_highlights()
        vim.api.nvim_set_hl(
            0, "RemoraActive", { fg = "#a6e3a1" }
        )
        vim.api.nvim_set_hl(
            0, "RemoraRunning", { fg = "#89b4fa" }
        )
        vim.api.nvim_set_hl(
            0, "RemoraPending", { fg = "#f9e2af" }
        )
        vim.api.nvim_set_hl(
            0, "RemoraOrphaned", { fg = "#6c7086" }
        )
        vim.api.nvim_set_hl(
            0, "RemoraBorder",
            { fg = "#89b4fa", bg = "NONE" }
        )
    end

    setup_highlights()

    vim.lsp.handlers["$/remora/event"] = function(_, result)
        panel.add_event(result)
    end

    vim.lsp.handlers["$/remora/requestInput"] = function(_, result)
        local prompt = result.prompt or "Input:"
        vim.ui.input({ prompt = prompt }, function(input)
            if input then
                local params = { input = input }
                if result.agent_id then
                    params.agent_id = result.agent_id
                end
                if result.proposal_id then
                    params.proposal_id = result.proposal_id
                end
                vim.lsp.buf_notify(
                    0, "$/remora/submitInput", params
                )
            end
        end)
    end

    vim.lsp.handlers["$/remora/agentSelected"] = function(_, result)
        panel.select_agent(result.agent_id)
    end

    local function setup_commands()
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

    setup_commands()

    local prefix = opts.prefix or "<leader>r"

    vim.keymap.set(
        "n", prefix .. "a", M.toggle_panel,
        { desc = "Toggle Remora agent panel" }
    )
    vim.keymap.set(
        "n", prefix .. "c",
        function() vim.cmd("RemoraChat") end,
        { desc = "Chat with Remora agent" }
    )
    vim.keymap.set(
        "n", prefix .. "r",
        function() vim.cmd("RemoraRewrite") end,
        { desc = "Request agent rewrite" }
    )
    vim.keymap.set(
        "n", prefix .. "y",
        function() vim.cmd("RemoraAccept") end,
        { desc = "Accept proposal" }
    )
    vim.keymap.set(
        "n", prefix .. "n",
        function() vim.cmd("RemoraReject") end,
        { desc = "Reject proposal" }
    )
end

function M.toggle_panel()
    if panel.is_open() then
        panel.close()
    else
        panel.open()
    end
end

return M
