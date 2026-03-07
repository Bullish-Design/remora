"""Consolidated code discovery using tree-sitter.

This module provides the `discover()` function which scans source files
and returns CSTNode objects representing functions, classes, files, etc.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterator

import yaml
import tree_sitter
from tree_sitter import Language, Parser, QueryCursor, Query

from pydantic import BaseModel, ConfigDict

from remora.utils import PathLike, normalize_path
from remora.utils.languages import EXTENSION_TO_LANGUAGE as LANGUAGE_EXTENSIONS

logger = logging.getLogger(__name__)

# ============================================================================
# Data Types
# ============================================================================


class CSTNode(BaseModel):
    """A concrete syntax tree node discovered from source code.

    Immutable data object representing a discovered code element.
    The node_id is deterministic based on file path, type, and semantic name.
    """

    model_config = ConfigDict(frozen=True)

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
    parent_id: str | None = None

    def __hash__(self) -> int:
        """Hash only by node_id — intentional override.

        Pydantic frozen models hash ALL fields by default, but CSTNode
        identity is defined solely by node_id.  Two nodes with the same
        node_id but different text (e.g. after an edit) must hash equally.
        DO NOT REMOVE this override.
        """
        return hash(self.node_id)


def compute_node_id(file_path: str, node_type: str, full_name: str) -> str:
    """Compute deterministic node ID from semantic key.

    Identity is based on (file_path, node_type, full_name) — not position.
    Same inputs always produce the same ID across restarts and line shifts.
    """
    content = f"{file_path}:{node_type}:{full_name}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_source_hash(text: str) -> str:
    """Compute SHA256-based hash of source text."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ============================================================================
# Query Loading (fixes MIN-05: path resolution)
# ============================================================================


def _get_query_dir() -> Path:
    """Get the queries directory using importlib.resources.

    This correctly resolves the path regardless of installation method.
    """
    return Path(importlib.resources.files("remora")) / "ts_queries"  # type: ignore[arg-type]


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

# Captures that are handled by language-specific post-processing, not the generic pipeline.
_POSTPROCESS_CAPTURES = frozenset({"frontmatter.def"})


def _parse_nodes(file_path: str, content: str, language: str) -> list[CSTNode]:
    """Common parsing logic used by both file and content parsing."""
    parser = _get_parser(language)
    if parser is None:
        return [_create_file_node(file_path, content)]

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
    nodes: list[CSTNode] = []
    captures = _collect_captures(query, tree.root_node)

    for node, capture_name in captures:
        if capture_name.endswith(NAME_CAPTURE_SUFFIXES):
            continue  # Skip name-only captures
        if capture_name in _POSTPROCESS_CAPTURES:
            continue  # Handled by language-specific post-processing

        node_type = capture_name.split(".", 1)[0]
        name = _extract_name(node, captures)
        full_name = f"{node_type}:{name}"

        cst_node = CSTNode(
            node_id=compute_node_id(file_path, node_type, full_name),
            node_type=node_type,
            name=name,
            full_name=full_name,
            file_path=file_path,
            text=content[node.start_byte : node.end_byte],
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
        )
        nodes.append(cst_node)

    # Markdown post-processing: create note/todo-note from frontmatter
    if language == "markdown":
        path_obj = Path(file_path)
        nodes = _postprocess_markdown(path_obj, content, captures, nodes)

    # Always include file-level node
    if not any(n.node_type == "file" for n in nodes):
        nodes.insert(0, _create_file_node(file_path, content))

    # Deduplicate: when both "function" and "method" exist for the same
    # (name, start_line, end_line), keep only "method".
    method_keys = {
        (n.name, n.start_line, n.end_line) for n in nodes if n.node_type == "method"
    }
    nodes = [
        n for n in nodes
        if not (n.node_type == "function" and (n.name, n.start_line, n.end_line) in method_keys)
    ]

    return _assign_semantic_identity(file_path, nodes)


def _parse_file(file_path: Path, language: str) -> list[CSTNode]:
    """Parse a single file and extract nodes using tree-sitter queries."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Could not read %s: %s", file_path, e)
        return []

    return _parse_nodes(str(file_path), content, language)


def _postprocess_markdown(
    file_path: Path,
    content: str,
    captures: list[tuple[tree_sitter.Node, str]],
    nodes: list[CSTNode],
) -> list[CSTNode]:
    """Create note/todo-note CSTNode from YAML frontmatter if present."""
    # Find frontmatter capture
    frontmatter_node = None
    for node, capture_name in captures:
        if capture_name == "frontmatter.def":
            frontmatter_node = node
            break

    if frontmatter_node is None:
        return nodes

    # Parse YAML from frontmatter text (strip --- delimiters)
    raw_text = content[frontmatter_node.start_byte : frontmatter_node.end_byte]
    yaml_text = raw_text.strip().removeprefix("---").removesuffix("---").strip()

    metadata: dict = {}
    try:
        parsed = yaml.safe_load(yaml_text)
        if isinstance(parsed, dict):
            metadata = parsed
    except yaml.YAMLError:
        logger.debug("Could not parse frontmatter YAML in %s", file_path)

    # Determine node type: "todo" if type: todo, otherwise "note"
    fm_type = str(metadata.get("type", "note")).lower()
    node_type = "todo" if fm_type == "todo" else "note"

    # Determine name: frontmatter title, fallback to filename
    name = str(metadata.get("title", file_path.name))
    full_name = f"{node_type}:{name}"

    line_count = content.count("\n") + 1 if content else 1
    byte_length = len(content.encode("utf-8")) if content else 0

    note_node = CSTNode(
        node_id=compute_node_id(str(file_path), node_type, full_name),
        node_type=node_type,
        name=name,
        full_name=full_name,
        file_path=str(file_path),
        text=content,
        start_line=1,
        end_line=line_count,
        start_byte=0,
        end_byte=byte_length,
    )
    nodes.insert(0, note_node)

    return nodes


def _collect_captures(query: tree_sitter.Query, root: tree_sitter.Node) -> list[tuple[tree_sitter.Node, str]]:
    """Collect captures with compatibility across tree-sitter versions."""
    try:
        captures = query.captures(root)  # type: ignore[attr-defined]
    except AttributeError:
        cursor = QueryCursor(query)
        captures = cursor.captures(root)

    if isinstance(captures, dict):
        flat: list[tuple[tree_sitter.Node, str]] = []
        for name, nodes in captures.items():
            for node in nodes:
                flat.append((node, name))
        # Dict-branch groups by capture name, not document position.
        # Sort by start position to restore document order.
        flat.sort(key=lambda pair: (pair[0].start_point[0], pair[0].start_point[1]))
        return flat

    return list(captures)


def _is_ancestor(ancestor: tree_sitter.Node, descendant: tree_sitter.Node) -> bool:
    """Check if *ancestor* is an ancestor of *descendant* (walking up parents)."""
    current = descendant.parent
    while current is not None:
        if current.id == ancestor.id:
            return True
        current = current.parent
    return False


def _extract_name(node: tree_sitter.Node, captures: list) -> str:
    """Extract the name for a captured node."""
    # Look for corresponding .name capture — walk ancestors, not just direct parent.
    for n, name in captures:
        if name.endswith(NAME_CAPTURE_SUFFIXES) and _is_ancestor(node, n):
            return n.text.decode() if n.text else "unknown"

    # Try common child names
    for child in node.children:
        if child.type in ("identifier", "name", "function_name"):
            return child.text.decode() if child.text else "unknown"

    return "unknown"


def _create_file_node(file_path: Path | str, content: str | None = None) -> CSTNode:
    """Create a file-level CSTNode from path, optionally with memory content."""
    path_str = str(file_path)
    path_obj = Path(file_path)
    if content is None:
        try:
            content = path_obj.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            content = ""

    line_count = content.count("\n") + 1 if content else 1
    byte_length = len(content.encode("utf-8")) if content else 0
    return CSTNode(
        node_id=compute_node_id(path_str, "file", path_obj.stem),
        node_type="file",
        name=path_obj.name,
        full_name=path_obj.stem,
        file_path=path_str,
        text=content,
        start_line=1,
        end_line=line_count,
        start_byte=0,
        end_byte=byte_length,
    )


def _assign_semantic_identity(file_path: str, nodes: list[CSTNode]) -> list[CSTNode]:
    """Assign semantic full_name, node_id, and parent_id using containment."""
    if not nodes:
        return nodes

    stem = Path(file_path).stem

    # Build work items: mutable dicts with room for full_name and parent index
    work: list[dict[str, int | str | None]] = []
    for node in nodes:
        work.append(
            {
                "node_type": node.node_type,
                "name": node.name,
                "file_path": node.file_path,
                "text": node.text,
                "start_line": node.start_line,
                "end_line": node.end_line,
                "start_byte": node.start_byte,
                "end_byte": node.end_byte,
                "full_name": "",
                "_parent_idx": None,  # track parent index for parent_id
            }
        )

    # First pass: compute full_name and cache parent index
    for i, item in enumerate(work):
        if item["node_type"] == "file":
            item["full_name"] = stem
            continue

        node_start = int(item["start_line"])
        node_end = int(item["end_line"])
        node_span = node_end - node_start
        best_j: int | None = None
        best_span = float("inf")
        for j, candidate in enumerate(work):
            if j == i:
                continue
            cand_start = int(candidate["start_line"])
            cand_end = int(candidate["end_line"])
            cand_span = cand_end - cand_start
            if (
                cand_start <= node_start
                and cand_end >= node_end
                and cand_span > node_span
                and cand_span < best_span
            ):
                best_j = j
                best_span = cand_span

        if best_j is not None:
            item["full_name"] = f"{work[best_j]['full_name']}.{item['name']}"
            item["_parent_idx"] = best_j
        else:
            item["full_name"] = f"{stem}.{item['name']}"

    # Second pass: compute node_ids (needs full_name), then resolve parent_id
    node_ids: list[str] = []
    for item in work:
        node_ids.append(
            compute_node_id(file_path, str(item["node_type"]), str(item["full_name"]))
        )

    resolved: list[CSTNode] = []
    for i, item in enumerate(work):
        parent_idx = item["_parent_idx"]
        parent_id = node_ids[parent_idx] if parent_idx is not None else None

        resolved.append(
            CSTNode(
                node_id=node_ids[i],
                node_type=str(item["node_type"]),
                name=str(item["name"]),
                full_name=str(item["full_name"]),
                file_path=str(item["file_path"]),
                text=str(item["text"]),
                start_line=int(item["start_line"]),
                end_line=int(item["end_line"]),
                start_byte=int(item["start_byte"]),
                end_byte=int(item["end_byte"]),
                parent_id=parent_id,
            )
        )

    return resolved


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
    from file extension. Custom .scm queries are loaded from ts_queries/ dir.

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


def _walk_directory(
    directory: Path,
    *,
    ignore_patterns: set[str] | None = None,
) -> Iterator[Path]:
    """Recursively walk directory, skipping hidden and common ignore patterns."""
    if ignore_patterns is None:
        ignore_patterns = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox"}

    for item in directory.iterdir():
        if item.name.startswith(".") or item.name in ignore_patterns:
            continue
        if item.is_file():
            yield item
        elif item.is_dir():
            yield from _walk_directory(item, ignore_patterns=ignore_patterns)


def parse_file(file_path: PathLike) -> list[CSTNode]:
    """Parse a single file and return discovered CSTNodes."""
    path_obj = normalize_path(file_path)
    if not path_obj.exists() or not path_obj.is_file():
        return []
    language = _detect_language(path_obj)
    if not language:
        return []
    return _parse_file(path_obj, language)


def parse_content(file_path: str, content: str, language: str | None = None) -> list[CSTNode]:
    """Parse text content and return CSTNode list."""
    path_obj = Path(file_path)

    if language is None:
        language = _detect_language(path_obj)

    if language is None:
        return [_create_file_node(file_path, content)]

    return _parse_nodes(file_path, content, language)


def node_to_event(node: CSTNode) -> "NodeDiscoveredEvent":
    """Convert a CSTNode to a NodeDiscoveredEvent.

    This factory lives in discovery (not on the event type) because event
    definitions must not depend on discovery internals.
    """
    from remora.core.events.code_events import NodeDiscoveredEvent

    return NodeDiscoveredEvent(
        node_id=node.node_id,
        node_type=node.node_type,
        name=node.name,
        full_name=node.full_name,
        file_path=node.file_path,
        start_line=node.start_line,
        end_line=node.end_line,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        source_code=node.text,
        source_hash=compute_source_hash(node.text),
        parent_id=node.parent_id,
    )


__all__ = [
    "CSTNode",
    "compute_node_id",
    "compute_source_hash",
    "discover",
    "LANGUAGE_EXTENSIONS",
    "node_to_event",
    "parse_content",
    "parse_file",
]
