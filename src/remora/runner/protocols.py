"""Protocol defining the server interface required by AgentRunner."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RunnerServer(Protocol):
    """Minimal server interface needed by AgentRunner."""

    event_store: Any
    db: Any
    subscriptions: Any | None
    proposals: dict[str, Any]
    workspace: Any

    def generate_correlation_id(self) -> str: ...
    async def emit_event(self, event: Any) -> Any: ...
    async def refresh_code_lenses(self) -> None: ...
    async def publish_diagnostics(self, uri: str, proposals: list[Any]) -> None: ...
    async def accept_proposal(self, proposal_id: str) -> None: ...
    async def emit_human_chat_event(self, *, agent_id: str, message: str, correlation_id: str) -> None: ...
    async def emit_rewrite_rejected_event(
        self,
        *,
        agent_id: str,
        proposal_id: str,
        feedback: str,
        correlation_id: str,
    ) -> None: ...
    async def emit_agent_error_event(self, *, agent_id: str, error: str, correlation_id: str) -> None: ...
    async def emit_agent_message_event(
        self,
        *,
        from_agent: str,
        to_agent: str,
        message: str,
        correlation_id: str,
    ) -> None: ...
    async def emit_rewrite_proposal_event(
        self,
        *,
        agent_id: str,
        proposal_id: str,
        diff: str,
        correlation_id: str,
    ) -> None: ...
    async def emit_agent_event(
        self,
        *,
        event_type: str,
        agent_id: str,
        correlation_id: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> None: ...
