"""Cairn workspace bridge for Remora.

Provides stable and per-agent workspaces using Cairn runtime APIs.
Remora does not import fsdantic directly; all workspace access flows
through Cairn.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from cairn.runtime import workspace_manager as cairn_workspace_manager

from remora.config import WorkspaceConfig
from remora.cairn_externals import CairnExternals
from remora.errors import WorkspaceError
from remora.workspace import AgentWorkspace
from remora.utils import PathResolver

logger = logging.getLogger(__name__)

_IGNORE_DIRS = {
    ".agentfs",
    ".git",
    ".jj",
    ".mypy_cache",
    ".pytest_cache",
    ".remora",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


class CairnWorkspaceService:
    """Manage stable and agent workspaces via Cairn."""

    def __init__(
        self,
        config: WorkspaceConfig,
        graph_id: str,
        project_root: Path | str | None = None,
    ) -> None:
        self._config = config
        self._graph_id = graph_id
        self._project_root = Path(project_root or Path.cwd()).resolve()
        self._resolver = PathResolver(self._project_root)
        self._base_path = Path(config.base_path) / graph_id
        self._manager = cairn_workspace_manager.WorkspaceManager()
        self._stable_workspace: Any | None = None
        self._agent_workspaces: dict[str, AgentWorkspace] = {}

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def resolver(self) -> PathResolver:
        return self._resolver

    async def initialize(self, *, sync: bool = True) -> None:
        """Initialize stable workspace and optionally sync project files."""
        if self._stable_workspace is not None:
            return

        self._base_path.mkdir(parents=True, exist_ok=True)
        stable_path = self._base_path / "stable.db"

        try:
            self._stable_workspace = await cairn_workspace_manager._open_workspace(
                stable_path,
                readonly=False,
            )
            self._manager.track_workspace(self._stable_workspace)
        except Exception as exc:
            raise WorkspaceError(f"Failed to create stable workspace: {exc}") from exc

        if sync:
            await self._sync_project_to_workspace()

    async def get_agent_workspace(self, agent_id: str) -> AgentWorkspace:
        """Get or create an agent workspace."""
        if agent_id in self._agent_workspaces:
            return self._agent_workspaces[agent_id]

        if self._stable_workspace is None:
            raise WorkspaceError("CairnWorkspaceService is not initialized")

        workspace_path = self._base_path / f"{agent_id}.db"
        workspace_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            workspace = await cairn_workspace_manager._open_workspace(
                workspace_path,
                readonly=False,
            )
            self._manager.track_workspace(workspace)
        except Exception as exc:
            raise WorkspaceError(f"Failed to create workspace for {agent_id}: {exc}") from exc

        agent_workspace = AgentWorkspace(workspace, agent_id, stable_workspace=self._stable_workspace)
        self._agent_workspaces[agent_id] = agent_workspace
        return agent_workspace

    def get_externals(self, agent_id: str, agent_workspace: AgentWorkspace) -> dict[str, Any]:
        """Build Cairn external helpers for Grail tools."""
        if self._stable_workspace is None:
            raise WorkspaceError("CairnWorkspaceService is not initialized")

        externals = CairnExternals(
            agent_id=agent_id,
            agent_fs=agent_workspace.cairn,
            stable_fs=self._stable_workspace,
            resolver=self._resolver,
        )
        return externals.as_externals()

    async def close(self) -> None:
        """Close all tracked workspaces."""
        await self._manager.close_all()
        self._agent_workspaces.clear()
        self._stable_workspace = None

    async def _sync_project_to_workspace(self) -> None:
        """Sync project files into the stable workspace."""
        if self._stable_workspace is None:
            return

        for path in self._project_root.rglob("*"):
            if path.is_dir():
                continue
            if _should_ignore(path, self._project_root):
                continue

            if not self._resolver.is_within_project(path):
                continue
            rel_path = self._resolver.to_workspace_path(path)

            try:
                payload = path.read_bytes()
            except OSError as exc:
                logger.debug("Failed to read %s: %s", path, exc)
                continue

            try:
                await self._stable_workspace.files.write(rel_path, payload, mode="binary")
            except Exception as exc:
                logger.debug("Failed to write %s to stable workspace: %s", rel_path, exc)


def _should_ignore(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return True

    for part in rel_parts:
        if part in _IGNORE_DIRS:
            return True
        if part.startswith("."):
            return True
    return False


__all__ = ["CairnWorkspaceService"]
