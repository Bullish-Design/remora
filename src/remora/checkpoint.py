"""Workspace Checkpointing - Materialize sandboxes to disk.

This module provides the ability to:
1. Materialize the virtual filesystem to disk
2. Export KV store to JSON files
3. Create complete checkpoints for jujutsu/github versioning
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class KVCheckpoint:
    """Represents a checkpoint of the KV store."""

    timestamp: datetime
    entries: list[dict[str, Any]] = field(default_factory=list)

    def to_dir(self, path: Path) -> None:
        """Write KV entries as JSON files to a directory.

        Structure:
            path/
                _metadata.json      # timestamp, entry count
                a/
                    alice.json     # key "alice" -> alice.json
                    _index.json    # directory listing
                b/
                    ...
        """
        path.mkdir(parents=True, exist_ok=True)

        (path / "_metadata.json").write_text(
            json.dumps({"timestamp": self.timestamp.isoformat(), "entry_count": len(self.entries)}, indent=2)
        )

        by_prefix: dict[str, list] = {}
        for entry in self.entries:
            key = entry.get("key", "")
            prefix = key[0].lower() if key else "_"
            by_prefix.setdefault(prefix, []).append(entry)

        for prefix, entries_list in by_prefix.items():
            prefix_dir = path / prefix
            prefix_dir.mkdir(exist_ok=True)

            for entry in entries_list:
                safe_key = entry.get("key", "").replace(":", "_")
                (prefix_dir / f"{safe_key}.json").write_text(json.dumps(entry, indent=2))

            (prefix_dir / "_index.json").write_text(
                json.dumps({"keys": [e.get("key") for e in entries_list]}, indent=2)
            )

    @classmethod
    def from_dir(cls, path: Path) -> "KVCheckpoint":
        """Load KV checkpoint from directory."""
        metadata = json.loads((path / "_metadata.json").read_text())
        entries = []

        for prefix_dir in path.iterdir():
            if prefix_dir.name.startswith("_"):
                continue
            for json_file in prefix_dir.glob("*.json"):
                if json_file.name == "_index.json":
                    continue
                entries.append(json.loads(json_file.read_text()))

        return cls(timestamp=datetime.fromisoformat(metadata["timestamp"]), entries=entries)

    @classmethod
    def from_workspace(cls, workspace: Any) -> "KVCheckpoint":
        """Create KV checkpoint from workspace."""
        entries = []
        try:
            for entry in workspace.kv.list(prefix=""):
                key = entry.get("key", "") if isinstance(entry, dict) else str(entry)
                value = workspace.kv.get(key)
                entries.append({"key": key, "value": value})
        except Exception:
            pass

        return cls(timestamp=datetime.now(), entries=entries)


@dataclass
class Checkpoint:
    """Complete checkpoint of an agent's workspace.

    This is what gets versioned with jujutsu/github:
    - Virtual filesystem materialized to disk
    - KV store exported to JSON
    - Metadata about the checkpoint
    """

    agent_id: str
    created_at: datetime

    filesystem_path: Path | None = None
    kv_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _root: Path | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        agent_id: str,
        workspace: Any,
        base_path: Path,
    ) -> "Checkpoint":
        """Create a complete checkpoint from workspace."""
        checkpoint = cls(
            agent_id=agent_id,
            created_at=datetime.now(),
            filesystem_path=base_path / agent_id / "filesystem",
            kv_path=base_path / agent_id / "kv",
            metadata={
                "agent_id": agent_id,
                "created_at": datetime.now().isoformat(),
            },
        )

        checkpoint.kv_path.mkdir(parents=True, exist_ok=True)

        kv_checkpoint = KVCheckpoint.from_workspace(workspace)
        kv_checkpoint.to_dir(checkpoint.kv_path)

        return checkpoint

    def load(self) -> KVCheckpoint:
        """Load KV checkpoint from disk."""
        if self.kv_path and self.kv_path.exists():
            return KVCheckpoint.from_dir(self.kv_path)
        return KVCheckpoint(timestamp=self.created_at, entries=[])


class CheckpointManager:
    """Manages checkpointing of agent workspaces.

    Usage:
        manager = CheckpointManager(Path("/checkpoints"))

        # Materialize a workspace to disk
        checkpoint = await manager.checkpoint(
            workspace=agent_workspace,
            agent_id=agent.id,
            message="Before applying changes"
        )

        # Later: restore from checkpoint
        workspace = await manager.restore(checkpoint)
    """

    def __init__(self, checkpoint_root: Path):
        self._root = checkpoint_root
        self._root.mkdir(parents=True, exist_ok=True)

    async def checkpoint(
        self,
        workspace: Any,
        agent_id: str,
        message: str | None = None,
    ) -> Checkpoint:
        """Create a checkpoint of a workspace.

        Args:
            workspace: The Fsdantic workspace to checkpoint
            agent_id: Unique identifier for this checkpoint
            message: Optional commit message

        Returns:
            Checkpoint object with paths to materialized data
        """
        timestamp = datetime.now()
        checkpoint_id = f"{agent_id}-{timestamp.strftime('%Y%m%d_%H%M%S')}"

        checkpoint_dir = self._root / checkpoint_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        fs_dir = checkpoint_dir / "filesystem"

        if hasattr(workspace, "materialize"):
            try:
                fs_result = await workspace.materialize.to_disk(
                    target_path=fs_dir,
                    clean=True,
                )
            except Exception:
                fs_dir.mkdir(parents=True, exist_ok=True)
                fs_result = None
        else:
            fs_dir.mkdir(parents=True, exist_ok=True)
            fs_result = None

        kv_dir = checkpoint_dir / "kv"
        await self._export_kv(workspace.kv, kv_dir)

        metadata = {
            "agent_id": agent_id,
            "created_at": timestamp.isoformat(),
            "message": message,
        }
        if fs_result:
            metadata["filesystem"] = {
                "files_written": getattr(fs_result, "files_written", 0),
                "bytes_written": getattr(fs_result, "bytes_written", 0),
            }
        (checkpoint_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

        return Checkpoint(
            agent_id=agent_id,
            created_at=timestamp,
            filesystem_path=Path("filesystem"),
            kv_path=Path("kv"),
            metadata=metadata,
        )

    async def _export_kv(self, kv_manager: Any, target_dir: Path) -> KVCheckpoint:
        """Export all KV entries to disk."""
        target_dir.mkdir(parents=True, exist_ok=True)

        entries = []
        try:
            kv_list = kv_manager.list(prefix="") if hasattr(kv_manager, "list") else []
            for entry in kv_list:
                key = entry.get("key", "") if isinstance(entry, dict) else str(entry)
                try:
                    value = kv_manager.get(key) if hasattr(kv_manager, "get") else None
                    entries.append({"key": key, "value": value})
                except Exception as e:
                    entries.append({"key": key, "error": str(e)})
        except Exception:
            pass

        checkpoint = KVCheckpoint(timestamp=datetime.now(), entries=entries)
        checkpoint.to_dir(target_dir)

        return checkpoint

    async def restore(self, checkpoint: Checkpoint) -> Any:
        """Restore a workspace from a checkpoint.

        Note: This creates a NEW workspace. To continue an agent
        from a checkpoint, you'd need to also restore the kernel state.
        """
        from fsdantic import Workspace

        checkpoint_dir = checkpoint._root / f"{checkpoint.agent_id}-{checkpoint.created_at.strftime('%Y%m%d_%H%M%S')}"
        fs_dir = checkpoint_dir / "filesystem"
        kv_dir = checkpoint_dir / "kv"

        workspace = Workspace(str(fs_dir))

        kv_checkpoint = KVCheckpoint.from_dir(kv_dir)
        for entry in kv_checkpoint.entries:
            if "error" in entry:
                continue
            try:
                workspace.kv.set(entry["key"], entry["value"])
            except Exception:
                pass

        return workspace

    def list_checkpoints(self, agent_id: str | None = None) -> list[Checkpoint]:
        """List all available checkpoints.

        Args:
            agent_id: If provided, only return checkpoints for this agent
        """
        checkpoints = []

        if not self._root.exists():
            return checkpoints

        for checkpoint_dir in self._root.iterdir():
            if not checkpoint_dir.is_dir():
                continue

            metadata_file = checkpoint_dir / "metadata.json"
            if not metadata_file.exists():
                continue

            try:
                metadata = json.loads(metadata_file.read_text())
            except Exception:
                continue

            if agent_id and metadata.get("agent_id") != agent_id:
                continue

            try:
                created_at = datetime.fromisoformat(metadata.get("created_at", datetime.now().isoformat()))
            except Exception:
                created_at = datetime.now()

            checkpoints.append(
                Checkpoint(
                    agent_id=metadata.get("agent_id", "unknown"),
                    created_at=created_at,
                    filesystem_path=Path("filesystem"),
                    kv_path=Path("kv"),
                    metadata=metadata,
                )
            )

        return sorted(checkpoints, key=lambda c: c.created_at, reverse=True)
