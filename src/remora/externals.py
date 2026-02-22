from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from cairn.runtime.external_functions import create_external_functions
from fsdantic import Workspace


def create_remora_externals(
    agent_id: str,
    node_source: str,
    node_metadata: dict[str, Any],
    workspace_path: str | None = None,
    stable_path: str | None = None,
) -> dict[str, Callable]:
    """Create external functions available to Remora's .pym tools.

    Extends Cairn's base externals with Remora-specific functions
    like node context access.

    Args:
        agent_id: Unique agent identifier.
        node_source: Source code of the node being analyzed.
        node_metadata: Metadata dict for the node (name, type, etc).
        workspace_path: Path to the agent's private workspace.
        stable_path: Path to the read-only backing filesystem.

    Returns:
        Dictionary of functions to inject into the Grail script.
    """
    agent_fs = Workspace(Path(workspace_path)) if workspace_path else None
    stable_fs = Workspace(Path(stable_path)) if stable_path else None

    base_externals = create_external_functions(agent_id, agent_fs, stable_fs)

    async def get_node_source() -> str:
        """Return the source code of the current node being analyzed."""
        return node_source

    async def get_node_metadata() -> dict[str, str]:
        """Return metadata about the current node."""
        return node_metadata

    async def run_json_command(cmd: str, args: list[str]) -> dict[str, Any] | list[Any]:
        """Run a command and parse its stdout as JSON."""
        import json
        run_command = base_externals.get("run_command")
        if not run_command:
            return {"error": "run_command not found in base_externals"}
        
        result = await run_command(cmd=cmd, args=args)
        stdout = str(result.get("stdout", ""))
        stderr = str(result.get("stderr", ""))
        exit_code = int(result.get("exit_code", 0) or 0)
        
        try:
            if not stdout.strip():
                return []
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {
                "error": "Failed to parse JSON", 
                "stdout": stdout, 
                "stderr": stderr,
                "exit_code": exit_code
            }

    # Remora-specific overrides or additions
    base_externals["get_node_source"] = get_node_source
    base_externals["get_node_metadata"] = get_node_metadata
    base_externals["run_json_command"] = run_json_command

    return base_externals


def create_resume_tool_schema() -> dict[str, Any]:
    """OpenAI-format tool schema for the built-in ``resume_tool``.

    This tool is injected into the model's tool list when snapshots are
    enabled, allowing the LLM to resume a previously suspended ``.pym``
    script execution.
    """
    return {
        "type": "function",
        "function": {
            "name": "resume_tool",
            "description": (
                "Resume a previously suspended tool execution. "
                "Use this when a tool call returns a 'suspended' status "
                "with a snapshot_id. Pass the snapshot_id and optionally "
                "provide additional_context as the return value for the "
                "external function that caused the suspension."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "snapshot_id": {
                        "type": "string",
                        "description": "The snapshot_id returned by the suspended tool.",
                    },
                    "additional_context": {
                        "type": "string",
                        "description": (
                            "Optional return value to pass to the suspended "
                            "external function. If omitted, None is used."
                        ),
                    },
                },
                "required": ["snapshot_id"],
            },
        },
    }
