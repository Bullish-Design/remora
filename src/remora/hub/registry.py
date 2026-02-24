"""Workspace registry - tracks agent -> workspace mappings.

This is a copy of the registry for the Hub to avoid stario dependencies.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.workspace import GraphWorkspace


@dataclass
class WorkspaceInfo:
    """Info about a workspace used by an agent."""

    workspace_id: str
    workspace: "GraphWorkspace | None" = None
    created_at: float = field(default_factory=lambda: __import__("time").time())


class WorkspaceRegistry:
    """Maps agent_ids to their workspaces."""

    def __init__(self) -> None:
        self._agent_workspace: dict[str, WorkspaceInfo] = {}

    async def register(self, agent_id: str, workspace_id: str, workspace: "GraphWorkspace") -> None:
        """Register a workspace for an agent."""
        self._agent_workspace[agent_id] = WorkspaceInfo(
            workspace_id=workspace_id,
            workspace=workspace,
        )

    def get(self, agent_id: str) -> WorkspaceInfo | None:
        """Get workspace info for an agent."""
        return self._agent_workspace.get(agent_id)

    def get_workspace(self, agent_id: str) -> "GraphWorkspace | None":
        """Get the actual workspace for an agent."""
        info = self._agent_workspace.get(agent_id)
        return info.workspace if info else None

    def unregister(self, agent_id: str) -> None:
        """Remove agent's workspace mapping."""
        self._agent_workspace.pop(agent_id, None)

    def list_agents(self) -> list[str]:
        """List all registered agent IDs."""
        return list(self._agent_workspace.keys())


workspace_registry = WorkspaceRegistry()
