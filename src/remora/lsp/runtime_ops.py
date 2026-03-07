from __future__ import annotations

import logging

from remora.core.code.discovery import node_to_event, parse_content
from remora.core.events.code_events import NodeRemovedEvent
from remora.core.events.interaction_events import CursorFocusEvent
from remora.lsp.protocols import LspServer

logger = logging.getLogger("remora.lsp")


async def do_reparse(server: LspServer, uri: str, text: str) -> None:
    """Reparse file content, emit node lifecycle events, and refresh UI state."""
    server._reparse_timers.pop(uri, None)
    try:
        cst_nodes = parse_content(uri, text)
        logger.debug("_do_reparse: %d nodes for %s", len(cst_nodes), uri)

        if server.event_store:
            old_agents = await server.event_store.nodes.list_nodes(file_path=uri)
            new_ids = {n.node_id for n in cst_nodes}
            old_ids = {a.node_id for a in old_agents}

            for orphan_id in old_ids - new_ids:
                await server.event_store.append("nodes", NodeRemovedEvent(node_id=orphan_id))

            for node in cst_nodes:
                await server.event_store.append("nodes", node_to_event(node))

        await server.refresh_code_lenses()
        await server.notify_agents_updated()
    except Exception:
        logger.exception("Error in _do_reparse for %s", uri)


async def do_cursor_update(server: LspServer, agent_id: str | None, uri: str, line: int) -> None:
    """Persist debounced cursor state and emit CursorFocusEvent."""
    server._cursor_timers.pop(uri, None)
    try:
        await server.db.update_cursor_focus(agent_id, uri, line)
        if server.event_store:
            event = CursorFocusEvent(focused_agent_id=agent_id, file_path=uri, line=line)
            await server.event_store.append("cursor", event)
    except Exception:
        logger.debug("Error in _do_cursor_update", exc_info=True)


__all__ = ["do_reparse", "do_cursor_update"]
