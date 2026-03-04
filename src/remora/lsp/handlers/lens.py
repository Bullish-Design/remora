from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.server import logger, server


@server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
async def code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
    try:
        uri = params.text_document.uri
        if not server.event_store:
            return []

        agents = await server.event_store.list_nodes(file_path=uri)
        return [agent.to_code_lens() for agent in agents]
    except Exception:
        logger.exception("Error in code_lens handler")
        return []


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
async def document_symbol(params: lsp.DocumentSymbolParams) -> list[lsp.DocumentSymbol]:
    try:
        uri = params.text_document.uri
        if not server.event_store:
            return []

        agents = await server.event_store.list_nodes(file_path=uri)
        return [agent.to_document_symbol() for agent in agents]
    except Exception:
        logger.exception("Error in document_symbol handler")
        return []
