"""NodeAgent event types for the companion system.

All events extend _FrozenEvent (Pydantic, frozen, timestamped).
These are emitted on the EventBus so the LSP server can react to them.
"""
from __future__ import annotations

import time

from pydantic import Field

from remora.core.events.agent_events import _FrozenEvent


class NodeAgentSidebarReady(_FrozenEvent):
    """Emitted when a node agent has composed its sidebar content.

    The LSP server subscribes to this event to push
    $/remora/companionSidebarUpdated to the Neovim client.
    """

    node_id: str
    markdown: str
    timestamp: float = Field(default_factory=time.time)


class NodeAgentExchangeIndexed(_FrozenEvent):
    """Emitted by SummarizerSwarm after indexing a chat exchange.

    The summary and tags are written into the node's workspace
    chat/index.json and also emitted here for observability.
    """

    node_id: str
    session_id: str
    summary: str
    tags: tuple[str, ...] = ()
    timestamp: float = Field(default_factory=time.time)


class NodeAgentLinkDiscovered(_FrozenEvent):
    """Emitted by LinkerSwarm when a cross-node connection is found.

    Written to the source node's links/links.json workspace file
    and also emitted on the EventBus for observability.
    """

    source_node_id: str
    target_node_id: str
    relationship: str
    confidence: float
    note: str = ""
    timestamp: float = Field(default_factory=time.time)


class NodeAgentNoteUpdated(_FrozenEvent):
    """Emitted by ReflectionSwarm after updating notes/agent_notes.md.

    note_type is one of: "agent_notes", "guide_understanding",
    "guide_refactoring", "guide_pitfalls".
    """

    node_id: str
    note_type: str
    timestamp: float = Field(default_factory=time.time)


class NodeAgentMessageReceived(_FrozenEvent):
    """Emitted when an agent receives an inter-agent message.

    Used by the LSP server to optionally notify the user that
    another node's agent sent a message.
    """

    target_node_id: str
    from_node_id: str
    content: str
    timestamp: float = Field(default_factory=time.time)


__all__ = [
    "NodeAgentSidebarReady",
    "NodeAgentExchangeIndexed",
    "NodeAgentLinkDiscovered",
    "NodeAgentNoteUpdated",
    "NodeAgentMessageReceived",
]
