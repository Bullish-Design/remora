"""Match extraction and CSTNode construction from tree-sitter queries."""

from __future__ import annotations

import logging
from pathlib import Path

from tree_sitter import Node, QueryCursor, Tree

from remora.discovery.models import CSTNode, NodeType, compute_node_id

logger = logging.getLogger(__name__)

# Map capture-name prefixes to base NodeType.
_PREFIX_TO_NODE_TYPE: dict[str, NodeType] = {
    "file": NodeType.FILE,
    "class": NodeType.CLASS,
    "function": NodeType.FUNCTION,
}


class MatchExtractor:
    """Executes compiled queries against parsed trees and builds CSTNode lists.

    Usage:
        extractor = MatchExtractor()
        nodes = extractor.extract(
            file_path=Path("example.py"),
            tree=tree,
            source_bytes=source_bytes,
            queries=[compiled_query_1, compiled_query_2],
        )
    """

    def extract(
        self,
        file_path: Path,
        tree: Tree,
        source_bytes: bytes,
        queries: list,
    ) -> list[CSTNode]:
        """Run all queries against a tree and return discovered CSTNodes.

        Args:
            file_path: Path to the source file (for node_id and file_path fields).
            tree: Parsed tree-sitter tree.
            source_bytes: Raw source bytes (for text extraction).
            queries: List of compiled queries to execute.

        Returns:
            Deduplicated, sorted list of CSTNode instances.
        """
        nodes: list[CSTNode] = []
        seen_ids: set[str] = set()

        for compiled_query in queries:
            new_nodes = self._run_query(file_path, tree, source_bytes, compiled_query)
            for node in new_nodes:
                if node.node_id not in seen_ids:
                    seen_ids.add(node.node_id)
                    nodes.append(node)

        nodes.sort(key=lambda n: (str(n.file_path), n.start_byte, n.node_type.value, n.name))
        return nodes

    def _run_query(
        self,
        file_path: Path,
        tree: Tree,
        source_bytes: bytes,
        compiled_query,
    ) -> list[CSTNode]:
        """Run a single query and extract CSTNodes from matches."""
        cursor = QueryCursor(compiled_query.query)
        captures = cursor.captures(tree.root_node)
        nodes: list[CSTNode] = []

        # Group captures by pattern (group by the @X.def capture)
        # For now, process each capture individually
        for capture_name, ts_nodes in captures.items():
            for ts_node in ts_nodes:
                node = self._build_node_from_capture(file_path, source_bytes, capture_name, ts_node)
                if node is not None:
                    nodes.append(node)

        return nodes

    def _build_node_from_capture(
        self,
        file_path: Path,
        source_bytes: bytes,
        capture_name: str,
        ts_node: Node,
    ) -> CSTNode | None:
        """Build a CSTNode from a single capture.

        The capture_name follows the convention @X.def or @X.name
        where X is one of: file, class, function
        """
        parts = capture_name.split(".")
        if len(parts) != 2:
            return None

        prefix, suffix = parts
        base_type = _PREFIX_TO_NODE_TYPE.get(prefix)

        if base_type is None:
            return None

        # Only process .def captures to create nodes
        if suffix != "def":
            return None

        # Extract the name from the corresponding @X.name capture
        # For now, try to get name from the node itself
        name_text = self._extract_name_from_node(ts_node, source_bytes)

        # For FILE nodes, use file stem as name
        if base_type == NodeType.FILE:
            name_text = file_path.stem

        if not name_text:
            name_text = "unknown"

        # Determine if a FUNCTION is actually a METHOD by inspecting parents
        actual_type = base_type
        full_name = name_text
        if base_type == NodeType.FUNCTION:
            actual_type, full_name = self._classify_function(ts_node, name_text, source_bytes)

        text = source_bytes[ts_node.start_byte : ts_node.end_byte].decode("utf-8", errors="replace")

        node_id = compute_node_id(file_path, actual_type, name_text)

        return CSTNode(
            node_id=node_id,
            node_type=actual_type,
            name=name_text,
            file_path=file_path,
            start_byte=ts_node.start_byte,
            end_byte=ts_node.end_byte,
            text=text,
            start_line=ts_node.start_point.row + 1,  # tree-sitter is 0-indexed
            end_line=ts_node.end_point.row + 1,
            _full_name=full_name,
        )

    def _extract_name_from_node(self, ts_node: Node, source_bytes: bytes) -> str | None:
        """Try to extract a name from a tree-sitter node."""
        # For function_definition and class_definition, get the name child
        name_node = ts_node.child_by_field_name("name")
        if name_node is not None:
            return source_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")
        return None

    def _classify_function(
        self,
        def_node: Node,
        name: str,
        source_bytes: bytes,
    ) -> tuple[NodeType, str]:
        """Determine if a function_definition is a METHOD or FUNCTION.

        Walk the tree-sitter parent chain. If any ancestor is a class_definition,
        this is a METHOD and we build a qualified full_name.

        Returns:
            Tuple of (NodeType, full_name).
        """
        parent = def_node.parent
        while parent is not None:
            if parent.type == "class_definition":
                # Extract the class name
                class_name_node = parent.child_by_field_name("name")
                if class_name_node is not None:
                    class_name = source_bytes[class_name_node.start_byte : class_name_node.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    return NodeType.METHOD, f"{class_name}.{name}"
                return NodeType.METHOD, name
            parent = parent.parent

        return NodeType.FUNCTION, name
