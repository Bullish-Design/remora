"""Checkpoint management for graph execution state.

Workspace snapshots are not supported by the current Cairn API.
This manager persists execution metadata only.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from remora.core.errors import CheckpointError
from remora.utils import PathLike, normalize_path
from remora.core.executor import AgentState, ExecutorState, ResultSummary
from remora.core.graph import AgentNode
from remora.core.workspace import AgentWorkspace

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Save and restore graph execution state metadata."""

    def __init__(self, base_path: PathLike):
        self._base_path = normalize_path(base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)

    async def save(
        self,
        executor_state: ExecutorState,
        workspaces: dict[str, AgentWorkspace],
    ) -> str:
        checkpoint_id = f"{executor_state.graph_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        checkpoint_dir = self._base_path / checkpoint_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        try:
            metadata = {
                "graph_id": executor_state.graph_id,
                "pending": list(executor_state.pending),
                "failed": list(executor_state.failed),
                "skipped": list(executor_state.skipped),
                "states": {k: v.value for k, v in executor_state.states.items()},
                "results": {aid: res.to_dict() for aid, res in executor_state.completed.items()},
                "nodes": {nid: self._serialize_node(node) for nid, node in executor_state.nodes.items()},
            }

            metadata_path = checkpoint_dir / "metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            if workspaces:
                logger.info("Workspace snapshots are not supported; skipping %d workspaces", len(workspaces))

            logger.info("Saved checkpoint: %s", checkpoint_id)
            return checkpoint_id

        except Exception as exc:
            raise CheckpointError(f"Failed to save checkpoint: {exc}") from exc

    async def restore(
        self,
        checkpoint_id: str,
    ) -> tuple[ExecutorState, dict[str, AgentWorkspace]]:
        checkpoint_dir = self._base_path / checkpoint_id
        if not checkpoint_dir.exists():
            raise CheckpointError(f"Checkpoint not found: {checkpoint_id}")

        try:
            metadata_path = checkpoint_dir / "metadata.json"
            with open(metadata_path) as f:
                metadata = json.load(f)

            completed = {aid: ResultSummary.from_dict(data) for aid, data in metadata.get("results", {}).items()}

            nodes = {nid: self._deserialize_node(data) for nid, data in metadata.get("nodes", {}).items()}

            states = {k: AgentState(v) for k, v in metadata.get("states", {}).items()}

            workspaces: dict[str, AgentWorkspace] = {}
            logger.info("Workspace snapshots are not supported; restoring metadata only")

            state = ExecutorState(
                graph_id=metadata["graph_id"],
                nodes=nodes,
                states=states,
                completed=completed,
                pending=set(metadata.get("pending", [])),
                failed=set(metadata.get("failed", [])),
                skipped=set(metadata.get("skipped", [])),
            )

            logger.info("Restored checkpoint: %s", checkpoint_id)
            return state, workspaces

        except Exception as exc:
            raise CheckpointError(f"Failed to restore checkpoint: {exc}") from exc

    def list_checkpoints(self, graph_id: str | None = None) -> list[str]:
        checkpoints = []
        for item in self._base_path.iterdir():
            if item.is_dir() and (item / "metadata.json").exists():
                if graph_id is None or item.name.startswith(graph_id):
                    checkpoints.append(item.name)
        return sorted(checkpoints, reverse=True)

    def delete(self, checkpoint_id: str) -> None:
        checkpoint_dir = self._base_path / checkpoint_id
        if checkpoint_dir.exists():
            shutil.rmtree(checkpoint_dir)
            logger.info("Deleted checkpoint: %s", checkpoint_id)

    def _serialize_node(self, node: AgentNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "name": node.name,
            "target": {
                "node_id": node.target.node_id,
                "node_type": node.target.node_type,
                "name": node.target.name,
                "full_name": node.target.full_name,
                "file_path": node.target.file_path,
                "text": node.target.text,
                "start_line": node.target.start_line,
                "end_line": node.target.end_line,
                "start_byte": node.target.start_byte,
                "end_byte": node.target.end_byte,
            },
            "bundle_path": str(node.bundle_path),
            "upstream": list(node.upstream),
            "downstream": list(node.downstream),
            "priority": node.priority,
        }

    def _deserialize_node(self, data: dict[str, Any]) -> AgentNode:
        from remora.core.discovery import CSTNode

        target_data = data["target"]
        target = CSTNode(
            node_id=target_data["node_id"],
            node_type=target_data["node_type"],
            name=target_data["name"],
            full_name=target_data.get("full_name", target_data.get("name", "unknown")),
            file_path=target_data["file_path"],
            text=target_data.get("text", ""),
            start_line=target_data.get("start_line", 1),
            end_line=target_data.get("end_line", 1),
            start_byte=target_data.get("start_byte", 0),
            end_byte=target_data.get("end_byte", 0),
        )

        return AgentNode(
            id=data["id"],
            name=data["name"],
            target=target,
            bundle_path=Path(data["bundle_path"]),
            upstream=frozenset(data.get("upstream", [])),
            downstream=frozenset(data.get("downstream", [])),
            priority=data.get("priority", 0),
        )


__all__ = [
    "CheckpointManager",
]
