from __future__ import annotations
import logging

from lsprotocol import types as lsp

from remora.lsp.protocols import LspServer

logger = logging.getLogger("remora.lsp")

async def hover(ls: LspServer, params: lsp.HoverParams) -> lsp.Hover | None:
    try:
        uri = params.text_document.uri
        pos = params.position
        if not ls.event_store:
            return None

        agent = await ls.event_store.nodes.get_node_at_position(uri, pos.line + 1)
        if not agent:
            return None

        events = await ls.event_store.get_recent_events(agent.node_id, limit=5)
        return agent.to_hover(events)
    except Exception:
        logger.exception("Error in hover handler")
        return None

def register_hover_handlers(server: LspServer) -> None:
    server.feature(lsp.TEXT_DOCUMENT_HOVER)(hover)
