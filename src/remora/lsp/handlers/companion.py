"""Companion LSP command handlers."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.lsp.protocols import LspServer

logger = logging.getLogger("remora.lsp.companion")


def _first_arg(args: tuple) -> dict:
    if not args:
        return {}
    first = args[0]
    if isinstance(first, list):
        if not first:
            return {}
        first = first[0]
    return first if isinstance(first, dict) else {}


def register_companion_handlers(server: "LspServer") -> None:
    """Register all companion workspace/executeCommand handlers."""

    @server.command("companion.getSidebar")
    async def cmd_get_sidebar(ls, *args) -> dict:
        registry = getattr(ls, "companion_registry", None)
        router = getattr(ls, "companion_router", None)
        if not registry or not router:
            return {"markdown": "", "node_id": ""}
        node_id = router.active_node_id
        if not node_id:
            return {"markdown": "*No node focused.*", "node_id": ""}
        agent = registry.get(node_id)
        if not agent:
            return {"markdown": "*Node not loaded.*", "node_id": node_id}
        from remora.companion.sidebar.composer import compose_sidebar

        markdown = await compose_sidebar(agent.node, agent.workspace)
        return {"markdown": markdown, "node_id": node_id}

    @server.command("companion.sendMessage")
    async def cmd_send_message(ls, *args) -> dict:
        registry = getattr(ls, "companion_registry", None)
        if not registry:
            return {"error": "companion not available"}
        params = _first_arg(args)
        node_id = params.get("node_id") or ""
        content = params.get("content") or ""
        if not node_id or not content:
            return {"error": "node_id and content are required"}
        agent = registry.get(node_id)
        if not agent:
            return {"error": f"agent not loaded for {node_id}"}
        try:
            response = await agent.send(content)
            return {
                "message": {"role": "assistant", "content": response.message.content},
                "turn_count": response.turn_count,
                "node_id": node_id,
            }
        except Exception:
            logger.exception("companion.sendMessage failed for %s", node_id)
            return {"error": "agent error"}

    @server.command("companion.writeNote")
    async def cmd_write_note(ls, *args) -> dict:
        registry = getattr(ls, "companion_registry", None)
        if not registry:
            return {"ok": False}
        params = _first_arg(args)
        node_id = params.get("node_id") or ""
        note = params.get("note") or ""
        if not node_id or not note:
            return {"ok": False}
        agent = registry.get(node_id)
        if not agent:
            return {"ok": False, "error": "agent not loaded"}
        import time

        from remora.companion.node_workspace import USER_NOTES, append_text

        timestamped = f"\n- *{time.strftime('%Y-%m-%d')}*: {note}\n"
        await append_text(agent.workspace, USER_NOTES, timestamped)
        return {"ok": True}

    @server.command("companion.getLinks")
    async def cmd_get_links(ls, *args) -> dict:
        registry = getattr(ls, "companion_registry", None)
        if not registry:
            return {"links": []}
        params = _first_arg(args)
        node_id = params.get("node_id") or ""
        agent = registry.get(node_id)
        if not agent:
            return {"links": []}
        from remora.companion.links.resolver import LinksResolver

        links = await LinksResolver().get_links(agent.node, agent.workspace)
        return {
            "links": [
                {
                    "target_node_id": link.target_node_id,
                    "relationship": link.relationship,
                    "confidence": link.confidence,
                    "note": link.note,
                }
                for link in links
            ]
        }

    @server.command("companion.listHistory")
    async def cmd_list_history(ls, *args) -> dict:
        registry = getattr(ls, "companion_registry", None)
        if not registry:
            return {"history": []}
        params = _first_arg(args)
        node_id = params.get("node_id") or ""
        agent = registry.get(node_id)
        if not agent:
            return {"history": []}
        from remora.companion.node_workspace import load_chat_index

        index = await load_chat_index(agent.workspace)
        return {"history": [entry.to_dict() for entry in sorted(index, key=lambda e: e.timestamp, reverse=True)]}

    @server.command("companion.getHistory")
    async def cmd_get_history(ls, *args) -> dict:
        registry = getattr(ls, "companion_registry", None)
        if not registry:
            return {"markdown": ""}
        params = _first_arg(args)
        node_id = params.get("node_id") or ""
        session_id = params.get("session_id") or ""
        agent = registry.get(node_id)
        if not agent:
            return {"markdown": ""}
        from remora.companion.node_workspace import read_text

        transcript = await read_text(agent.workspace, f"chat/{session_id}.md")
        return {"markdown": transcript}
