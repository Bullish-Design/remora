"""Simple file indexer for ad-hoc indexing.

This module provides a lightweight indexing function for the
"Lazy Daemon" pattern - when the Hub daemon isn't running,
the HubClient can perform minimal indexing on critical files.

This is intentionally simpler than the full Grail-based extraction
to minimize latency in the ad-hoc case.
"""

from __future__ import annotations

import ast
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.hub.store import NodeStateStore

logger = logging.getLogger(__name__)


async def index_file_simple(
    file_path: Path,
    store: "NodeStateStore",
) -> int:
    """Perform simple ad-hoc indexing of a Python file.

    This is a lightweight alternative to the full Grail-based
    extraction. It extracts basic metadata without running
    the full script infrastructure.

    Args:
        file_path: Path to Python file to index
        store: NodeStateStore to save results to

    Returns:
        Number of nodes indexed

    Raises:
        FileNotFoundError: If file doesn't exist
        SyntaxError: If file has syntax errors
    """
    from remora.hub.models import NodeState, FileIndex

    # Read and hash file
    content = file_path.read_text(encoding="utf-8")
    file_hash = hashlib.sha256(content.encode()).hexdigest()

    # Parse AST
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return 0
        
    lines = content.splitlines()

    # Extract nodes
    nodes: list[NodeState] = []
    now = datetime.now(timezone.utc)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            state = _extract_function_simple(node, file_path, file_hash, lines, tree)
            nodes.append(state)
        elif isinstance(node, ast.ClassDef):
            state = _extract_class_simple(node, file_path, file_hash, lines, tree)
            nodes.append(state)

    # Invalidate existing nodes for this file
    await store.invalidate_file(str(file_path))

    # Save new nodes
    for state in nodes:
        await store.set(state)

    # Update file index
    await store.set_file_index(FileIndex(
        file_path=str(file_path),
        file_hash=file_hash,
        node_count=len(nodes),
        last_scanned=now,
    ))

    logger.debug(
        f"Ad-hoc indexed {file_path}: {len(nodes)} nodes",
        extra={"file_path": str(file_path), "node_count": len(nodes)}
    )

    return len(nodes)


def _extract_function_simple(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: Path,
    file_hash: str,
    lines: list[str],
    tree: ast.AST,
) -> "NodeState":
    """Extract function metadata (simplified version)."""
    from remora.hub.models import NodeState
    from remora.hub.imports import extract_node_imports

    # Get source
    start = node.lineno - 1
    end = node.end_lineno or start + 1
    func_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(func_source.encode()).hexdigest()

    # Build signature
    args = []
    for arg in node.args.args:
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"
        args.append(arg_str)

    returns = ""
    if node.returns:
        returns = f" -> {ast.unparse(node.returns)}"

    is_async = isinstance(node, ast.AsyncFunctionDef)
    prefix = "async def" if is_async else "def"
    signature = f"{prefix} {node.name}({', '.join(args)}){returns}"

    # Get docstring (first line only)
    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    # Get decorators
    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    # Check type hints
    has_type_hints = (
        node.returns is not None
        or any(a.annotation for a in node.args.args)
    )

    imports = extract_node_imports(file_path, node.name)

    return NodeState(
        key=f"node:{file_path}:{node.name}",
        file_path=str(file_path),
        node_name=node.name,
        node_type="function",
        source_hash=source_hash,
        file_hash=file_hash,
        signature=signature,
        docstring=docstring,
        imports=imports,
        decorators=decorators,
        line_count=end - start,
        has_type_hints=has_type_hints,
        update_source="adhoc",
    )


def _extract_class_simple(
    node: ast.ClassDef,
    file_path: Path,
    file_hash: str,
    lines: list[str],
    tree: ast.AST,
) -> "NodeState":
    """Extract class metadata (simplified version)."""
    from remora.hub.models import NodeState
    from remora.hub.imports import extract_node_imports

    # Get source
    start = node.lineno - 1
    end = node.end_lineno or start + 1
    class_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(class_source.encode()).hexdigest()

    # Build signature
    bases = [ast.unparse(b) for b in node.bases]
    signature = f"class {node.name}"
    if bases:
        signature += f"({', '.join(bases)})"

    # Get docstring
    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    # Get decorators
    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    imports = extract_node_imports(file_path, node.name)

    return NodeState(
        key=f"node:{file_path}:{node.name}",
        file_path=str(file_path),
        node_name=node.name,
        node_type="class",
        source_hash=source_hash,
        file_hash=file_hash,
        signature=signature,
        docstring=docstring,
        imports=imports,
        decorators=decorators,
        line_count=end - start,
        has_type_hints=True,  # Classes don't need return annotations
        update_source="adhoc",
    )
