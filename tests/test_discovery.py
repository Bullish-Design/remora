from __future__ import annotations

from pathlib import Path

import pytest

from remora.discovery import DiscoveryError, NodeDiscoverer
from remora.errors import DISC_002

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample.py"


def test_discovery_returns_expected_nodes() -> None:
    discoverer = NodeDiscoverer([FIXTURE_PATH], ["file", "class_def", "function_def"])
    nodes = discoverer.discover()
    expected = {
        ("file", "sample"),
        ("class", "Greeter"),
        ("function", "greet"),
        ("function", "add"),
    }
    assert {(node.node_type, node.name) for node in nodes} == expected


def test_node_ids_are_stable() -> None:
    discoverer = NodeDiscoverer([FIXTURE_PATH], ["class_def", "function_def"])
    first = [node.node_id for node in discoverer.discover()]
    second = [node.node_id for node in discoverer.discover()]
    assert first == second


def test_overlapping_queries_produce_distinct_nodes() -> None:
    discoverer = NodeDiscoverer([FIXTURE_PATH], ["class_def", "function_def"])
    nodes = discoverer.discover()
    class_node = next(node for node in nodes if node.node_type == "class")
    function_node = next(node for node in nodes if node.name == "greet")
    assert class_node.node_id != function_node.node_id


def test_malformed_query_returns_disc_002(tmp_path: Path) -> None:
    query_path = tmp_path / "broken.scm"
    query_path.write_text("(function_definition", encoding="utf-8")
    discoverer = NodeDiscoverer([FIXTURE_PATH], ["broken"], queries_dir=tmp_path)
    with pytest.raises(DiscoveryError) as exc:
        discoverer.discover()
    assert exc.value.code == DISC_002


def test_node_text_matches_source_span() -> None:
    discoverer = NodeDiscoverer([FIXTURE_PATH], ["file", "class_def", "function_def"])
    nodes = discoverer.discover()
    source_bytes = FIXTURE_PATH.read_bytes()
    for node in nodes:
        expected = source_bytes[node.start_byte : node.end_byte].decode("utf-8")
        assert node.text == expected
