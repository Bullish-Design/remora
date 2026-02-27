# Remora V2 - Complete Fix & Refactor Guide

**Document Type:** Implementation Guide for Junior Developers
**Based On:** CODE_REVIEW.md dated 2026-02-27
**Version:** 1.0

---

## Table of Contents

1. [Introduction](#introduction)
2. [Critical Fixes](#critical-fixes)
   - [3.1.1 Remove Global Singleton Pattern](#311-remove-global-singleton-pattern)
   - [3.1.2 Fix O(n) List Operations](#312-fix-on-list-operations)
3. [Moderate Fixes](#moderate-fixes)
   - [3.2.1 Consolidate Duplicate Exports](#321-consolidate-duplicate-exports)
   - [3.2.2 Standardize Path Type Handling](#322-standardize-path-type-handling)
   - [3.2.3 Make Ignore Patterns Configurable](#323-make-ignore-patterns-configurable)
   - [3.2.4 Async Method Without Await (Decision Guide)](#324-async-method-without-await)
   - [3.2.5 Add Lazy/Incremental Sync Options](#325-add-lazyincremental-sync-options)
4. [Minor Fixes](#minor-fixes)
   - [3.3.1 Replace Magic Strings with Enum](#331-replace-magic-strings-with-enum)
   - [3.3.2 Add Proper Type Narrowing](#332-add-proper-type-narrowing)
   - [3.3.3 Consolidate Truncation Functions](#333-consolidate-truncation-functions)
5. [Blue Sky Implementation Guides](#blue-sky-implementation-guides)
   - [B1: Full Dependency Injection Container](#b1-full-dependency-injection-container)
   - [B2: Component-Based UI Architecture](#b2-component-based-ui-architecture)
   - [B4: Streaming File Sync](#b4-streaming-file-sync)
   - [B6: Event Sourcing for Execution History](#b6-event-sourcing-for-execution-history)
6. [Testing Requirements](#testing-requirements)
7. [Verification Checklist](#verification-checklist)

---

## Introduction

This guide provides step-by-step instructions for fixing all issues identified in the Remora V2 code review. Each section contains:

1. **Issue Description** - What's wrong and why
2. **Files to Modify** - Exact file paths
3. **Before Code** - Current problematic code
4. **After Code** - Fixed code with explanations
5. **Testing Steps** - How to verify the fix works

**Prerequisites:**
- Python 3.11+
- Familiarity with asyncio, dataclasses, and type hints
- Access to the Remora repository

---

## Critical Fixes

### 3.1.1 Remove Global Singleton Pattern

**Issue:** The `event_bus.py` file contains a global singleton pattern that violates dependency injection principles, makes testing harder, and creates hidden dependencies.

**Files to Modify:**
- `src/remora/core/event_bus.py`
- `src/remora/__init__.py`
- Any files importing `get_event_bus` or `reset_event_bus`

#### Step 1: Modify event_bus.py

**File:** `src/remora/core/event_bus.py`

**Before (lines 121-143):**
```python
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    global _event_bus
    if _event_bus:
        _event_bus.clear()
    _event_bus = None


__all__ = [
    "EventBus",
    "EventHandler",
    "get_event_bus",
    "reset_event_bus",
]
```

**After:**
```python
# REMOVED: Global singleton pattern
# The singleton functions get_event_bus() and reset_event_bus() have been removed.
# EventBus instances should be created explicitly and passed via dependency injection.
#
# Migration guide:
# - Old: event_bus = get_event_bus()
# - New: event_bus = EventBus()  # Create and pass explicitly
#
# For testing:
# - Old: reset_event_bus()
# - New: event_bus = EventBus()  # Create fresh instance per test


__all__ = [
    "EventBus",
    "EventHandler",
]
```

#### Step 2: Update remora/__init__.py

**File:** `src/remora/__init__.py`

**Before (line 36):**
```python
from remora.core.event_bus import EventBus, EventHandler, get_event_bus, reset_event_bus
```

**After:**
```python
from remora.core.event_bus import EventBus, EventHandler
```

**Also update __all__ list (lines 126-129):**

**Before:**
```python
    "get_event_bus",
    ...
    "reset_event_bus",
```

**After:**
Remove both entries from `__all__`.

#### Step 3: Search and Replace Usages

Run this grep to find all usages:
```bash
grep -rn "get_event_bus\|reset_event_bus" src/ tests/
```

For each occurrence:
- **In production code:** Replace `get_event_bus()` with explicit `EventBus()` creation or parameter injection
- **In test code:** Replace `reset_event_bus()` with creating a fresh `EventBus()` instance

**Example test migration:**

**Before:**
```python
def test_something():
    reset_event_bus()  # Old pattern
    bus = get_event_bus()
    # ...
```

**After:**
```python
def test_something():
    bus = EventBus()  # Fresh instance - explicit and testable
    # ...
```

#### Testing Steps

1. Run the full test suite: `pytest tests/`
2. Verify no imports of `get_event_bus` or `reset_event_bus` remain:
   ```bash
   grep -rn "get_event_bus\|reset_event_bus" src/
   # Should return nothing
   ```
3. Run type checking: `mypy src/remora/`

---

### 3.1.2 Fix O(n) List Operations

**Issue:** In `graph.py`, the topological sort uses `queue.pop(0)` which is O(n) because it shifts all elements. This creates O(n²) complexity for large graphs.

**File to Modify:** `src/remora/core/graph.py`

#### Step 1: Add deque import

**Before (line 9):**
```python
from collections import defaultdict
```

**After:**
```python
from collections import defaultdict, deque
```

#### Step 2: Modify _topological_sort function

**Before (lines 131-166):**
```python
def _topological_sort(nodes: list[AgentNode]) -> list[AgentNode]:
    """Kahn's algorithm with O(V+E) complexity."""
    node_by_id = {n.id: n for n in nodes}

    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {n.id: 0 for n in nodes}

    for node in nodes:
        for upstream_id in node.upstream:
            if upstream_id in node_by_id:
                adjacency[upstream_id].append(node.id)
                in_degree[node.id] += 1

    queue = sorted(
        [n for n in nodes if in_degree[n.id] == 0],
        key=lambda n: -n.priority,
    )

    result: list[AgentNode] = []

    while queue:
        node = queue.pop(0)  # O(n) - BAD!
        result.append(node)

        for downstream_id in adjacency[node.id]:
            in_degree[downstream_id] -= 1
            if in_degree[downstream_id] == 0:
                queue.append(node_by_id[downstream_id])

        queue.sort(key=lambda n: -n.priority)

    if len(result) != len(nodes):
        cycle_nodes = [n.id for n in nodes if in_degree[n.id] > 0]
        raise GraphError(f"Cycle detected involving nodes: {cycle_nodes}")

    return result
```

**After:**
```python
def _topological_sort(nodes: list[AgentNode]) -> list[AgentNode]:
    """Kahn's algorithm with O(V+E) complexity.

    Uses deque for O(1) popleft operations. Priority ordering is maintained
    by sorting when inserting newly ready nodes.
    """
    node_by_id = {n.id: n for n in nodes}

    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {n.id: 0 for n in nodes}

    for node in nodes:
        for upstream_id in node.upstream:
            if upstream_id in node_by_id:
                adjacency[upstream_id].append(node.id)
                in_degree[node.id] += 1

    # Use deque for O(1) popleft
    queue: deque[AgentNode] = deque(
        sorted(
            [n for n in nodes if in_degree[n.id] == 0],
            key=lambda n: -n.priority,
        )
    )

    result: list[AgentNode] = []

    while queue:
        node = queue.popleft()  # O(1) - GOOD!
        result.append(node)

        # Collect all newly ready nodes
        newly_ready: list[AgentNode] = []
        for downstream_id in adjacency[node.id]:
            in_degree[downstream_id] -= 1
            if in_degree[downstream_id] == 0:
                newly_ready.append(node_by_id[downstream_id])

        # Sort newly ready nodes by priority and extend queue
        if newly_ready:
            newly_ready.sort(key=lambda n: -n.priority)
            queue.extend(newly_ready)

    if len(result) != len(nodes):
        cycle_nodes = [n.id for n in nodes if in_degree[n.id] > 0]
        raise GraphError(f"Cycle detected involving nodes: {cycle_nodes}")

    return result
```

**Note on Priority Ordering:**

The original code sorted the entire queue after each iteration, which is actually O(n log n) per iteration. The new code:
1. Uses O(1) `popleft()` instead of O(n) `pop(0)`
2. Only sorts newly ready nodes (typically few) rather than the entire queue
3. For strict priority ordering across all nodes, you may want a heap-based approach (see alternative below)

**Alternative using heapq for strict priority:**
```python
import heapq

def _topological_sort(nodes: list[AgentNode]) -> list[AgentNode]:
    """Kahn's algorithm with heap for priority ordering."""
    node_by_id = {n.id: n for n in nodes}
    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {n.id: 0 for n in nodes}

    for node in nodes:
        for upstream_id in node.upstream:
            if upstream_id in node_by_id:
                adjacency[upstream_id].append(node.id)
                in_degree[node.id] += 1

    # Priority queue: (-priority, id) for max-priority first
    heap: list[tuple[int, str]] = []
    for n in nodes:
        if in_degree[n.id] == 0:
            heapq.heappush(heap, (-n.priority, n.id))

    result: list[AgentNode] = []

    while heap:
        _, node_id = heapq.heappop(heap)  # O(log n)
        node = node_by_id[node_id]
        result.append(node)

        for downstream_id in adjacency[node.id]:
            in_degree[downstream_id] -= 1
            if in_degree[downstream_id] == 0:
                heapq.heappush(heap, (-node_by_id[downstream_id].priority, downstream_id))

    if len(result) != len(nodes):
        cycle_nodes = [n.id for n in nodes if in_degree[n.id] > 0]
        raise GraphError(f"Cycle detected involving nodes: {cycle_nodes}")

    return result
```

#### Testing Steps

1. Run graph tests: `pytest tests/unit/test_agent_graph.py -v`
2. Create a performance test with large graphs:
   ```python
   import time
   from remora.core.graph import _topological_sort, AgentNode
   from remora.core.discovery import CSTNode
   from pathlib import Path

   def test_topological_sort_performance():
       # Create 1000 node graph
       nodes = []
       for i in range(1000):
           cst = CSTNode(
               node_id=f"node_{i}",
               node_type="function",
               name=f"func_{i}",
               file_path=f"/test/file_{i}.py",
               start_line=1,
               end_line=10,
           )
           upstream = frozenset([f"node_{i-1}"]) if i > 0 else frozenset()
           nodes.append(AgentNode(
               id=f"node_{i}",
               name=f"func_{i}",
               target=cst,
               bundle_path=Path("/test/bundle"),
               upstream=upstream,
           ))

       start = time.time()
       result = _topological_sort(nodes)
       elapsed = time.time() - start

       assert len(result) == 1000
       assert elapsed < 0.5  # Should be fast with deque
   ```

---

## Moderate Fixes

### 3.2.1 Consolidate Duplicate Exports

**Issue:** Both `remora/__init__.py` and `remora/core/__init__.py` export similar symbols, creating maintenance burden.

**Files to Modify:**
- `src/remora/core/__init__.py`
- `src/remora/__init__.py`

#### Step 1: Check if core/__init__.py exists

First, verify the structure:
```bash
ls -la src/remora/core/__init__.py
```

If `core/__init__.py` doesn't exist or is empty, this issue doesn't apply.

#### Step 2: Modify remora/__init__.py to re-export from core

**File:** `src/remora/__init__.py`

**After (complete rewrite):**
```python
"""Remora public API surface."""

# Re-export all core symbols
from remora.core.cairn_bridge import CairnWorkspaceService
from remora.core.cairn_externals import CairnExternals
from remora.core.checkpoint import CheckpointManager
from remora.core.config import (
    BundleConfig,
    ConfigError,
    DiscoveryConfig,
    ErrorPolicy,
    ExecutionConfig,
    IndexerConfig,
    ModelConfig,
    RemoraConfig,
    WorkspaceConfig,
    load_config,
    serialize_config,
)
from remora.core.context import ContextBuilder, RecentAction
from remora.core.discovery import (
    CSTNode,
    LANGUAGE_EXTENSIONS,
    NodeType,
    TreeSitterDiscoverer,
    compute_node_id,
    discover,
)
from remora.core.errors import (
    CheckpointError,
    DiscoveryError,
    ExecutionError,
    GraphError,
    RemoraError,
    WorkspaceError,
)
from remora.core.event_bus import EventBus, EventHandler
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentSkippedEvent,
    AgentStartEvent,
    CheckpointRestoredEvent,
    CheckpointSavedEvent,
    GraphCompleteEvent,
    GraphErrorEvent,
    GraphStartEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    RemoraEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from remora.core.executor import AgentState, ExecutorState, GraphExecutor, ResultSummary
from remora.core.graph import AgentNode, build_graph, get_execution_batches
from remora.core.tools import RemoraGrailTool, build_virtual_fs, discover_grail_tools
from remora.core.workspace import AgentWorkspace, CairnDataProvider, CairnResultHandler, WorkspaceManager
from remora.utils import PathResolver

# Collect all exports - single source of truth
__all__ = [
    # Errors
    "CheckpointError",
    "ConfigError",
    "DiscoveryError",
    "ExecutionError",
    "GraphError",
    "RemoraError",
    "WorkspaceError",
    # Config
    "BundleConfig",
    "DiscoveryConfig",
    "ErrorPolicy",
    "ExecutionConfig",
    "IndexerConfig",
    "ModelConfig",
    "RemoraConfig",
    "WorkspaceConfig",
    "load_config",
    "serialize_config",
    # Events
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentSkippedEvent",
    "AgentStartEvent",
    "CheckpointRestoredEvent",
    "CheckpointSavedEvent",
    "GraphCompleteEvent",
    "GraphErrorEvent",
    "GraphStartEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    "KernelEndEvent",
    "KernelStartEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "RemoraEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "TurnCompleteEvent",
    # Event Bus
    "EventBus",
    "EventHandler",
    # Graph
    "AgentNode",
    "build_graph",
    "get_execution_batches",
    # Execution
    "AgentState",
    "ExecutorState",
    "GraphExecutor",
    "ResultSummary",
    # Discovery
    "CSTNode",
    "LANGUAGE_EXTENSIONS",
    "NodeType",
    "TreeSitterDiscoverer",
    "compute_node_id",
    "discover",
    # Context
    "ContextBuilder",
    "RecentAction",
    # Workspace
    "AgentWorkspace",
    "CairnDataProvider",
    "CairnExternals",
    "CairnResultHandler",
    "CairnWorkspaceService",
    "WorkspaceManager",
    # Tools
    "RemoraGrailTool",
    "build_virtual_fs",
    "discover_grail_tools",
    # Checkpoint
    "CheckpointManager",
    # Utils
    "PathResolver",
]
```

#### Testing Steps

1. Verify all exports work:
   ```python
   from remora import *
   # Should not raise ImportError
   ```
2. Run: `python -c "from remora import EventBus, RemoraConfig; print('OK')"`

---

### 3.2.2 Standardize Path Type Handling

**Issue:** Some APIs accept `Path | str`, others only `Path` or only `str`.

**Files to Modify:**
- `src/remora/utils/__init__.py` (or create `src/remora/utils/types.py`)
- All files with public path-accepting APIs

#### Step 1: Create a PathLike type alias and normalize function

**Create/modify:** `src/remora/utils/types.py`

```python
"""Common type definitions and utilities."""

from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

# Type alias for path-like values
PathLike: TypeAlias = Path | str


def normalize_path(path: PathLike) -> Path:
    """Convert any path-like value to a Path object.

    Args:
        path: A string or Path object

    Returns:
        A resolved Path object
    """
    return Path(path) if isinstance(path, str) else path


__all__ = ["PathLike", "normalize_path"]
```

#### Step 2: Update utils/__init__.py

**File:** `src/remora/utils/__init__.py`

Add the export:
```python
from remora.utils.types import PathLike, normalize_path

__all__ = [
    "PathLike",
    "PathResolver",
    "normalize_path",
]
```

#### Step 3: Update APIs to use PathLike

Example for `workspace.py`:

**Before:**
```python
async def read(self, path: str) -> str:
```

**After:**
```python
from remora.utils import PathLike, normalize_path

async def read(self, path: PathLike) -> str:
    path = str(normalize_path(path))
    # ... rest of implementation
```

#### Testing Steps

1. Test with both str and Path arguments:
   ```python
   from pathlib import Path
   from remora.utils import normalize_path

   assert normalize_path("/test/path") == Path("/test/path")
   assert normalize_path(Path("/test/path")) == Path("/test/path")
   ```

---

### 3.2.3 Make Ignore Patterns Configurable

**Issue:** `cairn_bridge.py` has hardcoded `_IGNORE_DIRS` that users cannot customize.

**Files to Modify:**
- `src/remora/core/config.py`
- `src/remora/core/cairn_bridge.py`

#### Step 1: Update WorkspaceConfig

**File:** `src/remora/core/config.py`

Find the `WorkspaceConfig` dataclass and add `ignore_patterns`:

**Before:**
```python
@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    base_path: str = ".remora/workspaces"
    cleanup_after: str = "1h"
```

**After:**
```python
# Default ignore patterns - extracted for reuse
DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    ".agentfs",
    ".git",
    ".jj",
    ".mypy_cache",
    ".pytest_cache",
    ".remora",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
)


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """Configuration for workspace management."""

    base_path: str = ".remora/workspaces"
    cleanup_after: str = "1h"
    ignore_patterns: tuple[str, ...] = DEFAULT_IGNORE_PATTERNS
    ignore_dotfiles: bool = True  # Also ignore files starting with .
```

#### Step 2: Update cairn_bridge.py to use config

**File:** `src/remora/core/cairn_bridge.py`

**Before (lines 25-37 and 163-174):**
```python
_IGNORE_DIRS = {
    ".agentfs",
    ".git",
    # ... etc
}

# ... later in file:

def _should_ignore(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return True

    for part in rel_parts:
        if part in _IGNORE_DIRS:
            return True
        if part.startswith("."):
            return True
    return False
```

**After:**
```python
# Remove the module-level _IGNORE_DIRS constant

class CairnWorkspaceService:
    def __init__(
        self,
        config: WorkspaceConfig,
        graph_id: str,
        project_root: Path | str | None = None,
    ) -> None:
        self._config = config
        self._graph_id = graph_id
        self._project_root = Path(project_root or Path.cwd()).resolve()
        self._resolver = PathResolver(self._project_root)
        self._base_path = Path(config.base_path) / graph_id
        self._manager = cairn_workspace_manager.WorkspaceManager()
        self._stable_workspace: Any | None = None
        self._agent_workspaces: dict[str, AgentWorkspace] = {}
        self._stable_lock = asyncio.Lock()
        # Store ignore patterns as a set for O(1) lookup
        self._ignore_patterns: set[str] = set(config.ignore_patterns)
        self._ignore_dotfiles: bool = config.ignore_dotfiles

    # ... rest of class ...

    async def _sync_project_to_workspace(self) -> None:
        """Sync project files into the stable workspace."""
        if self._stable_workspace is None:
            return

        for path in self._project_root.rglob("*"):
            if path.is_dir():
                continue
            if self._should_ignore(path):
                continue

            if not self._resolver.is_within_project(path):
                continue
            rel_path = self._resolver.to_workspace_path(path)

            try:
                payload = path.read_bytes()
            except OSError as exc:
                logger.debug("Failed to read %s: %s", path, exc)
                continue

            try:
                await self._stable_workspace.files.write(rel_path, payload, mode="binary")
            except Exception as exc:
                logger.debug("Failed to write %s to stable workspace: %s", rel_path, exc)

    def _should_ignore(self, path: Path) -> bool:
        """Check if a path should be ignored based on config patterns."""
        try:
            rel_parts = path.relative_to(self._project_root).parts
        except ValueError:
            return True

        for part in rel_parts:
            if part in self._ignore_patterns:
                return True
            if self._ignore_dotfiles and part.startswith("."):
                return True
        return False


# Remove the module-level _should_ignore function
```

#### Step 3: Update remora.yaml.example

Add documentation for the new config options:

```yaml
workspace:
  base_path: ".remora/workspaces"
  cleanup_after: "1h"
  # Directories to ignore when syncing project files
  ignore_patterns:
    - ".git"
    - ".venv"
    - "node_modules"
    - "__pycache__"
    - ".mypy_cache"
    - ".pytest_cache"
  # Also ignore any files/dirs starting with "."
  ignore_dotfiles: true
```

#### Testing Steps

1. Test with custom patterns:
   ```python
   from remora.core.config import WorkspaceConfig

   config = WorkspaceConfig(
       ignore_patterns=(".git", "custom_ignore"),
       ignore_dotfiles=False,
   )
   assert ".git" in config.ignore_patterns
   assert "custom_ignore" in config.ignore_patterns
   ```

---

### 3.2.4 Async Method Without Await

**Issue:** The `handle` method in `context.py` is declared `async` but never awaits anything.

**File:** `src/remora/core/context.py`

This requires careful consideration. Below is a detailed analysis to help you decide.

---

#### Background & Context

The `ContextBuilder.handle()` method is designed to be an event handler that can be subscribed to the `EventBus`. Looking at the code:

```python
# context.py:57-83
async def handle(self, event: RemoraEvent) -> None:
    """EventBus subscriber - updates context from events."""
    match event:
        case ToolResultEvent(tool_name=name, output_preview=output, is_error=is_error):
            self._recent.append(
                RecentAction(
                    tool=name,
                    outcome="error" if is_error else "success",
                    summary=_summarize(str(output), max_len=200),
                )
            )

        case AgentCompleteEvent(agent_id=aid, result_summary=summary):
            self._knowledge[aid] = summary

        case AgentErrorEvent(agent_id=aid, error=error):
            self._recent.append(
                RecentAction(
                    tool="agent",
                    outcome="error",
                    summary=f"Agent {aid} failed: {error[:100]}",
                    agent_id=aid,
                )
            )

        case _:
            pass
```

The method only performs synchronous operations (`deque.append()`, dict assignment). It never uses `await`.

---

#### Option A: Keep as Async

**Rationale:**
1. **Protocol compatibility:** The `EventBus.emit()` method handles both sync and async handlers:
   ```python
   # event_bus.py:46-52
   for handler in handlers:
       try:
           result = handler(event)
           if asyncio.iscoroutine(result):
               await result
   ```
   So both sync and async handlers work. However, keeping `async` signals intent.

2. **Future-proofing:** The method might need to perform async operations in the future:
   - Async logging
   - Async database writes for event sourcing
   - Network calls for distributed context sharing

3. **Consistency:** Other event handlers in the codebase might be async, maintaining uniform signatures.

**Pros:**
- No breaking changes to existing code
- Ready for future async requirements
- Consistent handler signature

**Cons:**
- Minor overhead from creating a coroutine object (negligible)
- Slightly misleading - suggests async work when there is none
- Adds `await` overhead when called from async contexts

**Performance Impact:** Minimal. Creating a coroutine that immediately returns has ~100ns overhead.

---

#### Option B: Make Synchronous

**Rationale:**
1. **Honesty:** The method doesn't do async work; it shouldn't pretend to.
2. **Simplicity:** Synchronous functions are easier to reason about.
3. **Micro-optimization:** Avoids coroutine creation overhead.

**Pros:**
- Clearer intent
- Marginally better performance
- Easier to test (no need for `asyncio.run()` or `await`)

**Cons:**
- Requires changing to async later if requirements change
- Might be inconsistent with other handlers

**Performance Impact:** Saves ~100ns per call. For 10,000 events, that's 1ms total.

---

#### Recommendation

**Recommended approach: Keep as async BUT add a comment explaining why.**

The method should stay async because:
1. The EventBus protocol handles both, so there's no functional issue
2. Event handlers commonly need async capabilities
3. The context builder might need async operations in the future (e.g., for B6 Event Sourcing)

**Modified code:**

```python
async def handle(self, event: RemoraEvent) -> None:
    """EventBus subscriber - updates context from events.

    This method is async for EventBus protocol compatibility and to
    support future async operations (e.g., persistent storage).
    Current implementation is synchronous but the async signature
    allows for transparent evolution.
    """
    match event:
        # ... existing implementation unchanged ...
```

---

#### Alternative: Make Synchronous (if chosen)

If you decide to make it synchronous:

**Before:**
```python
async def handle(self, event: RemoraEvent) -> None:
    """EventBus subscriber - updates context from events."""
    match event:
        # ...
```

**After:**
```python
def handle(self, event: RemoraEvent) -> None:
    """EventBus subscriber - updates context from events.

    Note: This is synchronous because all operations are synchronous.
    The EventBus handles both sync and async handlers transparently.
    """
    match event:
        # ...
```

---

#### Testing Considerations

**If keeping async:**
```python
import asyncio

def test_handle_tool_result():
    builder = ContextBuilder()
    event = ToolResultEvent(tool_name="test", output_preview="output", is_error=False)
    asyncio.run(builder.handle(event))
    assert len(builder.get_recent_actions()) == 1
```

**If making sync:**
```python
def test_handle_tool_result():
    builder = ContextBuilder()
    event = ToolResultEvent(tool_name="test", output_preview="output", is_error=False)
    builder.handle(event)  # No asyncio.run needed
    assert len(builder.get_recent_actions()) == 1
```

---

### 3.2.5 Add Lazy/Incremental Sync Options

**Issue:** For large codebases, `_sync_project_to_workspace()` blocks initialization.

**File:** `src/remora/core/cairn_bridge.py`

#### Step 1: Add SyncMode enum

```python
from enum import Enum

class SyncMode(str, Enum):
    """Workspace synchronization modes."""
    FULL = "full"        # Sync all files upfront (current behavior)
    LAZY = "lazy"        # Sync files on first access
    NONE = "none"        # No automatic sync
```

#### Step 2: Modify CairnWorkspaceService

**Add to __init__:**
```python
def __init__(
    self,
    config: WorkspaceConfig,
    graph_id: str,
    project_root: Path | str | None = None,
) -> None:
    # ... existing initialization ...
    self._sync_mode: SyncMode = SyncMode.FULL
    self._synced_files: set[str] = set()
```

**Modify initialize method:**
```python
async def initialize(
    self,
    *,
    sync_mode: SyncMode = SyncMode.FULL,
) -> None:
    """Initialize stable workspace with configurable sync mode.

    Args:
        sync_mode: How to sync project files
            - FULL: Sync all files immediately (default, current behavior)
            - LAZY: Sync files on first access
            - NONE: No automatic sync
    """
    if self._stable_workspace is not None:
        return

    self._sync_mode = sync_mode
    self._base_path.mkdir(parents=True, exist_ok=True)
    stable_path = self._base_path / "stable.db"

    try:
        self._stable_workspace = await cairn_workspace_manager._open_workspace(
            stable_path,
            readonly=False,
        )
        self._manager.track_workspace(self._stable_workspace)
    except Exception as exc:
        raise WorkspaceError(f"Failed to create stable workspace: {exc}") from exc

    if sync_mode == SyncMode.FULL:
        await self._sync_project_to_workspace()
```

**Add lazy sync method:**
```python
async def ensure_file_synced(self, rel_path: str) -> bool:
    """Ensure a specific file is synced to workspace.

    Used for lazy sync mode. Returns True if file was synced.
    """
    if rel_path in self._synced_files:
        return True

    if self._stable_workspace is None:
        return False

    full_path = self._project_root / rel_path
    if not full_path.exists():
        return False

    if self._should_ignore(full_path):
        return False

    try:
        payload = full_path.read_bytes()
        await self._stable_workspace.files.write(rel_path, payload, mode="binary")
        self._synced_files.add(rel_path)
        return True
    except Exception as exc:
        logger.debug("Failed to sync %s: %s", rel_path, exc)
        return False
```

**Update AgentWorkspace.read to support lazy sync:**

In `workspace.py`, modify the `read` method to check if lazy sync is needed:

```python
async def read(self, path: str) -> str:
    """Read file content, syncing from project if needed."""
    # First try agent's own workspace
    try:
        return await self._workspace.files.read(path)
    except FileNotFoundError:
        pass

    # Then try stable workspace
    if self._stable_workspace:
        try:
            return await self._stable_workspace.files.read(path)
        except FileNotFoundError:
            pass

    # If lazy sync is enabled and file exists on disk, sync it
    # This requires passing a reference to CairnWorkspaceService or a sync callback
    raise FileNotFoundError(path)
```

#### Testing Steps

```python
import pytest
from remora.core.cairn_bridge import CairnWorkspaceService, SyncMode

@pytest.mark.asyncio
async def test_lazy_sync():
    config = WorkspaceConfig()
    service = CairnWorkspaceService(config, "test-graph", project_root="/tmp/test")

    await service.initialize(sync_mode=SyncMode.LAZY)

    # File should not be synced yet
    assert len(service._synced_files) == 0

    # Trigger lazy sync
    await service.ensure_file_synced("test.py")

    assert "test.py" in service._synced_files
```

---

## Minor Fixes

### 3.3.1 Replace Magic Strings with Enum

**Issue:** `projector.py` uses string literals like `"graph"`, `"agent"`, etc.

**File:** `src/remora/ui/projector.py`

#### Step 1: Add EventKind enum

At the top of the file, after imports:

```python
from enum import Enum

class EventKind(str, Enum):
    """Categories of events for UI display."""
    GRAPH = "graph"
    AGENT = "agent"
    HUMAN = "human"
    CHECKPOINT = "checkpoint"
    TOOL = "tool"
    MODEL = "model"
    KERNEL = "kernel"
    TURN = "turn"
    EVENT = "event"  # Default/unknown
```

#### Step 2: Update _event_kind function

**Before:**
```python
def _event_kind(event: StructuredEvent | RemoraEvent) -> str:
    if isinstance(event, (GraphStartEvent, GraphCompleteEvent, GraphErrorEvent)):
        return "graph"
    if isinstance(event, (AgentStartEvent, AgentCompleteEvent, AgentErrorEvent, AgentSkippedEvent)):
        return "agent"
    # ... etc
    return "event"
```

**After:**
```python
def _event_kind(event: StructuredEvent | RemoraEvent) -> EventKind:
    """Categorize an event for UI display."""
    if isinstance(event, (GraphStartEvent, GraphCompleteEvent, GraphErrorEvent)):
        return EventKind.GRAPH
    if isinstance(event, (AgentStartEvent, AgentCompleteEvent, AgentErrorEvent, AgentSkippedEvent)):
        return EventKind.AGENT
    if isinstance(event, (HumanInputRequestEvent, HumanInputResponseEvent)):
        return EventKind.HUMAN
    if isinstance(event, (CheckpointSavedEvent, CheckpointRestoredEvent)):
        return EventKind.CHECKPOINT
    if isinstance(event, (ToolCallEvent, ToolResultEvent)):
        return EventKind.TOOL
    if isinstance(event, (ModelRequestEvent, ModelResponseEvent)):
        return EventKind.MODEL
    if isinstance(event, (KernelStartEvent, KernelEndEvent)):
        return EventKind.KERNEL
    if isinstance(event, TurnCompleteEvent):
        return EventKind.TURN
    return EventKind.EVENT
```

**Note:** Since `EventKind` inherits from `str`, it will serialize to JSON correctly and the existing code that uses the kind value in templates will continue to work.

#### Step 3: Export the enum

Update `__all__`:
```python
__all__ = ["EventKind", "UiStateProjector", "normalize_event"]
```

---

### 3.3.2 Add Proper Type Narrowing

**Issue:** `executor.py` uses `cast(Any, ...)` which defeats type checking.

**File:** `src/remora/core/executor.py`

#### Step 1: Define a Protocol

Add near the top of the file:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class AgentResultProtocol(Protocol):
    """Protocol for agent execution results."""
    output: str | None
    final_message: Any  # Message type from structured_agents

    @property
    def success(self) -> bool: ...
```

#### Step 2: Replace cast(Any, ...) with proper type checking

Find usages like:
```python
agent_result = cast(Any, result)
output = getattr(agent_result, "output", None)
```

**Replace with:**
```python
if isinstance(result, AgentResultProtocol):
    output = result.output
else:
    # Fallback for non-protocol results
    output = getattr(result, "output", None)
```

Or use a helper function:

```python
def extract_output(result: Any) -> str | None:
    """Extract output from an agent result, handling various types."""
    if hasattr(result, "output"):
        return result.output
    if isinstance(result, dict):
        return result.get("output")
    return None
```

---

### 3.3.3 Consolidate Truncation Functions

**Issue:** Multiple similar truncation functions exist.

**Files:**
- `src/remora/core/executor.py` - has `_truncate()`
- `src/remora/core/context.py` - has `_summarize()`

#### Step 1: Create unified utility

**Create/modify:** `src/remora/utils/text.py`

```python
"""Text manipulation utilities."""

from __future__ import annotations


def truncate(
    text: str,
    max_len: int = 200,
    suffix: str = "...",
) -> str:
    """Truncate text to a maximum length with suffix.

    Args:
        text: The text to truncate
        max_len: Maximum length including suffix
        suffix: String to append when truncating

    Returns:
        Truncated text, or original if within limit

    Examples:
        >>> truncate("hello world", max_len=8)
        'hello...'
        >>> truncate("short", max_len=10)
        'short'
    """
    if len(text) <= max_len:
        return text
    return text[:max_len - len(suffix)] + suffix


def summarize(text: str, max_len: int = 200) -> str:
    """Alias for truncate with default settings.

    Provided for semantic clarity when summarizing content
    rather than just truncating.
    """
    return truncate(text, max_len=max_len)


__all__ = ["summarize", "truncate"]
```

#### Step 2: Update utils/__init__.py

```python
from remora.utils.text import summarize, truncate

__all__ = [
    # ... existing exports ...
    "summarize",
    "truncate",
]
```

#### Step 3: Update executor.py

**Before:**
```python
def _truncate(text: str, limit: int = 1024) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."
```

**After:**
```python
from remora.utils import truncate

# Remove the local _truncate function
# Replace _truncate(text, 1024) with truncate(text, max_len=1024)
```

#### Step 4: Update context.py

**Before:**
```python
def _summarize(text: str, max_len: int = 200) -> str:
    """Truncate text for context summary."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
```

**After:**
```python
from remora.utils import summarize

# Remove the local _summarize function
# Use summarize(text, max_len=200) directly
```

---

## Blue Sky Implementation Guides

### B1: Full Dependency Injection Container

**Goal:** Eliminate all global state and make dependencies explicit and testable.

#### Overview

Create a lightweight DI container that:
1. Holds all service instances
2. Wires dependencies automatically
3. Provides scoped containers for different runs

#### Implementation

##### Step 1: Create the Container

**Create:** `src/remora/core/container.py`

```python
"""Dependency injection container for Remora services."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from remora.core.config import RemoraConfig, load_config
from remora.core.context import ContextBuilder
from remora.core.event_bus import EventBus

if TYPE_CHECKING:
    from remora.core.cairn_bridge import CairnWorkspaceService
    from remora.core.executor import GraphExecutor


@dataclass
class RemoraContainer:
    """Central dependency container for Remora services.

    This container holds all service instances and ensures proper
    wiring of dependencies. Use the factory methods to create
    properly configured containers.

    Usage:
        # Create with defaults
        container = RemoraContainer.create()

        # Create with custom config
        container = RemoraContainer.create(config_path="./remora.yaml")

        # Use services
        await container.event_bus.emit(SomeEvent())
        context = container.context_builder.build_context_for(node)
    """

    config: RemoraConfig
    event_bus: EventBus
    context_builder: ContextBuilder
    project_root: Path

    # Lazily initialized services
    _workspace_service: "CairnWorkspaceService | None" = field(default=None, repr=False)
    _executor: "GraphExecutor | None" = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        *,
        config: RemoraConfig | None = None,
        config_path: Path | str | None = None,
        project_root: Path | str | None = None,
    ) -> "RemoraContainer":
        """Create a fully-wired container with default dependencies.

        Args:
            config: Pre-loaded configuration (takes precedence)
            config_path: Path to config file (used if config is None)
            project_root: Project root directory (defaults to cwd)

        Returns:
            A configured RemoraContainer instance
        """
        resolved_config = config or load_config(config_path)
        resolved_root = Path(project_root or Path.cwd()).resolve()

        event_bus = EventBus()
        context_builder = ContextBuilder()

        # Wire context builder to event bus
        event_bus.subscribe_all(context_builder.handle)

        return cls(
            config=resolved_config,
            event_bus=event_bus,
            context_builder=context_builder,
            project_root=resolved_root,
        )

    @classmethod
    def create_for_testing(
        cls,
        *,
        config: RemoraConfig | None = None,
    ) -> "RemoraContainer":
        """Create a minimal container for unit testing.

        Uses in-memory defaults and no file system access.
        """
        from remora.core.config import RemoraConfig as RC

        return cls(
            config=config or RC(),
            event_bus=EventBus(),
            context_builder=ContextBuilder(),
            project_root=Path("/tmp/test"),
        )

    async def get_workspace_service(self, graph_id: str) -> "CairnWorkspaceService":
        """Get or create workspace service for a graph execution.

        Workspace services are created lazily and cached.
        """
        if self._workspace_service is None:
            from remora.core.cairn_bridge import CairnWorkspaceService

            self._workspace_service = CairnWorkspaceService(
                config=self.config.workspace,
                graph_id=graph_id,
                project_root=self.project_root,
            )
            await self._workspace_service.initialize()

        return self._workspace_service

    def get_executor(self) -> "GraphExecutor":
        """Get or create graph executor."""
        if self._executor is None:
            from remora.core.executor import GraphExecutor

            self._executor = GraphExecutor(
                event_bus=self.event_bus,
                config=self.config,
            )

        return self._executor

    async def close(self) -> None:
        """Clean up all resources."""
        if self._workspace_service:
            await self._workspace_service.close()
            self._workspace_service = None

        self.event_bus.clear()


@dataclass
class ScopedContainer:
    """A scoped container for a single graph execution.

    Inherits base services from parent container but has its own
    workspace and execution state.
    """

    parent: RemoraContainer
    graph_id: str
    workspace_service: "CairnWorkspaceService"

    @classmethod
    async def create(
        cls,
        parent: RemoraContainer,
        graph_id: str,
    ) -> "ScopedContainer":
        """Create a scoped container for graph execution."""
        workspace_service = await parent.get_workspace_service(graph_id)
        return cls(
            parent=parent,
            graph_id=graph_id,
            workspace_service=workspace_service,
        )

    @property
    def config(self) -> RemoraConfig:
        return self.parent.config

    @property
    def event_bus(self) -> EventBus:
        return self.parent.event_bus

    @property
    def context_builder(self) -> ContextBuilder:
        return self.parent.context_builder


__all__ = ["RemoraContainer", "ScopedContainer"]
```

##### Step 2: Update Service Layer

**Modify:** `src/remora/service/api.py`

```python
"""Service layer entry point for Remora."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

from remora.core.config import RemoraConfig, load_config
from remora.core.container import RemoraContainer
from remora.core.event_bus import EventBus
from remora.models import ConfigSnapshot, InputResponse, PlanRequest, PlanResponse, RunRequest, RunResponse
from remora.service.datastar import render_patch, render_shell
from remora.service.handlers import (
    ExecutorFactory,
    ServiceDeps,
    default_executor_factory,
    handle_config_snapshot,
    handle_input,
    handle_plan,
    handle_run,
    handle_ui_snapshot,
)
from remora.ui.projector import UiStateProjector, normalize_event
from remora.ui.view import render_dashboard


class RemoraService:
    """Framework-agnostic Remora service API."""

    @classmethod
    def create_default(
        cls,
        *,
        config: RemoraConfig | None = None,
        config_path: Path | str | None = None,
        project_root: Path | str | None = None,
    ) -> "RemoraService":
        """Create service with default container."""
        container = RemoraContainer.create(
            config=config,
            config_path=config_path,
            project_root=project_root,
        )
        return cls(container=container)

    def __init__(
        self,
        *,
        container: RemoraContainer | None = None,
        # Legacy parameters for backwards compatibility
        event_bus: EventBus | None = None,
        config: RemoraConfig | None = None,
        project_root: Path | str | None = None,
        projector: UiStateProjector | None = None,
        executor_factory: ExecutorFactory | None = None,
    ) -> None:
        # New container-based initialization
        if container is not None:
            self._container = container
            self._event_bus = container.event_bus
            self._config = container.config
            self._project_root = container.project_root
        # Legacy initialization for backwards compatibility
        elif event_bus is not None:
            self._container = None
            self._event_bus = event_bus
            self._config = config or load_config()
            self._project_root = Path(project_root or Path.cwd()).resolve()
        else:
            raise ValueError(
                "Either 'container' or 'event_bus' is required; "
                "use RemoraService.create_default() for defaults"
            )

        self._projector = projector or UiStateProjector()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._bundle_default = _resolve_bundle_default(self._config)
        self._event_bus.subscribe_all(self._projector.record)

        self._deps = ServiceDeps(
            event_bus=self._event_bus,
            config=self._config,
            project_root=self._project_root,
            projector=self._projector,
            executor_factory=executor_factory or default_executor_factory,
            running_tasks=self._running_tasks,
        )

    # ... rest of methods unchanged ...
```

##### Step 3: Update CLI

**Modify:** `src/remora/cli/main.py`

```python
@main.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8420, show_default=True)
@click.option("--project-root", type=click.Path(file_okay=False, resolve_path=True))
@click.option("--config", "config_path", type=click.Path(dir_okay=False, resolve_path=True))
def serve(host: str, port: int, project_root: str | None, config_path: str | None) -> None:
    """Start the Remora service server."""
    from remora.core.container import RemoraContainer

    try:
        container = RemoraContainer.create(
            config_path=config_path,
            project_root=project_root,
        )
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    service = RemoraService(container=container)
    app = create_app(service)

    import uvicorn
    uvicorn.run(app, host=host, port=port)
```

##### Step 4: Update Exports

**Modify:** `src/remora/__init__.py`

Add:
```python
from remora.core.container import RemoraContainer, ScopedContainer

__all__ = [
    # ... existing exports ...
    "RemoraContainer",
    "ScopedContainer",
]
```

##### Testing the Container

```python
import pytest
from remora.core.container import RemoraContainer

def test_container_creation():
    container = RemoraContainer.create_for_testing()

    assert container.event_bus is not None
    assert container.context_builder is not None
    assert container.config is not None

@pytest.mark.asyncio
async def test_container_wiring():
    container = RemoraContainer.create_for_testing()

    # Events should flow to context builder
    from remora.core.events import ToolResultEvent

    event = ToolResultEvent(
        tool_name="test",
        output_preview="result",
        is_error=False,
    )
    await container.event_bus.emit(event)

    actions = container.context_builder.get_recent_actions()
    assert len(actions) == 1
    assert actions[0].tool == "test"
```

---

### B2: Component-Based UI Architecture

**Goal:** Replace procedural HTML generation with composable, reusable components.

#### Overview

Create a component system that:
1. Defines a `Component` base class with `render()` method
2. Provides common components (Card, List, Button, etc.)
3. Allows type-safe composition
4. Supports both static rendering and Datastar integration

#### Implementation

##### Step 1: Create Component Base

**Create:** `src/remora/ui/components/__init__.py`

```python
"""Component-based UI system for Remora."""

from remora.ui.components.base import Component, RawHTML
from remora.ui.components.layout import Card, Container, FlexRow, Grid, Panel
from remora.ui.components.controls import Button, Input, Select
from remora.ui.components.data import List, ListItem, ProgressBar, StatusBadge
from remora.ui.components.dashboard import (
    AgentStatusList,
    BlockedAgentCard,
    EventsList,
    GraphLauncher,
    ResultsList,
)

__all__ = [
    # Base
    "Component",
    "RawHTML",
    # Layout
    "Card",
    "Container",
    "FlexRow",
    "Grid",
    "Panel",
    # Controls
    "Button",
    "Input",
    "Select",
    # Data Display
    "List",
    "ListItem",
    "ProgressBar",
    "StatusBadge",
    # Dashboard
    "AgentStatusList",
    "BlockedAgentCard",
    "EventsList",
    "GraphLauncher",
    "ResultsList",
]
```

##### Step 2: Create Base Component

**Create:** `src/remora/ui/components/base.py`

```python
"""Base component classes."""

from __future__ import annotations

import html
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class Component(ABC):
    """Abstract base class for UI components.

    All components must implement the render() method which
    returns an HTML string.

    Example:
        class MyComponent(Component):
            def __init__(self, text: str):
                self.text = text

            def render(self) -> str:
                return f'<p>{html.escape(self.text)}</p>'
    """

    @abstractmethod
    def render(self) -> str:
        """Render the component to an HTML string."""
        ...

    def __str__(self) -> str:
        """Allow components to be used in f-strings."""
        return self.render()

    def __add__(self, other: "Component | str") -> "ComponentGroup":
        """Allow combining components with +."""
        return ComponentGroup([self, other])


@dataclass
class ComponentGroup(Component):
    """A group of components rendered sequentially."""

    children: list[Component | str] = field(default_factory=list)

    def render(self) -> str:
        parts = []
        for child in self.children:
            if isinstance(child, Component):
                parts.append(child.render())
            else:
                parts.append(str(child))
        return "".join(parts)

    def __add__(self, other: "Component | str") -> "ComponentGroup":
        return ComponentGroup([*self.children, other])


@dataclass
class RawHTML(Component):
    """Render raw HTML without escaping.

    Use with caution - only for trusted content.
    """

    content: str

    def render(self) -> str:
        return self.content


@dataclass
class Element(Component):
    """A generic HTML element.

    This is the building block for all other components.
    """

    tag: str
    content: Component | str = ""
    id: str | None = None
    class_: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    data_attrs: dict[str, str] = field(default_factory=dict)
    self_closing: bool = False

    def render(self) -> str:
        attr_parts = []

        if self.id:
            attr_parts.append(f'id="{html.escape(self.id)}"')

        if self.class_:
            attr_parts.append(f'class="{html.escape(self.class_)}"')

        for key, value in self.attrs.items():
            if value is not None:
                safe_key = key.replace("_", "-")
                attr_parts.append(f'{safe_key}="{html.escape(str(value))}"')

        for key, value in self.data_attrs.items():
            safe_key = key.replace("_", "-")
            attr_parts.append(f'data-{safe_key}="{html.escape(str(value))}"')

        attr_str = " ".join(attr_parts)

        if self.self_closing:
            return f"<{self.tag} {attr_str}/>" if attr_str else f"<{self.tag}/>"

        content = self.content.render() if isinstance(self.content, Component) else html.escape(str(self.content))

        if attr_str:
            return f"<{self.tag} {attr_str}>{content}</{self.tag}>"
        return f"<{self.tag}>{content}</{self.tag}>"


def escape(text: str) -> str:
    """Escape HTML special characters."""
    return html.escape(text)


__all__ = ["Component", "ComponentGroup", "Element", "RawHTML", "escape"]
```

##### Step 3: Create Layout Components

**Create:** `src/remora/ui/components/layout.py`

```python
"""Layout components."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from remora.ui.components.base import Component, Element


@dataclass
class Container(Component):
    """A generic container div."""

    children: list[Component | str] = field(default_factory=list)
    id: str | None = None
    class_: str | None = None

    def render(self) -> str:
        content = "".join(
            c.render() if isinstance(c, Component) else str(c)
            for c in self.children
        )
        return Element(
            tag="div",
            content=RawHTML(content),
            id=self.id,
            class_=self.class_,
        ).render()


@dataclass
class Card(Component):
    """A card with optional title and content."""

    title: str | None = None
    content: Component | str = ""
    class_: str = "card"

    def render(self) -> str:
        parts = []

        if self.title:
            parts.append(Element(
                tag="div",
                content=self.title,
                class_="card-title",
            ).render())

        if isinstance(self.content, Component):
            parts.append(self.content.render())
        else:
            parts.append(str(self.content))

        return Element(
            tag="div",
            content=RawHTML("".join(parts)),
            class_=self.class_,
        ).render()


@dataclass
class Panel(Component):
    """A panel section with header."""

    header: str
    content: Component | str
    id: str | None = None

    def render(self) -> str:
        header_html = Element(
            tag="div",
            content=self.header,
            id=f"{self.id}-header" if self.id else None,
        ).render()

        content_html = (
            self.content.render()
            if isinstance(self.content, Component)
            else str(self.content)
        )

        return Element(
            tag="div",
            content=RawHTML(header_html + content_html),
            id=self.id,
        ).render()


@dataclass
class FlexRow(Component):
    """Horizontal flex container."""

    children: list[Component | str] = field(default_factory=list)
    gap: str = "1rem"
    justify: str = "flex-start"
    align: str = "center"

    def render(self) -> str:
        content = "".join(
            c.render() if isinstance(c, Component) else str(c)
            for c in self.children
        )
        return Element(
            tag="div",
            content=RawHTML(content),
            attrs={
                "style": f"display:flex;gap:{self.gap};justify-content:{self.justify};align-items:{self.align}",
            },
        ).render()


@dataclass
class Grid(Component):
    """CSS Grid container."""

    children: list[Component | str] = field(default_factory=list)
    columns: str = "repeat(auto-fit, minmax(300px, 1fr))"
    gap: str = "1rem"

    def render(self) -> str:
        content = "".join(
            c.render() if isinstance(c, Component) else str(c)
            for c in self.children
        )
        return Element(
            tag="div",
            content=RawHTML(content),
            attrs={
                "style": f"display:grid;grid-template-columns:{self.columns};gap:{self.gap}",
            },
        ).render()


# Import RawHTML for use in this module
from remora.ui.components.base import RawHTML

__all__ = ["Card", "Container", "FlexRow", "Grid", "Panel"]
```

##### Step 4: Create Data Display Components

**Create:** `src/remora/ui/components/data.py`

```python
"""Data display components."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any

from remora.ui.components.base import Component, Element, RawHTML


@dataclass
class ListItem(Component):
    """A single list item."""

    content: Component | str
    class_: str | None = None

    def render(self) -> str:
        content = (
            self.content.render()
            if isinstance(self.content, Component)
            else html.escape(str(self.content))
        )
        return Element(
            tag="div",
            content=RawHTML(content),
            class_=self.class_,
        ).render()


@dataclass
class List(Component):
    """A list of items."""

    items: list[Component | str] = field(default_factory=list)
    id: str | None = None
    class_: str | None = None
    empty_message: str = "No items"

    def render(self) -> str:
        if not self.items:
            return Element(
                tag="div",
                content=Element(
                    tag="div",
                    content=self.empty_message,
                    class_="empty-state",
                ),
                id=self.id,
                class_=self.class_,
            ).render()

        items_html = "".join(
            item.render() if isinstance(item, Component) else html.escape(str(item))
            for item in self.items
        )

        return Element(
            tag="div",
            content=RawHTML(items_html),
            id=self.id,
            class_=self.class_,
        ).render()


@dataclass
class StatusBadge(Component):
    """A status indicator badge."""

    status: str  # e.g., "running", "completed", "failed"
    label: str | None = None

    def render(self) -> str:
        indicator = Element(
            tag="span",
            content="",
            class_=f"state-indicator {self.status}",
        ).render()

        if self.label:
            label_el = Element(
                tag="span",
                content=self.label,
                class_="status-label",
            ).render()
            return indicator + label_el

        return indicator


@dataclass
class ProgressBar(Component):
    """A progress bar with text."""

    total: int
    completed: int
    failed: int = 0

    def render(self) -> str:
        if self.total <= 0:
            percent = 0
        else:
            percent = min(100, int((self.completed / self.total) * 100))

        fill = Element(
            tag="div",
            content="",
            id="progress-fill",
            class_="progress-fill",
            attrs={"style": f"width: {percent}%"},
        ).render()

        bar = Element(
            tag="div",
            content=RawHTML(fill),
            class_="progress-bar",
        ).render()

        suffix = f" ({self.failed} failed)" if self.failed else ""
        text = Element(
            tag="div",
            content=f"{self.completed}/{self.total} agents completed{suffix}",
            class_="progress-text",
        ).render()

        return Element(
            tag="div",
            content=RawHTML(bar + text),
            class_="progress-container",
        ).render()


__all__ = ["List", "ListItem", "ProgressBar", "StatusBadge"]
```

##### Step 5: Create Dashboard Components

**Create:** `src/remora/ui/components/dashboard.py`

```python
"""Dashboard-specific components."""

from __future__ import annotations

import html
import json
import time
from dataclasses import dataclass, field
from typing import Any

from remora.ui.components.base import Component, Element, RawHTML
from remora.ui.components.data import List, ListItem, ProgressBar, StatusBadge
from remora.ui.components.layout import Card


@dataclass
class EventItem(Component):
    """A single event in the events list."""

    event: dict[str, Any]

    def render(self) -> str:
        timestamp = self.event.get("timestamp", 0)
        if timestamp:
            timestamp_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
        else:
            timestamp_str = "--:--:--"

        event_type = self.event.get("type", "")
        agent_id = self.event.get("agent_id", "")
        kind = self.event.get("kind", "")
        label = f"{kind}:{event_type}" if kind else event_type

        parts = [
            Element(tag="span", content=timestamp_str, class_="event-time").render(),
            Element(tag="span", content=label, class_="event-type").render(),
        ]

        if agent_id:
            parts.append(
                Element(tag="span", content=f"@{agent_id}", class_="event-agent").render()
            )

        return Element(
            tag="div",
            content=RawHTML("".join(parts)),
            class_="event",
        ).render()


@dataclass
class EventsList(Component):
    """List of recent events."""

    events: list[dict[str, Any]] = field(default_factory=list)
    max_display: int = 50

    def render(self) -> str:
        if not self.events:
            return List(
                id="events-list",
                class_="events-list",
                empty_message="No events yet",
            ).render()

        items = [EventItem(e) for e in reversed(self.events[-self.max_display:])]
        return List(
            items=items,
            id="events-list",
            class_="events-list",
        ).render()


@dataclass
class AgentStatusItem(Component):
    """A single agent status item."""

    agent_id: str
    state_info: dict[str, Any]

    def render(self) -> str:
        state = self.state_info.get("state", "pending")
        name = self.state_info.get("name", self.agent_id)

        badge = StatusBadge(status=state).render()
        name_el = Element(
            tag="span",
            content=name,
            class_="agent-name",
        ).render()

        return Element(
            tag="div",
            content=RawHTML(badge + name_el),
            class_="agent-item",
        ).render()


@dataclass
class AgentStatusList(Component):
    """List of agent statuses."""

    agent_states: dict[str, dict[str, Any]] = field(default_factory=dict)

    def render(self) -> str:
        if not self.agent_states:
            return List(
                id="agent-status",
                class_="agent-status",
                empty_message="No agents started yet",
            ).render()

        items = [
            AgentStatusItem(agent_id, info)
            for agent_id, info in self.agent_states.items()
        ]
        return List(
            items=items,
            id="agent-status",
            class_="agent-status",
        ).render()


@dataclass
class BlockedAgentCard(Component):
    """Card for a blocked agent awaiting input."""

    blocked: dict[str, Any]

    def render(self) -> str:
        agent_id = self.blocked.get("agent_id", "")
        question = self.blocked.get("question", "")
        options = self.blocked.get("options", [])
        request_id = self.blocked.get("request_id", "")

        key = f"{agent_id}:{question}".replace(":", "_").replace(" ", "_")

        if options:
            options_html = "".join(
                Element(tag="option", content=opt, attrs={"value": opt}).render()
                for opt in options
            )
            input_html = Element(
                tag="select",
                content=RawHTML(options_html),
                id=f"answer-{key}",
                data_attrs={"bind": f"responseDraft.{key}"},
            ).render()
        else:
            input_html = Element(
                tag="input",
                id=f"answer-{key}",
                attrs={"placeholder": "Your response", "type": "text"},
                data_attrs={"bind": f"responseDraft.{key}"},
                self_closing=True,
            ).render()

        # Escape for JS string
        escaped_request_id = request_id.replace("'", "\\'")
        button_html = Element(
            tag="button",
            content="Submit",
            attrs={"type": "button"},
            data_attrs={
                "on": "click",
                "on-click": f"""
                    const draft = $responseDraft?.{key}?.trim();
                    if (!draft) {{
                        alert('Response required.');
                        return;
                    }}
                    @post('/input', {{request_id: '{escaped_request_id}', response: draft}});
                """,
            },
        ).render()

        form = Element(
            tag="div",
            content=RawHTML(input_html + button_html),
            class_="response-form",
        ).render()

        agent_label = Element(
            tag="div",
            content=f"Agent: {html.escape(agent_id)}",
            class_="agent-id",
        ).render()

        question_el = Element(
            tag="div",
            content=question,
            class_="question",
        ).render()

        return Element(
            tag="div",
            content=RawHTML(agent_label + question_el + form),
            class_="blocked-agent",
        ).render()


@dataclass
class GraphLauncher(Component):
    """Graph launcher form."""

    recent_targets: list[str] = field(default_factory=list)
    bundle_default: str = ""

    def render(self) -> str:
        defaults = {
            "graphLauncher": {
                "target_path": "",
                "bundle": self.bundle_default or "",
            }
        }
        signals_attr = html.escape(json.dumps(defaults), quote=True)

        target_input = Element(
            tag="input",
            attrs={
                "placeholder": "Target path (file or directory)",
                "type": "text",
                "id": "target-path",
                "autocomplete": "off",
            },
            data_attrs={"bind": "graphLauncher.target_path"},
            self_closing=True,
        ).render()

        bundle_input = Element(
            tag="input",
            attrs={
                "placeholder": "Bundle name (e.g., lint, docstring)",
                "type": "text",
            },
            data_attrs={"bind": "graphLauncher.bundle"},
            self_closing=True,
        ).render()

        run_button = Element(
            tag="button",
            content="Run Graph",
            attrs={"type": "button"},
            data_attrs={
                "on": "click",
                "on-click": """
                    const target = $graphLauncher?.target_path?.trim();
                    const bundle = $graphLauncher?.bundle?.trim() || 'lint';
                    if (!target) {
                        alert('Target path is required.');
                        return;
                    }
                    @post('/run', {target_path: target, bundle: bundle});
                """,
            },
        ).render()

        root_button = Element(
            tag="button",
            content="Run Root Graph",
            attrs={"type": "button"},
            data_attrs={
                "on": "click",
                "on-click": """
                    const bundle = $graphLauncher?.bundle?.trim() || 'lint';
                    @post('/run', {target_path: '.', bundle: bundle});
                """,
            },
        ).render()

        form = Element(
            tag="div",
            content=RawHTML(target_input + bundle_input + run_button + root_button),
            class_="graph-launcher-form",
        ).render()

        signals_div = Element(
            tag="div",
            content="",
            attrs={"style": "display:none"},
            data_attrs={"signals__ifmissing": signals_attr},
        ).render()

        recent_panel = ""
        if self.recent_targets:
            recent_buttons = "".join(
                Element(
                    tag="button",
                    content=target,
                    attrs={"type": "button"},
                    class_="recent-target",
                    data_attrs={
                        "on": "click",
                        "on-click": f"$graphLauncher.target_path = '{self._escape_js(target)}';",
                    },
                ).render()
                for target in self.recent_targets
            )
            recent_panel = Element(
                tag="div",
                content=RawHTML(
                    Element(tag="div", content="Recent targets", class_="recent-label").render()
                    + recent_buttons
                ),
                class_="recent-targets",
            ).render()

        return Card(
            title="Run Agent Graph",
            content=RawHTML(form + recent_panel + signals_div),
            class_="card graph-launcher-card",
        ).render()

    @staticmethod
    def _escape_js(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


@dataclass
class ResultsList(Component):
    """List of agent results."""

    results: list[dict[str, Any]] = field(default_factory=list)
    max_display: int = 10

    def render(self) -> str:
        if not self.results:
            return List(
                id="results-list",
                class_="results",
                empty_message="No results yet",
            ).render()

        items = []
        for result in self.results[:self.max_display]:
            agent_el = Element(
                tag="div",
                content=result.get("agent_id", ""),
                class_="result-agent",
            ).render()
            content_el = Element(
                tag="div",
                content=result.get("content", ""),
                class_="result-content",
            ).render()
            items.append(ListItem(
                content=RawHTML(agent_el + content_el),
                class_="result-item",
            ))

        return List(
            items=items,
            id="results-list",
            class_="results",
        ).render()


__all__ = [
    "AgentStatusList",
    "BlockedAgentCard",
    "EventItem",
    "EventsList",
    "GraphLauncher",
    "ResultsList",
]
```

##### Step 6: Refactor view.py to Use Components

**Modify:** `src/remora/ui/view.py`

```python
"""UI rendering helpers for the Datastar HTML view."""

from __future__ import annotations

from typing import Any

from remora.ui.components import (
    AgentStatusList,
    Card,
    EventsList,
    GraphLauncher,
    ProgressBar,
    ResultsList,
)
from remora.ui.components.base import Element, RawHTML


def render_blocked_list(blocked: list[dict[str, Any]]) -> str:
    """Render the blocked agents list."""
    from remora.ui.components.dashboard import BlockedAgentCard
    from remora.ui.components.data import List

    if not blocked:
        return List(
            id="blocked-agents",
            class_="blocked-agents",
            empty_message="No agents waiting for input",
        ).render()

    cards = [BlockedAgentCard(b) for b in blocked]
    return List(
        items=cards,
        id="blocked-agents",
        class_="blocked-agents",
    ).render()


def render_dashboard(state: dict[str, Any], *, bundle_default: str = "") -> str:
    """Render the full dashboard using components."""
    events = state.get("events", [])
    blocked = state.get("blocked", [])
    agent_states = state.get("agent_states", {})
    progress = state.get("progress", {"total": 0, "completed": 0, "failed": 0})
    results = state.get("results", [])
    recent_targets = state.get("recent_targets", [])

    # Header
    header = Element(
        tag="div",
        content=RawHTML(
            Element(tag="div", content="Remora Dashboard").render()
            + Element(
                tag="div",
                content=f"Agents: {progress['completed']}/{progress['total']}",
                class_="status",
            ).render()
        ),
        class_="header",
    ).render()

    # Events panel
    events_panel = Element(
        tag="div",
        content=RawHTML(
            Element(tag="div", content="Events Stream", id="events-header").render()
            + EventsList(events=events).render()
        ),
        id="events-panel",
    ).render()

    # Main panel cards
    graph_launcher_card = GraphLauncher(
        recent_targets=recent_targets,
        bundle_default=bundle_default,
    ).render()

    blocked_card = Card(
        title="Blocked Agents",
        content=RawHTML(render_blocked_list(blocked)),
    ).render()

    status_card = Card(
        title="Agent Status",
        content=AgentStatusList(agent_states=agent_states),
    ).render()

    results_card = Card(
        title="Results",
        content=ResultsList(results=results),
    ).render()

    progress_card = Card(
        title="Graph Execution",
        content=ProgressBar(
            total=progress["total"],
            completed=progress["completed"],
            failed=progress.get("failed", 0),
        ),
    ).render()

    main_panel = Element(
        tag="div",
        content=RawHTML(
            graph_launcher_card + blocked_card + status_card + results_card + progress_card
        ),
        id="main-panel",
    ).render()

    main = Element(
        tag="div",
        content=RawHTML(events_panel + main_panel),
        class_="main",
    ).render()

    return Element(
        tag="main",
        content=RawHTML(header + main),
        id="remora-root",
    ).render()


# Keep render_tag for backwards compatibility
def render_tag(tag: str, content: str = "", **attrs: Any) -> str:
    """Legacy function - use Element component instead."""
    return Element(
        tag=tag,
        content=RawHTML(content) if content else "",
        class_=attrs.pop("class_", None),
        id=attrs.pop("id", None),
        attrs=attrs,
    ).render()


__all__ = ["render_dashboard", "render_tag"]
```

---

### B4: Streaming File Sync

**Goal:** Replace full directory sync with lazy/incremental synchronization.

#### Implementation

##### Step 1: Create StreamingSync Class

**Create:** `src/remora/core/streaming_sync.py`

```python
"""Streaming file synchronization for large projects."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Statistics for sync operations."""
    files_synced: int = 0
    bytes_synced: int = 0
    files_skipped: int = 0
    errors: int = 0


@dataclass
class StreamingSyncManager:
    """Manages lazy/incremental file synchronization.

    Instead of syncing all files upfront, this manager:
    1. Tracks which files have been synced
    2. Syncs files on-demand when first accessed
    3. Optionally watches for changes and syncs incrementally
    """

    project_root: Path
    workspace: Any  # Cairn workspace
    ignore_checker: Callable[[Path], bool]

    _synced_files: Set[str] = field(default_factory=set)
    _pending_syncs: dict[str, asyncio.Task] = field(default_factory=dict)
    _stats: SyncStats = field(default_factory=SyncStats)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def ensure_synced(self, rel_path: str) -> bool:
        """Ensure a specific file is synced to workspace.

        Args:
            rel_path: Relative path within project

        Returns:
            True if file is now synced, False otherwise
        """
        if rel_path in self._synced_files:
            return True

        async with self._lock:
            # Double-check after acquiring lock
            if rel_path in self._synced_files:
                return True

            full_path = self.project_root / rel_path

            if not full_path.exists():
                logger.debug("File not found: %s", full_path)
                return False

            if full_path.is_dir():
                return False

            if self.ignore_checker(full_path):
                self._stats.files_skipped += 1
                return False

            try:
                content = await asyncio.to_thread(full_path.read_bytes)
                await self.workspace.files.write(rel_path, content, mode="binary")
                self._synced_files.add(rel_path)
                self._stats.files_synced += 1
                self._stats.bytes_synced += len(content)
                return True
            except Exception as exc:
                logger.warning("Failed to sync %s: %s", rel_path, exc)
                self._stats.errors += 1
                return False

    async def ensure_directory_synced(
        self,
        rel_dir: str,
        *,
        recursive: bool = True,
        max_files: int | None = None,
    ) -> int:
        """Sync all files in a directory.

        Args:
            rel_dir: Relative directory path
            recursive: Whether to sync subdirectories
            max_files: Maximum files to sync (None for unlimited)

        Returns:
            Number of files synced
        """
        full_dir = self.project_root / rel_dir
        if not full_dir.exists() or not full_dir.is_dir():
            return 0

        synced = 0
        pattern = "**/*" if recursive else "*"

        for path in full_dir.glob(pattern):
            if max_files is not None and synced >= max_files:
                break

            if path.is_file():
                try:
                    rel_path = str(path.relative_to(self.project_root))
                    if await self.ensure_synced(rel_path):
                        synced += 1
                except ValueError:
                    continue

        return synced

    async def sync_batch(
        self,
        paths: list[str],
        *,
        concurrency: int = 10,
    ) -> int:
        """Sync multiple files concurrently.

        Args:
            paths: List of relative paths to sync
            concurrency: Maximum concurrent sync operations

        Returns:
            Number of files successfully synced
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def sync_with_limit(path: str) -> bool:
            async with semaphore:
                return await self.ensure_synced(path)

        results = await asyncio.gather(
            *[sync_with_limit(p) for p in paths],
            return_exceptions=True,
        )

        return sum(1 for r in results if r is True)

    def is_synced(self, rel_path: str) -> bool:
        """Check if a file has been synced."""
        return rel_path in self._synced_files

    def get_stats(self) -> SyncStats:
        """Get synchronization statistics."""
        return self._stats

    def clear(self) -> None:
        """Clear sync state (for testing)."""
        self._synced_files.clear()
        self._stats = SyncStats()


class FileWatcher:
    """Watch for file changes and sync incrementally.

    Uses watchfiles for efficient cross-platform file watching.
    """

    def __init__(
        self,
        sync_manager: StreamingSyncManager,
        *,
        debounce_ms: int = 100,
    ):
        self._sync = sync_manager
        self._debounce_ms = debounce_ms
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start watching for changes."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        """Stop watching for changes."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _watch_loop(self) -> None:
        """Main watch loop."""
        try:
            import watchfiles
        except ImportError:
            logger.warning("watchfiles not installed - file watching disabled")
            return

        try:
            async for changes in watchfiles.awatch(
                self._sync.project_root,
                debounce=self._debounce_ms,
            ):
                if not self._running:
                    break

                for change_type, path_str in changes:
                    try:
                        path = Path(path_str)
                        rel_path = str(path.relative_to(self._sync.project_root))

                        if change_type in (watchfiles.Change.added, watchfiles.Change.modified):
                            await self._sync.ensure_synced(rel_path)
                        elif change_type == watchfiles.Change.deleted:
                            # Could implement deletion sync here
                            pass
                    except ValueError:
                        continue
                    except Exception as exc:
                        logger.debug("Watch error for %s: %s", path_str, exc)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("File watcher error: %s", exc)


__all__ = ["FileWatcher", "StreamingSyncManager", "SyncStats"]
```

##### Step 2: Integrate with CairnWorkspaceService

**Modify:** `src/remora/core/cairn_bridge.py`

Add the streaming sync integration:

```python
from remora.core.streaming_sync import StreamingSyncManager, FileWatcher, SyncStats

class CairnWorkspaceService:
    def __init__(self, ...):
        # ... existing initialization ...
        self._streaming_sync: StreamingSyncManager | None = None
        self._file_watcher: FileWatcher | None = None

    async def initialize(
        self,
        *,
        sync_mode: SyncMode = SyncMode.FULL,
        watch_changes: bool = False,
    ) -> None:
        """Initialize with streaming sync support."""
        # ... existing workspace creation ...

        if sync_mode == SyncMode.FULL:
            await self._sync_project_to_workspace()
        elif sync_mode == SyncMode.LAZY:
            self._streaming_sync = StreamingSyncManager(
                project_root=self._project_root,
                workspace=self._stable_workspace,
                ignore_checker=self._should_ignore,
            )

        if watch_changes and self._streaming_sync:
            self._file_watcher = FileWatcher(self._streaming_sync)
            await self._file_watcher.start()

    async def ensure_file_synced(self, rel_path: str) -> bool:
        """Ensure a file is synced (for lazy mode)."""
        if self._streaming_sync:
            return await self._streaming_sync.ensure_synced(rel_path)
        return True  # Already synced in full mode

    def get_sync_stats(self) -> SyncStats | None:
        """Get streaming sync statistics."""
        if self._streaming_sync:
            return self._streaming_sync.get_stats()
        return None

    async def close(self) -> None:
        """Clean up resources."""
        if self._file_watcher:
            await self._file_watcher.stop()
        # ... existing cleanup ...
```

---

### B6: Event Sourcing for Execution History

**Goal:** Persist all events to enable replay, audit, and time-travel debugging.

#### Implementation

##### Step 1: Create Event Store

**Create:** `src/remora/core/event_store.py`

```python
"""Event sourcing storage for Remora events."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, TypeVar

from structured_agents.events import Event as StructuredEvent

from remora.core.events import RemoraEvent


T = TypeVar("T", bound=RemoraEvent)


class EventStore:
    """SQLite-backed event store for event sourcing.

    Features:
    - Append-only event log per graph
    - Full event replay capability
    - Time-based and type-based queries
    - Async interface backed by thread pool

    Schema:
        events (
            id INTEGER PRIMARY KEY,
            graph_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,  -- JSON
            timestamp REAL NOT NULL,
            created_at REAL NOT NULL
        )
    """

    def __init__(self, db_path: Path | str):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the database and create tables."""
        async with self._lock:
            self._conn = await asyncio.to_thread(
                sqlite3.connect,
                str(self._db_path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row

            await asyncio.to_thread(
                self._conn.executescript,
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    graph_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_graph_id
                ON events(graph_id);

                CREATE INDEX IF NOT EXISTS idx_events_type
                ON events(event_type);

                CREATE INDEX IF NOT EXISTS idx_events_timestamp
                ON events(timestamp);
                """
            )

    async def append(
        self,
        graph_id: str,
        event: StructuredEvent | RemoraEvent,
    ) -> int:
        """Append an event to the store.

        Args:
            graph_id: The graph execution ID
            event: The event to store

        Returns:
            The event's row ID
        """
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        event_type = type(event).__name__
        payload = self._serialize_event(event)
        timestamp = getattr(event, "timestamp", time.time())
        created_at = time.time()

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                """
                INSERT INTO events (graph_id, event_type, payload, timestamp, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (graph_id, event_type, payload, timestamp, created_at),
            )
            await asyncio.to_thread(self._conn.commit)
            return cursor.lastrowid or 0

    async def replay(
        self,
        graph_id: str,
        *,
        event_types: list[str] | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Replay events for a graph.

        Args:
            graph_id: The graph execution ID
            event_types: Filter to specific event types
            since: Only events after this timestamp
            until: Only events before this timestamp

        Yields:
            Event records as dictionaries
        """
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        query = "SELECT * FROM events WHERE graph_id = ?"
        params: list[Any] = [graph_id]

        if event_types:
            placeholders = ",".join("?" * len(event_types))
            query += f" AND event_type IN ({placeholders})"
            params.extend(event_types)

        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)

        if until is not None:
            query += " AND timestamp <= ?"
            params.append(until)

        query += " ORDER BY timestamp ASC, id ASC"

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                query,
                params,
            )
            rows = await asyncio.to_thread(cursor.fetchall)

        for row in rows:
            yield {
                "id": row["id"],
                "graph_id": row["graph_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload"]),
                "timestamp": row["timestamp"],
                "created_at": row["created_at"],
            }

    async def get_graph_ids(
        self,
        *,
        limit: int = 100,
        since: float | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent graph execution IDs with metadata.

        Args:
            limit: Maximum number of graphs to return
            since: Only graphs started after this timestamp

        Returns:
            List of graph metadata dicts
        """
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        query = """
            SELECT
                graph_id,
                MIN(timestamp) as started_at,
                MAX(timestamp) as ended_at,
                COUNT(*) as event_count
            FROM events
        """
        params: list[Any] = []

        if since is not None:
            query += " WHERE timestamp >= ?"
            params.append(since)

        query += " GROUP BY graph_id ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                query,
                params,
            )
            rows = await asyncio.to_thread(cursor.fetchall)

        return [
            {
                "graph_id": row["graph_id"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "event_count": row["event_count"],
            }
            for row in rows
        ]

    async def get_event_count(self, graph_id: str) -> int:
        """Get the number of events for a graph."""
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                "SELECT COUNT(*) FROM events WHERE graph_id = ?",
                (graph_id,),
            )
            row = await asyncio.to_thread(cursor.fetchone)

        return row[0] if row else 0

    async def delete_graph(self, graph_id: str) -> int:
        """Delete all events for a graph.

        Args:
            graph_id: The graph execution ID

        Returns:
            Number of events deleted
        """
        if self._conn is None:
            raise RuntimeError("EventStore not initialized")

        async with self._lock:
            cursor = await asyncio.to_thread(
                self._conn.execute,
                "DELETE FROM events WHERE graph_id = ?",
                (graph_id,),
            )
            await asyncio.to_thread(self._conn.commit)
            return cursor.rowcount

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            async with self._lock:
                await asyncio.to_thread(self._conn.close)
                self._conn = None

    def _serialize_event(self, event: StructuredEvent | RemoraEvent) -> str:
        """Serialize an event to JSON."""
        if is_dataclass(event):
            data = asdict(event)
        elif hasattr(event, "__dict__"):
            data = dict(vars(event))
        else:
            data = {"value": str(event)}

        return json.dumps(data, default=str)


class EventSourcedBus:
    """An EventBus wrapper that persists events to an EventStore.

    This wraps an existing EventBus and adds persistence:
    - All emitted events are stored
    - Events can be replayed
    """

    def __init__(
        self,
        event_bus: "EventBus",
        event_store: EventStore,
        graph_id: str,
    ):
        from remora.core.event_bus import EventBus

        self._bus = event_bus
        self._store = event_store
        self._graph_id = graph_id

    async def emit(self, event: StructuredEvent | RemoraEvent) -> None:
        """Emit and persist an event."""
        # Store first to ensure durability
        await self._store.append(self._graph_id, event)
        # Then emit to handlers
        await self._bus.emit(event)

    async def replay_to_bus(
        self,
        *,
        event_types: list[str] | None = None,
    ) -> int:
        """Replay stored events through the bus.

        Useful for rebuilding state from persisted events.

        Returns:
            Number of events replayed
        """
        count = 0
        async for event_record in self._store.replay(
            self._graph_id,
            event_types=event_types,
        ):
            # Note: This emits raw records, not typed events
            # In a full implementation, you'd deserialize back to event types
            await self._bus.emit(event_record)  # type: ignore
            count += 1
        return count


__all__ = ["EventSourcedBus", "EventStore"]
```

##### Step 2: Integration Example

**Usage in service layer:**

```python
from remora.core.event_store import EventStore, EventSourcedBus
from remora.core.event_bus import EventBus

async def create_sourced_service(
    config: RemoraConfig,
    graph_id: str,
) -> RemoraService:
    """Create a service with event sourcing enabled."""

    # Create event store
    store = EventStore(Path(".remora/events/events.db"))
    await store.initialize()

    # Create wrapped bus
    base_bus = EventBus()
    sourced_bus = EventSourcedBus(base_bus, store, graph_id)

    # Create service with sourced bus
    # Note: This requires the service to accept an EventSourcedBus
    # which has the same interface as EventBus
    service = RemoraService(
        event_bus=sourced_bus,  # type: ignore
        config=config,
    )

    return service
```

##### Step 3: Add Replay Endpoint

**Modify:** `src/remora/adapters/starlette.py`

```python
async def replay(request: Request) -> StreamingResponse:
    """Replay events for a graph as SSE stream."""
    graph_id = request.query_params.get("graph_id")
    if not graph_id:
        return _error("graph_id required", status_code=400)

    # This requires access to the event store
    # Implementation depends on how you wire up the store
    async def generate():
        async for event in service.replay_events(graph_id):
            yield f"event: replay\ndata: {json.dumps(event)}\n\n"

    return _sse_response(generate())

# Add to routes
Route("/replay", replay),
```

---

## Testing Requirements

After implementing all fixes, ensure:

### Unit Tests

1. **Event Bus Tests**
   - No global state tests (should use fresh instances)
   - Concurrent emission tests
   - Subscription/unsubscription tests

2. **Graph Tests**
   - Topological sort performance (should handle 1000+ nodes quickly)
   - Cycle detection tests
   - Priority ordering tests

3. **Component Tests**
   - Each component renders correctly
   - Composition works
   - XSS protection (proper escaping)

4. **Event Store Tests**
   - CRUD operations
   - Replay functionality
   - Concurrent access

### Integration Tests

1. Full graph execution with event sourcing
2. Lazy sync with large directories
3. DI container lifecycle

### Performance Tests

1. Topological sort with 10,000 nodes
2. Event store with 100,000 events
3. Streaming sync with 1,000 files

---

## Verification Checklist

After completing all fixes, verify:

- [ ] All tests pass: `pytest tests/ -v`
- [ ] Type checking passes: `mypy src/remora/`
- [ ] No global state: `grep -rn "global\|_singleton" src/`
- [ ] No O(n) list operations: `grep -rn "\.pop(0)" src/`
- [ ] No duplicate exports: Compare `__all__` lists
- [ ] All paths accept `Path | str`
- [ ] Ignore patterns are configurable
- [ ] EventKind enum is used for event categorization
- [ ] Single truncate function in utils
- [ ] DI container is documented and tested
- [ ] Components are documented and tested
- [ ] Streaming sync is tested with mock fs
- [ ] Event store has ACID guarantees

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-02-27 | Claude (Opus 4.5) | Initial document |
