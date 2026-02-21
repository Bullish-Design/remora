"""Tool call parsing utilities.

Provides fallback parsing when the model returns tool calls as JSON
in the content field instead of the structured tool_calls field.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParsedToolCall:
    """A tool call extracted from JSON content."""

    name: str
    arguments: dict[str, Any]

    @property
    def id(self) -> str:
        """Generate a synthetic ID for tool result pairing."""
        import uuid

        return f"parsed-{uuid.uuid4().hex[:8]}"


_FUNCTIONGEMMA_CALL_RE = re.compile(
    r"<start_function_call>call:(\w+)\{(.*?)\}<end_function_call>",
    re.DOTALL,
)
_FUNCTIONGEMMA_ARG_RE = re.compile(
    r"(\w+):<escape>(.*?)<escape>",
    re.DOTALL,
)


def parse_functiongemma_arguments(raw_args: str) -> dict[str, Any] | None:
    """Parse FunctionGemma-style arguments into a dict.

    Args:
        raw_args: Argument content inside the FunctionGemma braces.

    Returns:
        Parsed arguments dict, or None if not parseable.
    """
    if not raw_args:
        return {}
    matches = _FUNCTIONGEMMA_ARG_RE.findall(raw_args)
    if not matches:
        return None
    arguments: dict[str, Any] = {}
    for key, value in matches:
        try:
            arguments[key] = json.loads(value)
        except json.JSONDecodeError:
            arguments[key] = value
    return arguments


def _parse_functiongemma_call(content: str) -> ParsedToolCall | None:
    match = _FUNCTIONGEMMA_CALL_RE.search(content)
    if not match:
        return None
    name, raw_args = match.groups()
    arguments = parse_functiongemma_arguments(raw_args or "") or {}
    return ParsedToolCall(name=name, arguments=arguments)


def parse_tool_call_from_content(content: str) -> ParsedToolCall | None:
    """Attempt to parse a tool call from JSON content.

    Supports three formats:
    1. Direct: {"name": "tool_name", "arguments": {...}}
    2. Direct with parameters: {"name": "tool_name", "parameters": {...}}
    3. OpenAI array: {"tool_calls": [{"function": {"name": ..., "arguments": ...}}]}

    Args:
        content: The message content to parse.

    Returns:
        ParsedToolCall if parsing succeeds, None otherwise.
    """
    if not content or not content.strip():
        return None

    functiongemma_call = _parse_functiongemma_call(content)
    if functiongemma_call is not None:
        logger.debug("Parsed FunctionGemma format tool call: %s", functiongemma_call.name)
        return functiongemma_call

    try:
        parsed = json.loads(content.strip())
    except json.JSONDecodeError:
        logger.debug("Content is not valid JSON: %s", content[:100])
        return None

    if not isinstance(parsed, dict):
        logger.debug("Parsed JSON is not a dict: %s", type(parsed))
        return None

    if "name" in parsed:
        name = parsed["name"]
        arguments = parsed.get("arguments", parsed.get("parameters", {}))

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        if not isinstance(arguments, dict):
            arguments = {}

        logger.debug("Parsed direct format tool call: %s", name)
        return ParsedToolCall(name=name, arguments=arguments)

    if "tool_calls" in parsed:
        tool_calls = parsed["tool_calls"]
        if isinstance(tool_calls, list) and len(tool_calls) > 0:
            first_call = tool_calls[0]
            if isinstance(first_call, dict) and "function" in first_call:
                function = first_call["function"]
                name = function.get("name")
                arguments = function.get("arguments", {})

                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                if name and isinstance(arguments, dict):
                    logger.debug("Parsed OpenAI format tool call: %s", name)
                    return ParsedToolCall(name=name, arguments=arguments)

    logger.debug("No tool call pattern found in JSON")
    return None
