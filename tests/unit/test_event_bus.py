"""Tests for the unified event bus."""

import pytest
import asyncio

from remora.event_bus import (
    EventBus,
    Event,
    AgentAction,
    ToolAction,
    get_event_bus,
)


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def clean_event_bus():
    """Reset global event bus before and after test."""
    import remora.event_bus as eb

    old_bus = eb._event_bus
    eb._event_bus = None
    yield
    eb._event_bus = old_bus


@pytest.mark.asyncio
async def test_publish_and_subscribe(event_bus):
    """Events should be delivered to subscribers."""
    received = []

    async def handler(event: Event):
        received.append(event)

    await event_bus.subscribe("agent:started", handler)

    await event_bus.publish(Event.agent_started(agent_id="test-123"))

    await asyncio.sleep(0.01)

    assert len(received) == 1
    assert received[0].agent_id == "test-123"


@pytest.mark.asyncio
async def test_wildcard_subscription(event_bus):
    """Wildcard patterns should match multiple events."""
    received = []

    async def handler(event: Event):
        received.append(event)

    await event_bus.subscribe("agent:*", handler)

    await event_bus.publish(Event.agent_started(agent_id="1"))
    await event_bus.publish(Event.agent_blocked(agent_id="2", question="What?"))
    await event_bus.publish(Event.tool_called(tool_name="test", call_id="call-1"))

    await asyncio.sleep(0.01)

    assert len(received) == 2


@pytest.mark.asyncio
async def test_stream_iteration(event_bus):
    """stream() should yield published events."""
    results = []

    async def producer():
        await event_bus.publish(Event.agent_started(agent_id="1"))
        await event_bus.publish(Event.agent_completed(agent_id="1"))

    async def consumer():
        async for event in event_bus.stream():
            results.append(event)
            if len(results) >= 2:
                break

    await asyncio.gather(producer(), consumer())

    assert len(results) == 2


@pytest.mark.asyncio
async def test_event_serialization(event_bus):
    """Events should serialize to JSON."""
    event = Event.agent_blocked(agent_id="test", question="Continue?")

    data = event.model_dump()
    assert data["category"] == "agent"
    assert data["action"] == "blocked"
    assert data["payload"]["question"] == "Continue?"

    json_str = event.model_dump_json()
    assert '"category":"agent"' in json_str
    assert '"action":"blocked"' in json_str


@pytest.mark.asyncio
async def test_event_type_property(event_bus):
    """Event type property should return human-readable string."""
    event = Event(category="agent", action="blocked", agent_id="123")
    assert event.type == "agent_blocked"


@pytest.mark.asyncio
async def test_event_subscription_key(event_bus):
    """Event subscription_key should return pattern string."""
    event = Event(category="agent", action="started", agent_id="123")
    assert event.subscription_key == "agent:started"


@pytest.mark.asyncio
async def test_convenience_constructors(event_bus):
    """All convenience constructors should work."""
    e1 = Event.agent_started(agent_id="1")
    assert e1.category == "agent"
    assert e1.action == AgentAction.STARTED

    e2 = Event.agent_blocked(agent_id="2", question="What?")
    assert e2.category == "agent"
    assert e2.action == AgentAction.BLOCKED
    assert e2.payload["question"] == "What?"

    e3 = Event.agent_resumed(agent_id="3", answer="yes")
    assert e3.action == "resumed"
    assert e3.payload["answer"] == "yes"

    e4 = Event.tool_called(tool_name="read_file", call_id="c1")
    assert e4.category == "tool"
    assert e4.payload["tool_name"] == "read_file"


@pytest.mark.asyncio
async def test_multiple_subscribers(event_bus):
    """Multiple handlers should all receive the event."""
    received1 = []
    received2 = []

    async def handler1(event):
        received1.append(event)

    async def handler2(event):
        received2.append(event)

    await event_bus.subscribe("agent:started", handler1)
    await event_bus.subscribe("agent:started", handler2)

    await event_bus.publish(Event.agent_started(agent_id="test"))

    await asyncio.sleep(0.01)

    assert len(received1) == 1
    assert len(received2) == 1


@pytest.mark.asyncio
async def test_unsubscribe(event_bus):
    """Unsubscribing should stop event delivery."""
    received = []

    async def handler(event):
        received.append(event)

    await event_bus.subscribe("agent:started", handler)
    await event_bus.publish(Event.agent_started(agent_id="1"))

    await asyncio.sleep(0.01)
    assert len(received) == 1

    await event_bus.unsubscribe("agent:started", handler)
    await event_bus.publish(Event.agent_started(agent_id="2"))

    await asyncio.sleep(0.01)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_get_event_bus_singleton(clean_event_bus):
    """get_event_bus should return singleton."""
    bus1 = get_event_bus()
    bus2 = get_event_bus()
    assert bus1 is bus2


@pytest.mark.asyncio
async def test_send_sse_format(event_bus):
    """send_sse should format event correctly."""
    event = Event.agent_started(agent_id="test")
    sse = await event_bus.send_sse(event)
    assert sse.startswith("data: ")
    assert sse.endswith("\n\n")
    assert '"category":"agent"' in sse
    assert '"action":"started"' in sse


@pytest.mark.asyncio
async def test_backpressure_on_queue(event_bus):
    """Queue should drop events when full."""
    small_bus = EventBus(max_queue_size=2)

    await small_bus.publish(Event.agent_started(agent_id="1"))
    await small_bus.publish(Event.agent_started(agent_id="2"))
    await small_bus.publish(Event.agent_started(agent_id="3"))
    await small_bus.publish(Event.agent_started(agent_id="4"))

    results = []

    async def consume():
        async for event in small_bus.stream():
            results.append(event)
            if len(results) >= 2:
                break

    await asyncio.wait_for(consume(), timeout=1.0)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_event_frozen(event_bus):
    """Events should be immutable."""
    event = Event.agent_started(agent_id="test")
    with pytest.raises(Exception):
        event.agent_id = "different"


@pytest.mark.asyncio
async def test_tool_events(event_bus):
    """Tool events should work correctly."""
    received = []

    async def handler(event):
        received.append(event)

    await event_bus.subscribe("tool:*", handler)

    await event_bus.publish(Event.tool_called(tool_name="read_file", call_id="call-1"))
    await event_bus.publish(Event.tool_result(tool_name="read_file", call_id="call-1", result="content"))

    await asyncio.sleep(0.01)

    assert len(received) == 2
    assert received[0].payload["tool_name"] == "read_file"
    assert received[1].action == ToolAction.COMPLETED
