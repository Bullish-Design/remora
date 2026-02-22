# src/remora/workspace_bridge.py
"""Workspace interactions for Remora."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from cairn.runtime.workspace_manager import WorkspaceManager


class CairnWorkspaceBridge:
    """Encapsulates interaction with the Cairn WorkspaceManager."""
    
    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        project_root: Path,
        cache_root: Path,
    ) -> None:
        """Initialize the workspace bridge.
        
        Args:
            workspace_manager: The underlying Cairn WorkspaceManager instance.
            project_root: The root of the project the agent is operating on.
            cache_root: The root path where Remora's cache (including workspaces) lives.
        """
        self.workspace_manager = workspace_manager
        self.project_root = project_root
        self.cache_root = cache_root

    def get_workspace_db_path(self, workspace_id: str) -> Path:
        """Get the filesystem path to the sqlite DB for a workspace."""
        return self.cache_root / "workspaces" / workspace_id / "workspace.db"

    def _get_workspace_root(self, workspace_id: str) -> Path:
        """Get the filesystem root directory for a workspace."""
        return self.get_workspace_db_path(workspace_id).parent

    @staticmethod
    def _write_workspace_file(target_path: Path, content: bytes | str) -> None:
        """Helper to synchronously write content to a file, creating parents if needed."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target_path.write_bytes(content)
        else:
            target_path.write_text(content, encoding="utf-8")

    @staticmethod
    def _remove_workspace_dir(workspace_root: Path) -> None:
        """Helper to synchronously remove a workspace directory tree."""
        if workspace_root.exists():
            shutil.rmtree(workspace_root)

    async def merge(self, workspace_id: str) -> None:
        """Merge a workspace into the stable project root."""
        workspace_db = self.get_workspace_db_path(workspace_id)
        if not workspace_db.exists():
            raise FileNotFoundError(f"Workspace database not found: {workspace_db}")

        async with self.workspace_manager.open_workspace(workspace_db) as workspace:
            changed_paths = await workspace.overlay.list_changes("/")
            for overlay_path in changed_paths:
                relative_path = overlay_path.lstrip("/")
                target_path = (self.project_root / relative_path).resolve()
                if self.project_root not in target_path.parents and target_path != self.project_root:
                    raise ValueError(f"Refusing to write outside project root: {target_path}")
                content = await workspace.files.read(overlay_path, mode="binary", encoding=None)
                await asyncio.to_thread(self._write_workspace_file, target_path, content)

            await workspace.overlay.reset()

        await asyncio.to_thread(self._remove_workspace_dir, self._get_workspace_root(workspace_id))

    async def discard(self, workspace_id: str) -> None:
        """Discard a workspace, abandoning all changes."""
        workspace_db = self.get_workspace_db_path(workspace_id)
        if not workspace_db.exists():
            raise FileNotFoundError(f"Workspace database not found: {workspace_db}")

        async with self.workspace_manager.open_workspace(workspace_db) as workspace:
            await workspace.overlay.reset()

        await asyncio.to_thread(self._remove_workspace_dir, self._get_workspace_root(workspace_id))
