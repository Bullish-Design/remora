
-- Command to manually toggle the sidepanel
vim.api.nvim_create_user_command("RemoraToggle", function()
  require("remora_nvim.sidepanel").toggle()
end, {})

-- Command to manually connect
vim.api.nvim_create_user_command("RemoraConnect", function()
  require("remora_nvim").setup({})
end, {})
