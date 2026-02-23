"""
tests/hub/test_stress.py

Stress testing for Hub daemon with large codebases.
"""

import asyncio
from pathlib import Path

import pytest

from remora.hub.daemon import HubDaemon


@pytest.fixture
def large_project(tmp_path: Path) -> Path:
    """Create a project with many files."""
    src = tmp_path / "src"
    src.mkdir()
    agents = tmp_path / "agents"
    agents.mkdir()

    # Create 100 modules with 5 functions each
    for i in range(100):
        module = src / f"module_{i:03d}.py"
        functions = "\n\n".join([
            f'''
def function_{j}():
    """Function {j} in module {i}."""
    return {i * 100 + j}
'''
            for j in range(5)
        ])
        module.write_text(functions, encoding="utf-8")

    return tmp_path


@pytest.mark.asyncio
@pytest.mark.slow
async def test_large_codebase_indexing(large_project: Path, mock_grail_executor: "Any") -> None:
    """Test daemon can index a large codebase efficiently."""
    config = large_project / "remora.yaml"
    config.write_text("hub:\n  mode: in-process\n  enable_cross_file_analysis: false\n")

    daemon = HubDaemon(
        project_root=large_project,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    import time
    start = time.monotonic()

    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(5.0)  # Allow time for indexing
    daemon._shutdown_event.set()
    await task

    elapsed = time.monotonic() - start

    # Verify all nodes indexed
    status = await daemon._store.get_status()
    assert status.indexed_files >= 100
    assert status.indexed_nodes >= 500  # 100 files * 5 functions

    # Performance assertion: should index in reasonable time
    assert elapsed < 60.0, f"Indexing took {elapsed:.1f}s, expected < 60s"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_concurrent_file_changes(large_project: Path, mock_grail_executor: "Any") -> None:
    """Test daemon handles many concurrent file changes."""
    config = large_project / "remora.yaml"
    config.write_text("hub:\n  mode: in-process\n  enable_cross_file_analysis: false\n")

    daemon = HubDaemon(
        project_root=large_project,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(3.0)  # Initial indexing

    # Modify 20 files concurrently
    async def modify_file(i: int) -> None:
        path = large_project / "src" / f"module_{i:03d}.py"
        content = path.read_text(encoding="utf-8")
        path.write_text(content + f"\n\ndef added_func_{i}(): pass\n", encoding="utf-8")

    await asyncio.gather(*[modify_file(i) for i in range(20)])

    # Wait for processing
    await asyncio.sleep(3.0)

    daemon._shutdown_event.set()
    await task

    # Verify new functions indexed
    all_nodes = await daemon._store.list_all_nodes()
    added_funcs = [n for n in all_nodes if "added_func" in n]
    assert len(added_funcs) == 20
