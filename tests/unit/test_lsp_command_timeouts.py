from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from lsprotocol import types as lsp

from remora.lsp.handlers import commands


@pytest.mark.asyncio
async def test_resolve_agent_times_out_event_store_query() -> None:
    class SlowEventStore:
        async def get_node_at_position(self, uri: str, line: int):
            await asyncio.sleep(0.05)
            return None

    ls = SimpleNamespace(event_store=SlowEventStore())
    args = ({"uri": "file:///test.py", "line": 1},)

    with patch.object(commands, "RESOLVE_AGENT_TIMEOUT_SECONDS", 0.01):
        with pytest.raises(TimeoutError):
            await commands._resolve_agent(ls, args)


@pytest.mark.asyncio
async def test_cmd_chat_shows_error_on_resolve_timeout() -> None:
    ls = SimpleNamespace(
        event_store=object(),
        protocol=SimpleNamespace(notify=MagicMock()),
        window_show_message=MagicMock(),
    )
    args = ({"uri": "file:///test.py", "line": 1},)

    with patch.object(commands, "_resolve_agent", AsyncMock(side_effect=TimeoutError)):
        await commands.cmd_chat(ls, *args)

    ls.protocol.notify.assert_not_called()
    ls.window_show_message.assert_called_once()
    params = ls.window_show_message.call_args.args[0]
    assert isinstance(params, lsp.ShowMessageParams)
    assert params.type == lsp.MessageType.Error
    assert "Timed out" in params.message
