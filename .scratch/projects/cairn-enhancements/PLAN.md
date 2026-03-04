# Cairn Enhancements Implementation Plan

> **CRITICAL INSTRUCTIONS FOR EXECUTING AGENT:**
> - **DO NOT USE SUBAGENTS** - Execute all tasks directly
> - **DO NOT STOP UNTIL COMPLETE** - Continue through all phases
> - **UPDATE PROGRESS.md** - Mark tasks complete as you go

---

## Architecture Decision: Cairn-First

**Decision:** Add public APIs to Cairn first, then implement Remora features using those clean APIs.

**Rationale:**
- Maintains clean dependency chain: Remora → Cairn → fsdantic
- Avoids Remora importing fsdantic directly (tech debt)
- Creates reusable APIs that benefit other Cairn consumers

**Execution Strategy:**
1. **Phase 0 (Cairn):** Add public APIs to Cairn library
2. **Phases 1-7 (Remora):** Implement features using Cairn APIs

---

## Table of Contents

| Section | Description |
|---------|-------------|
| [1. Overview](#1-overview) | Project goals, scope, dependencies |
| [2. Phase 0: Cairn API Additions](#2-phase-0-cairn-api-additions) | **NEW** - Public APIs to add to Cairn |
| [3. Phase 1: CLI Wrappers](#3-phase-1-cli-wrappers) | Workspace inspection CLI commands |
| [4. Phase 2: WorkspaceProtocol](#4-phase-2-workspaceprotocol) | Abstract interface for testability |
| [5. Phase 3: KV Store Integration](#5-phase-3-kv-store-integration) | Agent state persistence |
| [6. Phase 4: Private API Fix](#6-phase-4-private-api-fix) | Replace `_open_workspace` usage |
| [7. Phase 5: Bidirectional Sync](#7-phase-5-bidirectional-sync) | Disk-to-workspace sync |
| [8. Phase 6: Container Sandbox](#8-phase-6-container-sandbox) | Isolated code execution |
| [9. Phase 7: Validation Harness](#9-phase-7-validation-harness) | Automated code validation |
| [10. File Manifest](#10-file-manifest) | All files to create/modify |
| [11. Test Strategy](#11-test-strategy) | Testing approach for each phase |
| [12. Acceptance Criteria](#12-acceptance-criteria) | Definition of done |

---

## 1. Overview

### 1.1 Project Goals

Enhance Remora's Cairn workspace integration with:

1. **CLI Visibility** - Inspect workspace contents without extraction
2. **Testability** - Abstract workspace interface for unit testing
3. **State Persistence** - Agent state via KV store
4. **API Stability** - Remove private API dependencies
5. **Development Workflow** - Bidirectional sync, sandbox execution, validation

### 1.2 Scope

**In Scope:**
- **Cairn additions:** Public workspace opening, inspection, state management APIs
- **Remora additions:** CLI commands, protocols, container sandbox, validation
- WorkspaceProtocol abstraction
- KV store integration for agent state
- Private API replacement
- Bidirectional disk-workspace sync
- Container sandbox execution
- Validation harness

**Out of Scope:**
- Web UI inspector (future enhancement)
- Multi-user workspace sharing
- Distributed workspace storage

### 1.3 Dependencies

| Dependency | Version | Source |
|------------|---------|--------|
| fsdantic | >=0.2.0 | Git: Bullish-Design/fsdantic |
| cairn | latest | Git: Bullish-Design/cairn |
| click | >=8.1 | PyPI |
| typer | >=0.12 | PyPI (optional, already in deps) |
| docker | >=6.0 | PyPI (new, for sandbox) |

### 1.4 Priority Order

| Phase | Priority | Effort | Dependencies | Target |
|-------|----------|--------|--------------|--------|
| **0. Cairn API Additions** | **P0** | **~8h** | **None** | **Cairn** |
| 1. CLI Wrappers | P1 | ~10h | Phase 0 | Remora |
| 2. WorkspaceProtocol | P1 | ~8h | None | Remora |
| 3. KV Store Integration | P1 | ~6h | Phase 0 | Remora |
| 4. Private API Fix | P0 | ~2h | Phase 0 | Remora |
| 5. Bidirectional Sync | P2 | ~12h | Phase 0, 1 | Remora |
| 6. Container Sandbox | P2 | ~18h | Phase 1, 5 | Remora |
| 7. Validation Harness | P2 | ~15h | Phase 6 | Remora |

**Recommended execution order:** 0 → 4 → 2 → 3 → 1 → 5 → 6 → 7

---

## 2. Phase 0: Cairn API Additions

### 2.1 Goal

Add public APIs to Cairn that Remora (and other consumers) can use without importing fsdantic directly.

### 2.2 APIs to Add

| API | Location | Purpose |
|-----|----------|---------|
| `open_workspace()` | `cairn.runtime` | Public function to open workspace |
| `Workspace` type | `cairn` (re-export) | Type annotation without fsdantic import |
| `WorkspaceInspector` | `cairn.runtime.inspection` | Tree, stats, diff utilities |
| `AgentStateManager` | `cairn.runtime.state` | General-purpose KV state for agents |
| `materialize_workspace()` | `cairn.runtime` | Extract workspace to disk |

### 2.3 File: `cairn/runtime/workspace_manager.py` (EDIT)

Add public function alongside existing class:

```python
# Add at module level, after WorkspaceManager class

async def open_workspace(
    path: Path | str,
    *,
    readonly: bool = False,
) -> "Workspace":
    """Open a Cairn workspace.
    
    This is the public API for opening workspaces without a context manager.
    The caller is responsible for closing the workspace.
    
    Args:
        path: Path to the workspace database file
        readonly: If True, open in read-only mode
        
    Returns:
        An open Workspace instance
        
    Example:
        workspace = await open_workspace("/path/to/workspace.db")
        try:
            content = await workspace.files.read("/file.txt")
        finally:
            await workspace.close()
    """
    return await _open_workspace(path, readonly=readonly)
```

### 2.4 File: `cairn/runtime/inspection.py` (NEW)

```python
"""Workspace inspection utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fsdantic import Workspace
    from fsdantic.materialization import FileChange


@dataclass
class WorkspaceStats:
    """Workspace statistics."""
    file_count: int
    dir_count: int
    total_bytes: int


class WorkspaceInspector:
    """Read-only workspace inspection utilities.
    
    Provides convenient methods for inspecting workspace contents
    without modifying them. Useful for CLI tools and debugging.
    
    Example:
        async with WorkspaceInspector.from_path("/path/to/ws.db") as inspector:
            tree = await inspector.tree("/")
            stats = await inspector.stats()
    """
    
    def __init__(self, workspace: "Workspace"):
        self._workspace = workspace
        self._owned = False  # True if we opened the workspace
    
    @classmethod
    async def from_path(cls, path: Path | str) -> "WorkspaceInspector":
        """Create inspector by opening workspace at path."""
        from cairn.runtime.workspace_manager import open_workspace
        
        workspace = await open_workspace(path, readonly=True)
        inspector = cls(workspace)
        inspector._owned = True
        return inspector
    
    async def __aenter__(self) -> "WorkspaceInspector":
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._owned:
            await self._workspace.close()
    
    @property
    def workspace(self) -> "Workspace":
        """Access underlying workspace."""
        return self._workspace
    
    async def tree(
        self,
        path: str = "/",
        max_depth: int | None = None,
    ) -> dict[str, Any]:
        """Get directory tree structure.
        
        Returns nested dict with name, type, size, children keys.
        """
        return await self._workspace.files.tree(path, max_depth=max_depth)
    
    async def list_dir(
        self,
        path: str = "/",
        include_stats: bool = False,
    ) -> list[str] | list[dict[str, Any]]:
        """List directory contents.
        
        If include_stats is True, returns list of dicts with name, size, type.
        Otherwise returns list of names.
        """
        names = await self._workspace.files.list_dir(path, output="name")
        
        if not include_stats:
            return names
        
        entries = []
        for name in names:
            full_path = f"{path.rstrip('/')}/{name}"
            try:
                stat = await self._workspace.files.stat(full_path)
                entries.append({
                    "name": name,
                    "size": stat.size if hasattr(stat, "size") else 0,
                    "type": "file" if stat.is_file else "directory",
                })
            except Exception:
                entries.append({"name": name, "size": 0, "type": "unknown"})
        return entries
    
    async def read(self, path: str) -> str:
        """Read file contents as text."""
        return await self._workspace.files.read(path, mode="text")
    
    async def read_bytes(self, path: str) -> bytes:
        """Read file contents as bytes."""
        return await self._workspace.files.read(path, mode="binary")
    
    async def stats(self) -> WorkspaceStats:
        """Get workspace statistics."""
        file_count = 0
        dir_count = 0
        total_bytes = 0
        
        # Use workspace query/traverse to count
        async for entry in self._workspace.files.traverse("/", recursive=True):
            if entry.is_file:
                file_count += 1
                total_bytes += entry.size if hasattr(entry, "size") else 0
            else:
                dir_count += 1
        
        return WorkspaceStats(
            file_count=file_count,
            dir_count=dir_count,
            total_bytes=total_bytes,
        )
    
    async def diff(self, base_path: Path | str) -> list["FileChange"]:
        """Diff this workspace against another.
        
        Returns list of FileChange objects describing differences.
        """
        from cairn.runtime.workspace_manager import open_workspace
        
        base_workspace = await open_workspace(base_path, readonly=True)
        try:
            return await self._workspace.materialize.diff(base_workspace)
        finally:
            await base_workspace.close()
```

### 2.5 File: `cairn/runtime/state.py` (NEW)

```python
"""Agent state management via workspace KV store."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from fsdantic import Workspace

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AgentStateManager:
    """Manage agent state in workspace KV store.
    
    Provides typed state persistence for agents, with automatic
    namespacing by agent ID to prevent collisions.
    
    Example:
        state = AgentStateManager(workspace, "agent-123")
        
        # Simple key-value
        await state.set("last_file", "/src/main.py")
        path = await state.get("last_file")
        
        # Typed models
        from pydantic import BaseModel
        class TurnState(BaseModel):
            turn: int
            context: dict
        
        await state.set_typed("turn_state", TurnState(turn=1, context={}))
        turn_state = await state.get_typed("turn_state", TurnState)
    """
    
    def __init__(self, workspace: "Workspace", agent_id: str):
        self._workspace = workspace
        self._agent_id = agent_id
        self._prefix = f"agent:{agent_id}:"
    
    @property
    def agent_id(self) -> str:
        """The agent ID this manager is scoped to."""
        return self._agent_id
    
    @property
    def _kv(self):
        """Access underlying KV manager."""
        return self._workspace.kv
    
    def _full_key(self, key: str) -> str:
        """Get namespaced key."""
        return self._prefix + key
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Get state value by key."""
        full_key = self._full_key(key)
        try:
            return await self._kv.get(full_key, default=default)
        except Exception as e:
            logger.debug("Failed to get state %s: %s", key, e)
            return default
    
    async def set(self, key: str, value: Any) -> None:
        """Set state value by key."""
        full_key = self._full_key(key)
        await self._kv.set(full_key, value)
    
    async def delete(self, key: str) -> bool:
        """Delete state value. Returns True if key existed."""
        full_key = self._full_key(key)
        try:
            await self._kv.delete(full_key)
            return True
        except KeyError:
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if state key exists."""
        full_key = self._full_key(key)
        try:
            await self._kv.get(full_key)
            return True
        except KeyError:
            return False
    
    async def list_keys(self) -> list[str]:
        """List all state keys for this agent."""
        entries = await self._kv.list(prefix=self._prefix)
        return [e["key"][len(self._prefix):] for e in entries]
    
    async def get_typed(self, key: str, model: type[T]) -> T | None:
        """Get state as typed Pydantic model."""
        data = await self.get(key)
        if data is None:
            return None
        return model.model_validate(data)
    
    async def set_typed(self, key: str, value: BaseModel) -> None:
        """Set state as typed Pydantic model."""
        await self.set(key, value.model_dump(mode="json"))
    
    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment numeric value and return new value."""
        current = await self.get(key, default=0)
        new_value = current + amount
        await self.set(key, new_value)
        return new_value
    
    async def increment_turn(self) -> int:
        """Increment and return turn counter. Convenience method."""
        return await self.increment("turn")
    
    async def get_turn(self) -> int:
        """Get current turn number."""
        return await self.get("turn", default=0)
    
    async def clear_all(self) -> int:
        """Clear all state for this agent. Returns count deleted."""
        keys = await self.list_keys()
        for key in keys:
            await self.delete(key)
        return len(keys)
    
    async def touch(self) -> None:
        """Update last_active timestamp."""
        await self.set("last_active", datetime.now(timezone.utc).isoformat())
```

### 2.6 File: `cairn/runtime/__init__.py` (EDIT)

Add exports:

```python
# Add to existing exports
from cairn.runtime.workspace_manager import open_workspace
from cairn.runtime.inspection import WorkspaceInspector, WorkspaceStats
from cairn.runtime.state import AgentStateManager

__all__ = [
    # ... existing exports ...
    "open_workspace",
    "WorkspaceInspector", 
    "WorkspaceStats",
    "AgentStateManager",
]
```

### 2.7 File: `cairn/__init__.py` (EDIT)

Add top-level exports:

```python
# Add to imports
from cairn.runtime import (
    open_workspace,
    WorkspaceInspector,
    WorkspaceStats,
    AgentStateManager,
)

# Re-export Workspace type for type hints
from fsdantic import Workspace

__all__ = [
    # ... existing exports ...
    "open_workspace",
    "Workspace",
    "WorkspaceInspector",
    "WorkspaceStats", 
    "AgentStateManager",
]
```

### 2.8 Tests for New APIs

File: `tests/unit/test_workspace_api.py`

```python
"""Tests for new public workspace APIs."""

import pytest
from pathlib import Path

from cairn import open_workspace, WorkspaceInspector, AgentStateManager


class TestOpenWorkspace:
    """Tests for open_workspace function."""
    
    @pytest.mark.asyncio
    async def test_open_workspace_returns_workspace(self, tmp_path: Path):
        """open_workspace should return a Workspace instance."""
        from cairn.runtime.workspace_manager import WorkspaceManager
        
        # Create workspace first
        manager = WorkspaceManager()
        async with manager.open_workspace(tmp_path / "test.db") as ws:
            await ws.files.write("/test.txt", "hello")
        
        # Now open with public API
        workspace = await open_workspace(tmp_path / "test.db")
        try:
            content = await workspace.files.read("/test.txt")
            assert content == "hello"
        finally:
            await workspace.close()
    
    @pytest.mark.asyncio
    async def test_open_workspace_readonly(self, tmp_path: Path):
        """open_workspace readonly mode should prevent writes."""
        from cairn.runtime.workspace_manager import WorkspaceManager
        
        manager = WorkspaceManager()
        async with manager.open_workspace(tmp_path / "test.db") as ws:
            await ws.files.write("/test.txt", "hello")
        
        workspace = await open_workspace(tmp_path / "test.db", readonly=True)
        try:
            # Read should work
            content = await workspace.files.read("/test.txt")
            assert content == "hello"
            
            # Write should fail (implementation dependent)
            # This may raise or silently fail depending on fsdantic
        finally:
            await workspace.close()


class TestWorkspaceInspector:
    """Tests for WorkspaceInspector."""
    
    @pytest.mark.asyncio
    async def test_inspector_tree(self, tmp_path: Path):
        """Inspector should return tree structure."""
        from cairn.runtime.workspace_manager import WorkspaceManager
        
        manager = WorkspaceManager()
        async with manager.open_workspace(tmp_path / "test.db") as ws:
            await ws.files.write("/src/main.py", "print('hello')")
            await ws.files.write("/src/utils.py", "# utils")
            await ws.files.write("/README.md", "# README")
        
        async with await WorkspaceInspector.from_path(tmp_path / "test.db") as inspector:
            tree = await inspector.tree("/")
            assert "children" in tree or "name" in tree
    
    @pytest.mark.asyncio
    async def test_inspector_stats(self, tmp_path: Path):
        """Inspector should return stats."""
        from cairn.runtime.workspace_manager import WorkspaceManager
        
        manager = WorkspaceManager()
        async with manager.open_workspace(tmp_path / "test.db") as ws:
            await ws.files.write("/a.txt", "aaa")
            await ws.files.write("/b.txt", "bbbbb")
        
        async with await WorkspaceInspector.from_path(tmp_path / "test.db") as inspector:
            stats = await inspector.stats()
            assert stats.file_count >= 2
            assert stats.total_bytes >= 8


class TestAgentStateManager:
    """Tests for AgentStateManager."""
    
    @pytest.mark.asyncio
    async def test_state_get_set(self, tmp_path: Path):
        """State manager should get and set values."""
        from cairn.runtime.workspace_manager import WorkspaceManager
        
        manager = WorkspaceManager()
        async with manager.open_workspace(tmp_path / "test.db") as ws:
            state = AgentStateManager(ws, "test-agent")
            
            await state.set("key1", "value1")
            result = await state.get("key1")
            assert result == "value1"
    
    @pytest.mark.asyncio
    async def test_state_increment_turn(self, tmp_path: Path):
        """State manager should increment turn counter."""
        from cairn.runtime.workspace_manager import WorkspaceManager
        
        manager = WorkspaceManager()
        async with manager.open_workspace(tmp_path / "test.db") as ws:
            state = AgentStateManager(ws, "test-agent")
            
            turn1 = await state.increment_turn()
            turn2 = await state.increment_turn()
            turn3 = await state.get_turn()
            
            assert turn1 == 1
            assert turn2 == 2
            assert turn3 == 2
    
    @pytest.mark.asyncio
    async def test_state_namespacing(self, tmp_path: Path):
        """Different agents should have isolated state."""
        from cairn.runtime.workspace_manager import WorkspaceManager
        
        manager = WorkspaceManager()
        async with manager.open_workspace(tmp_path / "test.db") as ws:
            state1 = AgentStateManager(ws, "agent-1")
            state2 = AgentStateManager(ws, "agent-2")
            
            await state1.set("key", "value1")
            await state2.set("key", "value2")
            
            assert await state1.get("key") == "value1"
            assert await state2.get("key") == "value2"
```

### 2.9 Tasks

| Task | Status | File | Target |
|------|--------|------|--------|
| Add `open_workspace()` function | Pending | `cairn/runtime/workspace_manager.py` | Cairn |
| Create `cairn/runtime/inspection.py` | Pending | - | Cairn |
| Create `cairn/runtime/state.py` | Pending | - | Cairn |
| Update `cairn/runtime/__init__.py` exports | Pending | - | Cairn |
| Update `cairn/__init__.py` exports | Pending | - | Cairn |
| Add tests for new APIs | Pending | `tests/unit/test_workspace_api.py` | Cairn |
| Run Cairn test suite | Pending | - | Cairn |
| Commit Cairn changes | Pending | - | Cairn |

---

## 3. Phase 1: CLI Wrappers

### 3.1 Goal

Add `remora workspace <command>` CLI commands for workspace inspection and materialization.

### 3.2 Commands to Implement

| Command | Description | fsdantic API |
|---------|-------------|--------------|
| `tree` | Print directory tree | `FileManager.tree()` |
| `ls` | List directory contents | `FileManager.list_dir()` |
| `cat` | Print file contents | `FileManager.read()` |
| `diff` | Show changes between workspaces | `MaterializationManager.diff()` |
| `stats` | Show workspace statistics | `FileManager.query()` |
| `materialize` | Extract workspace to disk | `MaterializationManager.to_disk()` |

### 3.3 File: `src/remora/cli/workspace.py`

```python
"""Workspace inspection CLI commands."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

import click

from remora.core.config import load_config


@click.group()
def workspace() -> None:
    """Workspace inspection and management commands."""
    pass


@workspace.command()
@click.argument("db_path", type=click.Path(exists=True))
@click.option("--depth", "-d", type=int, default=None, help="Maximum depth")
@click.option("--format", "-f", "fmt", type=click.Choice(["tree", "json", "flat"]), default="tree")
def tree(db_path: str, depth: int | None, fmt: str) -> None:
    """Print directory tree of workspace."""
    asyncio.run(_tree_impl(Path(db_path), depth, fmt))


async def _tree_impl(db_path: Path, depth: int | None, fmt: str) -> None:
    from remora.workspace.inspector import WorkspaceInspector
    
    async with WorkspaceInspector(db_path) as inspector:
        result = await inspector.tree("/", max_depth=depth)
        
        if fmt == "json":
            click.echo(json.dumps(result, indent=2))
        elif fmt == "flat":
            for path in _flatten_tree(result):
                click.echo(path)
        else:
            click.echo(_format_tree(result))


@workspace.command()
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("path", default="/")
@click.option("--long", "-l", is_flag=True, help="Show detailed info")
def ls(db_path: str, path: str, long: bool) -> None:
    """List directory contents in workspace."""
    asyncio.run(_ls_impl(Path(db_path), path, long))


async def _ls_impl(db_path: Path, path: str, long: bool) -> None:
    from remora.workspace.inspector import WorkspaceInspector
    
    async with WorkspaceInspector(db_path) as inspector:
        entries = await inspector.list_dir(path, include_stats=long)
        for entry in entries:
            if long and isinstance(entry, dict):
                click.echo(f"{entry.get('size', 0):>10}  {entry['name']}")
            else:
                click.echo(entry if isinstance(entry, str) else entry["name"])


@workspace.command()
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("file_path")
def cat(db_path: str, file_path: str) -> None:
    """Print file contents from workspace."""
    asyncio.run(_cat_impl(Path(db_path), file_path))


async def _cat_impl(db_path: Path, file_path: str) -> None:
    from remora.workspace.inspector import WorkspaceInspector
    
    async with WorkspaceInspector(db_path) as inspector:
        content = await inspector.read(file_path)
        click.echo(content)


@workspace.command()
@click.argument("workspace_path", type=click.Path(exists=True))
@click.argument("base_path", type=click.Path(exists=True))
@click.option("--unified", "-u", is_flag=True, help="Show unified diff")
def diff(workspace_path: str, base_path: str, unified: bool) -> None:
    """Show changes between workspaces."""
    asyncio.run(_diff_impl(Path(workspace_path), Path(base_path), unified))


async def _diff_impl(workspace_path: Path, base_path: Path, unified: bool) -> None:
    from remora.workspace.inspector import WorkspaceInspector
    
    async with WorkspaceInspector(workspace_path) as inspector:
        changes = await inspector.diff(base_path)
        
        for change in changes:
            marker = {"added": "+", "modified": "M", "deleted": "-"}.get(change.change_type, "?")
            click.echo(f"  [{marker}] {change.path}")
            
            if unified and change.change_type == "modified":
                # TODO: Show actual unified diff
                click.echo(f"      (content diff not yet implemented)")


@workspace.command()
@click.argument("db_path", type=click.Path(exists=True))
def stats(db_path: str) -> None:
    """Show workspace statistics."""
    asyncio.run(_stats_impl(Path(db_path)))


async def _stats_impl(db_path: Path) -> None:
    from remora.workspace.inspector import WorkspaceInspector
    
    async with WorkspaceInspector(db_path) as inspector:
        stats = await inspector.stats()
        click.echo(f"Files:       {stats['file_count']}")
        click.echo(f"Directories: {stats['dir_count']}")
        click.echo(f"Total size:  {stats['total_bytes']:,} bytes")


@workspace.command()
@click.argument("db_path", type=click.Path(exists=True))
@click.argument("output_dir", type=click.Path())
@click.option("--base", type=click.Path(exists=True), help="Base workspace for overlay diff")
@click.option("--changes-only", is_flag=True, help="Only extract changed files")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing directory")
def materialize(
    db_path: str,
    output_dir: str,
    base: str | None,
    changes_only: bool,
    force: bool,
) -> None:
    """Extract workspace to disk."""
    asyncio.run(_materialize_impl(Path(db_path), Path(output_dir), Path(base) if base else None, changes_only, force))


async def _materialize_impl(
    db_path: Path,
    output_dir: Path,
    base_path: Path | None,
    changes_only: bool,
    force: bool,
) -> None:
    from remora.workspace.inspector import WorkspaceInspector
    
    if output_dir.exists() and not force:
        click.echo(f"Error: {output_dir} exists. Use --force to overwrite.", err=True)
        raise SystemExit(1)
    
    async with WorkspaceInspector(db_path) as inspector:
        result = await inspector.materialize(
            output_dir,
            base_path=base_path,
            changes_only=changes_only,
        )
        click.echo(f"Extracted {result.files_written} files ({result.bytes_written:,} bytes)")


def _format_tree(node: dict, prefix: str = "", is_last: bool = True) -> str:
    """Format tree node as ASCII tree."""
    lines = []
    connector = "└── " if is_last else "├── "
    
    name = node.get("name", "/")
    if node.get("type") == "file":
        size = node.get("size", 0)
        lines.append(f"{prefix}{connector}{name} ({size} B)")
    else:
        lines.append(f"{prefix}{connector}{name}/")
    
    children = node.get("children", [])
    child_prefix = prefix + ("    " if is_last else "│   ")
    
    for i, child in enumerate(children):
        is_child_last = i == len(children) - 1
        lines.append(_format_tree(child, child_prefix, is_child_last))
    
    return "\n".join(lines)


def _flatten_tree(node: dict, prefix: str = "") -> list[str]:
    """Flatten tree to list of paths."""
    paths = []
    path = prefix + "/" + node.get("name", "") if prefix else node.get("path", "/")
    
    if node.get("type") == "file":
        paths.append(path)
    
    for child in node.get("children", []):
        paths.extend(_flatten_tree(child, path if path != "/" else ""))
    
    return paths
```

### 3.4 File: `src/remora/workspace/__init__.py`

```python
"""Workspace utilities package."""

from remora.workspace.inspector import WorkspaceInspector

__all__ = ["WorkspaceInspector"]
```

### 3.5 File: `src/remora/workspace/inspector.py`

```python
"""Workspace inspection utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fsdantic import Workspace
from fsdantic.materialization import FileChange, MaterializationResult


@dataclass
class WorkspaceStats:
    """Workspace statistics."""
    file_count: int
    dir_count: int
    total_bytes: int


class WorkspaceInspector:
    """Read-only workspace inspection utilities.
    
    Wraps fsdantic Workspace with convenient inspection methods.
    Designed for CLI and debugging use.
    """
    
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._workspace: Workspace | None = None
    
    async def __aenter__(self) -> "WorkspaceInspector":
        from agentfs_sdk import AgentFS
        
        raw = await AgentFS.open(str(self._db_path), mode="r")
        self._workspace = Workspace(raw)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._workspace:
            await self._workspace.close()
            self._workspace = None
    
    @property
    def workspace(self) -> Workspace:
        if self._workspace is None:
            raise RuntimeError("Inspector not initialized. Use 'async with'.")
        return self._workspace
    
    async def tree(self, path: str = "/", max_depth: int | None = None) -> dict[str, Any]:
        """Get directory tree structure."""
        return await self.workspace.files.tree(path, max_depth=max_depth)
    
    async def list_dir(
        self,
        path: str = "/",
        include_stats: bool = False,
    ) -> list[str] | list[dict[str, Any]]:
        """List directory contents."""
        if include_stats:
            entries = []
            for name in await self.workspace.files.list_dir(path, output="name"):
                full_path = f"{path.rstrip('/')}/{name}"
                try:
                    stat = await self.workspace.files.stat(full_path)
                    entries.append({
                        "name": name,
                        "size": stat.size,
                        "type": "file" if stat.is_file else "directory",
                    })
                except Exception:
                    entries.append({"name": name, "size": 0, "type": "unknown"})
            return entries
        return await self.workspace.files.list_dir(path, output="name")
    
    async def read(self, path: str) -> str:
        """Read file contents."""
        return await self.workspace.files.read(path, mode="text")
    
    async def diff(self, base_path: Path) -> list[FileChange]:
        """Diff this workspace against another."""
        from agentfs_sdk import AgentFS
        
        base_raw = await AgentFS.open(str(base_path), mode="r")
        base_workspace = Workspace(base_raw)
        
        try:
            return await self.workspace.materialize.diff(base_workspace)
        finally:
            await base_workspace.close()
    
    async def stats(self) -> dict[str, int]:
        """Get workspace statistics."""
        file_count = 0
        dir_count = 0
        total_bytes = 0
        
        async for path, stat in self.workspace.files.traverse_files("/", recursive=True, include_stats=True):
            if stat and stat.is_file:
                file_count += 1
                total_bytes += stat.size
            else:
                dir_count += 1
        
        return {
            "file_count": file_count,
            "dir_count": dir_count,
            "total_bytes": total_bytes,
        }
    
    async def materialize(
        self,
        output_dir: Path,
        base_path: Path | None = None,
        changes_only: bool = False,
    ) -> MaterializationResult:
        """Extract workspace to disk."""
        from fsdantic.materialization import Materializer
        
        base_fs = None
        if base_path:
            from agentfs_sdk import AgentFS
            base_raw = await AgentFS.open(str(base_path), mode="r")
            base_fs = base_raw
        
        try:
            materializer = Materializer()
            return await materializer.materialize(
                agent_fs=self.workspace.raw,
                target_path=output_dir,
                base_fs=base_fs,
                clean=True,
            )
        finally:
            if base_fs:
                await base_fs.close()
```

### 3.6 Wire CLI into main.py

**Edit:** `src/remora/cli/main.py`

Add import and register the workspace group:

```python
# After existing imports, add:
from remora.cli.workspace import workspace

# After main() definition, add:
main.add_command(workspace)
```

### 3.7 Tasks

| Task | Status | File |
|------|--------|------|
| Create `src/remora/workspace/` directory | Pending | - |
| Create `src/remora/workspace/__init__.py` | Pending | - |
| Create `src/remora/workspace/inspector.py` | Pending | - |
| Create `src/remora/cli/workspace.py` | Pending | - |
| Wire workspace group into main CLI | Pending | `cli/main.py` |
| Add tests for inspector | Pending | `tests/unit/test_workspace_inspector.py` |
| Add integration tests | Pending | `tests/integration/test_workspace_cli.py` |

---

## 4. Phase 2: WorkspaceProtocol

### 3.1 Goal

Define abstract `WorkspaceProtocol` interface for testability without real Cairn.

### 3.2 File: `src/remora/core/protocols.py`

```python
"""Protocol definitions for dependency injection and testing."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WorkspaceProtocol(Protocol):
    """Abstract workspace interface for file operations.
    
    Enables unit testing without real Cairn workspace.
    Implementations: AgentWorkspace (real), MockWorkspace (test)
    """
    
    async def read(self, path: str) -> str:
        """Read file contents as text."""
        ...
    
    async def write(self, path: str, content: str | bytes) -> None:
        """Write file contents."""
        ...
    
    async def exists(self, path: str) -> bool:
        """Check if file exists."""
        ...
    
    async def list_dir(self, path: str = ".") -> list[str]:
        """List directory entries."""
        ...
    
    async def delete(self, path: str) -> None:
        """Delete a file."""
        ...
    
    async def mkdir(self, path: str) -> None:
        """Create directory."""
        ...


@runtime_checkable
class KVStoreProtocol(Protocol):
    """Abstract KV store interface.
    
    Enables agent state persistence and testing.
    """
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Get value by key."""
        ...
    
    async def set(self, key: str, value: Any) -> None:
        """Set value by key."""
        ...
    
    async def delete(self, key: str) -> bool:
        """Delete key, return True if existed."""
        ...
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        ...
    
    async def list_keys(self, prefix: str = "") -> list[str]:
        """List keys with optional prefix filter."""
        ...
```

### 3.3 File: `src/remora/testing/mock_workspace.py`

```python
"""Mock workspace for unit testing."""

from __future__ import annotations

from typing import Any


class MockWorkspace:
    """In-memory workspace for unit testing.
    
    Implements WorkspaceProtocol without Cairn dependency.
    """
    
    def __init__(self, files: dict[str, str] | None = None):
        self._files: dict[str, str | bytes] = dict(files or {})
        self._dirs: set[str] = {"/"}
    
    async def read(self, path: str) -> str:
        path = self._normalize(path)
        if path not in self._files:
            raise FileNotFoundError(path)
        content = self._files[path]
        return content if isinstance(content, str) else content.decode("utf-8")
    
    async def write(self, path: str, content: str | bytes) -> None:
        path = self._normalize(path)
        self._ensure_parent_dirs(path)
        self._files[path] = content
    
    async def exists(self, path: str) -> bool:
        path = self._normalize(path)
        return path in self._files or path in self._dirs
    
    async def list_dir(self, path: str = ".") -> list[str]:
        path = self._normalize(path)
        if not path.endswith("/"):
            path += "/"
        
        entries = set()
        for file_path in self._files:
            if file_path.startswith(path):
                remainder = file_path[len(path):]
                if "/" in remainder:
                    entries.add(remainder.split("/")[0])
                else:
                    entries.add(remainder)
        
        return sorted(entries)
    
    async def delete(self, path: str) -> None:
        path = self._normalize(path)
        if path in self._files:
            del self._files[path]
        elif path in self._dirs:
            self._dirs.remove(path)
    
    async def mkdir(self, path: str) -> None:
        path = self._normalize(path)
        self._dirs.add(path)
    
    def _normalize(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return path.rstrip("/") if path != "/" else path
    
    def _ensure_parent_dirs(self, path: str) -> None:
        parts = path.split("/")
        for i in range(1, len(parts)):
            self._dirs.add("/".join(parts[:i]) or "/")


class MockKVStore:
    """In-memory KV store for unit testing."""
    
    def __init__(self, data: dict[str, Any] | None = None):
        self._data: dict[str, Any] = dict(data or {})
    
    async def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)
    
    async def set(self, key: str, value: Any) -> None:
        self._data[key] = value
    
    async def delete(self, key: str) -> bool:
        if key in self._data:
            del self._data[key]
            return True
        return False
    
    async def exists(self, key: str) -> bool:
        return key in self._data
    
    async def list_keys(self, prefix: str = "") -> list[str]:
        return [k for k in self._data if k.startswith(prefix)]
```

### 3.4 Update AgentWorkspace

**Edit:** `src/remora/core/workspace.py`

Ensure `AgentWorkspace` implements `WorkspaceProtocol`:

```python
# Add to imports
from remora.core.protocols import WorkspaceProtocol

# Update class docstring to note protocol compliance
class AgentWorkspace:
    """Workspace for a single agent execution.
    
    Wraps a Cairn workspace with agent-specific convenience methods.
    Implements WorkspaceProtocol for testability.
    """
    
    # Add missing methods if needed:
    
    async def delete(self, path: PathLike) -> None:
        """Delete a file from the workspace."""
        path_str = normalize_path(path).as_posix()
        async with self._lock:
            await self._workspace.files.delete(path_str)
    
    async def mkdir(self, path: PathLike) -> None:
        """Create a directory in the workspace."""
        path_str = normalize_path(path).as_posix()
        async with self._lock:
            await self._workspace.files.mkdir(path_str)
```

### 3.5 Tasks

| Task | Status | File |
|------|--------|------|
| Create `src/remora/core/protocols.py` | Pending | - |
| Create `src/remora/testing/mock_workspace.py` | Pending | - |
| Create `src/remora/testing/__init__.py` | Pending | - |
| Update `AgentWorkspace` with protocol methods | Pending | `core/workspace.py` |
| Add protocol conformance tests | Pending | `tests/unit/test_protocols.py` |

---

## 5. Phase 3: KV Store Integration

### 4.1 Goal

Use Cairn's KV store for agent state persistence between turns.

### 4.2 State Model

```python
# src/remora/core/agent_state.py

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentTurnState(BaseModel):
    """State persisted between agent turns."""
    
    turn_number: int = 0
    last_response: str | None = None
    last_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    accumulated_context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentMemory(BaseModel):
    """Long-term agent memory stored in KV."""
    
    facts: list[str] = Field(default_factory=list)
    learned_patterns: dict[str, str] = Field(default_factory=dict)
    file_summaries: dict[str, str] = Field(default_factory=dict)
```

### 4.3 File: `src/remora/core/state_manager.py`

```python
"""Agent state persistence via Cairn KV store."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from remora.core.workspace import AgentWorkspace

logger = logging.getLogger(__name__)


class AgentStateManager:
    """Manages agent state persistence in Cairn KV store.
    
    Uses typed repositories for structured state storage.
    """
    
    def __init__(self, workspace: "AgentWorkspace", agent_id: str):
        self._workspace = workspace
        self._agent_id = agent_id
        self._prefix = f"agent:{agent_id}:"
    
    @property
    def _kv(self):
        """Access underlying KV manager."""
        return self._workspace.cairn.kv
    
    async def get_state(self, key: str, default: Any = None) -> Any:
        """Get state value by key."""
        full_key = self._prefix + key
        try:
            return await self._kv.get(full_key, default=default)
        except Exception as e:
            logger.debug("Failed to get state %s: %s", key, e)
            return default
    
    async def set_state(self, key: str, value: Any) -> None:
        """Set state value by key."""
        full_key = self._prefix + key
        await self._kv.set(full_key, value)
    
    async def delete_state(self, key: str) -> bool:
        """Delete state value."""
        full_key = self._prefix + key
        return await self._kv.delete(full_key)
    
    async def list_keys(self) -> list[str]:
        """List all state keys for this agent."""
        entries = await self._kv.list(prefix=self._prefix)
        return [e["key"][len(self._prefix):] for e in entries]
    
    async def get_typed[T: BaseModel](self, key: str, model: type[T]) -> T | None:
        """Get state as typed Pydantic model."""
        data = await self.get_state(key)
        if data is None:
            return None
        return model.model_validate(data)
    
    async def set_typed[T: BaseModel](self, key: str, value: T) -> None:
        """Set state as typed Pydantic model."""
        await self.set_state(key, value.model_dump(mode="json"))
    
    async def increment_turn(self) -> int:
        """Increment and return turn counter."""
        turn = await self.get_state("turn", default=0)
        turn += 1
        await self.set_state("turn", turn)
        return turn
    
    async def clear_all(self) -> int:
        """Clear all state for this agent. Returns count deleted."""
        keys = await self.list_keys()
        for key in keys:
            await self.delete_state(key)
        return len(keys)
```

### 4.4 Integration with AgentContext

**Edit:** `src/remora/core/agent_context.py`

Add state manager field:

```python
# Add to imports
from remora.core.state_manager import AgentStateManager

# Add field to AgentContext
class AgentContext(BaseModel):
    # ... existing fields ...
    
    # State manager for persistence (optional)
    state_manager: AgentStateManager | None = None
```

### 4.5 Integration with SwarmExecutor

**Edit:** `src/remora/core/swarm_executor.py` or `execution.py`

Add state manager initialization:

```python
# In execute_agent_turn or run_agent, after getting workspace:
state_manager = AgentStateManager(agent_workspace, node.node_id)
turn = await state_manager.increment_turn()
logger.debug("Agent %s starting turn %d", node.node_id, turn)

# Pass to context
context = AgentContext(
    agent_id=node.node_id,
    # ... other fields ...
    state_manager=state_manager,
)
```

### 4.6 Tasks

| Task | Status | File |
|------|--------|------|
| Create `src/remora/core/agent_state.py` | Pending | - |
| Create `src/remora/core/state_manager.py` | Pending | - |
| Update `AgentContext` with state_manager | Pending | `core/agent_context.py` |
| Integrate state manager in execution | Pending | `core/execution.py` |
| Add unit tests for state manager | Pending | `tests/unit/test_state_manager.py` |
| Add integration tests | Pending | `tests/integration/cairn/test_state_persistence.py` |

---

## 6. Phase 4: Private API Fix

### 5.1 Goal

Replace usage of `cairn_workspace_manager._open_workspace()` with public API.

### 5.2 Current Problem

```python
# cairn_bridge.py:78
self._stable_workspace = await cairn_workspace_manager._open_workspace(
    stable_path,
    readonly=False,
)
```

The underscore prefix indicates this is a private API that may change.

### 5.3 Investigation Required

Check Cairn source for public alternatives:

```bash
# Look for public workspace opening API in Cairn
grep -r "def open" /home/andrew/Documents/Projects/remora/.context/cairn/
grep -r "async def open" /home/andrew/Documents/Projects/remora/.context/cairn/
```

### 5.4 Potential Solutions

**Option A:** If public API exists, use it:
```python
# Replace _open_workspace with public API
self._stable_workspace = await cairn_workspace_manager.open_workspace(stable_path)
```

**Option B:** If no public API, wrap and document:
```python
# cairn_bridge.py

async def _open_cairn_workspace(path: Path, readonly: bool = False) -> Any:
    """Open Cairn workspace using best available API.
    
    NOTE: Currently uses private _open_workspace API.
    Tracked issue: Pin Cairn version until public API available.
    """
    # Try public API first (when available)
    if hasattr(cairn_workspace_manager, "open_workspace"):
        return await cairn_workspace_manager.open_workspace(path, readonly=readonly)
    
    # Fall back to private API with warning
    import warnings
    warnings.warn(
        "Using private Cairn API _open_workspace. "
        "This may break on Cairn updates.",
        DeprecationWarning,
        stacklevel=2,
    )
    return await cairn_workspace_manager._open_workspace(path, readonly=readonly)
```

**Option C:** Request API from Cairn maintainers, document dependency:
```python
# pyproject.toml - pin Cairn version until API stable
cairn = { git = "...", tag = "v1.2.3" }  # Pinned - uses _open_workspace
```

### 5.5 Tasks

| Task | Status | File |
|------|--------|------|
| Check Cairn source for public API | Pending | - |
| Implement chosen solution | Pending | `core/cairn_bridge.py` |
| Document API dependency | Pending | `CAIRN_API_CONTRACT.md` |
| Add version check/warning | Pending | `core/cairn_bridge.py` |
| Update tests | Pending | - |

---

## 7. Phase 5: Bidirectional Sync

### 6.1 Goal

Enable syncing changes from disk back to workspace.

### 6.2 File: `src/remora/workspace/sync.py`

```python
"""Bidirectional workspace sync utilities."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsdantic import Workspace

logger = logging.getLogger(__name__)


@dataclass
class SyncChange:
    """Represents a change to sync."""
    path: str
    change_type: Literal["added", "modified", "deleted"]
    disk_path: Path | None = None


@dataclass
class SyncResult:
    """Result of sync operation."""
    synced: list[SyncChange]
    skipped: list[SyncChange]
    conflicts: list[SyncChange]
    errors: list[tuple[str, str]]


class WorkspaceSync:
    """Bidirectional sync between disk and workspace."""
    
    def __init__(
        self,
        workspace: Workspace,
        project_root: Path,
    ):
        self._workspace = workspace
        self._project_root = project_root
    
    async def scan_disk_changes(
        self,
        disk_dir: Path,
        workspace_prefix: str = "/",
    ) -> list[SyncChange]:
        """Scan disk directory for changes vs workspace."""
        changes = []
        
        for disk_path in disk_dir.rglob("*"):
            if disk_path.is_dir():
                continue
            
            rel_path = disk_path.relative_to(disk_dir)
            ws_path = f"{workspace_prefix.rstrip('/')}/{rel_path.as_posix()}"
            
            exists = await self._workspace.files.exists(ws_path)
            
            if not exists:
                changes.append(SyncChange(
                    path=ws_path,
                    change_type="added",
                    disk_path=disk_path,
                ))
            else:
                # Check if content differs
                disk_content = disk_path.read_bytes()
                try:
                    ws_content = await self._workspace.files.read(ws_path, mode="binary")
                    if disk_content != ws_content:
                        changes.append(SyncChange(
                            path=ws_path,
                            change_type="modified",
                            disk_path=disk_path,
                        ))
                except Exception:
                    changes.append(SyncChange(
                        path=ws_path,
                        change_type="modified",
                        disk_path=disk_path,
                    ))
        
        return changes
    
    async def sync_from_disk(
        self,
        disk_dir: Path,
        workspace_prefix: str = "/",
        *,
        dry_run: bool = False,
    ) -> SyncResult:
        """Sync changes from disk to workspace."""
        changes = await self.scan_disk_changes(disk_dir, workspace_prefix)
        
        synced = []
        skipped = []
        errors = []
        
        for change in changes:
            if dry_run:
                synced.append(change)
                continue
            
            try:
                if change.disk_path and change.change_type in ("added", "modified"):
                    content = change.disk_path.read_bytes()
                    await self._workspace.files.write(change.path, content, mode="binary")
                    synced.append(change)
                elif change.change_type == "deleted":
                    await self._workspace.files.delete(change.path)
                    synced.append(change)
            except Exception as e:
                errors.append((change.path, str(e)))
        
        return SyncResult(
            synced=synced,
            skipped=skipped,
            conflicts=[],
            errors=errors,
        )
```

### 6.3 CLI Command

Add to `src/remora/cli/workspace.py`:

```python
@workspace.command()
@click.argument("disk_dir", type=click.Path(exists=True))
@click.argument("db_path", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Preview changes without applying")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def sync(disk_dir: str, db_path: str, dry_run: bool, yes: bool) -> None:
    """Sync disk changes to workspace."""
    asyncio.run(_sync_impl(Path(disk_dir), Path(db_path), dry_run, yes))


async def _sync_impl(disk_dir: Path, db_path: Path, dry_run: bool, yes: bool) -> None:
    from agentfs_sdk import AgentFS
    from fsdantic import Workspace
    from remora.workspace.sync import WorkspaceSync
    
    raw = await AgentFS.open(str(db_path), mode="rw")
    workspace = Workspace(raw)
    
    try:
        sync_util = WorkspaceSync(workspace, disk_dir)
        
        # Preview changes
        changes = await sync_util.scan_disk_changes(disk_dir)
        
        if not changes:
            click.echo("No changes to sync.")
            return
        
        click.echo("Changes to sync:")
        for change in changes:
            marker = {"added": "+", "modified": "M", "deleted": "-"}[change.change_type]
            click.echo(f"  [{marker}] {change.path}")
        
        if dry_run:
            click.echo(f"\nDry run: {len(changes)} changes would be synced.")
            return
        
        if not yes:
            if not click.confirm(f"Sync {len(changes)} files?"):
                click.echo("Aborted.")
                return
        
        result = await sync_util.sync_from_disk(disk_dir)
        click.echo(f"Synced {len(result.synced)} files.")
        
        if result.errors:
            click.echo("Errors:")
            for path, error in result.errors:
                click.echo(f"  {path}: {error}")
    
    finally:
        await workspace.close()
```

### 6.4 Tasks

| Task | Status | File |
|------|--------|------|
| Create `src/remora/workspace/sync.py` | Pending | - |
| Add `sync` command to CLI | Pending | `cli/workspace.py` |
| Add unit tests | Pending | `tests/unit/test_workspace_sync.py` |
| Add integration tests | Pending | `tests/integration/test_workspace_sync.py` |

---

## 8. Phase 6: Container Sandbox

### 7.1 Goal

Execute workspace code in isolated Docker/Podman containers.

### 7.2 File: `src/remora/workspace/sandbox.py`

```python
"""Container sandbox for workspace execution."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class SandboxConfig:
    """Configuration for sandbox container."""
    
    image: str = "python:3.12-slim"
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    timeout: float = 300.0
    network: bool = False
    read_only: bool = False
    env: dict[str, str] = field(default_factory=dict)
    workdir: str = "/workspace"


@dataclass
class ExecutionResult:
    """Result of command execution in sandbox."""
    
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False


class ContainerRuntime:
    """Abstract container runtime interface."""
    
    async def run(
        self,
        image: str,
        command: list[str],
        *,
        volumes: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
        workdir: str = "/workspace",
        memory: str = "512m",
        cpus: float = 1.0,
        network: bool = False,
        timeout: float = 300.0,
    ) -> ExecutionResult:
        raise NotImplementedError


class DockerRuntime(ContainerRuntime):
    """Docker-based container runtime."""
    
    async def run(
        self,
        image: str,
        command: list[str],
        *,
        volumes: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
        workdir: str = "/workspace",
        memory: str = "512m",
        cpus: float = 1.0,
        network: bool = False,
        timeout: float = 300.0,
    ) -> ExecutionResult:
        import time
        
        cmd = ["docker", "run", "--rm"]
        
        # Resource limits
        cmd.extend(["--memory", memory])
        cmd.extend(["--cpus", str(cpus)])
        
        # Network
        if not network:
            cmd.extend(["--network", "none"])
        
        # Security
        cmd.append("--no-new-privileges")
        
        # Working directory
        cmd.extend(["--workdir", workdir])
        
        # Volumes
        for host_path, container_path in (volumes or {}).items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])
        
        # Environment
        for key, value in (env or {}).items():
            cmd.extend(["-e", f"{key}={value}"])
        
        # Image and command
        cmd.append(image)
        cmd.extend(command)
        
        start = time.monotonic()
        timed_out = False
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                timed_out = True
                stdout = b""
                stderr = b"Execution timed out"
            
            duration = time.monotonic() - start
            
            return ExecutionResult(
                exit_code=proc.returncode or -1,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                duration=duration,
                timed_out=timed_out,
            )
        
        except FileNotFoundError:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="Docker not found. Install Docker to use sandbox.",
                duration=0.0,
            )


class WorkspaceSandbox:
    """Container sandbox for workspace code execution.
    
    Materializes workspace to temp directory, runs commands in container,
    optionally syncs changes back.
    """
    
    def __init__(
        self,
        workspace_path: Path,
        config: SandboxConfig | None = None,
        runtime: ContainerRuntime | None = None,
    ):
        self._workspace_path = workspace_path
        self._config = config or SandboxConfig()
        self._runtime = runtime or DockerRuntime()
        self._temp_dir: Path | None = None
        self._workspace = None
    
    async def __aenter__(self) -> "WorkspaceSandbox":
        from agentfs_sdk import AgentFS
        from fsdantic import Workspace
        from fsdantic.materialization import Materializer
        
        # Create temp directory
        self._temp_dir = Path(tempfile.mkdtemp(prefix="remora-sandbox-"))
        
        # Materialize workspace
        raw = await AgentFS.open(str(self._workspace_path), mode="r")
        self._workspace = Workspace(raw)
        
        materializer = Materializer()
        await materializer.materialize(
            agent_fs=self._workspace.raw,
            target_path=self._temp_dir,
            clean=True,
        )
        
        logger.debug("Materialized workspace to %s", self._temp_dir)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._workspace:
            await self._workspace.close()
        
        if self._temp_dir and self._temp_dir.exists():
            shutil.rmtree(self._temp_dir)
    
    @property
    def workdir(self) -> Path:
        """Local path to materialized workspace."""
        if self._temp_dir is None:
            raise RuntimeError("Sandbox not initialized")
        return self._temp_dir
    
    async def exec(
        self,
        command: str | list[str],
        *,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Execute command in sandbox container."""
        if self._temp_dir is None:
            raise RuntimeError("Sandbox not initialized")
        
        if isinstance(command, str):
            cmd_list = ["sh", "-c", command]
        else:
            cmd_list = list(command)
        
        return await self._runtime.run(
            image=self._config.image,
            command=cmd_list,
            volumes={str(self._temp_dir): self._config.workdir},
            env=self._config.env,
            workdir=self._config.workdir,
            memory=self._config.memory_limit,
            cpus=self._config.cpu_limit,
            network=self._config.network,
            timeout=timeout or self._config.timeout,
        )
    
    async def sync_back(self) -> list[str]:
        """Sync container changes back to workspace.
        
        Returns list of modified paths.
        """
        if self._temp_dir is None or self._workspace is None:
            raise RuntimeError("Sandbox not initialized")
        
        from remora.workspace.sync import WorkspaceSync
        
        sync_util = WorkspaceSync(self._workspace, self._temp_dir)
        result = await sync_util.sync_from_disk(self._temp_dir)
        
        return [c.path for c in result.synced]
```

### 7.3 CLI Command

Add to `src/remora/cli/workspace.py`:

```python
@workspace.command()
@click.argument("db_path", type=click.Path(exists=True))
@click.option("--exec", "-e", "exec_cmd", help="Command to execute")
@click.option("--image", default="python:3.12-slim", help="Container image")
@click.option("--memory", default="512m", help="Memory limit")
@click.option("--timeout", default=300.0, type=float, help="Timeout in seconds")
@click.option("--network", is_flag=True, help="Enable network access")
@click.option("--sync-back", is_flag=True, help="Sync changes back to workspace")
def sandbox(
    db_path: str,
    exec_cmd: str | None,
    image: str,
    memory: str,
    timeout: float,
    network: bool,
    sync_back: bool,
) -> None:
    """Run workspace in container sandbox."""
    asyncio.run(_sandbox_impl(
        Path(db_path), exec_cmd, image, memory, timeout, network, sync_back
    ))


async def _sandbox_impl(
    db_path: Path,
    exec_cmd: str | None,
    image: str,
    memory: str,
    timeout: float,
    network: bool,
    sync_back: bool,
) -> None:
    from remora.workspace.sandbox import WorkspaceSandbox, SandboxConfig
    
    config = SandboxConfig(
        image=image,
        memory_limit=memory,
        timeout=timeout,
        network=network,
    )
    
    async with WorkspaceSandbox(db_path, config) as sandbox:
        click.echo(f"Sandbox ready at {sandbox.workdir}")
        
        if exec_cmd:
            result = await sandbox.exec(exec_cmd)
            
            if result.stdout:
                click.echo(result.stdout)
            if result.stderr:
                click.echo(result.stderr, err=True)
            
            click.echo(f"\nExit code: {result.exit_code}")
            click.echo(f"Duration: {result.duration:.2f}s")
            
            if result.timed_out:
                click.echo("(timed out)")
        else:
            # Interactive mode - just show path and wait
            click.echo("Press Ctrl+C to exit")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
        
        if sync_back:
            changed = await sandbox.sync_back()
            click.echo(f"Synced {len(changed)} files back to workspace")
```

### 7.4 Tasks

| Task | Status | File |
|------|--------|------|
| Create `src/remora/workspace/sandbox.py` | Pending | - |
| Add `sandbox` command to CLI | Pending | `cli/workspace.py` |
| Add docker dependency to pyproject.toml | Pending | `pyproject.toml` |
| Add unit tests (with mock runtime) | Pending | `tests/unit/test_sandbox.py` |
| Add integration tests | Pending | `tests/integration/test_sandbox.py` |

---

## 9. Phase 7: Validation Harness

### 8.1 Goal

Automated validation of agent-generated code.

### 8.2 File: `src/remora/workspace/validation.py`

```python
"""Validation harness for workspace code quality."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from remora.workspace.sandbox import WorkspaceSandbox, SandboxConfig, ExecutionResult

logger = logging.getLogger(__name__)


@dataclass
class ValidationCheck:
    """Result of a single validation check."""
    
    name: str
    passed: bool
    output: str
    duration: float
    error: str | None = None


@dataclass
class ValidationResult:
    """Combined result of all validation checks."""
    
    checks: list[ValidationCheck] = field(default_factory=list)
    
    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)
    
    @property
    def total_duration(self) -> float:
        return sum(c.duration for c in self.checks)
    
    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        return f"{passed}/{total} checks passed in {self.total_duration:.2f}s"


class WorkspaceValidator:
    """Validate agent-generated code in sandbox.
    
    Runs configurable checks: syntax, types, tests, lint.
    """
    
    DEFAULT_CHECKS = ["syntax", "types", "tests", "lint"]
    
    def __init__(
        self,
        workspace_path: Path,
        checks: list[str] | None = None,
        sandbox_config: SandboxConfig | None = None,
    ):
        self._workspace_path = workspace_path
        self._checks = checks or ["syntax"]  # Conservative default
        self._sandbox_config = sandbox_config or SandboxConfig(
            image="python:3.12-slim",
            timeout=120.0,
        )
    
    async def validate(self) -> ValidationResult:
        """Run all configured validation checks."""
        result = ValidationResult()
        
        async with WorkspaceSandbox(self._workspace_path, self._sandbox_config) as sandbox:
            # Install dependencies first if requirements.txt exists
            if (sandbox.workdir / "requirements.txt").exists():
                await sandbox.exec("pip install -r requirements.txt -q")
            
            # Install dev tools
            await sandbox.exec("pip install mypy ruff pytest -q")
            
            for check_name in self._checks:
                check_method = getattr(self, f"_check_{check_name}", None)
                if check_method:
                    check_result = await check_method(sandbox)
                    result.checks.append(check_result)
                else:
                    logger.warning("Unknown check: %s", check_name)
        
        return result
    
    async def _check_syntax(self, sandbox: WorkspaceSandbox) -> ValidationCheck:
        """Check Python syntax with py_compile."""
        exec_result = await sandbox.exec(
            "python -m py_compile $(find . -name '*.py' -type f)"
        )
        
        return ValidationCheck(
            name="syntax",
            passed=exec_result.exit_code == 0,
            output=exec_result.stdout + exec_result.stderr,
            duration=exec_result.duration,
            error=exec_result.stderr if exec_result.exit_code != 0 else None,
        )
    
    async def _check_types(self, sandbox: WorkspaceSandbox) -> ValidationCheck:
        """Check types with mypy."""
        exec_result = await sandbox.exec("mypy . --ignore-missing-imports")
        
        return ValidationCheck(
            name="types",
            passed=exec_result.exit_code == 0,
            output=exec_result.stdout,
            duration=exec_result.duration,
            error=exec_result.stderr if exec_result.exit_code != 0 else None,
        )
    
    async def _check_tests(self, sandbox: WorkspaceSandbox) -> ValidationCheck:
        """Run tests with pytest."""
        exec_result = await sandbox.exec("pytest -q --tb=short")
        
        return ValidationCheck(
            name="tests",
            passed=exec_result.exit_code == 0,
            output=exec_result.stdout,
            duration=exec_result.duration,
            error=exec_result.stderr if exec_result.exit_code != 0 else None,
        )
    
    async def _check_lint(self, sandbox: WorkspaceSandbox) -> ValidationCheck:
        """Lint with ruff."""
        exec_result = await sandbox.exec("ruff check .")
        
        return ValidationCheck(
            name="lint",
            passed=exec_result.exit_code == 0,
            output=exec_result.stdout,
            duration=exec_result.duration,
            error=exec_result.stderr if exec_result.exit_code != 0 else None,
        )
```

### 8.3 CLI Command

Add to `src/remora/cli/workspace.py`:

```python
@workspace.command()
@click.argument("db_path", type=click.Path(exists=True))
@click.option("--checks", "-c", multiple=True, default=["syntax"], help="Checks to run")
@click.option("--all-checks", is_flag=True, help="Run all checks")
@click.option("--image", default="python:3.12-slim", help="Container image")
def validate(db_path: str, checks: tuple[str, ...], all_checks: bool, image: str) -> None:
    """Validate workspace code quality."""
    check_list = list(WorkspaceValidator.DEFAULT_CHECKS) if all_checks else list(checks)
    asyncio.run(_validate_impl(Path(db_path), check_list, image))


async def _validate_impl(db_path: Path, checks: list[str], image: str) -> None:
    from remora.workspace.validation import WorkspaceValidator
    from remora.workspace.sandbox import SandboxConfig
    
    config = SandboxConfig(image=image)
    validator = WorkspaceValidator(db_path, checks=checks, sandbox_config=config)
    
    click.echo(f"Running checks: {', '.join(checks)}")
    result = await validator.validate()
    
    for check in result.checks:
        status = "PASS" if check.passed else "FAIL"
        click.echo(f"  [{status}] {check.name} ({check.duration:.2f}s)")
        if not check.passed and check.error:
            for line in check.error.split("\n")[:10]:
                click.echo(f"        {line}")
    
    click.echo(f"\n{result.summary()}")
    
    if not result.all_passed:
        raise SystemExit(1)
```

### 8.4 Integration with SwarmExecutor

**Edit:** `src/remora/core/execution.py`

Add optional validation after agent execution:

```python
# At end of execute_agent_turn, optionally validate

if config.validate_agent_output:
    from remora.workspace.validation import WorkspaceValidator
    
    validator = WorkspaceValidator(
        workspace_path=workspace_path,
        checks=config.validation_checks or ["syntax"],
    )
    validation_result = await validator.validate()
    
    if not validation_result.all_passed:
        logger.warning(
            "Agent %s output validation failed: %s",
            node.node_id,
            validation_result.summary(),
        )
        # Optionally emit event or store result
```

### 8.5 Tasks

| Task | Status | File |
|------|--------|------|
| Create `src/remora/workspace/validation.py` | Pending | - |
| Add `validate` command to CLI | Pending | `cli/workspace.py` |
| Add validation config options | Pending | `core/config.py` |
| Integrate validation in execution (optional) | Pending | `core/execution.py` |
| Add unit tests | Pending | `tests/unit/test_validation.py` |
| Add integration tests | Pending | `tests/integration/test_validation.py` |

---

## 10. File Manifest

### 9.1 New Files to Create

| File | Phase | Description |
|------|-------|-------------|
| `src/remora/workspace/__init__.py` | 1 | Package init |
| `src/remora/workspace/inspector.py` | 1 | Workspace inspection |
| `src/remora/workspace/sync.py` | 5 | Bidirectional sync |
| `src/remora/workspace/sandbox.py` | 6 | Container sandbox |
| `src/remora/workspace/validation.py` | 7 | Code validation |
| `src/remora/cli/workspace.py` | 1 | CLI commands |
| `src/remora/core/protocols.py` | 2 | Protocol definitions |
| `src/remora/core/agent_state.py` | 3 | State models |
| `src/remora/core/state_manager.py` | 3 | State persistence |
| `src/remora/testing/__init__.py` | 2 | Test utilities package |
| `src/remora/testing/mock_workspace.py` | 2 | Mock implementations |

### 9.2 Files to Modify

| File | Phase | Changes |
|------|-------|---------|
| `src/remora/cli/main.py` | 1 | Add workspace command group |
| `src/remora/core/workspace.py` | 2 | Add protocol methods |
| `src/remora/core/agent_context.py` | 3 | Add state_manager field |
| `src/remora/core/cairn_bridge.py` | 4 | Fix private API usage |
| `src/remora/core/config.py` | 7 | Add validation config |
| `src/remora/core/execution.py` | 3, 7 | State + validation integration |
| `pyproject.toml` | 6 | Add docker dependency |

### 9.3 New Test Files

| File | Phase | Tests |
|------|-------|-------|
| `tests/unit/test_workspace_inspector.py` | 1 | Inspector unit tests |
| `tests/unit/test_protocols.py` | 2 | Protocol conformance |
| `tests/unit/test_mock_workspace.py` | 2 | Mock implementation |
| `tests/unit/test_state_manager.py` | 3 | State manager |
| `tests/unit/test_workspace_sync.py` | 5 | Sync logic |
| `tests/unit/test_sandbox.py` | 6 | Sandbox with mock runtime |
| `tests/unit/test_validation.py` | 7 | Validation checks |
| `tests/integration/test_workspace_cli.py` | 1 | CLI integration |
| `tests/integration/cairn/test_state_persistence.py` | 3 | State with real Cairn |
| `tests/integration/test_sandbox.py` | 6 | Real Docker tests |

---

## 11. Test Strategy

### 10.1 Unit Tests

- Use `MockWorkspace` and `MockKVStore` for isolation
- Test each component independently
- Mock container runtime for sandbox tests
- No external dependencies required

### 10.2 Integration Tests

- Use real Cairn workspaces (existing fixtures)
- Mark with `@pytest.mark.cairn`
- Container tests marked `@pytest.mark.docker`
- Skip if dependencies unavailable

### 10.3 Test Patterns

```python
# Unit test example
async def test_inspector_tree():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        # Create test workspace
        async with WorkspaceInspector(Path(f.name)) as inspector:
            tree = await inspector.tree("/")
            assert tree["type"] == "directory"

# Integration test with fixture
@pytest.mark.cairn
async def test_state_persistence(workspace_service):
    workspace = await workspace_service.get_agent_workspace("test")
    manager = AgentStateManager(workspace, "test")
    
    await manager.set_state("key", "value")
    assert await manager.get_state("key") == "value"
```

---

## 12. Acceptance Criteria

### 11.1 Phase 1: CLI Wrappers

- [ ] `remora workspace tree <db>` prints directory tree
- [ ] `remora workspace ls <db> <path>` lists directory
- [ ] `remora workspace cat <db> <file>` prints file
- [ ] `remora workspace diff <db1> <db2>` shows changes
- [ ] `remora workspace stats <db>` shows statistics
- [ ] `remora workspace materialize <db> <dir>` extracts files
- [ ] All commands handle errors gracefully

### 11.2 Phase 2: WorkspaceProtocol

- [ ] `WorkspaceProtocol` defined with all methods
- [ ] `AgentWorkspace` implements protocol
- [ ] `MockWorkspace` implements protocol
- [ ] Protocol conformance tests pass
- [ ] Type checker accepts both implementations

### 11.3 Phase 3: KV Store Integration

- [ ] `AgentStateManager` can get/set/delete state
- [ ] State persists across workspace reopening
- [ ] Typed state with Pydantic models works
- [ ] Turn counter increments correctly
- [ ] State manager available in AgentContext

### 11.4 Phase 4: Private API Fix

- [ ] No usage of `_open_workspace` (or documented with warning)
- [ ] Public API used if available
- [ ] Cairn version pinned if necessary
- [ ] API contract documented

### 11.5 Phase 5: Bidirectional Sync

- [ ] `remora workspace sync <dir> <db>` works
- [ ] Added files detected and synced
- [ ] Modified files detected and synced
- [ ] Dry-run mode shows preview
- [ ] Confirmation prompt works

### 11.6 Phase 6: Container Sandbox

- [ ] `remora workspace sandbox <db>` materializes and runs
- [ ] `--exec` runs command and captures output
- [ ] Resource limits (memory, CPU) enforced
- [ ] Network isolation works
- [ ] `--sync-back` syncs changes

### 11.7 Phase 7: Validation Harness

- [ ] `remora workspace validate <db>` runs syntax check
- [ ] `--all-checks` runs syntax, types, tests, lint
- [ ] Results displayed with pass/fail status
- [ ] Exit code reflects validation result
- [ ] Optional integration with agent execution

---

> **REMINDER:**
> - **DO NOT USE SUBAGENTS** - Execute all tasks directly
> - **DO NOT STOP UNTIL COMPLETE** - Continue through all phases
> - **UPDATE PROGRESS.md** - Mark tasks complete as you go
