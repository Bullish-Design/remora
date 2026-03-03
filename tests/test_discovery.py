"""Tests for the tree-sitter discovery pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.discovery import CSTNode, compute_node_id, discover, parse_content

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


class TestCSTNodeIsPydantic:
    """CSTNode should be a Pydantic BaseModel with custom node_id-only __hash__."""

    def test_cstnode_is_pydantic_model(self) -> None:
        from pydantic import BaseModel

        assert issubclass(CSTNode, BaseModel), "CSTNode should be a Pydantic BaseModel"

    def test_cstnode_hash_uses_only_node_id(self) -> None:
        """Two CSTNodes with same node_id but different text should hash equally."""
        a = CSTNode(
            node_id="abc123",
            node_type="function",
            name="foo",
            full_name="mod.foo",
            file_path="a.py",
            text="def foo(): pass",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=15,
        )
        b = CSTNode(
            node_id="abc123",
            node_type="function",
            name="foo",
            full_name="mod.foo",
            file_path="a.py",
            text="def foo(): return 42",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=20,
        )
        assert hash(a) == hash(b), "CSTNodes with same node_id must have equal hash"
        assert a != b, "CSTNodes with different text should not be equal"

    def test_cstnode_is_frozen(self) -> None:
        """CSTNode should be immutable."""
        node = CSTNode(
            node_id="abc123",
            node_type="function",
            name="foo",
            full_name="mod.foo",
            file_path="a.py",
            text="def foo(): pass",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=15,
        )
        with pytest.raises((AttributeError, ValueError)):
            node.name = "bar"  # type: ignore[misc]


class TestParseContent:
    """Tests for parse_content() — the public API that accepts text directly."""

    def test_python_functions_and_classes(self) -> None:
        """parse_content() should extract functions, classes, and methods from Python."""
        code = "def top_func():\n    pass\n\nclass MyClass:\n    def my_method(self):\n        pass\n"
        nodes = parse_content("test.py", code)
        node_types = {n.node_type for n in nodes}
        assert "file" in node_types
        assert "function" in node_types
        assert "class" in node_types
        assert "method" in node_types

    def test_python_node_names(self) -> None:
        """parse_content() should extract correct names."""
        code = "def hello():\n    pass\n\ndef world():\n    pass\n"
        nodes = parse_content("test.py", code)
        names = {n.name for n in nodes if n.node_type == "function"}
        assert "hello" in names
        assert "world" in names

    def test_python_text_matches_content(self) -> None:
        """Node text should match the source content at byte offsets."""
        code = "def hello():\n    pass\n"
        nodes = parse_content("test.py", code)
        for node in nodes:
            expected = code[node.start_byte : node.end_byte]
            assert node.text == expected, f"Node {node.name}: text mismatch"

    def test_returns_cstnode_list(self) -> None:
        """parse_content() must return list[CSTNode]."""
        nodes = parse_content("test.py", "x = 1\n")
        assert isinstance(nodes, list)
        for n in nodes:
            assert isinstance(n, CSTNode)

    def test_deterministic_ids(self) -> None:
        """Same input should produce same node IDs."""
        code = "def foo():\n    pass\n"
        nodes1 = parse_content("test.py", code)
        nodes2 = parse_content("test.py", code)
        ids1 = [n.node_id for n in nodes1]
        ids2 = [n.node_id for n in nodes2]
        assert ids1 == ids2

    def test_language_auto_detection(self) -> None:
        """Language should be auto-detected from file extension."""
        py_nodes = parse_content("test.py", "def foo(): pass\n")
        assert any(n.node_type == "function" for n in py_nodes)

    def test_language_explicit(self) -> None:
        """Explicit language should override file extension."""
        # Even with .txt extension, should parse as Python if language is explicit
        nodes = parse_content("test.txt", "def foo(): pass\n", language="python")
        assert any(n.node_type == "function" for n in nodes)

    def test_unknown_extension_returns_file_node(self) -> None:
        """Unknown extension with no explicit language returns a file-level node."""
        nodes = parse_content("test.xyz", "some content\n")
        assert len(nodes) >= 1
        assert any(n.node_type == "file" for n in nodes)

    def test_empty_content(self) -> None:
        """Empty content should still return at least a file node."""
        nodes = parse_content("test.py", "")
        assert len(nodes) >= 1
        assert any(n.node_type == "file" for n in nodes)

    def test_markdown_sections(self) -> None:
        """parse_content() should extract Markdown sections."""
        md = "# Introduction\n\nSome text.\n\n## Details\n\nMore text.\n"
        nodes = parse_content("readme.md", md)
        node_types = {n.node_type for n in nodes}
        assert "section" in node_types

    def test_toml_tables(self) -> None:
        """parse_content() should extract TOML tables."""
        toml = "[project]\nname = 'test'\n\n[tool.pytest]\naddopts = '-v'\n"
        nodes = parse_content("pyproject.toml", toml)
        node_types = {n.node_type for n in nodes}
        assert "table" in node_types

    def test_file_path_preserved(self) -> None:
        """All nodes should have the file_path set to the input path."""
        code = "def foo(): pass\n"
        nodes = parse_content("src/module.py", code)
        for node in nodes:
            assert node.file_path == "src/module.py"

    def test_multibyte_characters(self) -> None:
        """Should handle multibyte UTF-8 correctly."""
        code = "# Comment with emoji: \u2728\ndef read_optional(path):\n    pass\n"
        nodes = parse_content("test.py", code)
        names = [n.name for n in nodes if n.node_type == "function"]
        assert "read_optional" in names
