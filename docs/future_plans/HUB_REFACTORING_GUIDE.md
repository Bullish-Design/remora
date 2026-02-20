# Hub Refactoring Guide

> **Version**: 1.0
> **Target**: Remora Library
> **Phases**: Node State Hub (Phase 2)

This guide provides step-by-step instructions for implementing the Node State Hub concept in Remora. It is designed to be followed by developers who are new to the codebase.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Phase 2: Node State Hub](#phase-2-node-state-hub)
   - [Step 2.1: Create Hub Models](#step-21-create-hub-models)
   - [Step 2.2: Implement NodeStateKV](#step-22-implement-nodestekv)
   - [Step 2.3: Create Analysis Scripts](#step-23-create-analysis-scripts)
   - [Step 2.4: Implement Rules Engine](#step-24-implement-rules-engine)
   - [Step 2.5: Create File Watcher](#step-25-create-file-watcher)
   - [Step 2.6: Implement IPC Server](#step-26-implement-ipc-server)
   - [Step 2.7: Create Hub Daemon](#step-27-create-hub-daemon)
   - [Step 2.8: Implement HubClient](#step-28-implement-hubclient)
   - [Step 2.9: Wire Pull Hook](#step-29-wire-pull-hook)
3. [Migration Checklist](#migration-checklist)
4. [Appendix: Library APIs](#appendix-library-apis)

---

## Prerequisites

### Required Knowledge

- Python 3.11+ (async/await, type hints)
- Pydantic v2 (BaseModel, Field, validation)
- Basic understanding of event sourcing patterns

### Codebase Orientation

Before starting, familiarize yourself with these files:

| File | Purpose |
|------|---------|
| `remora/runner.py` | FunctionGemmaRunner - the agent execution loop |
| `remora/events.py` | Event emission infrastructure (Long Track exists here) |
| `remora/subagent.py` | SubagentDefinition and tool loading |
| `remora/orchestrator.py` | Coordinator that manages agent runs |
| `agents/*/tools/*.pym` | Grail tool scripts |

### Key Dependencies

| Library | Location | Purpose |
|---------|----------|---------|
| `grail` | `.context/grail/` | Script execution framework |
| `fsdantic` | `.context/fsdantic/` | Typed KV storage |
| `pydantic` | (installed) | Data validation |
| `watchfiles` | (to install) | File system watching |

---

## Phase 2: Node State Hub

**Goal**: Implement the background daemon that maintains a live index of codebase metadata.

**Prerequisites**: Phase 1 complete (Pull Hook stub exists)

---

### Step 2.1: Create Hub Models

**File to create**: `remora/hub/models.py`

```python
"""Node State Hub data models.

These models define the structure of metadata stored and
served by the Hub daemon.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NodeState(BaseModel):
    """State for a single code node.

    This is what the Hub stores and serves to clients.
    """

    # === Identity ===
    key: str
    """Unique key: 'node:{file_path}:{node_name}'"""

    file_path: str
    """Absolute path to the file containing this node."""

    node_name: str
    """Name of the function, class, or module."""

    node_type: Literal["function", "class", "module"]
    """Type of code node."""

    # === Content Hashes (for change detection) ===
    source_hash: str
    """SHA256 of the node's source code."""

    file_hash: str
    """SHA256 of the entire file."""

    # === Static Analysis Results ===
    signature: str | None = None
    """Function/class signature: 'def foo(x: int) -> str'"""

    docstring: str | None = None
    """First line of docstring (truncated)."""

    imports: list[str] = Field(default_factory=list)
    """List of imports used by this node."""

    decorators: list[str] = Field(default_factory=list)
    """List of decorators: ['@staticmethod', '@cached']"""

    # === Cross-File Analysis (Expensive, Lazy) ===
    callers: list[str] | None = None
    """Nodes that call this node: ['bar.py:process']"""

    callees: list[str] | None = None
    """Nodes this calls: ['os.path.join']"""

    # === Test Discovery ===
    related_tests: list[str] | None = None
    """Test functions that exercise this node."""

    # === Quality Metrics ===
    line_count: int | None = None
    """Number of lines in this node."""

    complexity: int | None = None
    """Cyclomatic complexity score."""

    # === Flags ===
    docstring_outdated: bool = False
    """True if signature changed but docstring didn't."""

    has_type_hints: bool = True
    """True if function has type annotations."""

    # === Freshness ===
    last_updated: datetime
    """When this state was last computed."""

    update_source: Literal["file_change", "dependency_change", "manual", "cold_start"]
    """What triggered this update."""


class FileIndex(BaseModel):
    """Tracking entry for a source file."""

    file_path: str
    """Absolute path to the file."""

    file_hash: str
    """SHA256 of file contents."""

    node_count: int
    """Number of nodes extracted from this file."""

    last_scanned: datetime
    """When this file was last scanned."""


class HubStatus(BaseModel):
    """Status information from the Hub."""

    running: bool
    """Whether the Hub daemon is running."""

    root_path: str
    """Project root being watched."""

    indexed_files: int
    """Number of files in the index."""

    indexed_nodes: int
    """Number of nodes in the index."""

    uptime_seconds: float
    """How long the Hub has been running."""

    last_update: datetime | None
    """When the index was last updated."""
```

**Testing (Step 2.1)**:

```python
"""Tests for Hub models."""

import pytest
from datetime import datetime
from remora.hub.models import NodeState, FileIndex, HubStatus


class TestNodeState:
    def test_create_function_node(self):
        state = NodeState(
            key="node:foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            signature="def bar(x: int) -> str",
            last_updated=datetime.now(),
            update_source="file_change",
        )

        assert state.node_type == "function"
        assert state.signature == "def bar(x: int) -> str"

    def test_serializes_to_json(self):
        state = NodeState(
            key="node:foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            last_updated=datetime.now(),
            update_source="cold_start",
        )

        json_str = state.model_dump_json()
        assert "foo.py" in json_str
```

---

### Step 2.2: Implement NodeStateKV

**File to create**: `remora/hub/storage.py`

This uses fsdantic for SQLite-backed storage.

```python
"""Node State KV storage using fsdantic.

This module provides persistent storage for NodeState objects
using fsdantic's TypedKVRepository.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from remora.hub.models import NodeState, FileIndex


class NodeStateKV:
    """SQLite-backed storage for NodeState.

    This is a lightweight wrapper around SQLite that stores
    NodeState objects as JSON blobs.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the KV store.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")  # Concurrent reads
        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS node_state (
                key TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                node_name TEXT NOT NULL,
                node_type TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                state_json TEXT NOT NULL,
                last_updated REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_file_path
            ON node_state(file_path);

            CREATE INDEX IF NOT EXISTS idx_last_updated
            ON node_state(last_updated);

            CREATE TABLE IF NOT EXISTS file_index (
                file_path TEXT PRIMARY KEY,
                file_hash TEXT NOT NULL,
                node_count INTEGER NOT NULL,
                last_scanned REAL NOT NULL
            );
        """)
        self._conn.commit()

    def get(self, key: str) -> NodeState | None:
        """Get a NodeState by key."""
        cursor = self._conn.execute(
            "SELECT state_json FROM node_state WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return NodeState.model_validate_json(row[0])

    def get_many(self, keys: list[str]) -> dict[str, NodeState]:
        """Get multiple NodeStates by keys."""
        if not keys:
            return {}

        placeholders = ",".join("?" * len(keys))
        cursor = self._conn.execute(
            f"SELECT key, state_json FROM node_state WHERE key IN ({placeholders})",
            keys,
        )

        result = {}
        for row in cursor:
            key, state_json = row
            result[key] = NodeState.model_validate_json(state_json)
        return result

    def set(self, state: NodeState) -> None:
        """Store a NodeState."""
        self._conn.execute(
            """INSERT OR REPLACE INTO node_state
               (key, file_path, node_name, node_type, source_hash, state_json, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                state.key,
                state.file_path,
                state.node_name,
                state.node_type,
                state.source_hash,
                state.model_dump_json(),
                state.last_updated.timestamp(),
            ),
        )
        self._conn.commit()

    def delete(self, key: str) -> bool:
        """Delete a NodeState by key."""
        cursor = self._conn.execute(
            "DELETE FROM node_state WHERE key = ?",
            (key,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get_by_file(self, file_path: str) -> list[NodeState]:
        """Get all NodeStates for a file."""
        cursor = self._conn.execute(
            "SELECT state_json FROM node_state WHERE file_path = ?",
            (file_path,),
        )
        return [NodeState.model_validate_json(row[0]) for row in cursor]

    def invalidate_file(self, file_path: str) -> list[str]:
        """Remove all nodes for a file, return deleted keys."""
        cursor = self._conn.execute(
            "SELECT key FROM node_state WHERE file_path = ?",
            (file_path,),
        )
        deleted = [row[0] for row in cursor]

        self._conn.execute(
            "DELETE FROM node_state WHERE file_path = ?",
            (file_path,),
        )
        self._conn.commit()
        return deleted

    def gc_orphans(self, max_age_hours: int = 24) -> int:
        """Remove stale entries older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        cursor = self._conn.execute(
            "DELETE FROM node_state WHERE last_updated < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cursor.rowcount

    # --- File Index Methods ---

    def get_file_index(self, file_path: str) -> FileIndex | None:
        """Get file index entry."""
        cursor = self._conn.execute(
            "SELECT file_hash, node_count, last_scanned FROM file_index WHERE file_path = ?",
            (file_path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return FileIndex(
            file_path=file_path,
            file_hash=row[0],
            node_count=row[1],
            last_scanned=datetime.fromtimestamp(row[2], tz=timezone.utc),
        )

    def set_file_index(self, index: FileIndex) -> None:
        """Store file index entry."""
        self._conn.execute(
            """INSERT OR REPLACE INTO file_index
               (file_path, file_hash, node_count, last_scanned)
               VALUES (?, ?, ?, ?)""",
            (
                index.file_path,
                index.file_hash,
                index.node_count,
                index.last_scanned.timestamp(),
            ),
        )
        self._conn.commit()

    def stats(self) -> dict[str, int]:
        """Get storage statistics."""
        node_count = self._conn.execute(
            "SELECT COUNT(*) FROM node_state"
        ).fetchone()[0]
        file_count = self._conn.execute(
            "SELECT COUNT(*) FROM file_index"
        ).fetchone()[0]
        return {"nodes": node_count, "files": file_count}

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
```

**Testing (Step 2.2)**:

```python
"""Tests for NodeStateKV."""

import pytest
from datetime import datetime, timezone
from pathlib import Path
from remora.hub.storage import NodeStateKV
from remora.hub.models import NodeState


@pytest.fixture
def kv_store(tmp_path):
    """Create a temporary KV store."""
    db_path = tmp_path / "test.db"
    store = NodeStateKV(db_path)
    yield store
    store.close()


class TestNodeStateKV:
    def test_set_and_get(self, kv_store):
        state = NodeState(
            key="node:foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            last_updated=datetime.now(timezone.utc),
            update_source="file_change",
        )

        kv_store.set(state)
        retrieved = kv_store.get("node:foo.py:bar")

        assert retrieved is not None
        assert retrieved.node_name == "bar"
        assert retrieved.source_hash == "abc123"

    def test_get_missing_returns_none(self, kv_store):
        result = kv_store.get("nonexistent")
        assert result is None

    def test_invalidate_file_removes_all_nodes(self, kv_store):
        # Add multiple nodes for same file
        for name in ["foo", "bar", "baz"]:
            state = NodeState(
                key=f"node:test.py:{name}",
                file_path="/project/test.py",
                node_name=name,
                node_type="function",
                source_hash=f"hash_{name}",
                file_hash="file_hash",
                last_updated=datetime.now(timezone.utc),
                update_source="file_change",
            )
            kv_store.set(state)

        deleted = kv_store.invalidate_file("/project/test.py")

        assert len(deleted) == 3
        assert kv_store.get("node:test.py:foo") is None
```

---

### Step 2.3: Create Analysis Scripts

**Directory to create**: `agents/hub/tools/`

Create Grail scripts for static analysis.

**File**: `agents/hub/tools/extract_signatures.pym`

```python
"""Extract function/class signatures from a Python file.

This script parses a Python file and extracts metadata for
all functions and classes.
"""

from grail import Input, external
from typing import Any
import ast
import hashlib

file_path: str = Input("file_path")

@external
async def read_file(path: str) -> str:
    """Read file contents."""
    ...


async def main() -> dict[str, Any]:
    """Extract signatures from the file."""
    content = await read_file(file_path)
    file_hash = hashlib.sha256(content.encode()).hexdigest()

    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return {
            "error": f"Syntax error: {e}",
            "file_path": file_path,
        }

    nodes = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            nodes.append(_extract_function(node, content))
        elif isinstance(node, ast.AsyncFunctionDef):
            nodes.append(_extract_function(node, content, is_async=True))
        elif isinstance(node, ast.ClassDef):
            nodes.append(_extract_class(node, content))

    return {
        "file_path": file_path,
        "file_hash": file_hash,
        "nodes": nodes,
    }


def _extract_function(node: ast.FunctionDef, source: str, is_async: bool = False) -> dict:
    """Extract function metadata."""
    # Get source lines for this function
    lines = source.splitlines()
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

    returns = ""
    if node.returns:
        returns = f" -> {ast.unparse(node.returns)}"

    prefix = "async def" if is_async else "def"
    signature = f"{prefix} {node.name}({', '.join(args)}){returns}"

    # Get docstring
    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]  # First line, truncated

    # Get decorators
    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    return {
        "name": node.name,
        "type": "function",
        "signature": signature,
        "docstring": docstring,
        "decorators": decorators,
        "source_hash": source_hash,
        "line_count": end - start,
        "has_type_hints": node.returns is not None or any(a.annotation for a in node.args.args),
    }


def _extract_class(node: ast.ClassDef, source: str) -> dict:
    """Extract class metadata."""
    lines = source.splitlines()
    start = node.lineno - 1
    end = node.end_lineno or start + 1
    class_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(class_source.encode()).hexdigest()

    # Build signature
    bases = [ast.unparse(b) for b in node.bases]
    signature = f"class {node.name}"
    if bases:
        signature += f"({', '.join(bases)})"

    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    return {
        "name": node.name,
        "type": "class",
        "signature": signature,
        "docstring": docstring,
        "decorators": decorators,
        "source_hash": source_hash,
        "line_count": end - start,
        "has_type_hints": True,  # Classes don't have return annotations
    }
```

**Testing (Step 2.3)**:

Create integration tests that run the scripts against sample files.

---

### Step 2.4: Implement Rules Engine

**File to create**: `remora/hub/rules.py`

```python
"""Rules Engine for Hub updates.

The Rules Engine decides what actions to take when a file changes.
It is completely deterministic - no LLM involved.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remora.hub.models import NodeState


@dataclass
class UpdateAction(ABC):
    """Base class for update actions."""

    @abstractmethod
    async def execute(self, context: "RulesContext") -> dict[str, Any]:
        """Execute the update action."""
        ...


@dataclass
class ExtractSignatures(UpdateAction):
    """Extract signatures from a file."""
    file_path: Path

    async def execute(self, context: "RulesContext") -> dict[str, Any]:
        return await context.run_script(
            "hub/tools/extract_signatures.pym",
            {"file_path": str(self.file_path)},
        )


@dataclass
class ScanImports(UpdateAction):
    """Scan imports from a file."""
    file_path: Path

    async def execute(self, context: "RulesContext") -> dict[str, Any]:
        return await context.run_script(
            "hub/tools/scan_imports.pym",
            {"file_path": str(self.file_path)},
        )


@dataclass
class DeleteFileNodes(UpdateAction):
    """Delete all nodes for a file."""
    file_path: Path

    async def execute(self, context: "RulesContext") -> dict[str, Any]:
        deleted = context.kv.invalidate_file(str(self.file_path))
        return {"deleted": deleted, "count": len(deleted)}


@dataclass
class RulesContext:
    """Context for executing rules."""
    kv: Any  # NodeStateKV
    executor: Any  # GrailExecutor
    grail_dir: Path

    async def run_script(self, script: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return await self.executor.execute(
            pym_path=Path(script),
            grail_dir=self.grail_dir,
            inputs=inputs,
        )


class RulesEngine:
    """Decides what to recompute when a file changes."""

    def get_update_actions(
        self,
        change_type: str,  # "added", "modified", "deleted"
        file_path: Path,
        old_states: dict[str, NodeState] | None = None,
    ) -> list[UpdateAction]:
        """Determine actions to take for a file change.

        Args:
            change_type: Type of change
            file_path: Path to changed file
            old_states: Previous NodeStates for this file (if any)

        Returns:
            List of actions to execute
        """
        actions: list[UpdateAction] = []

        if change_type == "deleted":
            actions.append(DeleteFileNodes(file_path))
            return actions

        # For added/modified: always extract signatures
        actions.append(ExtractSignatures(file_path))
        actions.append(ScanImports(file_path))

        # Future: add more sophisticated rules
        # - If signature changed, find callers
        # - If new function, find tests
        # - If imports changed, update dependency graph

        return actions
```

---

### Step 2.5: Create File Watcher

**File to create**: `remora/hub/watcher.py`

```python
"""File watcher for the Hub daemon.

Uses watchfiles library for efficient filesystem monitoring.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator, Callable, Awaitable

try:
    import watchfiles
    WATCHFILES_AVAILABLE = True
except ImportError:
    WATCHFILES_AVAILABLE = False


class FileWatcher:
    """Watches a directory for Python file changes."""

    def __init__(
        self,
        root: Path,
        callback: Callable[[str, Path], Awaitable[None]],
    ) -> None:
        """Initialize the watcher.

        Args:
            root: Directory to watch
            callback: Async function called with (change_type, path)
        """
        if not WATCHFILES_AVAILABLE:
            raise RuntimeError("watchfiles not installed. Run: pip install watchfiles")

        self.root = root
        self.callback = callback
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start watching for changes."""
        async for changes in watchfiles.awatch(
            self.root,
            stop_event=self._stop_event,
            recursive=True,
        ):
            for change_type, path_str in changes:
                path = Path(path_str)

                # Only process Python files
                if not path.suffix == ".py":
                    continue

                # Skip __pycache__ and hidden files
                if "__pycache__" in path.parts or path.name.startswith("."):
                    continue

                # Map watchfiles change type to our string
                type_map = {
                    watchfiles.Change.added: "added",
                    watchfiles.Change.modified: "modified",
                    watchfiles.Change.deleted: "deleted",
                }
                change = type_map.get(change_type, "modified")

                try:
                    await self.callback(change, path)
                except Exception as e:
                    # Log but don't crash on errors
                    print(f"Error processing {path}: {e}")

    def stop(self) -> None:
        """Stop watching."""
        self._stop_event.set()
```

---

### Step 2.6: Implement IPC Server

**File to create**: `remora/hub/server.py`

```python
"""IPC server for Hub daemon.

Provides Unix socket interface for clients to query node state.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from remora.hub.storage import NodeStateKV


class HubServer:
    """Unix socket server for Hub queries."""

    def __init__(
        self,
        socket_path: Path,
        kv: NodeStateKV,
    ) -> None:
        self.socket_path = socket_path
        self.kv = kv
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start the server."""
        # Remove existing socket
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path),
        )

        # Set permissions
        self.socket_path.chmod(0o600)

    async def stop(self) -> None:
        """Stop the server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        if self.socket_path.exists():
            self.socket_path.unlink()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        try:
            data = await reader.read(65536)
            request = json.loads(data.decode())

            response = await self._handle_request(request)

            writer.write(json.dumps(response).encode())
            await writer.drain()
        except Exception as e:
            error_response = {"error": str(e)}
            writer.write(json.dumps(error_response).encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process a request and return response."""
        request_type = request.get("type")

        if request_type == "get_context":
            node_ids = request.get("nodes", [])
            states = self.kv.get_many(node_ids)
            return {
                "nodes": {
                    k: v.model_dump() for k, v in states.items()
                }
            }

        elif request_type == "health":
            stats = self.kv.stats()
            return {
                "status": "ok",
                "nodes": stats["nodes"],
                "files": stats["files"],
            }

        else:
            return {"error": f"Unknown request type: {request_type}"}
```

---

### Step 2.7: Create Hub Daemon

**File to create**: `remora/hub/daemon.py`

```python
"""Hub daemon implementation.

The main daemon that coordinates watching, indexing, and serving.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from remora.hub.models import NodeState, FileIndex
from remora.hub.storage import NodeStateKV
from remora.hub.rules import RulesEngine, RulesContext
from remora.hub.watcher import FileWatcher
from remora.hub.server import HubServer


class HubDaemon:
    """The Node State Hub daemon."""

    def __init__(
        self,
        root: Path,
        socket_path: Path = Path("/tmp/remora-hub.sock"),
        db_path: Path = Path("~/.cache/remora/hub.db"),
        grail_dir: Path | None = None,
        executor: Any = None,
    ) -> None:
        self.root = root.resolve()
        self.socket_path = socket_path
        self.db_path = db_path.expanduser()
        self.grail_dir = grail_dir or (root / "agents")
        self.executor = executor

        self.kv = NodeStateKV(self.db_path)
        self.rules = RulesEngine()
        self.server = HubServer(socket_path, self.kv)
        self.watcher = FileWatcher(root, self._handle_file_change)

        self._start_time = datetime.now(timezone.utc)

    async def run(self) -> None:
        """Run the daemon."""
        print(f"Hub starting: watching {self.root}")

        # 1. Cold start: index existing files
        await self._cold_start_index()

        # 2. Start server
        await self.server.start()
        print(f"Hub server listening on {self.socket_path}")

        # 3. Start watcher
        try:
            await self.watcher.start()
        except asyncio.CancelledError:
            pass
        finally:
            await self.server.stop()
            self.kv.close()
            print("Hub stopped")

    async def _cold_start_index(self) -> None:
        """Index all Python files on startup."""
        print("Cold start: indexing existing files...")

        indexed = 0
        for py_file in self.root.rglob("*.py"):
            # Skip __pycache__ and hidden
            if "__pycache__" in py_file.parts or py_file.name.startswith("."):
                continue

            # Check if file changed since last index
            file_hash = self._hash_file(py_file)
            existing = self.kv.get_file_index(str(py_file))

            if existing and existing.file_hash == file_hash:
                continue  # No changes

            await self._index_file(py_file, "cold_start")
            indexed += 1

        print(f"Cold start complete: indexed {indexed} files")

    async def _handle_file_change(self, change_type: str, path: Path) -> None:
        """Handle a file change event."""
        print(f"File change: {change_type} {path}")

        # Get old state for this file
        old_states = {
            s.key: s for s in self.kv.get_by_file(str(path))
        }

        # Get actions from rules engine
        actions = self.rules.get_update_actions(change_type, path, old_states)

        # Execute actions
        context = RulesContext(
            kv=self.kv,
            executor=self.executor,
            grail_dir=self.grail_dir,
        )

        for action in actions:
            result = await action.execute(context)

            # Process extract_signatures result
            if hasattr(action, "file_path") and "nodes" in result:
                await self._store_nodes(
                    result["file_path"],
                    result["file_hash"],
                    result["nodes"],
                    "file_change",
                )

    async def _index_file(self, path: Path, source: str) -> None:
        """Index a single file."""
        if self.executor is None:
            return  # No executor configured

        context = RulesContext(
            kv=self.kv,
            executor=self.executor,
            grail_dir=self.grail_dir,
        )

        # Run extraction
        result = await context.run_script(
            "hub/tools/extract_signatures.pym",
            {"file_path": str(path)},
        )

        if "error" in result:
            print(f"Error indexing {path}: {result['error']}")
            return

        await self._store_nodes(
            result["file_path"],
            result["file_hash"],
            result["nodes"],
            source,
        )

    async def _store_nodes(
        self,
        file_path: str,
        file_hash: str,
        nodes: list[dict],
        source: str,
    ) -> None:
        """Store extracted nodes in KV."""
        now = datetime.now(timezone.utc)

        # Store each node
        for node_data in nodes:
            key = f"node:{file_path}:{node_data['name']}"
            state = NodeState(
                key=key,
                file_path=file_path,
                node_name=node_data["name"],
                node_type=node_data["type"],
                source_hash=node_data["source_hash"],
                file_hash=file_hash,
                signature=node_data.get("signature"),
                docstring=node_data.get("docstring"),
                decorators=node_data.get("decorators", []),
                line_count=node_data.get("line_count"),
                has_type_hints=node_data.get("has_type_hints", False),
                last_updated=now,
                update_source=source,
            )
            self.kv.set(state)

        # Update file index
        self.kv.set_file_index(FileIndex(
            file_path=file_path,
            file_hash=file_hash,
            node_count=len(nodes),
            last_scanned=now,
        ))

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

### Step 2.8: Implement HubClient

**File to update**: `remora/context/hub_client.py`

Replace the stub with actual client implementation:

```python
"""Hub client for Pull Hook integration.

This client connects to the Hub daemon and retrieves node context.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from remora.hub.models import NodeState


class HubClient:
    """Client for the Hub daemon."""

    def __init__(
        self,
        socket_path: Path = Path("/tmp/remora-hub.sock"),
        timeout: float = 1.0,
    ) -> None:
        self.socket_path = socket_path
        self.timeout = timeout
        self._available: bool | None = None

    async def get_context(self, node_ids: list[str]) -> dict[str, NodeState]:
        """Get context for nodes from Hub.

        Returns empty dict if Hub is not available.
        """
        if not await self._is_available():
            return {}

        try:
            response = await self._send_request({
                "type": "get_context",
                "nodes": node_ids,
            })

            nodes = response.get("nodes", {})
            return {
                k: NodeState.model_validate(v)
                for k, v in nodes.items()
            }
        except Exception:
            return {}

    async def health_check(self) -> bool:
        """Check if Hub is healthy."""
        try:
            response = await self._send_request({"type": "health"})
            return response.get("status") == "ok"
        except Exception:
            return False

    async def _is_available(self) -> bool:
        """Check if Hub socket exists and is responsive."""
        if self._available is not None:
            return self._available

        if not self.socket_path.exists():
            self._available = False
            return False

        self._available = await self.health_check()
        return self._available

    async def _send_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send request to Hub and get response."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(self.socket_path)),
            timeout=self.timeout,
        )

        try:
            writer.write(json.dumps(request).encode())
            await writer.drain()

            data = await asyncio.wait_for(
                reader.read(65536),
                timeout=self.timeout,
            )

            return json.loads(data.decode())
        finally:
            writer.close()
            await writer.wait_closed()


def get_hub_client() -> HubClient:
    """Get the Hub client instance."""
    return HubClient()
```

---

### Step 2.9: Wire Pull Hook

**File to update**: `remora/context/manager.py`

Update `pull_hub_context` to use the real client:

```python
async def pull_hub_context(self) -> None:
    """Pull fresh context from Hub.

    This is called at the start of each turn to inject
    external context into the Decision Packet.
    """
    from remora.context.hub_client import get_hub_client

    if self._hub_client is None:
        self._hub_client = get_hub_client()

    try:
        context = await self._hub_client.get_context([self.packet.node_id])
        if context:
            # Convert NodeState to dict for packet
            node_state = context.get(self.packet.node_id)
            if node_state:
                self.packet.hub_context = {
                    "signature": node_state.signature,
                    "docstring": node_state.docstring,
                    "related_tests": node_state.related_tests,
                    "complexity": node_state.complexity,
                }
                self.packet.hub_freshness = node_state.last_updated
    except Exception:
        # Graceful degradation - Hub is optional
        pass
```

---

## Migration Checklist

### Phase 2 Completion

- [ ] Hub models created (`remora/hub/models.py`)
- [ ] NodeStateKV implemented (`remora/hub/storage.py`)
- [ ] Analysis scripts created (`agents/hub/tools/*.pym`)
- [ ] Rules engine implemented (`remora/hub/rules.py`)
- [ ] File watcher working (`remora/hub/watcher.py`)
- [ ] IPC server implemented (`remora/hub/server.py`)
- [ ] Hub daemon working (`remora/hub/daemon.py`)
- [ ] HubClient connecting to daemon
- [ ] Pull Hook returning real context
- [ ] End-to-end test: start Hub, run Remora, verify context

---

## Appendix: Library APIs

### fsdantic

Key classes for KV storage:

```python
from fsdantic import (
    KVManager,           # Low-level KV operations
    KVTransaction,       # Grouped operations
    TypedKVRepository,   # Type-safe model storage
)

# Using TypedKVRepository
repo = TypedKVRepository[NodeState](agent_fs, prefix="node:")
await repo.save("foo.py:bar", node_state)
state = await repo.load("foo.py:bar", NodeState)
all_states = await repo.list_all(NodeState)
```

### grail

Key functions for script execution:

```python
import grail

# Load and run a script
script = grail.load("path/to/script.pym", grail_dir=".grail")
check_result = script.check()  # Validate
result = await script.run(
    inputs={"file_path": "/path/to/file.py"},
    externals={"read_file": read_file_impl},
    limits=grail.DEFAULT,
)

# Limits presets
grail.STRICT      # 8MB memory, 500ms
grail.DEFAULT     # 16MB memory, 2s
grail.PERMISSIVE  # 64MB memory, 10s
```

### watchfiles

```python
import watchfiles

# Watch for changes
async for changes in watchfiles.awatch("/path/to/dir"):
    for change_type, path in changes:
        print(f"{change_type}: {path}")

# Change types
watchfiles.Change.added
watchfiles.Change.modified
watchfiles.Change.deleted
```

---

## End of Guide

This guide provides a complete roadmap for implementing the Node State Hub concept in Remora. Follow the steps in order, ensuring tests pass at each checkpoint before proceeding.
