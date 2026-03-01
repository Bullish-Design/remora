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

from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph
from remora.lsp.models import ASTAgentNode, RewriteProposal, ToolSchema
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
        self.graph = LazyGraph(self.db)
        self.watcher = ASTWatcher()
        self.proposals: dict[str, RewriteProposal] = {}
        self.runner: "AgentRunner | None" = None
        self._correlation_counter = 0
        self._injecting: set[str] = set()
        self.event_store = event_store
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
        self.text_document_publish_diagnostics(
            lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
        )

    async def emit_event(self, event) -> Any:
        if not getattr(event, "timestamp", None):
            event.timestamp = time.time()
        await self.db.store_event(event)

        if self.event_store:
            try:
                core_event = event.to_core_event()
            except NotImplementedError:
                core_event = None
            else:
                if core_event:
                    await self.event_store.append("swarm", core_event)

        self.send_notification("$/remora/event", event.model_dump())
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

    async def discover_tools_for_agent(self, agent: ASTAgentNode) -> list[ToolSchema]:
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


server = RemoraLanguageServer()


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


def register_handlers() -> None:
    # Force import order so that handlers register on `server`
    from remora.lsp.handlers import actions, capabilities, commands, documents, hover, lens  # noqa: F401
    from remora.lsp import notifications  # noqa: F401


register_handlers()

atexit.register(server.shutdown)
