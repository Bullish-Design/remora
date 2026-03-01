#!/usr/bin/env python3
"""
Remora Neovim V2.1 LSP-Native Demo

This is a demo implementation of the LSP-native architecture where
Remora connects to Neovim as a language server.

Usage:
    # Start the LSP server
    python -m demo.lsp.server

    # In Neovim, add to init.lua:
    -- lua/remora/init.lua
    local remora = require("remora")
    remora.setup()
"""

import asyncio
import sys

from demo.lsp.server import server
from demo.agent.runner import AgentRunner


async def main():
    runner = AgentRunner()
    server.runner = runner

    runner_task = asyncio.create_task(runner.run_forever())

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        runner.stop()
        runner_task.cancel()
        try:
            await runner_task
        except asyncio.CancelledError:
            pass

    server.db.close()


if __name__ == "__main__":
    asyncio.run(main())
