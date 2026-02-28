"""Tests for SwarmState."""

import pytest
from pathlib import Path

from remora.core.swarm_state import AgentMetadata, SwarmState


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_swarm.db"


def test_upsert_agent(temp_db: Path) -> None:
    swarm = SwarmState(temp_db)
    swarm.initialize()

    metadata = AgentMetadata(
        agent_id="test-agent-123",
        node_type="function",
        file_path="src/main.py",
        parent_id=None,
        start_line=10,
        end_line=20,
    )
    swarm.upsert(metadata)

    agent = swarm.get_agent("test-agent-123")
    assert agent is not None
    assert agent["agent_id"] == "test-agent-123"
    assert agent["node_type"] == "function"
    assert agent["status"] == "active"

    swarm.close()


def test_list_agents(temp_db: Path) -> None:
    swarm = SwarmState(temp_db)
    swarm.initialize()

    swarm.upsert(AgentMetadata("agent-1", "function", "src/a.py", None, 1, 10))
    swarm.upsert(AgentMetadata("agent-2", "class", "src/b.py", None, 1, 20))

    agents = swarm.list_agents()
    assert len(agents) == 2

    agents = swarm.list_agents(status="active")
    assert len(agents) == 2

    swarm.close()


def test_mark_orphaned(temp_db: Path) -> None:
    swarm = SwarmState(temp_db)
    swarm.initialize()

    swarm.upsert(AgentMetadata("agent-1", "function", "src/a.py", None, 1, 10))
    swarm.mark_orphaned("agent-1")

    agent = swarm.get_agent("agent-1")
    assert agent is not None
    assert agent["status"] == "orphaned"

    swarm.close()


def test_update_agent(temp_db: Path) -> None:
    swarm = SwarmState(temp_db)
    swarm.initialize()

    swarm.upsert(AgentMetadata("agent-1", "function", "src/a.py", None, 1, 10))

    swarm.upsert(AgentMetadata("agent-1", "function", "src/b.py", None, 5, 15))

    agent = swarm.get_agent("agent-1")
    assert agent is not None
    assert agent["file_path"] == "src/b.py"
    assert agent["start_line"] == 5

    swarm.close()
