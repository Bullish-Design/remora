"""Shared fixtures for Companion demo tests.

Provides reusable fixtures for the renderer, scenarios, workspace,
and the full CompanionRuntime pipeline. The runtime fixture is
session-scoped to avoid reloading the embedding model (~25s) on
every test.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from remora_demo.companion.demo.renderer import RenderConfig, TerminalRenderer
from remora_demo.companion.demo.scenarios import (
    DemoScenario,
    DemoStep,
    coding_scenario,
    get_all_scenarios,
    research_scenario,
)


@pytest.fixture
def examples_dir() -> Path:
    """Path to the built-in example data."""
    return Path(__file__).resolve().parent.parent.parent / "remora_demo" / "companion" / "examples"


@pytest.fixture
def render_config() -> RenderConfig:
    """Default A4-ish render config for tests."""
    return RenderConfig(total_width=100, total_height=56)


@pytest.fixture
def renderer(render_config: RenderConfig) -> TerminalRenderer:
    """A fresh TerminalRenderer with default config."""
    return TerminalRenderer(render_config)


@pytest.fixture
def coding_scn(examples_dir: Path) -> DemoScenario:
    """The coding exploration scenario."""
    return coding_scenario(examples_dir)


@pytest.fixture
def research_scn(examples_dir: Path) -> DemoScenario:
    """The document research scenario."""
    return research_scenario(examples_dir)


@pytest.fixture
def all_scenarios(examples_dir: Path) -> list[DemoScenario]:
    """All available demo scenarios."""
    return get_all_scenarios(examples_dir)


@pytest.fixture
def sample_editor_content() -> list[str]:
    """Sample Python lines for renderer tests."""
    return [
        "import asyncio",
        "from pathlib import Path",
        "",
        "",
        "class DataProcessor:",
        '    """Process data from multiple sources."""',
        "",
        "    def __init__(self, config):",
        "        self.config = config",
        "        self._data = []",
        "",
        "    def load_data(self, source: str) -> list:",
        '        """Load data from a source."""',
        "        pass",
        "",
        "    def process_batch(self, items: list) -> dict:",
        '        """Process a batch of items."""',
        "        results = {}",
        "        for item in items:",
        "            results[item] = self._process_one(item)",
        "        return results",
    ]


@pytest.fixture
def sample_sidebar_markdown() -> str:
    """Sample sidebar markdown for renderer tests."""
    return (
        "# Companion Context\n"
        "\n"
        "> Tracking: processor.py:21\n"
        "\n"
        "## Related Content\n"
        "\n"
        "- **validators.py** (85%)\n"
        "- test_processor.py (72%)\n"
        "\n"
        "## Connections\n"
        "\n"
        "- tests: test_processor.py tests DataProcessor\n"
        "- references: architecture.md mentions DataProcessor\n"
        "\n"
        "---\n"
        "\n"
        "<small>Updated 0.3s ago</small>\n"
    )


# -- Heavy fixtures (session-scoped) for pipeline tests --


@pytest.fixture(scope="session")
def _session_tmp_dir():
    """Session-scoped temporary directory (cleaned up at session end)."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(scope="session")
def _session_examples_dir() -> Path:
    """Session-scoped examples directory."""
    return Path(__file__).resolve().parent.parent.parent / "remora_demo" / "companion" / "examples"


@pytest.fixture(scope="session")
def companion_runtime(_session_tmp_dir: Path, _session_examples_dir: Path):
    """A fully-initialized CompanionRuntime with indexed example workspace.

    Session-scoped to avoid reloading the embedding model on every test.
    Tests that use this fixture MUST NOT modify the runtime state in ways
    that break other tests (or should restore it after).
    """
    import asyncio

    from remora_demo.companion.runtime import CompanionConfig, CompanionRuntime

    db_path = _session_tmp_dir / "test_index.db"
    config = CompanionConfig(
        workspace_path=_session_examples_dir,
        db_path=db_path,
        auto_index=True,
    )
    runtime = CompanionRuntime(config)

    # Start the runtime (triggers indexing + model load)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(runtime.start())
    yield runtime
    loop.run_until_complete(runtime.stop())
    loop.close()
