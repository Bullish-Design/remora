"""
src/remora/hub/call_graph.py

Cross-file call graph analysis for populating callers/callees fields.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.hub.store import NodeStateStore


@dataclass
class CallSite:
    """A single function call site."""
    caller_node_id: str  # node:file:func that makes the call
    callee_name: str     # Name being called (may be unresolved)
    line_number: int
    is_method_call: bool = False


@dataclass
class CallGraphBuilder:
    """Builds a call graph from indexed nodes."""

    store: "NodeStateStore"
    project_root: Path

    # Internal state
    _name_to_node_id: dict[str, list[str]] = field(default_factory=dict)
    _call_sites: list[CallSite] = field(default_factory=list)

    async def build(self) -> dict[str, dict[str, list[str]]]:
        """
        Build the call graph and return updates.

        Returns:
            Dict mapping node_id -> {"callers": [...], "callees": [...]}
        """
        # Step 1: Build name -> node_id index
        await self._build_name_index()

        # Step 2: Extract call sites from all function nodes
        await self._extract_call_sites()

        # Step 3: Resolve and aggregate
        return await self._resolve_graph()

    async def _build_name_index(self) -> None:
        """Build a mapping from function/class names to node IDs."""
        self._name_to_node_id.clear()

        all_nodes = await self.store.list_all_nodes()
        for node_id in all_nodes:
            node = await self.store.get(node_id)
            if node is None:
                continue

            name = node.node_name
            if name not in self._name_to_node_id:
                self._name_to_node_id[name] = []
            self._name_to_node_id[name].append(node_id)

    async def _extract_call_sites(self) -> None:
        """Extract all function calls from each node's source."""
        self._call_sites.clear()

        all_nodes = await self.store.list_all_nodes()
        for node_id in all_nodes:
            node = await self.store.get(node_id)
            if node is None or node.node_type != "function":
                continue

            # Read the source file and extract the node's AST
            file_path = Path(node.file_path)
            if not file_path.exists():
                continue

            try:
                source = file_path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError):
                continue

            # Find the function definition
            for item in ast.walk(tree):
                if isinstance(item, ast.FunctionDef) and item.name == node.node_name:
                    # Extract calls within this function
                    for call_node in ast.walk(item):
                        if isinstance(call_node, ast.Call):
                            call_info = self._extract_call_info(call_node)
                            if call_info:
                                self._call_sites.append(CallSite(
                                    caller_node_id=node_id,
                                    callee_name=call_info[0],
                                    line_number=call_node.lineno,
                                    is_method_call=call_info[1],
                                ))
                    break

    def _extract_call_info(self, call: ast.Call) -> tuple[str, bool] | None:
        """Extract the name being called and whether it's a method call."""
        func = call.func

        if isinstance(func, ast.Name):
            # Direct call: foo()
            return (func.id, False)
        elif isinstance(func, ast.Attribute):
            # Method call: obj.method() - extract just the method name
            return (func.attr, True)

        return None

    async def _resolve_graph(self) -> dict[str, dict[str, list[str]]]:
        """Resolve call sites to actual node IDs."""
        # Initialize result for all nodes
        result: dict[str, dict[str, list[str]]] = {}

        all_nodes = await self.store.list_all_nodes()
        for node_id in all_nodes:
            result[node_id] = {"callers": [], "callees": []}

        # Process call sites
        for site in self._call_sites:
            # Resolve callee name to node IDs
            callee_ids = self._name_to_node_id.get(site.callee_name, [])

            for callee_id in callee_ids:
                # Add caller -> callee relationship
                caller_info = result[site.caller_node_id]
                if callee_id not in caller_info["callees"]:
                    caller_info["callees"].append(callee_id)

                # Add callee <- caller relationship
                callee_info = result[callee_id]
                if site.caller_node_id not in callee_info["callers"]:
                    callee_info["callers"].append(site.caller_node_id)

        return result


async def update_call_graph(store: "NodeStateStore", project_root: Path) -> int:
    """
    Run call graph analysis and update all nodes.

    Returns:
        Number of nodes updated.
    """
    builder = CallGraphBuilder(store=store, project_root=project_root)
    graph = await builder.build()

    updated = 0
    for node_id, relationships in graph.items():
        node = await store.get(node_id)
        if node is None:
            continue

        # Check if update needed
        if node.callers != relationships["callers"] or node.callees != relationships["callees"]:
            node.callers = relationships["callers"] if relationships["callers"] else None
            node.callees = relationships["callees"] if relationships["callees"] else None
            await store.set(node)
            updated += 1

    return updated
