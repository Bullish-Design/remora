#!/usr/bin/env bash
# Remora sandbox entrypoint
# Runs commands in /workspace as the sandbox user.
#
# Usage:
#   docker run remora-sandbox:latest python -c "print('hello')"
#   docker run remora-sandbox:latest pytest -q
#   docker run remora-sandbox:latest bash     (interactive)

set -euo pipefail

# Ensure user-installed tools are on PATH
export PATH="/home/sandbox/.local/bin:$PATH"

# Run the command in /workspace
cd /workspace
exec "$@"
