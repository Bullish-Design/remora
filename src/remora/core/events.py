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
# Graph-Level Events
# ============================================================================


@dataclass(frozen=True, slots=True)
class GraphStartEvent:
    """Emitted when graph execution begins."""

    graph_id: str
    node_count: int
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class GraphCompleteEvent:
    """Emitted when graph execution completes successfully."""

    graph_id: str
    completed_count: int
    failed_count: int
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class GraphErrorEvent:
    """Emitted when graph execution fails fatally."""

    graph_id: str
    error: str
    timestamp: float = field(default_factory=time.time)


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
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class AgentErrorEvent:
    """Emitted when an agent fails."""

    graph_id: str
    agent_id: str
    error: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class AgentSkippedEvent:
    """Emitted when an agent is skipped due to upstream failure."""

    graph_id: str
    agent_id: str
    reason: str
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
# Checkpoint Events
# ============================================================================


@dataclass(frozen=True, slots=True)
class CheckpointSavedEvent:
    """Emitted when a checkpoint is saved."""

    graph_id: str
    checkpoint_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class CheckpointRestoredEvent:
    """Emitted when execution resumes from checkpoint."""

    graph_id: str
    checkpoint_id: str
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# Union Type for Pattern Matching
# ============================================================================

RemoraEvent = (
    # Graph events
    GraphStartEvent
    | GraphCompleteEvent
    | GraphErrorEvent
    |
    # Agent events
    AgentStartEvent
    | AgentCompleteEvent
    | AgentErrorEvent
    | AgentSkippedEvent
    |
    # Human-in-the-loop events
    HumanInputRequestEvent
    | HumanInputResponseEvent
    |
    # Checkpoint events
    CheckpointSavedEvent
    | CheckpointRestoredEvent
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
    "GraphStartEvent",
    "GraphCompleteEvent",
    "GraphErrorEvent",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentSkippedEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    "CheckpointSavedEvent",
    "CheckpointRestoredEvent",
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
