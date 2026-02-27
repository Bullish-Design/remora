# Cairn Integration Test Suite Refactor Guide

## Overview

This guide provides a comprehensive plan for refactoring the Remora integration test suite to fully verify that Cairn (and the underlying fsdantic/AgentFS) provides all desired capabilities. The goal is to ensure copy-on-write isolation, concurrent agent safety, and proper workspace lifecycle management.

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Test Categories](#2-test-categories)
3. [Test Infrastructure](#3-test-infrastructure)
4. [Detailed Test Specifications](#4-detailed-test-specifications)
5. [Implementation Plan](#5-implementation-plan)
6. [Code Templates](#6-code-templates)

---

## 1. Current State Analysis

### 1.1 Existing Test Files

| File | Tests | Cairn Coverage |
|------|-------|----------------|
| `test_smoke_real.py` | 2 | Basic workspace write |
| `test_executor_real.py` | 2 | Tool execution + submission |
| `test_agent_workflow_real.py` | 1 | Concurrent execution |
| `helpers.py` | N/A | `agentfs_available()` check |

### 1.2 What's Tested

- fsdantic can be imported and opened
- Files can be written to agent workspace
- Files can be read back from agent workspace
- Submission records work via KV store
- Concurrent agent execution completes

### 1.3 What's NOT Tested

| Gap | Risk | Priority |
|-----|------|----------|
| Copy-on-write isolation (stable unchanged) | Agent writes corrupt shared state | **Critical** |
| Multi-agent isolation | Agents interfere with each other | **Critical** |
| Read fall-through semantics | Agents can't read base files | **High** |
| Workspace lifecycle (open/close/cleanup) | Resource leaks | **High** |
| Accept/merge functionality | Changes never persist | **Medium** |
| Reject/discard functionality | Can't rollback | **Medium** |
| Concurrent read/write safety | Race conditions | **Medium** |
| Error recovery | Corrupted state on failure | **Medium** |
| Path normalization edge cases | Files written to wrong paths | **Low** |

---

## 2. Test Categories

### 2.1 Category Overview

```
tests/integration/cairn/
├── __init__.py
├── conftest.py                    # Shared fixtures
├── test_workspace_isolation.py    # Copy-on-write isolation
├── test_agent_isolation.py        # Multi-agent isolation
├── test_read_semantics.py         # Read fall-through behavior
├── test_write_semantics.py        # Write isolation behavior
├── test_lifecycle.py              # Open/close/cleanup
├── test_merge_operations.py       # Accept/reject/merge
├── test_concurrent_safety.py      # Race condition tests
├── test_error_recovery.py         # Failure scenarios
├── test_path_resolution.py        # Path edge cases
└── test_kv_operations.py          # KV store (submissions)
```

### 2.2 Test Markers

```python
# pytest markers for selective test execution
pytest.mark.cairn              # All Cairn tests
pytest.mark.cairn_isolation    # Isolation tests
pytest.mark.cairn_concurrent   # Concurrency tests
pytest.mark.cairn_lifecycle    # Lifecycle tests
pytest.mark.cairn_slow         # Long-running tests
```

---

## 3. Test Infrastructure

### 3.1 New Fixtures (conftest.py)

```python
"""Cairn integration test fixtures."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import AsyncIterator, Any

import pytest

from remora.cairn_bridge import CairnWorkspaceService
from remora.config import WorkspaceConfig
from remora.workspace import AgentWorkspace
from remora.utils import PathResolver


@pytest.fixture
def workspace_config(tmp_path: Path) -> WorkspaceConfig:
    """Create a workspace config pointing to temp directory."""
    return WorkspaceConfig(base_path=str(tmp_path / "workspaces"))


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a project root with sample files."""
    root = tmp_path / "project"
    root.mkdir()

    # Create sample structure
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("def main():\n    pass\n")
    (root / "src" / "utils.py").write_text("def helper():\n    return 42\n")
    (root / "README.md").write_text("# Test Project\n")

    return root


@pytest.fixture
async def workspace_service(
    workspace_config: WorkspaceConfig,
    project_root: Path,
) -> AsyncIterator[CairnWorkspaceService]:
    """Create and initialize a CairnWorkspaceService."""
    service = CairnWorkspaceService(
        workspace_config,
        graph_id="test-graph",
        project_root=project_root,
    )
    await service.initialize(sync=True)
    try:
        yield service
    finally:
        await service.close()


@pytest.fixture
async def stable_workspace(workspace_service: CairnWorkspaceService) -> Any:
    """Get the stable workspace from the service."""
    return workspace_service._stable_workspace


@pytest.fixture
async def agent_workspace(
    workspace_service: CairnWorkspaceService,
) -> AsyncIterator[AgentWorkspace]:
    """Create an agent workspace."""
    workspace = await workspace_service.get_agent_workspace("test-agent")
    yield workspace


@pytest.fixture
def path_resolver(project_root: Path) -> PathResolver:
    """Create a path resolver for the project."""
    return PathResolver(project_root)


# Helper functions exposed as fixtures
@pytest.fixture
def list_workspace_files():
    """Factory for listing files in a workspace."""
    async def _list_files(workspace: Any, path: str = "/") -> list[str]:
        try:
            return await workspace.files.list_dir(path, output="name")
        except Exception:
            return []
    return _list_files


@pytest.fixture
def read_workspace_file():
    """Factory for reading files from workspace."""
    async def _read_file(workspace: Any, path: str) -> str | None:
        try:
            return await workspace.files.read(path, mode="text")
        except Exception:
            return None
    return _read_file


@pytest.fixture
def write_workspace_file():
    """Factory for writing files to workspace."""
    async def _write_file(workspace: Any, path: str, content: str) -> bool:
        try:
            await workspace.files.write(path, content)
            return True
        except Exception:
            return False
    return _write_file
```

### 3.2 Helper Module Updates

Add to `tests/integration/helpers.py`:

```python
async def assert_file_exists_in_workspace(
    workspace: Any,
    path: str,
    *,
    expected_content: str | None = None,
) -> None:
    """Assert a file exists in workspace with optional content check."""
    exists = await workspace.files.exists(path)
    assert exists, f"File {path} should exist in workspace"

    if expected_content is not None:
        content = await workspace.files.read(path, mode="text")
        assert content == expected_content, (
            f"File {path} content mismatch: "
            f"expected {expected_content!r}, got {content!r}"
        )


async def assert_file_not_exists_in_workspace(
    workspace: Any,
    path: str,
) -> None:
    """Assert a file does NOT exist in workspace."""
    exists = await workspace.files.exists(path)
    assert not exists, f"File {path} should NOT exist in workspace"


async def get_workspace_file_list(
    workspace: Any,
    path: str = "/",
    *,
    recursive: bool = False,
) -> set[str]:
    """Get set of all files in workspace."""
    files: set[str] = set()

    try:
        entries = await workspace.files.list_dir(path, output="name")
    except Exception:
        return files

    for entry in entries:
        full_path = f"{path.rstrip('/')}/{entry}"
        files.add(full_path)

        if recursive:
            # Try to recurse (will fail silently for files)
            sub_files = await get_workspace_file_list(
                workspace, full_path, recursive=True
            )
            files.update(sub_files)

    return files


class WorkspaceStateSnapshot:
    """Capture workspace state for comparison."""

    def __init__(self, files: dict[str, str]):
        self.files = files

    @classmethod
    async def capture(cls, workspace: Any, paths: list[str]) -> "WorkspaceStateSnapshot":
        """Capture current state of specified paths."""
        files: dict[str, str] = {}
        for path in paths:
            try:
                content = await workspace.files.read(path, mode="text")
                files[path] = content
            except Exception:
                pass  # File doesn't exist
        return cls(files)

    def diff(self, other: "WorkspaceStateSnapshot") -> dict[str, tuple[str | None, str | None]]:
        """Compare two snapshots, return differences."""
        all_paths = set(self.files.keys()) | set(other.files.keys())
        diffs: dict[str, tuple[str | None, str | None]] = {}

        for path in all_paths:
            old = self.files.get(path)
            new = other.files.get(path)
            if old != new:
                diffs[path] = (old, new)

        return diffs

    def assert_unchanged(self, other: "WorkspaceStateSnapshot") -> None:
        """Assert no changes between snapshots."""
        diffs = self.diff(other)
        assert not diffs, f"Workspace changed unexpectedly: {diffs}"
```

---

## 4. Detailed Test Specifications

### 4.1 Workspace Isolation Tests (`test_workspace_isolation.py`)

```python
"""Tests verifying copy-on-write isolation between stable and agent workspaces."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.cairn, pytest.mark.cairn_isolation]


class TestStableWorkspaceIsolation:
    """Verify agent writes don't affect stable workspace."""

    @pytest.mark.asyncio
    async def test_agent_write_does_not_affect_stable(
        self,
        workspace_service,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ):
        """Writing to agent workspace should not modify stable."""
        # Capture stable state before
        stable_before = await WorkspaceStateSnapshot.capture(
            stable_workspace,
            ["/src/main.py", "/src/utils.py", "/README.md"],
        )

        # Write new file to agent workspace
        new_path = path_resolver.to_workspace_path("src/new_file.py")
        await agent_workspace.write(new_path, "# New file content")

        # Verify stable unchanged
        stable_after = await WorkspaceStateSnapshot.capture(
            stable_workspace,
            ["/src/main.py", "/src/utils.py", "/README.md", new_path],
        )

        # New file should NOT exist in stable
        assert new_path not in stable_after.files

        # Existing files should be unchanged
        stable_before.assert_unchanged(
            WorkspaceStateSnapshot(
                {k: v for k, v in stable_after.files.items() if k != new_path}
            )
        )

    @pytest.mark.asyncio
    async def test_agent_modify_does_not_affect_stable(
        self,
        workspace_service,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ):
        """Modifying existing file in agent should not modify stable."""
        file_path = path_resolver.to_workspace_path("src/main.py")

        # Get original content from stable
        original_content = await stable_workspace.files.read(file_path, mode="text")

        # Modify in agent workspace
        new_content = "# Modified by agent\ndef modified():\n    pass\n"
        await agent_workspace.write(file_path, new_content)

        # Verify agent has new content
        agent_content = await agent_workspace.read(file_path)
        assert agent_content == new_content

        # Verify stable still has original content
        stable_content = await stable_workspace.files.read(file_path, mode="text")
        assert stable_content == original_content

    @pytest.mark.asyncio
    async def test_agent_delete_does_not_affect_stable(
        self,
        workspace_service,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ):
        """Deleting file in agent workspace should not delete from stable."""
        file_path = path_resolver.to_workspace_path("src/utils.py")

        # Verify file exists in stable
        assert await stable_workspace.files.exists(file_path)
        original_content = await stable_workspace.files.read(file_path, mode="text")

        # Write empty/tombstone to agent (simulating delete)
        # Note: Actual delete semantics depend on fsdantic implementation
        await agent_workspace.write(file_path, "")

        # Verify stable still has original file
        assert await stable_workspace.files.exists(file_path)
        stable_content = await stable_workspace.files.read(file_path, mode="text")
        assert stable_content == original_content

    @pytest.mark.asyncio
    async def test_multiple_agent_writes_isolated_from_stable(
        self,
        workspace_service,
        stable_workspace,
        path_resolver,
    ):
        """Multiple writes across multiple agents should not affect stable."""
        agents = ["agent-1", "agent-2", "agent-3"]

        # Capture initial stable state
        stable_files = ["/src/main.py", "/src/utils.py"]
        stable_before = await WorkspaceStateSnapshot.capture(stable_workspace, stable_files)

        # Each agent writes unique files
        for agent_id in agents:
            ws = await workspace_service.get_agent_workspace(agent_id)
            await ws.write(f"/agent_output_{agent_id}.txt", f"Output from {agent_id}")
            await ws.write("/src/main.py", f"# Modified by {agent_id}")

        # Verify stable unchanged
        stable_after = await WorkspaceStateSnapshot.capture(stable_workspace, stable_files)
        stable_before.assert_unchanged(stable_after)

        # Verify agent files not in stable
        for agent_id in agents:
            exists = await stable_workspace.files.exists(f"/agent_output_{agent_id}.txt")
            assert not exists
```

### 4.2 Agent Isolation Tests (`test_agent_isolation.py`)

```python
"""Tests verifying isolation between different agent workspaces."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.cairn, pytest.mark.cairn_isolation]


class TestAgentToAgentIsolation:
    """Verify agents cannot see each other's writes."""

    @pytest.mark.asyncio
    async def test_agent_cannot_see_other_agent_writes(
        self,
        workspace_service,
        path_resolver,
    ):
        """Agent-1's writes should not be visible to Agent-2."""
        ws1 = await workspace_service.get_agent_workspace("agent-1")
        ws2 = await workspace_service.get_agent_workspace("agent-2")

        # Agent-1 writes a file
        test_file = "/agent1_private.txt"
        await ws1.write(test_file, "Private to agent-1")

        # Agent-2 should not see it
        exists_in_ws2 = await ws2.exists(test_file)
        assert not exists_in_ws2, "Agent-2 should not see Agent-1's private file"

    @pytest.mark.asyncio
    async def test_agents_can_modify_same_file_independently(
        self,
        workspace_service,
        path_resolver,
    ):
        """Multiple agents can modify the same file without interference."""
        ws1 = await workspace_service.get_agent_workspace("agent-1")
        ws2 = await workspace_service.get_agent_workspace("agent-2")
        ws3 = await workspace_service.get_agent_workspace("agent-3")

        shared_file = path_resolver.to_workspace_path("src/main.py")

        # Each agent writes different content to the same file
        await ws1.write(shared_file, "# Version from agent-1")
        await ws2.write(shared_file, "# Version from agent-2")
        await ws3.write(shared_file, "# Version from agent-3")

        # Each agent should see only their version
        content1 = await ws1.read(shared_file)
        content2 = await ws2.read(shared_file)
        content3 = await ws3.read(shared_file)

        assert content1 == "# Version from agent-1"
        assert content2 == "# Version from agent-2"
        assert content3 == "# Version from agent-3"

    @pytest.mark.asyncio
    async def test_agent_isolation_with_many_agents(
        self,
        workspace_service,
    ):
        """Verify isolation with many concurrent agents."""
        num_agents = 20
        workspaces = {}

        # Create all agent workspaces
        for i in range(num_agents):
            agent_id = f"agent-{i:02d}"
            workspaces[agent_id] = await workspace_service.get_agent_workspace(agent_id)

        # Each agent writes unique content
        for agent_id, ws in workspaces.items():
            await ws.write(f"/{agent_id}_output.txt", f"Output from {agent_id}")
            await ws.write("/shared.txt", f"Written by {agent_id}")

        # Verify each agent only sees their own files
        for agent_id, ws in workspaces.items():
            # Should see own output file
            own_file = f"/{agent_id}_output.txt"
            assert await ws.exists(own_file)
            content = await ws.read(own_file)
            assert content == f"Output from {agent_id}"

            # Should NOT see other agents' output files
            for other_id in workspaces.keys():
                if other_id != agent_id:
                    other_file = f"/{other_id}_output.txt"
                    exists = await ws.exists(other_file)
                    assert not exists, f"{agent_id} should not see {other_file}"

            # Shared file should have this agent's content
            shared_content = await ws.read("/shared.txt")
            assert shared_content == f"Written by {agent_id}"
```

### 4.3 Read Semantics Tests (`test_read_semantics.py`)

```python
"""Tests verifying read fall-through from agent to stable workspace."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.cairn]


class TestReadFallThrough:
    """Verify reads fall through from agent to stable workspace."""

    @pytest.mark.asyncio
    async def test_read_falls_through_to_stable(
        self,
        workspace_service,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ):
        """Agent can read files from stable that it hasn't modified."""
        # File exists in stable (from project sync)
        file_path = path_resolver.to_workspace_path("src/utils.py")

        # Verify it exists in stable
        stable_content = await stable_workspace.files.read(file_path, mode="text")
        assert stable_content is not None

        # Agent should be able to read it without having written it
        agent_content = await agent_workspace.read(file_path)
        assert agent_content == stable_content

    @pytest.mark.asyncio
    async def test_agent_write_shadows_stable(
        self,
        workspace_service,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ):
        """Agent's write should shadow (override) stable for reads."""
        file_path = path_resolver.to_workspace_path("src/main.py")

        # Get original from stable
        original = await stable_workspace.files.read(file_path, mode="text")

        # Agent writes new content
        new_content = "# Shadowed by agent"
        await agent_workspace.write(file_path, new_content)

        # Agent read should return agent's version
        agent_read = await agent_workspace.read(file_path)
        assert agent_read == new_content
        assert agent_read != original

    @pytest.mark.asyncio
    async def test_exists_checks_both_layers(
        self,
        workspace_service,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ):
        """exists() should return True if file is in either layer."""
        # File only in stable
        stable_file = path_resolver.to_workspace_path("README.md")
        assert await agent_workspace.exists(stable_file)

        # File only in agent
        agent_file = "/agent_only.txt"
        await agent_workspace.write(agent_file, "Agent content")
        assert await agent_workspace.exists(agent_file)

        # File in neither
        missing_file = "/does_not_exist.txt"
        assert not await agent_workspace.exists(missing_file)

    @pytest.mark.asyncio
    async def test_list_dir_combines_both_layers(
        self,
        workspace_service,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ):
        """list_dir should show files from both agent and stable."""
        # Get stable files in src/
        stable_files = set(await stable_workspace.files.list_dir("/src", output="name"))

        # Agent adds a new file
        await agent_workspace.write("/src/agent_added.py", "# New file")

        # list_dir from agent should include both
        agent_files = set(await agent_workspace.list_dir("/src"))

        # Should have stable files plus agent's new file
        assert "main.py" in agent_files  # From stable
        assert "utils.py" in agent_files  # From stable
        assert "agent_added.py" in agent_files  # From agent
```

### 4.4 Lifecycle Tests (`test_lifecycle.py`)

```python
"""Tests verifying workspace lifecycle management."""

import pytest
import asyncio
from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.cairn, pytest.mark.cairn_lifecycle]


class TestWorkspaceLifecycle:
    """Verify proper workspace open/close/cleanup behavior."""

    @pytest.mark.asyncio
    async def test_service_initialize_creates_databases(
        self,
        workspace_config,
        project_root,
    ):
        """Initialize should create stable.db in workspace directory."""
        service = CairnWorkspaceService(
            workspace_config,
            graph_id="lifecycle-test",
            project_root=project_root,
        )

        try:
            await service.initialize(sync=True)

            # Check database files exist
            workspace_dir = Path(workspace_config.base_path) / "lifecycle-test"
            assert workspace_dir.exists()
            assert (workspace_dir / "stable.db").exists()
        finally:
            await service.close()

    @pytest.mark.asyncio
    async def test_agent_workspace_creates_database(
        self,
        workspace_service,
        workspace_config,
    ):
        """Getting agent workspace should create agent database file."""
        agent_id = "lifecycle-agent"

        # Get workspace
        ws = await workspace_service.get_agent_workspace(agent_id)

        # Check database file exists
        workspace_dir = Path(workspace_config.base_path) / "test-graph"
        assert (workspace_dir / f"{agent_id}.db").exists()

    @pytest.mark.asyncio
    async def test_close_releases_resources(
        self,
        workspace_config,
        project_root,
    ):
        """Close should release all workspace resources."""
        service = CairnWorkspaceService(
            workspace_config,
            graph_id="close-test",
            project_root=project_root,
        )
        await service.initialize(sync=True)

        # Create some agent workspaces
        ws1 = await service.get_agent_workspace("agent-1")
        ws2 = await service.get_agent_workspace("agent-2")

        # Close service
        await service.close()

        # Verify internal state is cleared
        assert service._stable_workspace is None
        assert len(service._agent_workspaces) == 0

    @pytest.mark.asyncio
    async def test_reopen_preserves_data(
        self,
        workspace_config,
        project_root,
    ):
        """Closing and reopening should preserve written data."""
        # First session: write data
        service1 = CairnWorkspaceService(
            workspace_config,
            graph_id="reopen-test",
            project_root=project_root,
        )
        await service1.initialize(sync=True)

        ws1 = await service1.get_agent_workspace("agent-1")
        await ws1.write("/test_file.txt", "Persistent content")

        await service1.close()

        # Second session: verify data persists
        service2 = CairnWorkspaceService(
            workspace_config,
            graph_id="reopen-test",
            project_root=project_root,
        )
        await service2.initialize(sync=False)  # Don't re-sync

        ws2 = await service2.get_agent_workspace("agent-1")
        content = await ws2.read("/test_file.txt")

        assert content == "Persistent content"

        await service2.close()

    @pytest.mark.asyncio
    async def test_multiple_graph_isolation(
        self,
        workspace_config,
        project_root,
    ):
        """Different graph_ids should have isolated workspaces."""
        service1 = CairnWorkspaceService(
            workspace_config,
            graph_id="graph-1",
            project_root=project_root,
        )
        service2 = CairnWorkspaceService(
            workspace_config,
            graph_id="graph-2",
            project_root=project_root,
        )

        try:
            await service1.initialize(sync=True)
            await service2.initialize(sync=True)

            ws1 = await service1.get_agent_workspace("agent-1")
            ws2 = await service2.get_agent_workspace("agent-1")

            # Write to graph-1
            await ws1.write("/graph_specific.txt", "Graph 1 content")

            # Should not exist in graph-2
            exists = await ws2.exists("/graph_specific.txt")
            assert not exists
        finally:
            await service1.close()
            await service2.close()
```

### 4.5 Concurrent Safety Tests (`test_concurrent_safety.py`)

```python
"""Tests verifying thread/async safety of Cairn operations."""

import pytest
import asyncio
from typing import Any

pytestmark = [
    pytest.mark.integration,
    pytest.mark.cairn,
    pytest.mark.cairn_concurrent,
    pytest.mark.cairn_slow,
]


class TestConcurrentSafety:
    """Verify concurrent operations don't cause data corruption."""

    @pytest.mark.asyncio
    async def test_concurrent_agent_creation(
        self,
        workspace_service,
    ):
        """Creating many agent workspaces concurrently should be safe."""
        num_agents = 50

        async def create_agent(agent_id: str) -> tuple[str, bool]:
            try:
                ws = await workspace_service.get_agent_workspace(agent_id)
                await ws.write(f"/{agent_id}.txt", f"Content from {agent_id}")
                return agent_id, True
            except Exception as e:
                return agent_id, False

        # Create all agents concurrently
        tasks = [create_agent(f"concurrent-{i:03d}") for i in range(num_agents)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        failures = [(agent_id, success) for agent_id, success in results if not success]
        assert not failures, f"Failed to create agents: {failures}"

    @pytest.mark.asyncio
    async def test_concurrent_writes_to_same_agent(
        self,
        workspace_service,
    ):
        """Concurrent writes to same agent workspace should be safe."""
        ws = await workspace_service.get_agent_workspace("concurrent-writes")
        num_writes = 100

        async def write_file(index: int) -> bool:
            try:
                await ws.write(f"/file_{index:03d}.txt", f"Content {index}")
                return True
            except Exception:
                return False

        # Write many files concurrently
        tasks = [write_file(i) for i in range(num_writes)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        success_count = sum(1 for r in results if r)
        assert success_count == num_writes

        # Verify all files exist
        for i in range(num_writes):
            exists = await ws.exists(f"/file_{i:03d}.txt")
            assert exists, f"File {i} should exist"

    @pytest.mark.asyncio
    async def test_concurrent_read_write(
        self,
        workspace_service,
    ):
        """Concurrent reads and writes should be safe."""
        ws = await workspace_service.get_agent_workspace("read-write")

        # Pre-populate some files
        for i in range(10):
            await ws.write(f"/base_{i}.txt", f"Base content {i}")

        read_results: list[str] = []
        write_results: list[bool] = []

        async def read_file(index: int) -> None:
            content = await ws.read(f"/base_{index % 10}.txt")
            read_results.append(content)

        async def write_file(index: int) -> None:
            try:
                await ws.write(f"/new_{index}.txt", f"New content {index}")
                write_results.append(True)
            except Exception:
                write_results.append(False)

        # Mix reads and writes concurrently
        tasks = []
        for i in range(50):
            tasks.append(read_file(i))
            tasks.append(write_file(i))

        await asyncio.gather(*tasks)

        # All operations should succeed
        assert len(read_results) == 50
        assert all(write_results)

    @pytest.mark.asyncio
    async def test_rapid_open_close_cycles(
        self,
        workspace_config,
        project_root,
    ):
        """Rapidly opening and closing services should be safe."""
        cycles = 20

        for i in range(cycles):
            service = CairnWorkspaceService(
                workspace_config,
                graph_id=f"rapid-cycle-{i}",
                project_root=project_root,
            )
            await service.initialize(sync=True)

            ws = await service.get_agent_workspace("agent-1")
            await ws.write("/test.txt", f"Cycle {i}")

            await service.close()

        # Verify last cycle's data
        service = CairnWorkspaceService(
            workspace_config,
            graph_id=f"rapid-cycle-{cycles - 1}",
            project_root=project_root,
        )
        await service.initialize(sync=False)
        ws = await service.get_agent_workspace("agent-1")
        content = await ws.read("/test.txt")
        assert content == f"Cycle {cycles - 1}"
        await service.close()
```

### 4.6 KV Operations Tests (`test_kv_operations.py`)

```python
"""Tests verifying KV store operations for submissions."""

import pytest
from cairn.orchestrator.lifecycle import SUBMISSION_KEY, SubmissionRecord

pytestmark = [pytest.mark.integration, pytest.mark.cairn]


class TestKVSubmissions:
    """Verify submission KV operations work correctly."""

    @pytest.mark.asyncio
    async def test_submit_result_stores_in_kv(
        self,
        workspace_service,
        agent_workspace,
    ):
        """submit_result should store data in KV."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        # Submit result
        await externals["submit_result"](
            summary="Test completed",
            changed_files=["/test.txt"],
        )

        # Verify KV has the record
        repo = agent_workspace.cairn.kv.repository(prefix="", model_type=SubmissionRecord)
        record = await repo.load(SUBMISSION_KEY)

        assert record is not None
        assert record.submission["summary"] == "Test completed"
        assert record.submission["changed_files"] == ["/test.txt"]

    @pytest.mark.asyncio
    async def test_submission_isolated_per_agent(
        self,
        workspace_service,
    ):
        """Each agent should have isolated submission records."""
        agents = ["agent-1", "agent-2", "agent-3"]

        for agent_id in agents:
            ws = await workspace_service.get_agent_workspace(agent_id)
            externals = workspace_service.get_externals(agent_id, ws)

            await externals["submit_result"](
                summary=f"Summary from {agent_id}",
                changed_files=[f"/{agent_id}.txt"],
            )

        # Verify each agent has correct submission
        for agent_id in agents:
            ws = await workspace_service.get_agent_workspace(agent_id)
            repo = ws.cairn.kv.repository(prefix="", model_type=SubmissionRecord)
            record = await repo.load(SUBMISSION_KEY)

            assert record.submission["summary"] == f"Summary from {agent_id}"
            assert record.submission["changed_files"] == [f"/{agent_id}.txt"]

    @pytest.mark.asyncio
    async def test_submission_overwrites_previous(
        self,
        workspace_service,
        agent_workspace,
    ):
        """Calling submit_result again should overwrite."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        # First submission
        await externals["submit_result"](
            summary="First",
            changed_files=["/first.txt"],
        )

        # Second submission
        await externals["submit_result"](
            summary="Second",
            changed_files=["/second.txt"],
        )

        # Should have second submission
        repo = agent_workspace.cairn.kv.repository(prefix="", model_type=SubmissionRecord)
        record = await repo.load(SUBMISSION_KEY)

        assert record.submission["summary"] == "Second"
```

### 4.7 Error Recovery Tests (`test_error_recovery.py`)

```python
"""Tests verifying error handling and recovery."""

import pytest
from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.cairn]


class TestErrorRecovery:
    """Verify system handles errors gracefully."""

    @pytest.mark.asyncio
    async def test_read_missing_file_raises(
        self,
        agent_workspace,
    ):
        """Reading non-existent file should raise appropriate error."""
        with pytest.raises(Exception):
            await agent_workspace.read("/does/not/exist.txt")

    @pytest.mark.asyncio
    async def test_workspace_survives_partial_failure(
        self,
        workspace_service,
    ):
        """Workspace should remain usable after operation failure."""
        ws = await workspace_service.get_agent_workspace("error-test")

        # Write successfully
        await ws.write("/success.txt", "Good content")

        # Try to read non-existent file
        with pytest.raises(Exception):
            await ws.read("/missing.txt")

        # Should still be able to use workspace
        await ws.write("/after_error.txt", "Still works")
        content = await ws.read("/success.txt")
        assert content == "Good content"

    @pytest.mark.asyncio
    async def test_close_after_error_is_safe(
        self,
        workspace_config,
        project_root,
    ):
        """Closing service after errors should not raise."""
        service = CairnWorkspaceService(
            workspace_config,
            graph_id="error-close",
            project_root=project_root,
        )
        await service.initialize(sync=True)

        ws = await service.get_agent_workspace("agent-1")

        # Cause an error
        try:
            await ws.read("/missing.txt")
        except Exception:
            pass

        # Close should not raise
        await service.close()

    @pytest.mark.asyncio
    async def test_double_close_is_safe(
        self,
        workspace_config,
        project_root,
    ):
        """Calling close() twice should not raise."""
        service = CairnWorkspaceService(
            workspace_config,
            graph_id="double-close",
            project_root=project_root,
        )
        await service.initialize(sync=True)

        await service.close()
        await service.close()  # Should not raise
```

### 4.8 Path Resolution Tests (`test_path_resolution.py`)

```python
"""Tests verifying path resolution edge cases."""

import pytest
from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.cairn]


class TestPathResolution:
    """Verify path resolution works correctly."""

    @pytest.mark.asyncio
    async def test_absolute_path_normalization(
        self,
        workspace_service,
        agent_workspace,
        project_root,
    ):
        """Absolute paths should be normalized to workspace paths."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        # Write using absolute path
        abs_path = str(project_root / "src" / "new_file.py")
        await externals["write_file"](abs_path, "# Content")

        # Should be readable via workspace path
        workspace_path = "/src/new_file.py"
        content = await agent_workspace.read(workspace_path)
        assert content == "# Content"

    @pytest.mark.asyncio
    async def test_relative_path_handling(
        self,
        workspace_service,
        agent_workspace,
    ):
        """Relative paths should work correctly."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        # Write using relative path
        await externals["write_file"]("src/relative.py", "# Relative")

        # Should be readable
        content = await agent_workspace.read("/src/relative.py")
        assert content == "# Relative"

    @pytest.mark.asyncio
    async def test_path_with_dots(
        self,
        workspace_service,
        agent_workspace,
    ):
        """Paths with . and .. should be handled."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        # Write using path with dots
        await externals["write_file"]("./src/dotted.py", "# Dotted")

        content = await agent_workspace.read("/src/dotted.py")
        assert content == "# Dotted"

    @pytest.mark.asyncio
    async def test_deeply_nested_paths(
        self,
        workspace_service,
        agent_workspace,
    ):
        """Deeply nested paths should work."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        deep_path = "/a/b/c/d/e/f/deep.txt"
        await externals["write_file"](deep_path, "Deep content")

        content = await agent_workspace.read(deep_path)
        assert content == "Deep content"
```

---

## 5. Implementation Plan

### Phase 1: Infrastructure (1-2 days)

1. Create `tests/integration/cairn/` directory structure
2. Implement `conftest.py` with fixtures
3. Add helper functions to `tests/integration/helpers.py`
4. Add pytest markers to `pyproject.toml`

### Phase 2: Core Isolation Tests (2-3 days)

1. Implement `test_workspace_isolation.py`
2. Implement `test_agent_isolation.py`
3. Run and validate tests pass
4. Fix any issues discovered

### Phase 3: Semantics Tests (1-2 days)

1. Implement `test_read_semantics.py`
2. Implement `test_write_semantics.py` (if needed separate from isolation)
3. Implement `test_kv_operations.py`

### Phase 4: Lifecycle and Error Tests (1-2 days)

1. Implement `test_lifecycle.py`
2. Implement `test_error_recovery.py`
3. Implement `test_path_resolution.py`

### Phase 5: Concurrent Tests (1-2 days)

1. Implement `test_concurrent_safety.py`
2. Add stress test variants
3. Configure CI for longer timeout

### Phase 6: Integration and CI (1 day)

1. Update pytest configuration
2. Add CI workflow for cairn tests
3. Document test requirements
4. Create test coverage report

---

## 6. Code Templates

### 6.1 pyproject.toml Updates

```toml
[tool.pytest.ini_options]
markers = [
    "integration: requires vLLM FunctionGemma server",
    "cairn: Cairn workspace integration tests",
    "cairn_isolation: Tests for copy-on-write isolation",
    "cairn_concurrent: Concurrency safety tests",
    "cairn_lifecycle: Workspace lifecycle tests",
    "cairn_slow: Long-running Cairn tests",
]
```

### 6.2 CI Workflow Snippet

```yaml
# .github/workflows/cairn-tests.yml
name: Cairn Integration Tests

on:
  push:
    paths:
      - 'src/remora/cairn_*.py'
      - 'src/remora/workspace.py'
      - 'tests/integration/cairn/**'
  pull_request:
    paths:
      - 'src/remora/cairn_*.py'
      - 'src/remora/workspace.py'
      - 'tests/integration/cairn/**'

jobs:
  cairn-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Install dependencies
        run: |
          pip install uv
          uv sync --all-extras

      - name: Run Cairn tests
        run: |
          uv run pytest tests/integration/cairn/ -v -m cairn --timeout=300
```

### 6.3 Test Run Commands

```bash
# Run all Cairn tests
pytest tests/integration/cairn/ -v -m cairn

# Run only isolation tests
pytest tests/integration/cairn/ -v -m cairn_isolation

# Run quick tests (exclude slow)
pytest tests/integration/cairn/ -v -m "cairn and not cairn_slow"

# Run concurrent tests with extra timeout
pytest tests/integration/cairn/ -v -m cairn_concurrent --timeout=600

# Run with coverage
pytest tests/integration/cairn/ -v -m cairn --cov=remora.cairn_bridge --cov=remora.workspace
```

---

## Appendix: Test Matrix

| Test File | Markers | Dependencies | Expected Duration |
|-----------|---------|--------------|-------------------|
| `test_workspace_isolation.py` | cairn, cairn_isolation | fsdantic | ~10s |
| `test_agent_isolation.py` | cairn, cairn_isolation | fsdantic | ~15s |
| `test_read_semantics.py` | cairn | fsdantic | ~5s |
| `test_lifecycle.py` | cairn, cairn_lifecycle | fsdantic | ~10s |
| `test_kv_operations.py` | cairn | fsdantic | ~5s |
| `test_concurrent_safety.py` | cairn, cairn_concurrent, cairn_slow | fsdantic | ~60s |
| `test_error_recovery.py` | cairn | fsdantic | ~5s |
| `test_path_resolution.py` | cairn | fsdantic | ~5s |

**Total estimated duration**: ~2 minutes (excluding slow tests)
