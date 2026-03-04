# Custom Neovim Devenv Implementation Guide

This guide details the step-by-step instructions for refactoring the `remora_demo` to utilize the Custom Neovim (`nv2`) environment via `devenv`. This shift replaces the manual bootstrap scripts (like `start.sh` and `remora_nvim_startup.lua`) with a declarative, reproducible Nix-managed environment.

## Goal Description

Currently, the `remora_demo` relies on a shell script (`start.sh`) to start the Python LSP and instruct the user to manually alter the Neovim runtimepath. By integrating with the custom `nv2` configuration via `devenv`, we can automatically configure `nv2` to include the remora plugin code, pre-install all necessary Python packages (like `pygls`, `lsprotocol`, and `tree-sitter`), and automatically set up the Remora LSP server directly within the `devenv` shell environment.

## Phase 1: Configuring `devenv.yaml`

We must first declare the `nixvim` flake as an input and import it.

### Modify `devenv.yaml`

```diff
  inputs:
    nixpkgs:
      url: github:cachix/devenv-nixpkgs/rolling
    nixpkgs-python:
      url: github:cachix/nixpkgs-python
    nix2container:
      url: github:nlewo/nix2container
    mk-shell-bin:
      url: github:rrbutani/nix-mk-shell-bin
+   nixvim:
+     url: git+file:///home/andrew/Documents/Projects/nixvim
+     flake: false
+
+ imports:
+   - nixvim
```

> [!NOTE]
> The `nixvim` input is imported as a devenv module, which exposes the `nv2.*` options for configuration.

## Phase 2: Configuring `devenv.nix`

We need to add the `nv2` overrides to explicitly configure the custom Neovim environment to pick up the remora plugin, ensuring the environment is perfectly tailored for evaluating the demo.

### Modify `devenv.nix`

Update `devenv.nix` to include `nv2` module settings and inject the Neovim-specific configuration.

```diff
  { pkgs, lib, config, inputs, ... }:

  {
    # ... existing configurations ...

    languages = {
        python = {
            enable = true;
            version = "3.13";
            venv.enable = true;
            uv.enable = true;
          };
      };

+   # Custom Neovim Integration
+   # Add the remora plugin directories to the runtimepath
+   nv2.extraRuntimePaths = [
+     # Main remora nvim plugin (contains lua/remora/init.lua)
+     (builtins.toString ./src/remora/lsp/nvim)
+     # Demo-specific starter module
+     (builtins.toString ./remora_demo/nvim)
+   ];
+
+   # Add extra Init Lua to initialize the Remora demo plugin natively on startup
+   nv2.extraInitLua = ''
+     -- Initialize remora plugin automatically for the demo
+     local ok, remora = pcall(require, "remora")
+     if ok then
+       remora.setup({
+         -- Use the demo LSP server (runs via python -m)
+         cmd = { "python", "-m", "remora_demo.lsp.server" },
+         filetypes = { "python", "markdown" },
+         root_markers = { ".remora", ".git", "pyproject.toml" },
+         prefix = "<leader>r",
+       })
+       vim.notify("[Remora] nv2 initialized remora plugin", vim.log.levels.INFO)
+     else
+       vim.notify("[Remora] Failed to load remora plugin from runtimepath", vim.log.levels.ERROR)
+     end
+   '';

    # ... remaining configuration ...
  }
```

> [!TIP]
> This completely removes the need for `remora_nvim_startup.lua`. The `remora_demo.lsp.server` will be spawned internally by Neovim's LSP client, relying on `cmd` just like a standard LSP in `nvim-lspconfig`.

## Phase 3: Cleanup Demo Artifacts

Since `nv2` fully handles the lifecycle of the editor and its runtime paths, we no longer need the manual bash script bootstrap method.

1. **Delete** `remora_demo/start.sh` - It is obsolete. `devenv` replaces the dependency checking, and the LSP should be spawned by the editor, not as a background process holding a PID.
2. **Delete** `remora_demo/remora_nvim_startup.lua` - The lua initialization logic has been seamlessly integrated directly into the `nv2.extraInitLua` configuration inside `devenv.nix`.

## Phase 4: Validation & Execution

### Automated/Manual Validation Steps

1. **Enter the Nix Shell:**
   Navigate to your local project root and enter the configured shell.
   ```bash
   cd /path/to/remora
   devenv shell
   ```
   *Expected outcome:* The environment processes updates to `devenv.yaml`, reads the Nix directives, and downloads the `nixvim` binaries seamlessly.


2. **Launch Custom Neovim (`nv2`):**
   Execute `nv2` to launch the custom editor.
   ```bash
   nv2
   ```
   *Expected outcome:* Neovim successfully opens. The notification `[Remora] nv2 initialized remora plugin` alerts confirming that `remora.setup()` ran successfully.


3. **Test LSP Connectivity:**
   Open any python file in the project (e.g., `nv2 src/remora/core.py`) to trigger the LSP start based on the `python` filetype configuration. Then check the attached LSPs:
   ```vim
   :LspInfo
   ```
   *Expected outcome:* You should see an active client connected to the buffer executing the command: `python -m remora_demo.lsp.server`.

By completing these phases, the codebase becomes closely intertwined with your robust `nv2` environment, removing manual configuration complexities and empowering effortless demo evaluation within `devenv`.
