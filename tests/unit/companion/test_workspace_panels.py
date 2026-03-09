from __future__ import annotations

from types import SimpleNamespace

import pytest

from remora.companion.sidebar.composer import compose_sidebar
from remora.companion.sidebar.workspace import build_workspace_panels


class _FakeWorkspace:
    def __init__(self, files: dict[str, str], dirs: dict[str, list[str]] | None = None):
        self._files = files
        self._dirs = dirs or {}

    async def read(self, path: str) -> str:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]

    async def list_dir(self, path: str = ".") -> list[str]:
        if path not in self._dirs:
            raise FileNotFoundError(path)
        return self._dirs[path]


@pytest.mark.asyncio
async def test_build_workspace_panels_reads_files_and_limits_log() -> None:
    log_lines = "\n".join(f'{{"i": {i}}}' for i in range(30))
    workspace = _FakeWorkspace(
        files={
            "role.md": "Role content",
            "schema.yaml": "name: test",
            "notes.md": "Bootstrap notes",
            "summary.md": "## What I do\nDetailed behavior",
            "todo.md": "- [ ] next",
            "log.jsonl": log_lines,
        },
        dirs={"tools": ["z_tool.pym", "a_tool.pym", "README.md"]},
    )

    panels = await build_workspace_panels(workspace)
    by_key = {panel.key: panel for panel in panels}

    assert set(by_key) == {"role", "schema", "notes", "summary", "todo", "log", "tools"}
    assert by_key["role"].content == "Role content"
    assert by_key["schema"].content == "name: test"
    assert by_key["summary"].content == "## What I do\nDetailed behavior"
    assert by_key["tools"].content == "- `a_tool.pym`\n- `z_tool.pym`"
    assert by_key["log"].content.count("\n") == 19
    assert '{"i": 10}' in by_key["log"].content
    assert '{"i": 29}' in by_key["log"].content


@pytest.mark.asyncio
async def test_build_workspace_panels_handles_missing_files() -> None:
    workspace = _FakeWorkspace(files={}, dirs={})
    panels = await build_workspace_panels(workspace)

    assert len(panels) == 7
    assert all(panel.is_empty for panel in panels)


@pytest.mark.asyncio
async def test_compose_sidebar_includes_workspace_section() -> None:
    node = SimpleNamespace(
        node_id="module:src/app.py",
        name="app.py",
        node_type="module",
        file_path="src/app.py",
        start_line=1,
        callee_ids=[],
        caller_ids=[],
    )
    workspace = _FakeWorkspace(
        files={
            "role.md": "I own this module.",
            "summary.md": "## What I am\nA module entrypoint.",
        },
        dirs={"tools": []},
    )

    markdown = await compose_sidebar(node, workspace)
    assert "## Workspace" in markdown
    assert "### Role" in markdown
    assert "I own this module." in markdown
    assert "### Summary" in markdown
    assert "A module entrypoint." in markdown
