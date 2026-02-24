"""Interactive external functions using Workspace KV for IPC.

This module provides ask_user using Cairn's KV store as the communication
mechanism between Grail subprocesses and the coordinator.
"""

import time
import uuid
from datetime import datetime
from typing import Any


def ask_user(
    question: str,
    options: list[str] | None = None,
    timeout: float = 300.0,
    poll_interval: float = 0.5,
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
    workspace = _get_current_workspace()

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
            workspace.kv.set(
                outbox_key,
                {
                    **current,
                    "status": "answered",
                },
            )
            return response.get("answer", "")

        time.sleep(poll_interval)

    current = workspace.kv.get(outbox_key) or {}
    workspace.kv.set(
        outbox_key,
        {
            **current,
            "status": "timeout",
        },
    )
    raise TimeoutError(f"User did not respond within {timeout}s")


def _get_current_workspace() -> Any:
    """Get the current workspace from context."""
    import contextvars

    _workspace: contextvars.ContextVar[Any] = contextvars.ContextVar("workspace")
    ws = _workspace.get(None)
    if ws is None:
        raise RuntimeError("ask_user called outside workspace context")
    return ws


def get_user_messages() -> list[str]:
    """Get any async messages the user has sent to this agent.

    Call this at the start of each turn to check for new context from the user.

    Returns:
        List of messages from the user
    """
    workspace = _get_current_workspace()

    messages = []
    prefix = "inbox:user_message:"

    try:
        entries = workspace.kv.list(prefix=prefix)
        for entry in entries:
            key = entry.get("key", "")
            if key.startswith(prefix):
                msg = workspace.kv.get(key)
                if msg:
                    messages.append(msg.get("content", ""))
                workspace.kv.delete(key)
    except Exception:
        pass

    return messages
