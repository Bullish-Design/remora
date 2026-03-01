# Remora Neovim V2.1 Demo - LSP-Native Architecture

A complete rewrite where LSP is the spine. Neovim connects to Remora as a language server. Pydantic models are the bridge—they define both the agent structure AND the LSP protocol extensions.

## Architecture Overview

```
NEOVIM (LSP Client) <-- stdio/TCP --> REMORA LSP SERVER (Python)

Features:
- Agent IDs inline        → textDocument/codeLens
- Agent details on hover  → textDocument/hover  
- Tool menu               → textDocument/codeAction
- Pending proposals       → textDocument/publishDiagnostics
- Apply rewrites          → workspace/applyEdit
- Document symbols        → textDocument/documentSymbol
```

## Quick Start

### Install

```bash
uv pip install -e ".[dev]"
```

### Start the LSP Server

```bash
# Standalone
remora-lsp

# Or via CLI
remora swarm start --lsp

# Or via Python module
python -m remora.lsp
```

### Configure Neovim

Add to your `init.lua`:

```lua
vim.lsp.start({
    name = "remora",
    cmd = { "remora-lsp" },
    root_dir = vim.fn.getcwd(),
    filetypes = { "python" },
})
require("remora").setup()
```

**Or:** luafile demo/remora_nvim_startup.lua

### Commands

- `:RemoraChat` - Chat with agent at cursor
- `:RemoraRewrite` - Ask agent to rewrite itself  
- `:RemoraAccept` - Accept pending proposal
- `:RemoraReject` - Reject with feedback
- `:RemoraTogglePanel` - Toggle agent sidepanel
- `<leader>ra` - Toggle panel (default keybinding)

## Features

### Phase 1: LSP Foundation
- `textDocument/didOpen` and `didSave` - Parse files and register agents
- `textDocument/codeLens` - Show agent IDs inline
- `textDocument/hover` - Show agent details

### Phase 2: Proposals
- `textDocument/codeAction` - Agent tools as code actions
- `workspace/executeCommand` - Tool dispatch
- `RewriteProposal` → Diagnostic + CodeAction

### Phase 3: Agent Execution
- Agent hydration from DB
- vLLM integration (mock for demo)
- `rewrite_self` tool implementation
- Activation chain + cycle detection

### Phase 4: Communication
- `message_node` tool
- Inter-agent triggering
- Graph lazy loading

### Phase 5: Extensions
- `.remora/models/` discovery
- Custom tools in code actions

## ID Format

Agent IDs follow the format: `rm_a1b2c3d4`
- Prefix: `rm_` (8 chars total)
- Body: 8 lowercase alphanumeric characters

IDs are injected as comments at end of definition lines:
```python
def my_function():  # rm_a1b2c3d4
    ...
```

## Custom Notifications

The server uses custom LSP notifications:
- `$/remora/event` - Real-time event stream
- `$/remora/requestInput` - Request user input
- `$/remora/agentSelected` - Agent selection notification
- `$/remora/submitInput` - User input submission
