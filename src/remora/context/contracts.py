"""Tool return contract definitions.

This module defines the expected structure for tool results in the
Two-Track Memory system. Tools should return results conforming
to ToolResult schema for optimal context management.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standard tool result structure for Two-Track Memory.

    Tools should return this structure to enable proper summary
    extraction and knowledge management.
    """

    result: Any
    """The full raw result (goes to Long Track only)."""

    summary: str
    """Human-readable summary (1-2 sentences, goes to Short Track)."""

    knowledge_delta: dict[str, Any] = Field(default_factory=dict)
    """Key-value pairs to update in Decision Packet knowledge."""

    outcome: Literal["success", "error", "partial"] = "success"
    """Overall outcome of the operation."""

    error: str | None = None
    """Error message if outcome is 'error'."""


def make_success_result(
    result: Any,
    summary: str,
    knowledge_delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper to create a successful tool result."""
    return ToolResult(
        result=result,
        summary=summary,
        knowledge_delta=knowledge_delta or {},
        outcome="success",
    ).model_dump()


def make_error_result(
    error: str,
    summary: str | None = None,
) -> dict[str, Any]:
    """Helper to create an error tool result."""
    return ToolResult(
        result=None,
        summary=summary or f"Error: {error}",
        outcome="error",
        error=error,
    ).model_dump()


def make_partial_result(
    result: Any,
    summary: str,
    knowledge_delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper to create a partial success tool result."""
    return ToolResult(
        result=result,
        summary=summary,
        knowledge_delta=knowledge_delta or {},
        outcome="partial",
    ).model_dump()
