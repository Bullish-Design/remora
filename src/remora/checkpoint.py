"""Cairn-Native Checkpointing.

This module provides checkpointing for graph execution state using Cairn's
native snapshot/restore capabilities. Replaces the old file-backed KV store
approach with Cairn workspace snapshots.

Usage:
    manager = CheckpointManager(Path(".remora/checkpoints"))

    # Save checkpoint
    checkpoint_id = await manager.save(
        graph_id="graph-1",
        executor_state=executor_state,
    )

    # Restore checkpoint
    restored_state = await manager.restore(checkpoint_id)

    # List checkpoints
    checkpoints = await manager.list_checkpoints(graph_id="graph-1")

    # Delete checkpoint
    await manager.delete(checkpoint_id)
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from remora.workspace import CairnWorkspace, restore_workspace, snapshot_workspace

if TYPE_CHECKING:
    from remora.executor import ExecutorState


class JsonStore:
    """Simple JSON file-based store for checkpoint metadata.

    Provides basic key-value storage using JSON files.
    Replaces fsdantic for simplicity.
    """

    def __init__(self, store_path: Path):
        """Initialize the store.

        Args:
            store_path: Directory for JSON files
        """
        self._path = store_path
        self._path.mkdir(parents=True, exist_ok=True)

    async def put(self, key: str, value: dict[str, Any]) -> None:
        """Store a value.

        Args:
            key: The key to store
            value: The value (must be JSON-serializable dict)
        """
        file_path = self._path / f"{key}.json"
        file_path.write_text(json.dumps(value, indent=2))

    async def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a value.

        Args:
            key: The key to retrieve

        Returns:
            The stored dict, or None if not found
        """
        file_path = self._path / f"{key}.json"
        if not file_path.exists():
            return None
        return json.loads(file_path.read_text())

    async def delete(self, key: str) -> None:
        """Delete a value.

        Args:
            key: The key to delete
        """
        file_path = self._path / f"{key}.json"
        if file_path.exists():
            file_path.unlink()

    async def list(self) -> list[dict[str, Any]]:
        """List all stored values.

        Returns:
            List of all stored dicts
        """
        results = []
        for file_path in self._path.glob("*.json"):
            try:
                results.append(json.loads(file_path.read_text()))
            except (json.JSONDecodeError, IOError):
                continue
        return results


def _serialize_result(result: Any) -> dict[str, Any]:
    """Serialize a RunResult to JSON-serializable dict.

    Args:
        result: The RunResult or result dict to serialize

    Returns:
        JSON-serializable dict
    """
    if result is None:
        return {"type": "none"}

    if isinstance(result, dict):
        return {"type": "dict", "data": result}

    if hasattr(result, "model_dump"):
        return {"type": "model_dump", "data": result.model_dump()}

    if hasattr(result, "dict"):
        return {"type": "dict_attr", "data": result.dict()}

    return {"type": "str", "data": str(result)}


def _deserialize_result(data: dict[str, Any]) -> Any:
    """Deserialize a dict back to a RunResult-like object.

    Args:
        data: The serialized dict

    Returns:
        The deserialized result (typically a dict)
    """
    if data is None:
        return None

    result_type = data.get("type", "dict")
    result_data = data.get("data", data)

    if result_type in ("none", None):
        return None

    if result_type in ("dict", "dict_attr"):
        return result_data

    if result_type == "model_dump":
        return result_data

    if result_type == "str":
        return result_data

    return result_data


class CheckpointManager:
    """Save and restore graph execution state via Cairn snapshots.

    This replaces the old CheckpointManager that used file-backed KV stores.
    Now uses Cairn's native snapshot/restore for workspaces.

    Usage:
        manager = CheckpointManager(Path(".remora/checkpoints"))

        # Save
        checkpoint_id = await manager.save(graph_id, executor_state)

        # Restore
        state = await manager.restore(checkpoint_id)
    """

    def __init__(self, store_path: Path):
        """Initialize the CheckpointManager.

        Args:
            store_path: Directory to store checkpoints
        """
        self._store_path = store_path
        self._store: JsonStore | None = None

    async def _get_store(self) -> JsonStore:
        """Lazy initialization of the metadata store.

        Returns:
            The JsonStore instance
        """
        if self._store is None:
            self._store = JsonStore(self._store_path / "_metadata")
        return self._store

    async def save(
        self,
        graph_id: str,
        executor_state: "ExecutorState",
    ) -> str:
        """Snapshot all agent workspaces + execution state.

        Args:
            graph_id: ID of the graph being checkpointed
            executor_state: Current executor state with workspaces and results

        Returns:
            Checkpoint ID that can be used to restore
        """
        checkpoint_id = f"{graph_id}_{datetime.now().isoformat()}"
        checkpoint_dir = self._store_path / checkpoint_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        agent_snapshots: dict[str, str] = {}
        for agent_id, workspace in executor_state.workspaces.items():
            agent_dir = checkpoint_dir / agent_id
            snapshot_path = await snapshot_workspace(workspace, agent_dir)
            agent_snapshots[agent_id] = str(snapshot_path)

        metadata = {
            "checkpoint_id": checkpoint_id,
            "graph_id": graph_id,
            "timestamp": datetime.now().isoformat(),
            "completed": list(executor_state.completed.keys()),
            "results": {aid: _serialize_result(res) for aid, res in executor_state.completed.items()},
            "pending": list(executor_state.pending),
            "agent_workspaces": list(executor_state.workspaces.keys()),
            "agent_snapshots": agent_snapshots,
        }

        store = await self._get_store()
        await store.put(checkpoint_id, metadata)

        return checkpoint_id

    async def restore(self, checkpoint_id: str) -> "ExecutorState":
        """Restore workspaces and execution state from checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to restore

        Returns:
            Restored ExecutorState

        Raises:
            KeyError: If checkpoint not found
        """
        store = await self._get_store()
        metadata = await store.get(checkpoint_id)

        if metadata is None:
            raise KeyError(f"Checkpoint not found: {checkpoint_id}")

        from remora.executor import ExecutorState

        checkpoint_dir = self._store_path / checkpoint_id
        workspaces = {}

        for agent_id, snapshot_path in metadata.get("agent_snapshots", {}).items():
            workspaces[agent_id] = await restore_workspace(snapshot_path)

        results = {aid: _deserialize_result(res) for aid, res in metadata.get("results", {}).items()}

        return ExecutorState(
            graph_id=metadata["graph_id"],
            nodes={},
            completed=results,
            pending=set(metadata.get("pending", [])),
            workspaces=workspaces,
        )

    async def list_checkpoints(
        self,
        graph_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List available checkpoints.

        Args:
            graph_id: Optional filter by graph ID

        Returns:
            List of checkpoint metadata dicts
        """
        store = await self._get_store()
        all_checkpoints = await store.list()

        if graph_id:
            return [cp for cp in all_checkpoints if cp.get("graph_id") == graph_id]
        return all_checkpoints

    async def delete(self, checkpoint_id: str) -> None:
        """Delete a checkpoint.

        Args:
            checkpoint_id: ID of checkpoint to delete
        """
        store = await self._get_store()
        await store.delete(checkpoint_id)

        checkpoint_dir = self._store_path / checkpoint_id
        if checkpoint_dir.exists():
            shutil.rmtree(checkpoint_dir)


__all__ = [
    "CheckpointManager",
    "JsonStore",
]
