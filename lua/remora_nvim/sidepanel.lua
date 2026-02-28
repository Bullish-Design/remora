local M = {}
M.win = nil
M.buf = nil

function M.setup()
  M.buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_option(M.buf, "buftype", "nofile")
  vim.api.nvim_buf_set_option(M.buf, "filetype", "remora")
end

function M.toggle()
  if M.win and vim.api.nvim_win_is_valid(M.win) then
    vim.api.nvim_win_close(M.win, true)
    M.win = nil
  else
    vim.cmd("vsplit")
    vim.cmd("wincmd L")
    M.win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(M.win, M.buf)
    vim.api.nvim_win_set_width(M.win, 40)
    vim.api.nvim_win_set_option(M.win, "number", false)
    vim.api.nvim_win_set_option(M.win, "signcolumn", "no")
    vim.cmd("wincmd p") -- cursor back to main window
  end
end

function M.show_agent(agent_id, filepath, nodetype)
  -- Ask python for the state
  require("remora_nvim.bridge").call("agent.select", { id = agent_id, file = filepath }, function(state)
    if not M.win or not vim.api.nvim_win_is_valid(M.win) then return end

    local lines = {}
    table.insert(lines, "╭─────────────────────────────────╮")
    table.insert(lines, string.format("│ Agent ID: %-21s│", agent_id:sub(1, 21)))
    table.insert(lines, string.format("│ Type: %-25s│", nodetype))

    local status = state and state.status or "DORMANT"
    table.insert(lines, string.format("│ Status: %-23s│", status))
    table.insert(lines, "╰─────────────────────────────────╯")
    table.insert(lines, "")

    table.insert(lines, "RECENT TRIGGERS")
    table.insert(lines, "─────────────────────────────────")
    if state and state.triggers and #state.triggers > 0 then
      for _, t in ipairs(state.triggers) do
        table.insert(lines, "├─ " .. t)
      end
    else
      table.insert(lines, " (none)")
    end

    vim.api.nvim_buf_set_lines(M.buf, 0, -1, false, lines)
  end)
end

return M
