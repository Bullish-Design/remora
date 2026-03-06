# src/remora/lsp/watcher.py
"""AST watcher — delegates to core.discovery.parse_content() for tree-sitter parsing.

Converts CSTNode objects from the core discovery pipeline into the dict format
expected by the LSP path (EventStore / NodeDiscoveredEvent / NodeRemovedEvent).
"""

from __future__ import annotations

from pathlib import Path

import logging

from remora.core.discovery import CSTNode, compute_source_hash, parse_content

logger = logging.getLogger("remora.lsp.watcher")


class ASTWatcher:
    def __init__(self):
        pass

    def parse(self, uri: str, text: str) -> list[dict]:
        """Parse text and return list of node dicts for the LSP path.

        Delegates to ``core.discovery.parse_content()`` for tree-sitter parsing,
        then converts CSTNode objects to dicts. Node IDs are deterministic
        from parse output — no state or prior nodes needed.
        """
        cst_nodes = parse_content(uri, text)
        return self._convert_nodes(uri, text, cst_nodes)

    def _convert_nodes(
        self,
        uri: str,
        text: str,
        cst_nodes: list[CSTNode],
    ) -> list[dict]:
        """Convert CSTNode list to LSP-path dicts with parent_id and stable IDs."""
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

            source_hash = compute_source_hash(cst.text)
            node_id = cst.node_id

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
