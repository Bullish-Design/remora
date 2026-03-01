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

## File Structure

```
demo/
├── __main__.py           # Entry: python -m demo
├── __init__.py
├── lsp/
│   ├── __init__.py
│   └── server.py         # RemoraLanguageServer (pygls)
├── core/
│   ├── __init__.py
│   ├── models.py         # ASTAgentNode, RewriteProposal, events
│   ├── db.py             # SQLite operations
│   ├── graph.py          # Rustworkx lazy graph
│   └── watcher.py        # Tree-sitter parsing + ID injection
├── agent/
│   ├── __init__.py
│   └── runner.py         # AgentRunner execution loop
└── nvim/
    └── lua/
        └── remora/
            ├── __init__.lua   # Setup + handlers
            └── panel.lua      # Sidepanel UI
```

## Quick Start

### 1. Install Dependencies

The demo requires:
- `pygls` - Python LSP framework
- `lsprotocol` - LSP protocol types
- `tree-sitter` + `tree-sitter-python` - For AST parsing

### 2. Start the LSP Server

```bash
python -m demo.lsp.server
```

Or with the agent runner:
```bash
python -m demo
```

### 3. Configure Neovim

Add to your `init.lua`:

```lua
-- Add demo to Lua path
package.path = package.path .. ";./demo/nvim/lua/?.lua"

local remora = require("remora")
remora.setup({
    -- options
})
```

### 4. Commands

- `:RemoraChat` - Chat with agent at cursor
- `:RemoraRewrite` - Ask agent to rewrite itself  
- `:RemoraAccept` - Accept pending proposal
- `:RemoraReject` - Reject with feedback
- `:RemoraTogglePanel` - Toggle agent sidepanel

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
