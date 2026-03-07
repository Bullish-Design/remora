from __future__ import annotations

import asyncio
from typing import Any

from remora.core.events.agent_events import AgentEvent, HumanChatEvent, RewriteProposalEvent, RewriteRejectedEvent
from remora.core.events.interaction_events import AgentMessageEvent
from remora.runner.protocols import RunnerServer


class RunnerEventEmitter:
    """Encapsulates AgentRunner -> server event emission behavior."""

    def __init__(self, server: RunnerServer):
        self._server = server

    def _supports_server_method(self, method_name: str) -> bool:
        server_dict = getattr(self._server, "__dict__", {})
        return hasattr(type(self._server), method_name) or method_name in server_dict

    async def _call_server_method(self, method_name: str, **kwargs: Any) -> bool:
        if not self._supports_server_method(method_name):
            return False
        method = getattr(self._server, method_name)
        result = method(**kwargs)
        if asyncio.iscoroutine(result):
            await result
        return True

    async def emit_agent_event(
        self,
        *,
        event_type: str,
        agent_id: str,
        correlation_id: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if await self._call_server_method(
            "emit_agent_event",
            event_type=event_type,
            agent_id=agent_id,
            correlation_id=correlation_id,
            summary=summary,
            payload=payload or {},
        ):
            return
        await self._server.emit_event(
            AgentEvent(
                event_type=event_type,
                agent_id=agent_id,
                correlation_id=correlation_id,
                summary=summary,
                payload=payload or {},
            )
        )

    async def emit_agent_error(self, *, agent_id: str, error: str, correlation_id: str) -> None:
        if await self._call_server_method(
            "emit_agent_error_event",
            agent_id=agent_id,
            error=error,
            correlation_id=correlation_id,
        ):
            return
        await self._server.emit_event(
            AgentEvent(
                event_type="AgentErrorEvent",
                agent_id=agent_id,
                correlation_id=correlation_id,
                summary=f"Error: {error[:50]}",
                payload={"error": error},
            )
        )

    async def emit_human_chat(self, *, agent_id: str, message: str, correlation_id: str) -> None:
        if await self._call_server_method(
            "emit_human_chat_event",
            agent_id=agent_id,
            message=message,
            correlation_id=correlation_id,
        ):
            return
        await self._server.emit_event(
            HumanChatEvent(
                agent_id=agent_id,
                to_agent=agent_id,
                message=message,
                correlation_id=correlation_id,
            )
        )

    async def emit_rewrite_rejected(
        self,
        *,
        agent_id: str,
        proposal_id: str,
        feedback: str,
        correlation_id: str,
    ) -> None:
        if await self._call_server_method(
            "emit_rewrite_rejected_event",
            agent_id=agent_id,
            proposal_id=proposal_id,
            feedback=feedback,
            correlation_id=correlation_id,
        ):
            return
        await self._server.emit_event(
            RewriteRejectedEvent(
                agent_id=agent_id,
                proposal_id=proposal_id,
                feedback=feedback,
                correlation_id=correlation_id,
            )
        )

    async def emit_rewrite_proposal(
        self,
        *,
        agent_id: str,
        proposal_id: str,
        diff: str,
        correlation_id: str,
    ) -> None:
        if await self._call_server_method(
            "emit_rewrite_proposal_event",
            agent_id=agent_id,
            proposal_id=proposal_id,
            diff=diff,
            correlation_id=correlation_id,
        ):
            return
        await self._server.emit_event(
            RewriteProposalEvent(
                agent_id=agent_id,
                proposal_id=proposal_id,
                diff=diff,
                correlation_id=correlation_id,
            )
        )

    async def emit_agent_message(
        self,
        *,
        from_agent: str,
        to_agent: str,
        message: str,
        correlation_id: str,
    ) -> None:
        if await self._call_server_method(
            "emit_agent_message_event",
            from_agent=from_agent,
            to_agent=to_agent,
            message=message,
            correlation_id=correlation_id,
        ):
            return
        await self._server.emit_event(
            AgentMessageEvent(
                from_agent=from_agent,
                to_agent=to_agent,
                content=message,
                correlation_id=correlation_id,
            )
        )
