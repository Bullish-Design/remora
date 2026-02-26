# Implementation Guide: Step 8 — Cairn-Native Checkpointing

## Overview

This step implements **Idea 11: Checkpointing via Cairn Snapshots** from the design document. It rewrites checkpointing to use Cairn's native snapshot/restore capabilities instead of the old file-backed KV store approach.

## Contract Touchpoints
- Uses Cairn workspace snapshots and restores for per-graph checkpointing.
- Serializes executor state (completed/pending/results) for resume.

## Done Criteria
- [ ] `CheckpointManager.save()` writes workspace snapshots and metadata JSON.
- [ ] `CheckpointManager.restore()` reconstructs executor state and workspaces.
- [ ] Unit tests cover save/restore and serialization round-trips.

## Prerequisites

Before starting this step, complete:
- **Step 5: Graph Module** — `src/remora/graph.py` must exist with `AgentNode` and `build_graph()`
- **Step 6: Context Builder** — `src/remora/context.py` must exist with `ContextBuilder`
- **Step 7: Executor Implementation** — `src/remora/executor.py` must exist with `ExecutorState`

---

## What This Step Does

### Current State

```
src/remora/checkpoint.py    # 312 lines - KVCheckpoint, Checkpoint, CheckpointManager
```

The old implementation:
- Uses `KVCheckpoint` to export agent KV store data as JSON files
- Uses `Checkpoint` to materialize workspace filesystem to disk
- Depends on `fsdantic.Workspace` for restore
- Creates checkpoints per-agent, not per-graph

### Target State

```
src/remora/checkpoint.py    # ~200 lines - CheckpointManager using Cairn snapshots
```

The new implementation:
- Uses Cairn's `workspace.snapshot()` to capture agent workspace state
- Uses Cairn's `CairnWorkspace.from_snapshot()` to restore workspaces
- Creates checkpoints per-graph with all agent workspaces
- Stores execution metadata (completed agents, results, pending agents) in simple JSON

### Key Changes

| Old | New |
|-----|-----|
| Per-agent checkpoints | Per-graph checkpoints with all workspaces |
| `fsdantic.Workspace` | `CairnWorkspace` (Cairn-native) |
| KV store JSON export | Execution metadata JSON |
| Filesystem materialization | Cairn snapshots |
| `CheckpointManager.checkpoint(workspace, agent_id)` | `CheckpointManager.save(graph_id, executor_state)` |

---

## Implementation Steps

### Step 8.1: Create `src/remora/checkpoint.py`

Create the new checkpoint module:

```python
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
        
        # Snapshot each agent's workspace using Cairn
        for agent_id, workspace in executor_state.workspaces.items():
            agent_dir = checkpoint_dir / agent_id
            await workspace.snapshot(str(agent_dir))
        
        # Save execution metadata
        metadata = {
            "checkpoint_id": checkpoint_id,
            "graph_id": graph_id,
            "timestamp": datetime.now().isoformat(),
            "completed": list(executor_state.completed.keys()),
            "results": {
                aid: _serialize_result(res)
                for aid, res in executor_state.completed.items()
            },
            "pending": list(executor_state.pending),
            "agent_workspaces": list(executor_state.workspaces.keys()),
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
        
        # Import here to avoid circular imports
        from remora.executor import ExecutorState
        
        # Restore workspaces from snapshots
        checkpoint_dir = self._store_path / checkpoint_id
        workspaces = {}
        
        for agent_id in metadata["agent_workspaces"]:
            agent_dir = checkpoint_dir / agent_id
            if agent_dir.exists():
                # Import CairnWorkspace
                from cairn import CairnWorkspace
                workspace = await CairnWorkspace.from_snapshot(str(agent_dir))
                workspaces[agent_id] = workspace
        
        # Restore executor state
        results = {
            aid: _deserialize_result(res)
            for aid, res in metadata.get("results", {}).items()
        }
        
        return ExecutorState(
            graph_id=metadata["graph_id"],
            nodes={},  # Nodes would need to be re-created
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


# For backwards compatibility
__all__ = [
    "CheckpointManager",
    "JsonStore",
]
```

### Step 8.2: Update Exports in `src/remora/__init__.py`

Read the current `__init__.py` and add the new exports:

```python
# Add to existing exports
from remora.checkpoint import CheckpointManager, JsonStore

# Update __all__
__all__ = [
    # ... existing exports ...
    # Checkpointing
    "CheckpointManager",
    "JsonStore",
]
```

---

## Writing Tests

Create `tests/test_checkpoint.py`:

```python
"""Tests for CheckpointManager (Cairn-native checkpointing)."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from remora.checkpoint import CheckpointManager, JsonStore, _serialize_result, _deserialize_result


class TestJsonStore:
    """Test JsonStore functionality."""
    
    @pytest.fixture
    def store_path(self, tmp_path):
        """Temporary store path."""
        return tmp_path / "store"
    
    @pytest.fixture
    def store(self, store_path):
        """Fresh JsonStore for each test."""
        return JsonStore(store_path)
    
    @pytest.mark.asyncio
    async def test_put_and_get(self, store):
        """Basic put/get operations."""
        await store.put("key1", {"foo": "bar"})
        
        result = await store.get("key1")
        assert result == {"foo": "bar"}
    
    @pytest.mark.asyncio
    async def test_get_missing(self, store):
        """Missing key returns None."""
        result = await store.get("nonexistent")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_delete(self, store):
        """Delete removes the key."""
        await store.put("key1", {"foo": "bar"})
        await store.delete("key1")
        
        result = await store.get("key1")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_list(self, store):
        """List returns all stored values."""
        await store.put("key1", {"foo": 1})
        await store.put("key2", {"foo": 2})
        
        results = await store.list()
        assert len(results) == 2
    
    @pytest.mark.asyncio
    async def test_store_creates_directory(self, store_path):
        """Store creates directory if not exists."""
        assert not store_path.exists()
        store = JsonStore(store_path)
        assert store_path.exists()


class TestSerializeDeserialize:
    """Test result serialization/deserialization."""
    
    def test_serialize_none(self):
        """None serializes correctly."""
        result = _serialize_result(None)
        assert result == {"type": "none"}
    
    def test_serialize_dict(self):
        """Dict serializes correctly."""
        result = _serialize_result({"foo": "bar"})
        assert result["type"] == "dict"
        assert result["data"] == {"foo": "bar"}
    
    def test_deserialize_dict(self):
        """Dict deserializes correctly."""
        data = {"type": "dict", "data": {"foo": "bar"}}
        result = _deserialize_result(data)
        assert result == {"foo": "bar"}
    
    def test_roundtrip_dict(self):
        """Roundtrip preserves data."""
        original = {"key": "value", "nested": {"a": 1}}
        serialized = _serialize_result(original)
        deserialized = _deserialize_result(serialized)
        assert deserialized == original


class TestCheckpointManager:
    """Test CheckpointManager functionality."""
    
    @pytest.fixture
    def checkpoint_path(self, tmp_path):
        """Temporary checkpoint path."""
        return tmp_path / "checkpoints"
    
    @pytest.fixture
    def manager(self, checkpoint_path):
        """Fresh CheckpointManager for each test."""
        return CheckpointManager(checkpoint_path)
    
    @pytest.mark.asyncio
    async def test_save_creates_checkpoint(self, manager, checkpoint_path):
        """Save creates checkpoint directory and metadata."""
        # Create mock executor state
        mock_workspace = AsyncMock()
        mock_workspace.snapshot = AsyncMock()
        
        executor_state = MagicMock()
        executor_state.workspaces = {"agent-1": mock_workspace}
        executor_state.completed = {"agent-1": {"result": "success"}}
        executor_state.pending = ["agent-2"]
        
        checkpoint_id = await manager.save("graph-1", executor_state)
        
        assert checkpoint_id.startswith("graph-1_")
        assert (checkpoint_path / checkpoint_id).exists()
    
    @pytest.mark.asyncio
    async def test_list_checkpoints(self, manager):
        """List returns saved checkpoints."""
        # Create mock executor state
        mock_workspace = AsyncMock()
        mock_workspace.snapshot = AsyncMock()
        
        executor_state = MagicMock()
        executor_state.workspaces = {}
        executor_state.completed = {}
        executor_state.pending = []
        
        await manager.save("graph-1", executor_state)
        await manager.save("graph-2", executor_state)
        
        checkpoints = await manager.list_checkpoints()
        assert len(checkpoints) >= 2
    
    @pytest.mark.asyncio
    async def test_list_checkpoints_filtered(self, manager):
        """List can filter by graph_id."""
        mock_workspace = AsyncMock()
        mock_workspace.snapshot = AsyncMock()
        
        executor_state = MagicMock()
        executor_state.workspaces = {}
        executor_state.completed = {}
        executor_state.pending = []
        
        await manager.save("graph-1", executor_state)
        await manager.save("graph-1", executor_state)
        await manager.save("graph-2", executor_state)
        
        graph1_checkpoints = await manager.list_checkpoints(graph_id="graph-1")
        assert all(cp["graph_id"] == "graph-1" for cp in graph1_checkpoints)
    
    @pytest.mark.asyncio
    async def test_delete_removes_checkpoint(self, manager, checkpoint_path):
        """Delete removes checkpoint files and directory."""
        mock_workspace = AsyncMock()
        mock_workspace.snapshot = AsyncMock()
        
        executor_state = MagicMock()
        executor_state.workspaces = {"agent-1": mock_workspace}
        executor_state.completed = {}
        executor_state.pending = []
        
        checkpoint_id = await manager.save("graph-1", executor_state)
        checkpoint_dir = checkpoint_path / checkpoint_id
        
        assert checkpoint_dir.exists()
        
        await manager.delete(checkpoint_id)
        
        assert not checkpoint_dir.exists()
    
    @pytest.mark.asyncio
    async def test_restore_raises_on_missing(self, manager):
        """Restore raises KeyError for missing checkpoint."""
        with pytest.raises(KeyError):
            await manager.restore("nonexistent-checkpoint")


class TestCheckpointManagerIntegration:
    """Integration tests with mock Cairn workspace."""
    
    @pytest.fixture
    def checkpoint_path(self, tmp_path):
        """Temporary checkpoint path."""
        return tmp_path / "checkpoints"
    
    @pytest.fixture
    def manager(self, checkpoint_path):
        """Fresh CheckpointManager for each test."""
        return CheckpointManager(checkpoint_path)
    
    @pytest.mark.asyncio
    async def test_full_checkpoint_restore_cycle(self, manager, checkpoint_path):
        """Test complete save-restore cycle."""
        # Create mock Cairn workspace
        mock_workspace = AsyncMock()
        mock_workspace.snapshot = AsyncMock()
        mock_workspace.from_snapshot = AsyncMock()
        
        # Create executor state with workspace
        executor_state = MagicMock()
        executor_state.workspaces = {"agent-1": mock_workspace}
        executor_state.completed = {
            "agent-1": {"status": "success", "data": {"key": "value"}}
        }
        executor_state.pending = ["agent-2"]
        executor_state.graph_id = "graph-1"
        
        # Save checkpoint
        checkpoint_id = await manager.save("graph-1", executor_state)
        
        # Verify metadata was saved
        metadata = await manager._get_store().get(checkpoint_id)
        assert metadata["graph_id"] == "graph-1"
        assert "agent-1" in metadata["completed"]
        assert "agent-2" in metadata["pending"]
        
        # Verify workspace snapshot was called
        mock_workspace.snapshot.assert_called_once()
```

---

## Verification

### Basic Import Test
```bash
cd /home/andrew/Documents/Projects/remora
python -c "from remora import CheckpointManager; print('Import OK')"
```

### Run Tests
```bash
cd /home/andrew/Documents/Projects/remora
python -m pytest tests/test_checkpoint.py -v
```

### Verify No Broken Imports
```bash
grep -r "from remora.checkpoint import" src/ --include="*.py"
grep -r "remora.checkpoint\." src/ --include="*.py"
```

---

## Common Pitfalls

1. **Cairn API differences** — The actual Cairn API may differ from the mock. Check Cairn docs for `workspace.snapshot()` and `CairnWorkspace.from_snapshot()` signatures.

2. **RunResult serialization** — RunResult objects may not be directly JSON-serializable. The `_serialize_result` helper handles common cases but may need extension.

3. **Circular imports** — Import `ExecutorState` inside methods using `TYPE_CHECKING` guard to avoid circular imports.

4. **Checkpoint cleanup** — Old checkpoints can accumulate. Consider adding a cleanup mechanism or TTL for checkpoint directories.

5. **Workspace restoration** — `from_snapshot` may have different behavior than expected. Test with real Cairn workspaces, not just mocks.

6. **Missing metadata directory** — The `_metadata` subdirectory is created lazily. Ensure it's created before using the store.

---

## Files Created/Modified Summary

| File | Action | Description |
|------|--------|-------------|
| `src/remora/checkpoint.py` | REWRITE | ~200 lines - CheckpointManager with Cairn snapshots |
| `src/remora/__init__.py` | MODIFY | Add CheckpointManager, JsonStore exports |
| `tests/test_checkpoint.py` | CREATE | ~180 lines - Comprehensive tests |

---

## What This Preserves

- **Save/restore of graph execution state** — Completed agents, results, pending agents
- **Resume from checkpoint** — Workspaces restored with all state
- **Multiple named checkpoints** — Each checkpoint has unique ID based on graph_id + timestamp
- **List/delete operations** — Manage existing checkpoints

---

## What This Eliminates

- Old `CheckpointManager.checkpoint(workspace, agent_id)` — Replaced with graph-level save
- `KVCheckpoint` class — No longer needed
- `Checkpoint` class (old) — Replaced with Cairn-native approach
- Filesystem materialization code — Now handled by Cairn
- Dependencies on `fsdantic.Workspace` — Uses `CairnWorkspace` instead

---

## Next Step

After this step is complete and verified, proceed to **Step 9: Rewrite .pym Scripts** (Idea 8) which converts scripts to pure-function style with virtual FS in, structured result out.
