from __future__ import annotations

from pathlib import Path
import json

import pytest

from remora.discovery import DiscoveryError, PydantreeDiscoverer
from remora.errors import DISC_002

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample.py"


def _fixture_nodes() -> list[dict]:
    source = FIXTURE_PATH.read_text(encoding="utf-8")
    source_bytes = source.encode("utf-8")

    def span(text: str) -> tuple[int, int]:
        start = source_bytes.index(text.encode("utf-8"))
        return start, start + len(text.encode("utf-8"))

    class_block = 'class Greeter:\n    def greet(self, name: str) -> str:\n        return f"Hello, {name}!"\n'
    greet_block = 'def greet(self, name: str) -> str:\n        return f"Hello, {name}!"\n'
    add_block = "def add(x: int, y: int) -> int:\n    return x + y\n"

    class_start, class_end = span(class_block)
    greet_start, greet_end = span(greet_block)
    add_start, add_end = span(add_block)

    return [
        {
            "file_path": str(FIXTURE_PATH),
            "node_type": "file",
            "name": FIXTURE_PATH.stem,
            "start_byte": 0,
            "end_byte": len(source_bytes),
        },
        {
            "file_path": str(FIXTURE_PATH),
            "node_type": "class",
            "name": "Greeter",
            "start_byte": class_start,
            "end_byte": class_end,
        },
        {
            "file_path": str(FIXTURE_PATH),
            "node_type": "function",
            "name": "greet",
            "start_byte": greet_start,
            "end_byte": greet_end,
        },
        {
            "file_path": str(FIXTURE_PATH),
            "node_type": "function",
            "name": "add",
            "start_byte": add_start,
            "end_byte": add_end,
        },
    ]


class _Completed:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _patch_pydantree(monkeypatch: pytest.MonkeyPatch, nodes: list[dict]) -> None:
    def _fake_run(*_args, **_kwargs):
        return _Completed(stdout=json.dumps({"nodes": nodes}))

    monkeypatch.setattr("remora.discovery.subprocess.run", _fake_run)


def test_discovery_returns_expected_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = _fixture_nodes()
    _patch_pydantree(monkeypatch, nodes)
    discoverer = PydantreeDiscoverer([FIXTURE_PATH.parent], "python", "remora_core")
    results = discoverer.discover()
    expected = {("file", "sample"), ("class", "Greeter"), ("function", "greet"), ("function", "add")}
    assert {(node.node_type, node.name) for node in results} == expected


def test_node_ids_are_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = _fixture_nodes()
    _patch_pydantree(monkeypatch, nodes)
    discoverer = PydantreeDiscoverer([FIXTURE_PATH.parent], "python", "remora_core")
    first = [node.node_id for node in discoverer.discover()]
    second = [node.node_id for node in discoverer.discover()]
    assert first == second


def test_overlapping_queries_produce_distinct_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = _fixture_nodes()
    _patch_pydantree(monkeypatch, nodes)
    discoverer = PydantreeDiscoverer([FIXTURE_PATH.parent], "python", "remora_core")
    results = discoverer.discover()
    class_node = next(node for node in results if node.node_type == "class")
    function_node = next(node for node in results if node.name == "greet")
    assert class_node.node_id != function_node.node_id


def test_missing_span_raises_disc_002(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = _fixture_nodes()
    nodes[1].pop("start_byte")
    _patch_pydantree(monkeypatch, nodes)
    discoverer = PydantreeDiscoverer([FIXTURE_PATH.parent], "python", "remora_core")
    with pytest.raises(DiscoveryError) as exc:
        discoverer.discover()
    assert exc.value.code == DISC_002


def test_node_text_matches_source_span(monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = _fixture_nodes()
    _patch_pydantree(monkeypatch, nodes)
    discoverer = PydantreeDiscoverer([FIXTURE_PATH.parent], "python", "remora_core")
    results = discoverer.discover()
    source_bytes = FIXTURE_PATH.read_bytes()
    for node in results:
        expected = source_bytes[node.start_byte : node.end_byte].decode("utf-8")
        assert node.text == expected
