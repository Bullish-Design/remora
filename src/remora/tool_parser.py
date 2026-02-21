"""Helpers for parsing FunctionGemma argument strings."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

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


def parse_tool_call_from_content(content: str) -> None:
    """No-op fallback parsing when grammar enforcement is standard."""
    logger.debug("Skipping content tool-call parsing; grammar enforced.")
    return None
