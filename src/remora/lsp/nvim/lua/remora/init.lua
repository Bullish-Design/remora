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

    local function now_ms()
        local uv = vim.uv or vim.loop
        if uv and uv.hrtime then
            return math.floor(uv.hrtime() / 1000000)
        end
        return math.floor(os.clock() * 1000)
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
        local clients = vim.lsp.get_clients({ name = "remora", bufnr = 0, _uninitialized = true })
        log.debug("get_client: buffer-attached clients=%d", #clients)
        if #clients == 0 then
            clients = vim.lsp.get_clients({ name = "remora", _uninitialized = true })
            log.debug("get_client: all remora clients=%d", #clients)
        end
        if #clients == 0 then
            if opts.silent then
                log.debug("get_client: no remora clients found (silent)")
            else
                log.warn("get_client: NO remora clients found!")
                vim.notify("[Remora] LSP not running — is this a supported filetype?", vim.log.levels.WARN)
            end
            return nil
        end
        local client = clients[1]
        log.info("get_client: using client id=%d name=%s", client.id, client.name)
        return client
    end

    --- Only start remora from an actual user file buffer (not synthetic buffers).
    --- Synthetic startup buffers caused hard-to-debug delayed attach behavior.
    --- @param buf integer
    --- @return boolean
    local function is_startable_buffer(buf)
        if not vim.api.nvim_buf_is_valid(buf) or not vim.api.nvim_buf_is_loaded(buf) then
            return false
        end
        if vim.bo[buf].buftype ~= "" then
            return false
        end
        local ft = vim.bo[buf].filetype
        if not matching_fts[ft] then
            return false
        end
        local name = vim.api.nvim_buf_get_name(buf)
        if not name or name == "" then
            return false
        end
        return true
    end

    --- Pick the best real buffer for explicit startup.
    --- @return integer|nil
    local function find_startable_buffer()
        local current = vim.api.nvim_get_current_buf()
        if is_startable_buffer(current) then
            return current
        end
        for _, buf in ipairs(vim.api.nvim_list_bufs()) do
            if is_startable_buffer(buf) then
                return buf
            end
        end
        return nil
    end

    --- Attempt to explicitly start the remora client for a real user buffer.
    --- Useful when the initial FileType-triggered start races with server lock release.
    --- @return boolean started
    --- @return integer|nil client_id
    --- @param reason string
    local last_kick_ns = 0
    local min_kick_interval_ms = tonumber(vim.env.REMORA_LSP_KICK_MIN_MS or "200") or 200
    local function kick_lsp_start(reason)
        local uv = vim.uv or vim.loop
        if uv and uv.hrtime then
            local now_ns = uv.hrtime()
            if last_kick_ns > 0 and (now_ns - last_kick_ns) < (min_kick_interval_ms * 1000000) then
                log.debug(
                    "kick_lsp_start(%s): throttled (min_interval_ms=%d)",
                    reason,
                    min_kick_interval_ms
                )
                return false, nil
            end
            last_kick_ns = now_ns
        end

        local config = vim.lsp.config["remora"] or lsp_config
        if not config then
            log.warn("kick_lsp_start(%s): missing remora lsp config", reason)
            return false, nil
        end

        local cfg = vim.deepcopy(config)
        cfg.name = "remora"
        -- Ensure startup can resolve a workspace root.
        if not cfg.root_dir then
            local cwd = (vim.uv and vim.uv.cwd()) or (vim.loop and vim.loop.cwd()) or vim.fn.getcwd()
            if cwd and cwd ~= "" then
                cfg.root_dir = cwd
                log.info("kick_lsp_start(%s): using root_dir=%s", reason, cwd)
            end
        end

        local start_buf = find_startable_buffer()
        if not start_buf then
            log.debug("kick_lsp_start(%s): no real supported file buffer available yet", reason)
            return false, nil
        end
        local start_ft = vim.bo[start_buf].filetype

        local ok, client_id = pcall(vim.lsp.start, cfg, { bufnr = start_buf })
        if not ok then
            log.warn("kick_lsp_start(%s): vim.lsp.start failed: %s", reason, tostring(client_id))
            return false, nil
        end
        log.info(
            "kick_lsp_start(%s): vim.lsp.start returned %s (buf=%d ft=%s)",
            reason,
            tostring(client_id),
            start_buf,
            tostring(start_ft)
        )
        return client_id ~= nil, client_id
    end

    --- Read lock-owner metadata from .remora/lsp.pid if present.
    --- Format:
    ---  line 1: pid
    ---  line 2: heartbeat epoch ms (new) or seconds (legacy)
    ---  line 3: parent pid (new)
    --- @return {pid: integer|nil, heartbeat_ms: integer|nil, parent_pid: integer|nil, pid_path: string|nil}
    local function read_lock_owner_metadata()
        local cwd = (vim.uv and vim.uv.cwd()) or (vim.loop and vim.loop.cwd()) or vim.fn.getcwd()
        if not cwd or cwd == "" then
            return { pid = nil, heartbeat_ms = nil, parent_pid = nil, pid_path = nil }
        end
        local pid_path = cwd .. "/.remora/lsp.pid"
        local ok, lines = pcall(vim.fn.readfile, pid_path)
        if not ok or not lines or #lines == 0 then
            return { pid = nil, heartbeat_ms = nil, parent_pid = nil, pid_path = pid_path }
        end
        local pid = tonumber(vim.trim(lines[1] or ""))
        local heartbeat_ms = nil
        local parent_pid = nil
        if lines[2] ~= nil then
            local raw = tonumber(vim.trim(lines[2] or ""))
            if raw then
                -- Legacy format stored whole seconds.
                heartbeat_ms = raw < 10000000000 and (raw * 1000) or raw
            end
        end
        if lines[3] ~= nil then
            parent_pid = tonumber(vim.trim(lines[3] or ""))
        end
        return { pid = pid, heartbeat_ms = heartbeat_ms, parent_pid = parent_pid, pid_path = pid_path }
    end

    --- Build a user-facing lock hint string when lock metadata exists.
    --- @return string|nil
    local function lock_owner_hint()
        local owner = read_lock_owner_metadata()
        local pid = owner.pid
        if not pid then
            return nil
        end

        local uv = vim.uv or vim.loop
        local proc_supported = uv and uv.fs_stat and uv.fs_stat("/proc") ~= nil
        local alive = proc_supported and uv.fs_stat("/proc/" .. tostring(pid)) ~= nil
        if proc_supported and not alive then
            local pid_path = owner.pid_path
            if pid_path and pid_path ~= "" then
                local ok_delete, rc = pcall(vim.fn.delete, pid_path)
                if ok_delete and rc == 0 then
                    return nil
                end
            end
            return string.format("stale lock metadata found (pid=%d)", pid)
        end
        if not proc_supported then
            return string.format("lock owner exists but liveness unknown (pid=%d)", pid)
        end

        local stale_ms = tonumber(vim.env.REMORA_LSP_STALE_OWNER_MS or "45000") or 45000
        local now_ms = math.floor(os.time() * 1000)
        local heartbeat_ms = owner.heartbeat_ms
        local parent_pid = owner.parent_pid
        if parent_pid ~= nil then
            if parent_pid <= 1 then
                return string.format("lock owner appears orphaned (pid=%d parent=%d)", pid, parent_pid)
            end
            local parent_alive = uv and uv.fs_stat and uv.fs_stat("/proc/" .. tostring(parent_pid)) ~= nil
            if not parent_alive then
                return string.format("lock owner appears orphaned (pid=%d parent=%d dead)", pid, parent_pid)
            end
        end
        if heartbeat_ms ~= nil then
            local age_ms = math.max(0, now_ms - heartbeat_ms)
            if age_ms > stale_ms then
                return string.format("lock owner alive but stale heartbeat (pid=%d age=%.1fs)", pid, age_ms / 1000.0)
            end
            return string.format("another workspace lock owner exists (pid=%d heartbeat_age=%.1fs)", pid, age_ms / 1000.0)
        end

        return string.format("lock owner exists but heartbeat unknown (pid=%d)", pid)
    end

    --- State for tracking connection attempts
    local connection_state = {
        waiting = false,
        notified = false,
        autostart_attempted = false,
        autostart_retrying = false,
        autostart_retry_attempt = 0,
        autostart_retry_max_attempts = tonumber(vim.env.REMORA_LSP_AUTOSTART_RETRY_MAX or "60") or 60,
        autostart_timeout_ms = tonumber(vim.env.REMORA_LSP_AUTOSTART_TIMEOUT_MS or "3000") or 3000,
        autostart_last_lock_hint = nil,
        autostart_pending_client_id = nil,
        autostart_pending_started_ms = nil,
        autostart_recycled = false,
    }

    local function reset_startup_tracking()
        connection_state.autostart_retrying = false
        connection_state.autostart_retry_attempt = 0
        connection_state.autostart_last_lock_hint = nil
        connection_state.autostart_pending_client_id = nil
        connection_state.autostart_pending_started_ms = nil
        connection_state.autostart_recycled = false
    end

    --- Stop any startup client(s) to break out of a stuck pending attach state.
    --- @param reason string
    local function recycle_startup_clients(reason)
        local ids = {}
        local seen = {}
        local pending_id = connection_state.autostart_pending_client_id
        if pending_id then
            table.insert(ids, pending_id)
            seen[pending_id] = true
        end
        for _, client in ipairs(vim.lsp.get_clients({ name = "remora", _uninitialized = true })) do
            if not seen[client.id] then
                table.insert(ids, client.id)
                seen[client.id] = true
            end
        end
        if #ids == 0 then
            log.debug("recycle_startup_clients(%s): no remora clients to stop", reason)
            return
        end
        for _, id in ipairs(ids) do
            local ok = pcall(vim.lsp.stop_client, id, true)
            if not ok then
                ok = pcall(vim.lsp.stop_client, id)
            end
            if ok then
                log.warn("recycle_startup_clients(%s): requested stop for client id=%d", reason, id)
            else
                log.warn("recycle_startup_clients(%s): failed to stop client id=%d", reason, id)
            end
        end
        connection_state.autostart_pending_client_id = nil
        connection_state.autostart_pending_started_ms = nil
        last_kick_ns = 0
    end

    --- Keep trying to connect in the background so startup does not depend on
    --- the first user command to trigger retry logic.
    --- @param reason string
    local function ensure_autostart_connected(reason)
        if get_client({ silent = true }) then
            reset_startup_tracking()
            log.info("ensure_autostart_connected(%s): client already available", reason)
            return
        end

        if connection_state.autostart_retrying then
            log.debug("ensure_autostart_connected(%s): retry loop already running", reason)
            return
        end

        connection_state.autostart_retrying = true
        connection_state.autostart_retry_attempt = 0
        connection_state.autostart_last_lock_hint = nil
        connection_state.autostart_pending_client_id = nil
        connection_state.autostart_pending_started_ms = nil
        connection_state.autostart_recycled = false
        local max_attempts = connection_state.autostart_retry_max_attempts
        local base_delay_ms = 120

        local function report_lock_hint_if_any(attempt)
            if attempt ~= 1 and (attempt % 5) ~= 0 then
                return
            end
            local hint = lock_owner_hint()
            if not hint then
                if connection_state.autostart_last_lock_hint ~= nil then
                    log.info("ensure_autostart_connected: lock hint cleared while retrying")
                end
                connection_state.autostart_last_lock_hint = nil
                return
            end
            if connection_state.autostart_last_lock_hint ~= hint then
                connection_state.autostart_last_lock_hint = hint
                log.warn(
                    "ensure_autostart_connected: lock hint while retrying attempt=%d/%d: %s",
                    attempt,
                    max_attempts,
                    hint
                )
                vim.notify("[Remora] Startup waiting: " .. hint, vim.log.levels.WARN)
            else
                log.debug(
                    "ensure_autostart_connected: lock hint unchanged attempt=%d/%d: %s",
                    attempt,
                    max_attempts,
                    hint
                )
            end
        end

        local function poll()
            if get_client({ silent = true }) then
                local retries = connection_state.autostart_retry_attempt
                reset_startup_tracking()
                log.info(
                    "ensure_autostart_connected: connected after %d startup retries",
                    retries
                )
                return
            end

            connection_state.autostart_retry_attempt = connection_state.autostart_retry_attempt + 1
            local attempt = connection_state.autostart_retry_attempt
            if attempt > max_attempts then
                local hint = lock_owner_hint()
                log.warn(
                    "ensure_autostart_connected: gave up after %d retries",
                    max_attempts
                )
                if hint then
                    log.warn("ensure_autostart_connected: final lock hint: %s", hint)
                end
                reset_startup_tracking()
                return
            end

            report_lock_hint_if_any(attempt)

            if connection_state.autostart_pending_client_id ~= nil
                and connection_state.autostart_pending_started_ms ~= nil
            then
                local elapsed_ms = now_ms() - connection_state.autostart_pending_started_ms
                if (not connection_state.autostart_recycled) and elapsed_ms >= connection_state.autostart_timeout_ms then
                    local pending = tostring(connection_state.autostart_pending_client_id)
                    log.warn(
                        "ensure_autostart_connected: startup timeout elapsed_ms=%d pending_client_id=%s; recycling",
                        elapsed_ms,
                        pending
                    )
                    recycle_startup_clients("startup-timeout")
                    connection_state.autostart_recycled = true
                end
            end

            if connection_state.autostart_pending_client_id == nil then
                local started, client_id = kick_lsp_start(string.format("autostart-retry-%d", attempt))
                if started and client_id ~= nil then
                    connection_state.autostart_pending_client_id = client_id
                    connection_state.autostart_pending_started_ms = now_ms()
                    connection_state.autostart_recycled = false
                    log.info(
                        "ensure_autostart_connected: start requested attempt=%d client_id=%d",
                        attempt,
                        client_id
                    )
                end
            end

            local delay = math.min(1000, math.floor(base_delay_ms * (1.35 ^ (attempt - 1))))
            vim.defer_fn(poll, delay)
        end

        local started, client_id = kick_lsp_start(reason)
        if started and client_id ~= nil then
            connection_state.autostart_pending_client_id = client_id
            connection_state.autostart_pending_started_ms = now_ms()
            connection_state.autostart_recycled = false
        else
            connection_state.autostart_pending_client_id = nil
            connection_state.autostart_pending_started_ms = nil
        end
        log.info(
            "ensure_autostart_connected(%s): start_requested=%s client_id=%s",
            reason,
            tostring(started),
            tostring(client_id)
        )
        vim.defer_fn(poll, base_delay_ms)
    end

    --- Ensure remora-lsp startup orchestration is active for this session.
    --- A real supported file buffer is still required before explicit startup.
    --- Safe to call repeatedly.
    --- @param reason string
    local function autostart_lsp(reason)
        if not connection_state.autostart_attempted then
            connection_state.autostart_attempted = true
        else
            log.debug("autostart_lsp(%s): startup already attempted; ensuring connection", reason)
        end
        ensure_autostart_connected(reason)
    end

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

        -- Ensure the single startup loop is active; do not start in this loop.
        ensure_autostart_connected("interactive-retry")

        local function poll()
            attempt = attempt + 1
            log.debug("get_client_with_retry: attempt %d/%d", attempt, max_attempts)

            local c = get_client({ silent = true })
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
        local ok, err = pcall(panel.on_event, result)
        if not ok then
            log.error("HANDLER $/remora/event: panel.on_event FAILED: %s", tostring(err))
        end
    end

    vim.lsp.handlers["$/remora/requestInput"] = function(_, result)
        log.info("HANDLER $/remora/requestInput: result=%s", vim.inspect(result))
        local panel_open = panel.is_open()
        local panel_agent_id = panel._agent and panel._agent.id or nil
        local requested_agent_id = result and result.agent_id or nil
        local input_win_valid = panel._input_win and vim.api.nvim_win_is_valid(panel._input_win) or false
        log.info(
            "HANDLER $/remora/requestInput: routing panel_open=%s panel_agent=%s requested_agent=%s input_win_valid=%s",
            tostring(panel_open),
            tostring(panel_agent_id),
            tostring(requested_agent_id),
            tostring(input_win_valid)
        )

        -- If the panel is open and showing this agent, route to panel input
        if panel_open and panel._agent
            and requested_agent_id and requested_agent_id == panel._agent.id then
            log.info("HANDLER $/remora/requestInput: panel is open for this agent, focusing input")
            if result.request_id then
                panel.set_pending_request({
                    request_id = result.request_id,
                    prompt = result.prompt,
                    agent_id = result.agent_id,
                    node_id = result.node_id,
                    question = result.question,
                })
            end
            if input_win_valid then
                vim.api.nvim_set_current_win(panel._input_win)
                vim.cmd("startinsert")
                log.info("HANDLER $/remora/requestInput: panel input focused; waiting for Enter submit")
                return
            end
            log.warn("HANDLER $/remora/requestInput: agent matched but input window invalid; falling back to vim.ui.input")
        elseif panel_open and requested_agent_id then
            -- Panel is open but showing a different agent.  Switch the panel to
            -- track the chat target so live events (model response, etc.) are
            -- displayed rather than silently dropped, then focus the input window.
            log.info("HANDLER $/remora/requestInput: panel agent mismatch; switching panel to agent=%s", requested_agent_id)
            panel.switch_agent(requested_agent_id)
            if result.request_id then
                panel.set_pending_request({
                    request_id = result.request_id,
                    prompt = result.prompt,
                    agent_id = result.agent_id,
                    node_id = result.node_id,
                    question = result.question,
                })
            end
            if input_win_valid then
                vim.api.nvim_set_current_win(panel._input_win)
                vim.cmd("startinsert")
                log.info("HANDLER $/remora/requestInput: panel switched and input focused")
                return
            end
            log.warn("HANDLER $/remora/requestInput: panel switched but input window invalid; falling back to vim.ui.input")
        else
            log.info("HANDLER $/remora/requestInput: panel closed; using vim.ui.input fallback")
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
                if result.request_id then
                    params.request_id = result.request_id
                end
                if result.node_id then
                    params.node_id = result.node_id
                end
                if result.question then
                    params.question = result.question
                end
                log.info("HANDLER $/remora/requestInput: sending $/remora/submitInput params=%s", vim.inspect(params))
                local client = get_client({ silent = true })
                if client then
                    client.notify("$/remora/submitInput", params)
                    log.info("HANDLER $/remora/requestInput: explicit client.notify sent")
                else
                    vim.lsp.buf_notify(0, "$/remora/submitInput", params)
                    log.info("HANDLER $/remora/requestInput: buf_notify sent (fallback)")
                end
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
    local function open_companion_sidebar()
        if vim.fn.exists(":CompanionSidebar") == 2 then
            vim.cmd("CompanionSidebar")
            return
        end
        M.toggle_panel()
    end

    local function companion_chat()
        if vim.fn.exists(":CompanionChat") == 2 then
            vim.cmd("CompanionChat")
            return
        end
        vim.cmd("RemoraChat")
    end

    -- Add a group label to the first <space> popup (which-key) when available.
    local wk_ok, wk = pcall(require, "which-key")
    if wk_ok then
        if wk.add then
            wk.add({
                { prefix, group = "Remora - AI Code Assistant" },
            })
        elseif wk.register and prefix == "<leader>r" then
            wk.register({
                r = { name = "+Remora - AI Code Assistant" },
            }, { prefix = "<leader>" })
        end
    end

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
    vim.keymap.set(
        "n", prefix .. "s", open_companion_sidebar,
        { desc = "Open Companion sidebar" }
    )
    vim.keymap.set(
        "n", prefix .. "m", companion_chat,
        { desc = "Chat with Companion" }
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

    -- Proactive startup so chat/panel commands can work before opening a file.
    vim.schedule(function()
        autostart_lsp("setup-autostart")
    end)
    vim.api.nvim_create_autocmd("VimEnter", {
        once = true,
        callback = function()
            autostart_lsp("vimenter-autostart")
        end,
    })
    vim.api.nvim_create_autocmd({ "BufEnter", "BufWinEnter", "FileType" }, {
        callback = function(args)
            if is_startable_buffer(args.buf) then
                autostart_lsp("supported-buffer-autostart")
            end
        end,
    })
    log.info("M.setup: proactive autostart registered")

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
