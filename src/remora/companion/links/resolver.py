"""LinksResolver - aggregates cross-node links for sidebar display."""
from __future__ import annotations

from typing import TYPE_CHECKING

from remora.companion.links.types import NodeLink
from remora.companion.node_workspace import LINKS, read_json

if TYPE_CHECKING:
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.workspace import AgentWorkspace


class LinksResolver:
    """Resolves links for a single node from workspace + AgentNode graph data."""

    async def get_links(self, node: "AgentNode", workspace: "AgentWorkspace") -> list[NodeLink]:
        links: list[NodeLink] = []
        for callee_id in node.callee_ids:
            links.append(NodeLink.from_agent_node(node.node_id, callee_id, "calls"))
        for caller_id in node.caller_ids:
            links.append(NodeLink.from_agent_node(node.node_id, caller_id, "called_by"))

        raw = await read_json(workspace, LINKS) or []
        for entry in raw:
            try:
                links.append(NodeLink.from_dict(node.node_id, entry))
            except (KeyError, TypeError):
                continue

        seen: set[tuple[str, str]] = set()
        deduped: list[NodeLink] = []
        for link in links:
            key = (link.target_node_id, link.relationship)
            if key not in seen:
                seen.add(key)
                deduped.append(link)
        return deduped


__all__ = ["LinksResolver"]
