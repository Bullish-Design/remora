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

    def generate_correlation_id(self) -> str:
        return uuid.uuid4().hex[:12]
