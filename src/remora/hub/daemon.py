"""Hub daemon implementation.

The main daemon that coordinates watching, indexing, and serving.
Runs as a background process, communicating via shared workspace.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import json
import signal
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fsdantic import Fsdantic, Workspace

from remora.constants import HUB_DB_NAME
from remora.context.hub_client import HubClient
from remora.errors import HubError
from remora.hub.metrics import get_metrics
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
        standalone: bool = True,
    ) -> None:
        """Initialize the daemon.

        Args:
            project_root: Root directory to watch
            db_path: Path to {HUB_DB_NAME} (default: {{project_root}}/.remora/{HUB_DB_NAME})
            grail_executor: Grail script executor (optional)
        """
        self.project_root = project_root.resolve()
        self.db_path = db_path or (self.project_root / ".remora" / HUB_DB_NAME)
        self.executor = grail_executor # Renamed from grail_executor to executor

        self._metrics = get_metrics()

        self.workspace: Workspace | None = None
        self.store: NodeStateStore | None = None
        self.watcher: HubWatcher | None = None
        self.rules = RulesEngine()
        self.standalone = standalone

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

        if self.standalone:
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

        from remora.config import load_config
        config = load_config(self.project_root / "remora.yaml")
        enable_cross_file_analysis = config.hub.enable_cross_file_analysis

        logger.info("Cold start: checking for changed files...")
        self._metrics.start_timer("cold_start")

        indexed = 0
        errors = 0

        for py_file in self.project_root.rglob("*.py"):
            if not self.rules.should_process_file(
                py_file, HubWatcher.DEFAULT_IGNORE_PATTERNS
            ):
                continue

            self._metrics.start_timer(f"index:{py_file}")
            try:
                file_hash = self._hash_file(py_file)
                existing = await store.get_file_index(str(py_file))

                if existing and existing.file_hash == file_hash:
                    # File unchanged
                    self._metrics.stop_timer(f"index:{py_file}")
                    continue

                await self._index_file(py_file, "cold_start")
                indexed += 1

            except Exception as exc:
                logger.exception("Failed to index %s", py_file)
                self._metrics.stop_timer(f"index:{py_file}")
                self._metrics.record_file_failed()
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

        if enable_cross_file_analysis:
            from remora.hub.call_graph import update_call_graph
            from remora.hub.test_discovery import update_test_relationships
            
            logger.info("Running cross-file call graph analysis...")
            updated = await update_call_graph(store, self.project_root)
            logger.info("Call graph analysis complete: %s nodes updated", updated)
            
            logger.info("Running test discovery...")
            test_updated = await update_test_relationships(store, self.project_root)
            logger.info("Test discovery complete: %s nodes updated", test_updated)
            
        self._metrics.cold_start_duration = self._metrics.stop_timer("cold_start")

    async def _handle_file_change(self, change_type: str, path: Path) -> None:
        """Handle a file change event from watcher.
        
        Args:
            change_type: Type of change (e.g., "modified", "deleted")
            path: Path to the changed file
        """
        self._metrics.record_file_change()
        store = self.store
        if store is None:
            return

        from remora.config import load_config
        config = load_config(self.project_root / "remora.yaml")
        enable_cross_file_analysis = config.hub.enable_cross_file_analysis

        logger.debug("Processing %s: %s", change_type, path)

        actions = self.rules.get_actions(change_type, path)

        context = ActionContext(
            store=store,
            grail_executor=self.executor, # Use self.executor
            project_root=self.project_root,
        )

        self._metrics.start_timer(f"index:{path}")
        try:
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
            
            # Metrics for successful file change processing
            duration = self._metrics.stop_timer(f"index:{path}")
            # Node count is recorded in _process_extraction_result, so just record duration here if no nodes were extracted
            # or if it's a delete operation.
            # For now, we'll assume _process_extraction_result handles the node count metric.
            # If no nodes were extracted, this timer will still be stopped.
        except Exception as e:
            logger.error("Error processing file change for %s: %s", path, e)
            self._metrics.stop_timer(f"index:{path}")
            self._metrics.record_file_failed()


        if enable_cross_file_analysis:
            from remora.hub.call_graph import update_call_graph
            from remora.hub.test_discovery import update_test_relationships
            
            logger.debug("Incremental call graph analysis triggered by %s", path)
            await update_call_graph(store, self.project_root)
            
            logger.debug("Incremental test discovery triggered by %s", path)
            await update_test_relationships(store, self.project_root)

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
            grail_executor=self.executor, # Use self.executor
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
        node_states = {} # To store NodeState objects for cleanup and metrics

        await store.invalidate_file(str(path))

        from remora.hub.imports import extract_node_imports

        now = datetime.now(timezone.utc)
        for node_data in nodes:
            node_key = f"node:{path}:{node_data['name']}"
            
            imports = extract_node_imports(path, node_data["name"])

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
                imports=imports,
                line_count=node_data.get("line_count"),
                has_type_hints=node_data.get("has_type_hints", False),
                update_source=update_source,
            )
            node_states[node_key] = state
            await store.set(state)

        await store.set_file_index(
            FileIndex(
                file_path=str(path),
                file_hash=file_hash,
                node_count=len(nodes),
                last_scanned=now,
            )
        )

        # Cleanup old indices
        await self._cleanup_old_indices(str(path), file_hash, list(node_states.keys()))
        
        # Record metrics
        nodes_count = len(node_states)
        duration = self._metrics.stop_timer(f"index:{path}")
        self._metrics.record_file_indexed(nodes_count, duration)
        self._log_index_event(path, nodes_count, duration, success=True)

        logger.debug(
            "Indexed %s: %s nodes",
            path,
            len(nodes),
        )

    def _log_index_event(
        self,
        file_path: Path,
        nodes: int,
        duration: float,
        success: bool,
    ) -> None:
        """Emit structured log for indexing events."""
        event = {
            "event": "file_indexed",
            "file": str(file_path),
            "nodes": nodes,
            "duration_ms": round(duration * 1000, 2),
            "success": success,
        }
        logger.info(json.dumps(event))

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

        if self.standalone:
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
