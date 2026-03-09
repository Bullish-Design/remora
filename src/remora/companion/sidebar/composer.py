"""NodeAgentSidebarComposer - renders a node's workspace as sidebar markdown."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from remora.companion.links.resolver import LinksResolver
from remora.companion.node_workspace import AGENT_NOTES, USER_NOTES, load_chat_index, read_text
from remora.companion.sidebar.workspace import build_workspace_panels

if TYPE_CHECKING:
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.workspace import AgentWorkspace

_resolver = LinksResolver()


async def compose_sidebar(node: AgentNode, workspace: AgentWorkspace) -> str:
    """Compose the full sidebar markdown for a node agent."""
    lines: list[str] = []
    lines.append(f"# {node.name}")
    lines.append(f"`{node.node_type}` - `{node.file_path}:{node.start_line}`")
    lines.append("")

    user_notes = await read_text(workspace, USER_NOTES)
    if user_notes.strip():
        lines.append("## Notes")
        lines.append(user_notes.strip())
        lines.append("")

    agent_notes = await read_text(workspace, AGENT_NOTES)
    if agent_notes.strip():
        lines.append("## Agent Observations")
        lines.append(agent_notes.strip())
        lines.append("")

    workspace_panels = await build_workspace_panels(workspace)
    if any(not panel.is_empty for panel in workspace_panels):
        lines.append("## Workspace")
        for panel in workspace_panels:
            lines.append(f"### {panel.title}")
            if panel.is_empty:
                lines.append("_empty_")
            else:
                lines.append(panel.content.strip())
            lines.append("")

    index = await load_chat_index(workspace)
    if index:
        recent = sorted(index, key=lambda entry: entry.timestamp, reverse=True)[:5]
        lines.append("## Recent Conversations")
        for entry in recent:
            ts = time.strftime("%Y-%m-%d", time.localtime(entry.timestamp))
            tag_str = f" `{'` `'.join(entry.tags)}`" if entry.tags else ""
            lines.append(f"- **{ts}**{tag_str}: {entry.summary}")
        lines.append("")

    links = await _resolver.get_links(node, workspace)
    if links:
        lines.append("## Connections")
        for link in links[:8]:
            lines.append(f"- `{link.target_node_id}` ({link.relationship})")
            if link.note and link.note != "graph-derived":
                lines.append(f"  *{link.note}*")
        lines.append("")

    if not user_notes.strip() and not agent_notes.strip() and not index and not links:
        lines.append("*First visit. Start a conversation below.*")

    return "\n".join(lines)


__all__ = ["compose_sidebar"]
