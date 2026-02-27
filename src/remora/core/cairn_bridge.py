"""Cairn workspace bridge for Remora.

Provides stable and per-agent workspaces using Cairn runtime APIs.
Remora does not import fsdantic directly; all workspace access flows
through Cairn.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from pathlib import Path
from typing import Any

from cairn.runtime import workspace_manager as cairn_workspace_manager

from remora.core.config import WorkspaceConfig
from remora.core.streaming_sync import FileWatcher, StreamingSyncManager, SyncStats
from remora.core.cairn_externals import CairnExternals
from remora.core.errors import WorkspaceError
from remora.core.workspace import AgentWorkspace
from remora.utils import PathLike, PathResolver, normalize_path

logger = logging.getLogger(__name__)


class SyncMode(str, Enum):
    """Workspace synchronization modes."""

    FULL = "full"
    LAZY = "lazy"
    NONE = "none"


class CairnWorkspaceService:
    """Manage stable and agent workspaces via Cairn."""

    def __init__(
        self,
        config: WorkspaceConfig,
        graph_id: str,
        project_root: PathLike | None = None,
    ) -> None:
        self._config = config
        self._graph_id = graph_id
        self._project_root = normalize_path(project_root or Path.cwd()).resolve()
        self._resolver = PathResolver(self._project_root)
        self._base_path = normalize_path(config.base_path) / graph_id
        self._manager = cairn_workspace_manager.WorkspaceManager()
        self._stable_workspace: Any | None = None
        self._agent_workspaces: dict[str, AgentWorkspace] = {}
        self._stable_lock = asyncio.Lock()
        self._sync_mode: SyncMode = SyncMode.FULL
        self._ignore_patterns: set[str] = set(config.ignore_patterns or ())
        self._ignore_dotfiles: bool = config.ignore_dotfiles
        self._streaming_sync: StreamingSyncManager | None = None
        self._file_watcher: FileWatcher | None = None

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def resolver(self) -> PathResolver:
        return self._resolver

    async def initialize(
        self,
        *,
        sync_mode: SyncMode = SyncMode.FULL,
        watch_changes: bool = False,
    ) -> None:
        """Initialize stable workspace with configurable sync mode."""
        if self._stable_workspace is not None:
            return

        self._sync_mode = sync_mode
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

        if sync_mode == SyncMode.FULL:
            await self._sync_project_to_workspace()
        elif sync_mode == SyncMode.LAZY:
            self._streaming_sync = StreamingSyncManager(
                project_root=self._project_root,
                workspace=self._stable_workspace,
                ignore_checker=self._should_ignore,
            )

        if watch_changes and self._streaming_sync:
            self._file_watcher = FileWatcher(self._streaming_sync)
            await self._file_watcher.start()

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

        agent_workspace = AgentWorkspace(
            workspace,
            agent_id,
            stable_workspace=self._stable_workspace,
            ensure_file_synced=self.ensure_file_synced,
            lock=asyncio.Lock(),
            stable_lock=self._stable_lock,
        )
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
        if self._file_watcher:
            await self._file_watcher.stop()
            self._file_watcher = None
        await self._manager.close_all()
        self._agent_workspaces.clear()
        self._stable_workspace = None
        self._streaming_sync = None

    async def _sync_project_to_workspace(self) -> None:
        """Sync project files into the stable workspace."""
        if self._stable_workspace is None:
            return

        for path in self._project_root.rglob("*"):
            if path.is_dir():
                continue
            if self._should_ignore(path):
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

    async def ensure_file_synced(self, rel_path: str) -> bool:
        """Ensure a specific file is synced to workspace."""
        if self._streaming_sync:
            return await self._streaming_sync.ensure_synced(rel_path)
        if self._sync_mode == SyncMode.FULL:
            return True
        return False

    def get_sync_stats(self) -> SyncStats | None:
        """Get streaming sync statistics."""
        if self._streaming_sync:
            return self._streaming_sync.get_stats()
        return None

    def _should_ignore(self, path: Path) -> bool:
        try:
            rel_parts = path.relative_to(self._project_root).parts
        except ValueError:
            return True

        for part in rel_parts:
            if part in self._ignore_patterns:
                return True
            if self._ignore_dotfiles and part.startswith("."):
                return True
        return False


__all__ = ["CairnWorkspaceService", "SyncMode"]
