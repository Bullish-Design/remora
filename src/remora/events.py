"""Unified event types for Remora.

This module defines all event types in the Remora ecosystem:
- Graph-level events (start, complete, errors)
- Agent-level events (start, complete, errors, human input)
- Kernel-level events from structured-agents

All events are frozen dataclasses for immutability and hashability.
"""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Union

from structured_agents.events import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)

if TYPE_CHECKING:
    from remora.discovery import CSTNode


# =============================================================================
# Remora Graph Events
# =============================================================================


@dataclass(frozen=True)
class GraphStartEvent:
    """Emitted when a graph execution begins."""

    graph_id: str
    node_count: int
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class GraphCompleteEvent:
    """Emitted when a graph execution completes successfully."""

    graph_id: str
    results: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class GraphErrorEvent:
    """Emitted when a graph execution fails."""

    graph_id: str
    error: str
    timestamp: float = field(default_factory=time.time)


# =============================================================================
# Agent Events
# =============================================================================


@dataclass(frozen=True)
class AgentStartEvent:
    """Emitted when an agent begins execution.

    Note: node field is typed as dict for now to avoid circular imports.
    The actual CSTNode type will be used in production.
    """

    graph_id: str
    agent_id: str
    node: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class AgentCompleteEvent:
    """Emitted when an agent completes successfully."""

    graph_id: str
    agent_id: str
    result: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class AgentErrorEvent:
    """Emitted when an agent fails."""

    graph_id: str
    agent_id: str
    error: str
    timestamp: float = field(default_factory=time.time)


# =============================================================================
# Human-in-the-Loop Events
# =============================================================================


@dataclass(frozen=True)
class HumanInputRequestEvent:
    """Emitted when an agent requests human input.

    The dashboard should display this to the user and wait for response.
    """

    graph_id: str
    agent_id: str
    request_id: str
    question: str
    options: list[str] | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class HumanInputResponseEvent:
    """Emitted when human responds to an input request.

    This event resolves the corresponding request's wait_for.
    """

    request_id: str
    response: str
    timestamp: float = field(default_factory=time.time)


# =============================================================================
# Union Type
# =============================================================================

RemoraEvent = Union[
    GraphStartEvent,
    GraphCompleteEvent,
    GraphErrorEvent,
    AgentStartEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    KernelStartEvent,
    KernelEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    TurnCompleteEvent,
]


__all__ = [
    "GraphStartEvent",
    "GraphCompleteEvent",
    "GraphErrorEvent",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    "KernelStartEvent",
    "KernelEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "TurnCompleteEvent",
    "RemoraEvent",
]
