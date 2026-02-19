import pytest
from pathlib import Path
import json
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from remora.execution import ProcessIsolatedExecutor


@pytest.mark.asyncio
async def test_externals_integration(tmp_path: Path):
    """Verify that Remora-specific externals are injectable and callable."""

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    # Create the pym script that calls the externals
    pym_script = """
async def main(inputs):
    source = await get_node_source()
    metadata = await get_node_metadata()
    return {
        "source": source,
        "metadata": metadata,
    }
"""
    pym_path = tmp_path / "test_tool.pym"
    pym_path.write_text(pym_script, encoding="utf-8")

    grail_dir = tmp_path / ".grail"
    grail_dir.mkdir()

    executor = ProcessIsolatedExecutor()

    node_source = "def foo(): pass"
    node_metadata = {"name": "foo", "type": "function_definition"}

    # Mock expected return from _run_in_child
    expected_result = {
        "error": False,
        "result": {
            "source": node_source,
            "metadata": node_metadata,
        },
    }

    # Use ThreadPoolExecutor to avoid pickling issues
    import concurrent.futures

    executor._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    try:
        with patch("remora.execution._run_in_child", return_value=expected_result):
            result = await executor.execute(
                pym_path=pym_path,
                grail_dir=grail_dir,
                inputs={},
                agent_id="agent-123",
                workspace_path=workspace_dir,
                node_source=node_source,
                node_metadata=node_metadata,
            )

            assert result["error"] is False, f"Execution failed: {result}"
            output = result["result"]
            assert output["source"] == node_source
            assert output["metadata"] == node_metadata

    finally:
        await executor.shutdown()
