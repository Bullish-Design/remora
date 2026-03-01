import hashlib
import re
from pathlib import Path

try:
    from tree_sitter import Language, Parser
    from tree_sitter_python import language as py_language

    TREESITTER_AVAILABLE = True
except ImportError:
    TREESITTER_AVAILABLE = False

from .models import ASTAgentNode, generate_id


class ASTWatcher:
    def __init__(self):
        if TREESITTER_AVAILABLE:
            self.parser = Parser(Language(py_language()))
        else:
            self.parser = None

    def parse_and_inject_ids(self, uri: str, text: str, old_nodes: list[dict] = None) -> list[ASTAgentNode]:
        if not TREESITTER_AVAILABLE:
            return self._parse_fallback(uri, text, old_nodes)

        self.parser.parse(bytes(text, "utf8"))
        tree = self.parser.parse(bytes(text, "utf8"))

        nodes = []
        old_by_key = {(n["name"], n["node_type"]): n for n in (old_nodes or [])}

        self._find_definitions(tree.root_node, text, uri, nodes, old_by_key)

        return nodes

    def _find_definitions(self, node, text: str, uri: str, nodes: list[ASTAgentNode], old_by_key: dict):
        if node.type in ("function_definition", "class_definition"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = text[name_node.start_byte : name_node.end_byte]
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                source = text[node.start_byte : node.end_byte]
                source_hash = hashlib.md5(source.encode()).hexdigest()

                node_type = "function" if node.type == "function_definition" else "class"
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

        elif node.type == "method_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = text[name_node.start_byte : name_node.end_byte]
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                source = text[node.start_byte : node.end_byte]
                source_hash = hashlib.md5(source.encode()).hexdigest()

                key = (name, "method")

                if key in old_by_key:
                    remora_id = old_by_key[key]["id"]
                    del old_by_key[key]
                else:
                    remora_id = generate_id()

                nodes.append(
                    ASTAgentNode(
                        remora_id=remora_id,
                        node_type="method",
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

    def _parse_fallback(self, uri: str, text: str, old_nodes: list[dict] = None) -> list[ASTAgentNode]:
        nodes = []
        old_by_key = {(n["name"], n["node_type"]): n for n in (old_nodes or [])}

        for match in re.finditer(r"^(def|class)\s+(\w+)", text, re.MULTILINE):
            line_num = text[: match.start()].count("\n") + 1
            node_type = "function" if match.group(1) == "def" else "class"
            name = match.group(2)

            key = (name, node_type)
            if key in old_by_key:
                remora_id = old_by_key[key]["id"]
                del old_by_key[key]
            else:
                remora_id = generate_id()

            lines = text.split("\n")
            start_line = line_num
            end_line = line_num
            for i in range(line_num - 1, len(lines)):
                if lines[i].strip() and not lines[i].startswith(" ") and not lines[i].startswith("\t"):
                    if i > line_num - 1:
                        end_line = i
                        break
            else:
                end_line = len(lines)

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
