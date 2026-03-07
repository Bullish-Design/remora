import asyncio
import logging

import pytest
from structured_agents.events import ModelResponseEvent, ToolCallEvent, ToolResultEvent

from remora.core.events.event_bus import EventBus
from remora.core.events import CoreEvent, ScaffoldRequestEvent


@pytest.mark.asyncio
async def test_emit_notifies_subscribers() -> None:
    bus = EventBus()
    received: list[ToolCallEvent] = []

    async def handler(event: CoreEvent) -> None:
        if isinstance(event, ToolCallEvent):
            received.append(event)

    bus.subscribe(ToolCallEvent, handler)

    await bus.emit(ToolCallEvent(turn=1, tool_name="read_file", call_id="call-1", arguments={}))

    assert len(received) == 1
    assert received[0].tool_name == "read_file"
    assert received[0].call_id == "call-1"


@pytest.mark.asyncio
async def test_stream_filters_by_type() -> None:
    bus = EventBus()
    results: list[ToolCallEvent] = []

    async def producer() -> None:
        await bus.emit(ModelResponseEvent(turn=1, duration_ms=0, content="ignored", tool_calls_count=0, usage=None))
        await bus.emit(ToolCallEvent(turn=1, tool_name="foo", call_id="foo-1", arguments={}))
        await bus.emit(ToolCallEvent(turn=2, tool_name="bar", call_id="bar-1", arguments={}))

    async def consumer() -> None:
        async with bus.stream(ToolCallEvent) as events:
            async for event in events:
                assert isinstance(event, ToolCallEvent)
                results.append(event)
                if len(results) >= 2:
                    break

    consumer_task = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    await producer()
    await consumer_task

    assert [event.call_id for event in results] == ["foo-1", "bar-1"]


@pytest.mark.asyncio
async def test_wait_for_predicate_matching_event() -> None:
    bus = EventBus()

    async def waiter() -> ToolResultEvent:
        return await bus.wait_for(
            ToolResultEvent,
            lambda event: event.call_id == "call-1",
            timeout=1.0,
        )

    waiter_task = asyncio.create_task(waiter())
    await asyncio.sleep(0)

    await bus.emit(
        ToolResultEvent(
            turn=1,
            tool_name="read_file",
            call_id="call-1",
            is_error=False,
            duration_ms=0,
            output_preview="ok",
        )
    )
    result = await waiter_task

    assert result.output_preview == "ok"
    assert result.tool_name == "read_file"


@pytest.mark.asyncio
async def test_emit_noisy_events_log_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    bus = EventBus()
    caplog.set_level(logging.DEBUG, logger="remora.core.events.event_bus")

    await bus.emit(
        ScaffoldRequestEvent(
            node_id="rm_stub",
            to_agent="rm_stub",
            node_type="function",
        )
    )

    debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("EventBus.emit: ScaffoldRequestEvent" in msg for msg in debug_messages)
    assert not any("EventBus.emit: ScaffoldRequestEvent" in msg for msg in info_messages)
