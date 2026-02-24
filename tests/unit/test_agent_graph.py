"""Tests for AgentNode and AgentGraph."""

import asyncio
import pytest

from remora.agent_graph import (
    AgentNode,
    AgentGraph,
    AgentState,
    AgentInbox,
    GraphExecutor,
    ErrorPolicy,
)
from remora.event_bus import EventBus, Event, AgentAction


@pytest.fixture
def event_bus():
    return EventBus()


def test_create_agent_node():
    """AgentNode should have sensible defaults."""
    node = AgentNode(id="test-1", name="lint", target="def foo(): pass", bundle="lint")

    assert node.state == AgentState.PENDING
    assert node.id == "test-1"
    assert node.bundle == "lint"


def test_agent_node_defaults():
    """AgentNode should have default values."""
    node = AgentNode(id="test-1", name="test", target="code")

    assert node.target_path is None
    assert node.target_type == "unknown"
    assert node.result is None
    assert node.error is None
    assert node.started_at is None
    assert node.completed_at is None
    assert node.upstream == []
    assert node.downstream == []


def test_agent_inbox_defaults():
    """AgentInbox should have default values."""
    inbox = AgentInbox()

    assert inbox.blocked is False
    assert inbox.blocked_question is None
    assert inbox.blocked_since is None
    assert inbox._pending_response is None


def test_agent_graph_add_agent():
    """Graph should track added agents."""
    graph = AgentGraph()
    graph.agent("lint", bundle="lint", target="def foo(): pass")

    assert "lint" in graph.agents()
    assert graph["lint"].bundle == "lint"


def test_agent_graph_dependencies():
    """Graph should track dependencies."""
    graph = AgentGraph()
    graph.agent("lint", bundle="lint", target="code")
    graph.agent("docstring", bundle="docstring", target="code")
    graph.after("lint").run("docstring")

    assert graph["lint"].downstream == [graph["docstring"].id]
    assert graph["docstring"].upstream == [graph["lint"].id]


def test_agent_graph_chaining():
    """Graph should support method chaining."""
    graph = AgentGraph()
    result = graph.agent("lint", bundle="lint", target="code")

    assert result is graph


def test_agent_graph_multiple_dependencies():
    """Graph should track multiple dependencies."""
    graph = AgentGraph()
    graph.agent("lint", bundle="lint", target="code")
    graph.agent("docstring", bundle="docstring", target="code")
    graph.agent("test", bundle="test", target="code")
    graph.after("lint").run("docstring", "test")

    assert graph["lint"].downstream == [graph["docstring"].id, graph["test"].id]
    assert graph["docstring"].upstream == [graph["lint"].id]
    assert graph["test"].upstream == [graph["lint"].id]


def test_agent_graph_getitem():
    """Graph should support dictionary-style access."""
    graph = AgentGraph()
    graph.agent("lint", bundle="lint", target="code")

    assert graph["lint"].name == "lint"


def test_agent_graph_id():
    """Graph should have a unique ID."""
    graph1 = AgentGraph()
    graph2 = AgentGraph()

    assert graph1.id != graph2.id


@pytest.mark.asyncio
async def test_agent_inbox_ask_user():
    """Inbox should block and resolve."""
    inbox = AgentInbox()

    async def resolve_later():
        await asyncio.sleep(0.01)
        inbox._resolve_response("yes")

    async def ask():
        return await inbox.ask_user("Continue?")

    result = await asyncio.gather(ask(), resolve_later())

    assert result[0] == "yes"
    assert inbox.blocked is False


@pytest.mark.asyncio
async def test_agent_inbox_ask_user_timeout():
    """Inbox should raise TimeoutError on timeout."""
    inbox = AgentInbox()

    with pytest.raises(asyncio.TimeoutError):
        await inbox.ask_user("Continue?", timeout=0.01)


@pytest.mark.asyncio
async def test_agent_inbox_send_message():
    """Inbox should queue messages."""
    inbox = AgentInbox()

    await inbox.send_message("Hello")
    await inbox.send_message("World")

    messages = await inbox.drain_messages()

    assert messages == ["Hello", "World"]


@pytest.mark.asyncio
async def test_agent_inbox_drain_empty():
    """Drain should return empty list for empty queue."""
    inbox = AgentInbox()

    messages = await inbox.drain_messages()

    assert messages == []


@pytest.mark.asyncio
async def test_agent_inbox_resolve_response_async():
    """Inbox should resolve response in async context."""
    inbox = AgentInbox()

    async def resolve_later():
        await asyncio.sleep(0.01)
        return await inbox.resolve_response_async("yes")

    async def ask():
        return await inbox.ask_user("Continue?")

    result = await asyncio.gather(ask(), resolve_later())

    assert result[0] == "yes"


@pytest.mark.asyncio
async def test_agent_node_cancel():
    """Agent should cancel properly."""
    event_bus = EventBus()
    node = AgentNode(id="test-1", name="test", target="code")

    await node.cancel(event_bus)

    assert node.state == AgentState.CANCELLED
    assert node.error == "Cancelled by user"


@pytest.mark.asyncio
async def test_graph_executor_creates_events(event_bus):
    """Executor should emit events."""
    received = []

    async def handler(event: Event):
        received.append(event)

    await event_bus.subscribe("agent:*", handler)

    graph = AgentGraph(event_bus)
    graph.agent("lint", bundle="lint", target="code")

    executor = graph.execute()
    await executor.run()

    started_events = [e for e in received if e.action == AgentAction.STARTED]
    completed_events = [e for e in received if e.action == AgentAction.COMPLETED]

    assert len(started_events) == 1
    assert len(completed_events) == 1
    assert started_events[0].agent_id == graph["lint"].id


@pytest.mark.asyncio
async def test_graph_executor_concurrent(event_bus):
    """Executor should run agents with concurrency limit."""
    graph = AgentGraph(event_bus)
    graph.agent("lint", bundle="lint", target="code")
    graph.agent("docstring", bundle="docstring", target="code")
    graph.agent("test", bundle="test", target="code")

    executor = graph.execute(max_concurrency=2)
    results = await executor.run()

    assert len(results) == 3
    assert all(agent.state == AgentState.COMPLETED for agent in graph.agents().values())


@pytest.mark.asyncio
async def test_graph_cancel():
    """Graph should cancel all agents."""
    event_bus = EventBus()
    graph = AgentGraph(event_bus)
    graph.agent("lint", bundle="lint", target="code")
    graph.agent("docstring", bundle="docstring", target="code")

    await graph.cancel()

    assert graph["lint"].state == AgentState.CANCELLED
    assert graph["docstring"].state == AgentState.CANCELLED


def test_error_policy_values():
    """ErrorPolicy should have correct values."""
    assert ErrorPolicy.STOP_GRAPH.value == "stop_graph"
    assert ErrorPolicy.SKIP_DOWNSTREAM.value == "skip_downstream"
    assert ErrorPolicy.CONTINUE.value == "continue"


def test_agent_state_values():
    """AgentState should have correct values."""
    assert AgentState.PENDING.value == "pending"
    assert AgentState.QUEUED.value == "queued"
    assert AgentState.RUNNING.value == "running"
    assert AgentState.BLOCKED.value == "blocked"
    assert AgentState.COMPLETED.value == "completed"
    assert AgentState.FAILED.value == "failed"
    assert AgentState.CANCELLED.value == "cancelled"


@pytest.mark.asyncio
async def test_agent_inbox_with_options():
    """Inbox ask_user should work with options."""
    inbox = AgentInbox()

    async def resolve_later():
        await asyncio.sleep(0.01)
        inbox._resolve_response("google")

    async def ask():
        return await inbox.ask_user("Which format?", timeout=1.0)

    result = await asyncio.gather(ask(), resolve_later())

    assert result[0] == "google"
    assert inbox.blocked_question is None
