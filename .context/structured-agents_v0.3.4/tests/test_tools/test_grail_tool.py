# tests/test_tools/test_grail_tool.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from structured_agents.tools.protocol import Tool
from structured_agents.tools.grail import GrailTool


@pytest.mark.asyncio
async def test_grail_tool_execute():
    from structured_agents.types import ToolCall

    mock_script = MagicMock()
    mock_script.name = "test_tool"
    mock_script.run = AsyncMock(return_value={"result": 42})

    tool = GrailTool(script=mock_script, limits=None)

    assert tool.schema.name == "test_tool"

    context = ToolCall(id="call_123", name="test_tool", arguments={"a": 1})

    result = await tool.execute({"a": 1}, context)
    assert result.is_error == False
    assert "42" in result.output
