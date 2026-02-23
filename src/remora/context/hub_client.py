"""Hub client for Pull Hook integration.

This client reads directly from the Hub workspace.
Implements the "Lazy Daemon" pattern for graceful degradation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from fsdantic import Fsdantic, Workspace

from remora.constants import HUB_DB_NAME

if TYPE_CHECKING:
    from remora.hub.models import NodeState
    from remora.hub.store import NodeStateStore

logger = logging.getLogger(__name__)


class HubClient:
    """Client for reading Hub context.

    Design: "Lazy Daemon" pattern
    - If Hub is fresh, read directly from workspace
    - If Hub is stale and daemon running, warn but proceed
    - If Hub is stale and daemon not running, do ad-hoc index

    This provides graceful degradation when the daemon isn't running
    while still giving optimal performance when it is.
    """

    STALE_THRESHOLD_SECONDS = 5.0
    MAX_ADHOC_FILES = 5

    def __init__(
        self,
        hub_db_path: Path | None = None,
        project_root: Path | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            hub_db_path: Path to {HUB_DB_NAME} (default: auto-discover)
            project_root: Project root for ad-hoc indexing
        """
        self.hub_db_path = hub_db_path
        self.project_root = project_root

        self._workspace: Workspace | None = None
        self._store: "NodeStateStore | None" = None
        self._available: bool | None = None

    async def get_context(self, node_ids: list[str]) -> dict[str, "NodeState"]:
        """Get context for nodes with lazy fallback.

        Returns empty dict if Hub not available (graceful degradation).
        """
        if not await self._check_available():
            return {}

        await self._ensure_workspace()
        if self._store is None:
            return {}

        stale_files = await self._check_freshness(node_ids)
        if stale_files:
            if await self._daemon_running():
                logger.debug("Hub has stale data, daemon running")
            else:
                logger.warning(
                    "Hub daemon not running - performing ad-hoc index",
                    extra={"stale_files": len(stale_files)},
                )
                await self._adhoc_index(stale_files)

        return await self._store.get_many(node_ids)

    async def health_check(self) -> bool:
        """Check if Hub is available and responsive."""
        return await self._check_available()

    async def close(self) -> None:
        """Close the workspace."""
        if self._workspace is not None:
            await self._workspace.close()
            self._workspace = None
            self._store = None

    async def _check_available(self) -> bool:
        if self._available is True:
            return True

        if self.hub_db_path is None:
            self.hub_db_path = self._discover_db_path()

        if self.hub_db_path is None or not self.hub_db_path.exists():
            return False

        self._available = True
        return True

    async def _ensure_workspace(self) -> None:
        """Open workspace if not already open."""
        if self._workspace is None:
            self._workspace = await Fsdantic.open(path=str(self.hub_db_path))
            from remora.hub.store import NodeStateStore

            self._store = NodeStateStore(self._workspace)

    async def _check_freshness(self, node_ids: list[str]) -> list[Path]:
        """Check which files are stale."""
        if self._store is None:
            return []

        stale: list[Path] = []
        seen_files: set[Path] = set()

        for node_id in node_ids:
            file_path = self._node_id_to_path(node_id)
            if file_path in seen_files:
                continue
            seen_files.add(file_path)

            if not file_path.exists():
                continue

            index = await self._store.get_file_index(str(file_path))
            if index is None:
                stale.append(file_path)
                continue

            file_mtime = file_path.stat().st_mtime
            last_scanned = index.last_scanned
            if isinstance(last_scanned, str):
                last_scanned_dt = datetime.fromisoformat(last_scanned)
            else:
                last_scanned_dt = last_scanned
            if file_mtime > last_scanned_dt.timestamp() + self.STALE_THRESHOLD_SECONDS:
                stale.append(file_path)

        return stale

    async def _daemon_running(self) -> bool:
        """Check if Hub daemon is running."""
        if self.hub_db_path is None:
            return False

        pid_file = self.hub_db_path.parent / "hub.pid"
        return pid_file.exists()

    async def _adhoc_index(self, files: list[Path]) -> None:
        """Perform minimal ad-hoc indexing for critical files."""
        if self.project_root is None:
            self.project_root = self._discover_project_root()

        if self.project_root is None:
            logger.warning("Hub client could not locate project root for ad-hoc index")
            return

        if self._store is None:
            return

        from remora.hub.indexer import index_file_simple

        for file_path in files[: self.MAX_ADHOC_FILES]:
            try:
                await index_file_simple(file_path, self._store)
            except Exception as exc:
                logger.warning("Ad-hoc index failed for %s: %s", file_path, exc)

    def _node_id_to_path(self, node_id: str) -> Path:
        """Extract file path from node ID."""
        parts = node_id.split(":", 2)
        if len(parts) >= 2:
            return Path(parts[1])
        return Path(node_id)

    def _discover_project_root(self) -> Path | None:
        if self.hub_db_path is None:
            return None
        return self.hub_db_path.parent.parent

    def _discover_db_path(self) -> Path | None:
        current = Path.cwd()
        for parent in [current] + list(current.parents):
            candidate = parent / ".remora" / HUB_DB_NAME
            if candidate.exists():
                return candidate
        return None


_hub_client: HubClient | None = None


def get_hub_client() -> HubClient:
    """Get the Hub client instance (lazy singleton)."""
    global _hub_client
    if _hub_client is None:
        _hub_client = HubClient()
    return _hub_client
