"""Workspace management for agent graphs.

This module provides:
1. GraphWorkspace: A workspace that spans an entire agent graph
2. Integration with Cairn/Fsdantic workspaces
3. WorkspaceKV: Key-value store for IPC between agents and frontend
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class WorkspaceKV:
    """Key-value store for workspace IPC.

    Used for communication between agents and the frontend dashboard.
    Supports listing keys with prefix, getting, setting, and deleting values.

    Keys follow patterns:
    - outbox:question:{msg_id} - Questions from agent to user
    - inbox:response:{msg_id} - Responses from user to agent
    - agent:{agent_id}:state - Agent state information
    """

    def __init__(self, kv_dir: Path):
        self._dir = kv_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._load_all()

    def _load_all(self) -> None:
        """Load all KV pairs from disk into memory."""
        if not self._dir.exists():
            return
        for file in self._dir.rglob("*.json"):
            try:
                rel_path = file.relative_to(self._dir)
                key = str(rel_path.with_suffix("")).replace("/", ":")
                self._cache[key] = json.loads(file.read_text())
            except (json.JSONDecodeError, OSError):
                continue

    def _key_to_path(self, key: str) -> Path:
        """Convert key to file path."""
        parts = key.split(":")
        return self._dir / Path(*parts).with_suffix(".json")

    async def list(self, prefix: str = "") -> list[dict[str, str]]:
        """List all keys with optional prefix.

        Args:
            prefix: Only return keys starting with this prefix

        Returns:
            List of dicts with 'key' field for each matching entry
        """
        async with self._lock:
            results = []
            for key in self._cache.keys():
                if key.startswith(prefix):
                    results.append({"key": key})
            return results

    async def get(self, key: str) -> dict[str, Any] | None:
        """Get a value by key.

        Args:
            key: The key to retrieve

        Returns:
            The stored value dict, or None if not found
        """
        async with self._lock:
            return self._cache.get(key)

    async def set(self, key: str, value: dict[str, Any]) -> None:
        """Set a value by key.

        Args:
            key: The key to store under
            value: The value to store (must be JSON-serializable dict)
        """
        async with self._lock:
            self._cache[key] = value
            path = self._key_to_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, separators=(",", ":")))

    async def delete(self, key: str) -> None:
        """Delete a key.

        Args:
            key: The key to delete
        """
        async with self._lock:
            self._cache.pop(key, None)
            path = self._key_to_path(key)
            if path.exists():
                path.unlink()

    async def clear(self) -> None:
        """Clear all keys."""
        async with self._lock:
            self._cache.clear()
            if self._dir.exists():
                shutil.rmtree(self._dir)
                self._dir.mkdir(parents=True, exist_ok=True)


@dataclass
class GraphWorkspace:
    """A workspace that spans an entire agent graph.

    Provides:
    - Agent-specific directories
    - Shared space for passing artifacts
    - Original source snapshot
    """

    id: str
    root: Path

    _agent_spaces: dict[str, Path] = field(default_factory=dict)
    _shared_space: Path | None = None
    _original_source: Path | None = None
    _kv: WorkspaceKV | None = None

    @property
    def kv(self) -> WorkspaceKV:
        """Key-value store for agent-frontend IPC.

        Returns:
            WorkspaceKV instance for storing/retrieving IPC data
        """
        if self._kv is None:
            self._kv = WorkspaceKV(self.root / "kv")
        return self._kv

    def agent_space(self, agent_id: str) -> Path:
        """Private space for an agent.

        Args:
            agent_id: Unique identifier for the agent

        Returns:
            Path to the agent's private workspace
        """
        if agent_id not in self._agent_spaces:
            path = self.root / "agents" / agent_id
            path.mkdir(parents=True, exist_ok=True)
            self._agent_spaces[agent_id] = path
        return self._agent_spaces[agent_id]

    def shared_space(self) -> Path:
        """Shared space for passing data between agents.

        Returns:
            Path to the shared workspace
        """
        if self._shared_space is None:
            self._shared_space = self.root / "shared"
            self._shared_space.mkdir(parents=True, exist_ok=True)
        return self._shared_space

    def original_source(self) -> Path:
        """Read-only copy of original source.

        Returns:
            Path to the original source snapshot
        """
        if self._original_source is None:
            self._original_source = self.root / "original"
            self._original_source.mkdir(parents=True, exist_ok=True)
        return self._original_source

    async def snapshot_original(self, source_path: Path) -> None:
        """Create a snapshot of the original source code.

        Args:
            source_path: Path to the source code to snapshot
        """
        original_dir = self.original_source()

        if source_path.is_file():
            shutil.copy2(source_path, original_dir / source_path.name)
        elif source_path.is_dir():
            for item in source_path.rglob("*"):
                if item.is_file():
                    rel_path = item.relative_to(source_path)
                    dest = original_dir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)

    async def merge(self) -> None:
        """Merge agent changes back to original.

        This takes all the modifications made by agents in their
        individual workspaces and merges them back to the original source.
        """
        original_dir = self.original_source()

        for _agent_id, agent_space in self._agent_spaces.items():
            if not agent_space.exists():
                continue

            for item in agent_space.rglob("*"):
                if item.is_file():
                    rel_path = item.relative_to(agent_space)
                    dest = original_dir / rel_path

                    if dest.exists():
                        await self._merge_files(item, dest)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest)

    async def _merge_files(self, source: Path, dest: Path) -> None:
        """Merge a modified file back to original.

        For now, this is a simple overwrite. In the future,
        this could use more sophisticated merge strategies.
        """
        shutil.copy2(source, dest)

    @classmethod
    async def create(cls, id: str, root: Path | str | None = None) -> "GraphWorkspace":
        """Create a new graph workspace.

        Args:
            id: Unique identifier for this graph workspace
            root: Root directory (defaults to ./remora_workspaces/{id})

        Returns:
            New GraphWorkspace instance
        """
        if root is None:
            root = Path("./remora_workspaces") / id
        elif isinstance(root, str):
            root = Path(root)

        root.mkdir(parents=True, exist_ok=True)

        workspace = cls(id=id, root=root)

        (workspace.root / "agents").mkdir(exist_ok=True)
        workspace.shared_space()
        workspace.original_source()
        workspace.kv  # Initialize KV store

        return workspace

    def cleanup(self) -> None:
        """Clean up the workspace directory."""
        if self.root.exists():
            shutil.rmtree(self.root)
        self._agent_spaces.clear()
        self._shared_space = None
        self._original_source = None
        self._kv = None

    async def save_metadata(self, metadata: dict[str, Any]) -> None:
        """Save graph metadata to workspace.

        Args:
            metadata: Dict containing graph metadata (graph_id, bundle, target, etc.)
        """
        metadata_path = self.root / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, separators=(",", ":")))

    async def load_metadata(self) -> dict[str, Any] | None:
        """Load graph metadata from workspace.

        Returns:
            Dict containing graph metadata, or None if not found
        """
        metadata_path = self.root / "metadata.json"
        if not metadata_path.exists():
            return None
        return json.loads(metadata_path.read_text())


class WorkspaceManager:
    """Manages multiple GraphWorkspaces.

    Usage:
        manager = WorkspaceManager()

        # Create a workspace for a graph
        workspace = await manager.create("graph-123")

        # Get an existing workspace
        workspace = manager.get("graph-123")

        # List all workspaces
        workspaces = manager.list()

        # Clean up
        await manager.delete("graph-123")
    """

    def __init__(self, base_dir: Path | str | None = None):
        self._workspaces: dict[str, GraphWorkspace] = {}
        if base_dir is None:
            self._base_dir = Path("./remora_workspaces")
        elif isinstance(base_dir, str):
            self._base_dir = Path(base_dir)
        else:
            self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    async def create(self, id: str, root: Path | str | None = None) -> GraphWorkspace:
        """Create a new workspace."""
        if id in self._workspaces:
            return self._workspaces[id]

        workspace = await GraphWorkspace.create(id, root)
        self._workspaces[id] = workspace
        return workspace

    def get(self, id: str) -> GraphWorkspace | None:
        """Get an existing workspace."""
        return self._workspaces.get(id)

    def list(self) -> list[GraphWorkspace]:
        """List all workspaces."""
        return list(self._workspaces.values())

    async def list_all(self) -> list[GraphWorkspace]:
        """List all workspaces including persisted ones on disk.

        Returns:
            List of all GraphWorkspace instances (in-memory and from disk)
        """
        all_workspaces = list(self._workspaces.values())

        if self._base_dir.exists():
            for item in self._base_dir.iterdir():
                if item.is_dir():
                    ws_id = item.name
                    if ws_id not in self._workspaces:
                        ws = GraphWorkspace(id=ws_id, root=item)
                        all_workspaces.append(ws)

        return all_workspaces

    async def delete(self, id: str) -> None:
        """Delete a workspace."""
        if id in self._workspaces:
            self._workspaces[id].cleanup()
            del self._workspaces[id]

    def get_or_create(self, id: str) -> GraphWorkspace:
        """Get existing or create new workspace."""
        if id not in self._workspaces:
            import asyncio

            self._workspaces[id] = asyncio.run(GraphWorkspace.create(id, self._base_dir / id))
        return self._workspaces[id]
