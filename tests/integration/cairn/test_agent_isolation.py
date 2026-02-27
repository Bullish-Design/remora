"""Tests verifying isolation between different agent workspaces."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.cairn, pytest.mark.cairn_isolation]


class TestAgentToAgentIsolation:
    """Verify agents cannot see each other's writes."""

    @pytest.mark.asyncio
    async def test_agent_cannot_see_other_agent_writes(
        self,
        workspace_service,
    ) -> None:
        """Agent-1's writes should not be visible to Agent-2."""
        ws1 = await workspace_service.get_agent_workspace("agent-1")
        ws2 = await workspace_service.get_agent_workspace("agent-2")

        test_file = "agent1_private.txt"
        await ws1.write(test_file, "Private to agent-1")

        exists_in_ws2 = await ws2.exists(test_file)
        assert not exists_in_ws2, "Agent-2 should not see Agent-1's private file"

    @pytest.mark.asyncio
    async def test_agents_can_modify_same_file_independently(
        self,
        workspace_service,
        path_resolver,
    ) -> None:
        """Multiple agents can modify the same file without interference."""
        ws1 = await workspace_service.get_agent_workspace("agent-1")
        ws2 = await workspace_service.get_agent_workspace("agent-2")
        ws3 = await workspace_service.get_agent_workspace("agent-3")

        shared_file = path_resolver.to_workspace_path("src/main.py")

        await ws1.write(shared_file, "# Version from agent-1")
        await ws2.write(shared_file, "# Version from agent-2")
        await ws3.write(shared_file, "# Version from agent-3")

        content1 = await ws1.read(shared_file)
        content2 = await ws2.read(shared_file)
        content3 = await ws3.read(shared_file)

        assert content1 == "# Version from agent-1"
        assert content2 == "# Version from agent-2"
        assert content3 == "# Version from agent-3"

    @pytest.mark.asyncio
    async def test_agent_isolation_with_many_agents(
        self,
        workspace_service,
    ) -> None:
        """Verify isolation with many concurrent agents."""
        num_agents = 20
        workspaces = {}

        for i in range(num_agents):
            agent_id = f"agent-{i:02d}"
            workspaces[agent_id] = await workspace_service.get_agent_workspace(agent_id)

        for agent_id, ws in workspaces.items():
            await ws.write(f"{agent_id}_output.txt", f"Output from {agent_id}")
            await ws.write("shared.txt", f"Written by {agent_id}")

        for agent_id, ws in workspaces.items():
            own_file = f"{agent_id}_output.txt"
            assert await ws.exists(own_file)
            content = await ws.read(own_file)
            assert content == f"Output from {agent_id}"

            for other_id in workspaces.keys():
                if other_id != agent_id:
                    other_file = f"{other_id}_output.txt"
                    exists = await ws.exists(other_file)
                    assert not exists, f"{agent_id} should not see {other_file}"

            shared_content = await ws.read("shared.txt")
            assert shared_content == f"Written by {agent_id}"
