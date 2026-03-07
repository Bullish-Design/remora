from __future__ import annotations

import uuid
from typing import Any


class _HeadlessDB:
    """Minimal DB stub for headless (CLI) mode — no real persistence."""

    async def get_activation_chain(self, correlation_id: str) -> list[str]:
        return []

    async def add_to_chain(self, correlation_id: str, agent_id: str) -> None:
        pass

    async def store_proposal(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def poll_commands(self, limit: int) -> list[dict]:
        return []

    async def mark_command_done(self, cmd_id: str) -> None:
        pass


class _HeadlessServer:
    """Lightweight adapter for AgentRunner headless operation."""

    def __init__(self, event_store: Any) -> None:
        self.event_store = event_store
        self.db = _HeadlessDB()
        self.proposals: dict[str, Any] = {}
        self.subscriptions = None
        self.workspace = None

    def generate_correlation_id(self) -> str:
        return uuid.uuid4().hex[:12]

    async def emit_event(self, event: Any) -> Any:
        return event

    async def refresh_code_lenses(self) -> None:
        return None

    async def publish_diagnostics(self, uri: str, proposals: list[Any]) -> None:
        return None

    async def accept_proposal(self, proposal_id: str) -> None:
        return None

    async def emit_human_chat_event(self, *, agent_id: str, message: str, correlation_id: str) -> None:
        return None

    async def emit_rewrite_rejected_event(
        self,
        *,
        agent_id: str,
        proposal_id: str,
        feedback: str,
        correlation_id: str,
    ) -> None:
        return None

    async def emit_agent_error_event(self, *, agent_id: str, error: str, correlation_id: str) -> None:
        return None

    async def emit_agent_message_event(
        self,
        *,
        from_agent: str,
        to_agent: str,
        message: str,
        correlation_id: str,
    ) -> None:
        return None

    async def emit_rewrite_proposal_event(
        self,
        *,
        agent_id: str,
        proposal_id: str,
        diff: str,
        correlation_id: str,
    ) -> None:
        return None

    async def emit_agent_event(
        self,
        *,
        event_type: str,
        agent_id: str,
        correlation_id: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        return None
