"""Tests for the tree-sitter discovery pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.discovery import (
    CSTNode,
    DiscoveryError,
    MatchExtractor,
    NodeType,
    QueryLoader,
    SourceParser,
    TreeSitterDiscoverer,
    compute_node_id,
)
from remora.errors import DISC_001, DISC_003, DISC_004

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PY = FIXTURE_DIR / "sample.py"


class TestNodeType:
    def test_string_equality(self) -> None:
        assert NodeType.FUNCTION == "function"
        assert NodeType.METHOD == "method"
        assert NodeType.CLASS == "class"
        assert NodeType.FILE == "file"

    def test_from_string(self) -> None:
        assert NodeType("function") == NodeType.FUNCTION


class TestComputeNodeId:
    def test_deterministic(self) -> None:
        id1 = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
        id2 = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
        assert id1 == id2

    def test_length(self) -> None:
        nid = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
        assert len(nid) == 16

    def test_different_types_differ(self) -> None:
        f_id = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
        m_id = compute_node_id(Path("test.py"), NodeType.METHOD, "hello")
        assert f_id != m_id

    def test_different_names_differ(self) -> None:
        id1 = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
        id2 = compute_node_id(Path("test.py"), NodeType.FUNCTION, "goodbye")
        assert id1 != id2


class TestCSTNode:
    def test_frozen(self) -> None:
        node = CSTNode(
            node_id="test",
            node_type=NodeType.FUNCTION,
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
            node_type=NodeType.FUNCTION,
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
            node_type=NodeType.METHOD,
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
        parser = SourceParser()
        tree, source = parser.parse_file(SAMPLE_PY)
        assert tree.root_node.type == "module"
        assert len(source) > 0

    def test_parse_bytes(self) -> None:
        parser = SourceParser()
        source = b"def hello(): pass"
        tree = parser.parse_bytes(source)
        assert tree.root_node.type == "module"
        assert tree.root_node.child_count == 1

    def test_parse_invalid_syntax(self) -> None:
        parser = SourceParser()
        tree = parser.parse_bytes(b"def broken(:\n  pass")
        assert tree.root_node.has_error

    def test_parse_nonexistent_file(self) -> None:
        parser = SourceParser()
        with pytest.raises(DiscoveryError) as exc:
            parser.parse_file(Path("nonexistent_12345.py"))
        assert exc.value.code == DISC_004


class TestQueryLoader:
    def test_load_query_pack(self) -> None:
        loader = QueryLoader()
        queries = loader.load_query_pack(
            Path("remora/queries"),
            "python",
            "remora_core",
        )
        assert len(queries) == 3
        names = {q.name for q in queries}
        assert names == {"class_def", "file", "function_def"}

    def test_missing_query_pack(self) -> None:
        loader = QueryLoader()
        with pytest.raises(DiscoveryError) as exc:
            loader.load_query_pack(
                Path("remora/queries"),
                "python",
                "nonexistent",
            )
        assert exc.value.code == DISC_001

    def test_bad_query_syntax(self, tmp_path: Path) -> None:
        loader = QueryLoader()
        pack_dir = tmp_path / "python" / "test_pack"
        pack_dir.mkdir(parents=True)
        (pack_dir / "bad.scm").write_text("(broken syntax @capture")

        with pytest.raises(DiscoveryError) as exc:
            loader.load_query_pack(tmp_path, "python", "test_pack")
        assert exc.value.code == DISC_003


class TestMatchExtractor:
    def test_extract_from_sample(self) -> None:
        parser = SourceParser()
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("remora/queries"),
            "python",
            "remora_core",
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        assert len(nodes) >= 4

        node_types = {n.node_type for n in nodes}
        assert NodeType.FILE in node_types
        assert NodeType.CLASS in node_types
        assert NodeType.METHOD in node_types
        assert NodeType.FUNCTION in node_types

    def test_method_has_full_name(self) -> None:
        parser = SourceParser()
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("remora/queries"),
            "python",
            "remora_core",
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        method_nodes = [n for n in nodes if n.node_type == NodeType.METHOD]
        assert len(method_nodes) == 1
        assert method_nodes[0].name == "greet"
        assert method_nodes[0].full_name == "Greeter.greet"

    def test_function_not_method(self) -> None:
        parser = SourceParser()
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("remora/queries"),
            "python",
            "remora_core",
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        function_nodes = [n for n in nodes if n.node_type == NodeType.FUNCTION]
        assert len(function_nodes) == 1
        assert function_nodes[0].name == "add"
        assert function_nodes[0].full_name == "add"


class TestTreeSitterDiscoverer:
    def test_discover_from_directory(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[FIXTURE_DIR],
            language="python",
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        assert len(nodes) >= 4

        sample_nodes = [n for n in nodes if n.file_path.name == "sample.py"]
        assert len(sample_nodes) >= 4

        node_types = {n.node_type for n in sample_nodes}
        assert NodeType.FILE in node_types
        assert NodeType.CLASS in node_types
        assert NodeType.METHOD in node_types
        assert NodeType.FUNCTION in node_types

    def test_discover_from_single_file(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            language="python",
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        assert len(nodes) >= 4
        assert all(n.file_path == SAMPLE_PY for n in nodes)

    def test_discover_empty_directory(self, tmp_path: Path) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[tmp_path],
            language="python",
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
        assert nodes == []

    def test_discover_nonexistent_directory(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[Path("nonexistent_12345")],
            language="python",
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
        assert nodes == []

    def test_node_ids_are_stable(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            language="python",
            query_pack="remora_core",
        )
        first_ids = sorted(n.node_id for n in discoverer.discover())
        second_ids = sorted(n.node_id for n in discoverer.discover())
        assert first_ids == second_ids

    def test_node_text_matches_source(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            language="python",
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
            language="python",
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
            language="python",
            query_pack="remora_core",
            event_emitter=MockEmitter(),
        )
        discoverer.discover()

        assert len(events) == 1
        assert events[0]["event"] == "discovery"
        assert events[0]["status"] == "ok"
        assert "duration_ms" in events[0]
