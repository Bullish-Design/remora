"""Qwen component implementations."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from structured_agents.grammar.artifacts import (
    EBNFGrammar,
    GrammarArtifact,
    JsonSchemaGrammar,
    StructuralTagGrammar,
)
from structured_agents.grammar.builders.qwen3 import Qwen3GrammarBuilder
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
    """Grammar provider for Qwen3 models."""

    def __init__(self) -> None:
        self._grammar_builder = Qwen3GrammarBuilder()

    def supports_mode(self, mode: str) -> bool:
        return self._grammar_builder.supports_mode(mode)

    def build_grammar(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> GrammarArtifact | None:
        return self._grammar_builder.build(tools, config)

    def to_extra_body(self, artifact: GrammarArtifact | None) -> dict[str, Any] | None:
        if artifact is None:
            return None

        if isinstance(artifact, (EBNFGrammar, StructuralTagGrammar, JsonSchemaGrammar)):
            return artifact.to_vllm_payload()

        raise ValueError(f"Unsupported artifact type: {type(artifact)}")


class QwenResponseParser(ResponseParser):
    """Response parser for Qwen3."""

    _TOOL_CALL_PATTERN = re.compile(
        r"<function=([a-zA-Z_][a-zA-Z0-9_-]*)>"
        r"((?:<parameter=[^>]+>[^<]*</parameter>)*)"
        r"</function>"
    )

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

        if not tool_calls and content:
            matches = self._TOOL_CALL_PATTERN.findall(content)
            for name, params_str in matches:
                args = self._parse_qwen_xml_parameters(params_str)
                tool_calls.append(ToolCall.create(name=name, arguments=args))

            if tool_calls:
                return None, tool_calls

        return content, tool_calls

    def _parse_qwen_xml_parameters(self, params_str: str) -> dict[str, Any]:
        """Parse Qwen XML parameter format: <parameter=name>value</parameter>"""
        args = {}
        param_pattern = r"<parameter=([^>]+)>([^<]*)</parameter>"
        for match in re.finditer(param_pattern, params_str):
            key = match.group(1)
            value = match.group(2)
            try:
                args[key] = json.loads(value)
            except json.JSONDecodeError:
                args[key] = value
        return args
