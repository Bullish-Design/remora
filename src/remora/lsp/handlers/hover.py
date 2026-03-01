from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.models import ASTAgentNode
from remora.lsp.server import logger, server


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
    try:
        uri = params.text_document.uri
        pos = params.position

        node = await server.db.get_node_at_position(uri, pos.line + 1, pos.character)
        if not node:
            return None

        agent = ASTAgentNode(**node)
        events = await server.db.get_recent_events(agent.remora_id, limit=5)

        return agent.to_hover(events)
    except Exception:
        logger.exception("Error in hover handler")
        return None
