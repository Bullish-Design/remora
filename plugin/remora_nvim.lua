-- Only load once
if vim.g.loaded_remora_nvim then
  return
end
vim.g.loaded_remora_nvim = true

-- Command to manually toggle the sidepanel
vim.api.nvim_create_user_command("RemoraToggle", function()
  require("remora_nvim.sidepanel").toggle()
end, {})

-- Command to manually connect
vim.api.nvim_create_user_command("RemoraConnect", function()
  require("remora_nvim").setup({})
end, {})
