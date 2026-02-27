"""Tests verifying KV store operations for submissions."""

import pytest
from cairn.orchestrator.lifecycle import SUBMISSION_KEY, SubmissionRecord

pytestmark = [pytest.mark.integration, pytest.mark.cairn]


class TestKVSubmissions:
    """Verify submission KV operations work correctly."""

    @pytest.mark.asyncio
    async def test_submit_result_stores_in_kv(
        self,
        workspace_service,
        agent_workspace,
    ) -> None:
        """submit_result should store data in KV."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        await externals["submit_result"](
            summary="Test completed",
            changed_files=["test.txt"],
        )

        repo = agent_workspace.cairn.kv.repository(prefix="", model_type=SubmissionRecord)
        record = await repo.load(SUBMISSION_KEY)

        assert record is not None
        assert record.submission["summary"] == "Test completed"
        assert record.submission["changed_files"] == ["test.txt"]

    @pytest.mark.asyncio
    async def test_submission_isolated_per_agent(
        self,
        workspace_service,
    ) -> None:
        """Each agent should have isolated submission records."""
        agents = ["agent-1", "agent-2", "agent-3"]

        for agent_id in agents:
            ws = await workspace_service.get_agent_workspace(agent_id)
            externals = workspace_service.get_externals(agent_id, ws)

            await externals["submit_result"](
                summary=f"Summary from {agent_id}",
            changed_files=[f"{agent_id}.txt"],
            )

        for agent_id in agents:
            ws = await workspace_service.get_agent_workspace(agent_id)
            repo = ws.cairn.kv.repository(prefix="", model_type=SubmissionRecord)
            record = await repo.load(SUBMISSION_KEY)

            assert record.submission["summary"] == f"Summary from {agent_id}"
            assert record.submission["changed_files"] == [f"{agent_id}.txt"]

    @pytest.mark.asyncio
    async def test_submission_overwrites_previous(
        self,
        workspace_service,
        agent_workspace,
    ) -> None:
        """Calling submit_result again should overwrite."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        await externals["submit_result"](
            summary="First",
            changed_files=["first.txt"],
        )

        await externals["submit_result"](
            summary="Second",
            changed_files=["second.txt"],
        )

        repo = agent_workspace.cairn.kv.repository(prefix="", model_type=SubmissionRecord)
        record = await repo.load(SUBMISSION_KEY)

        assert record.submission["summary"] == "Second"
