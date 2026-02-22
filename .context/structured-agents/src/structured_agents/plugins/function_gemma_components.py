"""FunctionGemma component implementations."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from structured_agents.grammar.artifacts import (
    EBNFGrammar,
    GrammarArtifact,
    StructuralTagGrammar,
)
from structured_agents.grammar.builders.function_gemma import (
    FunctionGemmaGrammarBuilder,
)
from structured_agents.grammar.builders.schema_aware_function_gemma import (
    FunctionGemmaSchemaGrammarBuilder,
)
from structured_agents.grammar.config import GrammarConfig
from structured_agents.plugins.components import (
    GrammarProvider,
    MessageFormatter,
    ResponseParser,
    ToolFormatter,
)
from structured_agents.types import Message, ToolCall, ToolSchema

logger = logging.getLogger(__name__)


class FunctionGemmaMessageFormatter(MessageFormatter):
    """Message formatter for FunctionGemma."""

    def format_messages(
        self, messages: list[Message], tools: list[ToolSchema]
    ) -> list[dict[str, Any]]:
        return [msg.to_openai_format() for msg in messages]


class FunctionGemmaToolFormatter(ToolFormatter):
    """Tool formatter for FunctionGemma."""

    def format_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        return [tool.to_openai_format() for tool in tools]


class FunctionGemmaGrammarProvider(GrammarProvider):
    """Grammar provider for FunctionGemma."""

    def __init__(self) -> None:
        self._grammar_builder = FunctionGemmaGrammarBuilder()
        self._schema_grammar_builder = FunctionGemmaSchemaGrammarBuilder()

    def supports_mode(self, mode: str) -> bool:
        return self._grammar_builder.supports_mode(
            mode
        ) or self._schema_grammar_builder.supports_mode(mode)

    def build_grammar(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> GrammarArtifact | None:
        if config.mode == "json_schema":
            return self._schema_grammar_builder.build(tools, config)
        return self._grammar_builder.build(tools, config)

    def to_extra_body(self, artifact: GrammarArtifact | None) -> dict[str, Any] | None:
        if artifact is None:
            return None

        if isinstance(artifact, (EBNFGrammar, StructuralTagGrammar)):
            return artifact.to_vllm_payload()

        raise ValueError(f"Unsupported artifact type: {type(artifact)}")


class FunctionGemmaResponseParser(ResponseParser):
    """Response parser for FunctionGemma."""

    _TOOL_CALL_PATTERN = re.compile(
        r"<start_function_call>call:([a-zA-Z_][a-zA-Z0-9_-]*)\{([^}]*)\}<end_function_call>"
    )

    def parse_response(
        self, content: str | None, tool_calls_raw: list[dict[str, Any]] | None
    ) -> tuple[str | None, list[ToolCall]]:
        tool_calls: list[ToolCall] = []

        if tool_calls_raw:
            for tc in tool_calls_raw:
                try:
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "{}")
                    args = (
                        json.loads(args_str) if isinstance(args_str, str) else args_str
                    )
                    tool_calls.append(
                        ToolCall(
                            id=tc.get("id", f"call_{id(tc)}"),
                            name=func.get("name", "unknown"),
                            arguments=args,
                        )
                    )
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Failed to parse tool call: %s", exc)
            return content, tool_calls

        if content:
            matches = self._TOOL_CALL_PATTERN.findall(content)
            for name, args_str in matches:
                args = self._parse_arguments(args_str)
                tool_calls.append(ToolCall.create(name=name, arguments=args))

            if tool_calls:
                return None, tool_calls

        return content, tool_calls

    def _parse_arguments(self, args_str: str) -> dict[str, Any]:
        args: dict[str, Any] = {}

        if not args_str.strip():
            return args

        try:
            json_str = (
                "{" + args_str + "}" if not args_str.startswith("{") else args_str
            )
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        escape_pattern = re.compile(r"(\w+):(?:<escape>([^<]*)<escape>|([^,}]+))")

        for match in escape_pattern.finditer(args_str):
            key = match.group(1)
            value = match.group(2) if match.group(2) is not None else match.group(3)

            try:
                args[key] = json.loads(value)
            except json.JSONDecodeError:
                args[key] = value.strip().strip("\"'")

        return args
