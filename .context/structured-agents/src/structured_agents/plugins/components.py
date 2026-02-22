"""Component protocols for model plugins."""

from __future__ import annotations

from typing import Any, Protocol

from structured_agents.grammar.artifacts import GrammarArtifact
from structured_agents.grammar.config import GrammarConfig
from structured_agents.types import Message, ToolCall, ToolSchema


class MessageFormatter(Protocol):
    """Protocol for formatting model messages."""

    def format_messages(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> list[dict[str, Any]]:
        """Convert messages to model-specific API format."""
        ...


class ToolFormatter(Protocol):
    """Protocol for formatting tool schemas."""

    def format_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        """Convert tool schemas to model API format."""
        ...


class ResponseParser(Protocol):
    """Protocol for parsing model responses."""

    def parse_response(
        self, content: str | None, tool_calls_raw: list[dict[str, Any]] | None
    ) -> tuple[str | None, list[ToolCall]]:
        """Parse response content and tool calls."""
        ...


class GrammarProvider(Protocol):
    """Protocol for providing grammar constraints."""

    def supports_mode(self, mode: str) -> bool:
        """Return whether the grammar provider supports a mode."""
        ...

    def build_grammar(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> GrammarArtifact | None:
        """Build a grammar artifact for the given tools and config."""
        ...

    def to_extra_body(self, artifact: GrammarArtifact | None) -> dict[str, Any] | None:
        """Convert grammar artifact to vLLM extra_body payload."""
        ...
