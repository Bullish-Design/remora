# src/remora/lsp/__main__.py
from __future__ import annotations

import asyncio
import logging
import sys
import time

from lsprotocol import types as lsp


def _setup_logging() -> logging.Logger:
    """Configure logging to stderr AND a timestamped file in .remora/logs/."""
    from pathlib import Path
    from datetime import datetime

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
    swarm_state=None,
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
    from remora.lsp.runner import AgentRunner, LLMClient

    log.debug("Runner module loaded in %.1fms", (time.monotonic() - t0) * 1000)

    server.event_store = event_store
    server.subscriptions = subscriptions
    server.swarm_state = swarm_state

    log.debug("Creating LLM client ...")
    llm = LLMClient(
        base_url=config.model_base_url,
        model=config.model_default,
        api_key=config.model_api_key or "EMPTY",
    )

    log.debug("Creating AgentRunner ...")
    runner = AgentRunner(server=server, llm=llm)
    server.runner = runner
    log.debug("AgentRunner created with LLM client")

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
        log.info("Starting background workspace scan...")
        asyncio.ensure_future(_background_scan())

    async def _background_scan() -> None:
        """Walk workspace for *.py files, parse each, and populate the DB."""
        from pathlib import Path
        from pygls.uris import from_fs_path

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

        count = 0
        parsed = 0
        for fpath in py_files:
            try:
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
                # Emit events to EventStore
                if server.event_store:
                    from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent

                    old_ids = {n["node_id"] for n in old_nodes}
                    new_ids = {n["node_id"] for n in nodes}
                    for node_dict in nodes:
                        await server.event_store.append(
                            "lsp",
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
                            ),
                        )
                    for removed_id in old_ids - new_ids:
                        await server.event_store.append(
                            "lsp",
                            NodeRemovedEvent(node_id=removed_id, file_path=uri),
                        )
                await server.db.update_edges(nodes)
                count += len(nodes)
                parsed += 1
                log.debug("_background_scan: parsed %s -> %d nodes", fpath.relative_to(root_path), len(nodes))
            except Exception:
                log.warning("_background_scan: failed to parse %s", fpath, exc_info=True)

        log.info(
            "_background_scan: COMPLETE — %d nodes from %d parsed files (%d total)",
            count,
            parsed,
            len(py_files),
        )
        await _notify_agents_updated()

    async def _notify_agents_updated() -> None:
        """Send $/remora/agentsUpdated with all active nodes to the client."""
        try:
            if server.event_store:
                all_agents = await server.event_store.list_nodes()
                agent_list = [
                    {
                        "node_id": a.node_id,
                        "name": a.name,
                        "status": a.status,
                        "node_type": a.node_type,
                        "file_path": a.file_path,
                        "parent_id": a.parent_id or "",
                    }
                    for a in all_agents
                ]
            else:
                agent_list = []
            log.info("_notify_agents_updated: sending %d agents to client via $/remora/agentsUpdated", len(agent_list))
            if agent_list:
                log.debug("_notify_agents_updated: first 3 agents: %s", agent_list[:3])
            server.protocol.notify("$/remora/agentsUpdated", agent_list)
            log.info("_notify_agents_updated: notification sent successfully")
        except Exception:
            log.exception("_notify_agents_updated: FAILED")

    # Attach the notifier to the server so handlers can call it
    server._notify_agents_updated = _notify_agents_updated

    log.info("Starting IO transport (waiting for client on stdin) ...")
    try:
        server.start_io()
    except Exception:
        log.exception("Fatal error in server.start_io()")
        raise
    finally:
        log.info("remora-lsp shutting down")


if __name__ == "__main__":
    main()
