-- remora_demo/companion/nvim/lua/companion/init.lua
-- Companion plugin for ambient knowledge work assistance
--
-- This plugin:
-- 1. Connects to the companion-lsp server
-- 2. Sends cursor position on CursorHold events
-- 3. Can display the sidebar in a floating window or side panel
--
-- Usage:
--   require("companion").setup({
--     cmd = { "companion-lsp" },  -- or full path
--     filetypes = { "python", "markdown", "lua" },
--     sidebar_output = "/path/to/vault/sidebar.md",  -- optional
--   })

local M = {}

-- Configuration
M.config = {
    cmd = { "companion-lsp" },
    filetypes = { "python", "markdown", "lua", "typescript", "javascript" },
    root_markers = { ".companion", ".git" },
    sidebar_output = nil,  -- Write sidebar to this file
    sidebar_width = 40,    -- Sidebar panel width
    auto_open_sidebar = false,
    update_delay_ms = 100, -- Debounce for cursor updates
    debug = false,
}

-- State
M._client_id = nil
M._sidebar_win = nil
M._sidebar_buf = nil
M._last_cursor_update = 0

-- =========================================================================
-- Logging
-- =========================================================================

local function log(level, msg, ...)
    if not M.config.debug and level == "debug" then return end
    local formatted = string.format(msg, ...)
    vim.notify("[Companion] " .. formatted, 
        level == "error" and vim.log.levels.ERROR 
        or level == "warn" and vim.log.levels.WARN 
        or vim.log.levels.INFO)
end

-- =========================================================================
-- Client helpers
-- =========================================================================

--- Get the companion LSP client, or nil if not running.
local function get_client(opts)
    opts = opts or {}
    local clients = vim.lsp.get_clients({ name = "companion" })
    if #clients == 0 then
        if not opts.silent then
            log("warn", "LSP not running")
        end
        return nil
    end
    return clients[1]
end

--- Get current cursor context.
local function cursor_context()
    local buf = vim.api.nvim_get_current_buf()
    local uri = vim.uri_from_bufnr(buf)
    local row, col = unpack(vim.api.nvim_win_get_cursor(0))
    return { uri = uri, line = row - 1, col = col }  -- 0-indexed for LSP
end

-- =========================================================================
-- Sidebar panel
-- =========================================================================

-- Forward declaration for cursor update (defined below)
local send_cursor_update

--- Create or get the sidebar buffer.
local function get_sidebar_buf()
    if M._sidebar_buf and vim.api.nvim_buf_is_valid(M._sidebar_buf) then
        return M._sidebar_buf
    end
    
    M._sidebar_buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_buf_set_name(M._sidebar_buf, "[Companion Sidebar]")
    vim.api.nvim_set_option_value("buftype", "nofile", { buf = M._sidebar_buf })
    vim.api.nvim_set_option_value("bufhidden", "hide", { buf = M._sidebar_buf })
    vim.api.nvim_set_option_value("swapfile", false, { buf = M._sidebar_buf })
    vim.api.nvim_set_option_value("filetype", "markdown", { buf = M._sidebar_buf })
    
    return M._sidebar_buf
end

--- Open the sidebar panel.
function M.open_sidebar()
    if M._sidebar_win and vim.api.nvim_win_is_valid(M._sidebar_win) then
        return  -- Already open
    end
    
    local buf = get_sidebar_buf()
    
    -- Open a vertical split on the right
    vim.cmd("botright vsplit")
    M._sidebar_win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(M._sidebar_win, buf)
    vim.api.nvim_win_set_width(M._sidebar_win, M.config.sidebar_width)
    
    -- Make it non-focusable and read-only
    vim.api.nvim_set_option_value("winfixwidth", true, { win = M._sidebar_win })
    vim.api.nvim_set_option_value("number", false, { win = M._sidebar_win })
    vim.api.nvim_set_option_value("relativenumber", false, { win = M._sidebar_win })
    vim.api.nvim_set_option_value("signcolumn", "no", { win = M._sidebar_win })
    vim.api.nvim_set_option_value("wrap", true, { win = M._sidebar_win })
    
    -- Go back to previous window
    vim.cmd("wincmd p")
    
    -- Send initial cursor position so agents have context
    send_cursor_update()
    
    -- Wait for agents to process, then fetch content
    -- Debounce is 100ms + some processing time
    vim.defer_fn(M.refresh_sidebar, 300)
    
    log("info", "Sidebar opened")
end

--- Close the sidebar panel.
function M.close_sidebar()
    if M._sidebar_win and vim.api.nvim_win_is_valid(M._sidebar_win) then
        vim.api.nvim_win_close(M._sidebar_win, true)
        M._sidebar_win = nil
        log("info", "Sidebar closed")
    end
end

--- Toggle the sidebar panel.
function M.toggle_sidebar()
    if M._sidebar_win and vim.api.nvim_win_is_valid(M._sidebar_win) then
        M.close_sidebar()
    else
        M.open_sidebar()
    end
end

--- Update sidebar content.
local function update_sidebar_content(markdown)
    if not M._sidebar_buf or not vim.api.nvim_buf_is_valid(M._sidebar_buf) then
        return
    end
    
    local lines = vim.split(markdown or "", "\n")
    vim.api.nvim_buf_set_lines(M._sidebar_buf, 0, -1, false, lines)
end

--- Request sidebar content from LSP server.
--- Sends cursor position first to ensure agents have latest context.
function M.refresh_sidebar()
    local client = get_client({ silent = true })
    if not client then return end
    
    -- Send cursor position first (agents need this to compose)
    local ctx = cursor_context()
    client.notify("$/companion/cursorMoved", ctx)
    
    -- Wait for agents to process (debounce 100ms + compose time)
    vim.defer_fn(function()
        client.request("$/companion/getSidebar", {}, function(err, result)
            if err then
                log("error", "Failed to get sidebar: %s", vim.inspect(err))
                return
            end
            if result and result.markdown then
                update_sidebar_content(result.markdown)
            end
        end)
    end, 200)
end

-- =========================================================================
-- Cursor tracking
-- =========================================================================

--- Send cursor position to LSP server.
send_cursor_update = function()
    local client = get_client({ silent = true })
    if not client then return end
    
    local ctx = cursor_context()
    client.notify("$/companion/cursorMoved", ctx)
end

--- Debounced cursor update.
local function on_cursor_hold()
    local now = vim.uv.now()
    if now - M._last_cursor_update < M.config.update_delay_ms then
        return
    end
    M._last_cursor_update = now
    
    -- Check if current filetype is supported
    local ft = vim.bo.filetype
    local supported = false
    for _, supported_ft in ipairs(M.config.filetypes) do
        if ft == supported_ft then
            supported = true
            break
        end
    end
    
    if not supported then return end
    
    send_cursor_update()
end

-- =========================================================================
-- LSP notification handlers
-- =========================================================================

local function setup_handlers()
    -- Handle sidebar updates pushed from server
    vim.lsp.handlers["$/companion/sidebarUpdated"] = function(_, result)
        if result and result.markdown then
            update_sidebar_content(result.markdown)
        end
    end
    
    -- Handle debug/status notifications
    vim.lsp.handlers["$/companion/status"] = function(_, result)
        log("info", "Status: %s", vim.inspect(result))
    end
end

-- =========================================================================
-- Setup
-- =========================================================================

function M.setup(opts)
    opts = opts or {}
    
    -- Merge config
    M.config = vim.tbl_deep_extend("force", M.config, opts)
    
    -- Check Neovim version
    if not vim.lsp or not vim.lsp.config then
        vim.notify(
            "[Companion] Neovim 0.11+ required for LSP integration",
            vim.log.levels.ERROR
        )
        return
    end
    
    -- Build LSP command
    local cmd = M.config.cmd
    if M.config.sidebar_output then
        cmd = vim.list_extend(vim.deepcopy(cmd), { "--sidebar-output", M.config.sidebar_output })
    end
    if M.config.debug then
        cmd = vim.list_extend(vim.deepcopy(cmd), { "--debug" })
    end
    
    -- Configure LSP
    local lsp_config = {
        cmd = cmd,
        filetypes = M.config.filetypes,
        root_markers = M.config.root_markers,
        settings = {},
    }
    
    vim.lsp.config["companion"] = lsp_config
    vim.lsp.enable("companion")
    
    -- Setup handlers
    setup_handlers()
    
    -- Re-trigger FileType for already-open buffers
    local matching_fts = {}
    for _, ft in ipairs(M.config.filetypes) do matching_fts[ft] = true end
    for _, buf in ipairs(vim.api.nvim_list_bufs()) do
        if vim.api.nvim_buf_is_loaded(buf) then
            local ft = vim.bo[buf].filetype
            if matching_fts[ft] then
                vim.api.nvim_buf_call(buf, function()
                    vim.cmd("doautocmd FileType " .. ft)
                end)
            end
        end
    end
    
    -- -----------------------------------------------------------------------
    -- Autocmds
    -- -----------------------------------------------------------------------
    
    local augroup = vim.api.nvim_create_augroup("Companion", { clear = true })
    
    -- Cursor tracking
    vim.api.nvim_create_autocmd("CursorHold", {
        group = augroup,
        callback = on_cursor_hold,
    })
    
    -- Refresh sidebar on cursor move (if open)
    vim.api.nvim_create_autocmd("CursorHold", {
        group = augroup,
        callback = function()
            if M._sidebar_win and vim.api.nvim_win_is_valid(M._sidebar_win) then
                -- Refresh after a delay to let agents process
                vim.defer_fn(M.refresh_sidebar, 200)
            end
        end,
    })
    
    -- -----------------------------------------------------------------------
    -- User commands
    -- -----------------------------------------------------------------------
    
    vim.api.nvim_create_user_command("CompanionSidebar", function()
        M.toggle_sidebar()
    end, { desc = "Toggle Companion sidebar" })
    
    vim.api.nvim_create_user_command("CompanionRefresh", function()
        M.refresh_sidebar()
    end, { desc = "Refresh Companion sidebar" })
    
    vim.api.nvim_create_user_command("CompanionStatus", function()
        local client = get_client()
        if client then
            log("info", "LSP client active (id=%d)", client.id)
        end
    end, { desc = "Show Companion status" })
    
    -- -----------------------------------------------------------------------
    -- Keymaps (optional, user can override)
    -- -----------------------------------------------------------------------
    
    local prefix = opts.prefix or "<leader>k"  -- k for knowledge
    
    vim.keymap.set("n", prefix .. "s", M.toggle_sidebar, 
        { desc = "Toggle Companion sidebar" })
    vim.keymap.set("n", prefix .. "r", M.refresh_sidebar, 
        { desc = "Refresh Companion sidebar" })
    
    -- -----------------------------------------------------------------------
    -- Auto-open sidebar if configured
    -- -----------------------------------------------------------------------
    
    if M.config.auto_open_sidebar then
        vim.defer_fn(M.open_sidebar, 100)
    end
    
    log("info", "Setup complete")
end

return M
