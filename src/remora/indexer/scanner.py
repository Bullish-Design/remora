"""File scanner using tree-sitter discovery."""

from __future__ import annotations

import ast
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.indexer.store import NodeStateStore

logger = logging.getLogger(__name__)


class Scanner:
    """Scans source files and extracts node information.

    Uses tree-sitter for robust parsing and AST extraction.
    Falls back to stdlib ast for simple cases.
    """

    def __init__(self) -> None:
        self._use_tree_sitter = True

    async def scan_file(self, path: Path) -> list[dict[str, Any]]:
        """Scan a single file and return node data.

        Args:
            path: Path to Python file

        Returns:
            List of node data dicts with extracted metadata
        """
        if not path.exists():
            logger.warning("File does not exist: %s", path)
            return []

        content = path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(content.encode()).hexdigest()

        if self._use_tree_sitter:
            return await self._scan_with_tree_sitter(path, content, file_hash)
        else:
            return self._scan_with_ast(path, content, file_hash)

    async def _scan_with_tree_sitter(
        self,
        path: Path,
        content: str,
        file_hash: str,
    ) -> list[dict[str, Any]]:
        """Scan using tree-sitter (the robust way)."""
        try:
            from remora.discovery import discover

            nodes = discover([path])
        except Exception as e:
            logger.warning("Tree-sitter failed for %s, falling back to ast: %s", path, e)
            return self._scan_with_ast(path, content, file_hash)

        result = []
        lines = content.splitlines()

        for node in nodes:
            normalized_type = _normalize_node_type(node.node_type)
            if normalized_type is None:
                continue
            node_data = {
                "name": node.name,
                "type": normalized_type,
                "file_path": str(path),
                "file_hash": file_hash,
                "source_hash": hashlib.sha256(node.text.encode()).hexdigest(),
                "start_line": node.start_line,
                "end_line": node.end_line,
                "line_count": node.end_line - node.start_line + 1,
            }

            if normalized_type == "function":
                node_data.update(self._extract_function_details(node, lines))
            elif normalized_type == "class":
                node_data.update(self._extract_class_details(node, lines))

            result.append(node_data)

        return result

    def _scan_with_ast(
        self,
        path: Path,
        content: str,
        file_hash: str,
    ) -> list[dict[str, Any]]:
        """Scan using stdlib ast (fallback)."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        lines = content.splitlines()
        result = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result.append(self._extract_function_ast(node, path, file_hash, lines))
            elif isinstance(node, ast.ClassDef):
                result.append(self._extract_class_ast(node, path, file_hash, lines))

        return result

    def _extract_function_details(
        self,
        node: Any,
        lines: list[str],
    ) -> dict[str, Any]:
        """Extract function details from node."""
        start = node.start_line - 1
        end = node.end_line
        source = "\n".join(lines[start:end])

        return {
            "source": source,
            "signature": f"def {node.name}(...)",
            "docstring": None,
            "decorators": [],
            "has_type_hints": True,
        }

    def _extract_class_details(
        self,
        node: Any,
        lines: list[str],
    ) -> dict[str, Any]:
        """Extract class details from node."""
        start = node.start_line - 1
        end = node.end_line
        source = "\n".join(lines[start:end])

        return {
            "source": source,
            "signature": f"class {node.name}",
            "docstring": None,
            "decorators": [],
        }

    def _extract_function_ast(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        path: Path,
        file_hash: str,
        lines: list[str],
    ) -> dict[str, Any]:
        """Extract function details from AST node."""
        start = node.lineno - 1
        end = node.end_lineno or start + 1
        func_source = "\n".join(lines[start:end])
        source_hash = hashlib.sha256(func_source.encode()).hexdigest()

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

        docstring = ast.get_docstring(node)
        if docstring:
            docstring = docstring.split("\n")[0][:100]

        decorators = [ast.unparse(d) for d in node.decorator_list]

        has_type_hints = node.returns is not None or any(a.annotation for a in node.args.args)

        return {
            "name": node.name,
            "type": "function",
            "file_path": str(path),
            "file_hash": file_hash,
            "source_hash": source_hash,
            "start_line": node.lineno,
            "end_line": node.end_lineno or node.lineno,
            "line_count": end - start,
            "source": func_source,
            "signature": signature,
            "docstring": docstring,
            "decorators": decorators,
            "has_type_hints": has_type_hints,
        }

    def _extract_class_ast(
        self,
        node: ast.ClassDef,
        path: Path,
        file_hash: str,
        lines: list[str],
    ) -> dict[str, Any]:
        """Extract class details from AST node."""
        start = node.lineno - 1
        end = node.end_lineno or start + 1
        class_source = "\n".join(lines[start:end])
        source_hash = hashlib.sha256(class_source.encode()).hexdigest()

        bases = [ast.unparse(b) for b in node.bases]
        signature = f"class {node.name}"
        if bases:
            signature += f"({', '.join(bases)})"

        docstring = ast.get_docstring(node)
        if docstring:
            docstring = docstring.split("\n")[0][:100]

        decorators = [ast.unparse(d) for d in node.decorator_list]

        return {
            "name": node.name,
            "type": "class",
            "file_path": str(path),
            "file_hash": file_hash,
            "source_hash": source_hash,
            "start_line": node.lineno,
            "end_line": node.end_lineno or node.lineno,
            "line_count": end - start,
            "source": class_source,
            "signature": signature,
            "docstring": docstring,
            "decorators": decorators,
            "has_type_hints": True,
        }


async def scan_file_simple(
    file_path: Path,
    store: "NodeStateStore",
) -> int:
    """Simple file scanning for ad-hoc indexing.

    Args:
        file_path: Path to Python file
        store: NodeStateStore to save results

    Returns:
        Number of nodes indexed
    """
    from remora.indexer.models import FileIndex, NodeState

    content = file_path.read_text(encoding="utf-8")
    file_hash = hashlib.sha256(content.encode()).hexdigest()

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return 0

    lines = content.splitlines()
    nodes: list[NodeState] = []
    now = datetime.now(timezone.utc)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            state = _extract_function_ast(node, file_path, file_hash, lines)
            nodes.append(state)
        elif isinstance(node, ast.ClassDef):
            state = _extract_class_ast(node, file_path, file_hash, lines)
            nodes.append(state)

    await store.invalidate_file(str(file_path))

    if nodes:
        await store.set_many(nodes)

    await store.set_file_index(
        FileIndex(
            file_path=str(file_path),
            file_hash=file_hash,
            node_count=len(nodes),
            last_scanned=now,
        )
    )

    logger.debug("Indexed %s: %d nodes", file_path, len(nodes))

    return len(nodes)


def _normalize_node_type(node_type: str) -> str | None:
    if node_type in {"function", "method"}:
        return "function"
    if node_type == "class":
        return "class"
    if node_type == "file":
        return "module"
    return None


def _extract_function_ast(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: Path,
    file_hash: str,
    lines: list[str],
) -> NodeState:
    """Extract function metadata from AST."""
    from remora.indexer.models import NodeState

    start = node.lineno - 1
    end = node.end_lineno or start + 1
    func_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(func_source.encode()).hexdigest()

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

    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    decorators = [ast.unparse(d) for d in node.decorator_list]

    has_type_hints = node.returns is not None or any(a.annotation for a in node.args.args)

    return NodeState(
        key=f"node:{file_path}:{node.name}",
        file_path=str(file_path),
        node_name=node.name,
        node_type="function",
        source_hash=source_hash,
        file_hash=file_hash,
        signature=signature,
        docstring=docstring,
        imports=[],
        decorators=decorators,
        line_count=end - start,
        has_type_hints=has_type_hints,
        update_source="adhoc",
    )


def _extract_class_ast(
    node: ast.ClassDef,
    file_path: Path,
    file_hash: str,
    lines: list[str],
) -> NodeState:
    """Extract class metadata from AST."""
    from remora.indexer.models import NodeState

    start = node.lineno - 1
    end = node.end_lineno or start + 1
    class_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(class_source.encode()).hexdigest()

    bases = [ast.unparse(b) for b in node.bases]
    signature = f"class {node.name}"
    if bases:
        signature += f"({', '.join(bases)})"

    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    decorators = [ast.unparse(d) for d in node.decorator_list]

    return NodeState(
        key=f"node:{file_path}:{node.name}",
        file_path=str(file_path),
        node_name=node.name,
        node_type="class",
        source_hash=source_hash,
        file_hash=file_hash,
        signature=signature,
        docstring=docstring,
        imports=[],
        decorators=decorators,
        line_count=end - start,
        has_type_hints=True,
        update_source="adhoc",
    )
