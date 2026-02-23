"""
tests/hub/test_daemon_lifecycle.py

Comprehensive daemon lifecycle testing.
"""

import asyncio
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from remora.hub.daemon import HubDaemon
from remora.hub.models import HubStatus


@pytest.fixture
def project_with_files(tmp_path: Path) -> Path:
    """Create a project with multiple Python files."""
    src = tmp_path / "src"
    src.mkdir()
    agents = tmp_path / "agents"
    agents.mkdir()

    (src / "main.py").write_text('''
def main():
    """Entry point."""
    return 0
''', encoding="utf-8")

    (src / "utils.py").write_text('''
def helper():
    """A helper function."""
    return 42
''', encoding="utf-8")

    (src / "models.py").write_text('''
class User:
    """User model."""
    def __init__(self, name):
        self.name = name
''', encoding="utf-8")

    return tmp_path


@pytest.mark.asyncio
async def test_daemon_cold_start(project_with_files: Path, mock_grail_executor: "Any") -> None:
    """Test daemon indexes all files on cold start."""
    # Write dummy config to avoid ConfigError on boot
    config = project_with_files / "remora.yaml"
    config.write_text("hub:\n  mode: in-process\n  enable_cross_file_analysis: false\n")

    daemon = HubDaemon(
        project_root=project_with_files,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    # Run for a short time then stop
    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(0.5)

    # Verify files were indexed
    status = await daemon.store.get_status()
    assert status is not None
    assert status.indexed_files >= 3
    assert status.indexed_nodes >= 3

    daemon._shutdown_event.set()
    await task


@pytest.mark.asyncio
async def test_daemon_graceful_shutdown(project_with_files: Path, mock_grail_executor: "Any") -> None:
    """Test daemon shuts down gracefully on SIGTERM."""
    config = project_with_files / "remora.yaml"
    config.write_text("hub:\n  mode: in-process\n  enable_cross_file_analysis: false\n")

    daemon = HubDaemon(
        project_root=project_with_files,
        standalone=True,  # Will set up signal handlers
        grail_executor=mock_grail_executor,
    )

    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(0.2)

    # Simulate SIGTERM
    daemon._shutdown_event.set()
    await asyncio.wait_for(task, timeout=5.0)

    # Verify clean shutdown by opening a new temporary client
    from fsdantic import Fsdantic
    from remora.hub.store import NodeStateStore
    workspace = await Fsdantic.open(path=str(daemon.db_path))
    store = NodeStateStore(workspace)
    status = await store.get_status()
    await workspace.close()
    assert status is None or status.running is False


@pytest.mark.asyncio
async def test_daemon_file_change_handling(project_with_files: Path, mock_grail_executor: "Any") -> None:
    """Test daemon processes file changes correctly."""
    config = project_with_files / "remora.yaml"
    config.write_text("hub:\n  mode: in-process\n  enable_cross_file_analysis: false\n")

    daemon = HubDaemon(
        project_root=project_with_files,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(0.5)  # Let cold start complete

    # Modify a file
    (project_with_files / "src" / "main.py").write_text('''
def main():
    """Updated entry point."""
    return 1

def new_function():
    """A new function."""
    pass
''', encoding="utf-8")

    # Wait for change to be processed
    await asyncio.sleep(1.0)

    # Verify new function was indexed
    all_nodes = await daemon.store.list_all_nodes()
    node_names = [n.split(":")[-1] for n in all_nodes]
    assert "new_function" in node_names

    daemon._shutdown_event.set()
    await task


@pytest.mark.asyncio
async def test_daemon_restart_recovery(project_with_files: Path, mock_grail_executor: "Any") -> None:
    """Test daemon recovers state correctly on restart."""
    config = project_with_files / "remora.yaml"
    config.write_text("hub:\n  mode: in-process\n  enable_cross_file_analysis: false\n")

    # First run
    daemon1 = HubDaemon(
        project_root=project_with_files,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    task1 = asyncio.create_task(daemon1.run())
    await asyncio.sleep(0.5)

    initial_nodes = await daemon1.store.list_all_nodes()

    daemon1._shutdown_event.set()
    await task1

    # Second run (restart)
    daemon2 = HubDaemon(
        project_root=project_with_files,
        standalone=False,
        grail_executor=mock_grail_executor,
    )

    task2 = asyncio.create_task(daemon2.run())
    await asyncio.sleep(0.5)

    # Verify state persisted
    recovered_nodes = await daemon2.store.list_all_nodes()
    assert set(recovered_nodes) == set(initial_nodes)

    daemon2._shutdown_event.set()
    await task2
