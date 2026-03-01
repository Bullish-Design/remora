"""Cairn workspace integration.

Provides thin wrappers around Cairn for agent workspace management.
Remora does not import fsdantic directly; workspace access flows through Cairn.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from cairn.runtime import workspace_manager as cairn_workspace_manager

from remora.core.config import Config
from remora.core.discovery import CSTNode
from remora.core.errors import WorkspaceError
from remora.utils import PathLike, PathResolver, normalize_path

logger = logging.getLogger(__name__)


class AgentWorkspace:
    """Workspace for a single agent execution.

    Wraps a Cairn workspace with agent-specific convenience methods.
    """

    def __init__(
        self,
        workspace: Any,
        agent_id: str,
        stable_workspace: Any | None = None,
        *,
        ensure_file_synced: Callable[[str], Awaitable[bool]] | None = None,
        lock: asyncio.Lock | None = None,
        stable_lock: asyncio.Lock | None = None,
    ):
        self._workspace = workspace
        self._agent_id = agent_id
        self._stable_workspace = stable_workspace
        self._ensure_file_synced = ensure_file_synced
        self._lock = lock or asyncio.Lock()
        if stable_workspace is not None:
            self._stable_lock = stable_lock or self._lock
        else:
            self._stable_lock = None

    @property
    def cairn(self) -> Any:
        """Access underlying Cairn workspace."""
        return self._workspace

    async def read(self, path: PathLike) -> str:
        """Read a file from the workspace."""
        path_str = normalize_path(path).as_posix()
        try:
            async with self._lock:
                return await self._workspace.files.read(path_str, mode="text")
        except Exception as exc:
            if not _is_missing_file_error(exc) or self._stable_workspace is None:
                raise
        async with self._stable_lock:
            try:
                return await self._stable_workspace.files.read(path_str, mode="text")
            except Exception as exc:
                if not _is_missing_file_error(exc):
                    raise

        if self._ensure_file_synced is not None:
            await self._ensure_file_synced(path_str)
            async with self._stable_lock:
                return await self._stable_workspace.files.read(path_str, mode="text")
        raise FileNotFoundError(path_str)

    async def write(self, path: PathLike, content: str | bytes) -> None:
        """Write a file to the workspace (CoW isolated)."""
        path_str = normalize_path(path).as_posix()
        async with self._lock:
            await self._workspace.files.write(path_str, content)

    async def exists(self, path: PathLike) -> bool:
        """Check if a file exists in the workspace."""
        path_str = normalize_path(path).as_posix()
        async with self._lock:
            if await self._workspace.files.exists(path_str):
                return True
        if self._stable_workspace is None:
            return False
        async with self._stable_lock:
            return await self._stable_workspace.files.exists(path_str)

    async def list_dir(self, path: PathLike = ".") -> list[str]:
        """List directory entries in the workspace."""
        path_str = normalize_path(path).as_posix()
        async with self._lock:
            entries = set(await self._workspace.files.list_dir(path_str, output="name"))
        if self._stable_workspace is not None:
            try:
                async with self._stable_lock:
                    stable_entries = await self._stable_workspace.files.list_dir(path_str, output="name")
            except Exception:
                stable_entries = []
            entries.update(stable_entries)
        return sorted(entries)




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
            fallback_content = self._load_from_disk(node.file_path)
            if fallback_content is not None:
                files[target_path] = fallback_content
                if node.file_path != target_path:
                    files[node.file_path] = fallback_content
                logger.debug(
                    "Loaded %s directly from disk after workspace miss: %s",
                    node.file_path,
                    target_path,
                )
            else:
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

    def _resolve_disk_path(self, path: str) -> Path:
        path_obj = normalize_path(path)
        if not path_obj.is_absolute():
            path_obj = (self._resolver.project_root / path_obj).resolve()
        return path_obj

    def _load_from_disk(self, path: str) -> str | None:
        try:
            disk_path = self._resolve_disk_path(path)
            return disk_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.debug("Fallback read failed for %s: %s", path, exc)
            return None


__all__ = [
    "AgentWorkspace",
    "CairnDataProvider",
]


def _is_missing_file_error(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    code = getattr(exc, "code", None)
    if code in {"FS_NOT_FOUND", "ENOENT"}:
        return True
    context = getattr(exc, "context", None)
    if isinstance(context, dict) and context.get("agentfs_code") == "ENOENT":
        return True
    errno_value = getattr(exc, "errno", None)
    return errno_value == 2
