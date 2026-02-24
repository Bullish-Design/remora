"""Tests for workspace IPC coordinator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from remora.interactive.coordinator import WorkspaceInboxCoordinator, QuestionPayload
from remora.event_bus import EventBus, Event


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def coordinator(event_bus):
    return WorkspaceInboxCoordinator(event_bus=event_bus, poll_interval=0.05)


@pytest.fixture
def mock_workspace():
    workspace = AsyncMock()
    workspace.kv.list = AsyncMock(return_value=[])
    workspace.kv.get = AsyncMock(return_value=None)
    workspace.kv.set = AsyncMock()
    return workspace


@pytest.mark.asyncio
async def test_coordinator_initialization(event_bus):
    """Coordinator should initialize with event bus."""
    coordinator = WorkspaceInboxCoordinator(event_bus)
    assert coordinator.event_bus is event_bus
    assert coordinator._poll_interval == 0.5


@pytest.mark.asyncio
async def test_coordinator_custom_poll_interval(event_bus):
    """Coordinator should use custom poll interval."""
    coordinator = WorkspaceInboxCoordinator(event_bus, poll_interval=0.1)
    assert coordinator._poll_interval == 0.1


@pytest.mark.asyncio
async def test_coordinator_emits_blocked_event(coordinator, mock_workspace):
    """Coordinator should emit AGENT_BLOCKED when question is pending."""
    received_events = []

    async def handler(event: Event):
        received_events.append(event)

    await coordinator.event_bus.subscribe("agent:blocked", handler)

    mock_workspace.kv.list = AsyncMock(return_value=[{"key": "outbox:question:abc123"}])
    mock_workspace.kv.get = AsyncMock(
        return_value={
            "question": "Which format?",
            "options": ["google", "numpy"],
            "status": "pending",
            "created_at": "2026-02-23T10:00:00",
            "timeout": 300,
        }
    )

    await coordinator.watch_workspace("agent-1", mock_workspace)
    await asyncio.sleep(0.15)

    assert len(received_events) >= 1
    assert received_events[0].payload["question"] == "Which format?"
    assert received_events[0].payload["options"] == ["google", "numpy"]
    assert received_events[0].payload["msg_id"] == "abc123"


@pytest.mark.asyncio
async def test_coordinator_respond_writes_to_inbox(coordinator, mock_workspace):
    """Coordinator should write response to workspace inbox."""
    await coordinator.respond(agent_id="agent-1", msg_id="abc123", answer="google", workspace=mock_workspace)

    mock_workspace.kv.set.assert_called_once()
    call_args = mock_workspace.kv.set.call_args
    assert call_args[0][0] == "inbox:response:abc123"
    assert call_args[0][1]["answer"] == "google"


@pytest.mark.asyncio
async def test_coordinator_respond_emits_resumed_event(coordinator, mock_workspace):
    """Coordinator should emit AGENT_RESUMED when responding."""
    received_events = []
    await coordinator.event_bus.subscribe("agent:resumed", lambda e: received_events.append(e))

    await coordinator.respond(agent_id="agent-1", msg_id="abc123", answer="google", workspace=mock_workspace)

    assert len(received_events) == 1
    assert received_events[0].agent_id == "agent-1"
    assert received_events[0].payload["answer"] == "google"


@pytest.mark.asyncio
async def test_coordinator_stop_watching_cleans_up(coordinator, mock_workspace):
    """Stop watching should cancel the watcher task."""
    await coordinator.watch_workspace("agent-1", mock_workspace)
    assert "agent-1" in coordinator._watchers

    await coordinator.stop_watching("agent-1")
    assert "agent-1" not in coordinator._watchers


@pytest.mark.asyncio
async def test_coordinator_stop_all(coordinator, mock_workspace):
    """Stop all should cancel all watchers."""
    await coordinator.watch_workspace("agent-1", mock_workspace)
    await coordinator.watch_workspace("agent-2", mock_workspace)
    assert len(coordinator._watchers) == 2

    await coordinator.stop_all()
    assert len(coordinator._watchers) == 0


@pytest.mark.asyncio
async def test_coordinator_multiple_agents(coordinator, mock_workspace):
    """Coordinator should handle multiple agent workspaces."""
    received_events = []

    async def handler(event: Event):
        received_events.append(event)

    await coordinator.event_bus.subscribe("agent:blocked", handler)

    mock_workspace.kv.list = AsyncMock(
        return_value=[{"key": "outbox:question:abc123"}, {"key": "outbox:question:def456"}]
    )
    mock_workspace.kv.get = AsyncMock(
        return_value={
            "question": "Which format?",
            "options": None,
            "status": "pending",
            "created_at": "2026-02-23T10:00:00",
            "timeout": 300,
        }
    )

    await coordinator.watch_workspace("agent-1", mock_workspace)
    await asyncio.sleep(0.15)

    assert len(received_events) >= 2


@pytest.mark.asyncio
async def test_coordinator_ignores_non_pending_questions(coordinator, mock_workspace):
    """Coordinator should not emit events for answered questions."""
    received_events = []
    await coordinator.event_bus.subscribe("agent:blocked", lambda e: received_events.append(e))

    mock_workspace.kv.list = AsyncMock(return_value=[{"key": "outbox:question:abc123"}])
    mock_workspace.kv.get = AsyncMock(
        return_value={
            "question": "Which format?",
            "options": None,
            "status": "answered",
            "created_at": "2026-02-23T10:00:00",
            "timeout": 300,
        }
    )

    await coordinator.watch_workspace("agent-1", mock_workspace)
    await asyncio.sleep(0.15)

    assert len(received_events) == 0


def test_question_payload_model():
    """QuestionPayload should parse correctly."""
    payload = QuestionPayload(
        question="What?",
        options=["a", "b"],
        status="pending",
        created_at="2026-02-23T10:00:00",
        timeout=300.0,
        msg_id="abc123",
    )

    assert payload.question == "What?"
    assert payload.options == ["a", "b"]
    assert payload.status == "pending"
    assert payload.msg_id == "abc123"


def test_question_payload_without_options():
    """QuestionPayload should work without options."""
    payload = QuestionPayload(
        question="What?",
        options=None,
        status="pending",
        created_at="2026-02-23T10:00:00",
        timeout=300.0,
        msg_id="abc123",
    )

    assert payload.options is None
