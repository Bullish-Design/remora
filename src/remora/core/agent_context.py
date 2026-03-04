"""Typed agent execution context.

Replaces the untyped ``externals: dict[str, Any]`` pattern with a Pydantic
model whose fields carry explicit types for every callback and piece of
metadata that swarm tools and Grail scripts need at runtime.
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine

from pydantic import BaseModel, ConfigDict, Field

# Callback type aliases for readability
EmitEventFn = Callable[[str, Any], Coroutine[Any, Any, None]]
RegisterSubFn = Callable[[str, Any], Coroutine[Any, Any, None]]
UnsubscribeFn = Callable[[int], Coroutine[Any, Any, str]]
BroadcastFn = Callable[[str, str], Coroutine[Any, Any, str]]
QueryAgentsFn = Callable[[str | None], Coroutine[Any, Any, list[Any]]]


class AgentContext(BaseModel):
    """Typed execution context passed to swarm tools and Grail scripts.

    Replaces the old ``externals: dict[str, Any]`` bag-of-strings pattern.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent_id: str
    correlation_id: str | None = None

    # Swarm callbacks
    emit_event: EmitEventFn
    register_subscription: RegisterSubFn
    unsubscribe_subscription: UnsubscribeFn
    broadcast: BroadcastFn
    query_agents: QueryAgentsFn

    # Cairn file-system externals for Grail runtime
    cairn_externals: dict[str, Any] = Field(default_factory=dict)

    # State manager for persisting agent state (optional).
    # Typed as Any to avoid Pydantic forward-ref resolution issues;
    # at runtime this is a RemoraStateManager instance.
    state_manager: Any = None

    def as_externals(self) -> dict[str, Any]:
        """Return a flat dict for backward compatibility with Grail scripts.

        Merges swarm callback keys and cairn externals into one namespace,
        matching the old ``externals: dict[str, Any]`` layout that Grail
        scripts and some internal code still expect.
        """
        merged: dict[str, Any] = {}
        # Cairn externals first (read_file, write_file, etc.)
        merged.update(self.cairn_externals)
        # Swarm keys overlay
        merged["agent_id"] = self.agent_id
        merged["correlation_id"] = self.correlation_id
        merged["emit_event"] = self.emit_event
        merged["register_subscription"] = self.register_subscription
        merged["unsubscribe_subscription"] = self.unsubscribe_subscription
        merged["broadcast"] = self.broadcast
        merged["query_agents"] = self.query_agents
        return merged


__all__ = ["AgentContext"]
