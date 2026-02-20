"""File watcher for the Hub daemon.

Uses watchfiles library for efficient filesystem monitoring.
Follows the pattern established by Cairn's FileWatcher.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable

from watchfiles import Change, awatch

logger = logging.getLogger(__name__)


class HubWatcher:
    """Watches a directory for Python file changes.

    Calls the provided callback when relevant files change.
    Filters out ignored directories and non-Python files.
    """

    DEFAULT_IGNORE_PATTERNS = [
        ".git",
        ".jj",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".pytest_cache",
        ".mypy_cache",
        "build",
        "dist",
        ".eggs",
        "*.egg-info",
        ".remora",
    ]

    def __init__(
        self,
        root: Path,
        callback: Callable[[str, Path], Awaitable[None]],
        ignore_patterns: list[str] | None = None,
    ) -> None:
        """Initialize the watcher.

        Args:
            root: Directory to watch (recursively)
            callback: Async function called with (change_type, path)
            ignore_patterns: Patterns to ignore (defaults to DEFAULT_IGNORE_PATTERNS)
        """
        self.root = root.resolve()
        self.callback = callback
        self.ignore_patterns = ignore_patterns or self.DEFAULT_IGNORE_PATTERNS
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start watching for changes.

        Blocks until stop() is called or an error occurs.
        """
        logger.info("Starting file watcher on %s", self.root)

        async for changes in awatch(
            self.root,
            stop_event=self._stop_event,
            recursive=True,
        ):
            for change_type, path_str in changes:
                path = Path(path_str)

                if not self._should_process(path):
                    continue

                change_map = {
                    Change.added: "added",
                    Change.modified: "modified",
                    Change.deleted: "deleted",
                }
                change = change_map.get(change_type, "modified")

                logger.debug(
                    "File change detected",
                    extra={"change": change, "path": str(path)},
                )

                try:
                    await self.callback(change, path)
                except Exception as exc:
                    logger.error(
                        "Error processing file change: %s",
                        exc,
                        extra={"path": str(path), "change": change},
                        exc_info=True,
                    )

    def stop(self) -> None:
        """Stop watching."""
        logger.info("Stopping file watcher")
        self._stop_event.set()

    def _should_process(self, path: Path) -> bool:
        """Check if a file should be processed.

        Args:
            path: Absolute path to the file

        Returns:
            True if the file should trigger an update
        """
        if path.suffix != ".py":
            return False

        try:
            rel_parts = path.relative_to(self.root).parts
        except ValueError:
            return False

        for pattern in self.ignore_patterns:
            if pattern in rel_parts:
                return False
            if pattern.startswith("*") and path.name.endswith(pattern[1:]):
                return False

        if any(part.startswith(".") for part in rel_parts):
            return False

        return True
