"""Tool implementations for NodeAgent."""
from __future__ import annotations

import inspect
import json
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from structured_agents import Tool
from structured_agents.types import ToolCall, ToolResult, ToolSchema

if TYPE_CHECKING:
    from remora.companion.node_agent import NodeAgent

_PY_TYPE_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _params_schema(func: Callable[..., Any]) -> dict[str, Any]:
    from typing import get_type_hints

    sig = inspect.signature(func)
    hints = get_type_hints(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        json_type = _PY_TYPE_TO_JSON.get(hints.get(name, str), "string")
        properties[name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


class FunctionTool:
    def __init__(self, func: Callable[..., Awaitable[Any]]) -> None:
        self._func = func
        self._schema = ToolSchema(
            name=func.__name__,
            description=func.__doc__ or func.__name__,
            parameters=_params_schema(func),
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None = None) -> ToolResult:
        call_id = context.id if context else "unknown"
        try:
            result = await self._func(**arguments)
            output = json.dumps(result) if not isinstance(result, str) else result
            return ToolResult(call_id=call_id, name=self._schema.name, output=output, is_error=False)
        except Exception as exc:
            return ToolResult(call_id=call_id, name=self._schema.name, output=str(exc), is_error=True)


def build_node_agent_tools(agent: "NodeAgent") -> list[Tool]:
    """Build the standard tool set for a NodeAgent."""
    workspace = agent.workspace

    async def read_workspace_file(path: str) -> str:
        """Read a file from this node's workspace."""
        return await workspace.read(path)

    async def write_workspace_file(path: str, content: str) -> str:
        """Write a file to this node's workspace (notes, guides, scripts)."""
        await workspace.write(path, content)
        return f"Written: {path}"

    async def list_workspace(path: str = ".") -> list:
        """List files in this node's workspace directory."""
        return await workspace.list_dir(path)

    async def append_to_user_notes(note: str) -> str:
        """Append a note to notes/user_notes.md in this node's workspace."""
        import time

        from remora.companion.node_workspace import USER_NOTES, append_text

        await append_text(workspace, USER_NOTES, f"\n- *{time.strftime('%Y-%m-%d')}*: {note}\n")
        return "Note saved."

    async def get_node_info(node_id: str) -> str:
        """Get basic info about another node in the codebase graph."""
        return json.dumps(
            {
                "note": "Node lookup requires event store integration - not yet implemented.",
                "node_id": node_id,
            }
        )

    async def create_guide(name: str, content: str) -> str:
        """Create or update a guide file in guides/{name}.md in this node's workspace."""
        await workspace.write(f"guides/{name}.md", content)
        return f"Guide saved: guides/{name}.md"

    async def create_script(name: str, content: str) -> str:
        """Create or update a script in scripts/{name}.py in this node's workspace."""
        await workspace.write(f"scripts/{name}.py", content)
        return f"Script saved: scripts/{name}.py"

    return [
        FunctionTool(read_workspace_file),
        FunctionTool(write_workspace_file),
        FunctionTool(list_workspace),
        FunctionTool(append_to_user_notes),
        FunctionTool(get_node_info),
        FunctionTool(create_guide),
        FunctionTool(create_script),
    ]


__all__ = ["build_node_agent_tools"]
