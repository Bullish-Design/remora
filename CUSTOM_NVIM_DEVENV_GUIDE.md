# Importing nv2 Into Your devenv.sh Projects

This guide explains how to import the `nixvim` Neovim configuration
into any project managed by [devenv.sh](https://devenv.sh), giving you a
fully configured editor (LSPs, formatters, linters, treesitter, DAP, AI
companion) that activates automatically when you enter the project directory.

It covers local filesystem imports (via direct NixOS module import with
impure mode), git repository imports, per-project overrides, and Neovim
plugin development workflows.

---

## Table of Contents

- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
  - [Architecture Overview](#architecture-overview)
  - [What You Get](#what-you-get)
  - [The Module Option System](#the-module-option-system)
- [Import Methods](#import-methods)
  - [Direct NixOS Module Import (Recommended)](#direct-nixos-module-import-recommended)
  - [Git Repository (GitHub / Remote)](#git-repository-github--remote)
  - [Updating the Import](#updating-the-import)
  - [Known Issues: devenv Input Mechanisms](#known-issues-devenv-input-mechanisms)
- [Per-Project Overrides](#per-project-overrides)
  - [Available Options](#available-options)
  - [Extra Lua Init Code](#extra-lua-init-code)
  - [Environment Variables](#environment-variables)
  - [Extra Packages (LSPs, Formatters, Linters)](#extra-packages-lsps-formatters-linters)
  - [Extra Plugins](#extra-plugins)
  - [Treesitter Grammars](#treesitter-grammars)
  - [Combining Multiple Overrides](#combining-multiple-overrides)
- [Neovim Plugin Development](#neovim-plugin-development)
  - [Basic Plugin Development Setup](#basic-plugin-development-setup)
  - [Adding a Project-Level init.lua](#adding-a-project-level-initlua)
  - [Testing Against Multiple Configurations](#testing-against-multiple-configurations)
- [Reference](#reference)
  - [Full Option Reference](#full-option-reference)
  - [Troubleshooting](#troubleshooting)

---

## Quick Start

This section gets nv2 running in your project in under two minutes.

### 1. Enable impure mode in your project's devenv.yaml

Add `impure: true` to your `devenv.yaml`. This is required because we use
a direct Nix module import from an absolute filesystem path, which is not
allowed in Nix's default pure evaluation mode.

```yaml
# my-project/devenv.yaml
impure: true
inputs:
  nixpkgs:
    url: github:NixOS/nixpkgs/nixos-unstable
  # ... your other inputs
```

> **Why impure mode?** devenv's official input/import mechanism (`devenv.yaml`
> inputs + imports) has a [known bug](#known-issues-devenv-input-mechanisms)
> with local filesystem sources. The `impure: true` + direct NixOS module
> import approach is the reliable workaround. See
> [Import Methods](#import-methods) for details and alternatives.

### 2. Import the nv2 module in your project's devenv.nix

Add the nixvim `devenv.nix` to the NixOS-style `imports` list directly in
your `devenv.nix`:

```nix
# my-project/devenv.nix
{ pkgs, ... }:
{
  imports = [
    /home/andrew/Documents/Projects/nixvim/devenv.nix
  ];

  # Your project's own devenv config goes here.
  # The nv2 editor is already available via the import.
}
```

### 3. Enter the environment

```sh
cd my-project
devenv shell
```

The first run downloads and builds the Nix derivations (this takes a few
minutes). Subsequent runs are instant.

### 4. Launch the editor

```sh
nv2
```

You now have the full nv2 editor with all plugins, LSPs, formatters, and
linters available. When you leave the devenv shell (or cd out with direnv),
`nv2` is no longer on your PATH -- it's scoped to the project.

---

## How It Works

### Architecture Overview

The `nixvim` repository exposes a **devenv module** -- a Nix function
that declares options, packages, and scripts. When you import it into your
project, devenv merges its configuration with your project's own `devenv.nix`.

```
┌─────────────────────────────────────────────┐
│  Your project's devenv.yaml                 │
│                                             │
│  impure: true                               │
│  inputs:                                    │
│    nixpkgs: ...                             │
└───────────────┬─────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────┐
│  Your project's devenv.nix                  │
│                                             │
│  imports = [                                │
│    /path/to/nixvim/devenv.nix               │
│  ];                                         │
│  Can set: nv2.extraPlugins, nv2.env,        │
│    nv2.extraInitLua, etc.                   │
│  Plus your own: packages, languages,        │
│    services, scripts, processes, etc.       │
└───────────────┬─────────────────────────────┘
                │ imports devenv.nix from nixvim
                ▼
┌─────────────────────────────────────────────┐
│  nixvim/devenv.nix (the module)             │
│                                             │
│  Declares: options.nv2.{extraPlugins,       │
│    extraRuntimePaths, extraInitLua, env,    │
│    extraPackages, treesitterGrammars}       │
│                                             │
│  Provides: wrapped neovim binary + nv2      │
│    script + LSPs + formatters + linters     │
└─────────────────────────────────────────────┘
```

The merged result is a single devenv environment containing both your
project's tooling and the nv2 editor.

### What You Get

The import adds the following to your devenv environment:

| Category       | What's Included                                                              |
|----------------|------------------------------------------------------------------------------|
| **Editor**     | Neovim (unstable) wrapped with all plugins via `wrapNeovimUnstable`          |
| **Script**     | `nv2` command on PATH that launches the configured editor                    |
| **Plugins**    | mini.nvim, nvim-lspconfig, conform, nvim-lint, nvim-treesitter (+context),   |
|                | gitsigns, neogit, diffview, nvim-dap (+ui, +python), neotest (+adapters),    |
|                | obsidian.nvim, markdown-preview, codecompanion                               |
| **LSP**        | lua_ls, nil_ls, bashls, pyright, rust-analyzer, clangd, gopls, ts_ls,        |
|                | eslint, html, cssls, jsonls, yamlls                                          |
| **Formatters** | stylua, alejandra, ruff, prettierd, goimports-reviser, nixfmt                |
| **Linters**    | shellcheck, statix, yamllint, selene, golangci-lint, markdownlint-cli2       |
| **DAP**        | debugpy                                                                      |
| **Treesitter** | 17 grammars: lua, vim, vimdoc, python, nix, rust, go, js, ts, tsx, json,     |
|                | yaml, html, css, markdown, markdown_inline, bash, c, cpp                     |
| **Utilities**  | git, ripgrep, fd                                                             |

All of these are added to your PATH inside the devenv shell. They don't
pollute your system -- they only exist within the project environment.

### The Module Option System

The nv2 module exposes a set of options under the `nv2` namespace that let
consumer projects customize the editor without modifying the nixvim
repository. These options are evaluated at Nix build time and produce a
tailored `nv2` wrapper script.

When you write `nv2.extraPlugins = [ ... ]` in your project's `devenv.nix`,
Nix rebuilds the wrapped Neovim binary with those plugins included in the
packpath. When you write `nv2.extraInitLua = "..."`, Nix writes that Lua
code to a file in the store and adds a `-c "luafile ..."` flag to the `nv2`
script so it runs after the base `init.lua`.

This means all customization is declarative, reproducible, and tracked by
your project's `devenv.lock`.

---

## Import Methods

### Direct NixOS Module Import (Recommended)

This is the working approach. It uses a standard NixOS-style `imports` list
directly in your `devenv.nix`, bypassing devenv's input/import system entirely.

**Requirements:** `impure: true` in `devenv.yaml` (to allow absolute path
access during Nix evaluation).

```yaml
# my-project/devenv.yaml
impure: true
inputs:
  nixpkgs:
    url: github:cachix/devenv-nixpkgs/rolling
```

```nix
# my-project/devenv.nix
{ pkgs, ... }:
{
  imports = [
    /home/andrew/Documents/Projects/nixvim/devenv.nix
  ];

  # Your project config here...
}
```

**How it works:** The `imports` list in `devenv.nix` is standard NixOS module
machinery. Nix reads the file at the absolute path and merges the module's
options and configuration with your project's `devenv.nix`. The nixvim module
uses relative paths (`./nvim`, `./plugins.nix`) internally, which resolve
relative to its own location.

**Key behaviors:**
- Picks up the current state of the file on disk (including uncommitted
  changes) -- this is useful during development.
- No lock file entry for nixvim -- the import is not version-pinned.
- Requires `impure: true` because Nix's pure evaluation mode forbids
  access to absolute filesystem paths.
- The absolute path is not portable across machines. Each developer needs
  the nixvim repo at the same path, or must adjust the import.

**When to use:** Local development on your machine. This is the only
method that reliably works for local filesystem imports as of devenv 1.11.2.

**Trade-offs:**
- Not reproducible: no commit hash lock.
- Not portable: hardcoded absolute path.
- `impure: true` relaxes evaluation purity for the entire devenv environment.
  This is acceptable for development environments but means Nix cannot
  guarantee perfect reproducibility.

### Git Repository (GitHub / Remote)

For sharing across machines or with teammates, push your nixvim config to
a git host and use devenv's standard input mechanism:

```yaml
# my-project/devenv.yaml
inputs:
  nixpkgs:
    url: github:cachix/devenv-nixpkgs/rolling
  nixvim:
    url: github:yourusername/nixvim
    flake: false
imports:
  - nixvim
```

Or for a self-hosted git server:

```yaml
inputs:
  nixvim:
    url: git+https://git.example.com/user/nixvim
    flake: false
imports:
  - nixvim
```

Or pinned to a specific branch or tag:

```yaml
inputs:
  nixvim:
    url: github:yourusername/nixvim?ref=main
    flake: false
```

**How it works:** Nix fetches the repository from the remote, caches it
locally, and locks the exact commit in `devenv.lock`. devenv's auto-generated
flake imports the `devenv.nix` from the fetched source.

**Key behaviors:**
- Fully reproducible: locked to a specific commit in `devenv.lock`.
- Portable: any machine with network access can fetch the repo.
- Does **not** require `impure: true`.
- Only committed, pushed changes are visible.

**When to use:** Production, CI, sharing with teammates, or when you want
reproducible builds. This is the production-grade method.

### Updating the Import

**For the direct NixOS module import:** Changes to the nixvim directory on
disk are picked up immediately on the next `devenv shell` invocation (Nix
re-evaluates the file each time).

**For the git repository method:** The commit hash is locked in
`devenv.lock`. To update:

```sh
# Update just the nixvim input
devenv update nixvim

# Or update all inputs
devenv update
```

This fetches the latest commit, updates `devenv.lock`, and the next
`devenv shell` invocation will use the new version.

### Known Issues: devenv Input Mechanisms {#known-issues-devenv-input-mechanisms}

The following approaches for local filesystem imports were tested and found
to be broken as of devenv 1.11.2 (Nix 2.30.4):

| Approach | Issue |
|----------|-------|
| `git+file:///path` input | **Nix SIGABRT crash** -- `CanonPath::removePrefix` assertion failure in Nix 2.30.4. This is a bug in Nix's C++ path handling for local git repos. |
| `path:/path` input + `flake: false` | Lock resolves but evaluation fails: `'nixvim' is too short to be a valid store path`. devenv's `importModule` function coerces the input to a store path, but non-flake `path:` inputs aren't copied to the store. |
| `path:/path` input + `flake: true` | Nix tries to find `.devenv.flake.nix` inside the nixvim source, which doesn't exist. |
| `../nixvim` relative import | devenv CLI rejects paths that resolve outside the git repository. |
| Direct NixOS `imports` without `impure: true` | Fails with `access to absolute path is forbidden in pure evaluation mode`. |

The `github:` and `git+https:` input methods work correctly because they
use Nix's archive/remote fetching rather than the buggy local git path
handling.

---

## Per-Project Overrides

All overrides go in your project's `devenv.nix` under the `nv2` attribute
set. These are NixOS-style module options -- they compose cleanly with the
base configuration.

### Available Options

| Option                     | Type                      | Default     | Purpose                                       |
|----------------------------|---------------------------|-------------|-----------------------------------------------|
| `nv2.extraPlugins`         | list of packages          | `[]`        | Additional Vim plugins for the packpath        |
| `nv2.extraRuntimePaths`    | list of strings           | `[]`        | Extra dirs prepended to runtimepath            |
| `nv2.extraInitLua`         | multiline string          | `""`        | Lua code sourced after init.lua                |
| `nv2.treesitterGrammars`   | function (grammarSet -> list) | (17 grammars) | Override which treesitter grammars to bundle |
| `nv2.env`                  | attribute set of strings  | `{}`        | Environment variables exported before launch   |
| `nv2.extraPackages`        | list of packages          | `[]`        | Additional packages added to devenv PATH       |

### Extra Lua Init Code

`nv2.extraInitLua` is the most flexible override. The Lua code you provide
runs **after** the base `init.lua` has finished loading all plugins and
configuration. This means all base modules (`mini.*`, `lspconfig`, `conform`,
etc.) are already available.

#### Override the color scheme

```nix
# my-project/devenv.nix
{ pkgs, ... }:
{
  nv2.extraInitLua = ''
    -- Tokyo Night-inspired palette for this project
    require("mini.hues").setup({
      background = "#1a1b26",
      foreground = "#c0caf5",
      saturation = "high",
      accent = "cyan",
    })
  '';
}
```

#### Add project-specific keymaps

```nix
{
  nv2.extraInitLua = ''
    -- Quick access to project test runner
    vim.keymap.set("n", "<leader>pt", function()
      vim.cmd("!make test")
    end, { desc = "Run project tests" })
  '';
}
```

#### Configure an additional LSP server

```nix
{ pkgs, ... }:
{
  nv2.extraPackages = [ pkgs.haskell-language-server ];

  nv2.extraInitLua = ''
    vim.lsp.config("hls", {
      settings = {
        haskell = {
          formattingProvider = "ormolu",
        },
      },
    })
    vim.lsp.enable("hls")
  '';
}
```

#### Override existing LSP settings

Since `extraInitLua` runs after the base config, you can call
`vim.lsp.config()` again to merge additional settings into an existing
server:

```nix
{
  nv2.extraInitLua = ''
    -- Use stricter type checking for this Python project
    vim.lsp.config("pyright", {
      settings = {
        python = {
          analysis = {
            typeCheckingMode = "strict",
          },
        },
      },
    })
  '';
}
```

### Environment Variables

`nv2.env` exports variables before launching Neovim. These are visible to
both Neovim and any child processes it spawns.

#### LLM API keys

```nix
{
  nv2.env = {
    ANTHROPIC_API_KEY = "sk-ant-api03-...";
    OPENAI_API_KEY = "sk-...";
  };
}
```

> **Security note:** Hardcoding API keys in `devenv.nix` means they end up
> in the Nix store (world-readable on your machine) and in version control
> if you commit `devenv.nix`. For sensitive keys, prefer one of these
> alternatives:
>
> - Set them in your shell's environment (`.bashrc`, `.zshenv`, etc.) --
>   Neovim inherits the parent shell's environment automatically.
> - Use a `devenv.local.nix` file (add it to `.gitignore`):
>   ```nix
>   # my-project/devenv.local.nix
>   {
>     nv2.env.ANTHROPIC_API_KEY = "sk-ant-api03-...";
>   }
>   ```
>   devenv automatically loads `devenv.local.nix` if it exists and merges
>   it with `devenv.nix`.
> - Use `nv2.extraInitLua` with a secret manager:
>   ```nix
>   {
>     nv2.extraInitLua = ''
>       vim.env.ANTHROPIC_API_KEY = vim.fn.system("pass show api/anthropic"):gsub("%s+$", "")
>     '';
>   }
>   ```

#### Tool-specific configuration

```nix
{
  nv2.env = {
    # Tell rust-analyzer to use a specific toolchain
    RUSTUP_TOOLCHAIN = "nightly-2026-01-15";
    # Configure ruff for this project
    RUFF_CONFIG = "./pyproject.toml";
  };
}
```

### Extra Packages (LSPs, Formatters, Linters)

`nv2.extraPackages` adds packages to the devenv environment alongside the
base set. Use this when your project needs tooling that the base config
doesn't include.

```nix
{ pkgs, ... }:
{
  nv2.extraPackages = with pkgs; [
    # Haskell tooling
    haskell-language-server
    ormolu
    hlint

    # Elixir tooling
    elixir-ls
    mix2nix

    # Zig
    zls
  ];
}
```

These packages are on PATH inside the devenv shell, so Neovim's LSP client,
conform, nvim-lint, and other tools can find them automatically.

### Extra Plugins

`nv2.extraPlugins` adds Vim plugins to the wrapped Neovim's packpath. This
triggers a rebuild of the Neovim wrapper derivation.

```nix
{ pkgs, ... }:
{
  nv2.extraPlugins = [
    pkgs.vimPlugins.vim-fugitive
    pkgs.vimPlugins.vim-sleuth
    pkgs.vimPlugins.nvim-surround
  ];
}
```

You can also build plugins from source:

```nix
{ pkgs, ... }:
{
  nv2.extraPlugins = [
    (pkgs.vimUtils.buildVimPlugin {
      pname = "some-new-plugin";
      version = "unstable-2026-02-15";
      src = pkgs.fetchFromGitHub {
        owner = "author";
        repo = "some-new-plugin.nvim";
        rev = "abc123...";
        hash = "sha256-...";
      };
    })
  ];
}
```

To set up newly added plugins, combine `extraPlugins` with `extraInitLua`:

```nix
{ pkgs, ... }:
{
  nv2.extraPlugins = [ pkgs.vimPlugins.trouble-nvim ];

  nv2.extraInitLua = ''
    require("trouble").setup({
      mode = "workspace_diagnostics",
    })
    vim.keymap.set("n", "<leader>xx", "<cmd>Trouble<cr>", { desc = "Trouble" })
  '';
}
```

### Treesitter Grammars

`nv2.treesitterGrammars` replaces the default grammar list entirely. This
is a function that receives the grammar package set and returns a list.

```nix
{
  # Only include grammars relevant to a Haskell project
  nv2.treesitterGrammars = p: [
    p.haskell p.cabal
    p.lua p.vim p.vimdoc
    p.nix p.json p.yaml p.markdown p.markdown_inline p.bash
  ];
}
```

If you want to **add** grammars to the defaults rather than replacing them,
define a helper:

```nix
{ pkgs, lib, ... }:
let
  defaultGrammars = p: [
    p.lua p.vim p.vimdoc p.python p.nix p.rust p.go
    p.javascript p.typescript p.tsx p.json p.yaml
    p.html p.css p.markdown p.markdown_inline
    p.bash p.c p.cpp
  ];
in
{
  nv2.treesitterGrammars = p: (defaultGrammars p) ++ [
    p.haskell
    p.elixir
    p.zig
  ];
}
```

### Combining Multiple Overrides

All options compose. Here's a full example for a Rust project:

```nix
{ pkgs, ... }:
{
  # Add rust-specific packages not in the base set
  nv2.extraPackages = with pkgs; [
    cargo-watch
    cargo-nextest
    bacon
  ];

  # Add extra treesitter grammars for TOML (common in Rust projects)
  nv2.treesitterGrammars = p: [
    p.lua p.vim p.vimdoc p.python p.nix p.rust p.go
    p.javascript p.typescript p.tsx p.json p.yaml
    p.html p.css p.markdown p.markdown_inline
    p.bash p.c p.cpp
    p.toml  # added for Cargo.toml
  ];

  # Warm color scheme for Rust work
  nv2.extraInitLua = ''
    require("mini.hues").setup({
      background = "#1c1210",
      foreground = "#d4be98",
      saturation = "medium",
      accent = "orange",
    })

    -- Bacon integration keymap
    vim.keymap.set("n", "<leader>rb", function()
      vim.cmd("terminal bacon")
    end, { desc = "Run bacon (Rust watcher)" })
  '';

  # Rust-specific env
  nv2.env = {
    RUST_BACKTRACE = "1";
  };

  # Your project's own devenv config (not nv2-related)
  languages.rust.enable = true;
}
```

---

## Neovim Plugin Development

This section covers using nv2 as a development environment for building
Neovim plugins.

### Basic Plugin Development Setup

When developing a Neovim plugin, you want the plugin's source directory on
Neovim's runtimepath so changes are picked up immediately without rebuilding
any Nix derivation.

Given a plugin project at `~/Projects/my-plugin.nvim/`:

```
my-plugin.nvim/
├── lua/
│   └── my-plugin/
│       └── init.lua
├── plugin/
│   └── my-plugin.lua
├── devenv.nix
└── devenv.yaml
```

```yaml
# my-plugin.nvim/devenv.yaml
impure: true
inputs:
  nixpkgs:
    url: github:cachix/devenv-nixpkgs/rolling
```

```nix
# my-plugin.nvim/devenv.nix
{ pkgs, ... }:
{
  imports = [
    /home/andrew/Documents/Projects/nixvim/devenv.nix
  ];

  # Add the current project root to Neovim's runtimepath.
  # builtins.toString ./. resolves to the project directory.
  nv2.extraRuntimePaths = [ (builtins.toString ./.) ];
}
```

Now when you run `nv2`, Neovim loads your plugin from the project directory.
Edit `lua/my-plugin/init.lua`, restart Neovim (or use `:luafile %`), and
your changes are live.

**How `extraRuntimePaths` works:** Each path is prepended to Neovim's
`runtimepath` via `--cmd "set rtp^=/path/to/dir"` before `init.lua` runs.
This means Neovim's plugin loader will find your `plugin/` directory and
Lua's `require()` will find your `lua/` directory.

### Adding a Project-Level init.lua

For more complex plugin development, you often want project-specific
configuration: setting up your plugin with specific options, loading test
dependencies, enabling debug logging, etc.

Use `nv2.extraInitLua` to run Lua code after the base editor config loads:

```nix
# my-plugin.nvim/devenv.nix
{ pkgs, ... }:
{
  nv2.extraRuntimePaths = [ (builtins.toString ./.) ];

  nv2.extraPlugins = [
    pkgs.vimPlugins.plenary-nvim  # if your plugin depends on plenary
  ];

  nv2.extraInitLua = ''
    -- Configure the plugin being developed with debug options
    require("my-plugin").setup({
      debug = true,
      log_level = "trace",
    })

    -- Convenience keymaps for development
    vim.keymap.set("n", "<leader>pr", function()
      -- Reload the plugin module (clear cached require)
      package.loaded["my-plugin"] = nil
      package.loaded["my-plugin.core"] = nil
      require("my-plugin").setup({ debug = true, log_level = "trace" })
      vim.notify("my-plugin reloaded", vim.log.levels.INFO)
    end, { desc = "Reload my-plugin" })

    vim.keymap.set("n", "<leader>ps", function()
      vim.cmd("source plugin/my-plugin.lua")
      vim.notify("plugin/my-plugin.lua sourced", vim.log.levels.INFO)
    end, { desc = "Source plugin script" })
  '';
}
```

#### Alternative: keep the project init in a separate file

If your project-level init is large or you want to edit it without
triggering a Nix rebuild, you can keep it as a standalone Lua file and
reference it:

```
my-plugin.nvim/
├── lua/
│   └── my-plugin/
│       └── init.lua
├── .nvim/
│   └── init.lua          <-- project-level init
├── devenv.nix
└── devenv.yaml
```

```nix
# my-plugin.nvim/devenv.nix
{ pkgs, ... }:
{
  nv2.extraRuntimePaths = [ (builtins.toString ./.) ];

  nv2.extraInitLua = ''
    -- Source project-local init if it exists
    local project_init = vim.fn.getcwd() .. "/.nvim/init.lua"
    if vim.fn.filereadable(project_init) == 1 then
      dofile(project_init)
    end
  '';
}
```

Now you can freely edit `.nvim/init.lua` without any Nix rebuilds. The
`nv2.extraInitLua` snippet is tiny and rarely changes, while the actual
project configuration lives in a plain Lua file.

```lua
-- my-plugin.nvim/.nvim/init.lua

-- Set up the plugin with dev options
require("my-plugin").setup({
  debug = true,
  log_level = "trace",
})

-- Hot-reload keymap
vim.keymap.set("n", "<leader>pr", function()
  for name, _ in pairs(package.loaded) do
    if name:match("^my%-plugin") then
      package.loaded[name] = nil
    end
  end
  require("my-plugin").setup({ debug = true, log_level = "trace" })
  vim.notify("my-plugin reloaded")
end, { desc = "Reload my-plugin" })
```

### Testing Against Multiple Configurations

When building a plugin for distribution, you may want to test it with
minimal configuration (no other plugins loaded). You can create a separate
script for that:

```nix
# my-plugin.nvim/devenv.nix
{ pkgs, ... }:
let
  # Minimal neovim with only your plugin and its dependencies
  minimalConfig = pkgs.neovimUtils.makeNeovimConfig {
    plugins = map (p: { plugin = p; }) [
      pkgs.vimPlugins.plenary-nvim
    ];
  };
  minimalNeovim = pkgs.wrapNeovimUnstable pkgs.neovim-unwrapped (minimalConfig // {
    neovimRcContent = "";
    luaRcContent = "";
  });
in
{
  # Full nv2 for development
  nv2.extraRuntimePaths = [ (builtins.toString ./.) ];

  # Minimal neovim for isolated testing
  scripts.nv2-minimal.exec = ''
    exec ${minimalNeovim}/bin/nvim \
      --cmd "set rtp^=${builtins.toString ./.}" \
      -u NONE \
      -c "lua require('my-plugin').setup()" \
      "$@"
  '';

  # Test runner
  scripts.nv2-test.exec = ''
    exec ${minimalNeovim}/bin/nvim \
      --cmd "set rtp^=${builtins.toString ./.}" \
      --headless \
      -c "lua require('plenary.test_harness').test_directory('tests/', { minimal_init = 'tests/init.lua' })" \
      "$@"
  '';
}
```

This gives you three commands:
- `nv2` -- full editor with your plugin loaded
- `nv2-minimal` -- bare Neovim with only your plugin (for manual testing)
- `nv2-test` -- headless test runner for CI/automated tests

---

## Reference

### Full Option Reference

#### `nv2.extraPlugins`

- **Type:** `list of package`
- **Default:** `[]`
- **Description:** Additional Vim plugin packages included in the wrapped
  Neovim's packpath. Triggers a rebuild of the Neovim wrapper.

#### `nv2.extraRuntimePaths`

- **Type:** `list of string`
- **Default:** `[]`
- **Description:** Paths prepended to `runtimepath` via `--cmd` flags. These
  are injected before `init.lua` runs, so `plugin/` and `lua/` directories
  at these paths are available immediately. Use `builtins.toString ./.` to
  reference the consumer project's root.

#### `nv2.extraInitLua`

- **Type:** `lines` (multiline string)
- **Default:** `""`
- **Description:** Lua code written to a file in the Nix store and sourced
  after `init.lua` via `-c "luafile ..."`. Runs after all base plugins and
  configuration are loaded.

#### `nv2.treesitterGrammars`

- **Type:** `function` (grammar set -> list of packages)
- **Default:** 17 grammars (lua, vim, vimdoc, python, nix, rust, go, js, ts,
  tsx, json, yaml, html, css, markdown, markdown_inline, bash, c, cpp)
- **Description:** Replaces the treesitter grammar list entirely. Receives
  the grammar package set as argument.

#### `nv2.env`

- **Type:** `attribute set of string`
- **Default:** `{}`
- **Description:** Environment variables exported in the `nv2` wrapper
  script before Neovim launches. Visible to Neovim and child processes.

#### `nv2.extraPackages`

- **Type:** `list of package`
- **Default:** `[]`
- **Description:** Additional packages added to the devenv environment.
  These are on PATH alongside the base LSPs, formatters, and linters.

### Troubleshooting

#### "module 'X' not found" when using extraRuntimePaths

Ensure the path you're adding contains the expected directory structure.
For a Lua module `require("foo")` to resolve, there must be a `lua/foo.lua`
or `lua/foo/init.lua` at one of the runtimepath entries.

Verify your runtimepath inside Neovim:
```vim
:echo &runtimepath
```

#### Changes to nixvim aren't showing up

If you use the **direct NixOS module import** (recommended), changes to
the nixvim directory on disk are picked up on the next `devenv shell`
invocation. If they still don't appear, try removing `.devenv/` and
retrying.

If you use the **github: input** method, only committed and pushed files
are visible. Commit your changes in the nixvim repo, push them, then run
`devenv update nixvim` in the consumer project.

#### nv2.extraInitLua changes require devenv rebuild

This is expected. `extraInitLua` content is written to a file in the Nix
store at build time. Any change to the string triggers a new store path and
a new `nv2` wrapper script. If you want to iterate without rebuilds, use
the [separate file approach](#alternative-keep-the-project-init-in-a-separate-file)
described in the plugin development section.

#### Conflicting scripts.nv2

If your project's `devenv.nix` also defines `scripts.nv2.exec`, it will
conflict with the one from the nv2 module. The module system will raise an
error about duplicate definitions. Don't redefine `nv2` -- use the module
options instead. If you need a completely custom launch script, define it
under a different name (e.g., `scripts.nv2-custom.exec`).

#### Extra plugins aren't loading

Confirm the plugin appears in the packpath:
```vim
:echo &packpath
```

Plugins added via `nv2.extraPlugins` should appear under a
`/nix/store/...-vim-pack-dir/pack/myNeovimPackages/start/` path. If they
don't, check that the package you're passing is a valid Vim plugin
derivation (built with `buildVimPlugin` or from `pkgs.vimPlugins`).

#### devenv.local.nix for machine-specific overrides

devenv automatically loads `devenv.local.nix` if present. Add it to
`.gitignore` and use it for secrets or machine-specific config:

```nix
# devenv.local.nix (not committed)
{
  nv2.env = {
    ANTHROPIC_API_KEY = "sk-ant-...";
    OPENAI_API_KEY = "sk-...";
  };
}
```
