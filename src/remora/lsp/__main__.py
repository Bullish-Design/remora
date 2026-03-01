# src/remora/lsp/__main__.py
from __future__ import annotations

import asyncio
import logging
import sys
import time

from lsprotocol import types as lsp


def _setup_logging() -> logging.Logger:
    """Configure logging to stderr (stdout is reserved for LSP protocol)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger("remora")
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    # Quiet down pygls internals unless needed
    logging.getLogger("pygls").setLevel(logging.WARNING)

    return logging.getLogger("remora.lsp.startup")


def main(
    event_store=None,
    subscriptions=None,
    swarm_state=None,
) -> None:
    """Start the Remora LSP server with agent runner."""
    t0 = time.monotonic()
    log = _setup_logging()
    log.info("remora-lsp starting (pid=%d)", __import__("os").getpid())

    log.debug("Importing remora.lsp.server ...")
    from remora.lsp.server import server

    log.debug("Server module loaded (handlers registered) in %.1fms", (time.monotonic() - t0) * 1000)

    log.debug("Importing remora.lsp.runner ...")
    from remora.lsp.runner import AgentRunner

    log.debug("Runner module loaded in %.1fms", (time.monotonic() - t0) * 1000)

    server.event_store = event_store
    server.subscriptions = subscriptions
    server.swarm_state = swarm_state

    log.debug("Creating AgentRunner ...")
    runner = AgentRunner(server=server)
    server.runner = runner
    log.debug("AgentRunner created")

    @server.feature(lsp.INITIALIZED)
    async def _on_initialized(params: lsp.InitializedParams) -> None:
        log.info(
            "Client initialized — starting agent runner loop (startup took %.0fms)",
            (time.monotonic() - t0) * 1000,
        )
        asyncio.ensure_future(runner.run_forever())

    log.info("Starting IO transport (waiting for client on stdin) ...")
    try:
        server.start_io()
    except Exception:
        log.exception("Fatal error in server.start_io()")
        raise
    finally:
        log.info("remora-lsp shutting down")


if __name__ == "__main__":
    main()
