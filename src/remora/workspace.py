"""Cairn workspace integration.

Provides thin wrappers around Cairn for agent workspace management.
Remora does not import fsdantic directly; workspace access flows through Cairn.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from cairn.runtime import workspace_manager as cairn_workspace_manager

from remora.config import WorkspaceConfig
from remora.discovery import CSTNode
from remora.errors import WorkspaceError
from remora.utils import PathResolver

logger = logging.getLogger(__name__)


class AgentWorkspace:
    """Workspace for a single agent execution.

    Wraps a Cairn workspace with agent-specific convenience methods.
    """

    def __init__(self, workspace: Any, agent_id: str, stable_workspace: Any | None = None):
        self._workspace = workspace
        self._agent_id = agent_id
        self._stable_workspace = stable_workspace

    @property
    def cairn(self) -> Any:
        """Access underlying Cairn workspace."""
        return self._workspace

    async def read(self, path: str) -> str:
        """Read a file from the workspace."""
        try:
            return await self._workspace.files.read(path, mode="text")
        except Exception:
            if self._stable_workspace is None:
                raise
            return await self._stable_workspace.files.read(path, mode="text")

    async def write(self, path: str, content: str | bytes) -> None:
        """Write a file to the workspace (CoW isolated)."""
        await self._workspace.files.write(path, content)

    async def exists(self, path: str) -> bool:
        """Check if a file exists in the workspace."""
        if await self._workspace.files.exists(path):
            return True
        if self._stable_workspace is None:
            return False
        return await self._stable_workspace.files.exists(path)

    async def list_dir(self, path: str = ".") -> list[str]:
        """List directory entries in the workspace."""
        entries = set(await self._workspace.files.list_dir(path, output="name"))
        if self._stable_workspace is not None:
            try:
                stable_entries = await self._stable_workspace.files.list_dir(path, output="name")
            except Exception:
                stable_entries = []
            entries.update(stable_entries)
        return sorted(entries)

    async def accept(self) -> None:
        """Accept all changes in this workspace."""
        raise WorkspaceError("Accept/reject is not supported by the Cairn workspace API")

    async def reject(self) -> None:
        """Reject all changes and reset to base state."""
        raise WorkspaceError("Accept/reject is not supported by the Cairn workspace API")

    async def snapshot(self, name: str) -> str:
        """Create a named snapshot of current state."""
        raise WorkspaceError("Snapshots are not supported by the Cairn workspace API")

    async def restore(self, snapshot_id: str) -> None:
        """Restore from a named snapshot."""
        raise WorkspaceError("Snapshots are not supported by the Cairn workspace API")


class WorkspaceManager:
    """Manages Cairn workspaces for graph execution.

    Creates isolated workspaces per agent with CoW semantics.
    """

    def __init__(self, config: WorkspaceConfig, graph_id: str):
        self._config = config
        self._graph_id = graph_id
        self._base_path = Path(config.base_path) / graph_id
        self._workspaces: dict[str, AgentWorkspace] = {}
        self._manager = cairn_workspace_manager.WorkspaceManager()

    async def get_workspace(self, agent_id: str) -> AgentWorkspace:
        """Get or create a workspace for an agent."""
        if agent_id in self._workspaces:
            return self._workspaces[agent_id]

        workspace_path = self._base_path / f"{agent_id}.db"
        workspace_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            cairn_ws = await cairn_workspace_manager._open_workspace(workspace_path, readonly=False)
            self._manager.track_workspace(cairn_ws)
        except Exception as e:
            raise WorkspaceError(f"Failed to create workspace for {agent_id}: {e}")

        agent_ws = AgentWorkspace(cairn_ws, agent_id)
        self._workspaces[agent_id] = agent_ws
        return agent_ws

    async def cleanup(self) -> None:
        """Clean up all workspaces."""
        try:
            await self._manager.close_all()
        except Exception as e:
            logger.warning("Workspace cleanup error: %s", e)
        self._workspaces.clear()


class CairnDataProvider:
    """Populates Grail virtual FS from a Cairn workspace.

    Implements the DataProvider pattern for structured-agents v0.3.
    """

    def __init__(self, workspace: AgentWorkspace, resolver: PathResolver):
        self._workspace = workspace
        self._resolver = resolver

    async def load_files(self, node: CSTNode, related: list[str] | None = None) -> dict[str, str]:
        """Load target file and related files for Grail execution."""
        files: dict[str, str] = {}
        target_path = self._resolver.to_workspace_path(node.file_path)

        try:
            content = await self._workspace.read(target_path)
            files[target_path] = content
            if node.file_path != target_path:
                files[node.file_path] = content
        except Exception as e:
            logger.warning("Could not load target file %s: %s", node.file_path, e)

        if related:
            for path in related:
                try:
                    workspace_path = self._resolver.to_workspace_path(path)
                    if await self._workspace.exists(workspace_path):
                        content = await self._workspace.read(workspace_path)
                        files[workspace_path] = content
                        if path != workspace_path:
                            files[path] = content
                except Exception as e:
                    logger.debug("Could not load related file %s: %s", path, e)

        return files


class CairnResultHandler:
    """Persists script results back to Cairn workspace."""

    def __init__(self, workspace: AgentWorkspace):
        self._workspace = workspace

    async def handle(self, result: dict[str, Any]) -> None:
        """Write result data back to workspace."""
        if "written_file" in result and "content" in result:
            await self._workspace.write(result["written_file"], result["content"])

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
