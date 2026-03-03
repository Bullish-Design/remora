# companion.nvim

Neovim plugin for Companion - an ambient knowledge work assistant that provides contextual information as you code.

## Features

- **Cursor tracking**: Sends cursor position to Companion as you navigate code
- **Sidebar panel**: Displays contextual information, related code snippets, and connections
- **Live updates**: Sidebar updates as you move through your codebase

## Requirements

- Neovim 0.11+ (for `vim.lsp.config` API)
- `companion-lsp` command available in PATH (from remora package)

## Installation

### Using lazy.nvim

```lua
{
    dir = "path/to/remora/remora_demo/companion/nvim",
    config = function()
        require("companion").setup({
            -- Options (all optional)
            filetypes = { "python", "markdown", "lua" },
            sidebar_width = 40,
            auto_open_sidebar = false,
        })
    end,
}
```

### Using packer.nvim

```lua
use {
    "path/to/remora/remora_demo/companion/nvim",
    config = function()
        require("companion").setup()
    end,
}
```

### Manual

Add to your `runtimepath`:

```lua
vim.opt.runtimepath:append("path/to/remora/remora_demo/companion/nvim")
require("companion").setup()
```

## Configuration

```lua
require("companion").setup({
    -- LSP command (default: companion-lsp)
    cmd = { "companion-lsp" },
    
    -- Supported filetypes
    filetypes = { "python", "markdown", "lua", "typescript", "javascript" },
    
    -- Root directory markers
    root_markers = { ".companion", ".git" },
    
    -- Write sidebar to this file (for Obsidian integration)
    sidebar_output = nil,  -- e.g., "/path/to/vault/sidebar.md"
    
    -- Sidebar panel width
    sidebar_width = 40,
    
    -- Auto-open sidebar on startup
    auto_open_sidebar = false,
    
    -- Debounce delay for cursor updates (ms)
    update_delay_ms = 100,
    
    -- Enable debug logging
    debug = false,
    
    -- Keymap prefix (default: <leader>k)
    prefix = "<leader>k",
})
```

## Commands

| Command | Description |
|---------|-------------|
| `:CompanionSidebar` | Toggle the sidebar panel |
| `:CompanionRefresh` | Manually refresh sidebar content |
| `:CompanionStatus` | Show LSP client status |

## Keymaps

Default keymaps (with `<leader>k` prefix):

| Keymap | Description |
|--------|-------------|
| `<leader>ks` | Toggle sidebar |
| `<leader>kr` | Refresh sidebar |

## How It Works

1. **Cursor tracking**: On `CursorHold` events, the plugin sends your cursor position to the `companion-lsp` server
2. **Agent cascade**: The server runs a cascade of tiny agents that extract context, search for related content, and analyze connections
3. **Sidebar composition**: A composer agent assembles insights from all agents into a markdown sidebar
4. **Display**: The sidebar panel shows the composed content, updating as you navigate

## Obsidian Integration

To have the sidebar written to your Obsidian vault:

```lua
require("companion").setup({
    sidebar_output = vim.fn.expand("~/Documents/Obsidian/MyVault/.companion/sidebar.md"),
})
```

Then in Obsidian, you can embed this file or use a plugin to display it.

## Troubleshooting

### LSP not starting

1. Check that `companion-lsp` is in your PATH:
   ```bash
   which companion-lsp
   ```

2. If not, ensure the remora package is installed:
   ```bash
   uv pip install -e /path/to/remora
   ```

### No sidebar content

1. The workspace needs to be indexed first. Run with debug:
   ```lua
   require("companion").setup({ debug = true })
   ```

2. Check the LSP logs in Neovim:
   ```vim
   :LspLog
   ```

### Slow updates

Increase the debounce delay:
```lua
require("companion").setup({ update_delay_ms = 500 })
```
