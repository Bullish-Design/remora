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

    --- Get the first active remora LSP client, or nil.
    local function get_client()
        -- Try buffer-attached clients first, then fall back to all clients.
        local clients = vim.lsp.get_clients({ name = "remora", bufnr = 0 })
        if #clients == 0 then
            clients = vim.lsp.get_clients({ name = "remora" })
        end
        if #clients == 0 then
            vim.notify("[Remora] LSP not running — is this a supported filetype?", vim.log.levels.WARN)
            return nil
        end
        return clients[1]
    end

    --- Send workspace/executeCommand to the remora server.
    local function exec_command(command, arguments)
        local client = get_client()
        if not client then return end
        client.request("workspace/executeCommand", {
            command = command,
            arguments = arguments or {},
        }, function(err)
            if err then
                vim.notify(
                    "[Remora] " .. (err.message or tostring(err)),
                    vim.log.levels.ERROR
                )
            end
        end)
    end

    --- Try to apply a code action matching `command_name`.
    --- Shows a friendly message instead of the cryptic default error.
    local function apply_code_action(command_name, not_found_msg)
        local client = get_client()
        if not client then return end
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command
                    and action.command.command == command_name
            end,
            apply = true,
        })
    end

    local function setup_commands()
        vim.api.nvim_create_user_command("RemoraChat", function()
            exec_command("remora.chat")
        end, {})

        vim.api.nvim_create_user_command("RemoraRewrite", function()
            exec_command("remora.requestRewrite")
        end, {})

        vim.api.nvim_create_user_command("RemoraAccept", function()
            apply_code_action("remora.acceptProposal",
                "No pending proposal at cursor")
        end, {})

        vim.api.nvim_create_user_command("RemoraReject", function()
            apply_code_action("remora.rejectProposal",
                "No pending proposal at cursor")
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
