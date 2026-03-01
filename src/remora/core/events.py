"""Unified event types for Remora.

All events are frozen dataclasses that can be pattern-matched.
Re-exports structured-agents events for unified event handling.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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
# Agent-Level Events
# ============================================================================


@dataclass(frozen=True, slots=True)
class AgentStartEvent:
    """Emitted when an agent begins execution."""

    graph_id: str
    agent_id: str
    node_name: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class AgentCompleteEvent:
    """Emitted when an agent completes successfully."""

    graph_id: str
    agent_id: str
    result_summary: str
    response: str = ""  # Full response content for display
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class AgentErrorEvent:
    """Emitted when an agent fails."""

    graph_id: str
    agent_id: str
    error: str
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# Human-in-the-Loop Events (replaces broken interactive/ IPC)
# ============================================================================


@dataclass(frozen=True, slots=True)
class HumanInputRequestEvent:
    """Agent is blocked waiting for human input."""

    graph_id: str
    agent_id: str
    request_id: str
    question: str
    options: tuple[str, ...] | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class HumanInputResponseEvent:
    """Human has responded to an input request."""

    request_id: str
    response: str
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# Reactive Swarm Events (for subscription-based routing)
# ============================================================================


@dataclass(frozen=True, slots=True)
class AgentMessageEvent:
    """Message sent between agents."""

    from_agent: str
    to_agent: str
    content: str
    tags: list[str] = field(default_factory=list)
    correlation_id: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class FileSavedEvent:
    """A file was saved to disk."""

    path: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class ContentChangedEvent:
    """File content was modified."""

    path: str
    diff: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class ManualTriggerEvent:
    """Manual trigger to start an agent."""

    to_agent: str
    reason: str
    timestamp: float = field(default_factory=time.time)


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
