from __future__ import annotations

import asyncio
import atexit
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from remora.core.agents.agent_node import AgentNode, ToolSchema
from remora.core.events.events import (
    AgentEvent,
    AgentMessageEvent,
    HumanChatEvent,
    RewriteAppliedEvent,
    RewriteProposalEvent,
    RewriteRejectedEvent,
)
from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph
from remora.lsp.models import RewriteProposal

if TYPE_CHECKING:
    from remora.core.events.subscriptions import SubscriptionRegistry
    from remora.core.store.event_store import EventStore
    from remora.runner.agent_runner import AgentRunner

logger = logging.getLogger("remora.lsp")


class RemoraLanguageServer(LanguageServer):
    def __init__(
        self,
        event_store: EventStore | None = None,
        subscriptions: SubscriptionRegistry | None = None,
    ):
        super().__init__(name="remora", version="0.1.0")
        self.db = RemoraDB()
        self.event_store = event_store
        self.graph = LazyGraph(self.db, event_store=event_store)
        self.proposals: dict[str, RewriteProposal] = {}
        self.runner: AgentRunner | None = None
        self._correlation_counter = 0
        self.subscriptions = subscriptions
        # Debounce timers for didChange reparse (Gap #12) and cursor updates (Gap #13)
        self._reparse_timers: dict[str, asyncio.TimerHandle] = {}
        self._cursor_timers: dict[str, asyncio.TimerHandle] = {}
        self._last_user_activity_monotonic = 0.0
        self._handlers_registered = False
        self._remora_initialized_handler_registered = False
        self._remora_startup_log: logging.Logger | None = None
        self._remora_startup_t0 = 0.0
        self._remora_background_scan: Callable[[], Awaitable[None]] | None = None

    def generate_correlation_id(self) -> str:
        self._correlation_counter += 1
        return f"corr_{self._correlation_counter}_{uuid.uuid4().hex[:8]}"

    def note_user_activity(self, source: str = "unknown") -> None:
        self._last_user_activity_monotonic = time.monotonic()
        logger.debug("note_user_activity: source=%s", source)

    def user_recently_active(self, window_seconds: float = 2.0) -> bool:
        if self._last_user_activity_monotonic <= 0:
            return False
        return (time.monotonic() - self._last_user_activity_monotonic) <= window_seconds

    def schedule_reparse(self, uri: str, text: str, delay_ms: int = 500) -> None:
        """Schedule a debounced reparse for *uri*.

        Any pending reparse for the same URI is cancelled first.  The actual
        reparse is executed as an ``asyncio.Task`` after *delay_ms*
        milliseconds of inactivity.
        """
        # Cancel previous timer for this URI
        prev = self._reparse_timers.pop(uri, None)
        if prev is not None:
            prev.cancel()

        loop = asyncio.get_running_loop()
        handle = loop.call_later(
            delay_ms / 1000.0,
            lambda: asyncio.ensure_future(self._do_reparse(uri, text)),
        )
        self._reparse_timers[uri] = handle

    async def _do_reparse(self, uri: str, text: str) -> None:
        """Execute the actual debounced reparse for *uri*."""
        from remora.core.code.discovery import parse_content
        from remora.core.events.events import NodeDiscoveredEvent, NodeRemovedEvent

        self._reparse_timers.pop(uri, None)
        try:
            cst_nodes = parse_content(uri, text)
            logger.debug("_do_reparse: %d nodes for %s", len(cst_nodes), uri)

            if self.event_store:
                old_agents = await self.event_store.nodes.list_nodes(file_path=uri)
                new_ids = {n.node_id for n in cst_nodes}
                old_ids = {a.node_id for a in old_agents}

                for orphan_id in old_ids - new_ids:
                    await self.event_store.append("nodes", NodeRemovedEvent(node_id=orphan_id))

                for node in cst_nodes:
                    await self.event_store.append("nodes", NodeDiscoveredEvent.from_cst_node(node))

            await self.refresh_code_lenses()
            await self.notify_agents_updated()
        except Exception:
            logger.exception("Error in _do_reparse for %s", uri)

    def schedule_cursor_update(
        self,
        agent_id: str | None,
        uri: str,
        line: int,
        delay_ms: int = 200,
    ) -> None:
        """Schedule a debounced cursor-focus update.

        Cancels any pending cursor timer, then fires the actual DB update +
        ``CursorFocusEvent`` emission after *delay_ms* of cursor stability.
        """
        prev = self._cursor_timers.pop(uri, None)
        if prev is not None:
            prev.cancel()

        loop = asyncio.get_running_loop()
        handle = loop.call_later(
            delay_ms / 1000.0,
            lambda: asyncio.ensure_future(self._do_cursor_update(agent_id, uri, line)),
        )
        self._cursor_timers[uri] = handle

    async def _do_cursor_update(self, agent_id: str | None, uri: str, line: int) -> None:
        """Execute the actual debounced cursor update."""
        from remora.core.events.events import CursorFocusEvent

        self._cursor_timers.pop(uri, None)
        try:
            await self.db.update_cursor_focus(agent_id, uri, line)
            if self.event_store:
                event = CursorFocusEvent(focused_agent_id=agent_id, file_path=uri, line=line)
                await self.event_store.append("cursor", event)
        except Exception:
            logger.debug("Error in _do_cursor_update", exc_info=True)

    async def refresh_code_lenses(self) -> None:
        try:
            await self.workspace_code_lens_refresh_async()
        except Exception:
            pass

    async def publish_diagnostics(self, uri: str, proposals: list[RewriteProposal]) -> None:
        diagnostics = [p.to_diagnostic() for p in proposals]
        self.text_document_publish_diagnostics(lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics))

    async def emit_agent_event(
        self,
        *,
        event_type: str,
        agent_id: str,
        correlation_id: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await self.emit_event(
            AgentEvent(
                event_type=event_type,
                agent_id=agent_id,
                correlation_id=correlation_id,
                summary=summary,
                payload=payload or {},
            )
        )

    async def emit_agent_error_event(self, *, agent_id: str, error: str, correlation_id: str) -> None:
        await self.emit_event(
            AgentEvent(
                event_type="AgentErrorEvent",
                agent_id=agent_id,
                correlation_id=correlation_id,
                summary=f"Error: {error[:50]}",
                payload={"error": error},
            )
        )

    async def emit_human_chat_event(self, *, agent_id: str, message: str, correlation_id: str) -> None:
        await self.emit_event(
            HumanChatEvent(
                agent_id=agent_id,
                to_agent=agent_id,
                message=message,
                correlation_id=correlation_id,
            )
        )

    async def emit_rewrite_rejected_event(
        self,
        *,
        agent_id: str,
        proposal_id: str,
        feedback: str,
        correlation_id: str,
    ) -> None:
        await self.emit_event(
            RewriteRejectedEvent(
                agent_id=agent_id,
                proposal_id=proposal_id,
                feedback=feedback,
                correlation_id=correlation_id,
            )
        )

    async def emit_agent_message_event(
        self,
        *,
        from_agent: str,
        to_agent: str,
        message: str,
        correlation_id: str,
    ) -> None:
        await self.emit_event(
            AgentMessageEvent(
                from_agent=from_agent,
                to_agent=to_agent,
                content=message,
                correlation_id=correlation_id,
            )
        )

    async def emit_rewrite_proposal_event(
        self,
        *,
        agent_id: str,
        proposal_id: str,
        diff: str,
        correlation_id: str,
    ) -> None:
        await self.emit_event(
            RewriteProposalEvent(
                agent_id=agent_id,
                proposal_id=proposal_id,
                diff=diff,
                correlation_id=correlation_id,
            )
        )

    async def accept_proposal(self, proposal_id: str) -> None:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            return

        await self.workspace_apply_edit(lsp.ApplyWorkspaceEditParams(edit=proposal.to_workspace_edit()))
        del self.proposals[proposal_id]
        if self.event_store:
            await self.event_store.nodes.set_node_status(proposal.agent_id, "idle")
        await self.db.update_proposal_status(proposal_id, "accepted")
        await self.emit_event(
            RewriteAppliedEvent(
                agent_id=proposal.agent_id,
                proposal_id=proposal_id,
                correlation_id=proposal.correlation_id or "",
            )
        )

    async def emit_event(self, event) -> Any:
        if not getattr(event, "timestamp", None):
            if hasattr(event, "model_copy"):
                event = event.model_copy(update={"timestamp": time.time()})
            else:
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
                all_agents = await self.event_store.nodes.list_nodes()
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


def register_handlers(server: RemoraLanguageServer) -> None:
    """Register LSP handlers on the given server instance.

    Must be called AFTER server creation, BEFORE server.start_io().
    Handlers use pygls's built-in LanguageServer parameter injection.
    """
    if getattr(server, "_handlers_registered", False):
        return
    server._handlers_registered = True
    from remora.lsp.handlers.actions import register_action_handlers
    from remora.lsp.handlers.capabilities import register_capability_handlers
    from remora.lsp.handlers.commands import register_command_handlers
    from remora.lsp.handlers.documents import register_document_handlers
    from remora.lsp.handlers.hover import register_hover_handlers
    from remora.lsp.handlers.lens import register_lens_handlers
    from remora.lsp.notifications import register_notification_handlers

    register_command_handlers(server)
    register_document_handlers(server)
    register_action_handlers(server)
    register_capability_handlers(server)
    register_hover_handlers(server)
    register_lens_handlers(server)
    register_notification_handlers(server)


__all__ = [
    "RemoraLanguageServer",
    "get_server",
    "register_handlers",
]
