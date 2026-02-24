"""Workspace management for agent graphs.

This module provides:
1. GraphWorkspace: A workspace that spans an entire agent graph
2. Integration with Cairn/Fsdantic workspaces
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path


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

    def snapshot_original(self, source_path: Path) -> None:
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

        return workspace

    def cleanup(self) -> None:
        """Clean up the workspace directory."""
        if self.root.exists():
            shutil.rmtree(self.root)
        self._agent_spaces.clear()
        self._shared_space = None
        self._original_source = None


@dataclass
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

    _workspaces: dict[str, GraphWorkspace] = field(default_factory=dict)
    _base_dir: Path = field(default_factory=lambda: Path("./remora_workspaces"))

    def __post_init__(self):
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
