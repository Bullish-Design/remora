#!/bin/bash
# Remora Neovim V2.1 Quick Start Script
# Run this from the remora project root

set -e

echo "=== Remora Neovim V2.1 Quick Start ==="
echo ""

# Check Python
if ! command -v python &> /dev/null; then
    echo "Error: Python not found"
    exit 1
fi

# Check dependencies
echo "Checking dependencies..."

if python -c "import pygls" 2>/dev/null; then
    echo "  [OK] pygls"
else
    echo "  [WARN] pygls not installed (pip install pygls)"
fi

if python -c "import lsprotocol" 2>/dev/null; then
    echo "  [OK] lsprotocol"
else
    echo "  [WARN] lsprotocol not installed (pip install lsprotocol)"
fi

if python -c "import tree_sitter" 2>/dev/null; then
    echo "  [OK] tree-sitter"
else
    echo "  [WARN] tree-sitter not installed (pip install tree-sitter)"
fi

echo ""

# Start LSP server in background
echo "Starting Remora LSP server..."
python -m demo.lsp.server &
LSP_PID=$!

echo "LSP server started (PID: $LSP_PID)"
echo ""

# Instructions for Neovim
echo "=== To use in Neovim ==="
echo ""
echo "Option 1: Vim script (quick)"
echo "  :source demo/nvim/remora.vim"
echo "  :RemoraSetup"
echo "  :RemoraStart"
echo ""
echo "Option 2: Lua (recommended)"
echo "  In your init.lua, add:"
echo "    -- Set up demo path"
echo '    vim.opt.runtimepath:append("/path/to/remora/demo/nvim/lua")'
echo '    require("remora_starter")'
echo ""
echo "Option 3: Manual"
echo "  :lua require('remora').setup()"
echo ""
echo "=== Commands ==="
echo "  :RemoraStart     - Start LSP server"
echo "  :RemoraStop      - Stop LSP server"  
echo "  :RemoraRestart   - Restart LSP"
echo "  :RemoraTogglePanel - Toggle agent panel"
echo "  :RemoraChat      - Chat with agent"
echo "  :RemoraRewrite   - Request rewrite from agent"
echo "  :RemoraAccept    - Accept pending proposal"
echo "  :RemoraReject    - Reject with feedback"
echo "  :RemoraParse     - Re-parse current file"
echo "  :RemoraStatus    - Show LSP status"
echo ""

# Cleanup on exit
trap "kill $LSP_PID 2>/dev/null" EXIT
