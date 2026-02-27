"""Tests for the tree-sitter discovery pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.discovery import CSTNode, compute_node_id, discover

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PY = FIXTURE_DIR / "sample.py"
SAMPLE_TOML = FIXTURE_DIR / "sample.toml"
SAMPLE_MD = FIXTURE_DIR / "sample.md"


class TestComputeNodeId:
    def test_deterministic(self) -> None:
        id1 = compute_node_id("test.py", "hello", 1, 2)
        id2 = compute_node_id("test.py", "hello", 1, 2)
        assert id1 == id2

    def test_length(self) -> None:
        nid = compute_node_id("test.py", "hello", 1, 2)
        assert len(nid) == 16

    def test_different_names_differ(self) -> None:
        id1 = compute_node_id("test.py", "hello", 1, 2)
        id2 = compute_node_id("test.py", "goodbye", 1, 2)
        assert id1 != id2


class TestCSTNode:
    def test_frozen(self) -> None:
        node = CSTNode(
            node_id="test",
            node_type="function",
            name="hello",
            full_name="function:hello",
            file_path=str(SAMPLE_PY),
            start_byte=0,
            end_byte=10,
            text="def hello(): ...",
            start_line=1,
            end_line=1,
        )
        with pytest.raises(Exception):
            node.name = "changed"


class TestDiscover:
    def test_discover_python_nodes(self) -> None:
        nodes = discover([SAMPLE_PY], languages=["python"])
        node_types = {n.node_type for n in nodes}
        assert "file" in node_types
        assert "class" in node_types
        assert "method" in node_types
        assert "function" in node_types

    def test_node_text_matches_source(self) -> None:
        nodes = discover([SAMPLE_PY], languages=["python"])
        source = SAMPLE_PY.read_text(encoding="utf-8")
        for node in nodes:
            expected = source[node.start_byte : node.end_byte]
            assert node.text == expected

    def test_discover_toml_tables(self) -> None:
        nodes = discover([SAMPLE_TOML], languages=["toml"])
        node_types = {n.node_type for n in nodes}
        assert "file" in node_types
        assert "table" in node_types

    def test_discover_markdown_sections(self) -> None:
        nodes = discover([SAMPLE_MD], languages=["markdown"])
        node_types = {n.node_type for n in nodes}
        assert "file" in node_types
        assert "section" in node_types
