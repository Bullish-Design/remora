{ pkgs, lib, config, inputs, ... }:

{
  imports = [
    /home/andrew/Documents/Projects/nixvim/devenv.nix
  ];
  # https://devenv.sh/basics/
  env.GREET = "devenv";

  # https://devenv.sh/packages/
  packages = [
    pkgs.git
    pkgs.uv
  ];

  # https://devenv.sh/languages/
  languages = {
    python = {
      enable = true;
      version = "3.13";
      venv.enable = true;
      uv.enable = true;
    };
  };

  # ============================================================================
  # Custom Neovim (nv2) Integration for Remora Demo
  # ============================================================================
  # This configures the nv2 editor (from nixvim) to automatically load the
  # remora plugin and connect to the demo LSP server.
  #
  # nui.nvim and nui-components.nvim (required by remora's panel UI) are
  # included in the base nixvim plugin set.

  # Add the remora neovim plugin directories to the runtimepath
  nv2.extraRuntimePaths = [
    # Main remora nvim plugin (contains lua/remora/init.lua)
    (builtins.toString ./src/remora/lsp/nvim)
    # Demo-specific starter module
    (builtins.toString ./remora_demo/nvim)
  ];

  # Extra Lua init to automatically set up the remora plugin on nv2 startup
  nv2.extraInitLua = ''
    -- Initialize remora plugin automatically for the demo
    local ok, remora = pcall(require, "remora")
    if ok then
      remora.setup({
        -- Use the demo LSP server (runs via python -m)
        cmd = { "python", "-m", "remora_demo.lsp.server" },
        filetypes = { "python", "markdown" },
        root_markers = { ".remora", ".git", "pyproject.toml" },
        prefix = "<leader>r",
      })
      vim.notify("[Remora] nv2 initialized remora plugin", vim.log.levels.INFO)
    else
      vim.notify("[Remora] Failed to load remora plugin from runtimepath", vim.log.levels.ERROR)
    end
  '';

  # https://devenv.sh/scripts/
  scripts.hello.exec = ''
    echo hello from $GREET
  '';

  enterShell = ''
    hello
    git --version
    echo ""
    echo "Remora dev environment ready!"
    echo "  - Run 'nv2' to launch Neovim with the remora plugin pre-configured"
    echo "  - Open a Python file to auto-start the Remora LSP"
  '';

  # https://devenv.sh/tests/
  enterTest = ''
    echo "Running tests"
    git --version | grep --color=auto "${pkgs.git.version}"
  '';

  # See full reference at https://devenv.sh/reference/options/
}
