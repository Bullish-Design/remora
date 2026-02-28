"""Tests for SwarmState."""

import pytest
from pathlib import Path

from remora.core.swarm_state import AgentMetadata, SwarmState


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_swarm.db"


@pytest.mark.asyncio
async def test_upsert_agent(temp_db: Path) -> None:
    swarm = SwarmState(temp_db)
    await swarm.initialize()

    metadata = AgentMetadata(
        agent_id="test-agent-123",
        node_type="function",
        name="test-agent-123",
        full_name="src.main.test-agent-123",
        file_path="src/main.py",
        parent_id=None,
        start_line=10,
        end_line=20,
    )
    await swarm.upsert(metadata)

    agent = await swarm.get_agent("test-agent-123")
    assert agent is not None
    assert agent.agent_id == "test-agent-123"
    assert agent.node_type == "function"
    assert agent.status == "active"

    await swarm.close()


@pytest.mark.asyncio
async def test_list_agents(temp_db: Path) -> None:
    swarm = SwarmState(temp_db)
    await swarm.initialize()

    await swarm.upsert(AgentMetadata(
        agent_id="agent-1",
        node_type="function",
        name="agent-1",
        full_name="src.a.agent-1",
        file_path="src/a.py",
        parent_id=None,
        start_line=1,
        end_line=10,
    ))
    await swarm.upsert(AgentMetadata(
        agent_id="agent-2",
        node_type="class",
        name="agent-2",
        full_name="src.b.agent-2",
        file_path="src/b.py",
        parent_id=None,
        start_line=1,
        end_line=20,
    ))

    agents = await swarm.list_agents()
    assert len(agents) == 2

    agents = await swarm.list_agents(status="active")
    assert len(agents) == 2

    await swarm.close()


@pytest.mark.asyncio
async def test_mark_orphaned(temp_db: Path) -> None:
    swarm = SwarmState(temp_db)
    await swarm.initialize()

    await swarm.upsert(AgentMetadata(
        agent_id="agent-1",
        node_type="function",
        name="agent-1",
        full_name="src.a.agent-1",
        file_path="src/a.py",
        parent_id=None,
        start_line=1,
        end_line=10,
    ))
    await swarm.mark_orphaned("agent-1")

    agent = await swarm.get_agent("agent-1")
    assert agent is not None
    assert agent.status == "orphaned"

    await swarm.close()


@pytest.mark.asyncio
async def test_update_agent(temp_db: Path) -> None:
    swarm = SwarmState(temp_db)
    await swarm.initialize()

    await swarm.upsert(AgentMetadata(
        agent_id="agent-1",
        node_type="function",
        name="agent-1",
        full_name="src.a.agent-1",
        file_path="src/a.py",
        parent_id=None,
        start_line=1,
        end_line=10,
    ))

    await swarm.upsert(AgentMetadata(
        agent_id="agent-1",
        node_type="function",
        name="agent-1",
        full_name="src.b.agent-1",
        file_path="src/b.py",
        parent_id=None,
        start_line=5,
        end_line=15,
    ))

    agent = await swarm.get_agent("agent-1")
    assert agent is not None
    assert agent.file_path == "src/b.py"
    assert agent.start_line == 5

    await swarm.close()
