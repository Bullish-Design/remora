"""Workspace registry - tracks agent -> workspace mappings."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkspaceInfo:
    """Info about a workspace used by an agent."""

    workspace_id: str
    workspace: Any
    created_at: float = field(default_factory=lambda: __import__("time").time())


class WorkspaceRegistry:
    """Maps agent_ids to their workspaces."""

    def __init__(self) -> None:
        self._agent_workspace: dict[str, WorkspaceInfo] = {}

    async def register(self, agent_id: str, workspace_id: str, workspace: Any) -> None:
        """Register a workspace for an agent."""
        self._agent_workspace[agent_id] = WorkspaceInfo(
            workspace_id=workspace_id,
            workspace=workspace,
        )

    def get(self, agent_id: str) -> WorkspaceInfo | None:
        """Get workspace info for an agent."""
        return self._agent_workspace.get(agent_id)

    def get_workspace(self, agent_id: str) -> Any:
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
