import asyncio

from demo.ultimate_demo.state import DemoState
from demo.ultimate_demo.tools import LogUpdateTool


def test_log_update_tool_updates_state() -> None:
    state = DemoState.initial()
    tool = LogUpdateTool(state)
    result = asyncio.run(tool.execute({"update": "Kickoff done"}, None))
    assert "Kickoff done" in state.updates
    assert result.is_error is False
