from __future__ import annotations
import logging

from lsprotocol import types as lsp

from remora.lsp.server import RemoraLanguageServer

logger = logging.getLogger("remora.lsp")

async def code_lens(ls: RemoraLanguageServer, params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
    try:
        uri = params.text_document.uri
        if not ls.event_store:
            return []

        agents = await ls.event_store.list_nodes(file_path=uri)
        return [agent.to_code_lens() for agent in agents]
    except Exception:
        logger.exception("Error in code_lens handler")
        return []

async def document_symbol(ls: RemoraLanguageServer, params: lsp.DocumentSymbolParams) -> list[lsp.DocumentSymbol]:
    try:
        uri = params.text_document.uri
        if not ls.event_store:
            return []

        agents = await ls.event_store.list_nodes(file_path=uri)
        return [agent.to_document_symbol() for agent in agents]
    except Exception:
        logger.exception("Error in document_symbol handler")
        return []

def register_lens_handlers(server: RemoraLanguageServer) -> None:
    server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)(code_lens)
    server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)(document_symbol)
