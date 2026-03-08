# src/remora/lsp/__main__.py
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
import traceback

from lsprotocol import types as lsp

from remora.lsp.process_lock import _ParentProcessWatchdog, _WorkspaceProcessLock


def _bootstrap_log(message: str) -> None:
    """Early startup logging before logging handlers are configured."""
    stamp = time.strftime("%H:%M:%S")
    print(f"remora-lsp bootstrap [{stamp}] {message}", file=sys.stderr, flush=True)


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
    event_bus=None,
    cairn_service=None,
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
    from remora.lsp.server_setup import register_handlers

    server = _get_server()
    if hasattr(server, "command") and hasattr(server, "feature"):
        register_handlers(server)
    else:
        log.debug("Skipping handler registration for non-pygls server test double")

    log.debug("Server module loaded (handlers registered) in %.1fms", (time.monotonic() - t0) * 1000)

    log.debug("Importing remora.runner.agent_runner ...")
    from remora.runner.agent_runner import AgentRunner

    log.debug("Runner module loaded in %.1fms", (time.monotonic() - t0) * 1000)

    server.event_store = event_store
    # Rebind EventStore asyncio primitives so they bind to THIS event loop (pygls).
    if event_store is not None:
        event_store.rebind_runtime_primitives()
    server.subscriptions = subscriptions
    server.companion_registry = None
    server.companion_router = None
    server._companion_event_bus = event_bus
    server._companion_cairn_service = cairn_service

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
            event_bus_local = getattr(ls, "_companion_event_bus", None)
            cairn_svc = getattr(ls, "_companion_cairn_service", None)
            if event_bus_local and cairn_svc and ls.event_store:
                try:
                    from remora.companion.config import CompanionConfig
                    from remora.companion.events import NodeAgentSidebarReady
                    from remora.companion.startup import start_companion

                    workspace_path = getattr(ls.workspace, "root_path", None) or os.getcwd()
                    comp_config = CompanionConfig(workspace_path=workspace_path)
                    registry = await start_companion(
                        event_store=ls.event_store,
                        event_bus=event_bus_local,
                        cairn_service=cairn_svc,
                        config=comp_config,
                    )
                    ls.companion_registry = registry
                    ls.companion_router = getattr(registry, "_router", None)

                    async def _push_sidebar(event: NodeAgentSidebarReady) -> None:
                        try:
                            ls.protocol.notify(
                                "$/remora/companionSidebarUpdated",
                                {"markdown": event.markdown, "node_id": event.node_id},
                            )
                        except Exception:
                            pass

                    event_bus_local.subscribe(NodeAgentSidebarReady, _push_sidebar)
                    startup_log.info("Companion system started")
                except Exception:
                    startup_log.exception("Companion startup failed (non-fatal)")
            startup_log.info("Starting background workspace scan...")
            run_background_scan = getattr(ls, "_remora_background_scan", None)
            if callable(run_background_scan):
                asyncio.ensure_future(run_background_scan())

    # Import once so scan loop can reuse it and tests can monkeypatch
    # remora.core.code.discovery.parse_content consistently.
    from remora.core.code.discovery import parse_content
    from remora.lsp.background_scanner import BackgroundScanner

    scanner = BackgroundScanner(
        server=server,
        parse_content=parse_content,
        log=log,
        ignore_patterns=config.workspace_ignore_patterns,
    )

    # Attach dynamic startup context for the initialized callback.
    server._remora_startup_log = log
    server._remora_startup_t0 = t0
    server._remora_background_scan = scanner.run

    log.info("Starting IO transport (waiting for client on stdin) ...")
    def _run_async_cleanup(coro) -> None:
        if coro is None:
            return
        if not asyncio.iscoroutine(coro):
            return
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
        prepare_t0 = time.monotonic()
        _bootstrap_log("_prepare: begin")
        from remora.core.agents.cairn_bridge import CairnWorkspaceService, SyncMode
        from remora.core.code.projections import NodeProjection
        from remora.core.config import load_config
        from remora.core.events.event_bus import EventBus
        from remora.core.events.subscriptions import SubscriptionRegistry
        from remora.core.store.event_store import EventStore

        root = Path.cwd()
        swarm_path = root / ".remora"
        event_store_path = swarm_path / "events" / "events.db"
        subscriptions_path = swarm_path / "subscriptions.db"
        _bootstrap_log(f"_prepare: root={root}")
        _bootstrap_log(f"_prepare: event_store_path={event_store_path}")

        event_bus = EventBus()
        subscriptions = SubscriptionRegistry(subscriptions_path)
        _bootstrap_log("_prepare: EventBus + SubscriptionRegistry created")
        from remora.extensions import extension_matches, load_extensions
        extensions_t0 = time.monotonic()
        extensions = load_extensions(swarm_path / "models")
        _bootstrap_log(
            "_prepare: extensions loaded "
            f"(count={len(extensions)} elapsed_ms={(time.monotonic() - extensions_t0) * 1000:.1f})"
        )
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
        _bootstrap_log("_prepare: EventStore constructed")

        event_store.set_subscriptions(subscriptions)
        event_store.set_event_bus(event_bus)
        _bootstrap_log("_prepare: EventStore wiring complete")
        event_store_t0 = time.monotonic()
        _bootstrap_log("_prepare: EventStore initialize start")
        await event_store.initialize()
        _bootstrap_log(
            "_prepare: EventStore initialize complete "
            f"(elapsed_ms={(time.monotonic() - event_store_t0) * 1000:.1f})"
        )
        config = load_config()
        _bootstrap_log(
            "_prepare: config loaded "
            f"(model={config.model_default} base_url={config.model_base_url})"
        )
        _bootstrap_log(
            "_prepare: workspace sync config "
            f"(ignore_dotfiles={config.workspace_ignore_dotfiles} "
            f"ignore_patterns={list(config.workspace_ignore_patterns)})"
        )
        cairn_service = CairnWorkspaceService(
            config,
            project_root=root,
            progress_callback=_bootstrap_log,
        )
        cairn_t0 = time.monotonic()
        _bootstrap_log("_prepare: Cairn initialize start (sync_mode=FULL)")
        await cairn_service.initialize(sync_mode=SyncMode.FULL)
        _bootstrap_log(
            "_prepare: Cairn initialize complete "
            f"(elapsed_ms={(time.monotonic() - cairn_t0) * 1000:.1f})"
        )
        _bootstrap_log(
            f"_prepare: done total_elapsed_ms={(time.monotonic() - prepare_t0) * 1000:.1f}"
        )

        return event_store, subscriptions, event_bus, cairn_service

    root = Path.cwd()
    swarm_path = root / ".remora"
    _bootstrap_log(f"main: start cwd={root}")
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
    _bootstrap_log("main: lock acquired")

    watchdog = _ParentProcessWatchdog(process_lock=process_lock)
    watchdog.start()
    _bootstrap_log("main: watchdog started")
    _install_signal_handlers(process_lock)
    _bootstrap_log("main: signal handlers installed")

    try:
        _bootstrap_log("main: calling asyncio.run(_prepare())")
        event_store, subscriptions, event_bus, cairn_service = asyncio.run(_prepare())
        _bootstrap_log("main: _prepare complete, entering _run_server")
        _run_server(
            event_store=event_store,
            subscriptions=subscriptions,
            event_bus=event_bus,
            cairn_service=cairn_service,
        )
        _bootstrap_log("main: _run_server exited")
    except Exception as exc:
        _bootstrap_log(f"main: fatal startup exception: {exc!r}")
        traceback.print_exc(file=sys.stderr)
        raise
    finally:
        _bootstrap_log("main: shutting down watchdog + releasing lock")
        watchdog.stop()
        process_lock.release()

if __name__ == "__main__":
    main()
