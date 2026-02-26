"""Model adapter for specific model families."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.models.parsers import ResponseParser
from structured_agents.types import Message, ToolSchema


@dataclass
class ModelAdapter:
    """Adapts the kernel's generic tool-call loop to a specific model family."""

    name: str
    response_parser: ResponseParser
    constraint_pipeline: ConstraintPipeline | None = None
    format_messages: Callable[[list[Message]], list[dict[str, Any]]] | None = field(
        default=None
    )
    format_tools: Callable[[list[ToolSchema]], list[dict[str, Any]]] | None = field(
        default=None
    )

    def __post_init__(self) -> None:
        if self.format_messages is None:
            self.format_messages = self._default_format_messages
        if self.format_tools is None:
            self.format_tools = self._default_format_tools

    @staticmethod
    def _default_format_messages(messages: list[Message]) -> list[dict[str, Any]]:
        """Convert messages to OpenAI format. Tools are sent separately via the API."""
        return [msg.to_openai_format() for msg in messages]

    @staticmethod
    def _default_format_tools(tool_schemas: list[ToolSchema]) -> list[dict[str, Any]]:
        """Convert tool schemas to OpenAI tools format."""
        return [ts.to_openai_format() for ts in tool_schemas]
