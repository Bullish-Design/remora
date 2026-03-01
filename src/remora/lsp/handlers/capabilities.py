from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.server import logger, server


@server.feature(lsp.INITIALIZE)
async def on_initialize(params: lsp.InitializeParams) -> None:
    try:
        server.server_capabilities.execute_command_provider = lsp.ExecuteCommandOptions(
            commands=[
                "remora.chat",
                "remora.requestRewrite",
                "remora.executeTool",
                "remora.acceptProposal",
                "remora.rejectProposal",
                "remora.selectAgent",
                "remora.messageNode",
            ]
        )
    except Exception:
        logger.exception("Error setting server capabilities")
