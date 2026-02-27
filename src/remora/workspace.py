"""Cairn workspace integration.

Provides thin wrappers around Cairn for agent workspace management.
Replaces WorkspaceKV, GraphWorkspace, and WorkspaceManager with
direct Cairn usage.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from cairn import Workspace as CairnWorkspace

from remora.config import WorkspaceConfig
from remora.discovery import CSTNode
from remora.errors import WorkspaceError

logger = logging.getLogger(__name__)


class AgentWorkspace:
    """Workspace for a single agent execution.

    Wraps a Cairn workspace with agent-specific convenience methods.
    """

    def __init__(self, workspace: CairnWorkspace, agent_id: str):
        self._workspace = workspace
        self._agent_id = agent_id

    @property
    def cairn(self) -> CairnWorkspace:
        """Access underlying Cairn workspace."""
        return self._workspace

    async def read(self, path: str) -> str:
        """Read a file from the workspace."""
        return await self._workspace.read(path)

    async def write(self, path: str, content: str) -> None:
        """Write a file to the workspace (CoW isolated)."""
        await self._workspace.write(path, content)

    async def exists(self, path: str) -> bool:
        """Check if a file exists in the workspace."""
        return await self._workspace.exists(path)

    async def accept(self) -> None:
        """Accept all changes in this workspace."""
        await self._workspace.accept()

    async def reject(self) -> None:
        """Reject all changes and reset to base state."""
        await self._workspace.reject()

    async def snapshot(self, name: str) -> str:
        """Create a named snapshot of current state."""
        return await self._workspace.snapshot(name)

    async def restore(self, snapshot_id: str) -> None:
        """Restore from a named snapshot."""
        await self._workspace.restore(snapshot_id)


class WorkspaceManager:
    """Manages Cairn workspaces for graph execution.

    Creates isolated workspaces per agent with CoW semantics.
    """

    def __init__(self, config: WorkspaceConfig, graph_id: str):
        self._config = config
        self._graph_id = graph_id
        self._base_path = Path(config.base_path) / graph_id
        self._workspaces: dict[str, AgentWorkspace] = {}

    async def get_workspace(self, agent_id: str) -> AgentWorkspace:
        """Get or create a workspace for an agent."""
        if agent_id in self._workspaces:
            return self._workspaces[agent_id]

        workspace_path = self._base_path / agent_id
        workspace_path.mkdir(parents=True, exist_ok=True)

        try:
            cairn_ws = await CairnWorkspace.create(workspace_path)
        except Exception as e:
            raise WorkspaceError(f"Failed to create workspace for {agent_id}: {e}")

        agent_ws = AgentWorkspace(cairn_ws, agent_id)
        self._workspaces[agent_id] = agent_ws
        return agent_ws

    async def cleanup(self) -> None:
        """Clean up all workspaces."""
        for workspace in self._workspaces.values():
            try:
                await workspace.cairn.close()
            except Exception as e:
                logger.warning("Workspace cleanup error: %s", e)
        self._workspaces.clear()


class CairnDataProvider:
    """Populates Grail virtual FS from a Cairn workspace.

    Implements the DataProvider pattern for structured-agents v0.3.
    """

    def __init__(self, workspace: AgentWorkspace):
        self._workspace = workspace

    async def load_files(self, node: CSTNode, related: list[str] | None = None) -> dict[str, str]:
        """Load target file and related files for Grail execution."""
        files: dict[str, str] = {}

        try:
            files[node.file_path] = await self._workspace.read(node.file_path)
        except Exception as e:
            logger.warning("Could not load target file %s: %s", node.file_path, e)

        if related:
            for path in related:
                try:
                    if await self._workspace.exists(path):
                        files[path] = await self._workspace.read(path)
                except Exception as e:
                    logger.debug("Could not load related file %s: %s", path, e)

        return files


class CairnResultHandler:
    """Persists script results back to Cairn workspace."""

    def __init__(self, workspace: AgentWorkspace):
        self._workspace = workspace

    async def handle(self, result: dict[str, Any]) -> None:
        """Write result data back to workspace."""
        if "written_files" in result:
            for path, content in result["written_files"].items():
                await self._workspace.write(path, content)

        if "modified_file" in result:
            path, content = result["modified_file"]
            await self._workspace.write(path, content)


__all__ = [
    "AgentWorkspace",
    "WorkspaceManager",
    "CairnDataProvider",
    "CairnResultHandler",
]
