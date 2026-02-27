"""Tests verifying merge/accept/reject behavior."""

import pytest

from remora.errors import WorkspaceError

pytestmark = [pytest.mark.integration, pytest.mark.cairn]


class TestMergeOperations:
    """Verify merge operations are explicitly unsupported."""

    @pytest.mark.asyncio
    async def test_accept_raises_until_supported(
        self,
        agent_workspace,
    ) -> None:
        """accept() should raise until merge support is implemented."""
        with pytest.raises(WorkspaceError):
            await agent_workspace.accept()

    @pytest.mark.asyncio
    async def test_reject_raises_until_supported(
        self,
        agent_workspace,
    ) -> None:
        """reject() should raise until merge support is implemented."""
        with pytest.raises(WorkspaceError):
            await agent_workspace.reject()
