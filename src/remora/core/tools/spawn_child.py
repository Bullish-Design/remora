"""spawn_child tool — create a new scaffold child node.

Allows any agent to spawn a new child node by:
1. Writing a stub to disk (class/function/file)
2. Emitting NodeDiscoveredEvent with the stub content
3. Emitting ScaffoldRequestEvent with the intent
4. Returning the new node_id
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from structured_agents.types import ToolCall, ToolResult, ToolSchema

from remora.core.agents.agent_context import AgentContext
from remora.core.code.discovery import compute_node_id, compute_source_hash
from remora.core.events.code_events import NodeDiscoveredEvent, ScaffoldRequestEvent


_VALID_NODE_TYPES = {"class", "function", "file"}

_STUB_TEMPLATES: dict[str, str] = {
    "class": "class {name}: pass\n",
    "function": "def {name}(): pass\n",
}


class SpawnChildTool:
    """Swarm tool that creates a new scaffold child node."""

    def __init__(self, ctx: AgentContext, *, project_root: Path):
        self._context = ctx
        self._project_root = project_root
        self._schema = ToolSchema(
            name="spawn_child",
            description="Create a new scaffold child node (class, function, or file) that will self-initialize.",
            parameters={
                "type": "object",
                "properties": {
                    "node_type": {
                        "type": "string",
                        "description": "Type of node to create: 'class', 'function', or 'file'",
                        "enum": ["class", "function", "file"],
                    },
                    "name": {
                        "type": "string",
                        "description": "Name for the new node (e.g., 'HttpClient', 'process_data', 'utils.py')",
                    },
                    "intent": {
                        "type": "string",
                        "description": "What the child should do — becomes the scaffold initialization hint",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "File path to create/append the stub in. Required for class/function; for file, this is the new file path.",
                    },
                },
                "required": ["node_type", "name"],
            },
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else "unknown"

        node_type = arguments.get("node_type", "")
        name = arguments.get("name", "")
        intent = arguments.get("intent", "")
        file_path = arguments.get("file_path", "")

        # Validation
        if not node_type:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output="Error: 'node_type' is required.",
                is_error=True,
            )
        if not name:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output="Error: 'name' is required.",
                is_error=True,
            )
        if node_type not in _VALID_NODE_TYPES:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=f"Error: Invalid node_type '{node_type}'. Must be one of: {', '.join(sorted(_VALID_NODE_TYPES))}",
                is_error=True,
            )

        try:
            stub_source, actual_file_path, start_line, end_line = self._write_stub(node_type, name, file_path)

            if node_type == "file":
                full_name = Path(actual_file_path).stem
            else:
                full_name = f"{Path(actual_file_path).stem}.{name}"

            node_id = compute_node_id(actual_file_path, node_type, full_name)
            source_hash = compute_source_hash(stub_source)
            parent_id = self._context.agent_id

            # Emit NodeDiscoveredEvent
            discovered = NodeDiscoveredEvent(
                node_id=node_id,
                node_type=node_type,
                name=name,
                full_name=full_name,
                file_path=actual_file_path,
                start_line=start_line,
                end_line=end_line,
                source_code=stub_source,
                source_hash=source_hash,
                parent_id=parent_id,
            )
            await self._context.emit_event("NodeDiscoveredEvent", discovered)

            # Emit ScaffoldRequestEvent
            scaffold_req = ScaffoldRequestEvent(
                node_id=node_id,
                to_agent=node_id,
                node_type=node_type,
                parent_id=parent_id,
                intent=intent,
            )
            await self._context.emit_event("ScaffoldRequestEvent", scaffold_req)

            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=json.dumps(
                    {
                        "node_id": node_id,
                        "file_path": actual_file_path,
                        "node_type": node_type,
                        "name": name,
                    }
                ),
                is_error=False,
            )

        except Exception as e:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=f"Error: {e}",
                is_error=True,
            )

    def _write_stub(self, node_type: str, name: str, file_path: str) -> tuple[str, str, int, int]:
        """Write stub to disk and return (stub_source, file_path, start_line, end_line)."""
        if node_type == "file":
            # Create an empty file
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text("")
            return "", file_path, 1, 1

        # class or function: append stub to existing file
        template = _STUB_TEMPLATES[node_type]
        stub = template.format(name=name)

        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        if p.exists():
            existing = p.read_text()
        else:
            existing = ""

        # Count existing lines to determine start_line for the new stub
        existing_lines = existing.split("\n") if existing else []
        # If the file doesn't end with a newline, we need to add one
        if existing and not existing.endswith("\n"):
            existing += "\n"

        start_line = len(existing.rstrip("\n").split("\n")) + 1 if existing.strip() else 1
        stub_lines = stub.rstrip("\n").split("\n")
        end_line = start_line + len(stub_lines) - 1

        # Append stub with a blank line separator
        if existing.strip():
            new_content = existing + "\n" + stub
        else:
            new_content = stub

        p.write_text(new_content)

        return stub.rstrip("\n"), file_path, start_line, end_line
