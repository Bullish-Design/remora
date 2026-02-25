#!/usr/bin/env python3
"""start_server.py - Runs the Remora Hub standalone server."""

import asyncio
import logging
from pathlib import Path
from remora.hub.server import run_hub

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

if __name__ == "__main__":
    print("🟢 Starting Remora Hub Server on http://0.0.0.0:8001")
    asyncio.run(
        run_hub(
            workspace_path=Path("demo_workspaces/global.workspace"),
            host="0.0.0.0",
            port=8001,
            workspace_base=Path("demo_workspaces"),
        )
    )
