"""NodeStateStore - FSdantic-backed storage for Hub data.

This module wraps FSdantic's TypedKVRepository to provide
Hub-specific operations like file invalidation and batch queries.

Key design:
- Use TypedKVRepository for all CRUD operations
- Leverage VersionedKVRecord for optimistic concurrency
- No raw SQL - use repository methods only
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fsdantic import Workspace, TypedKVRepository

from remora.hub.models import FileIndex, HubStatus, NodeState

if TYPE_CHECKING:
    from fsdantic import BatchResult

logger = logging.getLogger(__name__)


class NodeStateStore:
    """FSdantic-backed storage for NodeState and FileIndex.

    Provides type-safe CRUD operations using TypedKVRepository.
    All data is stored in a single AgentFS workspace (hub.db).

    Usage:
        workspace = await Fsdantic.open(path="hub.db")
        store = NodeStateStore(workspace)

        await store.set(node_state)
        state = await store.get("node:/path/to/file.py:function_name")
    """

    def __init__(self, workspace: Workspace) -> None:
        """Initialize the store with an open workspace.

        Args:
            workspace: Open FSdantic Workspace instance
        """
        self.workspace = workspace

        # Create typed repositories for each model
        # Prefix determines the key namespace in KV store
        self.node_repo: TypedKVRepository[NodeState] = workspace.kv.repository(
            prefix="node:",
            model_type=NodeState,
        )
        self.file_repo: TypedKVRepository[FileIndex] = workspace.kv.repository(
            prefix="file:",
            model_type=FileIndex,
        )
        self.status_repo: TypedKVRepository[HubStatus] = workspace.kv.repository(
            prefix="hub:",
            model_type=HubStatus,
        )

    # === Node Operations ===

    async def get(self, key: str) -> NodeState | None:
        """Get a single node by full key.

        Args:
            key: Full node key (e.g., "node:/path/file.py:func_name")
                 Note: prefix "node:" is handled by repository

        Returns:
            NodeState or None if not found
        """
        node_key = self._strip_prefix(key, "node:")
        return await self.node_repo.load(node_key)

    async def get_many(self, keys: list[str]) -> dict[str, NodeState]:
        """Get multiple nodes by keys.

        Args:
            keys: List of full node keys

        Returns:
            Dict mapping keys to NodeState (missing keys omitted)
        """
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
        """Store a node state.

        The repository handles version checking automatically
        via VersionedKVRecord semantics.

        Args:
            state: NodeState to store
        """
        node_key = self._strip_prefix(state.key, "node:")
        await self.node_repo.save(node_key, state)

    async def set_many(self, states: list[NodeState]) -> None:
        """Store multiple node states.

        Args:
            states: List of NodeState objects to store
        """
        if not states:
            return

        records = [(self._strip_prefix(s.key, "node:"), s) for s in states]
        await self.node_repo.save_many(records)

    async def delete(self, key: str) -> None:
        """Delete a node by key.

        Args:
            key: Full node key
        """
        node_key = self._strip_prefix(key, "node:")
        await self.node_repo.delete(node_key)

    async def list_all_nodes(self) -> list[NodeState]:
        """List all stored nodes.

        Warning: Loads all nodes into memory. Use with caution
        on large codebases.

        Returns:
            List of all NodeState objects
        """
        return await self.node_repo.list_all()

    async def get_by_file(self, file_path: str) -> list[NodeState]:
        """Get all nodes for a specific file.

        Args:
            file_path: Absolute file path

        Returns:
            List of NodeState objects for that file
        """
        all_nodes = await self.node_repo.list_all()
        return [node for node in all_nodes if node.file_path == file_path]

    async def invalidate_file(self, file_path: str) -> list[str]:
        """Remove all nodes for a file.

        Used when a file is deleted or needs full re-indexing.

        Args:
            file_path: Absolute file path

        Returns:
            List of deleted node keys
        """
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

    # === File Index Operations ===

    async def get_file_index(self, file_path: str) -> FileIndex | None:
        """Get file index entry.

        Args:
            file_path: Absolute file path

        Returns:
            FileIndex or None if not tracked
        """
        return await self.file_repo.load(file_path)

    async def set_file_index(self, index: FileIndex) -> None:
        """Store file index entry.

        Args:
            index: FileIndex to store
        """
        await self.file_repo.save(index.file_path, index)

    async def delete_file_index(self, file_path: str) -> None:
        """Delete file index entry.

        Args:
            file_path: Absolute file path
        """
        await self.file_repo.delete(file_path)

    async def list_all_files(self) -> list[FileIndex]:
        """List all tracked files.

        Returns:
            List of all FileIndex objects
        """
        return await self.file_repo.list_all()

    # === Hub Status Operations ===

    async def get_status(self) -> HubStatus | None:
        """Get current Hub status."""
        return await self.status_repo.load("status")

    async def set_status(self, status: HubStatus) -> None:
        """Update Hub status."""
        await self.status_repo.save("status", status)

    # === Statistics ===

    async def stats(self) -> dict[str, int]:
        """Get storage statistics.

        Returns:
            Dict with 'nodes' and 'files' counts
        """
        nodes = await self.node_repo.list_all()
        files = await self.file_repo.list_all()
        return {"nodes": len(nodes), "files": len(files)}

    # === Garbage Collection ===

    async def gc_stale_nodes(self, max_age_seconds: float = 86400) -> int:
        """Remove nodes not updated within max_age_seconds.

        Args:
            max_age_seconds: Maximum age in seconds (default: 24 hours)

        Returns:
            Number of nodes removed
        """
        import time

        cutoff = time.time() - max_age_seconds

        all_nodes = await self.node_repo.list_all()
        stale = [node for node in all_nodes if node.updated_at < cutoff]

        if stale:
            stale_keys = [self._strip_prefix(node.key, "node:") for node in stale]
            await self.node_repo.delete_many(stale_keys)
            logger.info("GC removed %s stale nodes", len(stale))

        return len(stale)

    # === Helpers ===

    @staticmethod
    def _strip_prefix(key: str, prefix: str) -> str:
        """Strip prefix from key if present."""
        if key.startswith(prefix):
            return key[len(prefix) :]
        return key
