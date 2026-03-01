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

from remora.lsp.models import ASTAgentNode, generate_id

logger = logging.getLogger("remora.lsp.watcher")


class ASTWatcher:
    def __init__(self):
        if TREESITTER_AVAILABLE:
            self.parser = Parser(Language(py_language()))
        else:
            self.parser = None
        self._fallback_warned = False

    def parse_and_inject_ids(self, uri: str, text: str, old_nodes: list[dict] | None = None) -> list[ASTAgentNode]:
        if not TREESITTER_AVAILABLE:
            return self._parse_fallback(uri, text, old_nodes)

        tree = self.parser.parse(bytes(text, "utf8"))

        nodes: list[ASTAgentNode] = []
        old_by_key = {(n["name"], n["node_type"]): n for n in (old_nodes or [])}

        self._find_definitions(tree.root_node, text, uri, nodes, old_by_key)

        file_source = text[:200]
        file_hash = hashlib.md5(text.encode()).hexdigest()

        key = (Path(uri).stem, "file")
        if key in old_by_key:
            file_id = old_by_key[key]["id"]
        else:
            file_id = generate_id()

        nodes.insert(
            0,
            ASTAgentNode(
                remora_id=file_id,
                node_type="file",
                name=Path(uri).stem,
                file_path=uri,
                start_line=1,
                end_line=len(text.splitlines()),
                source_code=file_source,
                source_hash=file_hash,
            ),
        )

        return nodes

    def _find_definitions(self, node, text: str, uri: str, nodes: list[ASTAgentNode], old_by_key: dict) -> None:
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = text[name_node.start_byte : name_node.end_byte]
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                source = text[node.start_byte : node.end_byte]
                source_hash = hashlib.md5(source.encode()).hexdigest()

                is_method = (
                    node.parent
                    and node.parent.type == "block"
                    and node.parent.parent
                    and node.parent.parent.type == "class_definition"
                )
                node_type = "method" if is_method else "function"
                key = (name, node_type)

                if key in old_by_key:
                    remora_id = old_by_key[key]["id"]
                    del old_by_key[key]
                else:
                    remora_id = generate_id()

                nodes.append(
                    ASTAgentNode(
                        remora_id=remora_id,
                        node_type=node_type,
                        name=name,
                        file_path=uri,
                        start_line=start_line,
                        end_line=end_line,
                        source_code=source,
                        source_hash=source_hash,
                    )
                )

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = text[name_node.start_byte : name_node.end_byte]
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                source = text[node.start_byte : node.end_byte]
                source_hash = hashlib.md5(source.encode()).hexdigest()

                key = (name, "class")

                if key in old_by_key:
                    remora_id = old_by_key[key]["id"]
                    del old_by_key[key]
                else:
                    remora_id = generate_id()

                nodes.append(
                    ASTAgentNode(
                        remora_id=remora_id,
                        node_type="class",
                        name=name,
                        file_path=uri,
                        start_line=start_line,
                        end_line=end_line,
                        source_code=source,
                        source_hash=source_hash,
                    )
                )

        for child in node.children:
            self._find_definitions(child, text, uri, nodes, old_by_key)

    def _parse_fallback(self, uri: str, text: str, old_nodes: list[dict] | None = None) -> list[ASTAgentNode]:
        if not self._fallback_warned:
            logger.warning(
                "tree-sitter not available; using fallback parser with approximate ranges"
            )
            self._fallback_warned = True

        nodes: list[ASTAgentNode] = []
        old_by_key = {(n["name"], n["node_type"]): n for n in (old_nodes or [])}
        lines = text.split("\n")
        total_lines = len(lines)

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
                remora_id = old_by_key[key]["id"]
                del old_by_key[key]
            else:
                remora_id = generate_id()

            start_line = line_num
            end_line = total_lines
            source = "\n".join(lines[start_line - 1 : end_line])

            nodes.append(
                ASTAgentNode(
                    remora_id=remora_id,
                    node_type=node_type,
                    name=name,
                    file_path=uri,
                    start_line=start_line,
                    end_line=end_line,
                    source_code=source,
                    source_hash=hashlib.md5(source.encode()).hexdigest(),
                )
            )

        return nodes


def inject_ids(file_path: Path, nodes: list[ASTAgentNode]) -> str:
    lines = file_path.read_text().splitlines()

    nodes_sorted = sorted(nodes, key=lambda n: n.start_line, reverse=True)

    for node in nodes_sorted:
        line_idx = node.start_line - 1
        if line_idx >= len(lines):
            continue
        line = lines[line_idx]

        line = re.sub(r"\s*# rm_[a-z0-9]{8}\s*$", "", line)

        lines[line_idx] = f"{line}  # {node.remora_id}"

    new_content = "\n".join(lines) + "\n"
    file_path.write_text(new_content)
    return new_content
