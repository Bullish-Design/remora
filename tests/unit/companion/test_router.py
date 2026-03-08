from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from remora.companion.router import NodeAgentRouter
from remora.core.events.interaction_events import CursorFocusEvent


@pytest.mark.asyncio
async def test_cursor_focus_resolves_node_with_get_node() -> None:
    registry = MagicMock()
    agent = MagicMock()
    agent.on_cursor_focus = AsyncMock()
    registry.get_or_create = AsyncMock(return_value=agent)

    event_store = MagicMock()
    node = MagicMock()
    event_store.nodes.get_node = AsyncMock(return_value=node)

    router = NodeAgentRouter(registry=registry, event_store=event_store)
    event = CursorFocusEvent(
        focused_agent_id="node_123",
        file_path="file:///tmp/example.py",
        line=42,
    )

    await router._on_cursor_focus(event)

    event_store.nodes.get_node.assert_awaited_once_with("node_123")
    registry.get_or_create.assert_awaited_once_with(node)
    agent.on_cursor_focus.assert_awaited_once()
