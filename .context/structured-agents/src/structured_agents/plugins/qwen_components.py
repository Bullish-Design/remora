"""Qwen component implementations."""

from __future__ import annotations

import json
import logging
from typing import Any

from structured_agents.grammar.artifacts import GrammarArtifact
from structured_agents.grammar.config import GrammarConfig
from structured_agents.plugins.components import (
    GrammarProvider,
    MessageFormatter,
    ResponseParser,
    ToolFormatter,
)
from structured_agents.types import Message, ToolCall, ToolSchema

logger = logging.getLogger(__name__)


class QwenMessageFormatter(MessageFormatter):
    """Message formatter for Qwen."""

    def format_messages(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> list[dict[str, Any]]:
        return [msg.to_openai_format() for msg in messages]


class QwenToolFormatter(ToolFormatter):
    """Tool formatter for Qwen."""

    def format_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        return [tool.to_openai_format() for tool in tools]


class QwenGrammarProvider(GrammarProvider):
    """Grammar provider for Qwen."""

    def supports_mode(self, mode: str) -> bool:
        return False

    def build_grammar(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> GrammarArtifact | None:
        return None

    def to_extra_body(self, artifact: GrammarArtifact | None) -> dict[str, Any] | None:
        return None


class QwenResponseParser(ResponseParser):
    """Response parser for Qwen."""

    def parse_response(
        self, content: str | None, tool_calls_raw: list[dict[str, Any]] | None
    ) -> tuple[str | None, list[ToolCall]]:
        tool_calls: list[ToolCall] = []

        if tool_calls_raw:
            for tc in tool_calls_raw:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = (
                        json.loads(args_str) if isinstance(args_str, str) else args_str
                    )
                except json.JSONDecodeError:
                    args = {}
                    logger.warning("Failed to parse arguments: %s", args_str)

                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", f"call_{id(tc)}"),
                        name=func.get("name", "unknown"),
                        arguments=args,
                    )
                )

        return content, tool_calls
