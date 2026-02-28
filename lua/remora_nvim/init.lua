-- Remora.nvim: Agent-native IDE plugin

local M = {}

function M.setup(config)
    config = config or {}
    local socket_path = config.socket or "/run/user/1000/remora.sock"

    require("remora_nvim.sidepanel").setup()
    require("remora_nvim.bridge").setup(socket_path)
    require("remora_nvim.navigation").setup()

    M.setup_keymaps(config.keymaps or {})

    vim.notify("Remora.nvim initialized", vim.log.levels.INFO)
end

function M.setup_keymaps(user_keymaps)
    local defaults = {
        toggle = "<leader>ra",
        chat = "<leader>rc",
        parent = "[[",
    }

    local keymaps = vim.tbl_extend("force", defaults, user_keymaps)
    local opts = { noremap = true, silent = true }

    vim.keymap.set("n", keymaps.toggle, function()
        require("remora_nvim.sidepanel").toggle()
    end, opts)

    vim.keymap.set("n", keymaps.chat, function()
        require("remora_nvim.chat").open()
    end, opts)

    vim.keymap.set("n", keymaps.parent, function()
        require("remora_nvim.navigation").go_to_parent()
    end, opts)
end

return M
