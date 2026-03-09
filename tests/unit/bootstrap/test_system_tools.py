from __future__ import annotations

import json
from pathlib import Path

import grail
import pytest

TOOLS_DIR = Path("bootstrap/tools")
EXPECTED_FILES = {
    "read_file.pym",
    "write_file.pym",
    "graph_node.pym",
    "graph_neighbors.pym",
    "graph_find_nodes.pym",
    "graph_add_node.pym",
    "graph_add_edge.pym",
    "read_recent_events.pym",
    "emit_event.pym",
}


def _load_tool(path: Path, grail_dir: Path):
    return grail.load(str(path), grail_dir=grail_dir)


def test_all_system_tool_files_exist_and_compile(tmp_path: Path) -> None:
    files = {path.name for path in TOOLS_DIR.glob("*.pym")}
    assert files == EXPECTED_FILES

    grail_dir = tmp_path / ".grail"
    for pym_file in TOOLS_DIR.glob("*.pym"):
        script = _load_tool(pym_file, grail_dir)
        assert script is not None


def test_pym_externals_are_bedrock_names(tmp_path: Path) -> None:
    bedrock_names = {
        "cairn_read",
        "cairn_write",
        "graph_read",
        "graph_write",
        "event_read",
        "event_write",
    }

    grail_dir = tmp_path / ".grail"
    for pym_file in TOOLS_DIR.glob("*.pym"):
        script = _load_tool(pym_file, grail_dir)
        assert set(script.externals).issubset(bedrock_names)


@pytest.mark.asyncio
async def test_read_file_tool_calls_cairn_read(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "read_file.pym", tmp_path / ".grail")

    async def _cairn_read(path: str) -> str:
        return f"read:{path}"

    result = await script.run(
        inputs={"path": "notes.md"},
        externals={"cairn_read": _cairn_read},
    )
    assert result == "read:notes.md"


@pytest.mark.asyncio
async def test_graph_find_nodes_routes_to_graph_read(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "graph_find_nodes.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _graph_read(selector: dict) -> str:
        captured["selector"] = selector
        return json.dumps([{"id": "n1", "kind": "function", "attrs": {}}])

    result = await script.run(
        inputs={"kind": "function"},
        externals={"graph_read": _graph_read},
    )

    assert captured["selector"] == {"match": {"kind": "function"}}
    payload = json.loads(result)
    assert payload[0]["kind"] == "function"
