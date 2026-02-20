# Node State Hub - Concept Document v2

> **Version**: 2.0
> **Status**: Design Approved
> **Dependencies**: FSdantic, Grail, watchfiles
> **Prerequisite**: Two-Track Memory (Phase 1) must be complete

---

## Executive Summary

The Node State Hub is a **background daemon** that maintains a live, pre-computed index of codebase metadata. It provides instant context to Remora agents without requiring expensive AST parsing at runtime.

### Key Design Decisions (v2)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Architecture** | Background daemon | Continuous freshness, zero runtime latency |
| **Storage** | FSdantic workspace (Turso) | Native concurrency, type-safe repositories |
| **IPC** | None - shared workspace | Direct reads via FSdantic, no socket overhead |
| **Fallback** | Lazy Daemon pattern | Graceful degradation when daemon not running |

### What Changed from v1

1. **Removed IPC layer** - No Unix socket server/client; use shared AgentFS workspace instead
2. **FSdantic-native storage** - Use `TypedKVRepository` instead of raw SQLite
3. **Lazy Daemon pattern** - Ad-hoc indexing fallback for better UX
4. **Simplified architecture** - ~50% less code than v1 proposal

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Hub Daemon                                │
│                    (remora-hub process)                          │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │  FileWatcher │───►│ Rules Engine │───►│  NodeStateStore   │  │
│  │ (watchfiles) │    │ (no LLM)     │    │ (TypedKVRepository)│  │
│  └──────────────┘    └──────────────┘    └─────────┬─────────┘  │
│                                                     │            │
│                                              Fsdantic.open()     │
│                                               (read-write)       │
└─────────────────────────────────────────────────────────────────┘
                                                     │
                                                     ▼
                                    ┌─────────────────────────────┐
                                    │         hub.db              │
                                    │     (AgentFS/Turso)         │
                                    │                             │
                                    │  • Excellent concurrency    │
                                    │  • WAL handled natively     │
                                    │  • No locking concerns      │
                                    └─────────────────────────────┘
                                                     │
                                              Fsdantic.open()
                                               (read-only)
                                                     │
                                                     ▼
                                    ┌─────────────────────────────┐
                                    │      Remora Analyzer        │
                                    │       (HubClient)           │
                                    │                             │
                                    │  • Lazy Daemon check        │
                                    │  • Ad-hoc fallback          │
                                    │  • Direct workspace reads   │
                                    └─────────────────────────────┘
```

### Why No IPC?

The original v1 concept proposed Unix socket IPC between daemon and client. This is unnecessary because:

1. **Turso handles concurrency natively** - AgentFS is built on Turso (embedded libSQL), which supports concurrent readers with a single writer without manual WAL configuration.

2. **Direct reads are faster** - In-process FSdantic reads (~0.1ms) are faster than socket serialization (~1-5ms).

3. **Simpler failure modes** - If the daemon dies, the client can still read the last known state directly from the database file.

---

## Core Components

### 1. NodeState Model

The primary data structure stored in the Hub. Uses FSdantic's `VersionedKVRecord` for automatic versioning and timestamps.

```python
from fsdantic import VersionedKVRecord
from pydantic import Field
from typing import Literal
from datetime import datetime

class NodeState(VersionedKVRecord):
    """State for a single code node.

    Inherits from VersionedKVRecord:
    - created_at: float (Unix timestamp)
    - updated_at: float (Unix timestamp)
    - version: int (auto-incremented on save)
    """

    # === Identity ===
    key: str
    """Unique key: 'node:{file_path}:{node_name}'"""

    file_path: str
    """Absolute path to the source file."""

    node_name: str
    """Name of the function, class, or module."""

    node_type: Literal["function", "class", "module"]
    """Type of code node."""

    # === Content Hashes ===
    source_hash: str
    """SHA256 of the node's source code."""

    file_hash: str
    """SHA256 of the entire file."""

    # === Static Analysis ===
    signature: str | None = None
    """Function/class signature: 'def foo(x: int) -> str'"""

    docstring: str | None = None
    """First line of docstring (truncated to 100 chars)."""

    imports: list[str] = Field(default_factory=list)
    """Imports used by this node."""

    decorators: list[str] = Field(default_factory=list)
    """Decorators: ['@staticmethod', '@cached']"""

    # === Cross-File Analysis (Lazy) ===
    callers: list[str] | None = None
    """Nodes that call this: ['bar.py:process']"""

    callees: list[str] | None = None
    """Nodes this calls: ['os.path.join']"""

    # === Test Discovery ===
    related_tests: list[str] | None = None
    """Test functions that exercise this node."""

    # === Quality Metrics ===
    line_count: int | None = None
    complexity: int | None = None

    # === Flags ===
    docstring_outdated: bool = False
    has_type_hints: bool = True

    # === Update Metadata ===
    update_source: Literal["file_change", "cold_start", "manual"]
    """What triggered this update."""
```

### 2. FileIndex Model

Tracks file-level metadata for efficient change detection.

```python
class FileIndex(VersionedKVRecord):
    """Tracking entry for a source file."""

    file_path: str
    """Absolute path to the file."""

    file_hash: str
    """SHA256 of file contents."""

    node_count: int
    """Number of nodes in this file."""

    last_scanned: datetime
    """When this file was last indexed."""
```

### 3. NodeStateStore

Wrapper around FSdantic's `TypedKVRepository` that provides Hub-specific operations.

```python
from fsdantic import Fsdantic, Workspace, TypedKVRepository

class NodeStateStore:
    """FSdantic-backed storage for NodeState.

    Uses TypedKVRepository for type-safe CRUD operations
    with automatic Pydantic validation.
    """

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.node_repo = workspace.kv.repository(
            prefix="node:",
            model_type=NodeState
        )
        self.file_repo = workspace.kv.repository(
            prefix="file:",
            model_type=FileIndex
        )

    # === Node Operations ===

    async def get(self, key: str) -> NodeState | None:
        """Get a single node by key."""
        return await self.node_repo.load(key)

    async def get_many(self, keys: list[str]) -> dict[str, NodeState]:
        """Get multiple nodes by keys."""
        result = await self.node_repo.load_many(keys)
        return {
            keys[item.index]: item.value
            for item in result.items
            if item.ok and item.value is not None
        }

    async def set(self, state: NodeState) -> None:
        """Store a node (handles version increment)."""
        await self.node_repo.save(state.key, state)

    async def delete(self, key: str) -> None:
        """Delete a node by key."""
        await self.node_repo.delete(key)

    async def get_by_file(self, file_path: str) -> list[NodeState]:
        """Get all nodes for a file."""
        all_nodes = await self.node_repo.list_all()
        return [n for n in all_nodes if n.file_path == file_path]

    async def invalidate_file(self, file_path: str) -> list[str]:
        """Remove all nodes for a file, return deleted keys."""
        nodes = await self.get_by_file(file_path)
        deleted = [n.key for n in nodes]
        if deleted:
            # Extract node names from keys for delete_many
            node_names = [n.node_name for n in nodes]
            await self.node_repo.delete_many(node_names)
        return deleted

    # === File Index Operations ===

    async def get_file_index(self, file_path: str) -> FileIndex | None:
        """Get file index entry."""
        return await self.file_repo.load(file_path)

    async def set_file_index(self, index: FileIndex) -> None:
        """Store file index entry."""
        await self.file_repo.save(index.file_path, index)

    # === Statistics ===

    async def stats(self) -> dict[str, int]:
        """Get storage statistics."""
        nodes = await self.node_repo.list_all()
        files = await self.file_repo.list_all()
        return {"nodes": len(nodes), "files": len(files)}
```

### 4. Rules Engine

Deterministic logic for deciding what to update when files change. No LLM involved.

```python
from dataclasses import dataclass
from pathlib import Path
from abc import ABC, abstractmethod

@dataclass
class UpdateAction(ABC):
    """Base class for update actions."""

    @abstractmethod
    async def execute(self, context: "ActionContext") -> dict:
        ...

@dataclass
class ExtractSignatures(UpdateAction):
    """Extract signatures from a file using Grail."""
    file_path: Path

    async def execute(self, context: "ActionContext") -> dict:
        return await context.run_grail_script(
            "hub/extract_signatures.pym",
            {"file_path": str(self.file_path)}
        )

@dataclass
class DeleteFileNodes(UpdateAction):
    """Delete all nodes for a deleted file."""
    file_path: Path

    async def execute(self, context: "ActionContext") -> dict:
        deleted = await context.store.invalidate_file(str(self.file_path))
        return {"deleted": deleted, "count": len(deleted)}

class RulesEngine:
    """Decides what to recompute when a file changes."""

    def get_actions(
        self,
        change_type: str,  # "added", "modified", "deleted"
        file_path: Path,
    ) -> list[UpdateAction]:
        """Return actions to execute for a file change."""

        if change_type == "deleted":
            return [DeleteFileNodes(file_path)]

        # For added/modified: extract signatures
        return [ExtractSignatures(file_path)]
```

### 5. HubClient (Lazy Daemon Pattern)

The client that Remora uses to access Hub context. Implements graceful degradation.

```python
from pathlib import Path
from fsdantic import Fsdantic, Workspace
import logging

logger = logging.getLogger(__name__)

class HubClient:
    """Client for reading Hub context with lazy fallback.

    Design: "Lazy Daemon" pattern
    - If Hub is fresh, read directly from workspace
    - If Hub is stale and daemon running, wait briefly
    - If Hub is stale and daemon not running, do ad-hoc index
    """

    def __init__(
        self,
        hub_db_path: Path | None = None,
        project_root: Path | None = None,
    ):
        self.hub_db_path = hub_db_path
        self.project_root = project_root
        self._workspace: Workspace | None = None
        self._store: NodeStateStore | None = None

    async def get_context(self, node_ids: list[str]) -> dict[str, NodeState]:
        """Get context for nodes with lazy fallback.

        Returns empty dict if Hub not available (graceful degradation).
        """
        if self.hub_db_path is None or not self.hub_db_path.exists():
            return {}

        await self._ensure_workspace()

        # Check freshness for requested nodes
        stale_files = await self._check_freshness(node_ids)

        if stale_files:
            if await self._daemon_running():
                # Daemon will update soon, proceed with stale data
                logger.debug("Hub has stale data, daemon running")
            else:
                # No daemon - do ad-hoc indexing
                logger.warning(
                    "Hub daemon not running - performing ad-hoc index",
                    extra={"stale_files": len(stale_files)}
                )
                await self._adhoc_index(stale_files)

        return await self._store.get_many(node_ids)

    async def _ensure_workspace(self) -> None:
        """Open workspace if not already open."""
        if self._workspace is None:
            # Note: FSdantic doesn't have readonly mode yet,
            # but Turso handles concurrent access safely
            self._workspace = await Fsdantic.open(
                path=str(self.hub_db_path)
            )
            self._store = NodeStateStore(self._workspace)

    async def _check_freshness(self, node_ids: list[str]) -> list[Path]:
        """Check which files are stale."""
        stale = []
        seen_files = set()

        for node_id in node_ids:
            file_path = self._node_id_to_path(node_id)
            if file_path in seen_files:
                continue
            seen_files.add(file_path)

            if not file_path.exists():
                continue

            index = await self._store.get_file_index(str(file_path))
            if index is None:
                stale.append(file_path)
            elif file_path.stat().st_mtime > index.last_scanned.timestamp():
                stale.append(file_path)

        return stale

    async def _daemon_running(self) -> bool:
        """Check if Hub daemon is running."""
        # Check for PID file or lock file
        pid_file = self.hub_db_path.parent / "hub.pid"
        return pid_file.exists()

    async def _adhoc_index(self, files: list[Path]) -> None:
        """Perform minimal ad-hoc indexing for critical files."""
        # Import here to avoid circular dependency
        from remora.hub.indexer import index_file

        for file_path in files[:5]:  # Limit to 5 files for speed
            try:
                await index_file(file_path, self._store)
            except Exception as e:
                logger.warning(f"Ad-hoc index failed for {file_path}: {e}")

    def _node_id_to_path(self, node_id: str) -> Path:
        """Extract file path from node ID."""
        # node_id format: "node:{file_path}:{node_name}"
        parts = node_id.split(":", 2)
        if len(parts) >= 2:
            return Path(parts[1])
        return Path(node_id)

    async def close(self) -> None:
        """Close the workspace."""
        if self._workspace is not None:
            await self._workspace.close()
            self._workspace = None
            self._store = None
```

---

## Daemon Lifecycle

### Startup Sequence

```python
class HubDaemon:
    """The Node State Hub background daemon."""

    async def run(self) -> None:
        """Main daemon loop."""

        # 1. Open workspace (creates hub.db if needed)
        self.workspace = await Fsdantic.open(
            path=str(self.db_path)
        )
        self.store = NodeStateStore(self.workspace)

        # 2. Write PID file for daemon detection
        self._write_pid_file()

        # 3. Cold start: index files that changed since last run
        await self._cold_start_index()

        # 4. Start file watcher
        try:
            await self._watch_loop()
        finally:
            self._remove_pid_file()
            await self.workspace.close()

    async def _cold_start_index(self) -> None:
        """Index files that changed since last shutdown."""
        logger.info("Cold start: checking for changed files...")

        indexed = 0
        for py_file in self.project_root.rglob("*.py"):
            if self._should_ignore(py_file):
                continue

            # Check if file changed since last index
            file_hash = self._hash_file(py_file)
            existing = await self.store.get_file_index(str(py_file))

            if existing and existing.file_hash == file_hash:
                continue  # No changes

            await self._index_file(py_file)
            indexed += 1

        logger.info(f"Cold start complete: indexed {indexed} files")
```

### File Watching

Uses `watchfiles` (same as Cairn's `FileWatcher`):

```python
from watchfiles import awatch, Change

async def _watch_loop(self) -> None:
    """Watch for file changes and update index."""

    async for changes in awatch(self.project_root):
        for change_type, path_str in changes:
            path = Path(path_str)

            if not path.suffix == ".py":
                continue
            if self._should_ignore(path):
                continue

            # Map watchfiles change type
            change_map = {
                Change.added: "added",
                Change.modified: "modified",
                Change.deleted: "deleted",
            }
            change = change_map.get(change_type, "modified")

            await self._handle_change(change, path)
```

---

## Integration with Two-Track Memory

The Hub provides context to the `ContextManager` via the Pull Hook:

```python
# In src/remora/context/manager.py

class ContextManager:
    async def pull_hub_context(self) -> None:
        """Pull fresh context from Hub.

        Called at the start of each turn to inject
        external context into the Decision Packet.
        """
        if self._hub_client is None:
            from remora.context.hub_client import get_hub_client
            self._hub_client = get_hub_client()

        try:
            context = await self._hub_client.get_context([self.packet.node_id])

            if context:
                node_state = context.get(self.packet.node_id)
                if node_state:
                    self.packet.hub_context = {
                        "signature": node_state.signature,
                        "docstring": node_state.docstring,
                        "related_tests": node_state.related_tests,
                        "complexity": node_state.complexity,
                        "callers": node_state.callers,
                    }
                    self.packet.hub_freshness = datetime.fromtimestamp(
                        node_state.updated_at,
                        tz=timezone.utc
                    )
        except Exception:
            # Graceful degradation - Hub is optional
            pass
```

---

## File Layout

```
src/remora/
├── hub/
│   ├── __init__.py
│   ├── models.py          # NodeState, FileIndex
│   ├── store.py           # NodeStateStore
│   ├── rules.py           # RulesEngine, UpdateActions
│   ├── watcher.py         # FileWatcher integration
│   ├── daemon.py          # HubDaemon
│   ├── indexer.py         # File indexing logic
│   └── cli.py             # CLI entry point (remora-hub)
├── context/
│   ├── hub_client.py      # HubClient (lazy daemon)
│   └── ...
└── ...

.grail/
└── hub/
    └── extract_signatures.pym   # Grail script for AST parsing
```

---

## Performance Characteristics

| Operation | Expected Latency | Notes |
|-----------|-----------------|-------|
| Hub read (cached) | <1ms | Direct FSdantic read |
| Hub read (cold) | 5-10ms | Workspace open + read |
| Cold start (small project) | 1-5s | <100 files |
| Cold start (large project) | 30-60s | 1000+ files |
| File change processing | 50-200ms | Parse + index single file |

---

## Configuration

```python
# src/remora/hub/config.py

class HubConfig:
    """Hub daemon configuration."""

    # Paths
    project_root: Path
    db_path: Path = None  # Default: {project_root}/.remora/hub.db

    # Indexing
    ignore_patterns: list[str] = [
        ".git", "__pycache__", "node_modules",
        ".venv", "venv", ".tox", "build", "dist"
    ]

    # Performance
    max_file_size_kb: int = 500  # Skip files larger than this
    index_concurrency: int = 4   # Parallel file indexing

    # Freshness
    stale_threshold_seconds: float = 5.0  # Consider stale after this
```

---

## Open Questions (Resolved)

| Question | Resolution |
|----------|------------|
| Daemon vs In-Process? | **Daemon** - better latency and freshness |
| IPC mechanism? | **None** - shared FSdantic workspace |
| Storage backend? | **FSdantic** (Turso) - native concurrency |
| Fallback strategy? | **Lazy Daemon** - ad-hoc index when needed |

---

## Next Steps

See `HUB_REFACTORING_GUIDE_v2.md` for implementation instructions.
