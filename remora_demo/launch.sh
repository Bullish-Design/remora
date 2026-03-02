#!/usr/bin/env bash
# launch.sh — Start the Remora demo graph viewer.
#
# Usage:
#   ./remora_demo/launch.sh                        # defaults
#   ./remora_demo/launch.sh --port 8420 --db .remora/indexer.db
#
# This script starts the graph viewer web server.
# The Neovim LSP server is started separately by opening a file in
# the demo project with Neovim (which auto-starts the LSP).
#
# Requires Python 3.14 with Stario installed (use the web/ devenv).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "Starting Remora Graph Viewer..."
echo "  Project root: $PROJECT_ROOT"
echo ""

python -m remora_demo.web.graph "$@"
