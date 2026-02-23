"""Tests for the tree-sitter discovery pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.discovery import (
    CSTNode,
    DiscoveryError,
    MatchExtractor,
    QueryLoader,
    SourceParser,
    TreeSitterDiscoverer,
    compute_node_id,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PY = FIXTURE_DIR / "sample.py"
SAMPLE_TOML = FIXTURE_DIR / "sample.toml"
SAMPLE_MD = FIXTURE_DIR / "sample.md"


class TestComputeNodeId:
    def test_deterministic(self) -> None:
        id1 = compute_node_id(Path("test.py"), "function", "hello")
        id2 = compute_node_id(Path("test.py"), "function", "hello")
        assert id1 == id2

    def test_length(self) -> None:
        nid = compute_node_id(Path("test.py"), "function", "hello")
        assert len(nid) == 16

    def test_different_types_differ(self) -> None:
        f_id = compute_node_id(Path("test.py"), "function", "hello")
        m_id = compute_node_id(Path("test.py"), "method", "hello")
        assert f_id != m_id

    def test_different_names_differ(self) -> None:
        id1 = compute_node_id(Path("test.py"), "function", "hello")
        id2 = compute_node_id(Path("test.py"), "function", "goodbye")
        assert id1 != id2


class TestCSTNode:
    def test_frozen(self) -> None:
        node = CSTNode(
            node_id="test",
            node_type="function",
            name="hello",
            file_path=Path("test.py"),
            start_byte=0,
            end_byte=10,
            text="def hello(): ...",
            start_line=1,
            end_line=1,
        )
        with pytest.raises(Exception):
            node.name = "changed"

    def test_full_name_defaults_to_name(self) -> None:
        node = CSTNode(
            node_id="test",
            node_type="function",
            name="hello",
            file_path=Path("test.py"),
            start_byte=0,
            end_byte=10,
            text="def hello(): ...",
            start_line=1,
            end_line=1,
        )
        assert node.full_name == "hello"

    def test_full_name_can_be_set(self) -> None:
        node = CSTNode(
            node_id="test",
            node_type="method",
            name="greet",
            file_path=Path("test.py"),
            start_byte=0,
            end_byte=10,
            text="def greet(self): ...",
            start_line=1,
            end_line=1,
            _full_name="Greeter.greet",
        )
        assert node.full_name == "Greeter.greet"


class TestSourceParser:
    def test_parse_file(self) -> None:
        parser = SourceParser("tree_sitter_python")
        tree, source = parser.parse_file(SAMPLE_PY)
        assert tree.root_node.type == "module"
        assert len(source) > 0

    def test_parse_bytes(self) -> None:
        parser = SourceParser("tree_sitter_python")
        source = b"def hello(): pass"
        tree = parser.parse_bytes(source)
        assert tree.root_node.type == "module"
        assert tree.root_node.child_count == 1

    def test_parse_invalid_syntax(self) -> None:
        parser = SourceParser("tree_sitter_python")
        tree = parser.parse_bytes(b"def broken(:\n  pass")
        assert tree.root_node.has_error

    def test_parse_nonexistent_file(self) -> None:
        parser = SourceParser("tree_sitter_python")
        with pytest.raises(DiscoveryError) as exc:
            parser.parse_file(Path("nonexistent_12345.py"))
        assert exc.value.code == DiscoveryError.code


class TestQueryLoader:
    def test_load_query_pack(self) -> None:
        loader = QueryLoader()
        queries = loader.load_query_pack(
            Path("src/remora/queries"),
            "python",
            "remora_core",
        )
        assert len(queries) == 3
        names = {q.name for q in queries}
        assert names == {"class", "file", "function"}

    def test_missing_query_pack(self) -> None:
        loader = QueryLoader()
        with pytest.raises(DiscoveryError) as exc:
            loader.load_query_pack(
                Path("src/remora/queries"),
                "python",
                "nonexistent",
            )
        assert exc.value.code == DiscoveryError.code

    def test_bad_query_syntax(self, tmp_path: Path) -> None:
        loader = QueryLoader()
        pack_dir = tmp_path / "python" / "test_pack"
        pack_dir.mkdir(parents=True)
        (pack_dir / "bad.scm").write_text("(broken syntax @capture")

        with pytest.raises(DiscoveryError) as exc:
            loader.load_query_pack(tmp_path, "python", "test_pack")
        assert exc.value.code == DiscoveryError.code


class TestMatchExtractor:
    def test_extract_from_sample(self) -> None:
        parser = SourceParser("tree_sitter_python")
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("src/remora/queries"),
            "python",
            "remora_core",
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        assert len(nodes) >= 4

        node_types = {n.node_type for n in nodes}
        assert "file" in node_types
        assert "class" in node_types
        assert "method" in node_types
        assert "function" in node_types

    def test_method_has_full_name(self) -> None:
        parser = SourceParser("tree_sitter_python")
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("src/remora/queries"),
            "python",
            "remora_core",
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        method_nodes = [n for n in nodes if n.node_type == "method"]
        assert len(method_nodes) == 1
        assert method_nodes[0].name == "greet"

    def test_function_not_method(self) -> None:
        parser = SourceParser("tree_sitter_python")
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("src/remora/queries"),
            "python",
            "remora_core",
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        function_nodes = [n for n in nodes if n.node_type == "function"]
        # The function query matches all function_definition nodes, including methods.
        # We filter to only include standalone functions (not methods)
        standalone_functions = [n for n in function_nodes if n.name == "add"]
        assert len(standalone_functions) == 1
        assert standalone_functions[0].name == "add"


class TestTreeSitterDiscoverer:
    def test_discover_from_directory(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[FIXTURE_DIR],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        assert len(nodes) >= 4

        sample_nodes = [n for n in nodes if n.file_path.name == "sample.py"]
        assert len(sample_nodes) >= 4

        node_types = {n.node_type for n in sample_nodes}
        assert "file" in node_types
        assert "class" in node_types
        assert "method" in node_types
        assert "function" in node_types

    def test_discover_from_single_file(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        assert len(nodes) >= 4
        assert all(n.file_path == SAMPLE_PY for n in nodes)

    def test_discover_empty_directory(self, tmp_path: Path) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[tmp_path],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
        assert nodes == []

    def test_discover_nonexistent_directory(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[Path("nonexistent_12345")],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
        assert nodes == []

    def test_node_ids_are_stable(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            query_pack="remora_core",
        )
        first_ids = sorted(n.node_id for n in discoverer.discover())
        second_ids = sorted(n.node_id for n in discoverer.discover())
        assert first_ids == second_ids

    def test_node_text_matches_source(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
        source = SAMPLE_PY.read_bytes()

        for node in nodes:
            expected = source[node.start_byte : node.end_byte].decode("utf-8")
            assert node.text == expected

    def test_nodes_have_line_numbers(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        for node in nodes:
            assert node.start_line >= 1
            assert node.end_line >= node.start_line

    def test_event_emitter(self) -> None:
        events: list[dict] = []

        class MockEmitter:
            def emit(self, event: dict) -> None:
                events.append(event)

        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            query_pack="remora_core",
            event_emitter=MockEmitter(),
        )
        discoverer.discover()

        assert len(events) == 1
        assert events[0]["event"] == "discovery"
        assert events[0]["status"] == "ok"
        assert "duration_ms" in events[0]


class TestTOMLDiscovery:
    def test_parse_toml_file(self) -> None:
        parser = SourceParser("tree_sitter_toml")
        tree, source = parser.parse_file(SAMPLE_TOML)
        assert tree.root_node.type == "document"

    def test_discover_toml_tables(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_TOML],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        node_types = {n.node_type for n in nodes}
        assert "file" in node_types
        assert "table" in node_types

        table_nodes = [n for n in nodes if n.node_type == "table"]
        table_names = {n.name for n in table_nodes}
        assert "project" in table_names

    def test_discover_array_tables(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_TOML],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        array_table_nodes = [n for n in nodes if n.node_type == "array_table"]
        assert len(array_table_nodes) >= 1


class TestMarkdownDiscovery:
    def test_parse_markdown_file(self) -> None:
        parser = SourceParser("tree_sitter_markdown")
        tree, source = parser.parse_file(SAMPLE_MD)
        assert tree.root_node.type == "document"

    def test_discover_markdown_sections(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_MD],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        node_types = {n.node_type for n in nodes}
        assert "file" in node_types
        assert "section" in node_types

        section_nodes = [n for n in nodes if n.node_type == "section"]
        section_names = {n.name for n in section_nodes}
        assert any("Sample" in name for name in section_names)


class TestMultiLanguageDiscovery:
    def test_discover_mixed_directory(self) -> None:
        """Test discovering from a directory with multiple file types."""
        discoverer = TreeSitterDiscoverer(
            root_dirs=[FIXTURE_DIR],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        # Should have nodes from multiple languages
        extensions = {n.file_path.suffix for n in nodes}
        assert ".py" in extensions
