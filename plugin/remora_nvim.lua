-- Remora.nvim plugin entry point

if vim.g.loaded_remora_nvim then
    return
end
vim.g.loaded_remora_nvim = true

vim.api.nvim_create_user_command("RemoraToggle", function()
    require("remora_nvim.sidepanel").toggle()
end, { desc = "Toggle Remora sidepanel" })

vim.api.nvim_create_user_command("RemoraConnect", function(opts)
    local socket = opts.args ~= "" and opts.args or nil
    require("remora_nvim").setup({ socket = socket })
end, { nargs = "?", desc = "Connect to Remora daemon" })

vim.api.nvim_create_user_command("RemoraChat", function()
    require("remora_nvim.chat").open()
end, { desc = "Chat with current agent" })

vim.api.nvim_create_user_command("RemoraRefresh", function()
    require("remora_nvim.sidepanel").refresh()
end, { desc = "Refresh current agent" })
