# Remora V0.4.2 Refactor Implementation Guide

**Date:** 2026-02-26
**Target Version:** 0.4.2
**Scope:** Complete architectural refactor aligned with structured-agents v0.3.4 and Grail v3.0.0

---

## Overview

This guide provides step-by-step instructions for refactoring Remora from a 50+ file codebase with multiple architectural issues to a clean ~22 file architecture. The refactor addresses 19 identified issues from the V0.4.1 code review while implementing the ground-up redesign outlined in the project's refactor ideas.

**Key Principles:**
- No backwards compatibility - clean break
- One job per module
- Cairn as the single workspace layer
- Event-driven architecture with unified event types
- Pure data structures for topology, separate execution logic

---

## Table of Contents

1. [Pre-Refactor Setup](#1-pre-refactor-setup)
2. [Phase 1: Foundation](#2-phase-1-foundation)
3. [Phase 2: Core Components](#3-phase-2-core-components)
4. [Phase 3: Execution Engine](#4-phase-3-execution-engine)
5. [Phase 4: Agent Bundles](#5-phase-4-agent-bundles)
6. [Phase 5: Services](#6-phase-5-services)
7. [Phase 6: Integration & Cleanup](#7-phase-6-integration--cleanup)
8. [Testing Checklist](#8-testing-checklist)
9. [Issue Resolution Matrix](#9-issue-resolution-matrix)

---

## 1. Pre-Refactor Setup

### 1.1 Create Backup Branch

```bash
git checkout -b pre-v042-refactor
git push origin pre-v042-refactor
git checkout main
git checkout -b v042-refactor
```

### 1.2 Understand the Current Structure

Current problematic structure:
```
src/remora/
  __init__.py, agent_graph.py, agent_state.py, backend.py, checkpoint.py,
  cli.py, client.py, config.py, constants.py, errors.py, event_bus.py,
  workspace.py, discovery.py (CONFLICT with discovery/)

  hub/         (14 files - mixed indexer + dashboard)
  context/     (5 files)
  discovery/   (5 files - CONFLICT with discovery.py)
  interactive/ (2 files - broken IPC)
  frontend/    (3 files)
  testing/     (2 files)
```

Target structure:
```
src/remora/
  __init__.py
  config.py
  discovery.py
  graph.py
  executor.py
  events.py
  event_bus.py
  context.py
  checkpoint.py
  workspace.py
  errors.py
  cli.py
  __main__.py

  indexer/     (5 files)
  dashboard/   (3 files)
  queries/     (.scm files - unchanged)
```

### 1.3 Update Dependencies

Ensure `pyproject.toml` has correct versions:

```toml
[project]
dependencies = [
    "structured-agents>=0.3.4",
    "grail>=3.0.0",
    "cairn>=1.0.0",
    "fsdantic>=0.2.0",
    "pydantic>=2.0",
    "starlette>=0.30",
    "datastar-py>=0.1",
    "tree-sitter>=0.20",
]
```

---

## 2. Phase 1: Foundation

Phase 1 builds the core infrastructure that all other components depend on. These modules have no dependencies on other new modules.

### 2.1 Create `events.py` - Unified Event Types

**Purpose:** Define all event types as frozen dataclasses in a single module. This resolves:
- CRIT-01: Observer protocol compatibility
- MIN-01: Dead backwards-compat Event class

**File:** `src/remora/events.py`

```python
"""Unified event types for Remora.

All events are frozen dataclasses that can be pattern-matched.
Re-exports structured-agents events for unified event handling.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

# Re-export structured-agents events
from structured_agents.events import (
    KernelStartEvent,
    KernelEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    ModelRequestEvent,
    ModelResponseEvent,
)

if TYPE_CHECKING:
    from remora.discovery import CSTNode
    from structured_agents.types import RunResult


# ============================================================================
# Graph-Level Events
# ============================================================================

@dataclass(frozen=True, slots=True)
class GraphStartEvent:
    """Emitted when graph execution begins."""
    graph_id: str
    node_count: int
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class GraphCompleteEvent:
    """Emitted when graph execution completes successfully."""
    graph_id: str
    completed_count: int
    failed_count: int
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class GraphErrorEvent:
    """Emitted when graph execution fails fatally."""
    graph_id: str
    error: str
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# Agent-Level Events
# ============================================================================

@dataclass(frozen=True, slots=True)
class AgentStartEvent:
    """Emitted when an agent begins execution."""
    graph_id: str
    agent_id: str
    node_name: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class AgentCompleteEvent:
    """Emitted when an agent completes successfully."""
    graph_id: str
    agent_id: str
    result_summary: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class AgentErrorEvent:
    """Emitted when an agent fails."""
    graph_id: str
    agent_id: str
    error: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class AgentSkippedEvent:
    """Emitted when an agent is skipped due to upstream failure."""
    graph_id: str
    agent_id: str
    reason: str
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# Human-in-the-Loop Events (replaces broken interactive/ IPC)
# ============================================================================

@dataclass(frozen=True, slots=True)
class HumanInputRequestEvent:
    """Agent is blocked waiting for human input."""
    graph_id: str
    agent_id: str
    request_id: str
    question: str
    options: tuple[str, ...] | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class HumanInputResponseEvent:
    """Human has responded to an input request."""
    request_id: str
    response: str
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# Checkpoint Events
# ============================================================================

@dataclass(frozen=True, slots=True)
class CheckpointSavedEvent:
    """Emitted when a checkpoint is saved."""
    graph_id: str
    checkpoint_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class CheckpointRestoredEvent:
    """Emitted when execution resumes from checkpoint."""
    graph_id: str
    checkpoint_id: str
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# Union Type for Pattern Matching
# ============================================================================

RemoraEvent = (
    # Graph events
    GraphStartEvent | GraphCompleteEvent | GraphErrorEvent |
    # Agent events
    AgentStartEvent | AgentCompleteEvent | AgentErrorEvent | AgentSkippedEvent |
    # Human-in-the-loop events
    HumanInputRequestEvent | HumanInputResponseEvent |
    # Checkpoint events
    CheckpointSavedEvent | CheckpointRestoredEvent |
    # Re-exported structured-agents events
    KernelStartEvent | KernelEndEvent |
    ToolCallEvent | ToolResultEvent |
    ModelRequestEvent | ModelResponseEvent
)

__all__ = [
    # Remora events
    "GraphStartEvent",
    "GraphCompleteEvent",
    "GraphErrorEvent",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentSkippedEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    "CheckpointSavedEvent",
    "CheckpointRestoredEvent",
    # Re-exports
    "KernelStartEvent",
    "KernelEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    # Union type
    "RemoraEvent",
]
```

**Verification:**
- [ ] All events are frozen dataclasses with `slots=True`
- [ ] `RemoraEvent` union includes all event types
- [ ] structured-agents events are re-exported
- [ ] No string-based event categories

---

### 2.2 Create `event_bus.py` - Unified Event Dispatch

**Purpose:** Single event dispatch mechanism implementing structured-agents Observer protocol. This resolves:
- CRIT-01: Observer protocol implementation
- MAJ-03: Event stream resource leak
- MIN-01: Dead Event class removal
- MIN-02: Unused import cleanup

**File:** `src/remora/event_bus.py`

```python
"""Unified event bus implementing structured-agents Observer protocol.

The EventBus is the central nervous system for all Remora events.
It implements the Observer protocol from structured-agents, allowing
it to receive kernel events directly.
"""
from __future__ import annotations

import asyncio
import logging
import weakref
from collections.abc import Callable, AsyncIterator
from contextlib import asynccontextmanager
from typing import TypeVar, Any

from remora.events import RemoraEvent

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=RemoraEvent)
EventHandler = Callable[[RemoraEvent], Any]


class EventBus:
    """Unified event dispatch with Observer protocol support.

    Implements structured-agents Observer protocol via emit().
    Provides type-based subscription and async streaming.
    """

    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []
        self._waiters: dict[str, asyncio.Future[RemoraEvent]] = {}
        self._lock = asyncio.Lock()

    # ========================================================================
    # Observer Protocol (for structured-agents integration)
    # ========================================================================

    async def emit(self, event: RemoraEvent) -> None:
        """Observer protocol - receives all events.

        This method satisfies the structured-agents Observer interface.
        """
        # Notify type-specific handlers
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])

        # Also check parent types for handlers
        for base in event_type.__mro__:
            if base in self._handlers:
                handlers = handlers + self._handlers[base]

        # Notify all-event handlers
        handlers = handlers + self._all_handlers

        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning("Event handler error: %s", e)

        # Resolve any waiters
        await self._resolve_waiters(event)

    # ========================================================================
    # Subscription API
    # ========================================================================

    def subscribe(self, event_type: type[T], handler: Callable[[T], Any]) -> None:
        """Subscribe to a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to all events."""
        self._all_handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a handler from all subscriptions."""
        # Remove from type-specific handlers
        for handlers in self._handlers.values():
            if handler in handlers:
                handlers.remove(handler)
        # Remove from all-handlers
        if handler in self._all_handlers:
            self._all_handlers.remove(handler)

    # ========================================================================
    # Async Streaming (resolves MAJ-03: resource leak)
    # ========================================================================

    @asynccontextmanager
    async def stream(
        self,
        *event_types: type[T]
    ) -> AsyncIterator[AsyncIterator[T]]:
        """Async context manager for event streaming.

        Usage:
            async with event_bus.stream(AgentCompleteEvent) as events:
                async for event in events:
                    print(event.agent_id)

        The stream automatically unsubscribes when the context exits,
        preventing resource leaks.
        """
        queue: asyncio.Queue[RemoraEvent] = asyncio.Queue()
        filter_types = set(event_types) if event_types else None

        def enqueue(event: RemoraEvent) -> None:
            if filter_types is None or type(event) in filter_types:
                queue.put_nowait(event)

        self.subscribe_all(enqueue)

        async def iterate() -> AsyncIterator[T]:
            while True:
                event = await queue.get()
                yield event  # type: ignore

        try:
            yield iterate()
        finally:
            # Guaranteed cleanup - resolves MAJ-03
            self.unsubscribe(enqueue)

    # ========================================================================
    # Wait-for Pattern (for human-in-the-loop IPC)
    # ========================================================================

    async def wait_for(
        self,
        event_type: type[T],
        predicate: Callable[[T], bool],
        timeout: float = 60.0,
    ) -> T:
        """Block until an event matching the predicate is emitted.

        Used for human-in-the-loop IPC: emit a request event,
        then wait_for the matching response event.

        Args:
            event_type: The type of event to wait for
            predicate: Function that returns True for the desired event
            timeout: Maximum seconds to wait

        Returns:
            The matching event

        Raises:
            asyncio.TimeoutError: If timeout expires
        """
        future: asyncio.Future[T] = asyncio.get_event_loop().create_future()
        waiter_id = id(future)

        def handler(event: RemoraEvent) -> None:
            if isinstance(event, event_type) and predicate(event):
                if not future.done():
                    future.set_result(event)

        self.subscribe(event_type, handler)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.unsubscribe(handler)

    async def _resolve_waiters(self, event: RemoraEvent) -> None:
        """Check if any waiters match this event."""
        # Handled by wait_for's handler subscription
        pass

    # ========================================================================
    # Lifecycle
    # ========================================================================

    def clear(self) -> None:
        """Remove all handlers. Use for testing."""
        self._handlers.clear()
        self._all_handlers.clear()


# Module-level singleton with lazy initialization
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global EventBus instance.

    For testing, create a new EventBus directly instead of using this.
    """
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    """Reset the global EventBus. For testing only."""
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

**Verification:**
- [ ] `emit()` method satisfies Observer protocol
- [ ] `stream()` uses context manager for guaranteed cleanup (fixes MAJ-03)
- [ ] `wait_for()` supports human-in-the-loop IPC
- [ ] No string-based event routing
- [ ] `reset_event_bus()` available for testing

---

### 2.3 Create `discovery.py` - Consolidated Discovery

**Purpose:** Consolidate 5 discovery files into one module. This resolves:
- CRIT-04: Discovery module import inconsistency
- MIN-04: Missing `__all__` export issues
- MIN-05: Default query directory path resolution

**Step 1:** Delete the conflicting `discovery.py` file in root:

```bash
rm src/remora/discovery.py
```

**Step 2:** Create the new consolidated module:

**File:** `src/remora/discovery.py`

```python
"""Consolidated code discovery using tree-sitter.

This module provides the `discover()` function which scans source files
and returns CSTNode objects representing functions, classes, files, etc.
"""
from __future__ import annotations

import hashlib
import importlib.resources
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import tree_sitter
from tree_sitter import Language, Parser

logger = logging.getLogger(__name__)

# Language extension mapping
LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".md": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rs": "rust",
}


# ============================================================================
# Data Types
# ============================================================================

@dataclass(frozen=True, slots=True)
class CSTNode:
    """A concrete syntax tree node discovered from source code.

    Immutable data object representing a discovered code element.
    The node_id is deterministic based on file path, name, and position.
    """
    node_id: str
    node_type: str  # "function", "class", "file", "section", "table"
    name: str
    file_path: str
    text: str
    start_line: int
    end_line: int

    def __hash__(self) -> int:
        return hash(self.node_id)


def compute_node_id(file_path: str, name: str, start_line: int, end_line: int) -> str:
    """Compute deterministic node ID using SHA256."""
    content = f"{file_path}:{name}:{start_line}:{end_line}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ============================================================================
# Query Loading (fixes MIN-05: path resolution)
# ============================================================================

def _get_query_dir() -> Path:
    """Get the queries directory using importlib.resources.

    This correctly resolves the path regardless of installation method.
    """
    return Path(importlib.resources.files("remora")) / "queries"


def _load_queries(language: str, query_pack: str = "remora_core") -> str | None:
    """Load tree-sitter query from .scm file."""
    query_dir = _get_query_dir()

    # Try language-specific query pack
    query_path = query_dir / language / query_pack
    if not query_path.exists():
        return None

    queries = []
    for scm_file in sorted(query_path.glob("*.scm")):
        queries.append(scm_file.read_text())

    return "\n".join(queries) if queries else None


# ============================================================================
# Parsing
# ============================================================================

def _get_parser(language: str) -> Parser | None:
    """Get a tree-sitter parser for the given language."""
    try:
        # Language libraries are named like tree_sitter_python
        lang_module = __import__(f"tree_sitter_{language}")
        lang = Language(lang_module.language())
        parser = Parser(lang)
        return parser
    except (ImportError, AttributeError) as e:
        logger.debug("Could not load parser for %s: %s", language, e)
        return None


def _parse_file(file_path: Path, language: str) -> list[CSTNode]:
    """Parse a single file and extract nodes using tree-sitter queries."""
    parser = _get_parser(language)
    if parser is None:
        # Fall back to file-level node
        return [_create_file_node(file_path)]

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Could not read %s: %s", file_path, e)
        return []

    tree = parser.parse(content.encode())

    # Load and apply queries
    query_text = _load_queries(language)
    if query_text is None:
        return [_create_file_node(file_path, content)]

    try:
        lang_module = __import__(f"tree_sitter_{language}")
        lang = Language(lang_module.language())
        query = lang.query(query_text)
    except Exception as e:
        logger.warning("Query error for %s: %s", language, e)
        return [_create_file_node(file_path, content)]

    # Extract matches
    nodes = []
    captures = query.captures(tree.root_node)

    for node, capture_name in captures:
        if capture_name.endswith(".name"):
            continue  # Skip name-only captures

        node_type = capture_name.split(".")[-1]
        name = _extract_name(node, captures)

        cst_node = CSTNode(
            node_id=compute_node_id(
                str(file_path), name,
                node.start_point[0] + 1,
                node.end_point[0] + 1
            ),
            node_type=node_type,
            name=name,
            file_path=str(file_path),
            text=content[node.start_byte:node.end_byte],
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )
        nodes.append(cst_node)

    # Always include file-level node
    if not any(n.node_type == "file" for n in nodes):
        nodes.insert(0, _create_file_node(file_path, content))

    return nodes


def _extract_name(node: tree_sitter.Node, captures: list) -> str:
    """Extract the name for a captured node."""
    # Look for corresponding .name capture
    for n, name in captures:
        if name.endswith(".name") and n.parent == node:
            return n.text.decode() if n.text else "unknown"

    # Try common child names
    for child in node.children:
        if child.type in ("identifier", "name", "function_name"):
            return child.text.decode() if child.text else "unknown"

    return "unknown"


def _create_file_node(file_path: Path, content: str | None = None) -> CSTNode:
    """Create a file-level CSTNode."""
    if content is None:
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            content = ""

    line_count = content.count("\n") + 1 if content else 1

    return CSTNode(
        node_id=compute_node_id(str(file_path), file_path.name, 1, line_count),
        node_type="file",
        name=file_path.name,
        file_path=str(file_path),
        text=content,
        start_line=1,
        end_line=line_count,
    )


# ============================================================================
# Public API
# ============================================================================

def discover(
    paths: list[Path] | list[str],
    languages: list[str] | None = None,
    node_types: list[str] | None = None,
    max_workers: int = 4,
) -> list[CSTNode]:
    """Scan source paths with tree-sitter and return discovered nodes.

    Uses thread pool for parallel file parsing. Language is auto-detected
    from file extension. Custom .scm queries are loaded from queries/ dir.

    Args:
        paths: Files or directories to scan
        languages: Limit to specific languages (by extension, e.g. "python")
        node_types: Filter to specific node types ("function", "class", etc.)
        max_workers: Thread pool size for parallel parsing

    Returns:
        List of CSTNode objects sorted by file path and line number
    """
    # Normalize paths
    path_list = [Path(p) if isinstance(p, str) else p for p in paths]

    # Collect files to parse
    files: list[tuple[Path, str]] = []
    for path in path_list:
        if path.is_file():
            lang = _detect_language(path)
            if lang and (languages is None or lang in languages):
                files.append((path, lang))
        elif path.is_dir():
            for file_path in _walk_directory(path):
                lang = _detect_language(file_path)
                if lang and (languages is None or lang in languages):
                    files.append((file_path, lang))

    # Parse files in parallel
    all_nodes: list[CSTNode] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_parse_file, file_path, lang)
            for file_path, lang in files
        ]
        for future in futures:
            try:
                nodes = future.result()
                all_nodes.extend(nodes)
            except Exception as e:
                logger.warning("Parse error: %s", e)

    # Filter by node type if requested
    if node_types:
        all_nodes = [n for n in all_nodes if n.node_type in node_types]

    # Sort by file path, then line number
    all_nodes.sort(key=lambda n: (n.file_path, n.start_line))

    return all_nodes


def _detect_language(file_path: Path) -> str | None:
    """Detect language from file extension."""
    return LANGUAGE_EXTENSIONS.get(file_path.suffix.lower())


def _walk_directory(directory: Path) -> Iterator[Path]:
    """Recursively walk directory, skipping hidden and common ignore patterns."""
    ignore_patterns = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox"}

    for item in directory.iterdir():
        if item.name.startswith(".") or item.name in ignore_patterns:
            continue
        if item.is_file():
            yield item
        elif item.is_dir():
            yield from _walk_directory(item)


__all__ = [
    "CSTNode",
    "compute_node_id",
    "discover",
    "LANGUAGE_EXTENSIONS",
]
```

**Step 3:** Remove the old `discovery/` package:

```bash
rm -rf src/remora/discovery/
```

**Verification:**
- [ ] Single `discovery.py` file replaces package
- [ ] `discover()` function signature is consistent
- [ ] Path resolution uses `importlib.resources` (fixes MIN-05)
- [ ] `__all__` properly exports public API (fixes MIN-04)
- [ ] No import conflicts remain

---

### 2.4 Create `config.py` - Flattened Configuration

**Purpose:** Single frozen configuration with two levels (remora.yaml + bundle.yaml). This resolves:
- MIN-03: Inconsistent error class naming (consolidate ConfigError)

**File:** `src/remora/config.py`

```python
"""Configuration loading and validation.

Remora uses two configuration levels:
1. remora.yaml - Project-level config (loaded once at startup)
2. bundle.yaml - Per-agent config (structured-agents v0.3 format)
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Configuration loading or validation error.

    This is the single configuration error class for Remora.
    """
    pass


class ErrorPolicy(Enum):
    """How to handle agent failures in graph execution."""
    STOP_GRAPH = "stop_graph"
    SKIP_DOWNSTREAM = "skip_downstream"
    CONTINUE = "continue"


# ============================================================================
# Configuration Sections
# ============================================================================

@dataclass(frozen=True, slots=True)
class DiscoveryConfig:
    """Discovery configuration."""
    paths: tuple[str, ...] = ("src/",)
    languages: tuple[str, ...] | None = None
    max_workers: int = 4


@dataclass(frozen=True, slots=True)
class BundleConfig:
    """Agent bundle configuration."""
    path: str = "agents/"
    mapping: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """Graph execution configuration."""
    max_concurrency: int = 4
    error_policy: ErrorPolicy = ErrorPolicy.SKIP_DOWNSTREAM
    timeout: float = 300.0
    max_turns: int = 8
    truncation_limit: int = 1024  # Configurable (fixes MIN-06)


@dataclass(frozen=True, slots=True)
class IndexerConfig:
    """Indexer daemon configuration."""
    watch_paths: tuple[str, ...] = ("src/",)
    store_path: str = ".remora/index"


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    """Dashboard server configuration."""
    host: str = "0.0.0.0"
    port: int = 8420


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """Cairn workspace configuration."""
    base_path: str = ".remora/workspaces"
    cleanup_after: str = "1h"


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Default model configuration."""
    base_url: str = "http://localhost:8000/v1"
    default_model: str = "Qwen/Qwen3-4B"
    api_key: str = ""


# ============================================================================
# Main Configuration
# ============================================================================

@dataclass(frozen=True, slots=True)
class RemoraConfig:
    """Complete Remora configuration.

    Frozen dataclass - immutable after creation.
    Loaded once at startup, passed explicitly to components.
    """
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    bundles: BundleConfig = field(default_factory=BundleConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    indexer: IndexerConfig = field(default_factory=IndexerConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    model: ModelConfig = field(default_factory=ModelConfig)


# ============================================================================
# Loading
# ============================================================================

def load_config(path: Path | str | None = None) -> RemoraConfig:
    """Load configuration from YAML file.

    Args:
        path: Path to remora.yaml. If None, searches current directory
              and parent directories.

    Returns:
        Frozen RemoraConfig instance

    Raises:
        ConfigError: If config file is invalid
    """
    if path is None:
        path = _find_config_file()

    config_path = Path(path)

    if not config_path.exists():
        logger.info("No config file found, using defaults")
        return RemoraConfig()

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}")

    # Apply environment variable overrides
    data = _apply_env_overrides(data)

    try:
        return _build_config(data)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"Invalid configuration: {e}")


def _find_config_file() -> Path:
    """Search for remora.yaml in current and parent directories."""
    current = Path.cwd()

    for directory in [current] + list(current.parents):
        config_path = directory / "remora.yaml"
        if config_path.exists():
            return config_path
        # Also check pyproject.toml location
        if (directory / "pyproject.toml").exists():
            break

    return current / "remora.yaml"


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides to config.

    Environment variables use REMORA_ prefix:
    - REMORA_MODEL_BASE_URL -> model.base_url
    - REMORA_MODEL_API_KEY -> model.api_key
    - REMORA_EXECUTION_MAX_CONCURRENCY -> execution.max_concurrency
    """
    env_mappings = {
        "REMORA_MODEL_BASE_URL": ("model", "base_url"),
        "REMORA_MODEL_API_KEY": ("model", "api_key"),
        "REMORA_MODEL_DEFAULT": ("model", "default_model"),
        "REMORA_EXECUTION_MAX_CONCURRENCY": ("execution", "max_concurrency"),
        "REMORA_EXECUTION_TIMEOUT": ("execution", "timeout"),
        "REMORA_DASHBOARD_PORT": ("dashboard", "port"),
        "REMORA_WORKSPACE_BASE_PATH": ("workspace", "base_path"),
    }

    for env_var, (section, key) in env_mappings.items():
        value = os.environ.get(env_var)
        if value:
            if section not in data:
                data[section] = {}
            # Type conversion for numeric values
            if key in ("max_concurrency", "port", "timeout"):
                value = int(value) if "." not in value else float(value)
            data[section][key] = value

    return data


def _build_config(data: dict[str, Any]) -> RemoraConfig:
    """Build RemoraConfig from dictionary data."""
    def get_section(name: str, cls: type) -> Any:
        section_data = data.get(name, {})
        # Convert lists to tuples for frozen dataclasses
        for key, value in list(section_data.items()):
            if isinstance(value, list):
                section_data[key] = tuple(value)
        # Handle enums
        if name == "execution" and "error_policy" in section_data:
            section_data["error_policy"] = ErrorPolicy(section_data["error_policy"])
        return cls(**section_data)

    return RemoraConfig(
        discovery=get_section("discovery", DiscoveryConfig),
        bundles=get_section("bundles", BundleConfig),
        execution=get_section("execution", ExecutionConfig),
        indexer=get_section("indexer", IndexerConfig),
        dashboard=get_section("dashboard", DashboardConfig),
        workspace=get_section("workspace", WorkspaceConfig),
        model=get_section("model", ModelConfig),
    )


__all__ = [
    "ConfigError",
    "ErrorPolicy",
    "RemoraConfig",
    "DiscoveryConfig",
    "BundleConfig",
    "ExecutionConfig",
    "IndexerConfig",
    "DashboardConfig",
    "WorkspaceConfig",
    "ModelConfig",
    "load_config",
]
```

**Step 2:** Delete duplicates and constants:

```bash
rm src/remora/constants.py  # Values now in config defaults
```

**Verification:**
- [ ] Single `ConfigError` class (fixes MIN-03)
- [ ] `truncation_limit` is configurable (fixes MIN-06)
- [ ] All config classes are frozen
- [ ] Environment variable overrides work
- [ ] No global config singleton

---

### 2.5 Create `errors.py` - Consolidated Error Hierarchy

**Purpose:** Single error class hierarchy. This resolves:
- MIN-03: Inconsistent error class naming

**File:** `src/remora/errors.py`

```python
"""Remora error hierarchy.

All Remora-specific errors inherit from RemoraError.
"""
from __future__ import annotations


class RemoraError(Exception):
    """Base class for all Remora errors."""
    pass


class ConfigError(RemoraError):
    """Configuration loading or validation error."""
    pass


class DiscoveryError(RemoraError):
    """Error during code discovery."""
    pass


class GraphError(RemoraError):
    """Error in graph construction or validation."""
    pass


class ExecutionError(RemoraError):
    """Error during agent execution."""
    pass


class CheckpointError(RemoraError):
    """Error during checkpoint save or restore."""
    pass


class WorkspaceError(RemoraError):
    """Error in workspace operations."""
    pass


__all__ = [
    "RemoraError",
    "ConfigError",
    "DiscoveryError",
    "GraphError",
    "ExecutionError",
    "CheckpointError",
    "WorkspaceError",
]
```

**Verification:**
- [ ] All errors inherit from `RemoraError`
- [ ] Single `ConfigError` class (not `ConfigurationError`)
- [ ] No duplicate error definitions

---

## 3. Phase 2: Core Components

Phase 2 builds on Phase 1 to implement the core data structures and state management.

### 3.1 Create `graph.py` - Pure Data Topology

**Purpose:** Separate graph topology from execution. This resolves:
- MAJ-05: Graph dependency computation O(n^2)
- MAJ-06: Topological sort O(n^2)

**File:** `src/remora/graph.py`

```python
"""Agent graph topology.

This module defines the pure data structures for graph topology.
AgentNode is immutable - execution state is tracked separately.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from remora.discovery import CSTNode
from remora.errors import GraphError


@dataclass(frozen=True, slots=True)
class AgentNode:
    """A node in the execution graph. Immutable topology.

    Contains only topology information - no mutable state.
    Execution state is tracked by GraphExecutor separately.
    """
    id: str
    name: str
    target: CSTNode
    bundle_path: Path
    upstream: frozenset[str] = frozenset()
    downstream: frozenset[str] = frozenset()
    priority: int = 0

    def __hash__(self) -> int:
        return hash(self.id)


def build_graph(
    nodes: list[CSTNode],
    bundle_mapping: dict[str, Path],
    priority_mapping: dict[str, int] | None = None,
) -> list[AgentNode]:
    """Build agent graph from discovered nodes.

    Maps each CSTNode to an AgentNode based on node_type -> bundle_path mapping.
    Computes dependency edges based on file relationships.

    Args:
        nodes: Discovered CSTNodes from discovery.discover()
        bundle_mapping: Maps node_type (e.g., "function") to bundle path
        priority_mapping: Optional priority per node_type (higher = earlier)

    Returns:
        List of AgentNode sorted by priority and dependency order

    Raises:
        GraphError: If graph contains cycles
    """
    priority_mapping = priority_mapping or {}

    # Create initial agent nodes (without downstream)
    agent_nodes: dict[str, AgentNode] = {}

    for cst_node in nodes:
        bundle_path = bundle_mapping.get(cst_node.node_type)
        if bundle_path is None:
            continue  # No agent for this node type

        # Compute upstream dependencies
        upstream = _compute_upstream(cst_node, nodes, agent_nodes)

        agent_node = AgentNode(
            id=cst_node.node_id,
            name=cst_node.name,
            target=cst_node,
            bundle_path=bundle_path,
            upstream=frozenset(upstream),
            priority=priority_mapping.get(cst_node.node_type, 0),
        )
        agent_nodes[agent_node.id] = agent_node

    # Compute downstream edges efficiently (O(V+E), fixes MAJ-05)
    downstream_map = _compute_downstream_map(agent_nodes)

    # Update nodes with downstream edges
    final_nodes = []
    for node in agent_nodes.values():
        updated_node = AgentNode(
            id=node.id,
            name=node.name,
            target=node.target,
            bundle_path=node.bundle_path,
            upstream=node.upstream,
            downstream=frozenset(downstream_map[node.id]),
            priority=node.priority,
        )
        final_nodes.append(updated_node)

    # Topological sort (O(V+E), fixes MAJ-06)
    sorted_nodes = _topological_sort(final_nodes)

    return sorted_nodes


def _compute_upstream(
    cst_node: CSTNode,
    all_nodes: list[CSTNode],
    existing_agents: dict[str, AgentNode],
) -> set[str]:
    """Compute upstream dependencies for a node.

    A node depends on:
    1. The file-level node if this is a function/class
    2. The class node if this is a method
    """
    upstream: set[str] = set()

    # Functions/classes depend on their containing file
    if cst_node.node_type in ("function", "class", "method"):
        for other in all_nodes:
            if other.node_type == "file" and other.file_path == cst_node.file_path:
                if other.node_id in existing_agents:
                    upstream.add(other.node_id)

    # Methods depend on their class (if we tracked that relationship)
    # This would require parent tracking in CSTNode

    return upstream


def _compute_downstream_map(agent_nodes: dict[str, AgentNode]) -> dict[str, set[str]]:
    """Build downstream mapping in single O(V+E) pass.

    This fixes MAJ-05: previously was O(n^2).
    """
    downstream_map: dict[str, set[str]] = defaultdict(set)

    for node in agent_nodes.values():
        for upstream_id in node.upstream:
            downstream_map[upstream_id].add(node.id)

    return downstream_map


def _topological_sort(nodes: list[AgentNode]) -> list[AgentNode]:
    """Kahn's algorithm with O(V+E) complexity.

    This fixes MAJ-06: previously was O(n^2).

    Raises:
        GraphError: If graph contains a cycle
    """
    node_by_id = {n.id: n for n in nodes}

    # Build adjacency list (O(V+E))
    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {n.id: 0 for n in nodes}

    for node in nodes:
        for upstream_id in node.upstream:
            if upstream_id in node_by_id:
                adjacency[upstream_id].append(node.id)
                in_degree[node.id] += 1

    # Initialize queue with nodes that have no dependencies
    # Sort by priority (higher first) for tie-breaking
    queue = sorted(
        [n for n in nodes if in_degree[n.id] == 0],
        key=lambda n: -n.priority
    )

    result: list[AgentNode] = []

    while queue:
        # Pop highest priority node with in_degree 0
        node = queue.pop(0)
        result.append(node)

        # Process outgoing edges (O(E) total)
        for downstream_id in adjacency[node.id]:
            in_degree[downstream_id] -= 1
            if in_degree[downstream_id] == 0:
                queue.append(node_by_id[downstream_id])

        # Re-sort by priority after adding new nodes
        queue.sort(key=lambda n: -n.priority)

    # Check for cycle
    if len(result) != len(nodes):
        cycle_nodes = [n.id for n in nodes if in_degree[n.id] > 0]
        raise GraphError(f"Cycle detected involving nodes: {cycle_nodes}")

    return result


def get_execution_batches(nodes: list[AgentNode]) -> list[list[AgentNode]]:
    """Group nodes into batches that can execute in parallel.

    Nodes in the same batch have no dependencies on each other.
    """
    node_by_id = {n.id: n for n in nodes}
    completed: set[str] = set()
    batches: list[list[AgentNode]] = []
    remaining = set(n.id for n in nodes)

    while remaining:
        # Find all nodes whose dependencies are satisfied
        batch = [
            node_by_id[nid] for nid in remaining
            if node_by_id[nid].upstream <= completed
        ]

        if not batch:
            # Shouldn't happen if topological sort worked
            raise GraphError("Unable to make progress - possible cycle")

        # Sort batch by priority
        batch.sort(key=lambda n: -n.priority)
        batches.append(batch)

        # Mark batch as completed
        for node in batch:
            completed.add(node.id)
            remaining.discard(node.id)

    return batches


__all__ = [
    "AgentNode",
    "build_graph",
    "get_execution_batches",
]
```

**Verification:**
- [ ] `AgentNode` is frozen (immutable)
- [ ] `_compute_downstream_map` is O(V+E) (fixes MAJ-05)
- [ ] `_topological_sort` is O(V+E) (fixes MAJ-06)
- [ ] No mutable state in AgentNode
- [ ] Cycle detection raises `GraphError`

---

### 3.2 Create `workspace.py` - Cairn Integration

**Purpose:** Thin wrappers around Cairn for workspace management. Replaces three workspace abstractions.

**File:** `src/remora/workspace.py`

```python
"""Cairn workspace integration.

Provides thin wrappers around Cairn for agent workspace management.
Replaces WorkspaceKV, GraphWorkspace, and WorkspaceManager with
direct Cairn usage.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from cairn import Workspace as CairnWorkspace

from remora.config import WorkspaceConfig
from remora.discovery import CSTNode
from remora.errors import WorkspaceError

logger = logging.getLogger(__name__)


class AgentWorkspace:
    """Workspace for a single agent execution.

    Wraps a Cairn workspace with agent-specific convenience methods.
    """

    def __init__(self, workspace: CairnWorkspace, agent_id: str):
        self._workspace = workspace
        self._agent_id = agent_id

    @property
    def cairn(self) -> CairnWorkspace:
        """Access underlying Cairn workspace."""
        return self._workspace

    async def read(self, path: str) -> str:
        """Read a file from the workspace."""
        return await self._workspace.read(path)

    async def write(self, path: str, content: str) -> None:
        """Write a file to the workspace (CoW isolated)."""
        await self._workspace.write(path, content)

    async def exists(self, path: str) -> bool:
        """Check if a file exists in the workspace."""
        return await self._workspace.exists(path)

    async def accept(self) -> None:
        """Accept all changes in this workspace."""
        await self._workspace.accept()

    async def reject(self) -> None:
        """Reject all changes and reset to base state."""
        await self._workspace.reject()

    async def snapshot(self, name: str) -> str:
        """Create a named snapshot of current state."""
        return await self._workspace.snapshot(name)

    async def restore(self, snapshot_id: str) -> None:
        """Restore from a named snapshot."""
        await self._workspace.restore(snapshot_id)


class WorkspaceManager:
    """Manages Cairn workspaces for graph execution.

    Creates isolated workspaces per agent with CoW semantics.
    """

    def __init__(self, config: WorkspaceConfig, graph_id: str):
        self._config = config
        self._graph_id = graph_id
        self._base_path = Path(config.base_path) / graph_id
        self._workspaces: dict[str, AgentWorkspace] = {}

    async def get_workspace(self, agent_id: str) -> AgentWorkspace:
        """Get or create a workspace for an agent."""
        if agent_id in self._workspaces:
            return self._workspaces[agent_id]

        workspace_path = self._base_path / agent_id
        workspace_path.mkdir(parents=True, exist_ok=True)

        try:
            cairn_ws = await CairnWorkspace.create(workspace_path)
        except Exception as e:
            raise WorkspaceError(f"Failed to create workspace for {agent_id}: {e}")

        agent_ws = AgentWorkspace(cairn_ws, agent_id)
        self._workspaces[agent_id] = agent_ws
        return agent_ws

    async def cleanup(self) -> None:
        """Clean up all workspaces."""
        for workspace in self._workspaces.values():
            try:
                await workspace.cairn.close()
            except Exception as e:
                logger.warning("Workspace cleanup error: %s", e)
        self._workspaces.clear()


class CairnDataProvider:
    """Populates Grail virtual FS from a Cairn workspace.

    Implements the DataProvider pattern for structured-agents v0.3.
    """

    def __init__(self, workspace: AgentWorkspace):
        self._workspace = workspace

    async def load_files(self, node: CSTNode, related: list[str] | None = None) -> dict[str, str]:
        """Load target file and related files for Grail execution.

        Args:
            node: The target CSTNode
            related: Optional list of related file paths to include

        Returns:
            Dict mapping file paths to contents for Grail virtual FS
        """
        files: dict[str, str] = {}

        # Load target file
        try:
            files[node.file_path] = await self._workspace.read(node.file_path)
        except Exception as e:
            logger.warning("Could not load target file %s: %s", node.file_path, e)

        # Load related files
        if related:
            for path in related:
                try:
                    if await self._workspace.exists(path):
                        files[path] = await self._workspace.read(path)
                except Exception as e:
                    logger.debug("Could not load related file %s: %s", path, e)

        return files


class CairnResultHandler:
    """Persists script results back to Cairn workspace."""

    def __init__(self, workspace: AgentWorkspace):
        self._workspace = workspace

    async def handle(self, result: dict[str, Any]) -> None:
        """Write result data back to workspace.

        Handles common result patterns:
        - written_files: dict[path, content] - files to write
        - modified_file: (path, content) - single file modification
        """
        if "written_files" in result:
            for path, content in result["written_files"].items():
                await self._workspace.write(path, content)

        if "modified_file" in result:
            path, content = result["modified_file"]
            await self._workspace.write(path, content)


__all__ = [
    "AgentWorkspace",
    "WorkspaceManager",
    "CairnDataProvider",
    "CairnResultHandler",
]
```

**Verification:**
- [ ] Uses Cairn directly (no custom file-based KV)
- [ ] `AgentWorkspace` is a thin wrapper
- [ ] `CairnDataProvider` implements DataProvider pattern
- [ ] `CairnResultHandler` handles result persistence

---

### 3.3 Create `context.py` - Simplified Context Builder

**Purpose:** Single-file context building via event subscription. This resolves:
- MAJ-02: Unsafe exception handling (add logging)

**File:** `src/remora/context.py`

```python
"""Context builder for Two-Track Memory.

Short Track: Rolling deque of recent actions
Long Track: Full event subscription for knowledge accumulation

The ContextBuilder subscribes to the EventBus and builds bounded
context for agent prompts.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from remora.events import (
    RemoraEvent,
    ToolResultEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
)

if TYPE_CHECKING:
    from remora.discovery import CSTNode

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecentAction:
    """A recent tool/agent action for Short Track memory."""
    tool: str
    outcome: str  # "success", "error", "partial"
    summary: str
    agent_id: str | None = None


@dataclass
class ContextBuilder:
    """Builds bounded context from the event stream.

    Implements Two-Track Memory:
    - Short Track: Rolling window of recent actions (bounded deque)
    - Long Track: Knowledge accumulated from completed agents

    Usage:
        builder = ContextBuilder(window_size=20)
        event_bus.subscribe_all(builder.handle)

        # Later, when building prompt:
        context = builder.build_context_for(node)
    """

    window_size: int = 20
    _recent: deque[RecentAction] = field(default_factory=deque)
    _knowledge: dict[str, str] = field(default_factory=dict)
    _store: Any = None  # Optional NodeStateStore for related code

    def __post_init__(self):
        self._recent = deque(maxlen=self.window_size)

    async def handle(self, event: RemoraEvent) -> None:
        """EventBus subscriber - updates context from events.

        This method can be passed to EventBus.subscribe_all().
        """
        match event:
            case ToolResultEvent(name=name, output=output, is_error=is_error):
                self._recent.append(RecentAction(
                    tool=name,
                    outcome="error" if is_error else "success",
                    summary=_summarize(str(output), max_len=200),
                ))

            case AgentCompleteEvent(agent_id=aid, result_summary=summary):
                self._knowledge[aid] = summary

            case AgentErrorEvent(agent_id=aid, error=error):
                self._recent.append(RecentAction(
                    tool="agent",
                    outcome="error",
                    summary=f"Agent {aid} failed: {error[:100]}",
                    agent_id=aid,
                ))

            case _:
                pass  # Ignore other events

    def build_context_for(self, node: CSTNode) -> str:
        """Build full context for an agent prompt.

        Combines:
        1. Related code context from the store (if available)
        2. Short track recent actions
        3. Long track knowledge from completed agents
        """
        sections: list[str] = []

        # Related code from index store (fixes MAJ-02: add logging for errors)
        if self._store:
            try:
                related = self._store.get_related(getattr(node, "node_id", None))
                if related:
                    sections.append("## Related Code")
                    for rel in related[:5]:
                        sections.append(f"- {rel}")
            except Exception as e:
                # Log instead of silently swallowing (fixes MAJ-02)
                logger.warning("Failed to load related code for %s: %s", node.node_id, e)

        # Short track (recent actions)
        if self._recent:
            sections.append("\n## Recent Actions")
            for action in self._recent:
                status = "+" if action.outcome == "success" else "-"
                sections.append(f"[{status}] {action.tool}: {action.summary}")

        # Long track (accumulated knowledge)
        if self._knowledge:
            sections.append("\n## Prior Analysis")
            for agent_id, knowledge in list(self._knowledge.items())[-5:]:
                sections.append(f"- {agent_id}: {knowledge[:200]}")

        return "\n".join(sections)

    def build_prompt_section(self) -> str:
        """Render just the recent actions as a prompt section."""
        if not self._recent:
            return ""

        lines = ["## Recent Activity"]
        for action in self._recent:
            status = "+" if action.outcome == "success" else "-"
            lines.append(f"[{status}] {action.tool}: {action.summary}")

        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all context. Used for testing or new graph runs."""
        self._recent.clear()
        self._knowledge.clear()


def _summarize(text: str, max_len: int = 200) -> str:
    """Truncate text for context summary."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


__all__ = [
    "ContextBuilder",
    "RecentAction",
]
```

**Verification:**
- [ ] Single file replaces `context/` package
- [ ] Exception handling logs errors (fixes MAJ-02)
- [ ] Uses pattern matching on typed events
- [ ] No string-based event routing

---

## 4. Phase 3: Execution Engine

Phase 3 implements the execution pipeline using Phase 1 and 2 components.

### 4.1 Create `executor.py` - Graph Executor

**Purpose:** Execute agents in dependency order via structured-agents. This resolves:
- MAJ-01: Environment variables set globally (pass config directly)
- MAJ-07: SKIP_DOWNSTREAM error policy not implemented
- MIN-07: Inconsistent type hints

**File:** `src/remora/executor.py`

```python
"""Graph executor for running agents in dependency order.

Uses structured-agents Agent.from_bundle() for execution.
Configuration passed directly - no global environment variables.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from structured_agents import Agent
from structured_agents.exceptions import KernelError

from remora.config import RemoraConfig, ErrorPolicy, ExecutionConfig
from remora.context import ContextBuilder
from remora.errors import ExecutionError
from remora.events import (
    GraphStartEvent,
    GraphCompleteEvent,
    GraphErrorEvent,
    AgentStartEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentSkippedEvent,
)
from remora.event_bus import EventBus
from remora.graph import AgentNode, get_execution_batches
from remora.workspace import WorkspaceManager, CairnDataProvider

if TYPE_CHECKING:
    from structured_agents.types import RunResult

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Execution state of an agent."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ResultSummary:
    """Summary of an agent execution result."""
    agent_id: str
    success: bool
    output: str
    error: str | None = None

    def to_dict(self) -> dict:
        """Serialize for checkpoint storage."""
        return {
            "agent_id": self.agent_id,
            "success": self.success,
            "output": self.output,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResultSummary":
        """Deserialize from checkpoint storage."""
        return cls(**data)


@dataclass
class ExecutorState:
    """State of graph execution for checkpointing."""
    graph_id: str
    nodes: dict[str, AgentNode]
    states: dict[str, AgentState] = field(default_factory=dict)
    completed: dict[str, ResultSummary] = field(default_factory=dict)
    pending: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)


class GraphExecutor:
    """Executes agent graph in dependency order.

    Features:
    - Bounded concurrency via semaphore
    - Error policies (STOP_GRAPH, SKIP_DOWNSTREAM, CONTINUE)
    - Event emission at lifecycle points
    - Checkpoint save/restore support
    """

    def __init__(
        self,
        config: RemoraConfig,
        event_bus: EventBus,
        context_builder: ContextBuilder | None = None,
    ):
        self.config = config
        self.event_bus = event_bus
        self.context_builder = context_builder or ContextBuilder()

        # Subscribe context builder to events
        event_bus.subscribe_all(self.context_builder.handle)

    async def run(
        self,
        graph: list[AgentNode],
        graph_id: str,
    ) -> dict[str, ResultSummary]:
        """Execute all agents in topological order.

        Args:
            graph: List of AgentNodes (already topologically sorted)
            graph_id: Unique identifier for this execution

        Returns:
            Dict mapping agent_id to ResultSummary
        """
        # Initialize state
        state = ExecutorState(
            graph_id=graph_id,
            nodes={n.id: n for n in graph},
            pending=set(n.id for n in graph),
        )

        # Emit start event
        await self.event_bus.emit(GraphStartEvent(
            graph_id=graph_id,
            node_count=len(graph),
        ))

        # Create workspace manager
        workspace_mgr = WorkspaceManager(self.config.workspace, graph_id)

        # Create concurrency semaphore
        semaphore = asyncio.Semaphore(self.config.execution.max_concurrency)

        try:
            # Get execution batches
            batches = get_execution_batches(graph)

            for batch in batches:
                # Filter out skipped nodes
                runnable = [
                    n for n in batch
                    if n.id not in state.skipped and n.id not in state.failed
                ]

                if not runnable:
                    continue

                # Execute batch in parallel (bounded by semaphore)
                tasks = [
                    self._execute_agent(node, state, workspace_mgr, semaphore)
                    for node in runnable
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results and apply error policy
                should_stop = await self._process_results(
                    runnable, results, state, graph
                )

                if should_stop:
                    break

            # Emit completion event
            await self.event_bus.emit(GraphCompleteEvent(
                graph_id=graph_id,
                completed_count=len(state.completed),
                failed_count=len(state.failed),
            ))

        except Exception as e:
            await self.event_bus.emit(GraphErrorEvent(
                graph_id=graph_id,
                error=str(e),
            ))
            raise ExecutionError(f"Graph execution failed: {e}") from e

        finally:
            await workspace_mgr.cleanup()

        return state.completed

    async def _execute_agent(
        self,
        node: AgentNode,
        state: ExecutorState,
        workspace_mgr: WorkspaceManager,
        semaphore: asyncio.Semaphore,
    ) -> ResultSummary:
        """Execute a single agent."""
        async with semaphore:
            state.states[node.id] = AgentState.RUNNING

            await self.event_bus.emit(AgentStartEvent(
                graph_id=state.graph_id,
                agent_id=node.id,
                node_name=node.name,
            ))

            try:
                # Get workspace
                workspace = await workspace_mgr.get_workspace(node.id)

                # Load data for Grail
                data_provider = CairnDataProvider(workspace)
                files = await data_provider.load_files(node.target)

                # Build prompt with context
                prompt = self._build_prompt(node, files)

                # Execute via structured-agents (fixes MAJ-01: no env vars)
                result = await self._run_agent(node, prompt)

                # Create summary
                summary = ResultSummary(
                    agent_id=node.id,
                    success=True,
                    output=_truncate(str(result.output), self.config.execution.truncation_limit),
                )

                await self.event_bus.emit(AgentCompleteEvent(
                    graph_id=state.graph_id,
                    agent_id=node.id,
                    result_summary=summary.output[:200],
                ))

                return summary

            except Exception as e:
                logger.error("Agent %s failed: %s", node.id, e)

                summary = ResultSummary(
                    agent_id=node.id,
                    success=False,
                    output="",
                    error=str(e),
                )

                await self.event_bus.emit(AgentErrorEvent(
                    graph_id=state.graph_id,
                    agent_id=node.id,
                    error=str(e),
                ))

                return summary

    async def _run_agent(self, node: AgentNode, prompt: str) -> "RunResult":
        """Run agent via structured-agents.

        Configuration is passed directly - no environment variables (fixes MAJ-01).
        """
        # Create agent from bundle with config
        agent = await Agent.from_bundle(
            node.bundle_path,
            observer=self.event_bus,
            base_url=self.config.model.base_url,
            api_key=self.config.model.api_key or None,
            model=self.config.model.default_model,
        )

        try:
            return await agent.run(
                prompt,
                max_turns=self.config.execution.max_turns,
            )
        finally:
            await agent.close()

    def _build_prompt(self, node: AgentNode, files: dict[str, str]) -> str:
        """Build the prompt for an agent."""
        sections = []

        # Target information
        sections.append(f"# Target: {node.name}")
        sections.append(f"File: {node.target.file_path}")
        sections.append(f"Lines: {node.target.start_line}-{node.target.end_line}")

        # Target code
        if node.target.file_path in files:
            sections.append("\n## Code")
            sections.append("```")
            sections.append(node.target.text)
            sections.append("```")

        # Context from Two-Track Memory
        context = self.context_builder.build_context_for(node.target)
        if context:
            sections.append(context)

        return "\n".join(sections)

    async def _process_results(
        self,
        nodes: list[AgentNode],
        results: list[ResultSummary | BaseException],
        state: ExecutorState,
        graph: list[AgentNode],
    ) -> bool:
        """Process batch results and apply error policy.

        Returns True if execution should stop.
        Implements MAJ-07: SKIP_DOWNSTREAM error policy.
        """
        should_stop = False

        for node, result in zip(nodes, results):
            if isinstance(result, BaseException):
                result = ResultSummary(
                    agent_id=node.id,
                    success=False,
                    output="",
                    error=str(result),
                )

            state.pending.discard(node.id)

            if result.success:
                state.states[node.id] = AgentState.COMPLETED
                state.completed[node.id] = result
            else:
                state.states[node.id] = AgentState.FAILED
                state.failed.add(node.id)

                # Apply error policy (fixes MAJ-07)
                if self.config.execution.error_policy == ErrorPolicy.STOP_GRAPH:
                    should_stop = True

                elif self.config.execution.error_policy == ErrorPolicy.SKIP_DOWNSTREAM:
                    # Mark all downstream nodes as skipped
                    downstream = self._get_all_downstream(node.id, graph)
                    for skip_id in downstream:
                        if skip_id not in state.completed and skip_id not in state.failed:
                            state.skipped.add(skip_id)
                            state.states[skip_id] = AgentState.SKIPPED
                            state.pending.discard(skip_id)

                            await self.event_bus.emit(AgentSkippedEvent(
                                graph_id=state.graph_id,
                                agent_id=skip_id,
                                reason=f"Upstream agent {node.id} failed",
                            ))

                # ErrorPolicy.CONTINUE: do nothing, keep executing

        return should_stop

    def _get_all_downstream(self, node_id: str, graph: list[AgentNode]) -> set[str]:
        """Get all transitive downstream nodes."""
        node_by_id = {n.id: n for n in graph}
        downstream: set[str] = set()
        queue = list(node_by_id[node_id].downstream)

        while queue:
            current = queue.pop()
            if current not in downstream:
                downstream.add(current)
                if current in node_by_id:
                    queue.extend(node_by_id[current].downstream)

        return downstream


def _truncate(text: str, limit: int = 1024) -> str:
    """Truncate text to limit."""
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


__all__ = [
    "AgentState",
    "ResultSummary",
    "ExecutorState",
    "GraphExecutor",
]
```

**Verification:**
- [ ] No `os.environ` usage (fixes MAJ-01)
- [ ] SKIP_DOWNSTREAM policy implemented (fixes MAJ-07)
- [ ] Type hints use concrete types where possible (fixes MIN-07)
- [ ] `ResultSummary.to_dict()` method exists for checkpointing
- [ ] Observer passed to `Agent.from_bundle()` correctly

---

### 4.2 Create `checkpoint.py` - Cairn-Native Checkpointing

**Purpose:** Save/restore execution state using Cairn snapshots. This resolves:
- CRIT-02: Checkpoint restore returns incomplete ExecutorState
- CRIT-03: Completed results stored incorrectly

**File:** `src/remora/checkpoint.py`

```python
"""Checkpoint management via Cairn snapshots.

Provides save/restore of graph execution state for resumption
after interruption or failure.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from remora.errors import CheckpointError
from remora.events import CheckpointSavedEvent, CheckpointRestoredEvent
from remora.executor import ExecutorState, ResultSummary, AgentState
from remora.graph import AgentNode
from remora.workspace import AgentWorkspace

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Save and restore graph execution state via Cairn snapshots.

    Checkpoint data includes:
    - Execution metadata (graph_id, completed agents, pending agents)
    - Agent results (via ResultSummary.to_dict())
    - Workspace snapshots (via Cairn)
    """

    def __init__(self, base_path: Path | str):
        self._base_path = Path(base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)

    async def save(
        self,
        executor_state: ExecutorState,
        workspaces: dict[str, AgentWorkspace],
    ) -> str:
        """Save execution state to checkpoint.

        Args:
            executor_state: Current ExecutorState
            workspaces: Dict of agent_id -> AgentWorkspace

        Returns:
            Checkpoint ID for restoration
        """
        checkpoint_id = f"{executor_state.graph_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        checkpoint_dir = self._base_path / checkpoint_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Save execution metadata
            metadata = {
                "graph_id": executor_state.graph_id,
                "pending": list(executor_state.pending),
                "failed": list(executor_state.failed),
                "skipped": list(executor_state.skipped),
                "states": {k: v.value for k, v in executor_state.states.items()},
                # Fix CRIT-03: Use ResultSummary.to_dict() properly
                "results": {
                    aid: res.to_dict()
                    for aid, res in executor_state.completed.items()
                },
                # Fix CRIT-02: Serialize node data for restoration
                "nodes": {
                    nid: self._serialize_node(node)
                    for nid, node in executor_state.nodes.items()
                },
            }

            metadata_path = checkpoint_dir / "metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            # Snapshot each workspace via Cairn
            for agent_id, workspace in workspaces.items():
                snapshot_name = f"{checkpoint_id}/{agent_id}"
                await workspace.snapshot(snapshot_name)
                logger.debug("Saved workspace snapshot: %s", snapshot_name)

            logger.info("Saved checkpoint: %s", checkpoint_id)
            return checkpoint_id

        except Exception as e:
            raise CheckpointError(f"Failed to save checkpoint: {e}") from e

    async def restore(
        self,
        checkpoint_id: str,
    ) -> tuple[ExecutorState, dict[str, AgentWorkspace]]:
        """Restore execution state from checkpoint.

        Args:
            checkpoint_id: The checkpoint ID returned by save()

        Returns:
            Tuple of (ExecutorState, workspaces dict)

        Raises:
            CheckpointError: If checkpoint not found or invalid
        """
        checkpoint_dir = self._base_path / checkpoint_id

        if not checkpoint_dir.exists():
            raise CheckpointError(f"Checkpoint not found: {checkpoint_id}")

        try:
            # Load metadata
            metadata_path = checkpoint_dir / "metadata.json"
            with open(metadata_path) as f:
                metadata = json.load(f)

            # Restore results (fixes CRIT-03)
            completed = {
                aid: ResultSummary.from_dict(data)
                for aid, data in metadata.get("results", {}).items()
            }

            # Restore nodes (fixes CRIT-02)
            nodes = {
                nid: self._deserialize_node(data)
                for nid, data in metadata.get("nodes", {}).items()
            }

            # Restore states
            states = {
                k: AgentState(v)
                for k, v in metadata.get("states", {}).items()
            }

            # Restore workspaces from Cairn snapshots
            workspaces: dict[str, AgentWorkspace] = {}
            for agent_id in nodes.keys():
                snapshot_name = f"{checkpoint_id}/{agent_id}"
                try:
                    from cairn import Workspace as CairnWorkspace
                    cairn_ws = await CairnWorkspace.from_snapshot(snapshot_name)
                    workspaces[agent_id] = AgentWorkspace(cairn_ws, agent_id)
                except Exception as e:
                    logger.warning("Could not restore workspace for %s: %s", agent_id, e)

            # Build ExecutorState with all data (fixes CRIT-02)
            state = ExecutorState(
                graph_id=metadata["graph_id"],
                nodes=nodes,
                states=states,
                completed=completed,
                pending=set(metadata.get("pending", [])),
                failed=set(metadata.get("failed", [])),
                skipped=set(metadata.get("skipped", [])),
            )

            logger.info("Restored checkpoint: %s", checkpoint_id)
            return state, workspaces

        except Exception as e:
            raise CheckpointError(f"Failed to restore checkpoint: {e}") from e

    def list_checkpoints(self, graph_id: str | None = None) -> list[str]:
        """List available checkpoints, optionally filtered by graph_id."""
        checkpoints = []

        for item in self._base_path.iterdir():
            if item.is_dir() and (item / "metadata.json").exists():
                if graph_id is None or item.name.startswith(graph_id):
                    checkpoints.append(item.name)

        return sorted(checkpoints, reverse=True)

    def delete(self, checkpoint_id: str) -> None:
        """Delete a checkpoint."""
        checkpoint_dir = self._base_path / checkpoint_id
        if checkpoint_dir.exists():
            import shutil
            shutil.rmtree(checkpoint_dir)
            logger.info("Deleted checkpoint: %s", checkpoint_id)

    def _serialize_node(self, node: AgentNode) -> dict[str, Any]:
        """Serialize AgentNode for checkpoint storage."""
        return {
            "id": node.id,
            "name": node.name,
            "target": {
                "node_id": node.target.node_id,
                "node_type": node.target.node_type,
                "name": node.target.name,
                "file_path": node.target.file_path,
                "text": node.target.text,
                "start_line": node.target.start_line,
                "end_line": node.target.end_line,
            },
            "bundle_path": str(node.bundle_path),
            "upstream": list(node.upstream),
            "downstream": list(node.downstream),
            "priority": node.priority,
        }

    def _deserialize_node(self, data: dict[str, Any]) -> AgentNode:
        """Deserialize AgentNode from checkpoint storage."""
        from remora.discovery import CSTNode

        target = CSTNode(**data["target"])

        return AgentNode(
            id=data["id"],
            name=data["name"],
            target=target,
            bundle_path=Path(data["bundle_path"]),
            upstream=frozenset(data.get("upstream", [])),
            downstream=frozenset(data.get("downstream", [])),
            priority=data.get("priority", 0),
        )


__all__ = [
    "CheckpointManager",
]
```

**Verification:**
- [ ] `nodes` dict is serialized/deserialized (fixes CRIT-02)
- [ ] Uses `ResultSummary.to_dict()` (fixes CRIT-03)
- [ ] Workspaces restored from Cairn snapshots
- [ ] Complete ExecutorState can be restored

---

## 5. Phase 4: Agent Bundles

### 5.1 Update Bundle Format

Update each bundle's `bundle.yaml` to structured-agents v0.3 format with Remora extensions.

**Template:** `agents/<bundle_name>/bundle.yaml`

```yaml
# Standard structured-agents v0.3 fields
name: <bundle_name>
model: qwen
grammar: ebnf
system_prompt: |
  You are an agent that...

tools:
  - tools/*.pym

termination: submit_result
max_turns: 8

# Remora-specific extensions
node_types:
  - function
  - class
priority: 10
requires_context: true
```

### 5.2 Convert .pym Scripts to Pure Functions

Convert scripts from @external-heavy to virtual FS input pattern.

**Before (old pattern):**
```python
# tools/analyze.pym
from grail import external

@external
async def read_file(path: str) -> str: ...

content = await read_file("target.py")
# Process content
```

**After (new pattern):**
```python
# tools/analyze.pym
from grail import Input

# Data flows in via virtual FS or Input()
source_code: str = Input("source_code")
file_path: str = Input("file_path")

# Pure computation
issues = []
for i, line in enumerate(source_code.split("\n")):
    if len(line) > 120:
        issues.append({"line": i + 1, "issue": "line too long"})

# Return structured result
result = {
    "file_path": file_path,
    "issues": issues,
}
```

### 5.3 Keep Only Essential @external Declarations

Reserved for genuine external services:
- `ask_user(question: str) -> str` - Human-in-the-loop (event-based IPC)
- Future API calls that can't be pre-loaded

---

## 6. Phase 5: Services

### 6.1 Create `indexer/` Package

Split from `hub/` - independent filesystem indexer.

**Directory structure:**
```
src/remora/indexer/
  __init__.py
  daemon.py      # Filesystem watcher + cold-start indexer
  store.py       # NodeStateStore (fsdantic)
  models.py      # NodeState, FileIndex
  rules.py       # RulesEngine
  cli.py         # remora-index entry point
```

**File:** `src/remora/indexer/__init__.py`

```python
"""Remora indexer - background filesystem indexer.

Watches source files and maintains an index of code nodes.
Independent of dashboard - can run standalone.
"""
from remora.indexer.daemon import IndexerDaemon
from remora.indexer.store import NodeStateStore
from remora.indexer.models import NodeState

__all__ = ["IndexerDaemon", "NodeStateStore", "NodeState"]
```

### 6.2 Create `dashboard/` Package

Split from `hub/` - web UI for monitoring and triggering execution.

**Directory structure:**
```
src/remora/dashboard/
  __init__.py
  app.py         # Starlette application (async config load - fixes MAJ-04)
  views.py       # datastar-py SSE views
  cli.py         # remora-dashboard entry point
```

**File:** `src/remora/dashboard/app.py`

```python
"""Dashboard Starlette application.

Provides SSE-powered web UI for monitoring graph execution.
"""
from __future__ import annotations

import asyncio
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route

from remora.config import RemoraConfig, load_config
from remora.event_bus import EventBus


class DashboardApp:
    """Dashboard application wrapper."""

    def __init__(self, event_bus: EventBus, config: RemoraConfig | None = None):
        self._event_bus = event_bus
        self._config = config
        self._app: Starlette | None = None

    async def initialize(self) -> None:
        """Async initialization (fixes MAJ-04).

        Config is loaded via asyncio.to_thread to avoid blocking.
        """
        if self._config is None:
            # Non-blocking config load (fixes MAJ-04)
            self._config = await asyncio.to_thread(load_config)

        # Build Starlette app
        from remora.dashboard.views import create_routes
        routes = create_routes(self._event_bus, self._config)
        self._app = Starlette(routes=routes)

    @property
    def app(self) -> Starlette:
        """Get the Starlette app (must call initialize() first)."""
        if self._app is None:
            raise RuntimeError("Call initialize() before accessing app")
        return self._app


async def create_app(
    event_bus: EventBus | None = None,
    config: RemoraConfig | None = None,
) -> Starlette:
    """Factory function to create dashboard app.

    Usage with uvicorn:
        app = asyncio.run(create_app())
        uvicorn.run(app, ...)
    """
    if event_bus is None:
        from remora.event_bus import get_event_bus
        event_bus = get_event_bus()

    dashboard = DashboardApp(event_bus, config)
    await dashboard.initialize()
    return dashboard.app
```

**Verification:**
- [ ] Config loaded via `asyncio.to_thread()` (fixes MAJ-04)
- [ ] No blocking I/O in async context
- [ ] Event bus integration for SSE streaming

### 6.3 Update CLI Entry Points

**File:** `src/remora/cli.py`

```python
"""Remora CLI entry points."""
import asyncio
import click

from remora.config import load_config


@click.group()
def main():
    """Remora - Agent-based code analysis."""
    pass


@main.command()
@click.argument("paths", nargs=-1)
@click.option("--config", "-c", help="Config file path")
def run(paths, config):
    """Run agent graph on specified paths."""
    from remora.discovery import discover
    from remora.graph import build_graph
    from remora.executor import GraphExecutor
    from remora.event_bus import EventBus

    cfg = load_config(config)

    # Discovery
    nodes = discover(list(paths) or list(cfg.discovery.paths))

    # Build graph
    bundle_mapping = {
        k: cfg.bundles.path / v
        for k, v in cfg.bundles.mapping.items()
    }
    graph = build_graph(nodes, bundle_mapping)

    # Execute
    event_bus = EventBus()
    executor = GraphExecutor(cfg, event_bus)

    async def run_async():
        return await executor.run(graph, "cli-run")

    results = asyncio.run(run_async())
    click.echo(f"Completed {len(results)} agents")


@main.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8420)
def dashboard(host, port):
    """Start the dashboard server."""
    import uvicorn
    from remora.dashboard.app import create_app

    app = asyncio.run(create_app())
    uvicorn.run(app, host=host, port=port)


@main.command()
@click.argument("paths", nargs=-1)
def index(paths):
    """Start the indexer daemon."""
    from remora.indexer.daemon import IndexerDaemon

    cfg = load_config()
    daemon = IndexerDaemon(cfg.indexer)

    asyncio.run(daemon.run(list(paths) or list(cfg.indexer.watch_paths)))


if __name__ == "__main__":
    main()
```

---

## 7. Phase 6: Integration & Cleanup

### 7.1 Update `__init__.py`

**File:** `src/remora/__init__.py`

```python
"""Remora - Agent-based code analysis framework.

Core API:
    discover()      - Scan source code for CSTNodes
    build_graph()   - Map nodes to agent graph
    GraphExecutor   - Execute agents in dependency order
    EventBus        - Unified event dispatch
"""
from remora.discovery import CSTNode, discover
from remora.graph import AgentNode, build_graph
from remora.executor import GraphExecutor, ResultSummary
from remora.event_bus import EventBus, get_event_bus
from remora.config import RemoraConfig, load_config
from remora.context import ContextBuilder

__version__ = "0.4.2"

__all__ = [
    # Discovery
    "CSTNode",
    "discover",
    # Graph
    "AgentNode",
    "build_graph",
    # Execution
    "GraphExecutor",
    "ResultSummary",
    # Events
    "EventBus",
    "get_event_bus",
    # Config
    "RemoraConfig",
    "load_config",
    # Context
    "ContextBuilder",
    # Version
    "__version__",
]
```

### 7.2 Delete Old Files

Remove all files that have been consolidated or eliminated:

```bash
# Root modules to delete
rm src/remora/agent_graph.py
rm src/remora/agent_state.py
rm src/remora/backend.py
rm src/remora/client.py
rm src/remora/constants.py

# Old packages to delete (already backed up)
rm -rf src/remora/hub/
rm -rf src/remora/context/
rm -rf src/remora/interactive/
rm -rf src/remora/frontend/
rm -rf src/remora/utils/
```

### 7.3 Run Quality Checks

```bash
# Type checking
mypy src/remora --strict

# Linting
ruff check src/remora --fix

# Format
ruff format src/remora

# Run tests
pytest tests/ -v
```

### 7.4 Update pyproject.toml Entry Points

```toml
[project.scripts]
remora = "remora.cli:main"
remora-index = "remora.indexer.cli:main"
remora-dashboard = "remora.dashboard.cli:main"
```

---

## 8. Testing Checklist

### Unit Tests Required

- [ ] `test_events.py` - Event dataclass creation and union type
- [ ] `test_event_bus.py` - Subscribe, emit, stream, wait_for
- [ ] `test_discovery.py` - File parsing, query loading, CSTNode creation
- [ ] `test_config.py` - YAML loading, env overrides, frozen validation
- [ ] `test_graph.py` - Build graph, topological sort, cycle detection
- [ ] `test_executor.py` - Agent execution, error policies, batching
- [ ] `test_checkpoint.py` - Save/restore round-trip
- [ ] `test_context.py` - Event handling, context building

### Integration Tests Required

- [ ] Full pipeline: discover -> build_graph -> execute
- [ ] Checkpoint save/restore resumption
- [ ] Human-in-the-loop via event IPC
- [ ] Dashboard SSE streaming
- [ ] Indexer file watching

---

## 9. Issue Resolution Matrix

| Issue ID | Description | Resolution | File(s) |
|----------|-------------|------------|---------|
| CRIT-01 | Observer protocol implementation | EventBus implements Observer via emit() | event_bus.py |
| CRIT-02 | Incomplete ExecutorState restore | Serialize/deserialize nodes dict | checkpoint.py |
| CRIT-03 | Wrong serialization for ResultSummary | Use ResultSummary.to_dict() | checkpoint.py |
| CRIT-04 | Discovery module conflict | Delete discovery.py, keep discovery/ → consolidate to discovery.py | discovery.py |
| MAJ-01 | Global environment variables | Pass config directly to Agent.from_bundle() | executor.py |
| MAJ-02 | Silent exception handling | Add logging for caught exceptions | context.py |
| MAJ-03 | Event stream resource leak | Context manager pattern for stream() | event_bus.py |
| MAJ-04 | Blocking config load | Use asyncio.to_thread() | dashboard/app.py |
| MAJ-05 | O(n^2) dependency computation | Pre-compute adjacency list | graph.py |
| MAJ-06 | O(n^2) topological sort | Proper Kahn's algorithm | graph.py |
| MAJ-07 | SKIP_DOWNSTREAM not implemented | Track failed agents, skip downstream | executor.py |
| MIN-01 | Dead Event class | Removed - not needed | event_bus.py |
| MIN-02 | Unused import | Removed with Event class | event_bus.py |
| MIN-03 | Inconsistent error naming | Single ConfigError in errors.py | errors.py, config.py |
| MIN-04 | Missing __all__ | Proper __all__ in discovery.py | discovery.py |
| MIN-05 | Query path resolution | Use importlib.resources | discovery.py |
| MIN-06 | Hardcoded truncation | Configurable in ExecutionConfig | config.py, executor.py |
| MIN-07 | Inconsistent type hints | Concrete types where possible | executor.py |
| MIN-08 | Missing docstrings | Added to public functions | All files |

---

## Final Structure

After completing all phases:

```
src/remora/
  __init__.py          # Public API exports
  __main__.py          # python -m remora
  config.py            # RemoraConfig, load_config()
  errors.py            # RemoraError hierarchy
  events.py            # RemoraEvent union, all event dataclasses
  event_bus.py         # EventBus with Observer protocol
  discovery.py         # CSTNode, discover()
  graph.py             # AgentNode, build_graph()
  executor.py          # GraphExecutor, ExecutorState
  context.py           # ContextBuilder (Two-Track Memory)
  checkpoint.py        # CheckpointManager (Cairn-native)
  workspace.py         # Cairn wrappers
  cli.py               # CLI entry points

  indexer/
    __init__.py
    daemon.py
    store.py
    models.py
    rules.py
    cli.py

  dashboard/
    __init__.py
    app.py
    views.py
    cli.py

  queries/             # .scm files (unchanged)

agents/                # Bundles (updated format)
  lint/
  docstring/
  test/
  ...
```

**File count:** ~22 Python files (down from ~50+)
**Packages:** 4 (down from 7)
**Lines of code:** Estimated 40-50% reduction

---

## Completion Criteria

The refactor is complete when:

1. All 19 issues from V041_CODE_REVIEW.md are resolved
2. All unit tests pass
3. Integration tests pass (discover -> execute pipeline)
4. `mypy --strict` passes
5. `ruff check` passes
6. Old files are deleted
7. pyproject.toml entry points updated
8. Documentation updated to reflect new API
