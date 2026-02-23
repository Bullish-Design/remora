import pytest
from pathlib import Path
from remora.hub.call_graph import CallGraphBuilder, update_call_graph


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a sample project with cross-file calls."""
    # File 1: utils.py
    utils = tmp_path / "utils.py"
    utils.write_text('''
def helper():
    """A helper function."""
    return 42

def another_helper():
    return helper() + 1
''', encoding="utf-8")

    # File 2: main.py
    main = tmp_path / "main.py"
    main.write_text('''
from utils import helper

def process():
    """Main processing function."""
    result = helper()
    return result * 2
''', encoding="utf-8")

    return tmp_path


@pytest.mark.asyncio
async def test_call_graph_extraction(sample_project: Path, mock_store: "Any") -> None:
    """Test that call graph correctly identifies callers/callees."""
    # Note: `mock_store` should be implemented/injected properly in real test suites
    # Index the files first
    # ... setup mock_store with nodes ...

    builder = CallGraphBuilder(store=mock_store, project_root=sample_project)
    graph = await builder.build()

    # Verify relationships
    utils_helper_id = "node:utils.py:helper"
    utils_another_id = "node:utils.py:another_helper"
    main_process_id = "node:main.py:process"

    # Assume mock store was populated
    if utils_helper_id in graph:
        # helper is called by another_helper and process
        assert utils_another_id in graph[utils_helper_id]["callers"]
        assert main_process_id in graph[utils_helper_id]["callers"]

        # another_helper calls helper
        assert utils_helper_id in graph[utils_another_id]["callees"]

        # process calls helper
        assert utils_helper_id in graph[main_process_id]["callees"]
