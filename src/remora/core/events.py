"""Unified domain event types for the Remora core runtime.

All events are frozen Pydantic models that can be pattern-matched.
Re-exports structured-agents events for unified event handling.

The LSP layer (``remora.lsp.models``) defines a separate set of event
classes with the ``Lsp`` prefix (``LspAgentEvent``, ``LspAgentMessageEvent``,
``LspAgentErrorEvent``, etc.).  Those are LSP protocol events stored in the
LSP DB for diagnostics, proposals, and editor notifications.  The events
in *this* module are **domain events** stored in the ``EventStore`` and
used for subscriptions, routing, and the core execution pipeline.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

# Re-export structured-agents events
from structured_agents.events import (
    KernelStartEvent,
    KernelEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    TurnCompleteEvent,
)

if TYPE_CHECKING:
    from remora.core.discovery import CSTNode
    from structured_agents.types import RunResult


# ============================================================================
# Base
# ============================================================================


class _FrozenEvent(BaseModel):
    """Common base with frozen config for all Remora events."""

    model_config = ConfigDict(frozen=True)


# ============================================================================
# Agent-Level Events
# ============================================================================


class AgentStartEvent(_FrozenEvent):
    """Emitted when an agent begins execution."""

    graph_id: str
    agent_id: str
    node_name: str
    trigger_event_type: str = ""
    timestamp: float = Field(default_factory=time.time)


class AgentCompleteEvent(_FrozenEvent):
    """Emitted when an agent completes successfully."""

    graph_id: str
    agent_id: str
    result_summary: str
    response: str = ""  # Full response content for display
    timestamp: float = Field(default_factory=time.time)


class AgentErrorEvent(_FrozenEvent):
    """Emitted when an agent fails."""

    graph_id: str
    agent_id: str
    error: str
    timestamp: float = Field(default_factory=time.time)


# ============================================================================
# Human-in-the-Loop Events (replaces broken interactive/ IPC)
# ============================================================================


class HumanInputRequestEvent(_FrozenEvent):
    """Agent is blocked waiting for human input."""

    graph_id: str
    agent_id: str
    request_id: str
    question: str
    options: tuple[str, ...] | None = None
    timestamp: float = Field(default_factory=time.time)


class HumanInputResponseEvent(_FrozenEvent):
    """Human has responded to an input request."""

    request_id: str
    response: str
    timestamp: float = Field(default_factory=time.time)


# ============================================================================
# Reactive Swarm Events (for subscription-based routing)
# ============================================================================


class AgentMessageEvent(_FrozenEvent):
    """Message sent between agents."""

    from_agent: str
    to_agent: str
    content: str
    tags: tuple[str, ...] = ()
    correlation_id: str | None = None
    timestamp: float = Field(default_factory=time.time)


class FileSavedEvent(_FrozenEvent):
    """A file was saved to disk."""

    path: str
    timestamp: float = Field(default_factory=time.time)


class ContentChangedEvent(_FrozenEvent):
    """File content was modified."""

    path: str
    diff: str | None = None
    timestamp: float = Field(default_factory=time.time)


class ManualTriggerEvent(_FrozenEvent):
    """Manual trigger to start an agent."""

    to_agent: str
    reason: str
    timestamp: float = Field(default_factory=time.time)


# ============================================================================
# Node Lifecycle Events (for EventLog projection -> nodes table)
# ============================================================================


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


class NodeRemovedEvent(_FrozenEvent):
    """Emitted when a code node is no longer found in source."""

    node_id: str
    timestamp: float = Field(default_factory=time.time)


# ============================================================================
# Union Type for Pattern Matching
# ============================================================================

RemoraEvent = (
    # Agent events
    AgentStartEvent
    | AgentCompleteEvent
    | AgentErrorEvent
    |
    # Human-in-the-loop events
    HumanInputRequestEvent
    | HumanInputResponseEvent
    |
    # Reactive swarm events
    AgentMessageEvent
    | FileSavedEvent
    | ContentChangedEvent
    | ManualTriggerEvent
    |
    # Node lifecycle events
    NodeDiscoveredEvent
    | NodeRemovedEvent
    |
    # Re-exported structured-agents events
    KernelStartEvent
    | KernelEndEvent
    | ToolCallEvent
    | ToolResultEvent
    | ModelRequestEvent
    | ModelResponseEvent
    | TurnCompleteEvent
)

__all__ = [
    # Remora events
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    # Reactive swarm events
    "AgentMessageEvent",
    "FileSavedEvent",
    "ContentChangedEvent",
    "ManualTriggerEvent",
    # Node lifecycle events
    "NodeDiscoveredEvent",
    "NodeRemovedEvent",
    # Re-exports
    "KernelStartEvent",
    "KernelEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "TurnCompleteEvent",
    # Union type
    "RemoraEvent",
]
