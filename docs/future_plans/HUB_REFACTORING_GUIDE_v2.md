# Hub Refactoring Guide v2

> **Version**: 2.0
> **Target**: Remora Library
> **Phase**: Node State Hub (Phase 2)
> **Prerequisites**: Two-Track Memory (Phase 1) complete

This guide provides step-by-step instructions for implementing the Node State Hub using the v2 architecture (shared FSdantic workspace, no IPC).

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Phase 2: Node State Hub](#phase-2-node-state-hub)
   - [Step 2.1: Create Hub Models](#step-21-create-hub-models)
   - [Step 2.2: Implement NodeStateStore](#step-22-implement-nodestatestore)
   - [Step 2.3: Create Analysis Scripts](#step-23-create-analysis-scripts)
   - [Step 2.4: Implement Rules Engine](#step-24-implement-rules-engine)
   - [Step 2.5: Create File Watcher](#step-25-create-file-watcher)
   - [Step 2.6: Implement Hub Daemon](#step-26-implement-hub-daemon)
   - [Step 2.7: Implement HubClient](#step-27-implement-hubclient)
   - [Step 2.8: Wire Pull Hook](#step-28-wire-pull-hook)
   - [Step 2.9: Create CLI Entry Point](#step-29-create-cli-entry-point)
3. [Testing Strategy](#testing-strategy)
4. [Migration Checklist](#migration-checklist)
5. [Appendix: Library APIs](#appendix-library-apis)

---

## Prerequisites

### Required Knowledge

- Python 3.11+ (async/await, type hints)
- Pydantic v2.10+ (BaseModel, Field, validation)
- FSdantic workspace patterns

### Codebase Orientation

Before starting, familiarize yourself with these files:

| File | Purpose |
|------|---------|
| `src/remora/context/manager.py` | ContextManager - the Pull Hook integration point |
| `src/remora/context/models.py` | DecisionPacket - where hub_context is stored |
| `src/remora/context/hub_client.py` | Current stub (to be replaced) |
| `.context/fsdantic/` | FSdantic library source |
| `.context/grail/` | Grail script execution framework |

### Key Dependencies

| Library | Location | Purpose |
|---------|----------|---------|
| `fsdantic` | `.context/fsdantic/` | Type-safe AgentFS interface |
| `grail` | `.context/grail/` | Script execution framework |
| `watchfiles` | (pip install) | File system watching |
| `pydantic` | (installed) | Data validation |

### FSdantic Quick Reference

```python
from fsdantic import (
    Fsdantic,              # Entry point for opening workspaces
    Workspace,             # Facade around AgentFS
    TypedKVRepository,     # Type-safe KV operations
    VersionedKVRecord,     # Base class with version tracking
    KVRecord,              # Base class with timestamps
)

# Opening a workspace
workspace = await Fsdantic.open(path="/path/to/db.db")

# Using repositories
repo = workspace.kv.repository(prefix="node:", model_type=NodeState)
await repo.save("my_key", node_state)
state = await repo.load("my_key")
all_states = await repo.list_all()
await repo.delete("my_key")

# Batch operations
result = await repo.load_many(["key1", "key2", "key3"])
for item in result.items:
    if item.ok:
        print(item.value)

# Closing
await workspace.close()
```

---

## Phase 2: Node State Hub

**Goal**: Implement a background daemon that maintains a live index of codebase metadata, accessible via shared FSdantic workspace.

---

### Step 2.1: Create Hub Models

**File to create**: `src/remora/hub/models.py`

```python
"""Node State Hub data models.

These models define the structure of metadata stored by the Hub daemon
and read by the HubClient.

Key design:
- Inherit from VersionedKVRecord for automatic versioning
- Use Pydantic validation at all boundaries
- Keep models JSON-serializable for FSdantic storage
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fsdantic import VersionedKVRecord
from pydantic import Field


class NodeState(VersionedKVRecord):
    """State for a single code node.

    Inherits from VersionedKVRecord (fsdantic.models):
    - created_at: float (Unix timestamp, auto-set)
    - updated_at: float (Unix timestamp, auto-updated)
    - version: int (auto-incremented on save)

    Key format: "node:{file_path}:{node_name}"
    Stored with prefix "node:" in repository.
    """

    # === Identity ===
    key: str = Field(description="Unique key: 'node:{file_path}:{node_name}'")
    file_path: str = Field(description="Absolute path to the source file")
    node_name: str = Field(description="Name of the function, class, or module")
    node_type: Literal["function", "class", "module"] = Field(
        description="Type of code node"
    )

    # === Content Hashes (for change detection) ===
    source_hash: str = Field(description="SHA256 of the node's source code")
    file_hash: str = Field(description="SHA256 of the entire file")

    # === Static Analysis Results ===
    signature: str | None = Field(
        default=None,
        description="Function/class signature: 'def foo(x: int) -> str'"
    )
    docstring: str | None = Field(
        default=None,
        description="First line of docstring (truncated to 100 chars)"
    )
    imports: list[str] = Field(
        default_factory=list,
        description="Imports used by this node"
    )
    decorators: list[str] = Field(
        default_factory=list,
        description="Decorators: ['@staticmethod', '@cached']"
    )

    # === Cross-File Analysis (Computed Lazily) ===
    callers: list[str] | None = Field(
        default=None,
        description="Nodes that call this: ['bar.py:process']"
    )
    callees: list[str] | None = Field(
        default=None,
        description="Nodes this calls: ['os.path.join']"
    )

    # === Test Discovery ===
    related_tests: list[str] | None = Field(
        default=None,
        description="Test functions that exercise this node"
    )

    # === Quality Metrics ===
    line_count: int | None = Field(default=None, description="Lines of code")
    complexity: int | None = Field(default=None, description="Cyclomatic complexity")

    # === Flags ===
    docstring_outdated: bool = Field(
        default=False,
        description="True if signature changed but docstring didn't"
    )
    has_type_hints: bool = Field(
        default=True,
        description="True if function has type annotations"
    )

    # === Update Metadata ===
    update_source: Literal["file_change", "cold_start", "manual", "adhoc"] = Field(
        description="What triggered this update"
    )


class FileIndex(VersionedKVRecord):
    """Tracking entry for a source file.

    Used for efficient change detection during cold start
    and freshness checking.

    Key format: file_path (absolute)
    Stored with prefix "file:" in repository.
    """

    file_path: str = Field(description="Absolute path to the file")
    file_hash: str = Field(description="SHA256 of file contents")
    node_count: int = Field(description="Number of nodes in this file")
    last_scanned: datetime = Field(description="When this file was last indexed")


class HubStatus(VersionedKVRecord):
    """Hub daemon status information.

    Stored as a singleton with key "status".
    """

    running: bool = Field(description="Whether daemon is currently running")
    pid: int | None = Field(default=None, description="Daemon process ID")
    project_root: str = Field(description="Project root being watched")
    indexed_files: int = Field(default=0, description="Number of files indexed")
    indexed_nodes: int = Field(default=0, description="Number of nodes indexed")
    started_at: datetime | None = Field(default=None, description="When daemon started")
    last_update: datetime | None = Field(default=None, description="Last index update")
```

**Tests for Step 2.1**: `tests/hub/test_models.py`

```python
"""Tests for Hub models."""

import pytest
from datetime import datetime, timezone
from remora.hub.models import NodeState, FileIndex, HubStatus


class TestNodeState:
    def test_create_function_node(self):
        state = NodeState(
            key="node:/project/foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            signature="def bar(x: int) -> str",
            update_source="file_change",
        )

        assert state.node_type == "function"
        assert state.signature == "def bar(x: int) -> str"
        assert state.version == 1  # Default from VersionedKVRecord

    def test_inherits_timestamps(self):
        state = NodeState(
            key="node:/project/foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            update_source="cold_start",
        )

        # Inherited from VersionedKVRecord
        assert hasattr(state, "created_at")
        assert hasattr(state, "updated_at")
        assert hasattr(state, "version")
        assert isinstance(state.created_at, float)

    def test_serializes_to_json(self):
        state = NodeState(
            key="node:/project/foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            update_source="cold_start",
        )

        json_str = state.model_dump_json()
        assert "foo.py" in json_str
        assert "bar" in json_str


class TestFileIndex:
    def test_create_file_index(self):
        index = FileIndex(
            file_path="/project/foo.py",
            file_hash="abc123",
            node_count=5,
            last_scanned=datetime.now(timezone.utc),
        )

        assert index.node_count == 5
        assert index.file_hash == "abc123"
```

---

### Step 2.2: Implement NodeStateStore

**File to create**: `src/remora/hub/store.py`

```python
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
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fsdantic import Workspace, TypedKVRepository

from remora.hub.models import NodeState, FileIndex, HubStatus

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
        # Repository expects key without prefix
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

        # Strip prefixes for repository
        node_keys = [self._strip_prefix(k, "node:") for k in keys]
        result = await self.node_repo.load_many(node_keys)

        # Build result dict, mapping back to original keys
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
        # FSdantic doesn't support secondary indexes, so we filter in memory
        # For large codebases, consider maintaining a separate index
        all_nodes = await self.node_repo.list_all()
        return [n for n in all_nodes if n.file_path == file_path]

    async def invalidate_file(self, file_path: str) -> list[str]:
        """Remove all nodes for a file.

        Used when a file is deleted or needs full re-indexing.

        Args:
            file_path: Absolute file path

        Returns:
            List of deleted node keys
        """
        nodes = await self.get_by_file(file_path)
        deleted_keys = [n.key for n in nodes]

        if deleted_keys:
            # delete_many expects keys without prefix
            node_keys = [self._strip_prefix(k, "node:") for k in deleted_keys]
            await self.node_repo.delete_many(node_keys)
            logger.debug(
                "Invalidated file nodes",
                extra={"file_path": file_path, "count": len(deleted_keys)}
            )

        # Also remove file index
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
        stale = [n for n in all_nodes if n.updated_at < cutoff]

        if stale:
            stale_keys = [self._strip_prefix(n.key, "node:") for n in stale]
            await self.node_repo.delete_many(stale_keys)
            logger.info(f"GC removed {len(stale)} stale nodes")

        return len(stale)

    # === Helpers ===

    @staticmethod
    def _strip_prefix(key: str, prefix: str) -> str:
        """Strip prefix from key if present."""
        if key.startswith(prefix):
            return key[len(prefix):]
        return key
```

**Tests for Step 2.2**: `tests/hub/test_store.py`

```python
"""Tests for NodeStateStore."""

import pytest
from datetime import datetime, timezone
from pathlib import Path

from fsdantic import Fsdantic

from remora.hub.models import NodeState, FileIndex
from remora.hub.store import NodeStateStore


@pytest.fixture
async def store(tmp_path: Path):
    """Create a temporary store for testing."""
    db_path = tmp_path / "test_hub.db"
    workspace = await Fsdantic.open(path=str(db_path))
    store = NodeStateStore(workspace)
    yield store
    await workspace.close()


class TestNodeStateStore:
    @pytest.mark.asyncio
    async def test_set_and_get(self, store: NodeStateStore):
        state = NodeState(
            key="node:/project/foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            update_source="file_change",
        )

        await store.set(state)
        retrieved = await store.get("node:/project/foo.py:bar")

        assert retrieved is not None
        assert retrieved.node_name == "bar"
        assert retrieved.source_hash == "abc123"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, store: NodeStateStore):
        result = await store.get("node:/nonexistent:missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_many(self, store: NodeStateStore):
        # Create multiple nodes
        for i in range(3):
            state = NodeState(
                key=f"node:/project/file.py:func{i}",
                file_path="/project/file.py",
                node_name=f"func{i}",
                node_type="function",
                source_hash=f"hash{i}",
                file_hash="filehash",
                update_source="cold_start",
            )
            await store.set(state)

        # Fetch multiple
        keys = [
            "node:/project/file.py:func0",
            "node:/project/file.py:func1",
            "node:/project/file.py:missing",  # This one doesn't exist
        ]
        result = await store.get_many(keys)

        assert len(result) == 2
        assert "node:/project/file.py:func0" in result
        assert "node:/project/file.py:func1" in result
        assert "node:/project/file.py:missing" not in result

    @pytest.mark.asyncio
    async def test_invalidate_file_removes_all_nodes(self, store: NodeStateStore):
        # Add multiple nodes for same file
        for name in ["foo", "bar", "baz"]:
            state = NodeState(
                key=f"node:/project/test.py:{name}",
                file_path="/project/test.py",
                node_name=name,
                node_type="function",
                source_hash=f"hash_{name}",
                file_hash="file_hash",
                update_source="file_change",
            )
            await store.set(state)

        # Also add file index
        await store.set_file_index(FileIndex(
            file_path="/project/test.py",
            file_hash="file_hash",
            node_count=3,
            last_scanned=datetime.now(timezone.utc),
        ))

        # Invalidate
        deleted = await store.invalidate_file("/project/test.py")

        assert len(deleted) == 3
        assert await store.get("node:/project/test.py:foo") is None
        assert await store.get_file_index("/project/test.py") is None

    @pytest.mark.asyncio
    async def test_stats(self, store: NodeStateStore):
        # Add some nodes
        for i in range(5):
            state = NodeState(
                key=f"node:/project/file{i}.py:func",
                file_path=f"/project/file{i}.py",
                node_name="func",
                node_type="function",
                source_hash=f"hash{i}",
                file_hash=f"filehash{i}",
                update_source="cold_start",
            )
            await store.set(state)
            await store.set_file_index(FileIndex(
                file_path=f"/project/file{i}.py",
                file_hash=f"filehash{i}",
                node_count=1,
                last_scanned=datetime.now(timezone.utc),
            ))

        stats = await store.stats()

        assert stats["nodes"] == 5
        assert stats["files"] == 5
```

---

### Step 2.3: Create Analysis Scripts

**Directory to create**: `.grail/hub/`

These Grail scripts perform static analysis on Python files.

**File**: `.grail/hub/extract_signatures.pym`

```python
"""Extract function/class signatures from a Python file.

This Grail script parses a Python file using AST and extracts
metadata for all functions and classes.

Inputs:
    file_path: str - Path to the Python file to analyze

Returns:
    dict with:
        - file_path: str
        - file_hash: str (SHA256)
        - nodes: list[dict] - Extracted node metadata
        - error: str | None - Error message if parsing failed
"""

from grail import Input, external
from typing import Any
import ast
import hashlib


# === Inputs ===
file_path: str = Input("file_path")


# === External Functions ===
@external
async def read_file(path: str) -> str:
    """Read file contents (provided by host)."""
    ...


# === Main ===
async def main() -> dict[str, Any]:
    """Extract signatures from the file."""

    # Read file
    try:
        content = await read_file(file_path)
    except Exception as e:
        return {
            "file_path": file_path,
            "error": f"Failed to read file: {e}",
            "nodes": [],
        }

    # Compute file hash
    file_hash = hashlib.sha256(content.encode()).hexdigest()

    # Parse AST
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return {
            "file_path": file_path,
            "file_hash": file_hash,
            "error": f"Syntax error at line {e.lineno}: {e.msg}",
            "nodes": [],
        }

    # Extract nodes
    nodes: list[dict[str, Any]] = []
    lines = content.splitlines()

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            nodes.append(_extract_function(node, lines, is_async=False))
        elif isinstance(node, ast.AsyncFunctionDef):
            nodes.append(_extract_function(node, lines, is_async=True))
        elif isinstance(node, ast.ClassDef):
            nodes.append(_extract_class(node, lines))

    return {
        "file_path": file_path,
        "file_hash": file_hash,
        "nodes": nodes,
        "error": None,
    }


def _extract_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: list[str],
    is_async: bool,
) -> dict[str, Any]:
    """Extract function metadata."""

    # Get source lines for this function
    start = node.lineno - 1
    end = node.end_lineno or start + 1
    func_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(func_source.encode()).hexdigest()

    # Build signature
    args = []
    for arg in node.args.args:
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"
        args.append(arg_str)

    # Handle *args, **kwargs
    if node.args.vararg:
        vararg = f"*{node.args.vararg.arg}"
        if node.args.vararg.annotation:
            vararg += f": {ast.unparse(node.args.vararg.annotation)}"
        args.append(vararg)

    if node.args.kwarg:
        kwarg = f"**{node.args.kwarg.arg}"
        if node.args.kwarg.annotation:
            kwarg += f": {ast.unparse(node.args.kwarg.annotation)}"
        args.append(kwarg)

    returns = ""
    if node.returns:
        returns = f" -> {ast.unparse(node.returns)}"

    prefix = "async def" if is_async else "def"
    signature = f"{prefix} {node.name}({', '.join(args)}){returns}"

    # Get docstring (first line only, truncated)
    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    # Get decorators
    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    # Check for type hints
    has_type_hints = (
        node.returns is not None
        or any(a.annotation for a in node.args.args)
    )

    return {
        "name": node.name,
        "type": "function",
        "signature": signature,
        "docstring": docstring,
        "decorators": decorators,
        "source_hash": source_hash,
        "line_count": end - start,
        "has_type_hints": has_type_hints,
        "start_line": node.lineno,
        "end_line": end,
    }


def _extract_class(node: ast.ClassDef, lines: list[str]) -> dict[str, Any]:
    """Extract class metadata."""

    start = node.lineno - 1
    end = node.end_lineno or start + 1
    class_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(class_source.encode()).hexdigest()

    # Build signature
    bases = [ast.unparse(b) for b in node.bases]
    signature = f"class {node.name}"
    if bases:
        signature += f"({', '.join(bases)})"

    # Get docstring
    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    # Get decorators
    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    return {
        "name": node.name,
        "type": "class",
        "signature": signature,
        "docstring": docstring,
        "decorators": decorators,
        "source_hash": source_hash,
        "line_count": end - start,
        "has_type_hints": True,  # Classes don't need return annotations
        "start_line": node.lineno,
        "end_line": end,
    }
```

**File**: `.grail/hub/check.json` (Grail manifest)

```json
{
  "name": "extract_signatures",
  "description": "Extract function and class signatures from Python files",
  "inputs": {
    "file_path": {
      "type": "string",
      "description": "Path to Python file"
    }
  },
  "externals": {
    "read_file": {
      "parameters": {
        "path": "string"
      },
      "returns": "string"
    }
  }
}
```

---

### Step 2.4: Implement Rules Engine

**File to create**: `src/remora/hub/rules.py`

```python
"""Rules Engine for Hub updates.

The Rules Engine decides what actions to take when a file changes.
It is completely deterministic - no LLM involved.

Design:
- UpdateAction is the unit of work
- RulesEngine maps file changes to actions
- ActionContext provides dependencies for execution
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from remora.hub.store import NodeStateStore


@dataclass
class ActionContext:
    """Context for executing update actions.

    Provides access to store and Grail execution.
    """

    store: "NodeStateStore"
    grail_executor: Any  # Grail script runner
    project_root: Path

    async def run_grail_script(
        self,
        script_path: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a Grail script and return results.

        Args:
            script_path: Path to .pym file (relative to .grail/)
            inputs: Input parameters for the script

        Returns:
            Script output as dict
        """
        return await self.grail_executor.run(
            script_path=script_path,
            inputs=inputs,
            externals={
                "read_file": self._read_file,
            },
        )

    async def _read_file(self, path: str) -> str:
        """External function for Grail scripts to read files."""
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = self.project_root / file_path
        return file_path.read_text(encoding="utf-8")


@dataclass
class UpdateAction(ABC):
    """Base class for update actions."""

    @abstractmethod
    async def execute(self, context: ActionContext) -> dict[str, Any]:
        """Execute the action.

        Args:
            context: ActionContext with dependencies

        Returns:
            Result dict (action-specific)
        """
        ...


@dataclass
class ExtractSignatures(UpdateAction):
    """Extract signatures from a Python file."""

    file_path: Path

    async def execute(self, context: ActionContext) -> dict[str, Any]:
        """Run the extract_signatures Grail script."""
        return await context.run_grail_script(
            "hub/extract_signatures.pym",
            {"file_path": str(self.file_path)},
        )


@dataclass
class DeleteFileNodes(UpdateAction):
    """Delete all nodes for a deleted file."""

    file_path: Path

    async def execute(self, context: ActionContext) -> dict[str, Any]:
        """Remove all nodes associated with this file."""
        deleted = await context.store.invalidate_file(str(self.file_path))
        return {
            "action": "delete_file_nodes",
            "file_path": str(self.file_path),
            "deleted": deleted,
            "count": len(deleted),
        }


@dataclass
class UpdateNodeState(UpdateAction):
    """Update a single node's state from extraction results."""

    file_path: Path
    node_data: dict[str, Any]
    file_hash: str
    update_source: str

    async def execute(self, context: ActionContext) -> dict[str, Any]:
        """Create/update NodeState from extracted data."""
        from datetime import datetime, timezone
        from remora.hub.models import NodeState

        node_key = f"node:{self.file_path}:{self.node_data['name']}"

        state = NodeState(
            key=node_key,
            file_path=str(self.file_path),
            node_name=self.node_data["name"],
            node_type=self.node_data["type"],
            source_hash=self.node_data["source_hash"],
            file_hash=self.file_hash,
            signature=self.node_data.get("signature"),
            docstring=self.node_data.get("docstring"),
            decorators=self.node_data.get("decorators", []),
            line_count=self.node_data.get("line_count"),
            has_type_hints=self.node_data.get("has_type_hints", False),
            update_source=self.update_source,
        )

        await context.store.set(state)

        return {
            "action": "update_node_state",
            "key": node_key,
            "node_type": state.node_type,
        }


class RulesEngine:
    """Decides what to recompute when a file changes.

    The rules are deterministic and do not involve any LLM calls.
    """

    def get_actions(
        self,
        change_type: str,  # "added", "modified", "deleted"
        file_path: Path,
    ) -> list[UpdateAction]:
        """Determine actions to take for a file change.

        Args:
            change_type: Type of file system change
            file_path: Path to the changed file

        Returns:
            List of UpdateAction objects to execute
        """
        actions: list[UpdateAction] = []

        if change_type == "deleted":
            # File was deleted - remove all its nodes
            actions.append(DeleteFileNodes(file_path))
            return actions

        # For added/modified: extract signatures
        # The actual node updates are handled by the daemon
        # after processing extraction results
        actions.append(ExtractSignatures(file_path))

        return actions

    def should_process_file(self, file_path: Path, ignore_patterns: list[str]) -> bool:
        """Check if a file should be processed.

        Args:
            file_path: Path to check
            ignore_patterns: List of path patterns to ignore

        Returns:
            True if file should be processed
        """
        # Only Python files
        if file_path.suffix != ".py":
            return False

        # Check ignore patterns
        path_parts = file_path.parts
        for pattern in ignore_patterns:
            if pattern in path_parts:
                return False

        # Skip hidden files
        if file_path.name.startswith("."):
            return False

        return True
```

---

### Step 2.5: Create File Watcher

**File to create**: `src/remora/hub/watcher.py`

```python
"""File watcher for the Hub daemon.

Uses watchfiles library for efficient filesystem monitoring.
Follows the pattern established by Cairn's FileWatcher.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Awaitable

from watchfiles import Change, awatch

logger = logging.getLogger(__name__)


class HubWatcher:
    """Watches a directory for Python file changes.

    Calls the provided callback when relevant files change.
    Filters out ignored directories and non-Python files.
    """

    # Default patterns to ignore
    DEFAULT_IGNORE_PATTERNS = [
        ".git",
        ".jj",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".pytest_cache",
        ".mypy_cache",
        "build",
        "dist",
        ".eggs",
        "*.egg-info",
        ".remora",  # Don't watch our own database
    ]

    def __init__(
        self,
        root: Path,
        callback: Callable[[str, Path], Awaitable[None]],
        ignore_patterns: list[str] | None = None,
    ) -> None:
        """Initialize the watcher.

        Args:
            root: Directory to watch (recursively)
            callback: Async function called with (change_type, path)
            ignore_patterns: Patterns to ignore (defaults to DEFAULT_IGNORE_PATTERNS)
        """
        self.root = root.resolve()
        self.callback = callback
        self.ignore_patterns = ignore_patterns or self.DEFAULT_IGNORE_PATTERNS
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start watching for changes.

        Blocks until stop() is called or an error occurs.
        """
        logger.info(f"Starting file watcher on {self.root}")

        async for changes in awatch(
            self.root,
            stop_event=self._stop_event,
            recursive=True,
        ):
            for change_type, path_str in changes:
                path = Path(path_str)

                # Filter out irrelevant files
                if not self._should_process(path):
                    continue

                # Map watchfiles change type to string
                change_map = {
                    Change.added: "added",
                    Change.modified: "modified",
                    Change.deleted: "deleted",
                }
                change = change_map.get(change_type, "modified")

                logger.debug(
                    "File change detected",
                    extra={"change": change, "path": str(path)}
                )

                try:
                    await self.callback(change, path)
                except Exception as e:
                    # Log but don't crash on callback errors
                    logger.error(
                        f"Error processing file change: {e}",
                        extra={"path": str(path), "change": change},
                        exc_info=True,
                    )

    def stop(self) -> None:
        """Stop watching."""
        logger.info("Stopping file watcher")
        self._stop_event.set()

    def _should_process(self, path: Path) -> bool:
        """Check if a file should be processed.

        Args:
            path: Absolute path to the file

        Returns:
            True if the file should trigger an update
        """
        # Only Python files
        if path.suffix != ".py":
            return False

        # Check path against ignore patterns
        try:
            rel_parts = path.relative_to(self.root).parts
        except ValueError:
            # Path outside root (shouldn't happen)
            return False

        for pattern in self.ignore_patterns:
            # Check each path component
            if pattern in rel_parts:
                return False
            # Also check if pattern matches filename (for wildcards)
            if pattern.startswith("*") and path.name.endswith(pattern[1:]):
                return False

        # Skip hidden files/directories
        if any(part.startswith(".") for part in rel_parts):
            return False

        return True
```

---

### Step 2.6: Implement Hub Daemon

**File to create**: `src/remora/hub/daemon.py`

```python
"""Hub daemon implementation.

The main daemon that coordinates watching, indexing, and serving.
Runs as a background process, communicating via shared workspace.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fsdantic import Fsdantic, Workspace

from remora.hub.models import NodeState, FileIndex, HubStatus
from remora.hub.store import NodeStateStore
from remora.hub.rules import RulesEngine, ActionContext, ExtractSignatures
from remora.hub.watcher import HubWatcher

logger = logging.getLogger(__name__)


class HubDaemon:
    """The Node State Hub background daemon.

    Responsibilities:
    - Watch filesystem for Python file changes
    - Index files on cold start
    - Update NodeState records via Grail scripts
    - Maintain status for client health checks
    """

    def __init__(
        self,
        project_root: Path,
        db_path: Path | None = None,
        grail_executor: Any = None,
    ) -> None:
        """Initialize the daemon.

        Args:
            project_root: Root directory to watch
            db_path: Path to hub.db (default: {project_root}/.remora/hub.db)
            grail_executor: Grail script executor (optional)
        """
        self.project_root = project_root.resolve()
        self.db_path = db_path or (self.project_root / ".remora" / "hub.db")
        self.grail_executor = grail_executor

        self.workspace: Workspace | None = None
        self.store: NodeStateStore | None = None
        self.watcher: HubWatcher | None = None
        self.rules = RulesEngine()

        self._shutdown_event = asyncio.Event()
        self._started_at: datetime | None = None

    async def run(self) -> None:
        """Main daemon loop.

        Blocks until shutdown signal received.
        """
        logger.info(f"Hub daemon starting for {self.project_root}")

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Open workspace
        self.workspace = await Fsdantic.open(path=str(self.db_path))
        self.store = NodeStateStore(self.workspace)

        # Write PID file
        self._write_pid_file()

        # Set up signal handlers
        self._setup_signals()

        # Update status
        self._started_at = datetime.now(timezone.utc)
        await self._update_status(running=True)

        try:
            # Cold start: index changed files
            await self._cold_start_index()

            # Create watcher
            self.watcher = HubWatcher(
                self.project_root,
                self._handle_file_change,
            )

            # Run watcher until shutdown
            logger.info("Hub daemon ready, watching for changes")
            await self.watcher.start()

        except asyncio.CancelledError:
            logger.info("Hub daemon received shutdown signal")
        finally:
            await self._shutdown()

    async def _cold_start_index(self) -> None:
        """Index files that changed since last shutdown."""
        logger.info("Cold start: checking for changed files...")

        indexed = 0
        errors = 0

        for py_file in self.project_root.rglob("*.py"):
            if not self.rules.should_process_file(py_file, HubWatcher.DEFAULT_IGNORE_PATTERNS):
                continue

            try:
                # Check if file changed since last index
                file_hash = self._hash_file(py_file)
                existing = await self.store.get_file_index(str(py_file))

                if existing and existing.file_hash == file_hash:
                    continue  # No changes

                await self._index_file(py_file, "cold_start")
                indexed += 1

            except Exception as e:
                logger.warning(f"Failed to index {py_file}: {e}")
                errors += 1

        # Update status
        stats = await self.store.stats()
        await self._update_status(
            running=True,
            indexed_files=stats["files"],
            indexed_nodes=stats["nodes"],
        )

        logger.info(
            f"Cold start complete: indexed {indexed} files, {errors} errors",
            extra={"indexed": indexed, "errors": errors}
        )

    async def _handle_file_change(self, change_type: str, path: Path) -> None:
        """Handle a file change event from watcher.

        Args:
            change_type: "added", "modified", or "deleted"
            path: Absolute path to changed file
        """
        logger.debug(f"Processing {change_type}: {path}")

        # Get actions from rules engine
        actions = self.rules.get_actions(change_type, path)

        # Create context for action execution
        context = ActionContext(
            store=self.store,
            grail_executor=self.grail_executor,
            project_root=self.project_root,
        )

        # Execute actions
        for action in actions:
            try:
                result = await action.execute(context)

                # Handle extraction results
                if isinstance(action, ExtractSignatures) and "nodes" in result:
                    await self._process_extraction_result(
                        path,
                        result,
                        update_source="file_change",
                    )

            except Exception as e:
                logger.error(f"Action failed for {path}: {e}", exc_info=True)

        # Update status timestamp
        await self._update_status(running=True)

    async def _index_file(self, path: Path, update_source: str) -> None:
        """Index a single file.

        Args:
            path: Path to Python file
            update_source: Source of update ("cold_start", "file_change", etc.)
        """
        context = ActionContext(
            store=self.store,
            grail_executor=self.grail_executor,
            project_root=self.project_root,
        )

        # Run extraction
        action = ExtractSignatures(path)
        result = await action.execute(context)

        if result.get("error"):
            logger.warning(f"Extraction failed for {path}: {result['error']}")
            return

        await self._process_extraction_result(path, result, update_source)

    async def _process_extraction_result(
        self,
        path: Path,
        result: dict[str, Any],
        update_source: str,
    ) -> None:
        """Process extraction results and store nodes.

        Args:
            path: Source file path
            result: Output from extract_signatures script
            update_source: Source of update
        """
        file_hash = result["file_hash"]
        nodes = result.get("nodes", [])

        # First, invalidate existing nodes for this file
        await self.store.invalidate_file(str(path))

        # Store each extracted node
        now = datetime.now(timezone.utc)
        for node_data in nodes:
            node_key = f"node:{path}:{node_data['name']}"

            state = NodeState(
                key=node_key,
                file_path=str(path),
                node_name=node_data["name"],
                node_type=node_data["type"],
                source_hash=node_data["source_hash"],
                file_hash=file_hash,
                signature=node_data.get("signature"),
                docstring=node_data.get("docstring"),
                decorators=node_data.get("decorators", []),
                line_count=node_data.get("line_count"),
                has_type_hints=node_data.get("has_type_hints", False),
                update_source=update_source,
            )

            await self.store.set(state)

        # Update file index
        await self.store.set_file_index(FileIndex(
            file_path=str(path),
            file_hash=file_hash,
            node_count=len(nodes),
            last_scanned=now,
        ))

        logger.debug(
            f"Indexed {path}: {len(nodes)} nodes",
            extra={"file_path": str(path), "node_count": len(nodes)}
        )

    async def _update_status(
        self,
        running: bool,
        indexed_files: int | None = None,
        indexed_nodes: int | None = None,
    ) -> None:
        """Update Hub status record."""
        existing = await self.store.get_status()

        status = HubStatus(
            running=running,
            pid=os.getpid(),
            project_root=str(self.project_root),
            indexed_files=indexed_files or (existing.indexed_files if existing else 0),
            indexed_nodes=indexed_nodes or (existing.indexed_nodes if existing else 0),
            started_at=self._started_at,
            last_update=datetime.now(timezone.utc),
        )

        await self.store.set_status(status)

    async def _shutdown(self) -> None:
        """Clean shutdown."""
        logger.info("Hub daemon shutting down")

        # Stop watcher
        if self.watcher:
            self.watcher.stop()

        # Update status
        if self.store:
            await self._update_status(running=False)

        # Close workspace
        if self.workspace:
            await self.workspace.close()

        # Remove PID file
        self._remove_pid_file()

        logger.info("Hub daemon stopped")

    def _setup_signals(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(self._signal_handler()),
            )

    async def _signal_handler(self) -> None:
        """Handle shutdown signal."""
        logger.info("Received shutdown signal")
        if self.watcher:
            self.watcher.stop()

    def _write_pid_file(self) -> None:
        """Write PID file for daemon detection."""
        pid_file = self.db_path.parent / "hub.pid"
        pid_file.write_text(str(os.getpid()))
        logger.debug(f"Wrote PID file: {pid_file}")

    def _remove_pid_file(self) -> None:
        """Remove PID file on shutdown."""
        pid_file = self.db_path.parent / "hub.pid"
        if pid_file.exists():
            pid_file.unlink()
            logger.debug(f"Removed PID file: {pid_file}")

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Compute SHA256 hash of file contents."""
        try:
            content = path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except OSError:
            return ""
```

---

### Step 2.7: Implement HubClient

**File to update**: `src/remora/context/hub_client.py`

Replace the stub with the full implementation:

```python
"""Hub client for Pull Hook integration.

This client reads directly from the Hub workspace (no IPC).
Implements the "Lazy Daemon" pattern for graceful degradation.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from fsdantic import Fsdantic, Workspace

if TYPE_CHECKING:
    from remora.hub.models import NodeState
    from remora.hub.store import NodeStateStore

logger = logging.getLogger(__name__)


class HubClient:
    """Client for reading Hub context.

    Design: "Lazy Daemon" pattern
    - If Hub is fresh, read directly from workspace
    - If Hub is stale and daemon running, warn but proceed
    - If Hub is stale and daemon not running, do ad-hoc index

    This provides graceful degradation when the daemon isn't running
    while still giving optimal performance when it is.
    """

    # How old can data be before we consider it stale (seconds)
    STALE_THRESHOLD_SECONDS = 5.0

    # Max files to ad-hoc index (to avoid blocking)
    MAX_ADHOC_FILES = 5

    def __init__(
        self,
        hub_db_path: Path | None = None,
        project_root: Path | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            hub_db_path: Path to hub.db (default: auto-discover)
            project_root: Project root for ad-hoc indexing
        """
        self.hub_db_path = hub_db_path
        self.project_root = project_root

        self._workspace: Workspace | None = None
        self._store: "NodeStateStore | None" = None
        self._available: bool | None = None

    async def get_context(self, node_ids: list[str]) -> dict[str, "NodeState"]:
        """Get context for nodes with lazy fallback.

        Args:
            node_ids: List of node keys to fetch

        Returns:
            Dict mapping node IDs to NodeState objects.
            Missing nodes are omitted (graceful degradation).
        """
        if not await self._is_available():
            return {}

        await self._ensure_workspace()

        # Check freshness
        stale_files = await self._check_freshness(node_ids)

        if stale_files:
            if await self._daemon_running():
                # Daemon is running, it will update soon
                logger.debug(
                    "Hub has stale data, daemon running - proceeding",
                    extra={"stale_files": len(stale_files)}
                )
            else:
                # No daemon - do ad-hoc indexing
                logger.warning(
                    "Hub daemon not running - performing ad-hoc index",
                    extra={"stale_files": len(stale_files)}
                )
                await self._adhoc_index(stale_files)

        return await self._store.get_many(node_ids)

    async def health_check(self) -> dict[str, any]:
        """Check Hub health status.

        Returns:
            Dict with health information
        """
        if not await self._is_available():
            return {"available": False, "reason": "Hub database not found"}

        await self._ensure_workspace()

        status = await self._store.get_status()
        stats = await self._store.stats()

        return {
            "available": True,
            "daemon_running": await self._daemon_running(),
            "indexed_files": stats["files"],
            "indexed_nodes": stats["nodes"],
            "last_update": status.last_update.isoformat() if status and status.last_update else None,
        }

    async def close(self) -> None:
        """Close the workspace connection."""
        if self._workspace is not None:
            await self._workspace.close()
            self._workspace = None
            self._store = None

    # === Private Methods ===

    async def _is_available(self) -> bool:
        """Check if Hub database exists."""
        if self._available is not None:
            return self._available

        # Auto-discover hub.db path
        if self.hub_db_path is None:
            self.hub_db_path = self._discover_hub_db()

        if self.hub_db_path is None or not self.hub_db_path.exists():
            self._available = False
            return False

        self._available = True
        return True

    def _discover_hub_db(self) -> Path | None:
        """Discover hub.db in current or parent directories."""
        # Start from project root or CWD
        start = self.project_root or Path.cwd()

        # Look for .remora/hub.db
        for parent in [start] + list(start.parents):
            hub_path = parent / ".remora" / "hub.db"
            if hub_path.exists():
                self.project_root = parent
                return hub_path

        return None

    async def _ensure_workspace(self) -> None:
        """Open workspace if not already open."""
        if self._workspace is not None:
            return

        # Import here to avoid circular dependency
        from remora.hub.store import NodeStateStore

        self._workspace = await Fsdantic.open(path=str(self.hub_db_path))
        self._store = NodeStateStore(self._workspace)

    async def _check_freshness(self, node_ids: list[str]) -> list[Path]:
        """Check which files are stale and need re-indexing.

        Args:
            node_ids: Node IDs to check

        Returns:
            List of file paths that are stale
        """
        stale: list[Path] = []
        seen_files: set[str] = set()

        for node_id in node_ids:
            file_path_str = self._node_id_to_path(node_id)
            if file_path_str in seen_files:
                continue
            seen_files.add(file_path_str)

            file_path = Path(file_path_str)
            if not file_path.exists():
                continue

            # Get file index
            index = await self._store.get_file_index(file_path_str)

            if index is None:
                # File not indexed at all
                stale.append(file_path)
            elif file_path.stat().st_mtime > index.last_scanned.timestamp():
                # File modified since last index
                stale.append(file_path)

        return stale

    async def _daemon_running(self) -> bool:
        """Check if Hub daemon is currently running."""
        if self.hub_db_path is None:
            return False

        pid_file = self.hub_db_path.parent / "hub.pid"
        if not pid_file.exists():
            return False

        # Check if PID is still valid
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Signal 0 checks if process exists
            return True
        except (ValueError, OSError):
            return False

    async def _adhoc_index(self, files: list[Path]) -> None:
        """Perform minimal ad-hoc indexing for critical files.

        This is a fallback when the daemon isn't running.
        Limited to MAX_ADHOC_FILES to avoid blocking.

        Args:
            files: List of files that need indexing
        """
        from remora.hub.indexer import index_file_simple

        indexed = 0
        for file_path in files[:self.MAX_ADHOC_FILES]:
            try:
                await index_file_simple(file_path, self._store)
                indexed += 1
            except Exception as e:
                logger.warning(f"Ad-hoc index failed for {file_path}: {e}")

        if indexed > 0:
            logger.info(f"Ad-hoc indexed {indexed} files")

    @staticmethod
    def _node_id_to_path(node_id: str) -> str:
        """Extract file path from node ID.

        Node ID format: "node:{file_path}:{node_name}"
        """
        if node_id.startswith("node:"):
            parts = node_id[5:].rsplit(":", 1)
            if parts:
                return parts[0]
        return node_id


# === Module-level singleton ===

_hub_client: HubClient | None = None


def get_hub_client() -> HubClient:
    """Get the Hub client singleton.

    Creates a new client on first call.
    """
    global _hub_client
    if _hub_client is None:
        _hub_client = HubClient()
    return _hub_client


async def close_hub_client() -> None:
    """Close the Hub client singleton."""
    global _hub_client
    if _hub_client is not None:
        await _hub_client.close()
        _hub_client = None
```

---

### Step 2.8: Wire Pull Hook

**File to update**: `src/remora/context/manager.py`

Update the `pull_hub_context` method to use the real client:

```python
# In ContextManager class

async def pull_hub_context(self) -> None:
    """Pull fresh context from Hub.

    This is the Pull Hook - called at the start of each turn
    to inject external context into the Decision Packet.

    Uses the "Lazy Daemon" pattern:
    - If Hub daemon is running, reads fresh data
    - If not running, performs ad-hoc indexing for critical files
    - If Hub not available at all, gracefully degrades (empty context)
    """
    from remora.context.hub_client import get_hub_client

    if self._hub_client is None:
        self._hub_client = get_hub_client()

    try:
        # Request context for our target node
        context = await self._hub_client.get_context([self.packet.node_id])

        if context:
            node_state = context.get(self.packet.node_id)
            if node_state:
                # Inject Hub context into packet
                self.packet.hub_context = {
                    "signature": node_state.signature,
                    "docstring": node_state.docstring,
                    "decorators": node_state.decorators,
                    "related_tests": node_state.related_tests,
                    "complexity": node_state.complexity,
                    "callers": node_state.callers,
                    "has_type_hints": node_state.has_type_hints,
                }
                self.packet.hub_freshness = datetime.fromtimestamp(
                    node_state.updated_at,
                    tz=timezone.utc
                )

    except Exception as e:
        # Graceful degradation - Hub is optional
        logger.debug(f"Failed to pull Hub context: {e}")
```

---

### Step 2.9: Create CLI Entry Point

**File to create**: `src/remora/hub/cli.py`

```python
"""CLI entry point for the Hub daemon.

Usage:
    remora-hub start [--project-root PATH]
    remora-hub status
    remora-hub stop
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import click

from remora.hub.daemon import HubDaemon


@click.group()
def cli():
    """Remora Hub daemon management."""
    pass


@cli.command()
@click.option(
    "--project-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    help="Project root directory to watch",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to hub.db (default: {project-root}/.remora/hub.db)",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Logging level",
)
@click.option(
    "--foreground/--background",
    default=True,
    help="Run in foreground (default) or background",
)
def start(
    project_root: Path,
    db_path: Path | None,
    log_level: str,
    foreground: bool,
) -> None:
    """Start the Hub daemon."""
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not foreground:
        # Daemonize
        _daemonize()

    # Create and run daemon
    daemon = HubDaemon(
        project_root=project_root,
        db_path=db_path,
    )

    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        pass


@cli.command()
@click.option(
    "--project-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    help="Project root directory",
)
def status(project_root: Path) -> None:
    """Check Hub daemon status."""
    from fsdantic import Fsdantic
    from remora.hub.store import NodeStateStore

    hub_path = project_root / ".remora" / "hub.db"
    pid_file = project_root / ".remora" / "hub.pid"

    if not hub_path.exists():
        click.echo("Hub: not initialized")
        click.echo(f"  Run 'remora-hub start' to initialize")
        return

    # Check daemon
    daemon_running = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            daemon_running = True
        except (ValueError, OSError):
            pass

    # Get stats
    async def get_stats():
        workspace = await Fsdantic.open(path=str(hub_path))
        store = NodeStateStore(workspace)
        stats = await store.stats()
        status_obj = await store.get_status()
        await workspace.close()
        return stats, status_obj

    stats, status_obj = asyncio.run(get_stats())

    click.echo(f"Hub: {'running' if daemon_running else 'stopped'}")
    click.echo(f"  Database: {hub_path}")
    click.echo(f"  Files indexed: {stats['files']}")
    click.echo(f"  Nodes indexed: {stats['nodes']}")
    if status_obj and status_obj.last_update:
        click.echo(f"  Last update: {status_obj.last_update.isoformat()}")


@cli.command()
@click.option(
    "--project-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    help="Project root directory",
)
def stop(project_root: Path) -> None:
    """Stop the Hub daemon."""
    pid_file = project_root / ".remora" / "hub.pid"

    if not pid_file.exists():
        click.echo("Hub daemon not running")
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Sent SIGTERM to Hub daemon (PID {pid})")
    except ValueError:
        click.echo("Invalid PID file")
    except OSError as e:
        click.echo(f"Failed to stop daemon: {e}")


def _daemonize() -> None:
    """Daemonize the process (Unix only)."""
    if os.name != "posix":
        raise click.ClickException("Background mode only supported on Unix")

    # First fork
    if os.fork() > 0:
        sys.exit(0)

    # Become session leader
    os.setsid()

    # Second fork
    if os.fork() > 0:
        sys.exit(0)

    # Redirect standard file descriptors
    sys.stdin = open(os.devnull, "r")
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")


def main() -> None:
    """Entry point for remora-hub command."""
    cli()


if __name__ == "__main__":
    main()
```

**Add to pyproject.toml**:

```toml
[project.scripts]
remora-hub = "remora.hub.cli:main"
```

---

## Testing Strategy

### Unit Tests

| Module | Test File | Focus |
|--------|-----------|-------|
| `models.py` | `test_models.py` | Pydantic validation, serialization |
| `store.py` | `test_store.py` | CRUD operations, batch queries |
| `rules.py` | `test_rules.py` | Action generation logic |
| `watcher.py` | `test_watcher.py` | File filtering |
| `hub_client.py` | `test_hub_client.py` | Lazy daemon pattern |

### Integration Tests

```python
# tests/hub/test_integration.py

@pytest.mark.asyncio
async def test_end_to_end_indexing(tmp_path: Path):
    """Test full cycle: daemon indexes file, client reads."""
    # Create test Python file
    test_file = tmp_path / "test_module.py"
    test_file.write_text('''
def hello(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}"
''')

    # Start daemon
    daemon = HubDaemon(project_root=tmp_path)
    daemon_task = asyncio.create_task(daemon.run())

    # Wait for cold start
    await asyncio.sleep(1)

    # Create client and fetch
    client = HubClient(
        hub_db_path=tmp_path / ".remora" / "hub.db",
        project_root=tmp_path,
    )

    context = await client.get_context([f"node:{test_file}:hello"])

    assert len(context) == 1
    node = context[f"node:{test_file}:hello"]
    assert node.signature == "def hello(name: str) -> str"
    assert node.docstring == "Greet someone."

    # Cleanup
    daemon.watcher.stop()
    await client.close()
```

---

## Migration Checklist

### Phase 2 Completion

- [ ] Hub models created (`src/remora/hub/models.py`)
- [ ] NodeStateStore implemented (`src/remora/hub/store.py`)
- [ ] Grail scripts created (`.grail/hub/`)
- [ ] Rules engine implemented (`src/remora/hub/rules.py`)
- [ ] File watcher working (`src/remora/hub/watcher.py`)
- [ ] Hub daemon running (`src/remora/hub/daemon.py`)
- [ ] HubClient with lazy daemon (`src/remora/context/hub_client.py`)
- [ ] Pull Hook wired (`src/remora/context/manager.py`)
- [ ] CLI entry point (`src/remora/hub/cli.py`)
- [ ] Unit tests passing
- [ ] Integration test: start daemon, run Remora, verify context

---

## Appendix: Library APIs

### FSdantic (Key APIs)

```python
from fsdantic import (
    Fsdantic,              # Entry point
    Workspace,             # Facade around AgentFS
    TypedKVRepository,     # Type-safe KV operations
    VersionedKVRecord,     # Base class with versioning
    KVRecord,              # Base class with timestamps
    KVConflictError,       # Raised on version conflict
)

# Opening workspaces
workspace = await Fsdantic.open(path="/path/to/db.db")
workspace = await Fsdantic.open(id="my-agent")

# KV Manager
kv = workspace.kv
await kv.set("key", {"value": 123})
value = await kv.get("key")
await kv.delete("key")
items = await kv.list(prefix="node:")

# Typed Repository
repo = workspace.kv.repository(prefix="node:", model_type=NodeState)
await repo.save("key", node_state)       # Handles versioning
state = await repo.load("key")           # Returns NodeState | None
await repo.delete("key")
all_states = await repo.list_all()       # Returns list[NodeState]
await repo.save_many([(k, v), ...])      # Batch save
result = await repo.load_many([k1, k2])  # BatchResult

# Closing
await workspace.close()
```

### Grail (Key APIs)

```python
import grail

# Load script
script = grail.load("path/to/script.pym")

# Check syntax/types
check_result = script.check()
if not check_result.valid:
    print(check_result.errors)

# Run script
result = await script.run(
    inputs={"file_path": "/path/to/file.py"},
    externals={"read_file": my_read_file_impl},
    limits=grail.DEFAULT,
)
```

### watchfiles (Key APIs)

```python
from watchfiles import awatch, Change

# Watch directory
async for changes in awatch("/path/to/dir"):
    for change_type, path in changes:
        if change_type == Change.added:
            print(f"Added: {path}")
        elif change_type == Change.modified:
            print(f"Modified: {path}")
        elif change_type == Change.deleted:
            print(f"Deleted: {path}")
```

---

## End of Guide

This guide provides a complete roadmap for implementing the Node State Hub v2. The key differences from v1:

1. **No IPC** - Direct FSdantic workspace access
2. **FSdantic-native** - TypedKVRepository instead of raw SQL
3. **Lazy Daemon** - Graceful degradation when daemon not running
4. **Simpler architecture** - ~50% less code

Follow the steps in order, ensuring tests pass at each checkpoint.
