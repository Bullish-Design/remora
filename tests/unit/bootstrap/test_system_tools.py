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
    "user_question.pym",
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


@pytest.mark.asyncio
async def test_user_question_emits_human_input_request_event(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "user_question.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _event_write(event_type: str, payload: dict) -> str:
        captured["event_type"] = event_type
        captured["payload"] = payload
        return json.dumps({"event_id": 99})

    result = await script.run(
        inputs={
            "question": "What should this function return?",
            "request_id": "req-123",
            "node_id": "function:src/app.py:42",
        },
        externals={"event_write": _event_write},
    )

    assert json.loads(result)["event_id"] == 99
    assert captured["event_type"] == "HumanInputRequestEvent"
    assert captured["payload"] == {
        "question": "What should this function return?",
        "request_id": "req-123",
        "node_id": "function:src/app.py:42",
        "kind": "user_question",
    }


@pytest.mark.asyncio
async def test_write_file_tool_calls_cairn_write(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "write_file.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _cairn_write(path: str, content: str) -> str:
        captured["path"] = path
        captured["content"] = content
        return "ok"

    result = await script.run(
        inputs={"path": "notes.md", "content": "hello world"},
        externals={"cairn_write": _cairn_write},
    )

    assert result == "ok"
    assert captured["path"] == "notes.md"
    assert captured["content"] == "hello world"


@pytest.mark.asyncio
async def test_graph_node_tool_calls_graph_read(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "graph_node.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _graph_read(selector: dict) -> str:
        captured["selector"] = selector
        return json.dumps({"id": "n1", "kind": "function", "attrs": {"name": "foo"}})

    result = await script.run(
        inputs={"node_id": "n1"},
        externals={"graph_read": _graph_read},
    )

    assert captured["selector"] == {"node": "n1"}
    payload = json.loads(result)
    assert payload["id"] == "n1"


@pytest.mark.asyncio
async def test_graph_neighbors_tool_calls_graph_read(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "graph_neighbors.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _graph_read(selector: dict) -> str:
        captured["selector"] = selector
        return json.dumps([{"id": "n2", "kind": "function", "attrs": {}, "edge_kind": "calls"}])

    result = await script.run(
        inputs={"node_id": "n1", "direction": "out"},
        externals={"graph_read": _graph_read},
    )

    assert captured["selector"] == {"neighbors": "n1", "dir": "out"}
    payload = json.loads(result)
    assert payload[0]["id"] == "n2"


@pytest.mark.asyncio
async def test_graph_add_node_tool_calls_graph_write(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "graph_add_node.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _graph_write(op: str, data: dict) -> str:
        captured["op"] = op
        captured["data"] = data
        return json.dumps({"id": "generated-uuid", "kind": "custom"})

    result = await script.run(
        inputs={"kind": "custom", "attrs": {"label": "my-node"}},
        externals={"graph_write": _graph_write},
    )

    assert captured["op"] == "add_node"
    assert captured["data"] == {"kind": "custom", "attrs": {"label": "my-node"}}
    payload = json.loads(result)
    assert payload["id"] == "generated-uuid"


@pytest.mark.asyncio
async def test_graph_add_edge_tool_calls_graph_write(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "graph_add_edge.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _graph_write(op: str, data: dict) -> str:
        captured["op"] = op
        captured["data"] = data
        return json.dumps({"ok": True})

    result = await script.run(
        inputs={"from_id": "n1", "to_id": "n2", "kind": "calls"},
        externals={"graph_write": _graph_write},
    )

    assert captured["op"] == "add_edge"
    assert captured["data"] == {"from": "n1", "to": "n2", "kind": "calls"}
    assert json.loads(result)["ok"] is True


@pytest.mark.asyncio
async def test_read_recent_events_tool_calls_event_read(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "read_recent_events.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _event_read(selector: dict) -> str:
        captured["selector"] = selector
        return json.dumps([{"event_type": "AgentNeededEvent", "payload": {}}])

    result = await script.run(
        inputs={"node_id": "module:src/app.py", "limit": 5},
        externals={"event_read": _event_read},
    )

    assert captured["selector"] == {"node_id": "module:src/app.py", "limit": 5}
    payload = json.loads(result)
    assert payload[0]["event_type"] == "AgentNeededEvent"


@pytest.mark.asyncio
async def test_emit_event_tool_calls_event_write(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "emit_event.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _event_write(event_type: str, payload: dict) -> str:
        captured["event_type"] = event_type
        captured["payload"] = payload
        return json.dumps({"event_id": 7})

    result = await script.run(
        inputs={"event_type": "CustomEvent", "payload": {"key": "value"}},
        externals={"event_write": _event_write},
    )

    assert captured["event_type"] == "CustomEvent"
    assert captured["payload"] == {"key": "value"}
    assert json.loads(result)["event_id"] == 7
