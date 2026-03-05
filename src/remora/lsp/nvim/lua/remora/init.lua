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
        filetypes = opts.filetypes or { "python", "markdown", "toml" },
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

    -- If a matching buffer was already open before setup() ran (e.g. nv2
    -- was launched with a filename argument), the FileType autocmd that
    -- vim.lsp.enable() installs will have already fired before we
    -- registered.  Re-trigger FileType for those buffers so the LSP
    -- client actually starts.
    local matching_fts = {}
    for _, ft in ipairs(lsp_config.filetypes) do matching_fts[ft] = true end
    for _, buf in ipairs(vim.api.nvim_list_bufs()) do
        if vim.api.nvim_buf_is_loaded(buf) then
            local ft = vim.bo[buf].filetype
            if matching_fts[ft] then
                log.info("M.setup: re-triggering FileType for buf=%d ft=%s", buf, ft)
                vim.api.nvim_buf_call(buf, function()
                    vim.cmd("doautocmd FileType " .. ft)
                end)
            end
        end
    end

    local function setup_highlights()
        -- Status highlights
        vim.api.nvim_set_hl(0, "RemoraActive", { fg = "#a6e3a1" })
        vim.api.nvim_set_hl(0, "RemoraRunning", { fg = "#89b4fa" })
        vim.api.nvim_set_hl(0, "RemoraPending", { fg = "#f9e2af" })
        vim.api.nvim_set_hl(0, "RemoraOrphaned", { fg = "#6c7086" })
        vim.api.nvim_set_hl(0, "RemoraBorder", { fg = "#89b4fa", bg = "NONE" })
        -- Chat panel highlights
        vim.api.nvim_set_hl(0, "RemoraUser", { fg = "#89b4fa", bold = true })      -- blue, user name
        vim.api.nvim_set_hl(0, "RemoraUserText", { fg = "#cdd6f4" })               -- light text, user body
        vim.api.nvim_set_hl(0, "RemoraAgent", { fg = "#a6e3a1", bold = true })     -- green, agent name
        vim.api.nvim_set_hl(0, "RemoraAgentText", { fg = "#a6e3a1" })             -- green, agent body
        vim.api.nvim_set_hl(0, "RemoraToolCall", { fg = "#6c7086", italic = true }) -- muted grey, tool calls
    end

    setup_highlights()
    log.info("M.setup: highlights configured")

    -- -----------------------------------------------------------------------
    -- Client helpers
    -- -----------------------------------------------------------------------

    --- Get the first active remora LSP client, or nil.
    --- @param opts? {silent?: boolean}
    local function get_client(opts)
        opts = opts or {}
        local clients = vim.lsp.get_clients({ name = "remora", bufnr = 0 })
        log.debug("get_client: buffer-attached clients=%d", #clients)
        if #clients == 0 then
            clients = vim.lsp.get_clients({ name = "remora" })
            log.debug("get_client: all remora clients=%d", #clients)
        end
        if #clients == 0 then
            log.warn("get_client: NO remora clients found!")
            if not opts.silent then
                vim.notify("[Remora] LSP not running — is this a supported filetype?", vim.log.levels.WARN)
            end
            return nil
        end
        local client = clients[1]
        log.info("get_client: using client id=%d name=%s", client.id, client.name)
        return client
    end

    --- Attempt to explicitly start the remora client for the current buffer.
    --- Useful when the initial FileType-triggered start races with server lock release.
    --- @param reason string
    local function kick_lsp_start(reason)
        local config = vim.lsp.config["remora"] or lsp_config
        if not config then
            log.warn("kick_lsp_start(%s): missing remora lsp config", reason)
            return false
        end

        local cfg = vim.deepcopy(config)
        cfg.name = "remora"
        local ok, client_id = pcall(vim.lsp.start, cfg, { bufnr = vim.api.nvim_get_current_buf() })
        if not ok then
            log.warn("kick_lsp_start(%s): vim.lsp.start failed: %s", reason, tostring(client_id))
            return false
        end
        log.info("kick_lsp_start(%s): vim.lsp.start returned %s", reason, tostring(client_id))
        return client_id ~= nil
    end

    --- Read owner pid from .remora/lsp.pid if present.
    --- @return integer|nil
    local function read_lock_owner_pid()
        local cwd = (vim.uv and vim.uv.cwd()) or (vim.loop and vim.loop.cwd()) or vim.fn.getcwd()
        if not cwd or cwd == "" then
            return nil
        end
        local pid_path = cwd .. "/.remora/lsp.pid"
        local ok, lines = pcall(vim.fn.readfile, pid_path)
        if not ok or not lines or #lines == 0 then
            return nil
        end
        local pid = tonumber(vim.trim(lines[1] or ""))
        return pid
    end

    --- Build a user-facing lock hint string when lock metadata exists.
    --- @return string|nil
    local function lock_owner_hint()
        local pid = read_lock_owner_pid()
        if not pid then
            return nil
        end

        local uv = vim.uv or vim.loop
        local alive = uv and uv.fs_stat and uv.fs_stat("/proc/" .. tostring(pid)) ~= nil
        if alive then
            return string.format("another workspace lock owner exists (pid=%d)", pid)
        end
        return string.format("stale lock metadata found (pid=%d)", pid)
    end

    --- State for tracking connection attempts
    local connection_state = {
        waiting = false,
        notified = false,
    }

    --- Get client with retry/polling for startup race condition.
    --- Shows user feedback while waiting for LSP to become ready.
    --- @param opts? {silent?: boolean, max_attempts?: number, callback?: fun(client: any)}
    local function get_client_with_retry(opts)
        opts = opts or {}
        local max_attempts = opts.max_attempts or 20  -- ~5 seconds total
        local attempt = 0
        local base_delay_ms = 100

        -- Check immediately first
        local client = get_client({ silent = true })
        if client then
            connection_state.waiting = false
            connection_state.notified = false
            if opts.callback then
                opts.callback(client)
            end
            return client
        end

        -- Start polling
        if not connection_state.waiting then
            connection_state.waiting = true
            if not opts.silent and not connection_state.notified then
                connection_state.notified = true
                vim.notify("[Remora] Connecting to LSP...", vim.log.levels.INFO)
                log.info("get_client_with_retry: starting retry loop, showing 'Connecting' message")
            end
        end
        kick_lsp_start("initial-no-client")

        local function poll()
            attempt = attempt + 1
            log.debug("get_client_with_retry: attempt %d/%d", attempt, max_attempts)

            local c = get_client({ silent = true })
            if not c and (attempt == 1 or attempt % 5 == 0) then
                kick_lsp_start(string.format("retry-%d", attempt))
                c = get_client({ silent = true })
            end
            if c then
                connection_state.waiting = false
                if connection_state.notified then
                    connection_state.notified = false
                    vim.notify("[Remora] LSP connected!", vim.log.levels.INFO)
                    log.info("get_client_with_retry: connected after %d attempts", attempt)
                end
                if opts.callback then
                    opts.callback(c)
                end
                return
            end

            if attempt >= max_attempts then
                connection_state.waiting = false
                connection_state.notified = false
                log.warn("get_client_with_retry: gave up after %d attempts", max_attempts)
                local hint = lock_owner_hint()
                if hint then
                    log.warn("get_client_with_retry: lock hint: %s", hint)
                end
                if not opts.silent then
                    local message = "[Remora] LSP not available — try opening a Python/Markdown/TOML file"
                    if hint then
                        message = message .. " (" .. hint .. ")"
                    end
                    vim.notify(message, vim.log.levels.WARN)
                end
                if opts.callback then
                    opts.callback(nil)
                end
                return
            end

            -- Exponential backoff: 100ms, 150ms, 225ms, ... capped at 500ms
            local delay = math.min(500, base_delay_ms * (1.5 ^ (attempt - 1)))
            vim.defer_fn(poll, delay)
        end

        -- Start polling after initial delay
        vim.defer_fn(poll, base_delay_ms)
        return nil  -- Returns nil immediately; result comes via callback
    end

    --- Send workspace/executeCommand to the remora server.
    --- Uses retry logic to handle LSP startup race condition.
    local function exec_command(command, arguments)
        log.info("exec_command: command=%s arguments=%s", command, vim.inspect(arguments))

        local function do_request(client)
            if not client then
                log.warn("exec_command: no client after retry, aborting")
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

        -- Try immediate get first
        local client = get_client({ silent = true })
        if client then
            do_request(client)
        else
            -- Use retry with callback
            get_client_with_retry({ callback = do_request })
        end
    end

    --- Try to apply a code action matching `command_name`.
    --- Uses retry logic to handle LSP startup race condition.
    local function apply_code_action(command_name, not_found_msg)
        log.info("apply_code_action: command=%s", command_name)

        local function do_action(client)
            if not client then
                log.warn("apply_code_action: no client after retry")
                return
            end
            vim.lsp.buf.code_action({
                filter = function(action)
                    return action.command
                        and action.command.command == command_name
                end,
                apply = true,
            })
        end

        -- Try immediate get first
        local client = get_client({ silent = true })
        if client then
            do_action(client)
        else
            -- Use retry with callback
            get_client_with_retry({ callback = do_action })
        end
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
        get_client = function() return get_client({ silent = true }) end,
        get_client_with_retry = function(opts)
            return get_client_with_retry({
                silent = opts and opts.silent,
                callback = opts and opts.callback,
            })
        end,
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

    -- -----------------------------------------------------------------------
    -- Always-on cursor tracking (for web graph view)
    -- -----------------------------------------------------------------------

    vim.api.nvim_create_autocmd("CursorHold", {
        callback = function()
            local ft = vim.bo.filetype
            if ft ~= "python" and ft ~= "markdown" and ft ~= "toml" then return end
            local client = get_client({ silent = true })
            if not client then return end
            local ctx = cursor_context()
            client.notify("$/remora/cursorMoved", ctx)
        end,
    })
    log.info("M.setup: CursorHold autocmd registered for cursor tracking")

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
