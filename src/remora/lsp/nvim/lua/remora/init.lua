-- src/remora/lsp/nvim/lua/remora/init.lua
-- This IS the remora module. Export the panel + setup.
local M = {}

local panel = require("remora.panel")
local log = require("remora.log")

M.panel = panel

function M.setup(opts)
    opts = opts or {}
    log.init()
    log.info("M.setup: called with opts=%s", vim.inspect(opts))

    if not vim.lsp or not vim.lsp.config then
        vim.notify(
            "[Remora] Neovim 0.11+ required for LSP integration",
            vim.log.levels.ERROR
        )
        log.error("M.setup: vim.lsp or vim.lsp.config not available!")
        return
    end

    local lsp_config = {
        cmd = opts.cmd or { "remora-lsp" },
        filetypes = opts.filetypes or { "python" },
        root_markers = opts.root_markers or { ".remora", ".git" },
        settings = opts.settings or {},
    }
    log.info("M.setup: LSP config: cmd=%s filetypes=%s root_markers=%s",
        vim.inspect(lsp_config.cmd),
        vim.inspect(lsp_config.filetypes),
        vim.inspect(lsp_config.root_markers))

    vim.lsp.config["remora"] = lsp_config
    vim.lsp.enable("remora")
    log.info("M.setup: vim.lsp.enable('remora') called")

    local function setup_highlights()
        vim.api.nvim_set_hl(0, "RemoraActive", { fg = "#a6e3a1" })
        vim.api.nvim_set_hl(0, "RemoraRunning", { fg = "#89b4fa" })
        vim.api.nvim_set_hl(0, "RemoraPending", { fg = "#f9e2af" })
        vim.api.nvim_set_hl(0, "RemoraOrphaned", { fg = "#6c7086" })
        vim.api.nvim_set_hl(0, "RemoraBorder", { fg = "#89b4fa", bg = "NONE" })
    end

    setup_highlights()
    log.info("M.setup: highlights configured")

    -- -----------------------------------------------------------------------
    -- Client helpers
    -- -----------------------------------------------------------------------

    --- Get the first active remora LSP client, or nil.
    local function get_client()
        local clients = vim.lsp.get_clients({ name = "remora", bufnr = 0 })
        log.debug("get_client: buffer-attached clients=%d", #clients)
        if #clients == 0 then
            clients = vim.lsp.get_clients({ name = "remora" })
            log.debug("get_client: all remora clients=%d", #clients)
        end
        if #clients == 0 then
            log.warn("get_client: NO remora clients found!")
            vim.notify("[Remora] LSP not running — is this a supported filetype?", vim.log.levels.WARN)
            return nil
        end
        local client = clients[1]
        log.info("get_client: using client id=%d name=%s", client.id, client.name)
        return client
    end

    --- Send workspace/executeCommand to the remora server.
    local function exec_command(command, arguments)
        log.info("exec_command: command=%s arguments=%s", command, vim.inspect(arguments))
        local client = get_client()
        if not client then
            log.warn("exec_command: no client, aborting")
            return
        end
        client.request("workspace/executeCommand", {
            command = command,
            arguments = arguments or {},
        }, function(err, result)
            if err then
                log.error("exec_command: ERROR response: %s", vim.inspect(err))
                vim.notify(
                    "[Remora] " .. (err.message or tostring(err)),
                    vim.log.levels.ERROR
                )
            else
                log.info("exec_command: OK response: %s", vim.inspect(result))
            end
        end)
        log.info("exec_command: request sent")
    end

    --- Try to apply a code action matching `command_name`.
    local function apply_code_action(command_name, not_found_msg)
        log.info("apply_code_action: command=%s", command_name)
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

    --- Get the current buffer URI + cursor line (1-based) for agent resolution.
    local function cursor_context()
        local buf = vim.api.nvim_get_current_buf()
        local uri = vim.uri_from_bufnr(buf)
        local row, _col = unpack(vim.api.nvim_win_get_cursor(0))
        log.info("cursor_context: buf=%d uri=%s row=%d", buf, uri, row)
        return { uri = uri, line = row }
    end

    -- -----------------------------------------------------------------------
    -- Configure panel with callbacks
    -- -----------------------------------------------------------------------

    panel.configure({
        exec_command = exec_command,
        cursor_context = cursor_context,
        get_client = get_client,
    })
    log.info("M.setup: panel configured with callbacks")

    -- -----------------------------------------------------------------------
    -- LSP notification handlers
    -- -----------------------------------------------------------------------

    vim.lsp.handlers["$/remora/event"] = function(_, result)
        log.info("HANDLER $/remora/event: event_type=%s agent=%s",
            tostring(result and result.event_type or "nil"),
            tostring(result and result.agent_id or "nil"))
        log.dump("DEBUG", "$/remora/event result", result)
        if panel.is_open() then
            local ok, err = pcall(panel.on_event, result)
            if not ok then
                log.error("HANDLER $/remora/event: panel.on_event FAILED: %s", tostring(err))
            end
        end
    end

    vim.lsp.handlers["$/remora/requestInput"] = function(_, result)
        log.info("HANDLER $/remora/requestInput: result=%s", vim.inspect(result))

        -- If the panel is open and showing this agent, route to panel input
        if panel.is_open() and panel._agent
            and result.agent_id and result.agent_id == panel._agent.id then
            log.info("HANDLER $/remora/requestInput: panel is open for this agent, focusing input")
            if panel._input_win and vim.api.nvim_win_is_valid(panel._input_win) then
                vim.api.nvim_set_current_win(panel._input_win)
                vim.cmd("startinsert")
            end
            return
        end

        -- Fallback: use vim.ui.input
        local prompt = result.prompt or "Input:"
        vim.ui.input({ prompt = prompt }, function(input)
            log.info("HANDLER $/remora/requestInput: user input=%s", vim.inspect(input))
            if input then
                local params = { input = input }
                if result.agent_id then
                    params.agent_id = result.agent_id
                end
                if result.proposal_id then
                    params.proposal_id = result.proposal_id
                end
                log.info("HANDLER $/remora/requestInput: sending $/remora/submitInput params=%s", vim.inspect(params))
                vim.lsp.buf_notify(0, "$/remora/submitInput", params)
                log.info("HANDLER $/remora/requestInput: buf_notify sent")
            else
                log.info("HANDLER $/remora/requestInput: user cancelled input")
            end
        end)
    end

    vim.lsp.handlers["$/remora/agentSelected"] = function(_, result)
        log.info("HANDLER $/remora/agentSelected: agent_id=%s", tostring(result and result.agent_id or "nil"))
    end

    -- -----------------------------------------------------------------------
    -- User commands
    -- -----------------------------------------------------------------------

    local function setup_commands()
        vim.api.nvim_create_user_command("RemoraChat", function()
            log.info("CMD RemoraChat")
            exec_command("remora.chat", { cursor_context() })
        end, {})

        vim.api.nvim_create_user_command("RemoraRewrite", function()
            log.info("CMD RemoraRewrite")
            exec_command("remora.requestRewrite", { cursor_context() })
        end, {})

        vim.api.nvim_create_user_command("RemoraAccept", function()
            log.info("CMD RemoraAccept")
            apply_code_action("remora.acceptProposal",
                "No pending proposal at cursor")
        end, {})

        vim.api.nvim_create_user_command("RemoraReject", function()
            log.info("CMD RemoraReject")
            apply_code_action("remora.rejectProposal",
                "No pending proposal at cursor")
        end, {})

        vim.api.nvim_create_user_command("RemoraTogglePanel", function()
            log.info("CMD RemoraTogglePanel")
            M.toggle_panel()
        end, {})
    end

    setup_commands()
    log.info("M.setup: user commands registered")

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
    log.info("M.setup: keymaps set with prefix=%s", prefix)

    -- Close log on exit
    vim.api.nvim_create_autocmd("VimLeavePre", {
        callback = function()
            log.info("VimLeavePre: closing remora log")
            log.close()
        end,
    })

    log.info("M.setup: COMPLETE")
end

function M.toggle_panel()
    log.info("toggle_panel: is_open=%s", tostring(panel.is_open()))
    if panel.is_open() then
        panel.close()
    else
        panel.open()
    end
end

return M
