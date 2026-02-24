"""Agent state management using Cairn KV store.

This module provides KV-based state management for agents.
All agent state lives in KV, not Python objects.
This makes snapshots trivial - workspace snapshot = agent snapshot.
"""

import json
import uuid
from datetime import datetime
from typing import Any


class AgentKVStore:
    """Manages agent state in Cairn KV store.

    Key insight: All agent state lives in KV, not Python objects.
    This makes snapshots trivial - workspace snapshot = agent snapshot.
    """

    def __init__(self, workspace: Any, agent_id: str):
        self._ws = workspace
        self._agent_id = agent_id
        self._prefix = f"agent:{agent_id}"

    @property
    def _messages_key(self) -> str:
        return f"{self._prefix}:messages"

    @property
    def _tool_results_key(self) -> str:
        return f"{self._prefix}:tool_results"

    @property
    def _metadata_key(self) -> str:
        return f"{self._prefix}:metadata"

    def get_messages(self) -> list[dict[str, Any]]:
        """Get all messages from KV."""
        data = self._ws.kv.get(self._messages_key)
        return json.loads(data) if data else []

    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message to the conversation history."""
        messages = self.get_messages()
        messages.append(message)
        self._ws.kv.set(self._messages_key, json.dumps(messages))

    def add_message_from_object(self, msg_obj: Any) -> None:
        """Add a Message object (from structured-agents)."""
        tool_calls = []
        if hasattr(msg_obj, "tool_calls") and msg_obj.tool_calls:
            for tc in msg_obj.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id if hasattr(tc, "id") else tc.get("id"),
                        "name": tc.name if hasattr(tc, "name") else tc.get("name"),
                        "arguments": tc.arguments if hasattr(tc, "arguments") else tc.get("arguments"),
                    }
                )

        self.add_message(
            {
                "role": getattr(msg_obj, "role", "unknown"),
                "content": getattr(msg_obj, "content", ""),
                "tool_calls": tool_calls,
                "tool_call_id": getattr(msg_obj, "tool_call_id", None),
                "name": getattr(msg_obj, "name", None),
            }
        )

    def clear_messages(self) -> None:
        """Clear all messages."""
        self._ws.kv.set(self._messages_key, json.dumps([]))

    def get_tool_results(self) -> list[dict[str, Any]]:
        """Get all tool results from KV."""
        data = self._ws.kv.get(self._tool_results_key)
        return json.loads(data) if data else []

    def add_tool_result(self, result: dict[str, Any]) -> None:
        """Add a tool result."""
        results = self.get_tool_results()
        results.append(result)
        self._ws.kv.set(self._tool_results_key, json.dumps(results))

    def add_tool_result_from_object(self, result_obj: Any) -> None:
        """Add a ToolResult object (from structured-agents)."""
        self.add_tool_result(
            {
                "call_id": getattr(result_obj, "call_id", ""),
                "name": getattr(result_obj, "name", ""),
                "output": getattr(result_obj, "output", ""),
                "is_error": getattr(result_obj, "is_error", False),
            }
        )

    def clear_tool_results(self) -> None:
        """Clear all tool results."""
        self._ws.kv.set(self._tool_results_key, json.dumps([]))

    def get_metadata(self) -> dict[str, Any]:
        """Get agent metadata."""
        data = self._ws.kv.get(self._metadata_key)
        return json.loads(data) if data else {}

    def set_metadata(self, metadata: dict[str, Any]) -> None:
        """Set agent metadata."""
        self._ws.kv.set(self._metadata_key, json.dumps(metadata))

    def update_metadata(self, **kwargs: Any) -> None:
        """Update specific metadata fields."""
        current = self.get_metadata()
        current.update(kwargs)
        self.set_metadata(current)

    def create_snapshot(self, name: str) -> str:
        """Create a named snapshot of current state.

        This is now trivial - we just copy current state to a snapshot key.
        The workspace itself can be checkpointed via materialize().
        """
        snapshot_id = uuid.uuid4().hex[:8]
        snapshot_key = f"snapshot:{name}:{snapshot_id}"

        messages = self.get_messages()
        tool_results = self.get_tool_results()
        metadata = self.get_metadata()

        snapshot_data = {
            "messages": messages,
            "tool_results": tool_results,
            "metadata": metadata,
            "created_at": datetime.now().isoformat(),
        }

        self._ws.kv.set(snapshot_key, json.dumps(snapshot_data))
        return snapshot_id

    def restore_snapshot(self, snapshot_key: str) -> None:
        """Restore state from a snapshot."""
        data = self._ws.kv.get(snapshot_key)
        if not data:
            raise ValueError(f"Snapshot not found: {snapshot_key}")

        snapshot = json.loads(data)
        self._ws.kv.set(self._messages_key, json.dumps(snapshot["messages"]))
        self._ws.kv.set(self._tool_results_key, json.dumps(snapshot["tool_results"]))
        self._ws.kv.set(self._metadata_key, json.dumps(snapshot["metadata"]))

    def list_snapshots(self) -> list[dict[str, Any]]:
        """List all available snapshots."""
        entries = self._ws.kv.list(prefix="snapshot:")
        snapshots = []

        for entry in entries:
            key = entry.get("key", "") if isinstance(entry, dict) else str(entry)
            if ":metadata" in key:
                continue

            data = self._ws.kv.get(key)
            if data:
                snapshot = json.loads(data)
                snapshots.append(
                    {
                        "key": key,
                        "created_at": snapshot.get("created_at"),
                        "message_count": len(snapshot.get("messages", [])),
                    }
                )

        return snapshots
