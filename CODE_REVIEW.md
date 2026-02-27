# Remora V2 Code Review

**Review Date:** 2026-02-27
**Reviewer:** Claude (Opus 4.5)
**Version:** 0.4.3
**Scope:** Complete codebase analysis following refactor

---

## Executive Summary

Remora V2 is an event-driven agent graph workflow framework that orchestrates structured-agent workloads on codebases. The system discovers code nodes using tree-sitter, executes specialized agent bundles against each node, and manages changes through isolated Cairn workspaces.

The refactor has achieved a clean, minimal architecture with clear separation of concerns. The codebase demonstrates strong engineering principles including immutable configuration, explicit dependency injection (in most places), and a unified event system. However, there are opportunities to further improve consistency, performance, and extensibility.

**Overall Assessment:** The codebase is well-structured and achieves its goal of being elegant and maintainable. The integration with Grail and structured-agents is clean and well-considered. Some areas need refinement around consistency, performance edge cases, and DI purity.

---

## Table of Contents

1. [Architecture Analysis](#1-architecture-analysis)
2. [Strengths](#2-strengths)
3. [Issues & Recommendations](#3-issues--recommendations)
4. [Component-by-Component Review](#4-component-by-component-review)
5. [Code Quality Metrics](#5-code-quality-metrics)
6. [Testing Assessment](#6-testing-assessment)
7. [Blue Sky Refactor Opportunities](#blue-sky-refactor-opportunities)

---

## 1. Architecture Analysis

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           User Interface                            │
│                    (CLI / HTTP Service / Dashboard)                 │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Service Layer                                │
│              (RemoraService, Handlers, Starlette Adapter)           │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           Event Bus                                  │
│              (Observer Protocol, Type-Based Subscriptions)          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
│    Discovery        │ │    Graph Executor   │ │    Context Builder  │
│    (Tree-sitter)    │ │    (Agent Kernel)   │ │    (Two-Track)      │
└─────────────────────┘ └─────────────────────┘ └─────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Workspace Layer                               │
│         (Cairn Bridge, CairnExternals, AgentWorkspace)             │
└─────────────────────────────────────────────────────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
│   Grail Scripts     │ │  structured-agents  │ │       Cairn         │
│    (.pym tools)     │ │    (AgentKernel)    │ │    (Workspaces)     │
└─────────────────────┘ └─────────────────────┘ └─────────────────────┘
```

### 1.2 Key Design Decisions

| Decision | Rationale | Assessment |
|----------|-----------|------------|
| Frozen dataclasses for config | Immutability prevents runtime mutations | Excellent |
| EventBus as Observer protocol | Unified event handling across layers | Good |
| Tree-sitter for discovery | Multi-language support, accurate parsing | Excellent |
| Cairn for workspaces | CoW isolation, SQLite-backed state | Good |
| Grail for tool execution | Sandboxed execution with type safety | Excellent |
| Topological graph execution | Respects dependencies between nodes | Good |

### 1.3 Module Dependencies

```
remora/
├── core/                    # Framework-agnostic runtime (no HTTP dependencies)
│   ├── config.py           # Depends: yaml, errors
│   ├── discovery.py        # Depends: tree_sitter
│   ├── event_bus.py        # Depends: structured_agents.events
│   ├── events.py           # Depends: structured_agents.events
│   ├── graph.py            # Depends: discovery, errors
│   ├── executor.py         # Depends: ALL core modules, cairn, structured_agents
│   ├── context.py          # Depends: events
│   ├── workspace.py        # Depends: cairn
│   ├── cairn_bridge.py     # Depends: cairn, workspace
│   ├── cairn_externals.py  # Depends: cairn
│   ├── checkpoint.py       # Depends: executor, graph, workspace
│   └── tools/grail.py      # Depends: grail, structured_agents
│
├── service/                 # HTTP service layer
│   ├── api.py              # Depends: core, models, ui
│   ├── handlers.py         # Depends: core, models
│   └── datastar.py         # Depends: datastar_py, ui
│
├── adapters/                # Framework adapters
│   └── starlette.py        # Depends: starlette, service
│
├── ui/                      # UI rendering
│   ├── view.py             # Pure HTML rendering (no external deps)
│   └── projector.py        # Depends: events
│
├── cli/                     # Command-line interface
│   └── main.py             # Depends: click, core, service
│
├── models/                  # API models
│   └── __init__.py         # Depends: core.config
│
└── utils/                   # Utilities
    ├── path_resolver.py    # No external deps
    └── fs.py               # File system helpers
```

---

## 2. Strengths

### 2.1 Excellent API Design

The public API surface is minimal and well-curated (~35 exports in `__init__.py`). Each export serves a clear purpose:

```python
# Clean separation of concerns in exports
from remora import (
    # Graph execution
    GraphExecutor, AgentNode, build_graph, get_execution_batches,

    # Events
    EventBus, RemoraEvent, AgentStartEvent, AgentCompleteEvent,

    # Configuration
    RemoraConfig, load_config, ErrorPolicy,

    # Discovery
    discover, CSTNode, TreeSitterDiscoverer,

    # Workspace
    AgentWorkspace, CairnWorkspaceService,
)
```

### 2.2 Immutable Configuration

The configuration system uses frozen dataclasses with slots, providing:
- Thread safety
- Predictable behavior
- Clear validation at construction time

```python
@dataclass(frozen=True, slots=True)
class RemoraConfig:
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    bundles: BundleConfig = field(default_factory=BundleConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    # ...
```

### 2.3 Unified Event System

The EventBus implements the structured-agents Observer protocol while adding Remora-specific features:

```python
class EventBus:
    async def emit(self, event: StructuredEvent | RemoraEvent) -> None: ...
    def subscribe(self, event_type: type[Any], handler: EventHandler) -> None: ...
    async def stream(self, *event_types) -> AsyncIterator[...]: ...
    async def wait_for(self, event_type, predicate, timeout) -> ...: ...
```

This enables:
- Type-based filtering
- Async streaming for SSE
- Blocking waits with predicates
- Unified handling of kernel and Remora events

### 2.4 Two-Track Context Memory

The `ContextBuilder` implements an elegant sliding window pattern:

```python
@dataclass
class ContextBuilder:
    window_size: int = 20
    _recent: deque[RecentAction]  # Short track: bounded recent actions
    _knowledge: dict[str, str]     # Long track: accumulated knowledge
```

This balances context freshness with historical insight.

### 2.5 Clean Grail Integration

The `RemoraGrailTool` class elegantly bridges Grail scripts with structured-agents:

```python
class RemoraGrailTool:
    def __init__(self, script_path, *, externals, files_provider, limits): ...

    @property
    def schema(self) -> ToolSchema: ...  # Derived from Grail Input() specs

    async def execute(self, arguments, context) -> ToolResult: ...
```

### 2.6 Error Hierarchy

Clean, purposeful error hierarchy without over-engineering:

```python
RemoraError (base)
├── ConfigError       # Configuration issues
├── DiscoveryError    # Tree-sitter parsing issues
├── GraphError        # Cycle detection, topology issues
├── ExecutionError    # Runtime agent failures
├── CheckpointError   # Save/restore failures
└── WorkspaceError    # Cairn workspace issues
```

### 2.7 Framework-Agnostic Service Layer

The `RemoraService` class contains no framework-specific code:

```python
class RemoraService:
    def index_html(self) -> str: ...
    async def subscribe_stream(self) -> AsyncIterator[str]: ...
    async def events_stream(self) -> AsyncIterator[str]: ...
    async def run(self, request: RunRequest) -> RunResponse: ...
```

Adapters (Starlette) map HTTP requests to service methods.

---

## 3. Issues & Recommendations

### 3.1 Critical Issues

#### 3.1.1 Global Singleton Pattern Violates DI Principles

**Location:** `src/remora/core/event_bus.py:121-135`

```python
_event_bus: EventBus | None = None

def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
```

**Problem:** This global singleton pattern:
- Makes testing harder (requires reset between tests)
- Creates hidden dependencies
- Violates the explicit DI pattern used elsewhere

**Recommendation:** Remove the singleton and require explicit EventBus injection:

```python
# Remove get_event_bus() and reset_event_bus()
# Instead, always create and pass EventBus explicitly

# In service/api.py (already doing this correctly):
service = RemoraService(event_bus=EventBus(), config=config)
```

The codebase is already mostly doing explicit injection; complete the transition by removing the global fallback.

---

#### 3.1.2 O(n) List Operations in Critical Path

**Location:** `src/remora/core/graph.py:152`

```python
while queue:
    node = queue.pop(0)  # O(n) operation
```

**Problem:** `list.pop(0)` is O(n) because it requires shifting all remaining elements. For large graphs, this creates O(n²) complexity in the topological sort.

**Recommendation:** Use `collections.deque`:

```python
from collections import deque

queue = deque(sorted(...))
while queue:
    node = queue.popleft()  # O(1) operation
```

---

### 3.2 Moderate Issues

#### 3.2.1 Duplicate `__all__` Exports

**Location:** `src/remora/__init__.py` and `src/remora/core/__init__.py`

Both files export nearly identical symbols. This creates maintenance burden.

**Recommendation:** Make `remora/__init__.py` re-export from `remora/core`:

```python
# remora/__init__.py
from remora.core import *  # Re-export all core symbols
from remora.core import __all__ as _core_all

# Add any remora-specific exports
from remora.utils import PathResolver

__all__ = _core_all + ["PathResolver"]
```

---

#### 3.2.2 Inconsistent Path Type Handling

**Various locations**

Some APIs accept `Path | str`, others only `Path` or only `str`. This inconsistency creates friction:

```python
# In config.py
def load_config(path: Path | str | None = None) -> RemoraConfig

# In discovery.py
def discover(paths: list[Path] | list[str], ...) -> list[CSTNode]

# In workspace.py
async def read(self, path: str) -> str  # str only
```

**Recommendation:** Standardize on `Path | str` for all public path APIs and normalize internally:

```python
PathLike = Path | str

def normalize_path(path: PathLike) -> Path:
    return Path(path) if isinstance(path, str) else path
```

---

#### 3.2.3 Hardcoded Ignore Patterns

**Location:** `src/remora/core/cairn_bridge.py:25-37`

```python
_IGNORE_DIRS = {
    ".agentfs", ".git", ".jj", ".mypy_cache", ...
}
```

**Problem:** Users cannot customize ignore patterns without modifying source.

**Recommendation:** Add to `WorkspaceConfig`:

```python
@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    base_path: str = ".remora/workspaces"
    cleanup_after: str = "1h"
    ignore_patterns: tuple[str, ...] = (
        ".git", ".jj", ".venv", "node_modules", "__pycache__", ...
    )
```

---

#### 3.2.4 Async Method Without Await

**Location:** `src/remora/core/context.py:57`

```python
async def handle(self, event: RemoraEvent) -> None:
    match event:
        case ToolResultEvent(...):
            self._recent.append(...)  # Synchronous operation
```

**Problem:** The method is `async` but contains no `await`. This is not wrong, but it's inefficient when called from synchronous contexts.

**Recommendation:** If the method never awaits, make it synchronous:

```python
def handle(self, event: RemoraEvent) -> None:
    # Same implementation without async
```

Or use `async` only if future changes might need it.

---

#### 3.2.5 Large Project Sync Could Be Slow

**Location:** `src/remora/core/cairn_bridge.py:136-160`

```python
async def _sync_project_to_workspace(self) -> None:
    for path in self._project_root.rglob("*"):
        # Reads and writes every file
```

**Problem:** For large codebases (thousands of files), this synchronous loop blocks initialization.

**Recommendation:** Add incremental/lazy sync options:

```python
class CairnWorkspaceService:
    async def initialize(self, *, sync: bool = True, lazy: bool = False) -> None:
        if sync and not lazy:
            await self._sync_project_to_workspace()
        elif sync and lazy:
            # Only sync files when first accessed
            self._lazy_sync = True
```

---

### 3.3 Minor Issues

#### 3.3.1 Magic Strings for Event Kinds

**Location:** `src/remora/ui/projector.py:66-83`

```python
def _event_kind(event) -> str:
    if isinstance(event, (GraphStartEvent, ...)):
        return "graph"  # Magic string
```

**Recommendation:** Use an enum:

```python
class EventKind(str, Enum):
    GRAPH = "graph"
    AGENT = "agent"
    TOOL = "tool"
    # ...
```

---

#### 3.3.2 Missing Type Narrowing in Executor

**Location:** `src/remora/core/executor.py:297-301`

```python
agent_result = cast(Any, result)
output = getattr(agent_result, "output", None)
```

**Problem:** Using `cast(Any, ...)` defeats type checking.

**Recommendation:** Define a protocol or use proper typing:

```python
from typing import Protocol

class AgentResultProtocol(Protocol):
    output: str | None
    final_message: Message | None
```

---

#### 3.3.3 Inconsistent Truncation Functions

Multiple truncation implementations exist:

```python
# executor.py:538
def _truncate(text: str, limit: int = 1024) -> str

# context.py:157
def _summarize(text: str, max_len: int = 200) -> str
```

**Recommendation:** Consolidate into `utils/`:

```python
# utils/text.py
def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - len(suffix)] + suffix
```

---

## 4. Component-by-Component Review

### 4.1 Core Configuration (`core/config.py`)

**Rating:** Excellent

**Highlights:**
- Frozen dataclasses ensure immutability
- Environment variable overrides are well-documented
- Clear section separation (Discovery, Bundle, Execution, etc.)
- Serialization roundtrip support

**Minor improvement:** Add validation for `cleanup_after` duration format:

```python
def _parse_duration(value: str) -> timedelta:
    """Parse '1h', '30m', '7d' format."""
    # Implementation
```

---

### 4.2 Discovery (`core/discovery.py`)

**Rating:** Excellent

**Highlights:**
- Efficient parallel parsing with ThreadPoolExecutor
- Proper resource loading via `importlib.resources`
- Deterministic node IDs via SHA256
- Clean query loading from `.scm` files

**Minor improvement:** Add caching for parsed trees:

```python
_parser_cache: dict[str, Parser] = {}

def _get_parser(language: str) -> Parser | None:
    if language in _parser_cache:
        return _parser_cache[language]
    # Create and cache...
```

---

### 4.3 Event Bus (`core/event_bus.py`)

**Rating:** Good

**Highlights:**
- Implements structured-agents Observer protocol
- Type-based subscriptions
- Async streaming context manager
- `wait_for` with predicate support

**Issue:** Global singleton (addressed above)

---

### 4.4 Graph Builder (`core/graph.py`)

**Rating:** Good

**Highlights:**
- Clean Kahn's algorithm implementation
- Cycle detection
- Batch computation for parallel execution

**Issues:**
- O(n) list operations (addressed above)
- Could benefit from graph visualization export

---

### 4.5 Graph Executor (`core/executor.py`)

**Rating:** Good

**Highlights:**
- Bounded concurrency via semaphore
- Error policies (STOP_GRAPH, SKIP_DOWNSTREAM, CONTINUE)
- Checkpoint integration points
- Clean kernel lifecycle management

**Minor issues:**
- Long method `_execute_agent` (~80 lines) could be decomposed
- Heavy use of `Any` types

---

### 4.6 Workspace Integration (`core/workspace.py`, `core/cairn_bridge.py`)

**Rating:** Good

**Highlights:**
- Clean Cairn abstraction
- CoW semantics for agent isolation
- Fallback to stable workspace on read

**Issues:**
- No workspace snapshot support (documented limitation)
- Synchronous file sync

---

### 4.7 Grail Tools (`core/tools/grail.py`)

**Rating:** Excellent

**Highlights:**
- Clean bridge between Grail and structured-agents
- Dynamic schema generation from Input() specs
- Virtual filesystem normalization

---

### 4.8 Service Layer (`service/api.py`, `service/handlers.py`)

**Rating:** Good

**Highlights:**
- Framework-agnostic design
- Clean request/response models
- Proper async task management

**Minor issues:**
- Some handler code duplication
- Task cleanup could be more robust

---

### 4.9 UI Components (`ui/view.py`, `ui/projector.py`)

**Rating:** Acceptable

**Highlights:**
- Pure HTML rendering
- Datastar integration for reactive updates
- State projection from events

**Issues:**
- Very procedural rendering code
- Limited component reuse
- Inline CSS and JS

---

### 4.10 CLI (`cli/main.py`)

**Rating:** Good

**Highlights:**
- Clean Click integration
- Proper error handling
- Both `serve` and `run` commands

---

## 5. Code Quality Metrics

### 5.1 Lines of Code

| Module | Lines | Assessment |
|--------|-------|------------|
| core/config.py | 260 | Appropriate |
| core/discovery.py | 360 | Appropriate |
| core/executor.py | 550 | Could be split |
| core/event_bus.py | 145 | Appropriate |
| core/workspace.py | 225 | Appropriate |
| ui/view.py | 370 | Could use component pattern |
| **Total src/** | ~3,500 | Lean |

### 5.2 Cyclomatic Complexity

| Function | Complexity | Assessment |
|----------|------------|------------|
| `_execute_agent` | 12 | Consider decomposition |
| `_parse_file` | 8 | Acceptable |
| `record` (projector) | 10 | Consider pattern matching simplification |

### 5.3 Type Coverage

Estimated type coverage: **90%+**

Most code is fully typed. Remaining `Any` usage:
- `workspace` parameters (Cairn types)
- `manifest` from structured-agents
- Event handlers

---

## 6. Testing Assessment

### 6.1 Test Coverage Structure

```
tests/
├── unit/                    # Unit tests
│   ├── test_event_bus.py
│   ├── test_agent_graph.py
│   ├── test_dashboard_views.py
│   ├── test_ui_projector.py
│   └── test_service_handlers.py
│
├── integration/             # Integration tests
│   ├── cairn/              # Cairn workspace tests
│   ├── test_executor_real.py
│   ├── test_checkpoint_roundtrip.py
│   └── ...
│
└── benchmarks/             # Performance tests
    └── test_discovery_performance.py
```

### 6.2 Test Quality Assessment

| Area | Coverage | Quality |
|------|----------|---------|
| Event Bus | High | Excellent |
| Graph Building | High | Good |
| Discovery | Medium | Good |
| Executor | Medium | Could improve |
| UI Views | Low | Needs improvement |
| Service Handlers | Medium | Good |

### 6.3 Recommendations

1. Add property-based tests for graph topological sort
2. Increase UI component test coverage
3. Add fuzz testing for discovery edge cases
4. Add load tests for large graphs

---

## Blue Sky Refactor Opportunities

The following opportunities represent larger architectural changes that could significantly improve the codebase, regardless of implementation effort.

### B1. Full Dependency Injection Container

**Current State:** Mixed DI with some global state

**Opportunity:** Implement a lightweight DI container:

```python
from dataclasses import dataclass

@dataclass
class RemoraContainer:
    config: RemoraConfig
    event_bus: EventBus
    context_builder: ContextBuilder
    workspace_service: CairnWorkspaceService

    @classmethod
    def create(cls, config_path: Path | None = None) -> "RemoraContainer":
        config = load_config(config_path)
        event_bus = EventBus()
        context_builder = ContextBuilder()
        event_bus.subscribe_all(context_builder.handle)
        # ...
        return cls(config, event_bus, context_builder, workspace_service)
```

**Benefits:**
- Eliminates all global state
- Simplifies testing
- Makes dependencies explicit
- Enables scoped containers for different runs

---

### B2. Component-Based UI Architecture

**Current State:** Procedural HTML generation

**Opportunity:** Create a component pattern:

```python
from dataclasses import dataclass
from abc import ABC, abstractmethod

class Component(ABC):
    @abstractmethod
    def render(self) -> str: ...

@dataclass
class Card(Component):
    title: str
    content: Component | str

    def render(self) -> str:
        content = self.content.render() if isinstance(self.content, Component) else self.content
        return f'<div class="card"><h3>{self.title}</h3>{content}</div>'

@dataclass
class AgentStatusList(Component):
    agents: dict[str, AgentState]

    def render(self) -> str:
        items = [AgentStatusItem(id, state).render() for id, state in self.agents.items()]
        return f'<div class="agent-list">{"".join(items)}</div>'
```

**Benefits:**
- Reusable components
- Easier testing
- Type-safe composition
- Potential for server-side rendering frameworks

---

### B3. Plugin System for Tool Discovery

**Current State:** Grail tools discovered from directory

**Opportunity:** Create a plugin registry:

```python
from abc import ABC, abstractmethod
from typing import Protocol

class ToolProvider(Protocol):
    def discover_tools(self, bundle_path: Path) -> list[Tool]: ...

class GrailToolProvider(ToolProvider):
    def discover_tools(self, bundle_path: Path) -> list[Tool]:
        return discover_grail_tools(bundle_path / "tools")

class PythonToolProvider(ToolProvider):
    def discover_tools(self, bundle_path: Path) -> list[Tool]:
        # Discover Python function tools
        ...

class ToolRegistry:
    def __init__(self):
        self._providers: list[ToolProvider] = []

    def register(self, provider: ToolProvider) -> None:
        self._providers.append(provider)

    def discover_all(self, bundle_path: Path) -> list[Tool]:
        tools = []
        for provider in self._providers:
            tools.extend(provider.discover_tools(bundle_path))
        return tools
```

**Benefits:**
- Extensible tool ecosystem
- Support for different tool types
- Plugin marketplace potential

---

### B4. Streaming File Sync

**Current State:** Full directory sync on initialization

**Opportunity:** Implement lazy/incremental sync:

```python
class StreamingWorkspaceSync:
    def __init__(self, project_root: Path, workspace: CairnWorkspace):
        self._root = project_root
        self._workspace = workspace
        self._synced: set[str] = set()
        self._watcher = None

    async def ensure_synced(self, path: str) -> None:
        """Sync a specific file on-demand."""
        if path in self._synced:
            return

        full_path = self._root / path
        if full_path.exists():
            content = await asyncio.to_thread(full_path.read_bytes)
            await self._workspace.files.write(path, content)
            self._synced.add(path)

    async def watch_changes(self) -> None:
        """Watch for file changes and sync incrementally."""
        async for changes in watchfiles.awatch(self._root):
            for change_type, path in changes:
                rel_path = Path(path).relative_to(self._root)
                if change_type == Change.modified:
                    await self._sync_file(str(rel_path))
```

**Benefits:**
- Faster startup for large projects
- Lower memory usage
- Real-time sync capability

---

### B5. Schema Validation for Bundle Files

**Current State:** Bundles loaded without validation

**Opportunity:** Add Pydantic-based bundle validation:

```python
from pydantic import BaseModel, Field

class GrammarConfig(BaseModel):
    strategy: Literal["json_schema", "ebnf", "structural_tag"] = "json_schema"
    send_tools_to_api: bool = True
    allow_parallel_calls: bool = False

class ToolEntry(BaseModel):
    name: str
    registry: str = "grail"
    description: str | None = None

class BundleManifest(BaseModel):
    name: str
    model: str
    system_prompt: str
    max_turns: int = Field(default=8, ge=1, le=100)
    termination_tool: str = "submit_result"
    grammar: GrammarConfig = Field(default_factory=GrammarConfig)
    tools: list[ToolEntry] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "BundleManifest":
        data = yaml.safe_load(path.read_text())
        return cls.model_validate(data)
```

**Benefits:**
- Early validation errors
- Clear documentation via schema
- IDE support for bundle authoring
- Version migration support

---

### B6. Event Sourcing for Execution History

**Current State:** Events emitted and projected, not persisted

**Opportunity:** Full event sourcing:

```python
class EventStore:
    def __init__(self, db_path: Path):
        self._db = sqlite3.connect(db_path)
        self._create_tables()

    async def append(self, graph_id: str, event: RemoraEvent) -> None:
        """Persist event to store."""
        self._db.execute(
            "INSERT INTO events (graph_id, event_type, payload, timestamp) VALUES (?, ?, ?, ?)",
            (graph_id, type(event).__name__, json.dumps(asdict(event)), time.time())
        )

    async def replay(self, graph_id: str) -> AsyncIterator[RemoraEvent]:
        """Replay all events for a graph."""
        cursor = self._db.execute(
            "SELECT event_type, payload FROM events WHERE graph_id = ? ORDER BY timestamp",
            (graph_id,)
        )
        for event_type, payload in cursor:
            yield self._deserialize(event_type, payload)
```

**Benefits:**
- Full audit trail
- Time-travel debugging
- Execution replay
- Analytics on agent behavior

---

### B7. WebSocket Support Alongside SSE

**Current State:** SSE only for real-time updates

**Opportunity:** Add WebSocket support:

```python
class DualStreamService:
    async def sse_stream(self) -> AsyncIterator[str]:
        """Server-Sent Events stream."""
        async with self._event_bus.stream() as events:
            async for event in events:
                yield f"event: {type(event).__name__}\ndata: {json.dumps(...)}\n\n"

    async def websocket_handler(self, ws: WebSocket) -> None:
        """WebSocket bidirectional stream."""
        await ws.accept()

        async def send_events():
            async with self._event_bus.stream() as events:
                async for event in events:
                    await ws.send_json(normalize_event(event))

        async def receive_commands():
            while True:
                data = await ws.receive_json()
                if data["type"] == "input_response":
                    await self.handle_input(data["request_id"], data["response"])

        await asyncio.gather(send_events(), receive_commands())
```

**Benefits:**
- Bidirectional communication
- Lower latency
- Better mobile support
- Connection state management

---

### B8. Multi-Model Agent Support

**Current State:** Single model per bundle

**Opportunity:** Support model routing:

```python
class ModelRouter:
    def __init__(self, models: dict[str, ModelConfig]):
        self._models = models
        self._clients: dict[str, LLMClient] = {}

    def select_model(self, task_type: str, complexity: int) -> str:
        """Select optimal model for task."""
        if complexity < 3:
            return "fast"  # Small, fast model
        elif task_type == "code_generation":
            return "code"  # Code-specialized model
        else:
            return "default"  # General purpose

    async def run_with_fallback(
        self,
        messages: list[Message],
        models: list[str],
    ) -> RunResult:
        """Try models in order until one succeeds."""
        for model_name in models:
            try:
                return await self._run(model_name, messages)
            except ModelOverloadError:
                continue
        raise AllModelsFailedError(models)
```

**Benefits:**
- Cost optimization
- Reliability via fallbacks
- Task-specific model selection
- A/B testing capability

---

### B9. Distributed Execution

**Current State:** Single-process execution

**Opportunity:** Distributed agent execution:

```python
class DistributedExecutor:
    def __init__(self, broker_url: str):
        self._broker = MessageBroker(broker_url)

    async def submit_graph(self, graph: list[AgentNode]) -> str:
        """Submit graph for distributed execution."""
        graph_id = uuid.uuid4().hex

        # Partition into batches
        batches = get_execution_batches(graph)

        for batch in batches:
            await asyncio.gather(*[
                self._broker.publish("agent.execute", {
                    "graph_id": graph_id,
                    "agent_id": node.id,
                    "bundle_path": str(node.bundle_path),
                })
                for node in batch
            ])

            # Wait for batch completion
            await self._wait_for_batch(graph_id, batch)

        return graph_id
```

**Benefits:**
- Horizontal scaling
- Resource isolation
- Multi-machine execution
- Better fault tolerance

---

### B10. AI-Assisted Bundle Authoring

**Current State:** Manual bundle creation

**Opportunity:** Use Remora to help write bundles:

```python
class BundleGenerator:
    """Meta-agent that generates agent bundles."""

    async def generate_bundle(
        self,
        task_description: str,
        example_inputs: list[dict],
        example_outputs: list[dict],
    ) -> BundleManifest:
        """Generate a bundle from natural language description."""

        # Use an LLM to design the bundle
        prompt = self._build_generation_prompt(
            task_description, example_inputs, example_outputs
        )

        result = await self._llm.complete(prompt)

        # Validate and return
        return BundleManifest.model_validate_json(result)

    async def improve_bundle(
        self,
        bundle: BundleManifest,
        failure_logs: list[str],
    ) -> BundleManifest:
        """Improve a bundle based on failure analysis."""
        ...
```

**Benefits:**
- Lower barrier to entry
- Automated bundle optimization
- Self-improving system
- Documentation generation

---

## Conclusion

Remora V2 represents a well-executed refactor that achieves its goals of elegance and maintainability. The integration with Grail and structured-agents is clean, the event-driven architecture is sound, and the code is generally well-structured.

**Priority Improvements:**
1. Remove the global EventBus singleton (Critical)
2. Fix O(n) list operations in topological sort (Critical)
3. Consolidate duplicate exports (Moderate)
4. Add configurable ignore patterns (Moderate)
5. Improve UI component architecture (Low)

**Recommended Next Steps:**
1. Address critical issues in the next minor release
2. Consider implementing B1 (DI Container) for cleaner architecture
3. Plan for B5 (Schema Validation) to improve bundle authoring
4. Evaluate B4 (Streaming Sync) based on user feedback about large projects

The codebase is in excellent shape for production use and future development.
