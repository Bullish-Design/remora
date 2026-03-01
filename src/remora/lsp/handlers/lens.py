from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.models import ASTAgentNode
from remora.lsp.server import logger, server


@server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
async def code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
    try:
        uri = params.text_document.uri
        nodes = await server.db.get_nodes_for_file(uri)

        return [ASTAgentNode(**n).to_code_lens() for n in nodes]
    except Exception:
        logger.exception("Error in code_lens handler")
        return []


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
async def document_symbol(params: lsp.DocumentSymbolParams) -> list[lsp.DocumentSymbol]:
    try:
        uri = params.text_document.uri
        nodes = await server.db.get_nodes_for_file(uri)

        symbols = []
        for n in nodes:
            agent = ASTAgentNode(**n)
            symbol_kind = {
                "function": lsp.SymbolKind.Function,
                "class": lsp.SymbolKind.Class,
                "method": lsp.SymbolKind.Method,
                "file": lsp.SymbolKind.File,
            }.get(agent.node_type, lsp.SymbolKind.Variable)

            symbols.append(
                lsp.DocumentSymbol(
                    name=f"{agent.name} [{agent.remora_id}]",
                    kind=symbol_kind,
                    range=agent.to_range(),
                    selection_range=agent.to_range(),
                    detail=f"Status: {agent.status}",
                )
            )

        return symbols
    except Exception:
        logger.exception("Error in document_symbol handler")
        return []
