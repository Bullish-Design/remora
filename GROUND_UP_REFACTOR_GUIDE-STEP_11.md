# Implementation Guide: Step 11 — Indexer Package

**Step**: 11 of 15  
**Package**: `remora/indexer/`  
**Goal**: Extract daemon/indexing code from `hub/` into a focused indexer package  
**Design Reference**: Idea 3 in `.context/GROUND_UP_REFACTOR_IDEAS.md`

---

## Overview

This step extracts the daemon, indexing, and filesystem watching logic from `src/remora/hub/` into a new focused `src/remora/indexer/` package. This is Idea 3 from the design document: splitting the mixed "Hub" into two independent packages (`indexer` and `dashboard`).

### What You're Creating

```
src/remora/indexer/
  __init__.py        # Public exports
  models.py          # NodeState, FileIndex (from hub/models.py)
  store.py           # NodeStateStore (from hub/store.py)
  rules.py           # RulesEngine (from hub/rules.py)
  scanner.py         # NEW: Tree-sitter based file scanner
  daemon.py          # IndexerDaemon (refactored from hub/daemon.py)
  cli.py             # CLI entry point (remora-index)
```

### What You're Moving/Modifying

| Source File | Target | Notes |
|-------------|--------|-------|
| `hub/models.py` | `indexer/models.py` | NodeState, FileIndex (HubStatus stays in hub for dashboard) |
| `hub/store.py` | `indexer/store.py` | NodeStateStore |
| `hub/rules.py` | `indexer/rules.py` | ActionContext, UpdateAction, RulesEngine |
| `hub/daemon.py` | `indexer/daemon.py` | Refactor to IndexerDaemon |
| `hub/watcher.py` | `indexer/watcher.py` (or scanner.py) | Filesystem watcher |
| `hub/indexer.py` | `indexer/scanner.py` | Merge into scanner |

---

## Step-by-Step Implementation

### Step 1: Create the Package Directory

Create the new directory structure:

```bash
mkdir -p src/remora/indexer
touch src/remora/indexer/__init__.py
```

### Step 2: Create `models.py`

Copy from `hub/models.py` but **remove `HubStatus`** (that's for the dashboard):

```python
# src/remora/indexer/models.py
"""Node State data models for the indexer."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Literal

from fsdantic import VersionedKVRecord
from pydantic import Field, field_serializer


class NodeState(VersionedKVRecord):
    """State for a single code node.
    
    Inherits from VersionedKVRecord:
    - created_at: float (auto-set)
    - updated_at: float (auto-updated)
    - version: int (auto-incremented)
    
    Key format: "node:{file_path}:{node_name}"
    """

    updated_at: float = Field(default_factory=time.time)
    key: str = Field(description="Unique key: 'node:{file_path}:{node_name}'")
    file_path: str = Field(description="Absolute path to source file")
    node_name: str = Field(description="Name of function, class, or module")
    node_type: Literal["function", "class", "module"] = Field(
        description="Type of code node"
    )

    source_hash: str = Field(description="SHA256 of node source code")
    file_hash: str = Field(description="SHA256 of entire file")

    signature: str | None = Field(default=None)
    docstring: str | None = Field(default=None)
    imports: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)

    callers: list[str] | None = Field(default=None)
    callees: list[str] | None = Field(default=None)

    related_tests: list[str] | None = Field(default=None)

    line_count: int | None = Field(default=None)
    complexity: int | None = Field(default=None)

    docstring_outdated: bool = Field(default=False)
    has_type_hints: bool = Field(default=True)

    update_source: Literal["file_change", "cold_start", "manual", "adhoc"] = Field()


class FileIndex(VersionedKVRecord):
    """Tracking entry for a source file."""

    updated_at: float = Field(default_factory=time.time)
    file_path: str = Field(description="Absolute path")
    file_hash: str = Field(description="SHA256 of file contents")
    node_count: int = Field(description="Number of nodes in file")
    last_scanned: datetime = Field(description="When file was last indexed")

    @field_serializer("last_scanned")
    def _serialize_last_scanned(self, value: datetime) -> str:
        return value.isoformat()
```

### Step 3: Create `store.py`

Copy from `hub/store.py` but update imports. The store should NOT depend on `hub/` imports:

```python
# src/remora/indexer/store.py
"""FSdantic-backed storage for NodeState and FileIndex."""

from __future__ import annotations

import asyncio
import logging
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

    # === Node Operations ===

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

    # === File Index Operations ===

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

    # === Statistics ===

    async def stats(self) -> dict[str, int]:
        """Get storage statistics."""
        nodes = await self.node_repo.list_all()
        files = await self.file_repo.list_all()
        return {"nodes": len(nodes), "files": len(files)}

    # === Helpers ===

    @staticmethod
    def _strip_prefix(key: str, prefix: str) -> str:
        """Strip prefix from key if present."""
        if key.startswith(prefix):
            return key[len(prefix):]
        return key
```

### Step 4: Create `scanner.py`

This replaces `hub/indexer.py` and provides tree-sitter based scanning. Use the existing `remora.discovery` module:

```python
# src/remora/indexer/scanner.py
"""File scanner using tree-sitter discovery."""

from __future__ import annotations

import ast
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.discovery import CSTNode

logger = logging.getLogger(__name__)


class Scanner:
    """Scans source files and extracts node information.
    
    Uses tree-sitter for robust parsing and AST extraction.
    Falls back to stdlib ast for simple cases.
    """

    def __init__(self) -> None:
        self._use_tree_sitter = True

    async def scan_file(self, path: Path) -> list[dict]:
        """Scan a single file and return node data.
        
        Args:
            path: Path to Python file
            
        Returns:
            List of node data dicts with extracted metadata
        """
        if not path.exists():
            logger.warning("File does not exist: %s", path)
            return []

        content = path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(content.encode()).hexdigest()

        if self._use_tree_sitter:
            return await self._scan_with_tree_sitter(path, content, file_hash)
        else:
            return self._scan_with_ast(path, content, file_hash)

    async def _scan_with_tree_sitter(
        self,
        path: Path,
        content: str,
        file_hash: str,
    ) -> list[dict]:
        """Scan using tree-sitter (the robust way)."""
        from remora.discovery import discover, CSTNode

        try:
            nodes: list[CSTNode] = discover([path])
        except Exception as e:
            logger.warning("Tree-sitter failed for %s, falling back to ast: %s", path, e)
            return self._scan_with_ast(path, content, file_hash)

        result = []
        lines = content.splitlines()

        for node in nodes:
            node_data = {
                "name": node.name,
                "type": node.node_type,
                "file_path": str(path),
                "file_hash": file_hash,
                "source_hash": hashlib.sha256(node.text.encode()).hexdigest(),
                "start_line": node.start_line,
                "end_line": node.end_line,
                "line_count": node.end_line - node.start_line + 1,
            }

            if node.node_type == "function":
                node_data.update(self._extract_function_details(node, lines))
            elif node.node_type == "class":
                node_data.update(self._extract_class_details(node, lines))

            result.append(node_data)

        return result

    def _scan_with_ast(
        self,
        path: Path,
        content: str,
        file_hash: str,
    ) -> list[dict]:
        """Scan using stdlib ast (fallback)."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        lines = content.splitlines()
        result = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result.append(self._extract_function_ast(node, path, file_hash, lines))
            elif isinstance(node, ast.ClassDef):
                result.append(self._extract_class_ast(node, path, file_hash, lines))

        return result

    def _extract_function_details(
        self,
        node: CSTNode,
        lines: list[str],
    ) -> dict:
        """Extract function details from CSTNode."""
        source = "\n".join(lines[node.start_line - 1:node.end_line])

        return {
            "source": source,
            "signature": self._extract_signature(node),
            "docstring": None,
            "decorators": [],
            "has_type_hints": True,
        }

    def _extract_class_details(
        self,
        node: CSTNode,
        lines: list[str],
    ) -> dict:
        """Extract class details from CSTNode."""
        source = "\n".join(lines[node.start_line - 1:node.end_line])

        return {
            "source": source,
            "signature": f"class {node.name}",
            "docstring": None,
            "decorators": [],
        }

    def _extract_signature(self, node: CSTNode) -> str:
        """Extract signature from CSTNode."""
        return f"def {node.name}(...)"

    def _extract_function_ast(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        path: Path,
        file_hash: str,
        lines: list[str],
    ) -> dict:
        """Extract function details from AST node."""
        start = node.lineno - 1
        end = node.end_lineno or start + 1
        func_source = "\n".join(lines[start:end])
        source_hash = hashlib.sha256(func_source.encode()).hexdigest()

        args = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            args.append(arg_str)

        returns = ""
        if node.returns:
            returns = f" -> {ast.unparse(node.returns)}"

        is_async = isinstance(node, ast.AsyncFunctionDef)
        prefix = "async def" if is_async else "def"
        signature = f"{prefix} {node.name}({', '.join(args)}){returns}"

        docstring = ast.get_docstring(node)
        if docstring:
            docstring = docstring.split("\n")[0][:100]

        decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

        has_type_hints = node.returns is not None or any(a.annotation for a in node.args.args)

        return {
            "name": node.name,
            "type": "function",
            "file_path": str(path),
            "file_hash": file_hash,
            "source_hash": source_hash,
            "start_line": node.lineno,
            "end_line": node.end_lineno or node.lineno,
            "line_count": end - start,
            "source": func_source,
            "signature": signature,
            "docstring": docstring,
            "decorators": decorators,
            "has_type_hints": has_type_hints,
        }

    def _extract_class_ast(
        self,
        node: ast.ClassDef,
        path: Path,
        file_hash: str,
        lines: list[str],
    ) -> dict:
        """Extract class details from AST node."""
        start = node.lineno - 1
        end = node.end_lineno or start + 1
        class_source = "\n".join(lines[start:end])
        source_hash = hashlib.sha256(class_source.encode()).hexdigest()

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
            "file_path": str(path),
            "file_hash": file_hash,
            "source_hash": source_hash,
            "start_line": node.lineno,
            "end_line": node.end_lineno or node.lineno,
            "line_count": end - start,
            "source": class_source,
            "signature": signature,
            "docstring": docstring,
            "decorators": decorators,
            "has_type_hints": True,
        }


async def scan_file_simple(
    file_path: Path,
    store: "NodeStateStore",
) -> int:
    """Simple file scanning for ad-hoc indexing.
    
    This is a lightweight alternative that doesn't require tree-sitter.
    
    Args:
        file_path: Path to Python file
        store: NodeStateStore to save results
        
    Returns:
        Number of nodes indexed
    """
    from remora.indexer.models import FileIndex, NodeState

    content = file_path.read_text(encoding="utf-8")
    file_hash = hashlib.sha256(content.encode()).hexdigest()

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return 0

    lines = content.splitlines()
    nodes: list[NodeState] = []
    now = datetime.now(timezone.utc)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            state = _extract_function_ast(node, file_path, file_hash, lines)
            nodes.append(state)
        elif isinstance(node, ast.ClassDef):
            state = _extract_class_ast(node, file_path, file_hash, lines)
            nodes.append(state)

    await store.invalidate_file(str(file_path))

    if nodes:
        await store.set_many(nodes)

    await store.set_file_index(FileIndex(
        file_path=str(file_path),
        file_hash=file_hash,
        node_count=len(nodes),
        last_scanned=now,
    ))

    logger.debug("Indexed %s: %d nodes", file_path, len(nodes))

    return len(nodes)


def _extract_function_ast(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    file_path: Path,
    file_hash: str,
    lines: list[str],
) -> NodeState:
    """Extract function metadata from AST."""
    start = node.lineno - 1
    end = node.end_lineno or start + 1
    func_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(func_source.encode()).hexdigest()

    args = []
    for arg in node.args.args:
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"
        args.append(arg_str)

    returns = ""
    if node.returns:
        returns = f" -> {ast.unparse(node.returns)}"

    is_async = isinstance(node, ast.AsyncFunctionDef)
    prefix = "async def" if is_async else "def"
    signature = f"{prefix} {node.name}({', '.join(args)}){returns}"

    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    has_type_hints = node.returns is not None or any(a.annotation for a in node.args.args)

    return NodeState(
        key=f"node:{file_path}:{node.name}",
        file_path=str(file_path),
        node_name=node.name,
        node_type="function",
        source_hash=source_hash,
        file_hash=file_hash,
        signature=signature,
        docstring=docstring,
        imports=[],
        decorators=decorators,
        line_count=end - start,
        has_type_hints=has_type_hints,
        update_source="adhoc",
    )


def _extract_class_ast(
    node: ast.ClassDef,
    file_path: Path,
    file_hash: str,
    lines: list[str],
) -> NodeState:
    """Extract class metadata from AST."""
    start = node.lineno - 1
    end = node.end_lineno or start + 1
    class_source = "\n".join(lines[start:end])
    source_hash = hashlib.sha256(class_source.encode()).hexdigest()

    bases = [ast.unparse(b) for b in node.bases]
    signature = f"class {node.name}"
    if bases:
        signature += f"({', '.join(bases)})"

    docstring = ast.get_docstring(node)
    if docstring:
        docstring = docstring.split("\n")[0][:100]

    decorators = [f"@{ast.unparse(d)}" for d in node.decorator_list]

    return NodeState(
        key=f"node:{file_path}:{node.name}",
        file_path=str(file_path),
        node_name=node.name,
        node_type="class",
        source_hash=source_hash,
        file_hash=file_hash,
        signature=signature,
        docstring=docstring,
        imports=[],
        decorators=decorators,
        line_count=end - start,
        has_type_hints=True,
        update_source="adhoc",
    )
```

### Step 5: Create `rules.py`

Move from `hub/rules.py`. This defines the action system for handling file changes:

```python
# src/remora/indexer/rules.py
"""Rules Engine for indexer updates."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from remora.indexer.store import NodeStateStore


@dataclass
class ActionContext:
    """Context for executing update actions."""

    store: "NodeStateStore"
    grail_executor: Any = None
    project_root: Path = Path(".")

    async def run_grail_script(
        self,
        script_path: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Run a Grail script and return results."""
        if self.grail_executor is not None:
            return await self.grail_executor.run(
                script_path=script_path,
                inputs=inputs,
                externals={"read_file": self._read_file},
            )

        import grail

        grail_dir = self.project_root / ".grail"
        script_file = grail_dir / script_path
        script = grail.load(str(script_file), grail_dir=str(grail_dir))
        result = await script.run(
            inputs=inputs,
            externals={"read_file": self._read_file},
        )
        return result

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
        """Execute the action."""
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


class RulesEngine:
    """Decides what to recompute when a file changes."""

    def get_actions(
        self,
        change_type: str,
        file_path: Path,
    ) -> list[UpdateAction]:
        """Determine actions to take for a file change."""
        actions: list[UpdateAction] = []

        if change_type == "deleted":
            actions.append(DeleteFileNodes(file_path))
            return actions

        actions.append(ExtractSignatures(file_path))

        return actions

    def should_process_file(self, file_path: Path, ignore_patterns: list[str]) -> bool:
        """Check if a file should be processed."""
        if file_path.suffix != ".py":
            return False

        path_parts = file_path.parts
        for pattern in ignore_patterns:
            if pattern in path_parts:
                return False

        if file_path.name.startswith("."):
            return False

        return True
```

### Step 6: Create `daemon.py`

This is the main daemon that watches files and updates the index:

```python
# src/remora/indexer/daemon.py
"""Indexer daemon implementation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import signal
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fsdantic import Fsdantic, Workspace
from watchfiles import Change, awatch

from remora.indexer.models import FileIndex, NodeState
from remora.indexer.rules import ActionContext, ExtractSignatures, RulesEngine
from remora.indexer.scanner import scan_file_simple
from remora.indexer.store import NodeStateStore

logger = logging.getLogger(__name__)

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
    ".remora",
]


@dataclass
class IndexerConfig:
    """Configuration for the indexer daemon."""

    watch_paths: list[str] = ["src/"]
    store_path: str = ".remora/indexer.db"
    max_workers: int = 8
    enable_cross_file_analysis: bool = True


class IndexerDaemon:
    """Background indexer that watches files and updates the index.
    
    Responsibilities:
    - Watch filesystem for Python file changes
    - Index files on cold start
    - Update NodeState records
    """

    def __init__(
        self,
        config: IndexerConfig,
        store: NodeStateStore | None = None,
        grail_executor: Any = None,
    ) -> None:
        """Initialize the daemon.

        Args:
            config: Indexer configuration
            store: Pre-initialized store (optional)
            grail_executor: Grail script executor (optional)
        """
        self.config = config
        self.store = store
        self.executor = grail_executor

        self.workspace: Workspace | None = None
        self.rules = RulesEngine()

        self._shutdown_event = asyncio.Event()
        self._started_at: datetime | None = None

        self.max_workers = config.max_workers
        self._change_queue: asyncio.Queue[tuple[str, Path]] | None = None
        self._change_workers: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start the indexer daemon."""
        logger.info("Starting indexer daemon")

        self._change_queue = asyncio.Queue(maxsize=1000)

        project_root = Path.cwd()
        store_path = project_root / self.config.store_path
        store_path.parent.mkdir(parents=True, exist_ok=True)

        if self.store is None:
            self.workspace = await Fsdantic.open(path=str(store_path))
            self.store = NodeStateStore(self.workspace)

        self._setup_signals()

        self._started_at = datetime.now(timezone.utc)

        await self._cold_start_index()

        if self._shutdown_event.is_set():
            return

        await self._start_change_workers()

        watch_paths = [project_root / p for p in self.config.watch_paths]

        logger.info("Indexer daemon ready, watching: %s", watch_paths)

        await self._watch_files(watch_paths)

    async def _watch_files(self, watch_paths: list[Path]) -> None:
        """Watch filesystem for changes."""
        async for changes in awatch(
            *watch_paths,
            stop_event=self._shutdown_event,
            recursive=True,
        ):
            for change_type, path_str in changes:
                path = Path(path_str)

                if not self._should_process(path):
                    continue

                change_map = {
                    Change.added: "added",
                    Change.modified: "modified",
                    Change.deleted: "deleted",
                }
                change = change_map.get(change_type, "modified")

                logger.debug("File change: %s %s", change, path)

                if self._change_queue and not self._change_queue.full():
                    await self._change_queue.put((change, path))

    async def _start_change_workers(self) -> None:
        """Start workers to process file changes concurrently."""
        for i in range(self.max_workers):
            task = asyncio.create_task(self._change_worker(i))
            self._change_workers.append(task)
        logger.info("Started %d change workers", self.max_workers)

    async def _change_worker(self, worker_id: int) -> None:
        """Worker coroutine that processes file changes from queue."""
        logger.debug("Change worker %d started", worker_id)

        while not self._shutdown_event.is_set():
            try:
                change_type, path = await asyncio.wait_for(
                    self._change_queue.get(), timeout=1.0
                )
                await self._handle_file_change(change_type, path)

            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.exception("Error in change worker %d", worker_id)

        logger.debug("Change worker %d stopped", worker_id)

    async def _handle_file_change(self, change_type: str, path: Path) -> None:
        """Process a file change."""
        store = self.store
        if store is None:
            return

        logger.debug("Processing %s: %s", change_type, path)

        if change_type == "deleted":
            await store.invalidate_file(str(path))
            logger.info("Deleted nodes for: %s", path)
            return

        actions = self.rules.get_actions(change_type, path)

        context = ActionContext(
            store=store,
            grail_executor=self.executor,
            project_root=path.parent,
        )

        for action in actions:
            try:
                result = await action.execute(context)
                if isinstance(action, ExtractSignatures) and "nodes" in result:
                    await self._process_extraction_result(path, result)
            except Exception as exc:
                logger.exception("Action failed for %s", path)

    async def _process_extraction_result(
        self,
        path: Path,
        result: dict[str, Any],
    ) -> None:
        """Process extraction results and store nodes."""
        store = self.store
        if store is None:
            return

        file_hash = result.get("file_hash", "")
        nodes = result.get("nodes", [])

        await store.invalidate_file(str(path))

        now = datetime.now(timezone.utc)
        for node_data in nodes:
            node_key = f"node:{path}:{node_data['name']}"

            state = NodeState(
                key=node_key,
                file_path=str(path),
                node_name=node_data["name"],
                node_type=node_data["type"],
                source_hash=node_data.get("source_hash", ""),
                file_hash=file_hash,
                signature=node_data.get("signature"),
                docstring=node_data.get("docstring"),
                decorators=node_data.get("decorators", []),
                imports=node_data.get("imports", []),
                line_count=node_data.get("line_count"),
                has_type_hints=node_data.get("has_type_hints", False),
                update_source="file_change",
            )
            await store.set(state)

        await store.set_file_index(
            FileIndex(
                file_path=str(path),
                file_hash=file_hash,
                node_count=len(nodes),
                last_scanned=now,
            )
        )

        logger.debug("Indexed %s: %d nodes", path, len(nodes))

    async def _cold_start_index(self) -> None:
        """Index files that changed since last shutdown."""
        store = self.store
        if store is None:
            return

        project_root = Path.cwd()

        logger.info("Cold start: scanning for changed files...")

        files = []
        for py_file in project_root.rglob("*.py"):
            if self._shutdown_event.is_set():
                break

            if not self.rules.should_process_file(py_file, DEFAULT_IGNORE_PATTERNS):
                continue
            files.append(py_file)

        files_to_index = []
        for f in files:
            file_hash = self._hash_file(f)
            existing = await store.get_file_index(str(f))
            if not existing or existing.file_hash != file_hash:
                files_to_index.append(f)

        logger.info("Found %d files to index (out of %d total)", len(files_to_index), len(files))

        if files_to_index:
            indexed, errors = await self._index_files_parallel(files_to_index)
        else:
            indexed, errors = 0, 0

        stats = await store.stats()
        logger.info(
            "Cold start complete: indexed %d files, %d errors",
            indexed,
            errors,
        )

    async def _index_files_parallel(
        self,
        files: list[Path],
    ) -> tuple[int, int]:
        """Index multiple files in parallel."""
        store = self.store
        if store is None:
            return 0, len(files)

        semaphore = asyncio.Semaphore(self.max_workers)

        async def process_file_with_limit(path: Path) -> tuple[Path, int, float]:
            async with semaphore:
                start = time.monotonic()
                try:
                    count = await scan_file_simple(path, store)
                except Exception as e:
                    logger.exception("Error indexing %s", path)
                    raise
                duration = time.monotonic() - start
                return (path, count, duration)

        indexed = 0
        errors = 0

        tasks = [process_file_with_limit(f) for f in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            path = files[i]
            if isinstance(result, Exception):
                logger.exception("Error indexing %s", path)
                errors += 1
            else:
                _, count, duration = result
                indexed += 1
                logger.debug("Indexed %s: %d nodes in %.2fs", path, count, duration)

        return indexed, errors

    def _should_process(self, path: Path) -> bool:
        """Check if a file should be processed."""
        if path.suffix != ".py":
            return False

        try:
            rel_parts = path.relative_to(Path.cwd()).parts
        except ValueError:
            return False

        for pattern in DEFAULT_IGNORE_PATTERNS:
            if pattern in rel_parts:
                return False
            if pattern.startswith("*") and path.name.endswith(pattern[1:]):
                return False

        if any(part.startswith(".") for part in rel_parts):
            return False

        return True

    def _setup_signals(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(self._shutdown()),
            )

    async def _shutdown(self) -> None:
        """Clean shutdown."""
        logger.info("Indexer daemon shutting down")
        self._shutdown_event.set()

        if self.workspace:
            await self.workspace.close()

        logger.info("Indexer daemon stopped")

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Compute SHA256 hash of file contents."""
        try:
            content = path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except OSError:
            return ""
```

### Step 7: Create `cli.py`

Create the CLI entry point for the indexer:

```python
# src/remora/indexer/cli.py
"""CLI entry point for the indexer daemon."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer

from remora.indexer.daemon import IndexerConfig, IndexerDaemon

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

app = typer.Typer(help="Remora Indexer - Background file indexing daemon")


@app.command()
def run(
    watch: bool = typer.Option(
        True,
        "--no-watch",
        help="Run once without watching for changes",
    ),
    paths: list[str] = typer.Option(
        ["src/"],
        "--path",
        "-p",
        help="Paths to watch for changes",
    ),
    store: str = typer.Option(
        ".remora/indexer.db",
        "--store",
        "-s",
        help="Path to indexer store",
    ),
    workers: int = typer.Option(
        8,
        "--workers",
        "-w",
        help="Maximum concurrent workers",
    ),
) -> None:
    """Run the indexer daemon."""
    config = IndexerConfig(
        watch_paths=paths,
        store_path=store,
        max_workers=workers,
    )

    daemon = IndexerDaemon(config)

    try:
        asyncio.run(daemon.start())
    except KeyboardInterrupt:
        logger.info("Indexer stopped by user")


@app.command()
def status(
    store: str = typer.Option(
        ".remora/indexer.db",
        "--store",
        "-s",
        help="Path to indexer store",
    ),
) -> None:
    """Show indexer status."""
    import asyncio

    async def get_status():
        from fsdantic import Fsdantic
        from remora.indexer.store import NodeStateStore

        path = Path(store)
        if not path.exists():
            typer.echo(f"Store not found: {store}")
            raise typer.Exit(1)

        workspace = await Fsdantic.open(path=str(path))
        store_instance = NodeStateStore(workspace)

        stats = await store_instance.stats()
        files = await store_instance.list_all_files()

        await workspace.close()

        return stats, files

    stats, files = asyncio.run(get_status())

    typer.echo(f"Indexer Status")
    typer.echo(f"===============")
    typer.echo(f"Indexed files: {stats['files']}")
    typer.echo(f"Indexed nodes: {stats['nodes']}")

    if files:
        typer.echo(f"\nTracked files:")
        for f in files[:10]:
            typer.echo(f"  {f.file_path} ({f.node_count} nodes)")
        if len(files) > 10:
            typer.echo(f"  ... and {len(files) - 10} more")


if __name__ == "__main__":
    app()
```

### Step 8: Update `__init__.py`

Create the public API exports:

```python
# src/remora/indexer/__init__.py
"""Remora Indexer - Background file indexing daemon."""

from remora.indexer.daemon import IndexerConfig, IndexerDaemon
from remora.indexer.models import FileIndex, NodeState
from remora.indexer.rules import ActionContext, RulesEngine, UpdateAction
from remora.indexer.scanner import Scanner, scan_file_simple
from remora.indexer.store import NodeStateStore

__all__ = [
    "IndexerConfig",
    "IndexerDaemon",
    "FileIndex",
    "NodeState",
    "ActionContext",
    "RulesEngine",
    "UpdateAction",
    "Scanner",
    "scan_file_simple",
    "NodeStateStore",
]
```

---

## Verification

After implementation, verify the package works:

```bash
# Test imports
python -c "from remora.indexer import IndexerDaemon, NodeStateStore; print('OK')"

# Test CLI
python -m remora.indexer.cli --help

# Run the daemon (in background or with --no-watch for testing)
python -m remora.indexer.cli run --path src/ --no-watch
```

---

## Dependencies

The new package requires:

- `fsdantic` (existing) — for VersionedKVRecord and TypedKVRepository
- `typer` (existing) — for CLI
- `watchfiles` (existing) — for filesystem watching
- `remora.discovery` (existing) — for tree-sitter CSTNode

---

## Common Pitfalls

1. **Don't mix dashboard code** — Keep this package focused on indexing only
2. **Watch your imports** — The indexer should NOT import from `remora.hub` 
3. **Use asyncio.Queue** — Don't process file changes directly; queue them for workers
4. **Hash files before parsing** — Compute file hash before AST parsing to detect changes
5. **Handle missing files gracefully** — Deleted files should just invalidate, not error

---

## Next Steps

After completing this step:

1. Update `pyproject.toml` to add entry point for `remora-index` CLI
2. Move on to **Step 12: Dashboard Package** — Extract web server code from hub/
3. Update any code that imports from `remora.hub` to use `remora.indexer` instead
