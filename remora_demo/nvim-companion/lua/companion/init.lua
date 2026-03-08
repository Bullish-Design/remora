-- Companion sidebar plugin for Neovim.
-- Connects to the SAME remora-lsp server (no separate server).
-- Requires: require("remora").setup() called first.

local M = {}
local _sidebar_win = nil
local _sidebar_buf = nil
local _active_node_id = nil

local function get_remora_client()
    local clients = vim.lsp.get_clients({ name = "remora" })
    return clients and clients[1] or nil
end

local function set_sidebar_content(markdown)
    if not _sidebar_buf or not vim.api.nvim_buf_is_valid(_sidebar_buf) then
        return
    end
    local lines = vim.split(markdown or "*No companion context yet.*", "\n", { plain = true })
    vim.api.nvim_buf_set_option(_sidebar_buf, "modifiable", true)
    vim.api.nvim_buf_set_lines(_sidebar_buf, 0, -1, false, lines)
    vim.api.nvim_buf_set_option(_sidebar_buf, "modifiable", false)
end

local function open_sidebar()
    if _sidebar_win and vim.api.nvim_win_is_valid(_sidebar_win) then
        return
    end
    _sidebar_buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_buf_set_option(_sidebar_buf, "filetype", "markdown")
    vim.api.nvim_buf_set_option(_sidebar_buf, "modifiable", false)
    vim.api.nvim_buf_set_name(_sidebar_buf, "Companion")

    vim.cmd("botright vsplit")
    _sidebar_win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(_sidebar_win, _sidebar_buf)
    vim.api.nvim_win_set_width(_sidebar_win, 52)
    vim.api.nvim_win_set_option(_sidebar_win, "wrap", true)
    vim.api.nvim_win_set_option(_sidebar_win, "winfixwidth", true)
    vim.api.nvim_win_set_option(_sidebar_win, "number", false)
    vim.api.nvim_win_set_option(_sidebar_win, "signcolumn", "no")

    vim.cmd("wincmd p")

    vim.api.nvim_create_autocmd("WinClosed", {
        pattern = tostring(_sidebar_win),
        once = true,
        callback = function()
            _sidebar_win = nil
            _sidebar_buf = nil
        end,
    })
end

local function fetch_sidebar()
    local client = get_remora_client()
    if not client then return end
    client.request("workspace/executeCommand", {
        command = "companion.getSidebar",
        arguments = {},
    }, function(err, result)
        if err or not result then return end
        _active_node_id = result.node_id
        set_sidebar_content(result.markdown)
    end)
end

local function send_message(content)
    local client = get_remora_client()
    if not client then
        vim.notify("[companion] No remora client connected.", vim.log.levels.WARN)
        return
    end
    if not _active_node_id or _active_node_id == "" then
        vim.notify("[companion] No node focused. Move cursor to a function or class.", vim.log.levels.WARN)
        return
    end

    set_sidebar_content("*Thinking...*")

    client.request("workspace/executeCommand", {
        command = "companion.sendMessage",
        arguments = { { node_id = _active_node_id, content = content } },
    }, function(err, result)
        if err or not result then
            set_sidebar_content("*Error: agent did not respond.*")
            return
        end
        local msg = result.message and result.message.content or ""
        set_sidebar_content("**Agent:** " .. msg .. "\n\n*Updating sidebar...*")
        vim.defer_fn(fetch_sidebar, 2000)
    end)
end

local function prompt_and_send()
    vim.ui.input({ prompt = "Ask agent: " }, function(input)
        if input and input ~= "" then
            send_message(input)
        end
    end)
end

local function register_push_handler()
    vim.lsp.handlers["$/remora/companionSidebarUpdated"] = function(_, result)
        if not result then return end
        if result.node_id then
            _active_node_id = result.node_id
        end
        if _sidebar_win and vim.api.nvim_win_is_valid(_sidebar_win) then
            set_sidebar_content(result.markdown or "")
        end
    end
end

function M.setup(opts)
    opts = opts or {}
    register_push_handler()

    vim.api.nvim_create_user_command("CompanionSidebar", function()
        open_sidebar()
        fetch_sidebar()
    end, { desc = "Open companion sidebar for current node" })

    vim.api.nvim_create_user_command("CompanionRefresh", function()
        fetch_sidebar()
    end, { desc = "Refresh companion sidebar" })

    vim.api.nvim_create_user_command("CompanionChat", function()
        open_sidebar()
        prompt_and_send()
    end, { desc = "Chat with the active node agent" })

    vim.api.nvim_create_user_command("CompanionNote", function()
        local client = get_remora_client()
        if not client or not _active_node_id then
            vim.notify("[companion] No node focused.", vim.log.levels.WARN)
            return
        end
        vim.ui.input({ prompt = "Note: " }, function(input)
            if not input or input == "" then return end
            client.request("workspace/executeCommand", {
                command = "companion.writeNote",
                arguments = { { node_id = _active_node_id, note = input } },
            }, function(_, result)
                if result and result.ok then
                    vim.notify("[companion] Note saved.")
                    vim.defer_fn(fetch_sidebar, 500)
                end
            end)
        end)
    end, { desc = "Add a note to the current node" })

    if opts.auto_open then
        vim.api.nvim_create_autocmd("LspAttach", {
            callback = function(ev)
                local client = vim.lsp.get_client_by_id(ev.data.client_id)
                if client and client.name == "remora" then
                    vim.defer_fn(function()
                        open_sidebar()
                        fetch_sidebar()
                    end, 500)
                end
            end,
        })
    end
end

return M
