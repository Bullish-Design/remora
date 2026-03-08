"""Cairn workspace bridge for Remora.

Provides stable and per-agent workspaces using Cairn runtime APIs.
Remora does not import fsdantic directly; all workspace access flows
through Cairn.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from cairn.runtime import workspace_manager as cairn_workspace_manager
from cairn.runtime.workspace_manager import open_workspace as cairn_open_workspace

from remora.core.agents.cairn_externals import CairnExternals
from remora.core.agents.workspace import AgentWorkspace
from remora.core.config import DEFAULT_IGNORE_PATTERNS, Config
from remora.core.errors import WorkspaceError
from remora.utils import PathLike, PathResolver, normalize_path

logger = logging.getLogger(__name__)

OPEN_WORKSPACE_PROGRESS_INTERVAL_SECONDS = 5.0
SYNC_PROGRESS_INTERVAL_SECONDS = 2.0
SYNC_PROGRESS_FILE_INTERVAL = 2000


class SyncMode(Enum):
    """Levels of syncing project files into the workspace."""

    FULL = "full"
    NONE = "none"


class CairnWorkspaceService:
    """Manage stable and agent workspaces via Cairn."""

    def __init__(
        self,
        config: Config,
        *,
        graph_id: str | None = None,
        swarm_root: PathLike | None = None,
        project_root: PathLike | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self._config = config
        self._graph_id = graph_id or config.swarm_id or "default"

        base_path = normalize_path(swarm_root or config.swarm_root)
        self._swarm_root = base_path / self._graph_id
        self._project_root = normalize_path(project_root or Path.cwd()).resolve()
        self._resolver = PathResolver(self._project_root)
        self._manager = cairn_workspace_manager.WorkspaceManager()
        self._stable_workspace: Any | None = None
        self._agent_workspaces: dict[str, AgentWorkspace] = {}
        self._agent_workspaces_lock = asyncio.Lock()
        self._ignore_patterns: set[str] = set(config.workspace_ignore_patterns or DEFAULT_IGNORE_PATTERNS)
        self._ignore_dotfiles: bool = config.workspace_ignore_dotfiles
        self._file_mtimes: dict[str, float] = {}
        self._progress_callback = progress_callback

    def _reset_runtime_state(self) -> None:
        self._manager = cairn_workspace_manager.WorkspaceManager()
        self._stable_workspace = None
        self._agent_workspaces = {}
        self._agent_workspaces_lock = asyncio.Lock()

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def resolver(self) -> PathResolver:
        return self._resolver

    async def initialize(self, *, sync_mode: SyncMode | None = None) -> None:
        """Initialize stable workspace and optionally sync project files."""
        if self._stable_workspace is not None:
            return

        mode = sync_mode or SyncMode.FULL
        self._progress(
            "initialize start "
            f"(mode={mode.value} project_root={self._project_root} swarm_root={self._swarm_root} "
            f"ignore_dotfiles={self._ignore_dotfiles} ignore_patterns={sorted(self._ignore_patterns)})"
        )
        if not self._ignore_dotfiles:
            self._progress(
                "dotfiles are included in workspace sync; large trees like .devenv/.venv can delay startup"
            )
        self._swarm_root.mkdir(parents=True, exist_ok=True)
        stable_path = self._swarm_root / "stable.db"

        try:
            self._progress(f"opening stable workspace at {stable_path}")
            open_task = asyncio.create_task(cairn_open_workspace(stable_path, readonly=False))
            open_started_at = time.monotonic()
            while not open_task.done():
                try:
                    await asyncio.wait_for(
                        asyncio.shield(open_task),
                        timeout=OPEN_WORKSPACE_PROGRESS_INTERVAL_SECONDS,
                    )
                except TimeoutError:
                    elapsed_ms = (time.monotonic() - open_started_at) * 1000
                    self._progress(
                        "waiting for stable workspace open "
                        f"(path={stable_path} elapsed_ms={elapsed_ms:.1f})"
                    )
            self._stable_workspace = await open_task
            self._progress(f"stable workspace opened (elapsed_ms={(time.monotonic() - open_started_at) * 1000:.1f})")
            self._manager.track_workspace(self._stable_workspace)
            self._progress("stable workspace tracked")
        except Exception as exc:
            self._progress(f"failed to create stable workspace at {stable_path}: {exc!r}")
            raise WorkspaceError(f"Failed to create stable workspace: {exc}") from exc

        if mode is SyncMode.FULL:
            self._progress("starting full project sync")
            sync_started = time.monotonic()
            await self._sync_project_to_workspace()
            self._progress(f"full project sync complete (elapsed_ms={(time.monotonic() - sync_started) * 1000:.1f})")
        else:
            self._progress("sync skipped (mode=none)")

    async def get_agent_workspace(self, agent_id: str) -> AgentWorkspace:
        """Get or create an agent workspace."""
        if agent_id in self._agent_workspaces:
            return self._agent_workspaces[agent_id]

        async with self._agent_workspaces_lock:
            if agent_id in self._agent_workspaces:
                return self._agent_workspaces[agent_id]

            if self._stable_workspace is None:
                raise WorkspaceError("CairnWorkspaceService is not initialized")

            workspace_path = self._swarm_root / "agents" / agent_id[:2] / agent_id / "workspace.db"
            workspace_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                workspace = await cairn_open_workspace(
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
        await self._manager.close_all()
        self._reset_runtime_state()

    async def prepare_runtime_handoff(self) -> None:
        """Drop loop-bound workspace handles before crossing event loops.

        Stable/agent workspace objects wrap async DB connections that are bound
        to the loop where they were opened. Startup uses a bootstrap loop, then
        pygls serves requests on a different loop, so these handles must be
        closed and reopened after handoff.
        """
        has_runtime_handles = self._stable_workspace is not None or bool(self._agent_workspaces)
        if not has_runtime_handles:
            self._reset_runtime_state()
            return

        self._progress("runtime handoff start (closing loop-bound workspace handles)")
        try:
            await self._manager.close_all()
        except Exception as exc:
            logger.debug("runtime handoff close_all failed: %s", exc)
        self._reset_runtime_state()
        self._progress("runtime handoff complete")

    async def _sync_project_to_workspace(self) -> None:
        """Sync project files into the stable workspace, skipping unchanged files."""
        if self._stable_workspace is None:
            return

        start = time.monotonic()
        scanned_files = 0
        skipped_dirs = 0
        skipped_ignored = 0
        skipped_outside = 0
        skipped_unchanged = 0
        synced_files = 0
        read_failures = 0
        write_failures = 0
        top_level_counts: dict[str, int] = {}
        last_progress_at = start

        for dirpath, dirs, files in os.walk(self._project_root, topdown=True, followlinks=False):
            dir_path = Path(dirpath)
            try:
                dir_rel_parts = dir_path.relative_to(self._project_root).parts
            except ValueError:
                skipped_outside += 1
                dirs[:] = []
                continue

            # Prune ignored directories before traversal to avoid scanning huge trees.
            pruned = 0
            keep_dirs: list[str] = []
            for dname in dirs:
                child_rel_parts = (*dir_rel_parts, dname)
                if self._should_ignore_parts(child_rel_parts):
                    pruned += 1
                    continue
                keep_dirs.append(dname)
            if pruned:
                skipped_ignored += pruned
                skipped_dirs += pruned
            dirs[:] = keep_dirs

            for fname in files:
                scanned_files += 1
                rel_parts = (*dir_rel_parts, fname)
                top = rel_parts[0] if rel_parts else "."
                top_level_counts[top] = top_level_counts.get(top, 0) + 1

                now = time.monotonic()
                if (
                    scanned_files % SYNC_PROGRESS_FILE_INTERVAL == 0
                    or (now - last_progress_at) >= SYNC_PROGRESS_INTERVAL_SECONDS
                ):
                    self._progress(
                        "sync progress "
                        f"(elapsed_ms={(now - start) * 1000:.1f} scanned={scanned_files} synced={synced_files} "
                        f"ignored={skipped_ignored} unchanged={skipped_unchanged} read_failures={read_failures} "
                        f"write_failures={write_failures})"
                    )
                    last_progress_at = now

                if self._should_ignore_parts(rel_parts):
                    skipped_ignored += 1
                    continue

                path = dir_path / fname
                if not self._resolver.is_within_project(path):
                    skipped_outside += 1
                    continue

                # Incremental sync: skip files whose mtime hasn't changed
                try:
                    current_mtime = path.stat().st_mtime
                except OSError:
                    continue
                rel_path = self._resolver.to_workspace_path(path)
                if self._file_mtimes.get(rel_path) == current_mtime:
                    skipped_unchanged += 1
                    continue

                try:
                    payload = path.read_bytes()
                except OSError as exc:
                    logger.debug("Failed to read %s: %s", path, exc)
                    read_failures += 1
                    continue

                try:
                    await self._stable_workspace.files.write(rel_path, payload, mode="binary")
                    self._file_mtimes[rel_path] = current_mtime
                    synced_files += 1
                except Exception as exc:
                    logger.debug("Failed to write %s to stable workspace: %s", rel_path, exc)
                    write_failures += 1

        top_summary = ", ".join(
            f"{name}:{count}"
            for name, count in sorted(top_level_counts.items(), key=lambda item: item[1], reverse=True)[:8]
        )
        self._progress(
            "sync summary "
            f"(elapsed_ms={(time.monotonic() - start) * 1000:.1f} scanned={scanned_files} "
            f"dirs_skipped={skipped_dirs} ignored={skipped_ignored} outside={skipped_outside} "
            f"unchanged={skipped_unchanged} synced={synced_files} read_failures={read_failures} "
            f"write_failures={write_failures} top_roots=[{top_summary}])"
        )

    async def ensure_file_synced(self, rel_path: str) -> bool:
        """Ensure a specific file is synced to the stable workspace.

        Reads the file from the project root and writes it into the stable
        workspace.  Returns ``False`` when the source file does not exist.
        """
        rel_path = rel_path.lstrip("/")
        if not rel_path:
            return False
        source = self._project_root / rel_path
        if not source.exists():
            return False

        try:
            payload = source.read_bytes()
        except OSError as exc:
            logger.debug("ensure_file_synced: failed to read %s: %s", source, exc)
            return False

        try:
            await self._stable_workspace.files.write(rel_path, payload, mode="binary")
        except Exception as exc:
            logger.debug("ensure_file_synced: failed to write %s: %s", rel_path, exc)
            return False

        return True

    def _should_ignore(self, path: Path) -> bool:
        try:
            rel_parts = path.relative_to(self._project_root).parts
        except ValueError:
            return True
        return self._should_ignore_parts(rel_parts)

    def _should_ignore_parts(self, rel_parts: tuple[str, ...]) -> bool:
        for part in rel_parts:
            if part in self._ignore_patterns:
                return True
            if self._ignore_dotfiles and part.startswith("."):
                return True
        return False

    def _progress(self, message: str) -> None:
        logger.info("CairnWorkspaceService %s", message)
        if self._progress_callback is not None:
            self._progress_callback(f"CairnWorkspaceService: {message}")


__all__ = ["CairnWorkspaceService", "SyncMode"]
