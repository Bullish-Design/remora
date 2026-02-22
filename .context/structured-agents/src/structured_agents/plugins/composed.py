"""Composed plugin implementation using component protocols."""

from __future__ import annotations

from typing import Any

from structured_agents.grammar.artifacts import GrammarArtifact
from structured_agents.grammar.config import GrammarConfig
from structured_agents.plugins.components import (
    GrammarProvider,
    MessageFormatter,
    ResponseParser,
    ToolFormatter,
)
from structured_agents.plugins.protocol import ModelPlugin
from structured_agents.types import Message, ToolCall, ToolSchema


class ComposedModelPlugin(ModelPlugin):
    """Model plugin that delegates to component implementations."""

    def __init__(
        self,
        name: str,
        message_formatter: MessageFormatter,
        tool_formatter: ToolFormatter,
        response_parser: ResponseParser,
        grammar_provider: GrammarProvider,
    ) -> None:
        self._name = name
        self._message_formatter = message_formatter
        self._tool_formatter = tool_formatter
        self._response_parser = response_parser
        self._grammar_provider = grammar_provider

    @property
    def name(self) -> str:
        return self._name

    @property
    def supports_ebnf(self) -> bool:
        return self._grammar_provider.supports_mode("ebnf")

    @property
    def supports_structural_tags(self) -> bool:
        return self._grammar_provider.supports_mode("structural_tag")

    @property
    def supports_json_schema(self) -> bool:
        return self._grammar_provider.supports_mode("json_schema")

    def format_messages(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> list[dict[str, Any]]:
        return self._message_formatter.format_messages(messages, tools)

    def format_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        return self._tool_formatter.format_tools(tools)

    def build_grammar(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> GrammarArtifact | None:
        return self._grammar_provider.build_grammar(tools, config)

    def to_extra_body(self, artifact: GrammarArtifact | None) -> dict[str, Any] | None:
        return self._grammar_provider.to_extra_body(artifact)

    def parse_response(
        self, content: str | None, tool_calls_raw: list[dict[str, Any]] | None
    ) -> tuple[str | None, list[ToolCall]]:
        return self._response_parser.parse_response(content, tool_calls_raw)
