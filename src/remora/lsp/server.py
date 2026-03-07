from __future__ import annotations

import asyncio
import atexit
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from remora.core.events.agent_events import (
    AgentEvent,
    HumanChatEvent,
    RewriteAppliedEvent,
    RewriteProposalEvent,
    RewriteRejectedEvent,
)
from remora.core.events.interaction_events import AgentMessageEvent
from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph
from remora.lsp.runtime_ops import do_cursor_update, do_reparse
from remora.lsp.tooling import discover_tools_for_agent as _discover_tools_for_agent
from remora.runner.models import RewriteProposal

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
        await do_reparse(self, uri, text)

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
        await do_cursor_update(self, agent_id, uri, line)

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

    def __del__(self) -> None:
        # Finalizer safeguard for tests that forget explicit shutdown.
        try:
            self.shutdown()
        except Exception:
            pass

    async def discover_tools_for_agent(self, agent: Any) -> list[Any]:
        return await _discover_tools_for_agent(agent)

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
        atexit.register(shutdown_server)
    return _server


def shutdown_server() -> None:
    """Shutdown and clear the global server singleton."""
    global _server
    if _server is None:
        return
    try:
        _server.shutdown()
    finally:
        _server = None

__all__ = [
    "RemoraLanguageServer",
    "get_server",
    "shutdown_server",
]
