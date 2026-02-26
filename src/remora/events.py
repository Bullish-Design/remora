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

if TYPE_CHECKING:
    from remora.discovery import CSTNode


# =============================================================================
# Structured-Agents Kernel Events (stubs for compatibility)
# =============================================================================


@dataclass(frozen=True)
class KernelStartEvent:
    """Kernel started event from structured-agents."""

    graph_id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class KernelEndEvent:
    """Kernel ended event from structured-agents."""

    graph_id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolCallEvent:
    """Tool was called event from structured-agents."""

    name: str = ""
    call_id: str = ""
    arguments: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolResultEvent:
    """Tool result event from structured-agents."""

    name: str = ""
    call_id: str = ""
    output: Any = None
    is_error: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ModelRequestEvent:
    """Model request event from structured-agents."""

    prompt: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ModelResponseEvent:
    """Model response event from structured-agents."""

    response: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class RestartEvent:
    """Kernel restart event from structured-agents."""

    reason: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TurnComplete:
    """Turn complete event from structured-agents."""

    turn_count: int = 0
    timestamp: float = field(default_factory=time.time)


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
    RestartEvent,
    TurnComplete,
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
    "RestartEvent",
    "TurnComplete",
    "RemoraEvent",
]
