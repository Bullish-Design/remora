"""Tests verifying thread/async safety of Cairn operations."""

import asyncio
import os

import pytest

from remora.cairn_bridge import CairnWorkspaceService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.cairn,
    pytest.mark.cairn_concurrent,
    pytest.mark.cairn_slow,
]


class TestConcurrentSafety:
    """Verify concurrent operations don't cause data corruption."""

    @pytest.mark.asyncio
    async def test_concurrent_agent_creation(
        self,
        workspace_service,
    ) -> None:
        """Creating many agent workspaces concurrently should be safe."""
        num_agents = 50

        async def create_agent(agent_id: str) -> tuple[str, bool]:
            try:
                ws = await workspace_service.get_agent_workspace(agent_id)
                await ws.write(f"{agent_id}.txt", f"Content from {agent_id}")
                return agent_id, True
            except Exception:
                return agent_id, False

        tasks = [create_agent(f"concurrent-{i:03d}") for i in range(num_agents)]
        results = await asyncio.gather(*tasks)

        failures = [(agent_id, success) for agent_id, success in results if not success]
        assert not failures, f"Failed to create agents: {failures}"

    @pytest.mark.asyncio
    async def test_concurrent_writes_to_same_agent(
        self,
        workspace_service,
    ) -> None:
        """Concurrent writes to same agent workspace should be safe."""
        ws = await workspace_service.get_agent_workspace("concurrent-writes")
        num_writes = 100

        async def write_file(index: int) -> bool:
            try:
                await ws.write(f"file_{index:03d}.txt", f"Content {index}")
                return True
            except Exception:
                return False

        tasks = [write_file(i) for i in range(num_writes)]
        results = await asyncio.gather(*tasks)

        success_count = sum(1 for r in results if r)
        assert success_count == num_writes

        for i in range(num_writes):
            exists = await ws.exists(f"file_{i:03d}.txt")
            assert exists, f"File {i} should exist"

    @pytest.mark.asyncio
    async def test_concurrent_read_write(
        self,
        workspace_service,
    ) -> None:
        """Concurrent reads and writes should be safe."""
        ws = await workspace_service.get_agent_workspace("read-write")

        for i in range(10):
            await ws.write(f"base_{i}.txt", f"Base content {i}")

        read_results: list[str] = []
        write_results: list[bool] = []

        async def read_file(index: int) -> None:
            content = await ws.read(f"base_{index % 10}.txt")
            read_results.append(content)

        async def write_file(index: int) -> None:
            try:
                await ws.write(f"new_{index}.txt", f"New content {index}")
                write_results.append(True)
            except Exception:
                write_results.append(False)

        tasks = []
        for i in range(50):
            tasks.append(read_file(i))
            tasks.append(write_file(i))

        await asyncio.gather(*tasks)

        assert len(read_results) == 50
        assert all(write_results)

    @pytest.mark.asyncio
    async def test_rapid_open_close_cycles(
        self,
        workspace_config,
        project_root,
    ) -> None:
        """Rapidly opening and closing services should be safe."""
        cycles = 20

        for i in range(cycles):
            service = CairnWorkspaceService(
                workspace_config,
                graph_id=f"rapid-cycle-{i}",
                project_root=project_root,
            )
            await service.initialize(sync=True)

            ws = await service.get_agent_workspace("agent-1")
            await ws.write("test.txt", f"Cycle {i}")

            await service.close()

        service = CairnWorkspaceService(
            workspace_config,
            graph_id=f"rapid-cycle-{cycles - 1}",
            project_root=project_root,
        )
        await service.initialize(sync=False)
        ws = await service.get_agent_workspace("agent-1")
        content = await ws.read("test.txt")
        assert content == f"Cycle {cycles - 1}"
        await service.close()

    @pytest.mark.asyncio
    @pytest.mark.cairn_slow
    async def test_concurrent_agent_creation_stress(
        self,
        workspace_service,
    ) -> None:
        """Stress test concurrent agent creation."""
        num_agents = int(os.environ.get("REMORA_CAIRN_STRESS_AGENTS", "200"))

        async def create_agent(agent_id: str) -> bool:
            ws = await workspace_service.get_agent_workspace(agent_id)
            await ws.write(f"{agent_id}.txt", f"Content from {agent_id}")
            return True

        tasks = [create_agent(f"stress-{i:04d}") for i in range(num_agents)]
        results = await asyncio.gather(*tasks)
        assert all(results)
