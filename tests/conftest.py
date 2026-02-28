"""Pytest fixtures for Remora integration tests.

This module provides fixtures for testing the reactive, subscription-driven
Agent Swarm architecture. All fixtures use real components where possible
and only mock the LLM layer.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import pytest

from remora.core.config import Config
from remora.core.event_store import EventStore
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.swarm_state import AgentMetadata, SwarmState
from remora.core.agent_state import AgentState, save as save_agent_state


@pytest.fixture
def sample_workspace(tmp_path: Path) -> Path:
    """Create a real mini-codebase for tests to operate on."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def hello():\n    pass\n\ndef greet(name: str) -> str:\n    return f'Hello, {name}!'\n"
    )
    (tmp_path / "src" / "utils.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    return tmp_path


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create a test configuration."""
    return Config(
        project_path=str(tmp_path),
        discovery_paths=("src/",),
        model_base_url="http://localhost:8000/v1",
        model_default="test/model",
        model_api_key="test-key",
        swarm_root=".remora",
        swarm_id="test-swarm",
        max_concurrency=4,
        max_turns=3,
        max_trigger_depth=3,
        trigger_cooldown_ms=100,
    )


@pytest.fixture
async def event_store(tmp_path: Path) -> EventStore:
    """Create an initialized EventStore backed by a temp database."""
    store = EventStore(tmp_path / "events.db")
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def subscription_registry(tmp_path: Path) -> SubscriptionRegistry:
    """Create an initialized SubscriptionRegistry."""
    registry = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await registry.initialize()
    yield registry
    await registry.close()


@pytest.fixture
async def swarm_state(tmp_path: Path) -> AsyncIterator[SwarmState]:
    """Create an initialized SwarmState backed by a temp database."""
    state = SwarmState(tmp_path / "swarm.db")
    await state.initialize()
    try:
        yield state
    finally:
        await state.close()


@pytest.fixture
def agent_state(tmp_path: Path) -> AgentState:
    """Create a test agent state."""
    return AgentState(
        agent_id="test_agent",
        node_type="function",
        name="test_agent",
        full_name="src.main.test_agent",
        file_path="src/main.py",
        parent_id=None,
        range=(1, 10),
        connections={},
        chat_history=[],
    )


@pytest.fixture
def agent_metadata() -> AgentMetadata:
    """Create test agent metadata."""
    return AgentMetadata(
        agent_id="test_agent",
        node_type="function",
        name="test_agent",
        full_name="src.main.test_agent",
        file_path="src/main.py",
        parent_id=None,
        start_line=1,
        end_line=10,
    )


@pytest.fixture
async def configured_event_store(
    tmp_path: Path,
    subscription_registry: SubscriptionRegistry,
) -> EventStore:
    """Create an EventStore with subscriptions configured."""
    store = EventStore(tmp_path / "events.db", subscriptions=subscription_registry)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def sample_agent_state_file(tmp_path: Path) -> Path:
    """Create a persisted agent state file for testing."""
    state = AgentState(
        agent_id="test_agent",
        node_type="function",
        name="test_agent",
        full_name="src.main.test_agent",
        file_path="src/main.py",
        parent_id=None,
        range=(1, 10),
        connections={},
        chat_history=[],
    )
    state_path = tmp_path / ".remora" / "agents" / "test_agent" / "state.jsonl"
    save_agent_state(state_path, state)
    return state_path


class DummyKernel:
    """Dummy kernel that returns predefined responses deterministically.

    Used to test the reactive system without hitting a real LLM API.
    """

    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or ["Dummy response"]
        self.call_count = 0

    async def run(self, messages: list, tool_schemas: list, max_turns: int = 1) -> "DummyResult":
        response = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return DummyResult(content=response)

    async def close(self) -> None:
        pass


class DummyResult:
    """Dummy result from DummyKernel."""

    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []

    def __str__(self) -> str:
        return self.content


@pytest.fixture
def dummy_kernel():
    """Factory fixture for creating DummyKernel instances."""
    return DummyKernel
