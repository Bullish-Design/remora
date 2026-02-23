#!/usr/bin/env python3
# scripts/ast_summary_demo.py
"""AST Summary MVP: Recursive Documentation & Review demo.

This script parses a file (Python, Markdown, or TOML), builds a hierarchical
AST tree, provisions nested Cairn workspaces, and recursively generates summaries
for each node. It emits progress via JSONL for the dashboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel
from tree_sitter import Node, Tree

from cairn.runtime.workspace_manager import WorkspaceManager
from remora.discovery.source_parser import SourceParser

# Setup basic logging
logging.basicConfig(level=logging.INFO, filename="ast_summary.log")
logger = logging.getLogger(__name__)

EVENT_FILE = Path(".remora_summary_events.jsonl")


class AstNode(BaseModel):
    node_type: str
    name: str
    source_text: str
    children: list['AstNode'] = []
    summary: Optional[str] = None
    status: str = "pending"  # pending, parsing, summarizing, done


def emit_event(event_type: str, node_name: str, node_type: str, message: str = "", extra: dict = None) -> None:
    """Emit an event for the dashboard."""
    if extra is None:
        extra = {}
    payload = {
        "timestamp": time.time(),
        "event": event_type,
        "node": node_name,
        "type": node_type,
        "message": message,
        **extra
    }
    with open(EVENT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def build_python_tree(node: Node, source_bytes: bytes, parent_node: AstNode | None = None) -> AstNode | None:
    """Recursively build AstNode tree for Python."""
    if node.type == "module":
        ast_node = AstNode(node_type="Module", name="File Root", source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8"))
        for child in node.children:
            build_python_tree(child, source_bytes, ast_node)
        return ast_node

    if node.type in ("class_definition", "function_definition"):
        # Find the name node
        name_node = None
        for child in node.children:
            if child.type == "identifier":
                name_node = child
                break
        
        name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8") if name_node else "anonymous"
        node_type_str = "ClassDef" if node.type == "class_definition" else "FunctionDef"
        ast_node = AstNode(node_type=node_type_str, name=name, source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8"))
        
        if parent_node is not None:
            parent_node.children.append(ast_node)

        for child in node.children:
            if child.type == "block":
                for subchild in child.children:
                    build_python_tree(subchild, source_bytes, ast_node)
        return ast_node
    return None

def build_toml_tree(node: Node, source_bytes: bytes, parent_node: AstNode | None = None) -> AstNode | None:
    """Recursively build AstNode tree for TOML."""
    if node.type == "document":
        ast_node = AstNode(node_type="Document", name="File Root", source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8"))
        for child in node.children:
            build_toml_tree(child, source_bytes, ast_node)
        return ast_node

    if node.type in ("table", "table_array_element"):
        header = None
        for child in node.children:
            if child.type in ("table_header", "table_array_header"):
                header = child
                break
        
        name = source_bytes[header.start_byte:header.end_byte].decode("utf-8") if header else "table"
        ast_node = AstNode(node_type="Table", name=name, source_text=source_bytes[node.start_byte:node.end_byte].decode("utf-8"))
        
        if parent_node is not None:
            parent_node.children.append(ast_node)
        return ast_node
    return None


async def simulate_llm_summary(node: AstNode, child_summaries: list[str]) -> str:
    """Mock LLM call that returns a summary."""
    await asyncio.sleep(1.5)  # Simulate API latency
    if not child_summaries:
        return f"This {node.node_type} (`{node.name}`) performs specific local operations and manages its own state."
    
    rollup = " ".join([f"[{i+1}] {s}" for i, s in enumerate(child_summaries)])
    return f"The {node.node_type} (`{node.name}`) serves as a container. It manages: {rollup}"


async def process_node(node: AstNode, workspace_manager: WorkspaceManager, cache_root: Path) -> str:
    """Recursively process a node: spin up workspace, await children, summarize."""
    # 1. Process children concurrently
    child_tasks = []
    for child in node.children:
        child_tasks.append(process_node(child, workspace_manager, cache_root))
    
    child_summaries = await asyncio.gather(*child_tasks)

    # 2. Provision Cairn Workspace for THIS node
    emit_event("workspace_provision", node.name, node.node_type, "Provisioning Cairn workspace")
    workspace_id = f"summary-{id(node)}"
    workspace_db = cache_root / "workspaces" / workspace_id / "workspace.db"
    workspace_db.parent.mkdir(parents=True, exist_ok=True)
    
    emit_event("summarizing", node.name, node.node_type, "Generating LLM summary")
    
    async with workspace_manager.open_workspace(workspace_db) as workspace:
        # Write the source code of just this node
        await workspace.files.write("/node_source.txt", node.source_text)
        
        # 3. Generate Summary
        summary = await simulate_llm_summary(node, child_summaries)
        node.summary = summary
        node.status = "done"
        
        # Write the summary back to the workspace
        await workspace.files.write("/summary.md", summary)
    
    emit_event("done", node.name, node.node_type, "Rollup complete", extra={"summary": summary})
    return summary


def display_tree(node: AstNode, indent: int = 0) -> None:
    """Print the final tree to stdout."""
    prefix = "  " * indent
    print(f"{prefix}- {node.node_type}: {node.name}")
    print(f"{prefix}  Summary: {node.summary}")
    for child in node.children:
        display_tree(child, indent + 1)


async def main() -> None:
    # Clear old events
    if EVENT_FILE.exists():
        EVENT_FILE.unlink()

    # Target
    target_file = Path("src/remora/orchestrator.py")
    if not target_file.exists():
        target_file = Path("pyproject.toml")
    
    emit_event("start", str(target_file), "System", f"Starting AST Parse for {target_file.name}")
    
    # 1. Parse Tree
    ext = target_file.suffix
    grammar_map = {
        ".py": "tree_sitter_python",
        ".toml": "tree_sitter_toml",
        ".md": "tree_sitter_markdown",
    }
    grammar = grammar_map.get(ext, "tree_sitter_python")
    parser = SourceParser(grammar)
    tree, source_bytes = parser.parse_file(target_file)
    
    if ext == ".py":
        root_node = build_python_tree(tree.root_node, source_bytes)
    elif ext == ".toml":
        root_node = build_toml_tree(tree.root_node, source_bytes)
    else:
        # Fallback to python for MVP structure
        root_node = build_python_tree(tree.root_node, source_bytes)

    if not root_node:
        print("Failed to build AstNode tree.")
        return

    # Announce total nodes (flattened)
    def flatten(n):
        res = [n]
        for c in n.children:
            res.extend(flatten(c))
        return res
    
    all_nodes = flatten(root_node)
    emit_event("parsed", "AST", "System", f"Discovered {len(all_nodes)} nodes. Initiating workspaces.")

    # 2. Executive Rollup
    cache_root = Path(".cache/remora")
    cache_root.mkdir(parents=True, exist_ok=True)
    workspace_manager = WorkspaceManager()

    await process_node(root_node, workspace_manager, cache_root)
    
    emit_event("complete", "System", "System", "AST Summary Rollup Complete.")
    
    print("\n--- Final Aggregated Summaries ---")
    display_tree(root_node)

if __name__ == "__main__":
    asyncio.run(main())
