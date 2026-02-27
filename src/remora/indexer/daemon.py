"""Indexer daemon implementation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fsdantic import Fsdantic, Workspace
from watchfiles import Change, awatch

from remora.indexer.models import FileIndex, NodeState
from remora.indexer.rules import ActionContext, ExtractSignatures, RulesEngine
from remora.indexer.scanner import scan_file_simple
from remora.indexer.store import NodeStateStore

logger = logging.getLogger(__name__)

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


@dataclass
class IndexerConfig:
    """Configuration for the indexer daemon."""

    watch_paths: list[str] = field(default_factory=lambda: ["src/"])
    store_path: str = ".remora/indexer.db"
    max_workers: int = 8
    enable_cross_file_analysis: bool = True


class IndexerDaemon:
    """Background indexer that watches files and updates the index.

    Responsibilities:
    - Watch filesystem for Python file changes
    - Index files on cold start
    - Update NodeState records
    """

    def __init__(
        self,
        config: IndexerConfig,
        store: NodeStateStore | None = None,
        grail_executor: Any = None,
    ) -> None:
        """Initialize the daemon.

        Args:
            config: Indexer configuration
            store: Pre-initialized store (optional)
            grail_executor: Grail script executor (optional)
        """
        self.config = config
        self.store = store
        self.executor = grail_executor

        self.workspace: Workspace | None = None
        self.rules = RulesEngine()
        self.project_root = Path.cwd()

        self._shutdown_event = asyncio.Event()
        self._started_at: datetime | None = None

        self.max_workers = config.max_workers
        self._change_queue: asyncio.Queue[tuple[str, Path]] | None = None
        self._change_workers: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start the indexer daemon."""
        logger.info("Starting indexer daemon")

        self._change_queue = asyncio.Queue(maxsize=1000)

        store_path = self.project_root / self.config.store_path
        store_path.parent.mkdir(parents=True, exist_ok=True)

        if self.store is None:
            self.workspace = await Fsdantic.open(path=str(store_path))
            self.store = NodeStateStore(self.workspace)

        self._setup_signals()

        self._started_at = datetime.now(timezone.utc)

        try:
            await self._cold_start_index()

            if self._shutdown_event.is_set():
                return

            await self._start_change_workers()

            watch_paths = [self.project_root / p for p in self.config.watch_paths]

            logger.info("Indexer daemon ready, watching: %s", watch_paths)

            await self._watch_files(watch_paths)
        finally:
            self._shutdown_event.set()
            await self._stop_change_workers()
            await self._close_workspace()
            logger.info("Indexer daemon stopped")

    async def _watch_files(self, watch_paths: list[Path]) -> None:
        """Watch filesystem for changes."""
        async for changes in awatch(
            *watch_paths,
            stop_event=self._shutdown_event,
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

                logger.debug("File change: %s %s", change, path)

                if self._change_queue and not self._change_queue.full():
                    await self._change_queue.put((change, path))

    async def _start_change_workers(self) -> None:
        """Start workers to process file changes concurrently."""
        for i in range(self.max_workers):
            task = asyncio.create_task(self._change_worker(i))
            self._change_workers.append(task)
        logger.info("Started %d change workers", self.max_workers)

    async def _change_worker(self, worker_id: int) -> None:
        """Worker coroutine that processes file changes from queue."""
        logger.debug("Change worker %d started", worker_id)

        while not self._shutdown_event.is_set():
            try:
                change_type, path = await asyncio.wait_for(self._change_queue.get(), timeout=1.0)
                await self._handle_file_change(change_type, path)

            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.exception("Error in change worker %d", worker_id)

        logger.debug("Change worker %d stopped", worker_id)

    async def _stop_change_workers(self) -> None:
        """Stop all change workers."""
        if not self._change_workers:
            return
        for task in self._change_workers:
            task.cancel()
        await asyncio.gather(*self._change_workers, return_exceptions=True)
        self._change_workers.clear()

    async def _handle_file_change(self, change_type: str, path: Path) -> None:
        """Process a file change."""
        store = self.store
        if store is None:
            return

        logger.debug("Processing %s: %s", change_type, path)

        if change_type == "deleted":
            await store.invalidate_file(str(path))
            logger.info("Deleted nodes for: %s", path)
            return

        actions = self.rules.get_actions(change_type, path)

        context = ActionContext(
            store=store,
            grail_executor=self.executor,
            project_root=self.project_root,
        )

        for action in actions:
            try:
                result = await action.execute(context)
                if isinstance(action, ExtractSignatures) and "nodes" in result:
                    await self._process_extraction_result(path, result)
            except Exception as exc:
                logger.exception("Action failed for %s", path)

    async def _process_extraction_result(
        self,
        path: Path,
        result: dict[str, Any],
    ) -> None:
        """Process extraction results and store nodes."""
        store = self.store
        if store is None:
            return

        file_hash = result.get("file_hash", "")
        nodes = result.get("nodes", [])

        await store.invalidate_file(str(path))

        now = datetime.now(timezone.utc)
        for node_data in nodes:
            node_key = f"node:{path}:{node_data['name']}"

            state = NodeState(
                key=node_key,
                file_path=str(path),
                node_name=node_data["name"],
                node_type=node_data["type"],
                source_hash=node_data.get("source_hash", ""),
                file_hash=file_hash,
                signature=node_data.get("signature"),
                docstring=node_data.get("docstring"),
                decorators=node_data.get("decorators", []),
                imports=node_data.get("imports", []),
                line_count=node_data.get("line_count"),
                has_type_hints=node_data.get("has_type_hints", False),
                update_source="file_change",
            )
            await store.set(state)

        await store.set_file_index(
            FileIndex(
                file_path=str(path),
                file_hash=file_hash,
                node_count=len(nodes),
                last_scanned=now,
            )
        )

        logger.debug("Indexed %s: %d nodes", path, len(nodes))

    async def _cold_start_index(self) -> None:
        """Index files that changed since last shutdown."""
        store = self.store
        if store is None:
            return

        logger.info("Cold start: scanning for changed files...")

        files = []
        for py_file in self.project_root.rglob("*.py"):
            if self._shutdown_event.is_set():
                break

            if not self.rules.should_process_file(py_file, DEFAULT_IGNORE_PATTERNS):
                continue
            files.append(py_file)

        files_to_index = []
        for f in files:
            if self._shutdown_event.is_set():
                break
            file_hash = self._hash_file(f)
            existing = await store.get_file_index(str(f))
            if not existing or existing.file_hash != file_hash:
                files_to_index.append(f)

        logger.info("Found %d files to index (out of %d total)", len(files_to_index), len(files))

        if files_to_index and not self._shutdown_event.is_set():
            indexed, errors = await self._index_files_parallel(files_to_index)
        else:
            indexed, errors = 0, 0

        stats = await store.stats()
        logger.info(
            "Cold start complete: indexed %d files, %d errors",
            indexed,
            errors,
        )

    async def _index_files_parallel(
        self,
        files: list[Path],
    ) -> tuple[int, int]:
        """Index multiple files in parallel."""
        store = self.store
        if store is None:
            return 0, len(files)

        semaphore = asyncio.Semaphore(self.max_workers)

        async def process_file_with_limit(path: Path) -> tuple[Path, int, float, Exception | None]:
            async with semaphore:
                start = time.monotonic()
                try:
                    count = await scan_file_simple(path, store)
                except Exception as e:
                    logger.exception("Error indexing %s", path)
                    return (path, 0, 0.0, e)
                duration = time.monotonic() - start
                return (path, count, duration, None)

        indexed = 0
        errors = 0

        progress = self._progress_bar(len(files)) if files else None
        tasks = [asyncio.create_task(process_file_with_limit(f)) for f in files]

        try:
            for task in asyncio.as_completed(tasks):
                if self._shutdown_event.is_set():
                    for pending in tasks:
                        if not pending.done():
                            pending.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    break
                path, count, duration, error = await task
                if error is not None:
                    errors += 1
                else:
                    indexed += 1
                    logger.debug("Indexed %s: %d nodes in %.2fs", path, count, duration)
                if progress:
                    progress.update(1)
        finally:
            if progress:
                progress.close()

        return indexed, errors

    @staticmethod
    def _progress_bar(total: int) -> Any | None:
        try:
            from tqdm import tqdm
        except Exception:
            return None
        return tqdm(total=total, desc="Indexing", unit="file")

    def _should_process(self, path: Path) -> bool:
        """Check if a file should be processed."""
        if path.suffix != ".py":
            return False

        try:
            rel_parts = path.relative_to(Path.cwd()).parts
        except ValueError:
            return False

        for pattern in DEFAULT_IGNORE_PATTERNS:
            if pattern in rel_parts:
                return False
            if pattern.startswith("*") and path.name.endswith(pattern[1:]):
                return False

        if any(part.startswith(".") for part in rel_parts):
            return False

        return True

    def _setup_signals(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(self._shutdown()),
            )

    async def _shutdown(self) -> None:
        """Clean shutdown."""
        logger.info("Indexer daemon shutting down")
        self._shutdown_event.set()

    async def _close_workspace(self) -> None:
        """Close the workspace if open."""
        if self.workspace:
            await self.workspace.close()

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Compute SHA256 hash of file contents."""
        try:
            content = path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except OSError:
            return ""
