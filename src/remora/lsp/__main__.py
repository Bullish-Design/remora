# src/remora/lsp/__main__.py
from __future__ import annotations

import asyncio

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

    @server.thread()
    async def _start_runner() -> None:
        await runner.run_forever()

    server.start_io()


if __name__ == "__main__":
    main()
