-- remora/panel.lua — Right-side vsplit agent panel
-- Shows the agent at cursor: header, tools (collapsible), chat history, input.

local Line = require("nui.line")
local log = require("remora.log")

local M = {}

-- ---------------------------------------------------------------------------
-- State
-- ---------------------------------------------------------------------------

M._chat_win = nil    -- window id for the chat/header buffer
M._chat_buf = nil    -- buffer id for chat content
M._input_win = nil   -- window id for the input line
M._input_buf = nil   -- buffer id for the input line
M._agent = nil       -- current agent dict {id, name, node_type, status, ...}
M._tools = {}        -- list of {name, description}
M._events = {}       -- list of event dicts (chronological)
M._pending_request = nil -- pending human input request metadata
M._show_tools = false -- tools section collapsed by default
M._ns = vim.api.nvim_create_namespace("remora_panel")
M._augroup = nil     -- autocmd group id

-- Callbacks set by init.lua
M._exec_command = nil   -- function(command, arguments)
M._cursor_context = nil -- function() -> {uri, line}
M._get_client = nil     -- function() -> client or nil

-- Debounce state for cursor-driven refresh
M._debounce_timer = nil
M._debounce_ms = 300    -- ms to wait after last CursorHold/BufEnter

-- Request timeout state for panel fetches
M._request_seq = 0
M._request_inflight = nil
M._request_timeout_ms = 5000
M._request_timeout_timer = nil
M._last_fetch_error = nil

-- ---------------------------------------------------------------------------
-- Highlight groups
-- ---------------------------------------------------------------------------

local status_icons = {
    active = " ",
    running = " ",
    pending_approval = " ",
    orphaned = " ",
}

local status_hls = {
    active = "RemoraActive",
    running = "RemoraRunning",
    pending_approval = "RemoraPending",
    orphaned = "RemoraOrphaned",
}

local event_icons = {
    AgentTextResponse = " ",
    AgentStartEvent = " ",
    AgentCompleteEvent = " ",
    AgentErrorEvent = " ",
    RewriteProposalEvent = " ",
    RewriteAppliedEvent = " ",
    RewriteRejectedEvent = " ",
    HumanChatEvent = " ",
    HumanInputRequestEvent = " ",
    HumanInputResponseEvent = " ",
    AgentMessageEvent = " ",
    ToolResultEvent = " ",
}

local event_hls = {
    AgentTextResponse = "RemoraAgent",
    AgentStartEvent = "DiagnosticInfo",
    AgentCompleteEvent = "DiagnosticOk",
    AgentErrorEvent = "DiagnosticError",
    RewriteProposalEvent = "DiagnosticWarn",
    RewriteAppliedEvent = "DiagnosticOk",
    RewriteRejectedEvent = "DiagnosticError",
    HumanChatEvent = "RemoraUser",
    HumanInputRequestEvent = "DiagnosticWarn",
    HumanInputResponseEvent = "RemoraUser",
    AgentMessageEvent = "Comment",
    ToolResultEvent = "RemoraToolCall",
}

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

--- Sanitize a string: strip newlines (NuiLine crashes on them).
local function sanitize(s)
    if not s then return "" end
    return (tostring(s):gsub("\n", " "):gsub("\r", ""))
end

local function format_time(timestamp)
    if not timestamp or timestamp == 0 then return "" end
    return os.date("%H:%M:%S", math.floor(timestamp))
end

--- Check if a window is valid.
local function win_valid(win)
    return win and vim.api.nvim_win_is_valid(win)
end

--- Check if a buffer is valid.
local function buf_valid(buf)
    return buf and vim.api.nvim_buf_is_valid(buf)
end

--- Delete any leftover buffer with the given name (from a previous session).
local function wipe_named_buf(name)
    local ok, nr = pcall(vim.fn.bufnr, name)
    if ok and nr ~= -1 then
        pcall(vim.api.nvim_buf_delete, nr, { force = true })
    end
end

local function clear_request_timeout_timer()
    if M._request_timeout_timer then
        M._request_timeout_timer:stop()
        M._request_timeout_timer:close()
        M._request_timeout_timer = nil
    end
end

local function refresh_pending_request()
    local responded = {}
    for _, ev in ipairs(M._events) do
        if ev.event_type == "HumanInputResponseEvent" then
            local payload = ev.payload or {}
            local request_id = payload.request_id or ev.request_id
            if request_id and request_id ~= "" then
                responded[request_id] = true
            end
        end
    end

    M._pending_request = nil
    for idx = #M._events, 1, -1 do
        local ev = M._events[idx]
        if ev.event_type == "HumanInputRequestEvent" then
            local payload = ev.payload or {}
            local request_id = payload.request_id or ev.request_id
            if request_id and request_id ~= "" and not responded[request_id] then
                M._pending_request = {
                    request_id = request_id,
                    prompt = payload.question or ev.summary or "Input:",
                    agent_id = ev.from_agent or payload.agent_id or (M._agent and M._agent.id),
                    node_id = payload.node_id,
                    question = payload.question,
                }
                break
            end
        end
    end
end

-- ---------------------------------------------------------------------------
-- Rendering — build lines and set them on the chat buffer
-- ---------------------------------------------------------------------------

--- Build all display lines as {text, highlights} pairs.
--- Returns a list of NuiLine objects.
local function build_lines()
    local lines = {}

    -- ── Header ──────────────────────────────────────────────────
    if M._agent then
        local sep = Line()
        sep:append("─── Agent ───────────────────────", "Comment")
        table.insert(lines, sep)

        local title = Line()
        local icon = status_icons[M._agent.status] or "?"
        local hl = status_hls[M._agent.status] or "Normal"
        title:append(icon, hl)
        title:append(" " .. sanitize(M._agent.name or "unnamed"), "Title")
        table.insert(lines, title)

        local info = Line()
        info:append("  Type: ", "Comment")
        info:append(sanitize(M._agent.node_type or "?"))
        info:append("  Status: ", "Comment")
        info:append(sanitize(M._agent.status or "?"), hl)
        table.insert(lines, info)

        local loc = Line()
        loc:append("  Lines: ", "Comment")
        loc:append(tostring(M._agent.start_line or "?") .. "-" .. tostring(M._agent.end_line or "?"))
        table.insert(lines, loc)

        -- Blank separator
        table.insert(lines, Line())
    else
        local noagent = Line()
        noagent:append("No agent at cursor", "Comment")
        table.insert(lines, noagent)
        if M._request_inflight then
            local loading = Line()
            loading:append("  Resolving agent...", "Comment")
            table.insert(lines, loading)
        end
        if M._last_fetch_error then
            local fetch_err = Line()
            fetch_err:append("  " .. sanitize(M._last_fetch_error), "DiagnosticWarn")
            table.insert(lines, fetch_err)
        end
        table.insert(lines, Line())
    end

    -- ── Tools (collapsible) ─────────────────────────────────────
    local tools_header = Line()
    if M._show_tools then
        tools_header:append("▼ Tools (" .. #M._tools .. ")", "Title")
    else
        tools_header:append("▶ Tools (" .. #M._tools .. ")  [t to toggle]", "Comment")
    end
    table.insert(lines, tools_header)

    if M._show_tools then
        if #M._tools == 0 then
            local none = Line()
            none:append("  (none)", "Comment")
            table.insert(lines, none)
        else
            for _, tool in ipairs(M._tools) do
                local tl = Line()
                tl:append("  " .. sanitize(tool.name), "Function")
                if tool.description and tool.description ~= "" then
                    tl:append(" — " .. sanitize(tool.description), "Comment")
                end
                table.insert(lines, tl)
            end
        end
    end
    table.insert(lines, Line())

    -- ── Chat history ────────────────────────────────────────────
    local chat_sep = Line()
    chat_sep:append("─── Chat ────────────────────────", "Comment")
    table.insert(lines, chat_sep)

    if #M._events == 0 then
        local empty = Line()
        empty:append("  No messages yet. Type below to chat.", "Comment")
        table.insert(lines, empty)
    else
        for _, ev in ipairs(M._events) do
            local etype = ev.event_type or ""
            local icon = event_icons[etype] or "  "
            local hl = event_hls[etype] or "Normal"

            if etype == "HumanChatEvent" then
                -- User message
                local header = Line()
                header:append(icon, hl)
                header:append("You", "RemoraUser")
                local ts = format_time(ev.timestamp)
                if ts ~= "" then
                    header:append("  " .. ts, "Comment")
                end
                table.insert(lines, header)

                local msg = (ev.payload and ev.payload.message)
                    or (ev.payload and ev.payload.content)
                    or ev.summary or ""
                for _, text_line in ipairs(vim.split(msg, "\n")) do
                    local ml = Line()
                    ml:append("  " .. text_line, "RemoraUserText")
                    table.insert(lines, ml)
                end
                table.insert(lines, Line())

            elseif etype == "HumanInputRequestEvent" then
                local header = Line()
                header:append(icon, hl)
                header:append("Question", "DiagnosticWarn")
                local ts = format_time(ev.timestamp)
                if ts ~= "" then
                    header:append("  " .. ts, "Comment")
                end
                table.insert(lines, header)

                local prompt = (ev.payload and ev.payload.question) or ev.summary or ""
                for _, text_line in ipairs(vim.split(prompt, "\n")) do
                    local ql = Line()
                    ql:append("  " .. text_line, "DiagnosticWarn")
                    table.insert(lines, ql)
                end
                table.insert(lines, Line())

            elseif etype == "HumanInputResponseEvent" then
                local header = Line()
                header:append(icon, hl)
                header:append("You (response)", "RemoraUser")
                local ts = format_time(ev.timestamp)
                if ts ~= "" then
                    header:append("  " .. ts, "Comment")
                end
                table.insert(lines, header)

                local msg = (ev.payload and ev.payload.response)
                    or ev.summary or ""
                for _, text_line in ipairs(vim.split(msg, "\n")) do
                    local rl = Line()
                    rl:append("  " .. text_line, "RemoraUserText")
                    table.insert(lines, rl)
                end
                table.insert(lines, Line())

            elseif etype == "AgentTextResponse" then
                -- LLM response
                local header = Line()
                header:append(icon, hl)
                header:append("Agent", "RemoraAgent")
                local ts = format_time(ev.timestamp)
                if ts ~= "" then
                    header:append("  " .. ts, "Comment")
                end
                table.insert(lines, header)

                local content = (ev.payload and ev.payload.content) or ev.summary or ""
                for _, text_line in ipairs(vim.split(content, "\n")) do
                    local ml = Line()
                    ml:append("  " .. text_line, "RemoraAgentText")
                    table.insert(lines, ml)
                end
                table.insert(lines, Line())

            elseif etype == "AgentErrorEvent" then
                local el = Line()
                el:append(icon, hl)
                el:append(sanitize(ev.summary or "Error"), hl)
                table.insert(lines, el)
                table.insert(lines, Line())

            elseif etype == "RewriteProposalEvent" then
                local pl = Line()
                pl:append(icon, hl)
                pl:append("Rewrite proposal", hl)
                local ts = format_time(ev.timestamp)
                if ts ~= "" then
                    pl:append("  " .. ts, "Comment")
                end
                table.insert(lines, pl)

                -- Show diff if available
                local diff = ev.payload and ev.payload.diff or ev.diff
                if diff then
                    for _, dl in ipairs(vim.split(diff, "\n")) do
                        local dline = Line()
                        if dl:sub(1, 1) == "+" then
                            dline:append("  " .. dl, "DiffAdd")
                        elseif dl:sub(1, 1) == "-" then
                            dline:append("  " .. dl, "DiffDelete")
                        else
                            dline:append("  " .. dl, "Comment")
                        end
                        table.insert(lines, dline)
                    end
                end
                table.insert(lines, Line())

            elseif etype == "AgentMessageEvent" then
                -- Inter-agent message
                local header = Line()
                header:append(icon, hl)
                local from = (ev.payload and ev.payload.from_agent) or "unknown"
                local to = (ev.payload and ev.payload.to_agent) or "unknown"
                -- Show direction relative to current agent
                if M._agent and to == M._agent.id then
                    header:append("From: ", "Comment")
                    header:append(sanitize(from), "Function")
                else
                    header:append("To: ", "Comment")
                    header:append(sanitize(to), "Function")
                end
                local ts = format_time(ev.timestamp)
                if ts ~= "" then
                    header:append("  " .. ts, "Comment")
                end
                table.insert(lines, header)

                local msg = (ev.payload and ev.payload.message)
                    or (ev.payload and ev.payload.content)
                    or ev.summary or ""
                for _, text_line in ipairs(vim.split(msg, "\n")) do
                    local ml = Line()
                    ml:append("  " .. text_line, "Comment")
                    table.insert(lines, ml)
                end
                table.insert(lines, Line())

            elseif etype == "ToolResultEvent" then
                -- Tool call result — compact, greyed out
                local tool_name = (ev.payload and ev.payload.tool_name) or "tool"
                local target = (ev.payload and ev.payload.target_id) or ""
                local ts = format_time(ev.timestamp)

                local tl = Line()
                tl:append("  " .. icon, "RemoraToolCall")
                tl:append(sanitize(tool_name), "RemoraToolCall")
                if target ~= "" then
                    tl:append("(" .. sanitize(target) .. ")", "RemoraToolCall")
                end
                if ts ~= "" then
                    tl:append("  " .. ts, "RemoraToolCall")
                end
                table.insert(lines, tl)

                -- Show result summary on next line if available
                local result_text = (ev.payload and ev.payload.result_summary) or ""
                if result_text ~= "" then
                    local rl = Line()
                    rl:append("    -> " .. sanitize(result_text), "RemoraToolCall")
                    table.insert(lines, rl)
                end

            else
                -- Generic event
                local gl = Line()
                gl:append(icon, hl)
                gl:append(sanitize(ev.summary or etype), hl)
                local ts = format_time(ev.timestamp)
                if ts ~= "" then
                    gl:append("  " .. ts, "Comment")
                end
                table.insert(lines, gl)
            end
        end
    end

    -- ── Help line ───────────────────────────────────────────────
    table.insert(lines, Line())
    local help = Line()
    if M._pending_request then
        help:append("[q] close  [t] tools  [<CR>] submit response", "Comment")
    else
        help:append("[q] close  [t] tools  [<CR>] send message", "Comment")
    end
    table.insert(lines, help)

    return lines
end

--- Render lines into the chat buffer.
local function render()
    if not buf_valid(M._chat_buf) then return end

    local nui_lines = build_lines()

    -- Convert NuiLine objects to plain strings for nvim_buf_set_lines
    local plain = {}
    for _, line in ipairs(nui_lines) do
        table.insert(plain, line:content())
    end

    vim.api.nvim_set_option_value("modifiable", true, { buf = M._chat_buf })
    vim.api.nvim_buf_set_lines(M._chat_buf, 0, -1, false, plain)

    -- Apply highlights via NuiLine
    vim.api.nvim_buf_clear_namespace(M._chat_buf, M._ns, 0, -1)
    for i, line in ipairs(nui_lines) do
        line:highlight(M._chat_buf, M._ns, i) -- NuiLine:highlight is 1-based
    end

    vim.api.nvim_set_option_value("modifiable", false, { buf = M._chat_buf })

    -- Scroll chat to bottom
    if win_valid(M._chat_win) then
        local count = vim.api.nvim_buf_line_count(M._chat_buf)
        pcall(vim.api.nvim_win_set_cursor, M._chat_win, { count, 0 })
    end

    if win_valid(M._input_win) then
        local label = " Message agent..."
        if M._pending_request then
            label = " Answer question..."
        end
        pcall(vim.api.nvim_set_option_value, "winbar", label, { win = M._input_win })
    end
end

-- ---------------------------------------------------------------------------
-- Fetch agent data from server
-- ---------------------------------------------------------------------------

--- Internal: perform the actual fetch once we have a client.
local function do_fetch_agent_data(client)
    if not client then
        log.debug("panel.do_fetch_agent_data: no LSP client")
        return
    end
    if not M._cursor_context then
        log.warn("panel.do_fetch_agent_data: no cursor_context callback")
        return
    end

    local ctx = M._cursor_context()
    log.info("panel.do_fetch_agent_data: requesting for %s:%d", ctx.uri, ctx.line)
    M._request_seq = M._request_seq + 1
    local request_id = M._request_seq
    M._request_inflight = request_id
    clear_request_timeout_timer()
    M._request_timeout_timer = vim.uv.new_timer()
    M._request_timeout_timer:start(M._request_timeout_ms, 0, vim.schedule_wrap(function()
        if M._request_inflight ~= request_id then
            return
        end
        M._request_inflight = nil
        M._last_fetch_error = string.format(
            "Panel request timed out at line %d; server may be busy.",
            ctx.line or -1
        )
        log.warn("panel.do_fetch_agent_data: TIMEOUT request_id=%d uri=%s line=%d", request_id, ctx.uri, ctx.line)
        render()
    end))

    client.request("workspace/executeCommand", {
        command = "remora.getAgentPanel",
        arguments = { ctx },
    }, function(err, result)
        if M._request_inflight ~= request_id then
            log.debug("panel.do_fetch_agent_data: stale response ignored request_id=%d", request_id)
            return
        end
        M._request_inflight = nil
        clear_request_timeout_timer()

        if err then
            log.error("panel.do_fetch_agent_data: error: %s", vim.inspect(err))
            M._last_fetch_error = "Panel request failed; check LSP logs."
            vim.schedule(function()
                render()
            end)
            return
        end
        if result and result.error then
            log.warn("panel.do_fetch_agent_data: server timeout/error: %s", tostring(result.error))
            M._last_fetch_error = tostring(result.error)
            vim.schedule(function()
                render()
            end)
            return
        end
        if not result then
            -- No agent at cursor
            vim.schedule(function()
                local changed = M._agent ~= nil
                M._agent = nil
                M._tools = {}
                M._pending_request = nil
                M._last_fetch_error = nil
                if changed then
                    M._events = {}
                end
                render()
            end)
            return
        end

        vim.schedule(function()
            local new_agent = result.agent
            local old_id = M._agent and M._agent.id
            local new_id = new_agent and new_agent.id

            if old_id ~= new_id then
                -- Agent changed — replace everything
                M._agent = new_agent
                M._tools = result.tools or {}
                M._events = result.events or {}
                refresh_pending_request()
                M._last_fetch_error = nil
                log.info("panel.do_fetch_agent_data: agent changed to %s (%s), %d tools, %d events",
                    tostring(new_id), tostring(new_agent and new_agent.name),
                    #M._tools, #M._events)
            else
                -- Same agent — update metadata but keep accumulated live events
                M._agent = new_agent
                M._tools = result.tools or {}
                M._last_fetch_error = nil
                -- Merge server events with live events we already have
                local server_ids = {}
                for _, ev in ipairs(result.events or {}) do
                    server_ids[ev.id or ev.event_id] = true
                end
                -- Keep only live events that server doesn't already have
                local new_events = {}
                for _, ev in ipairs(result.events or {}) do
                    table.insert(new_events, ev)
                end
                for _, ev in ipairs(M._events) do
                    if not server_ids[ev.id or ev.event_id] then
                        table.insert(new_events, ev)
                    end
                end
                M._events = new_events
                refresh_pending_request()
                log.debug("panel.do_fetch_agent_data: same agent %s, merged to %d events",
                    tostring(new_id), #M._events)
            end

            render()
        end)
    end)
end

--- Request agent panel data from the server and re-render (with retry on open).
--- If agent_id changes, clear events and re-render. If same agent, just update.
--- @param use_retry? boolean  If true and no client, use retry polling
local function fetch_agent_data(use_retry)
    if not M._cursor_context or not M._get_client then
        log.warn("panel.fetch_agent_data: no cursor_context or get_client callback")
        return
    end

    local client = M._get_client()
    if client then
        do_fetch_agent_data(client)
        return
    end

    -- No client yet — maybe use retry
    if use_retry and M._get_client_with_retry then
        log.info("panel.fetch_agent_data: no client, using retry")
        M._last_fetch_error = "Waiting for LSP connection..."
        M._get_client_with_retry({ callback = do_fetch_agent_data })
        return
    end

    log.debug("panel.fetch_agent_data: no LSP client")
    M._last_fetch_error = "LSP not connected yet."
    render()
end

--- Wrapper for autocmd use (no retry, silent failure).
local function fetch_agent_data_no_retry()
    fetch_agent_data(false)
end

-- ---------------------------------------------------------------------------
-- Send chat message
-- ---------------------------------------------------------------------------

local function send_message()
    if not buf_valid(M._input_buf) then return end
    if not M._agent and not M._pending_request then
        log.warn("panel.send_message: no agent selected")
        if M._request_inflight then
            vim.notify("[Remora] Panel is still resolving agent data; please retry in a moment.", vim.log.levels.WARN)
        elseif M._last_fetch_error then
            vim.notify("[Remora] " .. M._last_fetch_error, vim.log.levels.WARN)
        end
        return
    end

    local lines = vim.api.nvim_buf_get_lines(M._input_buf, 0, -1, false)
    local text = vim.fn.join(lines, "\n")
    text = vim.trim(text)
    if text == "" then return end

    local target_agent = (M._pending_request and M._pending_request.agent_id)
        or (M._agent and M._agent.id)
        or "unknown"
    log.info("panel.send_message: sending to agent %s: %s", target_agent, text:sub(1, 100))

    local params = nil
    if M._pending_request then
        local pending = M._pending_request
        table.insert(M._events, {
            event_type = "HumanInputResponseEvent",
            agent_id = pending.agent_id or (M._agent and M._agent.id),
            timestamp = os.time(),
            summary = text:sub(1, 200),
            payload = {
                request_id = pending.request_id,
                response = text,
                node_id = pending.node_id,
                question = pending.question,
            },
        })
        params = {
            request_id = pending.request_id,
            input = text,
            agent_id = pending.agent_id,
            node_id = pending.node_id,
            question = pending.question,
        }
        M._pending_request = nil
    else
        -- Immediately append to local events for instant feedback
        table.insert(M._events, {
            event_type = "HumanChatEvent",
            agent_id = M._agent.id,
            timestamp = os.time(),
            summary = text:sub(1, 200),
            payload = { message = text, to_agent = M._agent.id },
        })
        params = {
            agent_id = M._agent.id,
            input = text,
        }
    end
    refresh_pending_request()
    render()

    -- Clear input
    vim.api.nvim_buf_set_lines(M._input_buf, 0, -1, false, { "" })

    -- Send to server
    local client = M._get_client and M._get_client()
    if client then
        client.notify("$/remora/submitInput", params)
    end
end

-- ---------------------------------------------------------------------------
-- Lifecycle
-- ---------------------------------------------------------------------------

function M.open()
    log.info("panel.open: called")
    if win_valid(M._chat_win) then
        log.info("panel.open: already open")
        return
    end

    -- Remember which window to return to
    local origin_win = vim.api.nvim_get_current_win()

    -- Clean up any stale named buffers from a previous session
    wipe_named_buf("remora://panel")
    wipe_named_buf("remora://input")

    -- Create both buffers first (before any window manipulation)
    M._chat_buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_set_option_value("buftype", "nofile", { buf = M._chat_buf })
    vim.api.nvim_set_option_value("bufhidden", "wipe", { buf = M._chat_buf })
    vim.api.nvim_set_option_value("swapfile", false, { buf = M._chat_buf })
    vim.api.nvim_set_option_value("filetype", "remora-panel", { buf = M._chat_buf })
    vim.api.nvim_buf_set_name(M._chat_buf, "remora://panel")

    M._input_buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_set_option_value("buftype", "nofile", { buf = M._input_buf })
    vim.api.nvim_set_option_value("bufhidden", "wipe", { buf = M._input_buf })
    vim.api.nvim_set_option_value("swapfile", false, { buf = M._input_buf })
    vim.api.nvim_set_option_value("filetype", "remora-input", { buf = M._input_buf })
    vim.api.nvim_buf_set_name(M._input_buf, "remora://input")

    -- Open the chat buffer in a right-edge vertical split.
    local width = math.max(40, math.floor(vim.o.columns * 0.25))
    vim.cmd("botright vsplit")
    M._chat_win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(M._chat_win, M._chat_buf)
    vim.api.nvim_win_set_width(M._chat_win, width)

    -- Chat window options
    vim.api.nvim_set_option_value("number", false, { win = M._chat_win })
    vim.api.nvim_set_option_value("relativenumber", false, { win = M._chat_win })
    vim.api.nvim_set_option_value("signcolumn", "no", { win = M._chat_win })
    vim.api.nvim_set_option_value("wrap", true, { win = M._chat_win })
    vim.api.nvim_set_option_value("linebreak", true, { win = M._chat_win })
    vim.api.nvim_set_option_value("cursorline", false, { win = M._chat_win })
    vim.api.nvim_set_option_value("winfixwidth", true, { win = M._chat_win })

    -- Open the input buffer in a horizontal split below chat (~1/5 of panel)
    vim.cmd("belowright split")
    M._input_win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(M._input_win, M._input_buf)
    local input_height = math.max(5, math.floor(vim.o.lines * 0.20))
    vim.api.nvim_win_set_height(M._input_win, input_height)

    -- Input window options
    vim.api.nvim_set_option_value("number", false, { win = M._input_win })
    vim.api.nvim_set_option_value("relativenumber", false, { win = M._input_win })
    vim.api.nvim_set_option_value("signcolumn", "no", { win = M._input_win })
    vim.api.nvim_set_option_value("wrap", true, { win = M._input_win })
    vim.api.nvim_set_option_value("winfixheight", true, { win = M._input_win })
    vim.api.nvim_set_option_value("winbar", " Message agent...", { win = M._input_win })

    -- ── Keymaps ─────────────────────────────────────────────────

    -- Chat buffer keymaps
    vim.keymap.set("n", "q", function() M.close() end, { buffer = M._chat_buf, desc = "Close remora panel" })
    vim.keymap.set("n", "t", function()
        M._show_tools = not M._show_tools
        render()
    end, { buffer = M._chat_buf, desc = "Toggle tools" })

    -- Input buffer keymaps
    vim.keymap.set("i", "<CR>", function()
        send_message()
    end, { buffer = M._input_buf, desc = "Send message" })
    vim.keymap.set("n", "<CR>", function()
        send_message()
    end, { buffer = M._input_buf, desc = "Send message" })
    vim.keymap.set("n", "q", function() M.close() end, { buffer = M._input_buf, desc = "Close remora panel" })

    -- ── Autocmds ────────────────────────────────────────────────

    M._augroup = vim.api.nvim_create_augroup("RemoraPanel", { clear = true })

    -- Auto-refresh when cursor moves to a different agent (debounced)
    vim.api.nvim_create_autocmd({ "CursorHold", "BufEnter" }, {
        group = M._augroup,
        callback = function(ev)
            -- Only trigger for non-panel buffers
            if ev.buf == M._chat_buf or ev.buf == M._input_buf then return end
            -- Only trigger for supported file types (skip mini.files, help, etc.)
            local ft = vim.api.nvim_get_option_value("filetype", { buf = ev.buf })
            if ft ~= "python" and ft ~= "markdown" and ft ~= "toml" then return end
            -- Only if panel is still open
            if not win_valid(M._chat_win) then return end
            -- Debounce: cancel pending timer and start a new one
            if M._debounce_timer then
                M._debounce_timer:stop()
                M._debounce_timer:close()
            end
            M._debounce_timer = vim.uv.new_timer()
            M._debounce_timer:start(M._debounce_ms, 0, vim.schedule_wrap(function()
                if M._debounce_timer then
                    M._debounce_timer:stop()
                    M._debounce_timer:close()
                    M._debounce_timer = nil
                end
                if win_valid(M._chat_win) then
                    fetch_agent_data_no_retry()
                end
            end))
        end,
    })

    -- Clean up if either panel window is closed externally
    vim.api.nvim_create_autocmd("WinClosed", {
        group = M._augroup,
        callback = function(ev)
            local closed_win = tonumber(ev.match)
            if closed_win == M._chat_win or closed_win == M._input_win then
                vim.schedule(function() M._cleanup() end)
            end
        end,
    })

    -- Initial render with placeholder
    render()

    -- Return focus to origin window
    if vim.api.nvim_win_is_valid(origin_win) then
        vim.api.nvim_set_current_win(origin_win)
    end

    -- Fetch data for current cursor position (with retry for startup race)
    fetch_agent_data(true)

    log.info("panel.open: done, chat_win=%d input_win=%d", M._chat_win, M._input_win)
end

function M._cleanup()
    log.info("panel._cleanup: called")

    if M._debounce_timer then
        M._debounce_timer:stop()
        M._debounce_timer:close()
        M._debounce_timer = nil
    end
    clear_request_timeout_timer()
    M._request_inflight = nil
    M._last_fetch_error = nil

    if M._augroup then
        pcall(vim.api.nvim_del_augroup_by_id, M._augroup)
        M._augroup = nil
    end

    -- Close windows if still valid
    if win_valid(M._input_win) then
        pcall(vim.api.nvim_win_close, M._input_win, true)
    end
    if win_valid(M._chat_win) then
        pcall(vim.api.nvim_win_close, M._chat_win, true)
    end

    M._chat_win = nil
    M._chat_buf = nil
    M._input_win = nil
    M._input_buf = nil
end

function M.close()
    log.info("panel.close: called")
    M._cleanup()
end

function M.is_open()
    return win_valid(M._chat_win)
end

-- ---------------------------------------------------------------------------
-- External API (called from init.lua)
-- ---------------------------------------------------------------------------

--- Handle a live event from $/remora/event.
--- Only appends if the event matches the current agent.
function M.on_event(event)
    if not event then return end
    log.info("panel.on_event: type=%s agent=%s",
        tostring(event.event_type), tostring(event.agent_id))

    -- Only show events for the current agent (as sender or receiver)
    if not M._agent then
        log.debug("panel.on_event: ignoring (no agent)")
        return
    end
    local agent_id = M._agent.id
    local payload = event.payload or {}
    local to_agent = event.to_agent or payload.to_agent
    local from_agent = event.from_agent or payload.from_agent
    if event.agent_id ~= agent_id and to_agent ~= agent_id and from_agent ~= agent_id then
        log.debug("panel.on_event: ignoring (agent mismatch: event.agent_id=%s from_agent=%s to_agent=%s current=%s)",
            tostring(event.agent_id), tostring(from_agent), tostring(to_agent), agent_id)
        return
    end

    -- Avoid duplicate HumanChatEvent (we already appended locally on send)
    if event.event_type == "HumanChatEvent" then
        log.debug("panel.on_event: skipping HumanChatEvent (already shown locally)")
        return
    end

    table.insert(M._events, event)
    refresh_pending_request()
    render()
end

--- Force the panel to track a specific agent, clearing events and re-rendering.
--- Called from init.lua when requestInput fires for an agent that doesn't match
--- the currently displayed agent, so that live events stream to the right panel.
--- @param agent_id string  The agent ID to switch to.
--- @param agent_name? string  Optional display name for the agent.
function M.switch_agent(agent_id, agent_name)
    log.info("panel.switch_agent: switching to agent_id=%s name=%s", tostring(agent_id), tostring(agent_name))
    if M._agent and M._agent.id == agent_id then
        log.debug("panel.switch_agent: already tracking agent_id=%s", agent_id)
        return
    end
    -- Clear state and pin to new agent so on_event() will accept its events.
    M._agent = {
        id = agent_id,
        name = agent_name or agent_id,
        node_type = "?",
        status = "running",
        start_line = nil,
        end_line = nil,
    }
    M._events = {}
    M._tools = {}
    M._pending_request = nil
    M._last_fetch_error = nil
    render()
    log.info("panel.switch_agent: panel now tracking agent_id=%s", agent_id)
end

function M.set_pending_request(request)
    if not request or not request.request_id then
        return
    end
    M._pending_request = {
        request_id = request.request_id,
        prompt = request.prompt or "Input:",
        agent_id = request.agent_id or (M._agent and M._agent.id),
        node_id = request.node_id,
        question = request.question,
    }
    render()
end

--- Configure callbacks. Called once from init.lua setup.
function M.configure(opts)
    M._exec_command = opts.exec_command
    M._cursor_context = opts.cursor_context
    M._get_client = opts.get_client
    M._get_client_with_retry = opts.get_client_with_retry
    log.info("panel.configure: callbacks set")
end

return M
