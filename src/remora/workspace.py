"""Cairn workspace layer for Remora.

This module provides thin wrappers around Cairn workspaces:
- CairnDataProvider: Populates Grail virtual FS from Cairn workspace
- CairnResultHandler: Writes script results back to Cairn workspace
- Workspace factory functions for agent and shared workspaces
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkspaceConfig:
    """Configuration for Cairn workspaces."""

    base_path: Path
    cleanup_after_seconds: int | None = None


class CairnDataProvider:
    """Populates Grail virtual FS from a Cairn workspace.

    This class implements the data provider pattern from structured-agents v0.3.
    It reads files from the Cairn workspace to populate the virtual filesystem
    that .pym scripts operate on.
    """

    def __init__(self, workspace: Any) -> None:
        """Initialize with a Cairn workspace."""
        self._ws = workspace

    async def load_files(self, node: Any) -> dict[str, str]:
        """Read the target file + related files from the workspace.

        Args:
            node: The CSTNode to load files for. Must have:
                - file_path: str path to the target file
                - related_files: list[str] of related file paths (optional)

        Returns:
            Dict mapping virtual file paths to their contents
        """
        files = {}

        main_path = getattr(node, "file_path", None)
        if main_path:
            try:
                content = await self._ws.read(main_path)
                files[main_path] = content
            except FileNotFoundError:
                files[main_path] = ""

        related = getattr(node, "related_files", None)
        if related:
            for rel_path in related:
                try:
                    content = await self._ws.read(rel_path)
                    files[rel_path] = content
                except FileNotFoundError:
                    files[rel_path] = ""

        return files

    async def load_file(self, path: str) -> str:
        """Load a single file from the workspace.

        Args:
            path: Path to the file relative to workspace root

        Returns:
            File contents as string, or empty string if not found
        """
        try:
            return await self._ws.read(path)
        except FileNotFoundError:
            return ""


class CairnResultHandler:
    """Writes script results back to the Cairn workspace.

    This class implements the result handler pattern from structured-agents v0.3.
    It processes structured results from .pym scripts and persists them to
    the Cairn workspace.
    """

    async def handle(self, result: dict[str, Any], workspace: Any) -> None:
        """Process and persist script results.

        Args:
            result: The result dict returned by a .pym script. Common keys:
                - written_file: str path to write
                - content: str content to write
                - lint_fixes: list[dict] of {path, content} fixes
                - deleted_files: list[str] of paths to delete
            workspace: The Cairn workspace to write to
        """
        if "written_file" in result and "content" in result:
            await workspace.write(result["written_file"], result["content"])

        if "lint_fixes" in result:
            for fix in result["lint_fixes"]:
                if "path" in fix and "content" in fix:
                    await workspace.write(fix["path"], fix["content"])

        if "deleted_files" in result:
            for path in result["deleted_files"]:
                await workspace.delete(path)

        if "generated_tests" in result:
            for test_file in result["generated_tests"]:
                if "path" in test_file and "content" in test_file:
                    await workspace.write(test_file["path"], test_file["content"])

    async def extract_writes(self, result: dict[str, Any]) -> list[tuple[str, str]]:
        """Extract file writes from a result without persisting.

        Useful for preview/dry-run modes.

        Args:
            result: The result dict from a .pym script

        Returns:
            List of (path, content) tuples
        """
        writes = []

        if "written_file" in result and "content" in result:
            writes.append((result["written_file"], result["content"]))

        if "lint_fixes" in result:
            for fix in result["lint_fixes"]:
                if "path" in fix and "content" in fix:
                    writes.append((fix["path"], fix["content"]))

        if "generated_tests" in result:
            for test_file in result["generated_tests"]:
                if "path" in test_file and "content" in test_file:
                    writes.append((test_file["path"], test_file["content"]))

        return writes


async def create_workspace(
    agent_id: str,
    config: WorkspaceConfig,
) -> Any:
    """Create an isolated workspace for a single agent.

    Args:
        agent_id: Unique identifier for this agent
        config: Workspace configuration

    Returns:
        Cairn workspace instance
    """
    raise NotImplementedError("Cairn integration pending")


async def create_shared_workspace(
    graph_id: str,
    config: WorkspaceConfig,
) -> Any:
    """Create a shared workspace for a graph.

    Args:
        graph_id: Unique identifier for this graph
        config: Workspace configuration

    Returns:
        Cairn workspace instance (the shared base)
    """
    raise NotImplementedError("Cairn integration pending")


async def snapshot_workspace(
    workspace: Any,
    snapshot_name: str,
) -> str:
    """Create a snapshot of a workspace.

    Args:
        workspace: Cairn workspace to snapshot
        snapshot_name: Name for the snapshot

    Returns:
        Snapshot identifier
    """
    raise NotImplementedError("Cairn integration pending")


async def restore_workspace(
    workspace: Any,
    snapshot_id: str,
) -> None:
    """Restore a workspace from a snapshot.

    Args:
        workspace: Cairn workspace to restore into
        snapshot_id: Identifier of the snapshot to restore
    """
    raise NotImplementedError("Cairn integration pending")


# Backwards compatibility - keep old workspace classes
class WorkspaceKV:
    """Backwards compatible WorkspaceKV wrapper."""

    pass


class GraphWorkspace:
    """Backwards compatible GraphWorkspace wrapper."""

    pass


class WorkspaceManager:
    """Backwards compatible WorkspaceManager wrapper."""

    pass


__all__ = [
    "CairnDataProvider",
    "CairnResultHandler",
    "WorkspaceConfig",
    "create_workspace",
    "create_shared_workspace",
    "snapshot_workspace",
    "restore_workspace",
    "WorkspaceKV",
    "GraphWorkspace",
    "WorkspaceManager",
]
