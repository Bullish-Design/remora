# src/remora/lsp/__main__.py
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time

from lsprotocol import types as lsp
from remora.lsp.process_lock import _ParentProcessWatchdog, _WorkspaceProcessLock

def _install_signal_handlers(process_lock: _WorkspaceProcessLock) -> None:
    def _handle_termination(signum, _frame) -> None:
        process_lock.release()
        raise SystemExit(128 + signum)

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(signum, _handle_termination)
        except Exception:
            continue



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
    from remora.lsp.server import get_server

    return get_server()


def _run_server(
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
    from remora.lsp.server import register_handlers

    server = _get_server()
    if hasattr(server, "command") and hasattr(server, "feature"):
        register_handlers(server)
    else:
        log.debug("Skipping handler registration for non-pygls server test double")

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

    if not getattr(server, "_remora_initialized_handler_registered", False):
        server._remora_initialized_handler_registered = True

        @server.feature(lsp.INITIALIZED)
        async def _on_initialized(*args) -> None:
            if len(args) == 1:
                ls = server
            elif len(args) >= 2:
                ls = args[0]
            else:
                ls = server
            startup_log = getattr(ls, "_remora_startup_log", log)
            started_at = getattr(ls, "_remora_startup_t0", t0)
            startup_log.info(
                "=== INITIALIZED received — startup took %.0fms ===",
                (time.monotonic() - started_at) * 1000,
            )
            startup_log.info("Workspace root_uri: %s", getattr(ls.workspace, "root_uri", "NOT SET"))
            startup_log.info("Workspace root_path: %s", getattr(ls.workspace, "root_path", "NOT SET"))
            active_runner = getattr(ls, "runner", None)
            if active_runner is not None:
                startup_log.info("Starting agent runner loop...")
                asyncio.ensure_future(active_runner.run_forever())
                # Wire subscription-based triggers into the runner so the reactive
                # loop is fully closed: event → EventStore → subscription matching
                # → trigger queue → AgentRunner (Gap #1 closure)
                if ls.event_store is not None:
                    try:
                        # Opportunistically compact carried-over WAL work from prior sessions.
                        await ls.event_store.checkpoint_wal("PASSIVE")
                    except Exception:
                        startup_log.warning("startup checkpoint failed", exc_info=True)
                    startup_log.info("Starting EventStore trigger bridge...")
                    asyncio.ensure_future(active_runner.run_from_event_store(ls.event_store))
            startup_log.info("Starting background workspace scan...")
            run_background_scan = getattr(ls, "_remora_background_scan", None)
            if callable(run_background_scan):
                asyncio.ensure_future(run_background_scan())

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

                from remora.core.discovery import parse_content
                text = await asyncio.to_thread(fpath.read_text, encoding="utf-8", errors="replace")
                uri = from_fs_path(str(fpath))
                nodes = await asyncio.to_thread(parse_content, uri, text)
                # Emit events to EventStore (batched per file for efficiency)
                if server.event_store:
                    from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent

                    old_agents = await server.event_store.list_nodes(file_path=uri)
                    old_ids = {a.node_id for a in old_agents}
                    new_ids = {n.node_id for n in nodes}

                    # Batch all events for this file
                    batch_events = [NodeDiscoveredEvent.from_cst_node(n) for n in nodes]
                    for removed_id in old_ids - new_ids:
                        batch_events.append(
                            NodeRemovedEvent(node_id=removed_id)
                        )

                    # Append events in small chunks so user-triggered operations
                    # can preempt scan writes quickly.
                    if batch_events:
                        timed_out = False
                        for idx in range(0, len(batch_events), scan_append_chunk_size):
                            chunk = batch_events[idx : idx + scan_append_chunk_size]
                            await _pause_for_user_activity()
                            # Yield to event loop BEFORE acquiring write lock so
                            # pending panel / chat requests can be serviced first.
                            await asyncio.sleep(0)
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

    # Attach dynamic startup context for the initialized callback.
    server._remora_startup_log = log
    server._remora_startup_t0 = t0
    server._remora_background_scan = _background_scan

    # Attach the notifier to the server so handlers can call it.
    server._notify_agents_updated = _notify_agents_updated

    log.info("Starting IO transport (waiting for client on stdin) ...")
    def _run_async_cleanup(coro) -> None:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return
        running_loop.create_task(coro)

    try:
        server.start_io()
    except Exception:
        log.exception("Fatal error in server.start_io()")
        raise
    finally:
        try:
            if hasattr(runner, "stop"):
                runner.stop()
            if hasattr(runner, "close"):
                _run_async_cleanup(runner.close())
        except Exception:
            log.warning("runner close failed", exc_info=True)
        if event_store is not None:
            try:
                _run_async_cleanup(event_store.close())
            except Exception:
                log.warning("event store close failed", exc_info=True)
        log.info("remora-lsp shutting down")


def main() -> None:
    """Start the Remora LSP server with agent runner.
    
    Creates an EventStore + SubscriptionRegistry before handing off to
    the real server loop.
    """
    import asyncio
    from pathlib import Path
    
    async def _prepare():
        from remora.core.event_bus import EventBus
        from remora.core.event_store import EventStore
        from remora.core.projections import NodeProjection
        from remora.core.subscriptions import SubscriptionRegistry

        root = Path.cwd()
        swarm_path = root / ".remora"
        event_store_path = swarm_path / "events" / "events.db"
        subscriptions_path = swarm_path / "subscriptions.db"

        event_bus = EventBus()
        subscriptions = SubscriptionRegistry(subscriptions_path)
        from remora.extensions import extension_matches, load_extensions
        extensions = load_extensions(swarm_path / "models")
        projection = NodeProjection(
            extension_matcher=extension_matches,
            extension_configs=extensions,
        )
        event_store = EventStore(
            event_store_path,
            subscriptions=subscriptions,
            event_bus=event_bus,
            projection=projection,
        )

        event_store.set_subscriptions(subscriptions)
        event_store.set_event_bus(event_bus)

        return event_store, subscriptions

    root = Path.cwd()
    swarm_path = root / ".remora"
    process_lock = _WorkspaceProcessLock(
        lock_path=swarm_path / "lsp.lock",
        pid_path=swarm_path / "lsp.pid",
    )
    owner_at_start = process_lock._read_owner_metadata()
    if owner_at_start.pid is not None:
        age_ms = process_lock._heartbeat_age_ms(owner_at_start)
        print(
            "remora-lsp: existing lock metadata before acquire "
            f"(owner_pid={owner_at_start.pid}, "
            f"owner_parent_pid={owner_at_start.parent_pid}, "
            f"owner_heartbeat_age_ms={age_ms}, "
            f"lock={process_lock.lock_path}, pid_file={process_lock.pid_path})",
            file=sys.stderr,
        )
    try:
        process_lock.acquire()
    except RuntimeError as exc:
        owner = process_lock._read_owner_metadata()
        age_ms = process_lock._heartbeat_age_ms(owner)
        print(
            "remora-lsp: workspace lock acquire failed "
            f"(error={exc}, owner_pid={owner.pid}, owner_parent_pid={owner.parent_pid}, "
            f"owner_heartbeat_age_ms={age_ms}, lock={process_lock.lock_path}, "
            f"pid_file={process_lock.pid_path})",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    print(
        "remora-lsp: workspace lock acquired "
        f"(pid={os.getpid()}, parent_pid={os.getppid()}, lock={process_lock.lock_path}, "
        f"pid_file={process_lock.pid_path})",
        file=sys.stderr,
    )

    watchdog = _ParentProcessWatchdog(process_lock=process_lock)
    watchdog.start()
    _install_signal_handlers(process_lock)

    try:
        event_store, subscriptions = asyncio.run(_prepare())
        _run_server(
            event_store=event_store,
            subscriptions=subscriptions,
        )
    finally:
        watchdog.stop()
        process_lock.release()

if __name__ == "__main__":
    main()
