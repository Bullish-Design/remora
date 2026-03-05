# src/remora/lsp/__main__.py
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time

from lsprotocol import types as lsp


def _setup_logging() -> logging.Logger:
    """Configure logging to stderr AND a timestamped file in .remora/logs/."""
    from datetime import datetime
    from pathlib import Path

    # Stderr handler (stdout is reserved for LSP protocol)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    # File handler — new log file per session
    log_dir = Path(".remora/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = log_dir / f"server-{stamp}.log"
    file_handler = logging.FileHandler(str(log_file), mode="w", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s (%(filename)s:%(lineno)d): %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    file_handler.setLevel(logging.DEBUG)

    root = logging.getLogger("remora")
    root.addHandler(stderr_handler)
    root.addHandler(file_handler)
    root.setLevel(logging.DEBUG)

    # Quiet down pygls internals unless needed
    logging.getLogger("pygls").setLevel(logging.WARNING)

    startup_log = logging.getLogger("remora.lsp.startup")
    startup_log.info("=== Remora LSP session started — logging to %s ===", log_file)
    return startup_log


def _get_server():
    """Import and return the LSP server singleton (extracted for testability)."""
    from remora.lsp.server import server

    return server


def main(
    event_store=None,
    subscriptions=None,
) -> None:
    """Start the Remora LSP server with agent runner."""
    t0 = time.monotonic()
    log = _setup_logging()
    log.info("remora-lsp starting (pid=%d)", __import__("os").getpid())

    log.debug("Loading configuration ...")
    from remora.core.config import load_config

    config = load_config()
    log.info("Config loaded: model=%s base_url=%s", config.model_default, config.model_base_url)

    log.debug("Importing remora.lsp.server ...")
    server = _get_server()

    log.debug("Server module loaded (handlers registered) in %.1fms", (time.monotonic() - t0) * 1000)

    log.debug("Importing remora.lsp.runner ...")
    from remora.lsp.runner import AgentRunner

    log.debug("Runner module loaded in %.1fms", (time.monotonic() - t0) * 1000)

    server.event_store = event_store
    # Reset the asyncio.Lock so it binds to THIS event loop (pygls)
    if event_store is not None:
        event_store._lock = asyncio.Lock()
    server.subscriptions = subscriptions

    log.debug("Creating AgentRunner ...")
    runner = AgentRunner(server=server, config=config)
    server.runner = runner
    log.debug("AgentRunner created")

    @server.feature(lsp.INITIALIZED)
    async def _on_initialized(params: lsp.InitializedParams) -> None:
        log.info(
            "=== INITIALIZED received — startup took %.0fms ===",
            (time.monotonic() - t0) * 1000,
        )
        log.info("Workspace root_uri: %s", getattr(server.workspace, "root_uri", "NOT SET"))
        log.info("Workspace root_path: %s", getattr(server.workspace, "root_path", "NOT SET"))
        log.info("Starting agent runner loop...")
        asyncio.ensure_future(runner.run_forever())
        # Wire subscription-based triggers into the runner so the reactive
        # loop is fully closed: event → EventStore → subscription matching
        # → trigger queue → AgentRunner (Gap #1 closure)
        if server.event_store is not None:
            try:
                # Opportunistically compact carried-over WAL work from prior sessions.
                await server.event_store.checkpoint_wal("PASSIVE")
            except Exception:
                log.warning("startup checkpoint failed", exc_info=True)
            log.info("Starting EventStore trigger bridge...")
            asyncio.ensure_future(runner.run_from_event_store(server.event_store))
        log.info("Starting background workspace scan...")
        asyncio.ensure_future(_background_scan())

    async def _background_scan() -> None:
        """Walk workspace for *.py files, parse each, and populate the DB.

        The scan runs with a brief delay between files to reduce SQLite write
        contention with user operations (chat, panel queries).  SQLite only
        allows one writer at a time, so continuous batch_append calls would
        block emit_event operations.
        """
        from pathlib import Path

        from pygls.uris import from_fs_path

        # Brief initial delay to let user operations proceed first
        await asyncio.sleep(0.5)

        log.info("_background_scan: starting")
        root = server.workspace.root_path
        log.info("_background_scan: root_path = %r", root)
        if not root:
            log.warning("_background_scan: No workspace root — skipping")
            return

        root_path = Path(root)
        if not root_path.exists():
            log.error("_background_scan: root_path %s does not exist!", root_path)
            return

        _SKIP_DIRS = frozenset(
            {
                "__pycache__",
                "node_modules",
                ".venv",
                "venv",
                ".devenv",
                ".git",
                ".tox",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                ".nox",
                "dist",
                "build",
                ".eggs",
            }
        )

        _SUPPORTED_SUFFIXES = frozenset({".py", ".md", ".toml"})
        manifest_path = root_path / ".remora" / "scan-manifest.json"
        manifest_save_interval = 10

        def _load_manifest() -> dict[str, dict[str, int]]:
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {
                        str(path): {"mtime_ns": int(sig["mtime_ns"]), "size": int(sig["size"])}
                        for path, sig in data.items()
                        if isinstance(sig, dict) and "mtime_ns" in sig and "size" in sig
                    }
            except FileNotFoundError:
                return {}
            except Exception:
                log.warning("_background_scan: failed to load scan manifest %s", manifest_path, exc_info=True)
            return {}

        def _save_manifest_atomic(data: dict[str, dict[str, int]]) -> None:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = manifest_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
            tmp_path.replace(manifest_path)

        def _save_manifest(data: dict[str, dict[str, int]]) -> None:
            _save_manifest_atomic(data)

        def _iter_source_files(root: Path):
            """Walk root, pruning skip-dirs early to avoid descending into venvs."""
            for entry in sorted(root.iterdir()):
                if entry.is_dir():
                    if entry.name in _SKIP_DIRS or entry.name.startswith("."):
                        continue
                    yield from _iter_source_files(entry)
                elif entry.is_file() and entry.suffix in _SUPPORTED_SUFFIXES:
                    yield entry

        py_files = list(_iter_source_files(root_path))
        log.info("_background_scan: found %d source files in %s (skip-dirs pruned)", len(py_files), root)

        scan_pause_window_seconds = 5.0
        scan_pause_sleep_seconds = 0.1
        scan_append_slow_warning_seconds = 1.5
        scan_append_chunk_size = 8
        scan_update_edges_timeout_seconds = 1.0

        async def _pause_for_user_activity() -> None:
            nonlocal scan_pauses
            while server.user_recently_active(window_seconds=scan_pause_window_seconds):
                scan_pauses += 1
                await asyncio.sleep(scan_pause_sleep_seconds)

        existing_manifest = _load_manifest()
        next_manifest: dict[str, dict[str, int]] = {}
        count = 0
        parsed = 0
        skipped_unchanged = 0
        scan_pauses = 0
        files_since_last_manifest_save = 0

        def _maybe_save_manifest_incremental() -> None:
            nonlocal files_since_last_manifest_save
            if files_since_last_manifest_save < manifest_save_interval:
                return
            _save_manifest(next_manifest)
            files_since_last_manifest_save = 0

        for fpath in py_files:
            try:
                relative = str(fpath.relative_to(root_path))
                stat = fpath.stat()
                signature = {"mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
                next_manifest[relative] = signature
                if existing_manifest.get(relative) == signature:
                    skipped_unchanged += 1
                    files_since_last_manifest_save += 1
                    _maybe_save_manifest_incremental()
                    continue

                await _pause_for_user_activity()

                text = fpath.read_text(encoding="utf-8", errors="replace")
                uri = from_fs_path(str(fpath))
                # Get existing nodes from EventStore to preserve IDs
                old_nodes = []
                if server.event_store:
                    existing = await server.event_store.list_nodes(file_path=uri)
                    old_nodes = [
                        {
                            "node_id": n.node_id,
                            "name": n.name,
                            "node_type": n.node_type,
                            "start_line": n.start_line,
                            "end_line": n.end_line,
                            "source_hash": n.source_hash,
                        }
                        for n in existing
                    ]
                nodes = server.watcher.parse_and_inject_ids(uri, text, old_nodes)
                # Emit events to EventStore (batched per file for efficiency)
                if server.event_store:
                    from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent

                    old_ids = {n["node_id"] for n in old_nodes}
                    new_ids = {n["node_id"] for n in nodes}

                    # Batch all events for this file
                    batch_events = []
                    for node_dict in nodes:
                        batch_events.append(
                            NodeDiscoveredEvent(
                                node_id=node_dict["node_id"],
                                node_type=node_dict["node_type"],
                                name=node_dict["name"],
                                full_name=node_dict.get("full_name", node_dict["name"]),
                                file_path=node_dict["file_path"],
                                start_line=node_dict["start_line"],
                                end_line=node_dict["end_line"],
                                source_code=node_dict["source_code"],
                                source_hash=node_dict["source_hash"],
                                parent_id=node_dict.get("parent_id"),
                                start_byte=node_dict.get("start_byte", 0),
                                end_byte=node_dict.get("end_byte", 0),
                            )
                        )
                    for removed_id in old_ids - new_ids:
                        batch_events.append(
                            NodeRemovedEvent(node_id=removed_id, file_path=uri)
                        )

                    # Append events in small chunks so user-triggered operations
                    # can preempt scan writes quickly.
                    if batch_events:
                        timed_out = False
                        for idx in range(0, len(batch_events), scan_append_chunk_size):
                            chunk = batch_events[idx : idx + scan_append_chunk_size]
                            await _pause_for_user_activity()
                            append_start = time.monotonic()
                            try:
                                await server.event_store.batch_append("lsp", chunk)
                            except Exception:
                                log.warning(
                                    "_background_scan: failed to batch append chunk file=%s chunk_start=%d chunk_size=%d",
                                    fpath,
                                    idx,
                                    len(chunk),
                                    exc_info=True,
                                )
                                timed_out = True
                                break
                            append_duration_ms = (time.monotonic() - append_start) * 1000
                            if append_duration_ms > scan_append_slow_warning_seconds * 1000:
                                log.warning(
                                    "_background_scan: batch_append SLOW file=%s chunk_start=%d chunk_size=%d duration_ms=%.1f warn_threshold_s=%.1f",
                                    fpath,
                                    idx,
                                    len(chunk),
                                    append_duration_ms,
                                    scan_append_slow_warning_seconds,
                                )
                            await asyncio.sleep(0.05)
                        if timed_out:
                            continue
                await _pause_for_user_activity()
                try:
                    await asyncio.wait_for(
                        server.db.update_edges(nodes),
                        timeout=scan_update_edges_timeout_seconds,
                    )
                except TimeoutError:
                    log.warning(
                        "_background_scan: update_edges TIMEOUT file=%s timeout_s=%.1f",
                        fpath,
                        scan_update_edges_timeout_seconds,
                    )
                    continue
                count += len(nodes)
                parsed += 1
                files_since_last_manifest_save += 1
                _maybe_save_manifest_incremental()
                # Brief delay between files to reduce SQLite write contention.
                # This allows user operations (chat, panel) to acquire write locks.
                await asyncio.sleep(0.1)
                log.debug("_background_scan: parsed %s -> %d nodes", fpath.relative_to(root_path), len(nodes))
            except Exception:
                log.warning("_background_scan: failed to parse %s", fpath, exc_info=True)

        try:
            _save_manifest(next_manifest)
        except Exception:
            log.warning("_background_scan: failed to save scan manifest %s", manifest_path, exc_info=True)

        log.info(
            "_background_scan: COMPLETE — %d nodes from %d parsed files (%d total, %d unchanged skipped, %d pauses for user activity)",
            count,
            parsed,
            len(py_files),
            skipped_unchanged,
            scan_pauses,
        )
        await server.notify_agents_updated()

    async def _notify_agents_updated() -> None:
        """Delegate to the proper method on the server."""
        await server.notify_agents_updated()

    # Attach the notifier to the server so handlers can call it
    server._notify_agents_updated = _notify_agents_updated

    log.info("Starting IO transport (waiting for client on stdin) ...")
    try:
        server.start_io()
    except Exception:
        log.exception("Fatal error in server.start_io()")
        raise
    finally:
        if event_store is not None:
            try:
                asyncio.run(event_store.close())
            except Exception:
                log.warning("event store close failed", exc_info=True)
        log.info("remora-lsp shutting down")


if __name__ == "__main__":
    main()
