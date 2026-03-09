"""Agent lifecycle, proposal, chat, and human-in-the-loop events."""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _FrozenEvent(BaseModel):
    """Common base with frozen config for all Remora events."""

    model_config = ConfigDict(frozen=True)


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


class AgentTextResponseEvent(_FrozenEvent):
    """Final text response from an agent turn, displayed in the chat panel."""

    event_type: str = "AgentTextResponse"
    agent_id: str
    correlation_id: str
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
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


__all__ = [
    "_FrozenEvent",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentTextResponseEvent",
    "AgentEvent",
    "HumanChatEvent",
    "RewriteProposalEvent",
    "RewriteAppliedEvent",
    "RewriteRejectedEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
]
