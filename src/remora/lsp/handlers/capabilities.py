from __future__ import annotations
import logging

from lsprotocol import types as lsp

from remora.lsp.protocols import LspServer

logger = logging.getLogger("remora.lsp")

async def on_initialize(ls: LspServer, params: lsp.InitializeParams) -> None:
    """Log successful initialization.

    Command capabilities are registered automatically by pygls 2.x via the
    ``@server.command()`` decorator in the commands module — no manual
    ``execute_command_provider`` setup needed.
    """
    logger.info("Client connected (initialize received)")

def register_capability_handlers(server: LspServer) -> None:
    server.feature(lsp.INITIALIZE)(on_initialize)
