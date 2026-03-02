from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.server import logger, server


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
    try:
        uri = params.text_document.uri
        pos = params.position
        if not server.event_store:
            return None

        agent = await server.event_store.get_node_at_position(uri, pos.line + 1)
        if not agent:
            return None

        events = await server.db.get_recent_events(agent.node_id, limit=5)
        return agent.to_hover(events)
    except Exception:
        logger.exception("Error in hover handler")
        return None
