"""
src/remora/hub/imports.py

Import extraction for Python files at the AST node level.
"""

from __future__ import annotations

import ast
from pathlib import Path


def extract_imports(file_path: Path) -> list[str]:
    """
    Extract all imports from a Python file.

    Returns:
        List of import strings (e.g., ["os", "pathlib.Path", "typing.TYPE_CHECKING"])
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if module:
                    imports.append(f"{module}.{alias.name}")
                else:
                    imports.append(alias.name)

    return sorted(set(imports))


def extract_node_imports(file_path: Path, node_name: str) -> list[str]:
    """
    Extract imports used by a specific function/class.

    This is more precise: only returns imports that are actually
    referenced within the node's body.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    # First, get all imports in the file
    file_imports = {}  # name -> full import path
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                file_imports[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local_name = alias.asname or alias.name
                if module:
                    file_imports[local_name] = f"{module}.{alias.name}"
                else:
                    file_imports[local_name] = alias.name

    # Find the target node
    target_node = None
    for item in ast.walk(tree):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if item.name == node_name:
                target_node = item
                break

    if target_node is None:
        return []

    # Find all names used in the node
    used_names: set[str] = set()
    for child in ast.walk(target_node):
        if isinstance(child, ast.Name):
            used_names.add(child.id)
        elif isinstance(child, ast.Attribute):
            # Get the root name of attribute chains
            current = child
            while isinstance(current, ast.Attribute):
                current = current.value
            if isinstance(current, ast.Name):
                used_names.add(current.id)

    # Match used names to imports
    node_imports = []
    for name in used_names:
        if name in file_imports:
            node_imports.append(file_imports[name])

    return sorted(set(node_imports))
