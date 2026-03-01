#!/bin/bash
# Start the Remora LSP server (Linux/macOS)

echo "=== Remora LSP Server ==="

# Check Python
if ! command -v python &> /dev/null; then
    echo "Error: Python not found"
    exit 1
fi

# Check dependencies
for dep in pygls lsprotocol tree_sitter; do
    if python -c "import $dep" 2>/dev/null; then
        echo "  [OK] $dep"
    else
        echo "  [WARN] $dep not installed"
    fi
done

# Start server
echo ""
echo "Starting Remora LSP server..."
python -m remora.lsp
