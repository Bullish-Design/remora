"""Hub daemon implementation.

The main daemon that coordinates watching, indexing, and serving.
Runs as a background process, communicating via shared workspace.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fsdantic import Fsdantic, Workspace

from remora.hub.models import FileIndex, HubStatus, NodeState
from remora.hub.rules import ActionContext, ExtractSignatures, RulesEngine
from remora.hub.store import NodeStateStore
from remora.hub.watcher import HubWatcher

logger = logging.getLogger(__name__)


class HubDaemon:
    """The Node State Hub background daemon.

    Responsibilities:
    - Watch filesystem for Python file changes
    - Index files on cold start
    - Update NodeState records via Grail scripts
    - Maintain status for client health checks
    """

    def __init__(
        self,
        project_root: Path,
        db_path: Path | None = None,
        grail_executor: Any = None,
    ) -> None:
        """Initialize the daemon.

        Args:
            project_root: Root directory to watch
            db_path: Path to hub.db (default: {project_root}/.remora/hub.db)
            grail_executor: Grail script executor (optional)
        """
        self.project_root = project_root.resolve()
        self.db_path = db_path or (self.project_root / ".remora" / "hub.db")
        self.grail_executor = grail_executor

        self.workspace: Workspace | None = None
        self.store: NodeStateStore | None = None
        self.watcher: HubWatcher | None = None
        self.rules = RulesEngine()

        self._shutdown_event = asyncio.Event()
        self._started_at: datetime | None = None

    async def run(self) -> None:
        """Main daemon loop.

        Blocks until shutdown signal received.
        """
        logger.info("Hub daemon starting for %s", self.project_root)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.workspace = await Fsdantic.open(path=str(self.db_path))
        self.store = NodeStateStore(self.workspace)

        self._write_pid_file()
        self._setup_signals()

        self._started_at = datetime.now(timezone.utc)
        await self._update_status(running=True)

        try:
            await self._cold_start_index()

            self.watcher = HubWatcher(
                self.project_root,
                self._handle_file_change,
            )

            logger.info("Hub daemon ready, watching for changes")
            await self.watcher.start()

        except asyncio.CancelledError:
            logger.info("Hub daemon received shutdown signal")
        finally:
            await self._shutdown()

    async def _cold_start_index(self) -> None:
        """Index files that changed since last shutdown."""
        store = self.store
        if store is None:
            return

        logger.info("Cold start: checking for changed files...")

        indexed = 0
        errors = 0

        for py_file in self.project_root.rglob("*.py"):
            if not self.rules.should_process_file(
                py_file, HubWatcher.DEFAULT_IGNORE_PATTERNS
            ):
                continue

            try:
                file_hash = self._hash_file(py_file)
                existing = await store.get_file_index(str(py_file))

                if existing and existing.file_hash == file_hash:
                    continue

                await self._index_file(py_file, "cold_start")
                indexed += 1

            except Exception as exc:
                logger.exception("Failed to index %s", py_file)
                errors += 1

        stats = await store.stats()
        await self._update_status(
            running=True,
            indexed_files=stats["files"],
            indexed_nodes=stats["nodes"],
        )

        logger.info(
            "Cold start complete: indexed %s files, %s errors",
            indexed,
            errors,
        )

    async def _handle_file_change(self, change_type: str, path: Path) -> None:
        """Handle a file change event from watcher.

        Args:
            change_type: "added", "modified", or "deleted"
            path: Absolute path to changed file
        """
        store = self.store
        if store is None:
            return

        logger.debug("Processing %s: %s", change_type, path)

        actions = self.rules.get_actions(change_type, path)

        context = ActionContext(
            store=store,
            grail_executor=self.grail_executor,
            project_root=self.project_root,
        )

        for action in actions:
            try:
                result = await action.execute(context)

                if isinstance(action, ExtractSignatures) and "nodes" in result:
                    await self._process_extraction_result(
                        path,
                        result,
                        update_source="file_change",
                    )

            except Exception as exc:
                logger.exception("Action failed for %s", path)

        await self._update_status(running=True)

    async def _index_file(
        self,
        path: Path,
        update_source: Literal["file_change", "cold_start", "manual", "adhoc"],
    ) -> None:
        """Index a single file.

        Args:
            path: Path to Python file
            update_source: Source of update ("cold_start", "file_change", etc.)
        """
        store = self.store
        if store is None:
            return

        context = ActionContext(
            store=store,
            grail_executor=self.grail_executor,
            project_root=self.project_root,
        )

        action = ExtractSignatures(path)
        result = await action.execute(context)

        if result.get("error"):
            logger.warning("Extraction failed for %s: %s", path, result["error"])
            return

        await self._process_extraction_result(path, result, update_source)

    async def _process_extraction_result(
        self,
        path: Path,
        result: dict[str, Any],
        update_source: Literal["file_change", "cold_start", "manual", "adhoc"],
    ) -> None:
        """Process extraction results and store nodes.

        Args:
            path: Source file path
            result: Output from extract_signatures script
            update_source: Source of update
        """
        store = self.store
        if store is None:
            return

        file_hash = result["file_hash"]
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
                source_hash=node_data["source_hash"],
                file_hash=file_hash,
                signature=node_data.get("signature"),
                docstring=node_data.get("docstring"),
                decorators=node_data.get("decorators", []),
                line_count=node_data.get("line_count"),
                has_type_hints=node_data.get("has_type_hints", False),
                update_source=update_source,
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

        logger.debug(
            "Indexed %s: %s nodes",
            path,
            len(nodes),
        )

    async def _update_status(
        self,
        running: bool,
        indexed_files: int | None = None,
        indexed_nodes: int | None = None,
    ) -> None:
        """Update Hub status record."""
        store = self.store
        if store is None:
            return

        existing = await store.get_status()

        status = HubStatus(
            running=running,
            pid=os.getpid(),
            project_root=str(self.project_root),
            indexed_files=indexed_files
            if indexed_files is not None
            else (existing.indexed_files if existing else 0),
            indexed_nodes=indexed_nodes
            if indexed_nodes is not None
            else (existing.indexed_nodes if existing else 0),
            started_at=self._started_at,
            last_update=datetime.now(timezone.utc),
            version=existing.version if existing else 1,
        )

        await store.set_status(status)

    async def _shutdown(self) -> None:
        """Clean shutdown."""
        logger.info("Hub daemon shutting down")

        if self.watcher:
            self.watcher.stop()

        if self.store:
            await self._update_status(running=False)

        if self.workspace:
            await self.workspace.close()

        self._remove_pid_file()

        logger.info("Hub daemon stopped")

    def _setup_signals(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(self._signal_handler()),
            )

    async def _signal_handler(self) -> None:
        """Handle shutdown signal."""
        logger.info("Received shutdown signal")
        if self.watcher:
            self.watcher.stop()

    def _write_pid_file(self) -> None:
        """Write PID file for daemon detection."""
        pid_file = self.db_path.parent / "hub.pid"
        pid_file.write_text(str(os.getpid()))
        logger.debug("Wrote PID file: %s", pid_file)

    def _remove_pid_file(self) -> None:
        """Remove PID file on shutdown."""
        pid_file = self.db_path.parent / "hub.pid"
        if pid_file.exists():
            pid_file.unlink()
            logger.debug("Removed PID file: %s", pid_file)

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Compute SHA256 hash of file contents."""
        try:
            content = path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except OSError:
            return ""
