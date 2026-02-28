local M = {}
M.client = nil
M.callbacks = {}
M.next_id = 1

function M.setup(socket_path)
  M.client = vim.loop.new_pipe(false)
  M.client:connect(socket_path, function(err)
    if err then
      vim.schedule(function()
        vim.notify("Remora Bridge: Failed to connect to " .. socket_path .. ": " .. err, vim.log.levels.ERROR)
      end)
      return
    end

    M.client:read_start(function(err, data)
      if err then return end
      if data then M.handle_response(data) end
    end)

    vim.schedule(function()
      vim.notify("Remora Bridge: Connected!", vim.log.levels.INFO)
    end)
  end)
end

function M.call(method, params, callback)
  if not M.client then return end
  local id = M.next_id
  M.next_id = M.next_id + 1

  local msg = vim.fn.json_encode({
    jsonrpc = "2.0",
    id = id,
    method = method,
    params = params,
  })

  if callback then
    M.callbacks[id] = callback
  end

  M.client:write(msg .. "\n")
end

function M.handle_response(data)
  for line in data:gmatch("[^\n]+") do
    local ok, msg = pcall(vim.fn.json_decode, line)
    if ok and msg.id and M.callbacks[msg.id] then
      vim.schedule(function()
        M.callbacks[msg.id](msg.result)
        M.callbacks[msg.id] = nil
      end)
    end
  end
end

return M
