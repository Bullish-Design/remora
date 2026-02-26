"""FSdantic-backed storage for NodeState and FileIndex."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fsdantic import Workspace, TypedKVRepository

from remora.indexer.models import FileIndex, NodeState

if TYPE_CHECKING:
    from fsdantic import BatchResult

logger = logging.getLogger(__name__)


class NodeStateStore:
    """FSdantic-backed storage for NodeState and FileIndex.

    Usage:
        workspace = await Fsdantic.open(path=".remora/indexer.db")
        store = NodeStateStore(workspace)

        await store.set(node_state)
        state = await store.get("node:/path/file.py:func_name")
    """

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._lock = asyncio.Lock()

        self.node_repo: TypedKVRepository[NodeState] = workspace.kv.repository(
            prefix="node:",
            model_type=NodeState,
        )
        self.file_repo: TypedKVRepository[FileIndex] = workspace.kv.repository(
            prefix="file:",
            model_type=FileIndex,
        )

    async def get(self, key: str) -> NodeState | None:
        """Get a single node by full key."""
        node_key = self._strip_prefix(key, "node:")
        return await self.node_repo.load(node_key)

    async def get_many(self, keys: list[str]) -> dict[str, NodeState]:
        """Get multiple nodes by keys."""
        if not keys:
            return {}

        node_keys = [self._strip_prefix(k, "node:") for k in keys]
        result = await self.node_repo.load_many(node_keys)

        output: dict[str, NodeState] = {}
        for i, item in enumerate(result.items):
            if item.ok and item.value is not None:
                output[keys[i]] = item.value

        return output

    async def set(self, state: NodeState) -> None:
        """Store a node state."""
        node_key = self._strip_prefix(state.key, "node:")
        await self.node_repo.save(node_key, state)

    async def set_many(self, states: list[NodeState]) -> None:
        """Store multiple node states."""
        if not states:
            return

        records = [(self._strip_prefix(s.key, "node:"), s) for s in states]
        await self.node_repo.save_many(records)

    async def delete(self, key: str) -> None:
        """Delete a node by key."""
        node_key = self._strip_prefix(key, "node:")
        await self.node_repo.delete(node_key)

    async def list_all_nodes(self) -> list[NodeState]:
        """List all stored nodes."""
        return await self.node_repo.list_all()

    async def get_by_file(self, file_path: str) -> list[NodeState]:
        """Get all nodes for a specific file."""
        all_ids = await self.node_repo.list_ids()

        file_prefix = f"{file_path}:"
        file_node_ids = [node_id for node_id in all_ids if node_id.startswith(file_prefix)]

        if not file_node_ids:
            return []

        nodes_dict = await self.get_many([f"node:{n}" for n in file_node_ids])
        return list(nodes_dict.values())

    async def invalidate_file(self, file_path: str) -> list[str]:
        """Remove all nodes for a file."""
        nodes = await self.get_by_file(file_path)
        deleted_keys = [node.key for node in nodes]

        if deleted_keys:
            node_keys = [self._strip_prefix(k, "node:") for k in deleted_keys]
            await self.node_repo.delete_many(node_keys)
            logger.debug(
                "Invalidated file nodes",
                extra={"file_path": file_path, "count": len(deleted_keys)},
            )

        await self.delete_file_index(file_path)

        return deleted_keys

    async def invalidate_and_set(
        self,
        file_path: str,
        states: list[NodeState],
        file_index: FileIndex,
    ) -> None:
        """Atomic operation: invalidate + set + set_file_index."""
        async with self._lock:
            await self.invalidate_file(file_path)
            if states:
                await self.set_many(states)
            await self.set_file_index(file_index)

    async def get_file_index(self, file_path: str) -> FileIndex | None:
        """Get file index entry."""
        return await self.file_repo.load(file_path)

    async def set_file_index(self, index: FileIndex) -> None:
        """Store file index entry."""
        await self.file_repo.save(index.file_path, index)

    async def delete_file_index(self, file_path: str) -> None:
        """Delete file index entry."""
        await self.file_repo.delete(file_path)

    async def list_all_files(self) -> list[FileIndex]:
        """List all tracked files."""
        return await self.file_repo.list_all()

    async def stats(self) -> dict[str, int]:
        """Get storage statistics."""
        nodes = await self.node_repo.list_all()
        files = await self.file_repo.list_all()
        return {"nodes": len(nodes), "files": len(files)}

    @staticmethod
    def _strip_prefix(key: str, prefix: str) -> str:
        """Strip prefix from key if present."""
        if key.startswith(prefix):
            return key[len(prefix) :]
        return key
