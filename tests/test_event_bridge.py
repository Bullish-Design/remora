"""Tests for the event bridge."""

from unittest.mock import MagicMock

import pytest

structured_agents = pytest.importorskip("structured_agents")
ModelRequestEvent = structured_agents.ModelRequestEvent
ToolResultEvent = structured_agents.ToolResultEvent

from remora.event_bridge import RemoraEventBridge
from remora.events import EventName


class TestRemoraEventBridge:
    @pytest.fixture
    def emitter(self):
        return MagicMock()

    @pytest.fixture
    def context_manager(self):
        cm = MagicMock()
        cm.apply_event = MagicMock()
        return cm

    @pytest.fixture
    def bridge(self, emitter, context_manager):
        return RemoraEventBridge(
            emitter=emitter,
            context_manager=context_manager,
            agent_id="test-agent",
            node_id="test-node",
            operation="docstring",
        )

    @pytest.mark.asyncio
    async def test_model_request_event(self, bridge, emitter):
        event = ModelRequestEvent(
            turn=1,
            messages_count=3,
            tools_count=5,
            model="test-model",
        )

        await bridge.on_model_request(event)

        emitter.emit.assert_called_once()
        payload = emitter.emit.call_args[0][0]
        assert payload["event"] == EventName.MODEL_REQUEST
        assert payload["turn"] == 1
        assert payload["agent_id"] == "test-agent"

    @pytest.mark.asyncio
    async def test_tool_result_updates_context_manager(self, bridge, context_manager):
        event = ToolResultEvent(
            turn=2,
            tool_name="write_docstring",
            call_id="call_123",
            is_error=False,
            duration_ms=150,
            output_preview="Success",
        )

        await bridge.on_tool_result(event)

        context_manager.apply_event.assert_called_once()
        call_args = context_manager.apply_event.call_args[0][0]
        assert call_args["type"] == "tool_result"
        assert call_args["tool_name"] == "write_docstring"
