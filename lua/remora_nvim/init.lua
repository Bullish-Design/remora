local M = {}

function M.setup(config)
  config = config or {}
  local socket_path = config.socket or "/run/user/1000/remora.sock"

  -- 1. Initialize the UI
  require("remora_nvim.sidepanel").setup()

  -- 2. Connect to the Daemon
  require("remora_nvim.bridge").setup(socket_path)

  -- 3. Start watching the cursor
  require("remora_nvim.navigation").setup()
end

return M
