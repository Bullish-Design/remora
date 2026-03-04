"""Workspace inspector wrapper for Cairn WorkspaceInspector.

Provides a high-level interface for inspecting Cairn workspace contents
from the Remora CLI and tooling.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cairn import WorkspaceInspector, WorkspaceStats

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """Information about a file in the workspace."""

    path: str
    size: int
    is_binary: bool = False


@dataclass
class DirectoryInfo:
    """Information about a directory in the workspace."""

    path: str
    file_count: int
    subdirs: list[str]


class RemoraWorkspaceInspector:
    """High-level workspace inspector for Remora.

    Wraps Cairn's WorkspaceInspector with Remora-specific conveniences
    for CLI output and tooling integration.

    Example:
        ```python
        async with RemoraWorkspaceInspector.open("/path/to/workspace.db") as inspector:
            # Get workspace statistics
            stats = await inspector.stats()
            print(f"Files: {stats.file_count}, Size: {stats.total_size}")

            # List directory contents
            entries = await inspector.list_dir("/src")

            # Get file tree
            tree = await inspector.tree("/")
        ```
    """

    def __init__(self, cairn_inspector: WorkspaceInspector):
        """Create inspector from Cairn WorkspaceInspector.

        Use RemoraWorkspaceInspector.open() for convenient context manager usage.
        """
        self._inspector = cairn_inspector

    @classmethod
    async def open(cls, workspace_path: str | Path) -> "RemoraWorkspaceInspector":
        """Open a workspace for inspection.

        Args:
            workspace_path: Path to the workspace .db file

        Returns:
            RemoraWorkspaceInspector instance

        Example:
            ```python
            inspector = await RemoraWorkspaceInspector.open("/path/to/workspace.db")
            try:
                stats = await inspector.stats()
            finally:
                await inspector.close()
            ```
        """
        cairn_inspector = await WorkspaceInspector.from_path(str(workspace_path))
        return cls(cairn_inspector)

    async def close(self) -> None:
        """Close the inspector and release resources.

        Note: cairn v0.2.0 WorkspaceInspector no longer has an explicit
        close method — the underlying workspace is closed automatically.
        This is kept for interface compatibility.
        """
        workspace = getattr(self._inspector, "workspace", None)
        if workspace is not None and hasattr(workspace, "close"):
            await workspace.close()

    async def __aenter__(self) -> "RemoraWorkspaceInspector":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    async def stats(self) -> WorkspaceStats:
        """Get workspace statistics.

        Returns:
            WorkspaceStats with file_count, total_size, etc.
        """
        return await self._inspector.stats()

    async def tree(self, path: str = "/", max_depth: int = -1) -> str:
        """Get directory tree as formatted string.

        Args:
            path: Root path for the tree (default: "/")
            max_depth: Maximum depth to traverse (-1 for unlimited)

        Returns:
            Formatted tree string suitable for CLI output
        """
        return await self._inspector.tree(path, max_depth=max_depth)

    async def list_dir(self, path: str = "/") -> list[str]:
        """List directory contents.

        Args:
            path: Directory path to list

        Returns:
            List of entry names in the directory
        """
        return await self._inspector.list_dir(path)

    async def read_file(self, path: str) -> str:
        """Read file contents as text.

        Args:
            path: Path to the file

        Returns:
            File contents as string

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        return await self._inspector.read(path)

    async def exists(self, path: str) -> bool:
        """Check if path exists in workspace.

        Args:
            path: Path to check

        Returns:
            True if path exists
        """
        return await self._inspector.exists(path)

    async def get_kv_keys(self, prefix: str = "") -> list[str]:
        """List KV store keys with optional prefix filter.

        Args:
            prefix: Optional prefix to filter keys

        Returns:
            List of matching key names
        """
        workspace = self._inspector.workspace
        entries = await workspace.kv.list(prefix)
        return [entry["key"] for entry in entries if "key" in entry]

    async def get_kv_value(self, key: str):
        """Get value from KV store.

        Args:
            key: The key to look up

        Returns:
            The stored value, or None if not found
        """
        workspace = self._inspector.workspace
        return await workspace.kv.get(key, default=None)

    def format_stats(self, stats: WorkspaceStats) -> str:
        """Format stats for CLI output.

        Args:
            stats: WorkspaceStats to format

        Returns:
            Human-readable stats string
        """
        size_str = self._format_size(stats.total_bytes)
        return (
            f"Workspace Statistics:\n"
            f"  Files: {stats.file_count}\n"
            f"  Directories: {stats.dir_count}\n"
            f"  Total Size: {size_str}"
        )

    def _format_size(self, size_bytes: int) -> str:
        """Format byte size as human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


__all__ = ["RemoraWorkspaceInspector", "FileInfo", "DirectoryInfo"]
