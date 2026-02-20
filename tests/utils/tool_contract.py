"""Helpers for testing tool return contracts."""

from remora.context.contracts import ToolResult


def assert_valid_tool_result(result: dict) -> None:
    """Assert that a tool result follows the Two-Track contract."""
    assert "summary" in result, "Missing summary"
    assert "outcome" in result, "Missing outcome"

    assert result["outcome"] in ("success", "error", "partial"), f"Invalid outcome: {result['outcome']}"

    assert len(str(result["summary"])) < 200, f"Summary too long: {len(str(result['summary']))} chars"

    if "knowledge_delta" in result:
        assert isinstance(result["knowledge_delta"], dict), "knowledge_delta must be dict"

    ToolResult.model_validate(result)
