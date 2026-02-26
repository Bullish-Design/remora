# Implementation Guide for Step 4: Cairn Workspace Layer

## Context

This guide implements **Idea 1: Cairn Replaces All Workspace Abstractions** from the design document (`GROUND_UP_REFACTOR_IDEAS.md`).

The goal is to replace Remora's three workspace abstractions (`WorkspaceKV`, `GraphWorkspace`, `WorkspaceManager`) with thin wrappers around Cairn. Cairn already provides:
- **File isolation** via copy-on-write overlays
- **Shared state** via base layers
- **Snapshot/restore** via built-in snapshot API
- **Workspace lifecycle** management (no orphaned directories)

## Current State (What You're Replacing)

### Files Being Replaced

1. **`src/remora/workspace.py`** (~370 lines)
   - `WorkspaceKV`: File-backed JSON KV store with async locks
   - `GraphWorkspace`: Agent space + shared space partitioning with snapshot/merge
   - `WorkspaceManager`: Creates, caches, lists, deletes workspaces

2. **`src/remora/agent_state.py`** (~170 lines)
   - `AgentKVStore`: Wrapper around `WorkspaceKV` with typed methods for messages, tool results, metadata, and snapshots

### Design Problems Being Fixed

- Three abstractions for what Cairn does natively
- The `asyncio.run()` inside sync method bug in `WorkspaceManager.get_or_create()`
- Orphaned workspace directory problem
- File-backed JSON KV serialization overhead
- `Any` typing on `workspace` throughout the codebase

## Target State

### Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/remora/workspace.py` | MODIFY | Rewrite with CairnDataProvider, CairnResultHandler, factory functions |
| `src/remora/__init__.py` | MODIFY | Update exports |
| `src/remora/agent_state.py` | DELETE | After confirming no remaining imports |

### Dependencies

- `cairn` — workspace isolation and sandboxing (from Bullish-Design GitHub)
- `grail` — virtual filesystem population (from Bullish-Design GitHub)

### What This Preserves

- **File isolation**: Each agent gets a Cairn workspace with CoW overlay
- **Shared state**: Downstream agents see upstream changes via Cairn base layer
- **Snapshot/restore**: Cairn's native snapshot API
- **IPC**: Moved to event-based system (Step 7 of the refactor)

---

## Implementation Steps

### Step 4.1: Rewrite `src/remora/workspace.py`

Replace the entire file content with Cairn wrapper classes:

```python
"""Cairn workspace layer for Remora.

This module provides thin wrappers around Cairn workspaces:
- CairnDataProvider: Populates Grail virtual FS from Cairn workspace
- CairnResultHandler: Writes script results back to Cairn workspace
- Workspace factory functions for agent and shared workspaces
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# TODO: Import actual Cairn types when available
# from cairn import Workspace as CairnWorkspace


@dataclass(frozen=True)
class WorkspaceConfig:
    """Configuration for Cairn workspaces."""
    base_path: Path
    cleanup_after_seconds: int | None = None


class CairnDataProvider:
    """Populates Grail virtual FS from a Cairn workspace.
    
    This class implements the data provider pattern from structured-agents v0.3.
    It reads files from the Cairn workspace to populate the virtual filesystem
    that .pym scripts operate on.
    """
    
    def __init__(self, workspace: Any) -> None:
        """Initialize with a Cairn workspace.
        
        Args:
            workspace: Cairn workspace instance (CairnWorkspace type)
        """
        self._ws = workspace
    
    async def load_files(self, node: Any) -> dict[str, str]:
        """Read the target file + related files from the workspace.
        
        Args:
            node: The CSTNode to load files for. Must have:
                - file_path: str path to the target file
                - related_files: list[str] of related file paths (optional)
                
        Returns:
            Dict mapping virtual file paths to their contents
        """
        files = {}
        
        # Read the main file
        main_path = getattr(node, "file_path", None)
        if main_path:
            try:
                content = await self._ws.read(main_path)
                files[main_path] = content
            except FileNotFoundError:
                files[main_path] = ""
        
        # Read related files based on node metadata
        related = getattr(node, "related_files", None)
        if related:
            for rel_path in related:
                try:
                    content = await self._ws.read(rel_path)
                    files[rel_path] = content
                except FileNotFoundError:
                    files[rel_path] = ""
        
        return files
    
    async def load_file(self, path: str) -> str:
        """Load a single file from the workspace.
        
        Args:
            path: Path to the file relative to workspace root
            
        Returns:
            File contents as string, or empty string if not found
        """
        try:
            return await self._ws.read(path)
        except FileNotFoundError:
            return ""


class CairnResultHandler:
    """Writes script results back to the Cairn workspace.
    
    This class implements the result handler pattern from structured-agents v0.3.
    It processes structured results from .pym scripts and persists them to
    the Cairn workspace.
    """
    
    async def handle(self, result: dict[str, Any], workspace: Any) -> None:
        """Process and persist script results.
        
        Args:
            result: The result dict returned by a .pym script. Common keys:
                - written_file: str path to write
                - content: str content to write
                - lint_fixes: list[dict] of {path, content} fixes
                - deleted_files: list[str] of paths to delete
            workspace: The Cairn workspace to write to
        """
        # Handle file writes
        if "written_file" in result and "content" in result:
            await workspace.write(result["written_file"], result["content"])
        
        # Handle lint fixes - apply them to workspace
        if "lint_fixes" in result:
            for fix in result["lint_fixes"]:
                if "path" in fix and "content" in fix:
                    await workspace.write(fix["path"], fix["content"])
        
        # Handle file deletions
        if "deleted_files" in result:
            for path in result["deleted_files"]:
                await workspace.delete(path)
        
        # Handle test file generation
        if "generated_tests" in result:
            for test_file in result["generated_tests"]:
                if "path" in test_file and "content" in test_file:
                    await workspace.write(test_file["path"], test_file["content"])
    
    async def extract_writes(self, result: dict[str, Any]) -> list[tuple[str, str]]:
        """Extract file writes from a result without persisting.
        
        Useful for preview/dry-run modes.
        
        Args:
            result: The result dict from a .pym script
            
        Returns:
            List of (path, content) tuples
        """
        writes = []
        
        if "written_file" in result and "content" in result:
            writes.append((result["written_file"], result["content"]))
        
        if "lint_fixes" in result:
            for fix in result["lint_fixes"]:
                if "path" in fix and "content" in fix:
                    writes.append((fix["path"], fix["content"]))
        
        if "generated_tests" in result:
            for test_file in result["generated_tests"]:
                if "path" in test_file and "content" in test_file:
                    writes.append((test_file["path"], test_file["content"]))
        
        return writes


async def create_workspace(
    agent_id: str,
    config: WorkspaceConfig,
) -> Any:
    """Create an isolated workspace for a single agent.
    
    The workspace is initialized as a copy-on-write layer on top of
    a shared base (if shared_workspace is provided) or fresh.
    
    Args:
        agent_id: Unique identifier for this agent
        config: Workspace configuration
        
    Returns:
        Cairn workspace instance
    """
    # TODO: Implement actual Cairn workspace creation
    # Example:
    # ws_path = config.base_path / agent_id
    # return await CairnWorkspace.create(path=ws_path)
    raise NotImplementedError("Cairn integration pending")


async def create_shared_workspace(
    graph_id: str,
    config: WorkspaceConfig,
) -> Any:
    """Create a shared workspace for a graph.
    
    This workspace serves as the base layer that agent workspaces
    copy-on-write from. When an agent accepts changes, they
    propagate to this shared layer for downstream agents.
    
    Args:
        graph_id: Unique identifier for this graph
        config: Workspace configuration
        
    Returns:
        Cairn workspace instance (the shared base)
    """
    # TODO: Implement actual Cairn shared workspace creation
    # Example:
    # ws_path = config.base_path / "shared" / graph_id
    # return await CairnWorkspace.create(path=ws_path)
    raise NotImplementedError("Cairn integration pending")


async def snapshot_workspace(
    workspace: Any,
    snapshot_name: str,
) -> str:
    """Create a snapshot of a workspace.
    
    Args:
        workspace: Cairn workspace to snapshot
        snapshot_name: Name for the snapshot
        
    Returns:
        Snapshot identifier
    """
    # TODO: Implement using Cairn's snapshot API
    # Example:
    # return await workspace.snapshot(snapshot_name)
    raise NotImplementedError("Cairn integration pending")


async def restore_workspace(
    workspace: Any,
    snapshot_id: str,
) -> None:
    """Restore a workspace from a snapshot.
    
    Args:
        workspace: Cairn workspace to restore into
        snapshot_id: Identifier of the snapshot to restore
    """
    # TODO: Implement using Cairn's restore API
    # Example:
    # await workspace.restore(snapshot_id)
    raise NotImplementedError("Cairn integration pending")
```

### Step 4.2: Update `src/remora/__init__.py`

Update the exports to reflect the new workspace layer:

```python
"""Remora V2 - Simple, elegant agent graph workflows."""

from remora.agent_graph import AgentGraph, GraphConfig
from remora.config import RemoraConfig
from remora.discovery import CSTNode, TreeSitterDiscoverer
from remora.event_bus import Event, EventBus, get_event_bus
from remora.workspace import (
    CairnDataProvider,
    CairnResultHandler,
    WorkspaceConfig,
    create_workspace,
    create_shared_workspace,
)

__all__ = [
    "AgentGraph",
    "GraphConfig",
    "get_event_bus",
    "EventBus",
    "Event",
    "CSTNode",
    "TreeSitterDiscoverer",
    "RemoraConfig",
    "CairnDataProvider",
    "CairnResultHandler",
    "WorkspaceConfig",
    "create_workspace",
    "create_shared_workspace",
]
```

### Step 4.3: Delete `src/remora/agent_state.py`

After confirming no remaining imports (see verification below), delete this file.

### Step 4.4: Write Tests

Create `tests/unit/test_workspace.py` with the following test cases:

```python
"""Tests for the Cairn workspace layer."""

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestCairnDataProvider:
    """Tests for CairnDataProvider."""
    
    @pytest.fixture
    def mock_workspace(self):
        ws = MagicMock()
        ws.read = AsyncMock()
        return ws
    
    @pytest.fixture
    def provider(self, mock_workspace):
        from remora.workspace import CairnDataProvider
        return CairnDataProvider(mock_workspace)
    
    async def test_load_files_reads_main_file(self, provider, mock_workspace):
        """Test that load_files reads the main file from workspace."""
        mock_workspace.read = AsyncMock(return_value="def foo(): pass")
        
        node = MagicMock()
        node.file_path = "src/foo.py"
        node.related_files = []
        
        files = await provider.load_files(node)
        
        assert "src/foo.py" in files
        assert files["src/foo.py"] == "def foo(): pass"
        mock_workspace.read.assert_called_once_with("src/foo.py")
    
    async def test_load_files_handles_missing_file(self, provider, mock_workspace):
        """Test that missing files return empty string."""
        mock_workspace.read = AsyncMockFileNotFoundError(side_effect=())
        
        node = MagicMock()
        node.file_path = "src/missing.py"
        node.related_files = []
        
        files = await provider.load_files(node)
        
        assert files["src/missing.py"] == ""
    
    async def test_load_files_loads_related_files(self, provider, mock_workspace):
        """Test that related files are also loaded."""
        mock_workspace.read = AsyncMock(side_effect=lambda p: {
            "src/main.py": "def main(): pass",
            "src/config.py": "CONFIG = {}",
        }.get(p, ""))
        
        node = MagicMock()
        node.file_path = "src/main.py"
        node.related_files = ["src/config.py"]
        
        files = await provider.load_files(node)
        
        assert "src/main.py" in files
        assert "src/config.py" in files
    
    async def test_load_file_returns_content(self, provider, mock_workspace):
        """Test loading a single file."""
        mock_workspace.read = AsyncMock(return_value="content here")
        
        content = await provider.load_file("test.txt")
        
        assert content == "content here"
        mock_workspace.read.assert_called_once_with("test.txt")
    
    async def test_load_file_returns_empty_for_missing(self, provider, mock_workspace):
        """Test that load_file returns empty string for missing files."""
        mock_workspace.read = AsyncMock(side_effect=FileNotFoundError())
        
        content = await provider.load_file("missing.txt")
        
        assert content == ""


class TestCairnResultHandler:
    """Tests for CairnResultHandler."""
    
    @pytest.fixture
    def handler(self):
        from remora.workspace import CairnResultHandler
        return CairnResultHandler()
    
    @pytest.fixture
    def mock_workspace(self):
        ws = MagicMock()
        ws.write = AsyncMock()
        ws.delete = AsyncMock()
        return ws
    
    async def test_handle_written_file(self, handler, mock_workspace):
        """Test handling of written_file result."""
        result = {
            "written_file": "output.txt",
            "content": "Hello, world!",
        }
        
        await handler.handle(result, mock_workspace)
        
        mock_workspace.write.assert_called_once_with("output.txt", "Hello, world!")
    
    async def test_handle_lint_fixes(self, handler, mock_workspace):
        """Test handling of lint_fixes result."""
        result = {
            "lint_fixes": [
                {"path": "src/foo.py", "content": "fixed content 1"},
                {"path": "src/bar.py", "content": "fixed content 2"},
            ]
        }
        
        await handler.handle(result, mock_workspace)
        
        assert mock_workspace.write.call_count == 2
        mock_workspace.write.assert_any_call("src/foo.py", "fixed content 1")
        mock_workspace.write.assert_any_call("src/bar.py", "fixed content 2")
    
    async def test_handle_deleted_files(self, handler, mock_workspace):
        """Test handling of deleted_files result."""
        result = {
            "deleted_files": ["temp.txt", "debug.log"],
        }
        
        await handler.handle(result, mock_workspace)
        
        assert mock_workspace.delete.call_count == 2
    
    async def test_handle_generated_tests(self, handler, mock_workspace):
        """Test handling of generated_tests result."""
        result = {
            "generated_tests": [
                {"path": "tests/test_foo.py", "content": "def test_foo(): pass"},
            ]
        }
        
        await handler.handle(result, mock_workspace)
        
        mock_workspace.write.assert_called_once_with(
            "tests/test_foo.py", "def test_foo(): pass"
        )
    
    async def test_extract_writes(self, handler):
        """Test extracting writes without persisting."""
        result = {
            "written_file": "output.txt",
            "content": "Hello!",
            "lint_fixes": [
                {"path": "src/fixed.py", "content": "fixed!"},
            ],
        }
        
        writes = await handler.extract_writes(result)
        
        assert len(writes) == 2
        assert ("output.txt", "Hello!") in writes
        assert ("src/fixed.py", "fixed!") in writes
    
    async def test_handle_empty_result(self, handler, mock_workspace):
        """Test handling of empty result dict."""
        result = {}
        
        await handler.handle(result, mock_workspace)
        
        mock_workspace.write.assert_not_called()
        mock_workspace.delete.assert_not_called()


class TestWorkspaceConfig:
    """Tests for WorkspaceConfig."""
    
    def test_default_values(self):
        """Test default configuration values."""
        from remora.workspace import WorkspaceConfig
        from pathlib import Path
        
        config = WorkspaceConfig(base_path=Path("/tmp/workspaces"))
        
        assert config.base_path == Path("/tmp/workspaces")
        assert config.cleanup_after_seconds is None
    
    def test_with_cleanup(self):
        """Test configuration with cleanup timeout."""
        from remora.workspace import WorkspaceConfig
        from pathlib import Path
        
        config = WorkspaceConfig(
            base_path=Path("/tmp/workspaces"),
            cleanup_after_seconds=3600,
        )
        
        assert config.cleanup_after_seconds == 3600
```

---

## Verification

Run the following verification steps:

```bash
# 1. Check that imports work
python -c "from remora import CairnDataProvider, CairnResultHandler, WorkspaceConfig; print('Import OK')"

# 2. Run the new workspace tests
python -m pytest tests/unit/test_workspace.py -v

# 3. Verify no remaining imports of old modules
grep -r "from remora.workspace import.*WorkspaceKV\|from remora.workspace import.*GraphWorkspace\|from remora.workspace import.*WorkspaceManager" --include="*.py" src/

# 4. Verify no remaining imports of agent_state
grep -r "from remora.agent_state\|import.*agent_state" --include="*.py" src/remora/
```

Expected output for step 1:
```
Import OK
```

Expected output for step 3: No matches (empty result)

Expected output for step 4: Only matches in files scheduled for deletion/modification

---

## Common Pitfalls

1. **Cairn API Differences**: The code above uses placeholder `raise NotImplementedError` for the actual Cairn workspace creation. When Cairn is integrated, the API may differ from this sketch. Check the actual Cairn documentation for:
   - `CairnWorkspace.create()` signature
   - Snapshot/restore methods
   - Read/write/delete methods
   - Copy-on-write overlay setup

2. **DataProvider Related Files**: The `CairnDataProvider` needs to know what "related files" to load. This depends on the `CSTNode` type:
   - For functions: imports, test files
   - For classes: related classes, subclasses
   - For files: config files, test files
   
   The current implementation reads from `node.related_files` — ensure discovery populates this field.

3. **Result Handler Types**: As new .pym script types are created, the `CairnResultHandler` needs to handle their result formats. Keep the handler flexible and add cases as needed.

4. **Workspace Cleanup**: The `WorkspaceConfig.cleanup_after_seconds` field is reserved for future TTL-based cleanup. Cairn may have its own cleanup mechanisms.

---

## Files Summary

### After Step 4

```
src/remora/
├── __init__.py           # Updated exports
├── workspace.py          # Cairn wrappers (NEW)
├── agent_state.py        # DELETED
├── ...
```

### Tests

```
tests/unit/
├── test_workspace.py     # NEW - CairnDataProvider, CairnResultHandler tests
├── ...
```

---

## Next Step

After completing Step 4, proceed to **Step 5: Flatten the Agent Graph** (`graph.py`), which implements Idea 4 from the design document. This separates graph topology (`AgentNode`) from execution (`GraphExecutor`).
