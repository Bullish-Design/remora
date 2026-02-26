# tests/test_agent/test_bundle.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from structured_agents.agent import Agent


@pytest.mark.asyncio
async def test_agent_from_bundle_minimal():
    with patch("structured_agents.agent.load_manifest") as mock_load:
        mock_load.return_value = MagicMock(
            name="test_agent",
            system_prompt="You are helpful.",
            agents_dir="/tmp/agents",
            limits=None,
            model="qwen",
            grammar_config=None,
        )

        with patch("structured_agents.agent.discover_tools") as mock_discover:
            mock_discover.return_value = []

            with patch("structured_agents.agent.build_client") as mock_client:
                mock_client.return_value = AsyncMock()

                agent = await Agent.from_bundle("/tmp/bundle")

                assert agent is not None
