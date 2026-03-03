# src/remora/lsp/watcher.py
"""AST watcher — delegates to core.discovery.parse_content() for tree-sitter parsing.

Converts CSTNode objects from the core discovery pipeline into the dict format
expected by the LSP path (EventStore / NodeDiscoveredEvent / NodeRemovedEvent).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import logging

from remora.core.discovery import parse_content, CSTNode
from remora.lsp.models import generate_id

logger = logging.getLogger("remora.lsp.watcher")


class ASTWatcher:
    def __init__(self):
        pass

    def parse_and_inject_ids(self, uri: str, text: str, old_nodes: list[dict] | None = None) -> list[dict]:
        """Parse text and return list of node dicts for the LSP path.

        Delegates to ``core.discovery.parse_content()`` for tree-sitter parsing,
        then converts CSTNode objects to dicts and assigns stable IDs.
        """
        cst_nodes = parse_content(uri, text)
        return self._convert_nodes(uri, text, cst_nodes, old_nodes)

    def _convert_nodes(
        self,
        uri: str,
        text: str,
        cst_nodes: list[CSTNode],
        old_nodes: list[dict] | None = None,
    ) -> list[dict]:
        """Convert CSTNode list to LSP-path dicts with parent_id and stable IDs."""
        old_by_key = {(n["name"], n["node_type"]): n for n in (old_nodes or [])}
        stem = Path(uri).stem

        # Deduplicate: when both "function" and "method" exist for the same
        # (name, start_line, end_line), keep only "method".
        method_keys = {(c.name, c.start_line, c.end_line) for c in cst_nodes if c.node_type == "method"}
        filtered = [
            c
            for c in cst_nodes
            if not (c.node_type == "function" and (c.name, c.start_line, c.end_line) in method_keys)
        ]

        # First pass: convert to dicts with deterministic IDs
        dicts: list[dict] = []
        for cst in filtered:
            node_type = cst.node_type
            name = cst.name

            # For file nodes, use stem as name (LSP convention)
            if node_type == "file":
                name = stem
                source_code = text[:200]
            else:
                source_code = cst.text

            source_hash = hashlib.md5(cst.text.encode("utf-8")).hexdigest()

            # Stable IDs: reuse old node ID if the (name, type) key matches
            key = (name, node_type)
            if key in old_by_key:
                node_id = old_by_key[key]["node_id"]
                del old_by_key[key]
            else:
                node_id = generate_id()

            dicts.append(
                {
                    "node_id": node_id,
                    "node_type": node_type,
                    "name": name,
                    "full_name": "",  # computed in second pass
                    "file_path": uri,
                    "start_line": cst.start_line,
                    "end_line": cst.end_line,
                    "start_byte": cst.start_byte,
                    "end_byte": cst.end_byte,
                    "source_code": source_code,
                    "source_hash": source_hash,
                    "parent_id": None,
                }
            )

        # Second pass: assign parent_id and full_name by containment
        self._assign_parents(dicts, stem)

        return dicts

    @staticmethod
    def _assign_parents(dicts: list[dict], stem: str) -> None:
        """Assign parent_id and full_name by line-range containment.

        Rules:
        - file node: parent_id = None, full_name = stem
        - class/function/section/table/etc: parent = innermost enclosing node
        - method: parent = enclosing class
        """
        for node in dicts:
            if node["node_type"] == "file":
                node["full_name"] = stem
                node["parent_id"] = None
                continue

            # Find the innermost *strictly* enclosing node.
            # "Strictly enclosing" means the candidate's span is strictly
            # larger than this node's span (not the exact same range).
            node_span = node["end_line"] - node["start_line"]
            best_parent = None
            best_span = float("inf")
            for candidate in dicts:
                if candidate is node:
                    continue
                cand_span = candidate["end_line"] - candidate["start_line"]
                # candidate must fully contain node AND be strictly larger
                if (
                    candidate["start_line"] <= node["start_line"]
                    and candidate["end_line"] >= node["end_line"]
                    and cand_span > node_span
                ):
                    if cand_span < best_span:
                        best_span = cand_span
                        best_parent = candidate

            if best_parent is not None:
                node["parent_id"] = best_parent["node_id"]
                node["full_name"] = f"{best_parent['full_name']}.{node['name']}"
            else:
                node["parent_id"] = None
                node["full_name"] = f"{stem}.{node['name']}"


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
