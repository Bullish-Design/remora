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
