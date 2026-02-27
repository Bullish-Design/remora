"""Consolidated code discovery using tree-sitter.

This module provides the `discover()` function which scans source files
and returns CSTNode objects representing functions, classes, files, etc.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator

import tree_sitter
from tree_sitter import Language, Parser, QueryCursor, Query

from remora.utils import PathLike, normalize_path

logger = logging.getLogger(__name__)

# Language extension mapping
LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".md": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rs": "rust",
}


# ============================================================================
# Data Types
# ============================================================================


@dataclass(frozen=True, slots=True)
class CSTNode:
    """A concrete syntax tree node discovered from source code.

    Immutable data object representing a discovered code element.
    The node_id is deterministic based on file path, name, and position.
    """

    node_id: str
    node_type: str  # "function", "class", "file", "section", "table"
    name: str
    full_name: str
    file_path: str
    text: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int

    def __hash__(self) -> int:
        return hash(self.node_id)


def compute_node_id(file_path: str, name: str, start_line: int, end_line: int) -> str:
    """Compute deterministic node ID using SHA256."""
    content = f"{file_path}:{name}:{start_line}:{end_line}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ============================================================================
# Query Loading (fixes MIN-05: path resolution)
# ============================================================================


def _get_query_dir() -> Path:
    """Get the queries directory using importlib.resources.

    This correctly resolves the path regardless of installation method.
    """
    return Path(importlib.resources.files("remora")) / "queries"


def _load_queries(language: str, query_pack: str = "remora_core") -> str | None:
    """Load tree-sitter query from .scm file."""
    query_dir = _get_query_dir()

    # Try language-specific query pack
    query_path = query_dir / language / query_pack
    if not query_path.exists():
        return None

    queries = []
    for scm_file in sorted(query_path.glob("*.scm")):
        queries.append(scm_file.read_text())

    return "\n".join(queries) if queries else None


# ============================================================================
# Parsing
# ============================================================================


def _get_parser(language: str) -> Parser | None:
    """Get a tree-sitter parser for the given language."""
    try:
        # Language libraries are named like tree_sitter_python
        lang_module = __import__(f"tree_sitter_{language}")
        lang = Language(lang_module.language())
        parser = Parser(lang)
        return parser
    except (ImportError, AttributeError) as e:
        logger.debug("Could not load parser for %s: %s", language, e)
        return None


NAME_CAPTURE_SUFFIXES = (".name", ".lang")


def _parse_file(file_path: Path, language: str) -> list[CSTNode]:
    """Parse a single file and extract nodes using tree-sitter queries."""
    parser = _get_parser(language)
    if parser is None:
        # Fall back to file-level node
        return [_create_file_node(file_path)]

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Could not read %s: %s", file_path, e)
        return []

    tree = parser.parse(content.encode())

    # Load and apply queries
    query_text = _load_queries(language)
    if query_text is None:
        return [_create_file_node(file_path, content)]

    try:
        lang_module = __import__(f"tree_sitter_{language}")
        lang = Language(lang_module.language())
        query = Query(lang, query_text)
    except Exception as e:
        logger.warning("Query error for %s: %s", language, e)
        return [_create_file_node(file_path, content)]

    # Extract matches
    nodes = []
    captures = _collect_captures(query, tree.root_node)

    for node, capture_name in captures:
        if capture_name.endswith(NAME_CAPTURE_SUFFIXES):
            continue  # Skip name-only captures

        node_type = capture_name.split(".", 1)[0]
        name = _extract_name(node, captures)

        cst_node = CSTNode(
            node_id=compute_node_id(str(file_path), name, node.start_point[0] + 1, node.end_point[0] + 1),
            node_type=node_type,
            name=name,
            full_name=f"{node_type}:{name}",
            file_path=str(file_path),
            text=content[node.start_byte : node.end_byte],
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
        )
        nodes.append(cst_node)

    # Always include file-level node
    if not any(n.node_type == "file" for n in nodes):
        nodes.insert(0, _create_file_node(file_path, content))

    return nodes


def _collect_captures(query: tree_sitter.Query, root: tree_sitter.Node) -> list[tuple[tree_sitter.Node, str]]:
    """Collect captures with compatibility across tree-sitter versions."""
    try:
        captures = query.captures(root)
    except AttributeError:
        cursor = QueryCursor(query)
        captures = cursor.captures(root)

    if isinstance(captures, dict):
        flat: list[tuple[tree_sitter.Node, str]] = []
        for name, nodes in captures.items():
            for node in nodes:
                flat.append((node, name))
        return flat

    return list(captures)


def _extract_name(node: tree_sitter.Node, captures: list) -> str:
    """Extract the name for a captured node."""
    # Look for corresponding .name capture
    for n, name in captures:
        if name.endswith(NAME_CAPTURE_SUFFIXES) and n.parent == node:
            return n.text.decode() if n.text else "unknown"

    # Try common child names
    for child in node.children:
        if child.type in ("identifier", "name", "function_name"):
            return child.text.decode() if child.text else "unknown"

    return "unknown"


def _create_file_node(file_path: Path, content: str | None = None) -> CSTNode:
    """Create a file-level CSTNode."""
    if content is None:
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            content = ""

    line_count = content.count("\n") + 1 if content else 1

    byte_length = len(content.encode("utf-8")) if content else 0
    return CSTNode(
        node_id=compute_node_id(str(file_path), file_path.name, 1, line_count),
        node_type="file",
        name=file_path.name,
        full_name=file_path.name,
        file_path=str(file_path),
        text=content,
        start_line=1,
        end_line=line_count,
        start_byte=0,
        end_byte=byte_length,
    )


# ============================================================================
# Public API
# ============================================================================


def discover(
    paths: list[PathLike],
    languages: list[str] | None = None,
    node_types: list[str] | None = None,
    max_workers: int = 4,
) -> list[CSTNode]:
    """Scan source paths with tree-sitter and return discovered nodes.

    Uses thread pool for parallel file parsing. Language is auto-detected
    from file extension. Custom .scm queries are loaded from queries/ dir.

    Args:
        paths: Files or directories to scan
        languages: Limit to specific languages (by extension, e.g. "python")
        node_types: Filter to specific node types ("function", "class", etc.)
        max_workers: Thread pool size for parallel parsing

    Returns:
        List of CSTNode objects sorted by file path and line number
    """
    path_list = [normalize_path(p) for p in paths]

    files: list[tuple[Path, str]] = []
    for path in path_list:
        if path.is_file():
            lang = _detect_language(path)
            if lang and (languages is None or lang in languages):
                files.append((path, lang))
        elif path.is_dir():
            for file_path in _walk_directory(path):
                lang = _detect_language(file_path)
                if lang and (languages is None or lang in languages):
                    files.append((file_path, lang))

    all_nodes: list[CSTNode] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_parse_file, file_path, lang) for file_path, lang in files]
        for future in futures:
            try:
                nodes = future.result()
                all_nodes.extend(nodes)
            except Exception as e:
                logger.warning("Parse error: %s", e)

    if node_types:
        all_nodes = [n for n in all_nodes if n.node_type in node_types]

    all_nodes.sort(key=lambda n: (n.file_path, n.start_line))

    return all_nodes


def _detect_language(file_path: Path) -> str | None:
    """Detect language from file extension."""
    return LANGUAGE_EXTENSIONS.get(file_path.suffix.lower())


def _walk_directory(directory: Path) -> Iterator[Path]:
    """Recursively walk directory, skipping hidden and common ignore patterns."""
    ignore_patterns = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox"}

    for item in directory.iterdir():
        if item.name.startswith(".") or item.name in ignore_patterns:
            continue
        if item.is_file():
            yield item
        elif item.is_dir():
            yield from _walk_directory(item)


class NodeType(str, Enum):
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    SECTION = "section"
    TABLE = "table"


class TreeSitterDiscoverer:
    """Compatibility wrapper that exposes the old API."""

    def __init__(
        self,
        root_dirs: list[PathLike],
        language: str | None = None,
        query_pack: str = "remora_core",
        node_types: list[NodeType | str] | None = None,
        max_workers: int = 4,
    ) -> None:
        self._paths = [normalize_path(p) for p in root_dirs]
        self._language = language
        self._query_pack = query_pack
        self._node_types = [nt.value if isinstance(nt, NodeType) else nt for nt in node_types] if node_types else None
        self._max_workers = max_workers

    def discover(self) -> list[CSTNode]:
        languages: list[str] | None = [self._language] if self._language else None
        return discover(
            paths=self._paths,
            languages=languages,
            node_types=self._node_types,
            max_workers=self._max_workers,
        )


__all__ = [
    "CSTNode",
    "compute_node_id",
    "discover",
    "LANGUAGE_EXTENSIONS",
    "NodeType",
    "TreeSitterDiscoverer",
]
