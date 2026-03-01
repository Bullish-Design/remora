-- demo/remora_nvim_startup.lua
-- Convenience script that mirrors what `require("remora").setup()` does so you can
-- profile the Neovim startup sequence from within a terminal session.

local function normalize_opts(opts)
    opts = opts or {}
    return {
        cmd = opts.cmd or { "remora-lsp" },
        filetypes = opts.filetypes or { "python" },
        root_markers = opts.root_markers or { ".remora", ".git" },
        settings = opts.settings or {},
        prefix = opts.prefix or "<leader>r",
    }
end

local function trace(msg)
    vim.notify("[Remora Startup] " .. msg, vim.log.levels.INFO)
end

local function bootstrap(opts)
    opts = normalize_opts(opts)
    local repo_root = "/home/andrew/Documents/Projects/remora"
    local nvim_plugin_path = repo_root .. "/src/remora/lsp/nvim"
    vim.opt.runtimepath:prepend(repo_root)
    vim.opt.runtimepath:prepend(nvim_plugin_path)
    package.path = nvim_plugin_path .. "/lua/?.lua;" .. package.path

    trace("runtimepath prepended with: " .. repo_root)
    trace("runtimepath prepended with: " .. nvim_plugin_path)
    trace("package.path updated for lua modules")

    local ok, remora = pcall(require, "remora")
    if not ok then
        vim.notify(
            "[Remora] Failed to load plugin; check runtimepath\n"
                .. vim.inspect(vim.opt.runtimepath:get()),
            vim.log.levels.ERROR
        )
        return
    end

    local start = vim.loop.hrtime()
    remora.setup(opts)
    local took = (vim.loop.hrtime() - start) / 1e6
    trace(string.format("setup completed in %.2f ms", took))

    if not vim.lsp or not vim.lsp.config then
        vim.notify(
            string.format("[Remora] Detected Neovim %d.%d.%d (LSP config missing)", vim.version().major, vim.version().minor, vim.version().patch),
            vim.log.levels.WARN
        )
    else
        trace("Neovim reports vim.lsp.config available")
    end
end

bootstrap()
