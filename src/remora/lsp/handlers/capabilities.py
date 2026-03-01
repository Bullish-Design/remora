from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.server import logger, server


@server.feature(lsp.INITIALIZE)
async def on_initialize(params: lsp.InitializeParams) -> None:
    """Log successful initialization.

    Command capabilities are registered automatically by pygls 2.x via the
    ``@server.command()`` decorator in the commands module — no manual
    ``execute_command_provider`` setup needed.
    """
    logger.info("Client connected (initialize received)")
