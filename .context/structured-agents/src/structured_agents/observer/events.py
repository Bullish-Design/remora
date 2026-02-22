"""Typed event dataclasses for the observer system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from structured_agents.types import TokenUsage


@dataclass(frozen=True, slots=True)
class ModelRequestEvent:
    """Fired before making a model request."""

    turn: int
    messages_count: int
    tools_count: int
    model: str


@dataclass(frozen=True, slots=True)
class ModelResponseEvent:
    """Fired after receiving a model response."""

    turn: int
    duration_ms: int
    content: str | None
    tool_calls_count: int
    usage: TokenUsage | None


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    """Fired before executing a tool."""

    turn: int
    tool_name: str
    call_id: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    """Fired after a tool execution completes."""

    turn: int
    tool_name: str
    call_id: str
    is_error: bool
    duration_ms: int
    output_preview: str


@dataclass(frozen=True, slots=True)
class TurnCompleteEvent:
    """Fired after a full turn (model call + all tool executions)."""

    turn: int
    tool_calls_count: int
    tool_results_count: int
    errors_count: int


@dataclass(frozen=True, slots=True)
class KernelStartEvent:
    """Fired when kernel.run() begins."""

    max_turns: int
    tools_count: int
    initial_messages_count: int


@dataclass(frozen=True, slots=True)
class KernelEndEvent:
    """Fired when kernel.run() completes."""

    turn_count: int
    termination_reason: str
    total_duration_ms: int
