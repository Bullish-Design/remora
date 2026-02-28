local M = {}
M.current_agent_id = nil

function M.setup()
  vim.api.nvim_create_autocmd("CursorMoved", {
    callback = M.on_cursor_moved,
  })
end

function M.on_cursor_moved()
  local bufnr = vim.api.nvim_get_current_buf()
  local filetype = vim.api.nvim_buf_get_option(bufnr, 'filetype')
  -- Only attempt to parse supported languages to avoid "no parser" errors
  if filetype == '' or filetype == 'notify' or filetype == 'remora' then
      return
  end

  -- Use pcall because get_parser throws an error for unsupported filetypes
  local ok, parser = pcall(vim.treesitter.get_parser, bufnr)
  if not ok or not parser then return end

  -- A simple way to get the node at the cursor
  local win = vim.api.nvim_get_current_win()
  local cursor = vim.api.nvim_win_get_cursor(win)
  local row = cursor[1] - 1
  local col = cursor[2]

  local root_tree = parser:parse()[1]
  if not root_tree then return end
  local root = root_tree:root()
  if not root then return end
  local node = root:named_descendant_for_range(row, col, row, col)

  -- Walk up to find a class or function
  local target_node = nil
  while node do
    local type = node:type()
    if type == "function_definition" or type == "class_definition" or type == "async_function_definition" then
      target_node = node
      break
    end
    node = node:parent()
  end

  local node_type = "file"
  local start_row = 0
  
  if target_node then
    node_type = target_node:type()
    start_row, _ = target_node:start()
  end

  -- Create a stable ID. Must match how python generates IDs
  local file_path = vim.api.nvim_buf_get_name(bufnr)
  local file_name = vim.fn.fnamemodify(file_path, ":t:r")

  -- e.g. "function_definition_utils_15" or "file_remora_1"
  local agent_id = string.format("%s_%s_%d", node_type, file_name, start_row + 1)

  if agent_id ~= M.current_agent_id then
    M.current_agent_id = agent_id
    require("remora_nvim.sidepanel").show_agent(agent_id, file_path, node_type)
  end
end

return M
