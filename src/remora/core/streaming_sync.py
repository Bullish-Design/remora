"""Streaming file synchronization for large projects."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Set

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Statistics for sync operations."""

    files_synced: int = 0
    bytes_synced: int = 0
    files_skipped: int = 0
    errors: int = 0


@dataclass
class StreamingSyncManager:
    """Manages lazy/incremental file synchronization."""

    project_root: Path
    workspace: Any
    ignore_checker: Callable[[Path], bool]

    _synced_files: Set[str] = field(default_factory=set)
    _pending_syncs: dict[str, asyncio.Task] = field(default_factory=dict)
    _stats: SyncStats = field(default_factory=SyncStats)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def ensure_synced(self, rel_path: str) -> bool:
        """Ensure a specific file is synced to workspace."""
        if rel_path in self._synced_files:
            return True

        async with self._lock:
            if rel_path in self._synced_files:
                return True

            full_path = self.project_root / rel_path

            if not full_path.exists():
                logger.debug("File not found: %s", full_path)
                return False

            if full_path.is_dir():
                return False

            if self.ignore_checker(full_path):
                self._stats.files_skipped += 1
                return False

            try:
                content = await asyncio.to_thread(full_path.read_bytes)
                await self.workspace.files.write(rel_path, content, mode="binary")
                self._synced_files.add(rel_path)
                self._stats.files_synced += 1
                self._stats.bytes_synced += len(content)
                return True
            except Exception as exc:
                logger.warning("Failed to sync %s: %s", rel_path, exc)
                self._stats.errors += 1
                return False

    async def ensure_directory_synced(
        self,
        rel_dir: str,
        *,
        recursive: bool = True,
        max_files: int | None = None,
    ) -> int:
        """Sync all files in a directory."""
        full_dir = self.project_root / rel_dir
        if not full_dir.exists() or not full_dir.is_dir():
            return 0

        synced = 0
        pattern = "**/*" if recursive else "*"

        for path in full_dir.glob(pattern):
            if max_files is not None and synced >= max_files:
                break

            if path.is_file():
                try:
                    rel_path = str(path.relative_to(self.project_root))
                    if await self.ensure_synced(rel_path):
                        synced += 1
                except ValueError:
                    continue

        return synced

    async def sync_batch(
        self,
        paths: list[str],
        *,
        concurrency: int = 10,
    ) -> int:
        """Sync multiple files concurrently."""
        semaphore = asyncio.Semaphore(concurrency)

        async def sync_with_limit(path: str) -> bool:
            async with semaphore:
                return await self.ensure_synced(path)

        results = await asyncio.gather(
            *[sync_with_limit(p) for p in paths],
            return_exceptions=True,
        )

        return sum(1 for result in results if result is True)

    def is_synced(self, rel_path: str) -> bool:
        """Check if a file has been synced."""
        return rel_path in self._synced_files

    def get_stats(self) -> SyncStats:
        """Get synchronization statistics."""
        return self._stats

    def clear(self) -> None:
        """Clear sync state (for testing)."""
        self._synced_files.clear()
        self._stats = SyncStats()


class FileWatcher:
    """Watch for file changes and sync incrementally."""

    def __init__(
        self,
        sync_manager: StreamingSyncManager,
        *,
        debounce_ms: int = 100,
    ):
        self._sync = sync_manager
        self._debounce_ms = debounce_ms
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start watching for changes."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        """Stop watching for changes."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _watch_loop(self) -> None:
        """Main watch loop."""
        try:
            import watchfiles
        except ImportError:
            logger.warning("watchfiles not installed - file watching disabled")
            return

        try:
            async for changes in watchfiles.awatch(
                self._sync.project_root,
                debounce=self._debounce_ms,
            ):
                if not self._running:
                    break

                for change_type, path_str in changes:
                    try:
                        path = Path(path_str)
                        rel_path = str(path.relative_to(self._sync.project_root))

                        if change_type in (watchfiles.Change.added, watchfiles.Change.modified):
                            await self._sync.ensure_synced(rel_path)
                        elif change_type == watchfiles.Change.deleted:
                            pass
                    except ValueError:
                        continue
                    except Exception as exc:
                        logger.debug("Watch error for %s: %s", path_str, exc)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("File watcher error: %s", exc)


__all__ = ["FileWatcher", "StreamingSyncManager", "SyncStats"]
