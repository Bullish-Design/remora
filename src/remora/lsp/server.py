from __future__ import annotations

import atexit
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from remora.core.agent_node import AgentNode, ToolSchema
from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph
from remora.lsp.models import RewriteProposal
from remora.lsp.watcher import ASTWatcher

logger = logging.getLogger("remora.lsp")


class RemoraLanguageServer(LanguageServer):
    def __init__(
        self,
        event_store=None,
        subscriptions=None,
        swarm_state=None,
    ):
        super().__init__(name="remora", version="0.1.0")
        self.db = RemoraDB()
        self.event_store = event_store
        es_db_path = str(event_store._db_path) if event_store else None
        self.graph = LazyGraph(self.db, event_store_db_path=es_db_path)
        self.watcher = ASTWatcher()
        self.proposals: dict[str, RewriteProposal] = {}
        self.runner: "AgentRunner | None" = None
        self._correlation_counter = 0
        self._injecting: set[str] = set()
        self.subscriptions = subscriptions
        self.swarm_state = swarm_state

    def generate_correlation_id(self) -> str:
        self._correlation_counter += 1
        return f"corr_{self._correlation_counter}_{uuid.uuid4().hex[:8]}"

    async def refresh_code_lenses(self) -> None:
        try:
            await self.workspace_code_lens_refresh_async()
        except Exception:
            pass

    async def publish_diagnostics(self, uri: str, proposals: list[RewriteProposal]) -> None:
        diagnostics = [p.to_diagnostic() for p in proposals]
        self.text_document_publish_diagnostics(lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics))

    async def emit_event(self, event) -> Any:
        if not getattr(event, "timestamp", None):
            event.timestamp = time.time()

        if self.event_store:
            await self.event_store.append("swarm", event)

        self.protocol.notify("$/remora/event", event.model_dump())
        return event

    def shutdown(self) -> None:
        """Cleanly close all persistent connections."""
        try:
            self.db.close()
        except Exception:
            logger.warning("Failed to close RemoraDB", exc_info=True)
        try:
            self.graph.close()
        except Exception:
            logger.warning("Failed to close LazyGraph", exc_info=True)

    async def discover_tools_for_agent(self, agent: AgentNode) -> list[ToolSchema]:
        try:
            from remora.core.config import load_config
            from remora.core.tools.grail import discover_grail_tools

            config = load_config()
            bundle_name = config.bundle_mapping.get(agent.node_type)
            if not bundle_name:
                return []

            bundle_dir = Path(config.bundle_root) / bundle_name / "tools"
            if not bundle_dir.exists():
                return []

            grail_tools = discover_grail_tools(str(bundle_dir), {}, lambda: {})
            return [
                ToolSchema(
                    name=t.schema.name,
                    description=t.schema.description,
                    parameters=t.schema.parameters,
                )
                for t in grail_tools
            ]
        except Exception:
            logger.exception("Error discovering tools for agent")
            return []

    async def notify_agents_updated(self) -> None:
        """Send $/remora/agentsUpdated with all active nodes to the client."""
        try:
            if self.event_store:
                all_agents = await self.event_store.list_nodes()
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
            logger.info("notify_agents_updated: sending %d agents to client", len(agent_list))
            self.protocol.notify("$/remora/agentsUpdated", agent_list)
        except Exception:
            logger.exception("notify_agents_updated: FAILED")


_server: RemoraLanguageServer | None = None


def get_server() -> RemoraLanguageServer:
    """Return the global RemoraLanguageServer singleton, creating it lazily."""
    global _server
    if _server is None:
        _server = RemoraLanguageServer()
        atexit.register(_server.shutdown)
    return _server


def register_handlers() -> None:
    """Force import of handler modules so they register on the server singleton."""
    from remora.lsp.handlers import actions, capabilities, commands, documents, hover, lens  # noqa: F401
    from remora.lsp import notifications  # noqa: F401


# Backward-compatible eager singleton — handler decorators need this at import time.
server = get_server()


def uri_to_path(uri: str) -> str:
    try:
        return to_fs_path(uri)
    except Exception:
        return uri


async def refresh_code_lenses() -> None:
    await server.refresh_code_lenses()


async def publish_diagnostics(uri: str, proposals: list[RewriteProposal]) -> None:
    await server.publish_diagnostics(uri, proposals)


async def emit_event(event) -> Any:
    return await server.emit_event(event)


register_handlers()
