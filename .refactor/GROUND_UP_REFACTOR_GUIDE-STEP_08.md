# Implementation Guide: Step 8 - Cairn Native Checkpointing

## Target
Implement `CheckpointManager` that snapshots all Cairn workspaces per graph run, stores execution metadata, and can restore those snapshots to resume execution without re-running completed agents.

## Overview
- Use Cairn's `workspace.snapshot()`/`from_snapshot()` APIs plus a simple JSON store for metadata.
- Save per-graph checkpoints containing workspace snapshots for each agent, the set of completed nodes, pending nodes, and serialized results.
- Restore populates a new `ExecutorState` with the recovered workspaces and results, enabling the executor to resume.

## Contract Touchpoints
- `CheckpointManager` uses Cairn `workspace.snapshot()`/`from_snapshot()` plus a JSON metadata store.
- `GraphExecutor` calls `checkpoint_manager.save()`/`restore()` with serialized results and workspace snapshots.
- Restores return a populated `ExecutorState` that the executor can resume.

## Done Criteria
- Checkpoints save and restore workspace snapshots per agent.
- Result serialization round-trips for supported result types.
- Tests cover metadata operations and full save/restore cycles.

## Steps
1. Create `CheckpointManager` that takes a checkpoint directory, snapshots each agent's workspace into a subdirectory, writes metadata via a lightweight JSON store, and exposes `save`, `restore`, `list_checkpoints`, and `delete` operations.
2. Implement result serialization helpers (`_serialize_result`, `_deserialize_result`) that handle dicts, SimpleNamespace, or objects with `model_dump`.
3. Update `executor.GraphExecutor` to call `checkpoint_manager.save()` after important milestones and to offer a `restore(checkpoint_id)` path that reuses the sanitized workspaces.
4. Write tests (`tests/test_checkpoint.py`) that cover metadata store operations, serialization round-trips, and full save/restore cycles with mocked Cairn workspaces.
