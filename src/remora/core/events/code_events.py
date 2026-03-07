"""Node lifecycle events (discovery, scaffold, removal)."""

from __future__ import annotations

import time

from pydantic import Field

from remora.core.events.agent_events import _FrozenEvent


class NodeDiscoveredEvent(_FrozenEvent):
    """Emitted when a code node is discovered or re-discovered."""

    node_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    source_code: str
    source_hash: str
    parent_id: str | None = None
    start_byte: int = 0
    end_byte: int = 0
    timestamp: float = Field(default_factory=time.time)


class ScaffoldRequestEvent(_FrozenEvent):
    """Emitted when a scaffold node is created and needs initialization.

    Triggers the scaffold lifecycle: the node gathers context from its
    parent/siblings and fills itself in via rewrite_self().

    ``to_agent`` is set to ``node_id`` so that the existing direct-message
    subscription (``SubscriptionPattern(to_agent=agent_id)``) routes this
    event to the correct agent without needing a separate subscription.
    """

    node_id: str
    to_agent: str  # same as node_id — enables subscription routing
    node_type: str
    parent_id: str | None = None
    intent: str = ""  # Optional human-provided hint (e.g. "HTTP client class")
    timestamp: float = Field(default_factory=time.time)


class NodeRemovedEvent(_FrozenEvent):
    """Emitted when a code node is no longer found in source."""

    node_id: str
    timestamp: float = Field(default_factory=time.time)


__all__ = [
    "NodeDiscoveredEvent",
    "ScaffoldRequestEvent",
    "NodeRemovedEvent",
]
