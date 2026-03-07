"""Unified event types for the Remora runtime."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Re-export structured-agents events
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

    from remora.core.code.discovery import CSTNode


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
    tags: tuple[str, ...] = ()  # Enables chained agent workflows (e.g. ("scaffold",))
    timestamp: float = Field(default_factory=time.time)


class AgentErrorEvent(_FrozenEvent):
    """Emitted when an agent fails."""

    graph_id: str
    agent_id: str
    error: str
    timestamp: float = Field(default_factory=time.time)


class AgentEvent(_FrozenEvent):
    """Generic agent-facing event envelope used by LSP/UI flows."""

    event_type: str
    correlation_id: str
    agent_id: str | None = None
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class HumanChatEvent(AgentEvent):
    """Human message directed to an agent."""

    to_agent: str = ""
    message: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict[str, Any]) -> dict[str, Any]:
        values.setdefault("event_type", "HumanChatEvent")
        to_agent = values.get("to_agent", "")
        if values.get("agent_id") is None:
            values["agent_id"] = to_agent
        values.setdefault("summary", f"Human message to {to_agent}")
        return values


class RewriteProposalEvent(AgentEvent):
    """Agent proposed a code rewrite."""

    proposal_id: str = ""
    diff: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict[str, Any]) -> dict[str, Any]:
        values.setdefault("event_type", "RewriteProposalEvent")
        values.setdefault("summary", f"Rewrite proposal from {values.get('agent_id', '')}")
        return values


class RewriteAppliedEvent(AgentEvent):
    """Rewrite proposal accepted and applied."""

    proposal_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict[str, Any]) -> dict[str, Any]:
        values.setdefault("event_type", "RewriteAppliedEvent")
        values.setdefault("summary", f"Proposal {values.get('proposal_id', '')} accepted")
        return values


class RewriteRejectedEvent(AgentEvent):
    """Rewrite proposal rejected with optional feedback."""

    proposal_id: str = ""
    feedback: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict[str, Any]) -> dict[str, Any]:
        values.setdefault("event_type", "RewriteRejectedEvent")
        values.setdefault("summary", "Proposal rejected with feedback")
        return values


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


class CursorFocusEvent(_FrozenEvent):
    """Cursor moved to focus on a specific agent (debounced)."""

    focused_agent_id: str | None
    file_path: str
    line: int
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

    @classmethod
    def from_cst_node(cls, node: CSTNode) -> NodeDiscoveredEvent:
        """Create from a CSTNode — single source of truth for field mapping."""
        from remora.core.code.discovery import compute_source_hash
        return cls(
            node_id=node.node_id,
            node_type=node.node_type,
            name=node.name,
            full_name=node.full_name,
            file_path=node.file_path,
            start_line=node.start_line,
            end_line=node.end_line,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
            source_code=node.text,
            source_hash=compute_source_hash(node.text),
            parent_id=node.parent_id,
        )


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


# ============================================================================
# Union Type for Pattern Matching
# ============================================================================

CoreEvent = (
    # Agent events
    AgentStartEvent
    | AgentCompleteEvent
    | AgentErrorEvent
    | AgentEvent
    | HumanChatEvent
    | RewriteProposalEvent
    | RewriteAppliedEvent
    | RewriteRejectedEvent
    |
    # Human-in-the-loop events
    HumanInputRequestEvent
    | HumanInputResponseEvent
    |
    # Reactive swarm events
    AgentMessageEvent
    | FileSavedEvent
    | ContentChangedEvent
    | CursorFocusEvent
    | ManualTriggerEvent
    |
    # Node lifecycle events
    NodeDiscoveredEvent
    | ScaffoldRequestEvent
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
    "AgentEvent",
    "HumanChatEvent",
    "RewriteProposalEvent",
    "RewriteAppliedEvent",
    "RewriteRejectedEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    # Reactive swarm events
    "AgentMessageEvent",
    "FileSavedEvent",
    "ContentChangedEvent",
    "CursorFocusEvent",
    "ManualTriggerEvent",
    # Node lifecycle events
    "NodeDiscoveredEvent",
    "ScaffoldRequestEvent",
    "NodeRemovedEvent",
    # Re-exports
    "KernelStartEvent",
    "KernelEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "TurnCompleteEvent",
    "CoreEvent",
]
