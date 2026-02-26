"""Event types for unified event model."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Union
from structured_agents.types import TokenUsage


@dataclass(frozen=True)
class KernelStartEvent:
    max_turns: int
    tools_count: int
    initial_messages_count: int


@dataclass(frozen=True)
class KernelEndEvent:
    turn_count: int
    termination_reason: str
    total_duration_ms: int


@dataclass(frozen=True)
class ModelRequestEvent:
    turn: int
    messages_count: int
    tools_count: int
    model: str


@dataclass(frozen=True)
class ModelResponseEvent:
    turn: int
    duration_ms: int
    content: str | None
    tool_calls_count: int
    usage: TokenUsage | None


@dataclass(frozen=True)
class ToolCallEvent:
    turn: int
    tool_name: str
    call_id: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResultEvent:
    turn: int
    tool_name: str
    call_id: str
    is_error: bool
    duration_ms: int
    output_preview: str


@dataclass(frozen=True)
class TurnCompleteEvent:
    turn: int
    tool_calls_count: int
    tool_results_count: int
    errors_count: int


Event = Union[
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
]
