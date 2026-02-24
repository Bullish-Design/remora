from __future__ import annotations

import contextvars
import time
import uuid
from datetime import datetime
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
            return {"error": "Failed to parse JSON", "stdout": stdout, "stderr": stderr, "exit_code": exit_code}

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


_workspace_var: contextvars.ContextVar[Workspace | None] = contextvars.ContextVar("workspace", default=None)


def set_workspace(workspace: Workspace | None) -> None:
    """Set the current workspace for ask_user and get_user_messages."""
    _workspace_var.set(workspace)


def get_workspace() -> Workspace:
    """Get the current workspace or raise RuntimeError."""
    ws = _workspace_var.get()
    if ws is None:
        raise RuntimeError("ask_user called outside workspace context")
    return ws


def ask_user(
    question: str, options: list[str] | None = None, timeout: float = 300.0, poll_interval: float = 0.5
) -> str:
    """Ask the user a question and wait for their response.

    This function writes to the workspace KV store and polls for a response.
    No async needed - just synchronous KV operations that Grail supports.

    Args:
        question: The question to ask the user
        options: Optional constrained choices (makes UI easier)
        timeout: How long to wait for response (default 300s)
        poll_interval: How often to check for response (default 0.5s)

    Returns:
        The user's response string

    Raises:
        TimeoutError: If the user doesn't respond within timeout
    """
    workspace = get_workspace()

    msg_id = uuid.uuid4().hex[:8]
    outbox_key = f"outbox:question:{msg_id}"
    inbox_key = f"inbox:response:{msg_id}"

    workspace.kv.set(
        outbox_key,
        {
            "question": question,
            "options": options,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "timeout": timeout,
        },
    )

    start_time = time.time()
    while time.time() - start_time < timeout:
        response = workspace.kv.get(inbox_key)
        if response is not None:
            current = workspace.kv.get(outbox_key) or {}
            workspace.kv.set(outbox_key, {**current, "status": "answered"})
            return response.get("answer", "")

        time.sleep(poll_interval)

    current = workspace.kv.get(outbox_key) or {}
    workspace.kv.set(outbox_key, {**current, "status": "timeout"})
    raise TimeoutError(f"User did not respond within {timeout}s")


def get_user_messages() -> list[str]:
    """Get any async messages the user has sent to this agent.

    Call this at the start of each turn to check for new context from the user.

    Returns:
        List of messages from the user
    """
    workspace = get_workspace()

    messages = []
    prefix = "inbox:user_message:"

    try:
        entries = workspace.kv.list(prefix=prefix)
        for entry in entries:
            key = entry.get("key", "") if isinstance(entry, dict) else str(entry)
            if key.startswith(prefix):
                msg = workspace.kv.get(key)
                if msg:
                    messages.append(msg.get("content", ""))
                workspace.kv.delete(key)
    except Exception:
        pass

    return messages
