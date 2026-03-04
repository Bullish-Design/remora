"""Bidirectional workspace sync utilities.

Enables syncing changes from a disk directory into a workspace,
detecting added, modified, and deleted files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from remora.core.protocols import WorkspaceProtocol

logger = logging.getLogger(__name__)


@dataclass
class SyncChange:
    """Represents a single change detected during sync scan."""

    path: str
    change_type: Literal["added", "modified", "deleted"]
    disk_path: Path | None = None


@dataclass
class SyncResult:
    """Result of a sync operation."""

    synced: list[SyncChange] = field(default_factory=list)
    skipped: list[SyncChange] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return len(self.synced) + len(self.skipped) + len(self.errors)


class WorkspaceSync:
    """Sync changes between a disk directory and a workspace.

    Scans a disk directory for files that differ from the workspace
    and optionally applies those changes.

    Args:
        workspace: Workspace to sync into (implements WorkspaceProtocol).
        project_root: Root directory on disk to sync from.
    """

    def __init__(
        self,
        workspace: WorkspaceProtocol,
        project_root: Path,
    ) -> None:
        self._workspace = workspace
        self._project_root = project_root

    async def scan_disk_changes(
        self,
        disk_dir: Path,
        workspace_prefix: str = "/",
    ) -> list[SyncChange]:
        """Scan a disk directory and find changes vs workspace.

        Detects files that are new (added), changed (modified), or
        present in the workspace but missing on disk (deleted).

        Args:
            disk_dir: Directory on disk to scan.
            workspace_prefix: Prefix for workspace paths (default: "/").

        Returns:
            List of SyncChange objects describing detected changes.
        """
        changes: list[SyncChange] = []
        prefix = workspace_prefix.rstrip("/")

        # Scan disk files for added/modified
        for disk_path in sorted(disk_dir.rglob("*")):
            if disk_path.is_dir():
                continue

            rel_path = disk_path.relative_to(disk_dir)
            ws_path = f"{prefix}/{rel_path.as_posix()}"

            exists = await self._workspace.exists(ws_path)

            if not exists:
                changes.append(
                    SyncChange(
                        path=ws_path,
                        change_type="added",
                        disk_path=disk_path,
                    )
                )
            else:
                # Compare content
                disk_content = disk_path.read_text(encoding="utf-8", errors="replace")
                try:
                    ws_content = await self._workspace.read(ws_path)
                    if disk_content != ws_content:
                        changes.append(
                            SyncChange(
                                path=ws_path,
                                change_type="modified",
                                disk_path=disk_path,
                            )
                        )
                except Exception:
                    # If we can't read, treat as modified
                    changes.append(
                        SyncChange(
                            path=ws_path,
                            change_type="modified",
                            disk_path=disk_path,
                        )
                    )

        return changes

    async def scan_deleted(
        self,
        disk_dir: Path,
        workspace_prefix: str = "/",
    ) -> list[SyncChange]:
        """Scan for workspace files missing from disk.

        Walks workspace entries under workspace_prefix and checks
        whether each file still exists on disk.

        Args:
            disk_dir: Directory on disk to compare against.
            workspace_prefix: Workspace path prefix to scan.

        Returns:
            List of SyncChange with change_type="deleted".
        """
        prefix = workspace_prefix.rstrip("/")
        deleted: list[SyncChange] = []

        await self._walk_deleted(prefix or "/", disk_dir, prefix, deleted)
        return deleted

    async def _walk_deleted(
        self,
        ws_dir: str,
        disk_dir: Path,
        prefix: str,
        deleted: list[SyncChange],
    ) -> None:
        """Recursively walk workspace dirs to find deleted files."""
        try:
            entries = await self._workspace.list_dir(ws_dir)
        except Exception:
            return

        for entry in entries:
            ws_path = f"{ws_dir.rstrip('/')}/{entry}"
            # Derive disk path from workspace path
            rel = ws_path
            if prefix and rel.startswith(prefix):
                rel = rel[len(prefix) :]
            rel = rel.lstrip("/")
            disk_path = disk_dir / rel

            # Determine if entry is a directory (has children) or a file.
            # list_dir returns a non-empty list for directories and an
            # empty list for files (or non-existent dirs).
            try:
                sub_entries = await self._workspace.list_dir(ws_path)
            except Exception:
                sub_entries = []

            if sub_entries:
                # It's a directory — recurse
                await self._walk_deleted(ws_path, disk_dir, prefix, deleted)
            else:
                # It's a file — check if deleted from disk
                if not disk_path.exists():
                    deleted.append(
                        SyncChange(
                            path=ws_path,
                            change_type="deleted",
                            disk_path=None,
                        )
                    )

    async def sync_from_disk(
        self,
        disk_dir: Path,
        workspace_prefix: str = "/",
        *,
        dry_run: bool = False,
        include_deleted: bool = False,
    ) -> SyncResult:
        """Sync changes from disk directory into the workspace.

        Args:
            disk_dir: Directory on disk to sync from.
            workspace_prefix: Workspace path prefix.
            dry_run: If True, report changes without applying them.
            include_deleted: If True, also delete workspace files
                missing from disk.

        Returns:
            SyncResult with synced, skipped, and error details.
        """
        changes = await self.scan_disk_changes(disk_dir, workspace_prefix)

        if include_deleted:
            deleted = await self.scan_deleted(disk_dir, workspace_prefix)
            changes.extend(deleted)

        synced: list[SyncChange] = []
        skipped: list[SyncChange] = []
        errors: list[tuple[str, str]] = []

        for change in changes:
            if dry_run:
                synced.append(change)
                continue

            try:
                if change.change_type in ("added", "modified"):
                    if change.disk_path is None:
                        skipped.append(change)
                        continue
                    content = change.disk_path.read_text(encoding="utf-8", errors="replace")
                    await self._workspace.write(change.path, content)
                    synced.append(change)
                elif change.change_type == "deleted":
                    await self._workspace.delete(change.path)
                    synced.append(change)
            except Exception as e:
                errors.append((change.path, str(e)))

        return SyncResult(
            synced=synced,
            skipped=skipped,
            errors=errors,
        )


__all__ = ["SyncChange", "SyncResult", "WorkspaceSync"]
