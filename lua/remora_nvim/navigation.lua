-- Remora Navigation: Treesitter cursor tracking + agent discovery

local M = {}

M.current_agent_id = nil
M.registered_buffers = {}
M.agent_id_cache = {}

function M.setup()
    vim.api.nvim_create_autocmd("CursorMoved", {
        callback = M.on_cursor_moved,
    })
    vim.api.nvim_create_autocmd("BufReadPost", {
        pattern = "*.py",
        callback = M.on_buffer_opened,
    })
    vim.api.nvim_create_autocmd("BufEnter", {
        pattern = "*.py",
        callback = M.on_buffer_entered,
    })
end

function M.on_buffer_opened(ev)
    local bufnr = vim.api.nvim_get_current_buf()
    local file_path = vim.api.nvim_buf_get_name(bufnr)

    if file_path == "" or M.registered_buffers[file_path] then
        return
    end

    M.registered_buffers[file_path] = true
    require("remora_nvim.bridge").notify_buffer_opened(file_path, function(result)
        if not result or not result.agents then
            return
        end

        local file_name = vim.fn.fnamemodify(file_path, ":t:r")
        for _, agent in ipairs(result.agents) do
            local cache_key = string.format("%s_%s_%d", agent.type, file_name, agent.line)
            M.agent_id_cache[cache_key] = agent.agent_id
        end
    end)
end

function M.on_buffer_entered(ev)
    M.on_buffer_opened(ev)
end

function M.on_cursor_moved()
    local bufnr = vim.api.nvim_get_current_buf()
    local filetype = vim.bo[bufnr].filetype

    if filetype ~= "python" then
        return
    end

    local ok, parser = pcall(vim.treesitter.get_parser, bufnr)
    if not ok or not parser then
        return
    end

    local cursor = vim.api.nvim_win_get_cursor(0)
    local row = cursor[1] - 1
    local col = cursor[2]

    local tree = parser:parse()[1]
    if not tree then
        return
    end

    local root = tree:root()
    if not root then
        return
    end

    local node = root:named_descendant_for_range(row, col, row, col)

    local target_node = nil
    while node do
        local node_type = node:type()
        if M.is_agent_node_type(node_type) then
            target_node = node
            break
        end
        node = node:parent()
    end

    local file_path = vim.api.nvim_buf_get_name(bufnr)
    local file_name = vim.fn.fnamemodify(file_path, ":t:r")

    local ts_node_type = "file"
    local start_line = 1

    if target_node then
        ts_node_type = target_node:type()
        start_line, _ = target_node:start()
        start_line = start_line + 1
    end

    -- Normalize the type to match server format (function, class, etc.)
    local node_type = M.normalize_node_type(ts_node_type)
    local cache_key = string.format("%s_%s_%d", node_type, file_name, start_line)
    local agent_id = M.agent_id_cache[cache_key] or cache_key

    if agent_id ~= M.current_agent_id then
        M.current_agent_id = agent_id

        require("remora_nvim.bridge").subscribe_to_agent(agent_id)
        require("remora_nvim.sidepanel").show_agent(agent_id, file_path, node_type, start_line)
    end
end

function M.is_agent_node_type(node_type)
    local agent_types = {
        "function_definition",
        "async_function_definition",
        "class_definition",
        "decorated_definition",
    }
    return vim.tbl_contains(agent_types, node_type)
end

-- Normalize treesitter node type to server node type
-- Server uses: function, method, class, file
-- Treesitter uses: function_definition, class_definition, etc.
function M.normalize_node_type(ts_type)
    local type_map = {
        ["function_definition"] = "function",
        ["async_function_definition"] = "function",
        ["class_definition"] = "class",
        ["decorated_definition"] = "function",  -- decorated functions/methods
    }
    return type_map[ts_type] or ts_type
end

function M.go_to_parent()
    local bufnr = vim.api.nvim_get_current_buf()
    local cursor = vim.api.nvim_win_get_cursor(0)
    local row = cursor[1] - 1
    local col = cursor[2]

    local ok, parser = pcall(vim.treesitter.get_parser, bufnr)
    if not ok or not parser then
        return
    end

    local tree = parser:parse()[1]
    if not tree then
        return
    end

    local root = tree:root()
    local node = root:named_descendant_for_range(row, col, row, col)

    while node and not M.is_agent_node_type(node:type()) do
        node = node:parent()
    end

    if not node then
        return
    end

    local parent = node:parent()
    while parent and not M.is_agent_node_type(parent:type()) do
        parent = parent:parent()
    end

    if parent then
        local start_row, start_col = parent:start()
        vim.api.nvim_win_set_cursor(0, {start_row + 1, start_col})
    end
end

return M
