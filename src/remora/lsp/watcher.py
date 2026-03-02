# src/remora/lsp/watcher.py
from __future__ import annotations

import hashlib
import re
from pathlib import Path

try:
    from tree_sitter import Language, Parser
    from tree_sitter_python import language as py_language

    TREESITTER_AVAILABLE = True
except ImportError:
    TREESITTER_AVAILABLE = False

import logging

from remora.lsp.models import generate_id

logger = logging.getLogger("remora.lsp.watcher")


class ASTWatcher:
    def __init__(self):
        if TREESITTER_AVAILABLE:
            self.parser = Parser(Language(py_language()))
        else:
            self.parser = None
        self._fallback_warned = False

    # Suffixes that tree-sitter-python can parse into function/class nodes
    _PYTHON_SUFFIXES = frozenset({".py"})
    # All supported suffixes (non-Python get file-level nodes only)
    _SUPPORTED_SUFFIXES = frozenset({".py", ".md", ".toml"})

    def parse_and_inject_ids(self, uri: str, text: str, old_nodes: list[dict] | None = None) -> list[dict]:
        suffix = Path(uri).suffix.lower() if "." in Path(uri).name else ""

        # Non-Python files: create a file-level node only (no AST decomposition)
        if suffix not in self._PYTHON_SUFFIXES:
            return self._parse_file_only(uri, text, old_nodes)

        if not TREESITTER_AVAILABLE:
            return self._parse_fallback(uri, text, old_nodes)

        text_bytes = text.encode("utf-8")
        tree = self.parser.parse(text_bytes)

        nodes: list[dict] = []
        old_by_key = {(n["name"], n["node_type"]): n for n in (old_nodes or [])}
        stem = Path(uri).stem

        file_source = text[:200]
        file_hash = hashlib.md5(text_bytes).hexdigest()

        key = (stem, "file")
        if key in old_by_key:
            file_id = old_by_key[key]["node_id"]
        else:
            file_id = generate_id()

        file_node = {
            "node_id": file_id,
            "node_type": "file",
            "name": stem,
            "full_name": stem,
            "file_path": uri,
            "start_line": 1,
            "end_line": len(text.splitlines()),
            "start_byte": 0,
            "end_byte": len(text_bytes),
            "source_code": file_source,
            "source_hash": file_hash,
            "parent_id": None,
        }
        nodes.append(file_node)

        self._find_definitions(
            tree.root_node, text_bytes, uri, nodes, old_by_key, parent_id=file_id, parent_full_name=stem
        )

        return nodes

    def _find_definitions(
        self,
        node,
        text_bytes: bytes,
        uri: str,
        nodes: list[dict],
        old_by_key: dict,
        parent_id: str | None = None,
        parent_full_name: str = "",
    ) -> None:
        stem = Path(uri).stem

        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = text_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                source = text_bytes[node.start_byte : node.end_byte].decode("utf-8")
                source_hash = hashlib.md5(source.encode("utf-8")).hexdigest()

                is_method = (
                    node.parent
                    and node.parent.type == "block"
                    and node.parent.parent
                    and node.parent.parent.type == "class_definition"
                )
                node_type = "method" if is_method else "function"
                key = (name, node_type)

                if key in old_by_key:
                    node_id = old_by_key[key]["node_id"]
                    del old_by_key[key]
                else:
                    node_id = generate_id()

                full_name = f"{parent_full_name}.{name}"

                nodes.append(
                    {
                        "node_id": node_id,
                        "node_type": node_type,
                        "name": name,
                        "full_name": full_name,
                        "file_path": uri,
                        "start_line": start_line,
                        "end_line": end_line,
                        "start_byte": node.start_byte,
                        "end_byte": node.end_byte,
                        "source_code": source,
                        "source_hash": source_hash,
                        "parent_id": parent_id,
                    }
                )

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = text_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8")
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                source = text_bytes[node.start_byte : node.end_byte].decode("utf-8")
                source_hash = hashlib.md5(source.encode("utf-8")).hexdigest()

                key = (name, "class")

                if key in old_by_key:
                    node_id = old_by_key[key]["node_id"]
                    del old_by_key[key]
                else:
                    node_id = generate_id()

                full_name = f"{parent_full_name}.{name}"

                nodes.append(
                    {
                        "node_id": node_id,
                        "node_type": "class",
                        "name": name,
                        "full_name": full_name,
                        "file_path": uri,
                        "start_line": start_line,
                        "end_line": end_line,
                        "start_byte": node.start_byte,
                        "end_byte": node.end_byte,
                        "source_code": source,
                        "source_hash": source_hash,
                        "parent_id": parent_id,
                    }
                )

                # Methods inside this class get the class as their parent
                for child in node.children:
                    self._find_definitions(
                        child, text_bytes, uri, nodes, old_by_key, parent_id=node_id, parent_full_name=full_name
                    )
                return  # Already recursed into children

        for child in node.children:
            self._find_definitions(
                child, text_bytes, uri, nodes, old_by_key, parent_id=parent_id, parent_full_name=parent_full_name
            )

    def _parse_file_only(self, uri: str, text: str, old_nodes: list[dict] | None = None) -> list[dict]:
        """Create a single file-level agent node for non-Python files (markdown, toml, etc.)."""
        old_by_key = {(n["name"], n["node_type"]): n for n in (old_nodes or [])}
        text_bytes = text.encode("utf-8")
        file_hash = hashlib.md5(text_bytes).hexdigest()
        stem = Path(uri).stem

        key = (stem, "file")
        if key in old_by_key:
            file_id = old_by_key[key]["node_id"]
        else:
            file_id = generate_id()

        return [
            {
                "node_id": file_id,
                "node_type": "file",
                "name": stem,
                "full_name": stem,
                "file_path": uri,
                "start_line": 1,
                "end_line": len(text.splitlines()),
                "start_byte": 0,
                "end_byte": len(text_bytes),
                "source_code": text[:200],
                "source_hash": file_hash,
                "parent_id": None,
            }
        ]

    def _parse_fallback(self, uri: str, text: str, old_nodes: list[dict] | None = None) -> list[dict]:
        if not self._fallback_warned:
            logger.warning("tree-sitter not available; using fallback parser with approximate ranges")
            self._fallback_warned = True

        nodes: list[dict] = []
        old_by_key = {(n["name"], n["node_type"]): n for n in (old_nodes or [])}
        lines = text.split("\n")
        total_lines = len(lines)
        stem = Path(uri).stem

        for match in re.finditer(r"^(\s*)(def|class)\s+(\w+)", text, re.MULTILINE):
            indent = match.group(1)
            keyword = match.group(2)
            name = match.group(3)
            line_num = text[: match.start()].count("\n") + 1

            if keyword == "class":
                node_type = "class"
            elif indent:
                node_type = "method"
            else:
                node_type = "function"

            key = (name, node_type)
            if key in old_by_key:
                node_id = old_by_key[key]["node_id"]
                del old_by_key[key]
            else:
                node_id = generate_id()

            start_line = line_num
            end_line = total_lines
            source = "\n".join(lines[start_line - 1 : end_line])

            # Fallback: approximate full_name (no class context tracking)
            full_name = f"{stem}.{name}"

            nodes.append(
                {
                    "node_id": node_id,
                    "node_type": node_type,
                    "name": name,
                    "full_name": full_name,
                    "file_path": uri,
                    "start_line": start_line,
                    "end_line": end_line,
                    "start_byte": 0,
                    "end_byte": 0,
                    "source_code": source,
                    "source_hash": hashlib.md5(source.encode()).hexdigest(),
                    "parent_id": None,
                }
            )

        return nodes


def inject_ids(file_path: Path, nodes: list[dict]) -> str:
    lines = file_path.read_text().splitlines()

    nodes_sorted = sorted(nodes, key=lambda n: n["start_line"], reverse=True)

    for node in nodes_sorted:
        line_idx = node["start_line"] - 1
        if line_idx >= len(lines):
            continue
        line = lines[line_idx]

        line = re.sub(r"\s*# rm_[a-z0-9]{8}\s*$", "", line)

        lines[line_idx] = f"{line}  # {node['node_id']}"

    new_content = "\n".join(lines) + "\n"
    file_path.write_text(new_content)
    return new_content
