# src/remora/lsp/__main__.py
from __future__ import annotations

import asyncio
import logging
import sys
import time

from lsprotocol import types as lsp


def _setup_logging() -> logging.Logger:
    """Configure logging to stderr (stdout is reserved for LSP protocol)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger("remora")
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    # Quiet down pygls internals unless needed
    logging.getLogger("pygls").setLevel(logging.WARNING)

    return logging.getLogger("remora.lsp.startup")


def main(
    event_store=None,
    subscriptions=None,
    swarm_state=None,
) -> None:
    """Start the Remora LSP server with agent runner."""
    t0 = time.monotonic()
    log = _setup_logging()
    log.info("remora-lsp starting (pid=%d)", __import__("os").getpid())

    log.debug("Importing remora.lsp.server ...")
    from remora.lsp.server import server

    log.debug("Server module loaded (handlers registered) in %.1fms", (time.monotonic() - t0) * 1000)

    log.debug("Importing remora.lsp.runner ...")
    from remora.lsp.runner import AgentRunner, LLMClient

    log.debug("Runner module loaded in %.1fms", (time.monotonic() - t0) * 1000)

    server.event_store = event_store
    server.subscriptions = subscriptions
    server.swarm_state = swarm_state

    log.debug("Creating LLM client ...")
    llm = LLMClient(
        base_url="http://remora-server:8000/v1",
        model="Qwen/Qwen3-4B-Instruct-2507-FP8",
    )

    log.debug("Creating AgentRunner ...")
    runner = AgentRunner(server=server, llm=llm)
    server.runner = runner
    log.debug("AgentRunner created with LLM client")

    @server.feature(lsp.INITIALIZED)
    async def _on_initialized(params: lsp.InitializedParams) -> None:
        log.info(
            "Client initialized — starting agent runner loop (startup took %.0fms)",
            (time.monotonic() - t0) * 1000,
        )
        asyncio.ensure_future(runner.run_forever())
        asyncio.ensure_future(_background_scan())

    async def _background_scan() -> None:
        """Walk workspace for *.py files, parse each, and populate the DB."""
        from pathlib import Path
        from pygls.uris import from_fs_path

        root = server.workspace.root_path
        if not root:
            log.warning("No workspace root — skipping background scan")
            return

        root_path = Path(root)
        py_files = sorted(root_path.rglob("*.py"))
        log.info("Background scan: found %d .py files in %s", len(py_files), root)

        count = 0
        for fpath in py_files:
            # Skip common non-project directories
            parts = fpath.relative_to(root_path).parts
            if any(p.startswith(".") or p in ("__pycache__", "node_modules", ".venv", "venv") for p in parts):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
                uri = from_fs_path(str(fpath))
                nodes = server.watcher.parse_and_inject_ids(uri, text)
                await server.db.upsert_nodes(nodes)
                await server.db.update_edges(nodes)
                count += len(nodes)
            except Exception:
                log.debug("Background scan: failed to parse %s", fpath, exc_info=True)

        log.info("Background scan complete: %d agent nodes from %d files", count, len(py_files))
        await _notify_agents_updated()

    async def _notify_agents_updated() -> None:
        """Send $/remora/agentsUpdated with all active nodes to the client."""
        try:
            all_nodes = await server.db.get_all_nodes()
            agent_list = [
                {
                    "remora_id": n["id"],
                    "name": n["name"],
                    "status": n.get("status", "active"),
                    "node_type": n.get("node_type", ""),
                    "file_path": n.get("file_path", ""),
                    "parent_id": n.get("parent_id", ""),
                }
                for n in all_nodes
            ]
            server.protocol.notify("$/remora/agentsUpdated", agent_list)
            log.debug("Notified client: %d agents", len(agent_list))
        except Exception:
            log.exception("Failed to send $/remora/agentsUpdated")

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
