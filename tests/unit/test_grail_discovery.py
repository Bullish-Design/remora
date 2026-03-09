from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from remora.core.tools import grail as grail_mod
from remora.core.tools.grail import discover_grail_tools


class FakeGrailTool:
    def __init__(
        self,
        script_path: Path,
        *,
        externals,
        files_provider,
        limits=None,
        grail_dir=None,
    ) -> None:
        self.script_path = script_path
        self.externals = externals
        self.files_provider = files_provider
        self.schema = SimpleNamespace(name=script_path.stem)

    async def execute(self, arguments, context=None):
        return SimpleNamespace(output=f"{self.schema.name}:{arguments}")


async def _empty_files_provider() -> dict[str, str | bytes]:
    return {}


def _write_tool(dir_path: Path, name: str) -> None:
    (dir_path / f"{name}.pym").write_text("async def x() -> str:\n    return 'ok'\n", encoding="utf-8")


def test_discover_requires_context_or_externals(tmp_path: Path) -> None:
    _write_tool(tmp_path, "one")

    with pytest.raises(ValueError, match="Either context or externals"):
        discover_grail_tools(
            tmp_path,
            context=None,
            externals=None,
            files_provider=_empty_files_provider,
        )


def test_discover_context_mode_includes_swarm_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_tool(tmp_path, "one")
    monkeypatch.setattr(grail_mod, "RemoraGrailTool", FakeGrailTool)

    sentinel_swarm_tool = object()
    build_swarm_tools = MagicMock(return_value=[sentinel_swarm_tool])
    monkeypatch.setattr(grail_mod, "build_swarm_tools", build_swarm_tools)

    context = MagicMock()
    context.as_externals.return_value = {"_cairn_read": object()}

    tools = discover_grail_tools(
        tmp_path,
        context=context,
        externals=None,
        files_provider=_empty_files_provider,
    )

    assert len(tools) == 2
    assert tools[-1] is sentinel_swarm_tool
    build_swarm_tools.assert_called_once_with(context)


def test_discover_externals_mode_skips_swarm_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _write_tool(tmp_path, "one")
    monkeypatch.setattr(grail_mod, "RemoraGrailTool", FakeGrailTool)

    build_swarm_tools = MagicMock(return_value=[object()])
    monkeypatch.setattr(grail_mod, "build_swarm_tools", build_swarm_tools)

    tools = discover_grail_tools(
        tmp_path,
        context=None,
        externals={"_graph_read": object()},
        files_provider=_empty_files_provider,
    )

    assert len(tools) == 1
    assert isinstance(tools[0], FakeGrailTool)
    build_swarm_tools.assert_not_called()


@pytest.mark.asyncio
async def test_workspace_tools_get_system_tool_callables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    system_dir = tmp_path / "system"
    workspace_dir = tmp_path / "workspace"
    system_dir.mkdir()
    workspace_dir.mkdir()
    _write_tool(system_dir, "graph_node")
    _write_tool(system_dir, "emit_event")
    _write_tool(workspace_dir, "workspace_summary")

    created: list[FakeGrailTool] = []

    class CapturingFakeGrailTool(FakeGrailTool):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(grail_mod, "RemoraGrailTool", CapturingFakeGrailTool)
    monkeypatch.setattr(grail_mod, "build_swarm_tools", MagicMock(return_value=[]))

    tools = discover_grail_tools(
        system_dir,
        context=None,
        externals={"_graph_read": object()},
        files_provider=_empty_files_provider,
        workspace_tools_dir=workspace_dir,
    )

    assert len(tools) == 3
    workspace_tool = created[-1]
    assert workspace_tool.script_path.name == "workspace_summary.pym"
    assert set(workspace_tool.externals.keys()) == {"graph_node", "emit_event"}

    output = await workspace_tool.externals["graph_node"](node_id="node:1")
    assert output == "graph_node:{'node_id': 'node:1'}"
