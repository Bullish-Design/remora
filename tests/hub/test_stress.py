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
    # Wait for indexing to complete by polling stats
    stats = {"files": 0, "nodes": 0}
    for _ in range(100): # Allow up to 50s
        if daemon.store is not None:
            stats = await daemon.store.stats()
            if stats["files"] >= 100:
                break
        await asyncio.sleep(0.5)

    elapsed = time.monotonic() - start

    # Verify all nodes indexed
    status = await daemon.store.get_status()
    assert stats["files"] >= 100
    assert stats["nodes"] >= 500  # 100 files * 5 functions

    daemon._shutdown_event.set()
    await task

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
    
    # Wait for initial cold start indexing to finish
    for _ in range(100):
        if daemon.store is not None:
            stats = await daemon.store.stats()
            if stats["files"] >= 100:
                break
        await asyncio.sleep(0.5)
        
    # Wait for watcher to explicitly be created
    for _ in range(10):
        if getattr(daemon, "watcher", None) is not None:
            break
        await asyncio.sleep(0.5)
        
    # Extra sleep to ensure watcher has started observing the FS
    await asyncio.sleep(1.0)

    # Modify 20 files concurrently
    async def modify_file(i: int) -> None:
        path = large_project / "src" / f"module_{i:03d}.py"
        content = path.read_text(encoding="utf-8")
        path.write_text(content + f"\n\ndef added_func_{i}(): pass\n", encoding="utf-8")

    await asyncio.gather(*[modify_file(i) for i in range(20)])

    # Wait for processing by polling
    for _ in range(60):
        if daemon.store is not None:
            all_nodes = await daemon.store.list_all_nodes()
            added_funcs = [n for n in all_nodes if "added_func" in n.node_name]
            if len(added_funcs) >= 20:
                break
        await asyncio.sleep(0.5)

    # Verify new functions indexed
    all_nodes = await daemon.store.list_all_nodes()
    added_funcs = [n for n in all_nodes if "added_func" in n.node_name]
    assert len(added_funcs) == 20

    daemon._shutdown_event.set()
    await task
