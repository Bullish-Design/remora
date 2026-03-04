"""File watcher sensor agent.

Watches a workspace directory for external file changes (created, modified,
deleted) and emits FileChanged events. Uses asyncio polling rather than
an external library like watchdog, keeping dependencies minimal.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from remora_demo.companion.models.events import FileChanged

logger = logging.getLogger(__name__)

# Default directory/file patterns to ignore
DEFAULT_IGNORE_PATTERNS: list[str] = [
    ".git",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".env",
    ".companion",
    ".devenv",
]


@dataclass
class FileWatcherConfig:
    """Configuration for file watcher sensor."""

    watch_path: Path = field(default_factory=Path.cwd)
    poll_interval_ms: int = 1000  # How often to poll for changes
    ignore_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS))


class FileWatcher:
    """File watcher sensor.

    Monitors a workspace directory for external file changes by periodically
    polling the filesystem and comparing snapshots. Emits FileChanged events
    for created, modified, and deleted files.

    Usage:
        watcher = FileWatcher(FileWatcherConfig(watch_path=Path("/project")))
        watcher.on_event(lambda e: print(f"File changed: {e}"))
        await watcher.start()
        ...
        await watcher.stop()
    """

    def __init__(self, config: FileWatcherConfig | None = None) -> None:
        self.config = config or FileWatcherConfig()
        self._event_handlers: list[callable] = []
        self._snapshot: dict[Path, float] | None = None
        self._poll_task: asyncio.Task | None = None
        self._running = False

    def on_event(self, handler: callable) -> None:
        """Register an event handler for FileChanged events."""
        self._event_handlers.append(handler)

    async def _emit(self, event: FileChanged) -> None:
        """Emit event to all registered handlers."""
        for handler in self._event_handlers:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result

    def _should_ignore(self, path: Path) -> bool:
        """Check if a path should be ignored based on configured patterns."""
        parts = path.parts
        for pattern in self.config.ignore_patterns:
            if pattern in parts:
                return True
        return False

    def _take_snapshot(self) -> dict[Path, float]:
        """Take a snapshot of all files under watch_path with their mtimes.

        Returns a dict mapping file path -> modification time.
        """
        snapshot: dict[Path, float] = {}
        watch = self.config.watch_path

        if not watch.is_dir():
            return snapshot

        try:
            for path in watch.rglob("*"):
                if not path.is_file():
                    continue
                if self._should_ignore(path):
                    continue
                try:
                    snapshot[path] = path.stat().st_mtime
                except OSError:
                    # File may have been deleted between rglob and stat
                    pass
        except OSError:
            logger.warning("Error scanning directory: %s", watch)

        return snapshot

    def _detect_changes(self) -> list[FileChanged]:
        """Compare current filesystem state to last snapshot and return changes."""
        if self._snapshot is None:
            return []

        current = self._take_snapshot()
        changes: list[FileChanged] = []

        # Detect created and modified files
        for path, mtime in current.items():
            if path not in self._snapshot:
                changes.append(FileChanged(path=str(path), kind="created"))
            elif mtime != self._snapshot[path]:
                changes.append(FileChanged(path=str(path), kind="modified"))

        # Detect deleted files
        for path in self._snapshot:
            if path not in current:
                changes.append(FileChanged(path=str(path), kind="deleted"))

        # Update snapshot to current state
        self._snapshot = current

        return changes

    async def start(self) -> None:
        """Start the file watcher."""
        if self._running:
            return

        self._snapshot = self._take_snapshot()
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("File watcher started watching: %s", self.config.watch_path)

    async def stop(self) -> None:
        """Stop the file watcher."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        logger.info("File watcher stopped")

    async def _poll_loop(self) -> None:
        """Background loop that polls for filesystem changes."""
        while self._running:
            try:
                await asyncio.sleep(self.config.poll_interval_ms / 1000)

                changes = self._detect_changes()
                for change in changes:
                    await self._emit(change)

            except asyncio.CancelledError:
                break
            except Exception:
                # Don't crash the loop on errors
                logger.exception("Error in file watcher poll loop")
