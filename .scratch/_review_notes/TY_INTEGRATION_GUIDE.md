# Ty & Remora Tandem Integration Guide

You are perfectly correct. In this tandem architecture:
1. **`ty` (Astral's LSP)** will handle 100% of the standard Python language features natively: blazing fast type-checking, inline diagnostics, find references, auto-imports, hover documentation, and code completions.
2. **`remora-lsp` (Your Pygls server)** will handle *only* the Remora-specific functionality: LLM Swarm Executor interactions, "Ghost Node" UI-driven code generation, diff approvals, and routing custom AI agents.

This guide provides a step-by-step implementation for integrating both servers into your Neovim environment using your `devenv` setup.

## Phase 1: Installing `ty` Dependencies

We first need to ensure `ty` is available on your system path. Assuming Astral's `ty` is packaged via Nix or installable via a package manager/cargo within your `devenv` environment, we will add it to the `devenv.yaml` or `devenv.nix` configuration.

### Modify `devenv.nix` packages

Assuming `ty` is available in `nixpkgs` (or you can install it via an overlay/`uv`), add it to your environment packages.

```nix
  { pkgs, lib, config, inputs, ... }:

  {
    packages = [
      pkgs.ty # Or however the Astral ty binary is packaged
      # (If it's not in nixpkgs yet, you might install it via `uv tool install ty` in a post-hook)
    ];

    languages = {
        python = {
            enable = true;
            version = "3.13";
            venv.enable = true;
            uv.enable = true;
        };
    };
```

## Phase 2: Configuring Dual-LSP Attachment in Neovim

Neovim natively supports attaching multiple different Language Servers to the same buffer. We just need to configure both to start sequentially or concurrently when a Python file is opened.

We will modify the `nv2.extraInitLua` block inside `devenv.nix` (which you built in the Custom Neovim Devenv Implementation Guide) to initialize `ty` right alongside `remora`.

### Modify `devenv.nix` (Neovim Configuration)

```lua
   # Add extra Init Lua to initialize both the Remora demo plugin and Ty natively on startup
   nv2.extraInitLua = ''
     local ok_remora, remora = pcall(require, "remora")
     if ok_remora then
       -- 1. Initialize custom generic AI Agent Server
       remora.setup({
         cmd = { "python", "-m", "remora_demo.lsp.server" },
         filetypes = { "python", "markdown" },
         root_markers = { ".remora", ".git", "pyproject.toml" },
         prefix = "<leader>r",
       })
       vim.notify("[Remora] nv2 initialized custom Remora plugin", vim.log.levels.INFO)
     else
       vim.notify("[Remora] Failed to load remora plugin from runtimepath", vim.log.levels.ERROR)
     end

     -- 2. Initialize the Astral ty Language Server for standard LSP features
     local lspconfig = require("lspconfig")
     
     -- Only run if the executable exists
     if vim.fn.executable("ty") == 1 then
       -- Custom ty setup block (if it isn't officially in lspconfig yet)
       local configs = require("lspconfig.configs")
       if not configs.ty then
         configs.ty = {
           default_config = {
             cmd = { "ty" }, -- The command to start the ty LSP
             filetypes = { "python" },
             root_dir = lspconfig.util.root_pattern("pyproject.toml", "setup.py", ".git"),
           },
         }
       end
       
       -- Setup ty
       lspconfig.ty.setup({
           -- Optional: Overwrite capabilities if you want to turn off specific ty features
           -- in favor of another tool, but generally ty is all-inclusive.
       })
       
       vim.notify("[Remora] nv2 initialized ty language server", vim.log.levels.INFO)
     else
       vim.notify("[Remora] ty binary not found in PATH", vim.log.levels.WARN)
     end
   '';
```

## Phase 3: Preventing Duplication (Important)

When running multiple LSPs, they might overlap in functionality, especially if you previously had `pyright`, `pylsp`, or another python LSP running.

### 1. Disable Competing Type Checkers
Ensure you have removed `pyright` or `basedpyright` from your `lspconfig` setup to avoid duplicated diagnostics (red squiggly lines).

### 2. Isolate Responsibilities
- **`remora-lsp`:** Should **not** register capabilities for `textDocument/completion`, `textDocument/hover`, or `textDocument/diagnostic` unless those specific requests are explicitly resolving custom AI functionality (e.g., providing completions for a Ghost Node). The Python specification standard should be entirely delegated to `ty`.
- **`ty`:** Should be completely unaware of the AI swarm. It just checks your Python types.

## Phase 4: Validating the Tandem Setup

1. **Enter the Nix Shell:**
   ```bash
   devenv shell
   ```
2. **Launch Neovim:**
   ```bash
   nv2 src/remora/core.py
   ```
3. **Check Active LSPs:**
   Type the following command inside Neovim:
   ```vim
   :LspInfo
   ```
   **Expected Outcome:** Under active clients attached to the `core.py` buffer, you should see **two** entries:
   * `ty` (Providing diagnostics, go-to-definition, etc.)
   * `remora_demo.lsp.server` (Listening for agent commands and custom Swarm invocations)

With this completed, your UI effectively gets the speed of Astral's `ty` backend for coding, without sacrificing the vast, custom logic available in your `pygls` Remora server.
