"""File watching with automatic re-analysis.

Provides ``RemoraFileWatcher``, a thin layer over ``watchfiles.awatch``
that adds extension filtering, debouncing, configurable ignore patterns,
and an async callback for triggering Remora analysis.

The ignore-pattern logic mirrors Cairn's ``FileWatcher.should_ignore``
so that behaviour stays consistent across Cairn-based tools.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from watchfiles import Change, awatch

from remora.constants import CACHE_DIR

logger = logging.getLogger(__name__)

# Map watchfiles Change enum → human-readable string
_CHANGE_TYPE_MAP: dict[Change, Literal["added", "modified", "deleted"]] = {
    Change.added: "added",
    Change.modified: "modified",
    Change.deleted: "deleted",
}

DEFAULT_IGNORE_PATTERNS: list[str] = [
    "__pycache__",
    ".git",
    ".jj",
    ".venv",
    "node_modules",
    CACHE_DIR,
    ".agentfs",
]


@dataclass(frozen=True, slots=True)
class FileChange:
    """A single file-system change detected by the watcher."""

    path: Path
    change_type: Literal["added", "modified", "deleted"]


class RemoraFileWatcher:
    """Watch for file changes and trigger Remora analysis.

    Features:
        - Extension filtering for configured suffixes.
        - Ignore patterns that skip matching directories.
        - Debounced change batches before callbacks fire.
        - Graceful stop via ``stop()`` or SIGINT.
    """

    def __init__(
        self,
        watch_paths: list[Path],
        on_changes: Callable[[list[FileChange]], Awaitable[Any]],
        *,
        extensions: set[str] | None = None,
        ignore_patterns: list[str] | None = None,
        debounce_ms: int = 500,
    ) -> None:
        self._watch_paths = [p.resolve() for p in watch_paths]
        self._on_changes = on_changes
        self._extensions = extensions if extensions is not None else {".py"}
        self._ignore_patterns = ignore_patterns if ignore_patterns is not None else list(DEFAULT_IGNORE_PATTERNS)
        self._debounce_s = debounce_ms / 1000.0
        self._stop_event = asyncio.Event()
        self._running = False

    # -- Public API ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start watching for changes until ``stop()`` is called."""
        self._running = True
        self._stop_event.clear()
        pending: list[FileChange] = []
        debounce_task: asyncio.Task[None] | None = None

        logger.info(
            "Watching %d path(s) for changes (extensions=%s, debounce=%dms)",
            len(self._watch_paths),
            self._extensions,
            int(self._debounce_s * 1000),
        )

        try:
            async for raw_changes in awatch(
                *self._watch_paths,
                stop_event=self._stop_event,
            ):
                if not self._running:
                    break

                # Filter and convert changes
                for change_type, path_str in raw_changes:
                    path = Path(path_str)
                    if self._should_ignore(path):
                        continue
                    if path.suffix not in self._extensions:
                        continue
                    mapped_type = _CHANGE_TYPE_MAP.get(change_type, "modified")
                    pending.append(FileChange(path=path, change_type=mapped_type))

                if not pending:
                    continue

                # Debounce: cancel any pending trigger task and start a new one
                if debounce_task is not None and not debounce_task.done():
                    debounce_task.cancel()

                async def _debounced_fire(batch: list[FileChange] = pending) -> None:
                    await asyncio.sleep(self._debounce_s)
                    if not batch:
                        return
                    changes_to_fire = list(batch)
                    batch.clear()
                    for change in changes_to_fire:
                        logger.debug("File %s: %s", change.change_type, change.path)
                    try:
                        await self._on_changes(changes_to_fire)
                    except Exception:
                        logger.exception(
                            "Error during analysis callback after %d file change(s)",
                            len(changes_to_fire),
                        )

                debounce_task = asyncio.create_task(_debounced_fire())
        finally:
            # Ensure pending debounce fires before exit
            if debounce_task is not None and not debounce_task.done():
                debounce_task.cancel()
            self._running = False

    def stop(self) -> None:
        """Signal the watcher to stop after the current iteration."""
        self._running = False
        self._stop_event.set()
        logger.info("File watcher stop requested.")

    # -- Internal -----------------------------------------------------------

    def _should_ignore(self, path: Path) -> bool:
        """Check whether *path* falls under an ignored directory.

        Mirrors the logic in ``cairn.watcher.FileWatcher.should_ignore``.
        """
        for watch_root in self._watch_paths:
            try:
                rel_parts = path.relative_to(watch_root).parts
            except ValueError:
                continue
            # If any path component matches an ignore pattern, skip it
            if any(part in self._ignore_patterns for part in rel_parts):
                return True
            return False  # Successfully resolved — not ignored

        # Path outside all watch roots
        return True
