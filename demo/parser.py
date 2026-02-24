"""Tree-sitter parsing logic for AST Summary."""

from __future__ import annotations

from pathlib import Path

from tree_sitter import Node, Tree

from demo.models import AstNode
from remora.discovery.source_parser import SourceParser  # type: ignore[import-untyped]

GRAMMAR_MAP = {
    ".py": "tree_sitter_python",
    ".toml": "tree_sitter_toml",
    ".md": "tree_sitter_markdown",
}


def get_grammar_for_file(file_path: Path) -> str:
    """Get the tree-sitter grammar module name for a file."""
    ext = file_path.suffix
    return GRAMMAR_MAP.get(ext, "tree_sitter_python")


def parse_file(file_path: Path) -> tuple[AstNode, Tree]:
    """Parse a source file into an AstNode tree.

    Args:
        file_path: Path to the source file.

    Returns:
        Tuple of (root AstNode, tree-sitter Tree).
    """
    grammar = get_grammar_for_file(file_path)
    parser = SourceParser(grammar)
    tree, source_bytes = parser.parse_file(file_path)

    ext = file_path.suffix
    if ext == ".py":
        root_node = _build_python_tree(tree.root_node, source_bytes)
    elif ext == ".toml":
        root_node = _build_toml_tree(tree.root_node, source_bytes)
    elif ext == ".md":
        root_node = _build_markdown_tree(tree.root_node, source_bytes)
    else:
        root_node = _build_python_tree(tree.root_node, source_bytes)

    if root_node is None:
        raise ValueError(f"Failed to parse {file_path}")

    return root_node, tree


def _build_python_tree(node: Node, source_bytes: bytes, parent: AstNode | None = None) -> AstNode | None:
    """Recursively build AstNode tree for Python."""
    if node.type == "module":
        ast_node = AstNode(
            node_type="Module",
            name="File Root",
            source_text=source_bytes[node.start_byte : node.end_byte].decode("utf-8"),
        )
        for child in node.children:
            _build_python_tree(child, source_bytes, ast_node)
        return ast_node

    if node.type in ("class_definition", "function_definition"):
        name_node = None
        for child in node.children:
            if child.type == "identifier":
                name_node = child
                break

        name = source_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8") if name_node else "anonymous"
        node_type_str = "ClassDef" if node.type == "class_definition" else "FunctionDef"
        ast_node = AstNode(
            node_type=node_type_str,
            name=name,
            source_text=source_bytes[node.start_byte : node.end_byte].decode("utf-8"),
        )

        if parent is not None:
            parent.children.append(ast_node)

        for child in node.children:
            if child.type == "block":
                for subchild in child.children:
                    _build_python_tree(subchild, source_bytes, ast_node)
        return ast_node

    return None


def _build_toml_tree(node: Node, source_bytes: bytes, parent: AstNode | None = None) -> AstNode | None:
    """Recursively build AstNode tree for TOML."""
    if node.type == "document":
        ast_node = AstNode(
            node_type="Document",
            name="File Root",
            source_text=source_bytes[node.start_byte : node.end_byte].decode("utf-8"),
        )
        for child in node.children:
            _build_toml_tree(child, source_bytes, ast_node)
        return ast_node

    if node.type in ("table", "table_array_element"):
        header = None
        for child in node.children:
            if child.type in ("table_header", "table_array_header"):
                header = child
                break

        name = source_bytes[header.start_byte : header.end_byte].decode("utf-8") if header else "table"
        ast_node = AstNode(
            node_type="Table",
            name=name,
            source_text=source_bytes[node.start_byte : node.end_byte].decode("utf-8"),
        )

        if parent is not None:
            parent.children.append(ast_node)
        return ast_node

    return None


def _build_markdown_tree(node: Node, source_bytes: bytes, parent: AstNode | None = None) -> AstNode | None:
    """Recursively build AstNode tree for Markdown."""
    if node.type == "document":
        ast_node = AstNode(
            node_type="Document",
            name="File Root",
            source_text=source_bytes[node.start_byte : node.end_byte].decode("utf-8"),
        )
        for child in node.children:
            _build_markdown_tree(child, source_bytes, ast_node)
        return ast_node

    if node.type == "section":
        heading_node: AstNode | None = None
        section_parent = parent

        for child in node.children:
            if child.type in ("atx_heading", "setext_heading"):
                heading_node = _build_markdown_tree(child, source_bytes, section_parent)
            elif child.type == "section":
                _build_markdown_tree(child, source_bytes, section_parent)
            elif child.type in ("paragraph", "list", "block_quote", "code_fence") and heading_node is not None:
                content = source_bytes[child.start_byte : child.end_byte].decode("utf-8").strip()
                if content:
                    content_node = AstNode(
                        node_type=child.type.replace("_", " ").title().replace(" ", ""),
                        name=child.type,
                        source_text=content,
                    )
                    heading_node.children.append(content_node)

        if heading_node is not None and heading_node.children:
            heading_node.source_text = "\n\n".join(c.source_text for c in heading_node.children)

        return None

    if node.type in ("atx_heading", "setext_heading"):
        heading_text = None
        for child in node.children:
            if child.type == "heading_text":
                heading_text = child
                break
            if child.type == "inline" and heading_text is None:
                heading_text = child

        name = (
            source_bytes[heading_text.start_byte : heading_text.end_byte].decode("utf-8").strip()
            if heading_text
            else "heading"
        )
        level = 1
        if node.type == "atx_heading":
            for child in node.children:
                if child.type.startswith("atx_h"):
                    level = int(child.type.split("_")[1][1])
                    break
        elif node.type == "setext_heading":
            for child in node.children:
                if child.type.startswith("setext_h"):
                    level = int(child.type.split("_")[1][1])
                    break

        ast_node = AstNode(
            node_type=f"Heading{level}",
            name=name,
            source_text="",
        )

        if parent is not None:
            parent.children.append(ast_node)
        return ast_node

    if node.type in ("paragraph", "list", "block_quote", "code_fence"):
        content = source_bytes[node.start_byte : node.end_byte].decode("utf-8").strip()
        ast_node = AstNode(
            node_type=node.type.replace("_", " ").title().replace(" ", ""),
            name=node.type,
            source_text=content,
        )
        if parent is not None:
            parent.children.append(ast_node)
        return ast_node

    return None
