-- Remora Neovim V2.1 Starter File
-- Put this in your Neovim config or run with :luafile

-- Usage:
--   1. Copy this file to your Neovim config directory (e.g., ~/.config/nvim/lua/remora_starter.lua)
--   2. Add to your init.lua: require("remora_starter")
--   3. Or run: :luafile ~/.config/nvim/lua/remora_starter.lua
--   4. Run commands: :RemoraSetup, :RemoraStart, etc.

local M = {}

-- Configuration
M.config = {
    -- Path to the Remora demo directory (adjust as needed)
    demo_path = vim.fn.stdpath("config") .. "/lua/../../../demo",
    -- LSP command
    lsp_cmd = { "python", "-m", "demo.lsp.server" },
    -- File types to enable
    filetypes = { "python" },
    -- Root markers
    root_markers = { ".remora", ".git", "pyproject.toml" },
}

-- Print helper
local function log(msg)
    vim.notify("[Remora] " .. msg, vim.log.levels.INFO)
end

local function err(msg)
    vim.notify("[Remora] " .. msg, vim.log.levels.ERROR)
end

-- Setup function
function M.setup(config)
    M.config = vim.tbl_deep_extend("force", M.config, config or {})
    
    -- Verify demo path exists
    if not vim.fn.isdirectory(M.config.demo_path) == 1 then
        -- Try alternative paths
        local paths = {
            vim.fn.stdpath("config") .. "/../remora/demo",
            vim.fn.stdpath("config") .. "/../../remora/demo",
            "./demo",
            "../demo",
        }
        for _, p in ipairs(paths) do
            if vim.fn.isdirectory(p) == 1 then
                M.config.demo_path = p
                break
            end
        end
    end
    
    log("Demo path: " .. M.config.demo_path)
    
    -- Register LSP
    M.register_lsp()
    
    -- Create commands
    M.create_commands()
    
    log("Remora V2.1 initialized!")
end

-- Register Remora as LSP server
function M.register_lsp()
    -- Check if lua path includes demo
    local demo_path = M.config.demo_path
    local lua_path_add = demo_path .. "/nvim/lua/?.lua;" .. demo_path .. "/nvim/lua/?/init.lua"
    
    -- Add to package.path
    local current_path = package.path or ""
    if not current_path:find(demo_path, 1, true) then
        package.path = lua_path_add .. ";" .. current_path
    end
    
    log("Registered LSP for: " .. table.concat(M.config.filetypes, ", "))
end

-- Create user commands
function M.create_commands()
    -- Main setup command
    vim.api.nvim_create_user_command("RemoraSetup", function(opts)
        M.setup(opts.fargs)
    end, { nargs = "*" })
    
    -- Start LSP server
    vim.api.nvim_create_user_command("RemoraStart", function()
        -- Enable the LSP client
        local ok, _ = pcall(vim.lsp.start, {
            name = "remora",
            cmd = M.config.lsp_cmd,
            filetypes = M.config.filetypes,
            root_dir = vim.fn.getcwd(),
        })
        
        if ok then
            log("LSP server started!")
            -- Trigger didOpen for current buffer
            if vim.bo.filetype == "python" then
                vim.defer_fn(function()
                    -- Notify LSP that file was opened
                    vim.lsp.buf_notify(0, "textDocument/didOpen", {
                        textDocument = {
                            uri = vim.uri_from_bufnr(0),
                            text = table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n"),
                            version = 0,
                        }
                    })
                    log("File parsed!")
                    
                    -- Request code lens refresh to show agents
                    vim.defer_fn(function()
                        vim.lsp.codelens.refresh()
                        vim.lsp.buf_request(0, "textDocument/codeLens", {
                            textDocument = { uri = vim.uri_from_bufnr(0) }
                        }, function(err, result)
                            if not err and result then
                                log(#result .. " agents found in file")
                            end
                        end)
                    end, 200)
                end, 100)
            end
        else
            err("Failed to start LSP server. Is the demo installed?")
        end
    end, {})
    
    -- Stop LSP server
    vim.api.nvim_create_user_command("RemoraStop", function()
        vim.lsp.stop_client(vim.lsp.get_clients({ name = "remora" }))
        log("LSP server stopped")
    end, {})
    
    -- Restart LSP server
    vim.api.nvim_create_user_command("RemoraRestart", function()
        vim.cmd("RemoraStop")
        vim.defer_fn(function()
            vim.cmd("RemoraStart")
        end, 500)
    end, {})
    
    -- Toggle sidepanel
    vim.api.nvim_create_user_command("RemoraTogglePanel", function()
        -- Try to toggle panel if remora module is loaded
        local ok, remora = pcall(require, "remora")
        if ok and remora and remora.toggle_panel then
            remora.toggle_panel()
        else
            err("Panel module not loaded. Run :RemoraStart first")
        end
    end, {})
    
    -- Chat with agent
    vim.api.nvim_create_user_command("RemoraChat", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.chat"
            end,
            apply = true
        })
    end, {})
    
    -- Request rewrite
    vim.api.nvim_create_user_command("RemoraRewrite", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.requestRewrite"
            end,
            apply = true
        })
    end, {})
    
    -- Accept proposal
    vim.api.nvim_create_user_command("RemoraAccept", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.acceptProposal"
            end,
            apply = true
        })
    end, {})
    
    -- Reject proposal
    vim.api.nvim_create_user_command("RemoraReject", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.rejectProposal"
            end,
            apply = true
        })
    end, {})
    
    -- Show agents
    vim.api.nvim_create_user_command("RemoraAgents", function()
        -- Get all code lenses to show agents
        vim.lsp.codelens.run()
    end, {})
    
    -- Status
    vim.api.nvim_create_user_command("RemoraStatus", function()
        local clients = vim.lsp.get_clients({ name = "remora" })
        if #clients > 0 then
            log("Remora LSP running")
            for _, c in ipairs(clients) do
                log("  - " .. c.name .. " (id: " .. c.rpc.client_id .. ")")
            end
        else
            log("Remora LSP not running. Run :RemoraStart")
        end
    end, {})
    
    -- Parse current file (re-scan for agents)
    vim.api.nvim_create_user_command("RemoraParse", function()
        if vim.bo.filetype ~= "python" then
            err("Not a Python file")
            return
        end
        
        -- Save first to get latest content
        vim.cmd("write")
        
        -- Send didSave to trigger re-parse
        vim.lsp.buf_notify(0, "textDocument/didSave", {
            textDocument = { uri = vim.uri_from_bufnr(0) }
        })
        
        -- Also trigger didOpen to ensure full parse
        vim.lsp.buf_notify(0, "textDocument/didOpen", {
            textDocument = {
                uri = vim.uri_from_bufnr(0),
                text = table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n"),
                version = 0,
            }
        })
        
        -- Refresh code lenses
        vim.defer_fn(function()
            vim.lsp.codelens.refresh()
            log("File re-parsed!")
        end, 200)
    end, {})
    
    log("Commands created: RemoraSetup, RemoraStart, RemoraStop, RemoraRestart, RemoraTogglePanel, RemoraChat, RemoraRewrite, RemoraAccept, RemoraReject, RemoraAgents, RemoraStatus, RemoraParse")
end

-- Auto-start when file is loaded
vim.api.nvim_create_autocmd("FileType", {
    pattern = "python",
    callback = function(args)
        -- Optionally auto-start (uncomment if desired)
        -- vim.cmd("RemoraStart")
    end,
})

-- Auto-install dependencies check
function M.check_dependencies()
    local deps = {
        { cmd = "python", msg = "Python" },
    }
    
    for _, dep in ipairs(deps) do
        if vim.fn.executable(dep.cmd) == 0 then
            err("Missing: " .. dep.msg)
        end
    end
    
    log("Dependency check complete")
end

-- Initialize on require
M.check_dependencies()

return M
