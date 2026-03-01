# src/remora/lsp/__main__.py
from __future__ import annotations

import asyncio

from lsprotocol import types as lsp

from remora.lsp.server import server
from remora.lsp.runner import AgentRunner


def main(
    event_store=None,
    subscriptions=None,
    swarm_state=None,
) -> None:
    """Start the Remora LSP server with agent runner."""
    server.event_store = event_store
    server.subscriptions = subscriptions
    server.swarm_state = swarm_state
    runner = AgentRunner(server=server)
    server.runner = runner

    @server.feature(lsp.INITIALIZED)
    async def _on_initialized(params: lsp.InitializedParams) -> None:
        asyncio.ensure_future(runner.run_forever())

    server.start_io()


if __name__ == "__main__":
    main()
