# Remora v1.0 — Ground-Up Refactor Ideas

## Purpose

This document proposes a complete ground-up refactor of Remora, taking the opportunity presented by the structured-agents v0.3 and Grail 3.0 integrations — plus Cairn as the workspace layer — to rethink the entire architecture. The goal: a framework where each layer has one job and one primary dependency, achieving the same overall functionality with half the files and none of the architectural debt.

This is a clean break. No backwards compatibility. Best architecture only.

---

## Current Architecture: What We're Working With

### The Good (Keep)

- **Event-driven lifecycle** — the EventBus with typed events and wildcard subscriptions is architecturally sound
- **Tree-sitter discovery** — multi-language CST scanning with thread pool is solid and well-tested
- **Agent graph as dependency DAG** — the concept of discovering code nodes, mapping to agents, and executing in dependency order is correct
- **Bundle-as-configuration** — declarative YAML for agent setup aligns with structured-agents v0.3
- **Two-Track Memory concept** — Short Track (rolling context) + Long Track (full history) is a good abstraction for bounded-context agents
- **Hub daemon concept** — background file indexing for incremental re-analysis is valuable
- **Pydantic config** — nested, validated configuration with YAML loading

### The Problematic (Rethink)

- **3 workspace abstractions** (`WorkspaceKV`, `GraphWorkspace`, `WorkspaceManager`) for what Cairn does natively with CoW isolation
- **2 "Hub" concepts jammed into one package** — `HubDaemon` (filesystem watcher + indexer) and `HubServer` (web dashboard + agent executor) are architecturally unrelated but share code, imports, and even state models
- **Broken interactive IPC** — `ask_user()` uses synchronous `time.sleep()` polling on `WorkspaceKV` with a `ContextVar` that doesn't survive the async boundary between `externals.py` and `agent_graph.py`
- **Mixed sync/async throughout** — `WorkspaceManager.get_or_create()` calls `asyncio.run()` inside sync; `TreeSitterDiscoverer.discover()` is sync; `ask_user()` blocks threads
- **Hardcoded model config** — `http://remora-server:8000/v1` and `Qwen/Qwen3-4B-Instruct-2507-FP8` baked into `_run_kernel()`, ignoring the config system
- **Duplicate .pym code** — helper functions copy-pasted across agent scripts (e.g., `analyze_signature.pym` in both `test/` and `sample_data/`)
- **Global mutable singletons** — `_event_bus`, `_hub_client` with no reset mechanism for testing
- **Fragile bundle path search** — 6 hardcoded paths with broken `or` condition
- **Pervasive `Any` typing** — `AgentNode.kernel`, `workspace`, `_kv_store` all typed as `Any` despite `mypy strict=true`
- **No workspace cleanup** — no TTL, GC, or automatic cleanup for workspace directories
- **Config reloaded on every file change** — `HubDaemon` re-reads and re-validates config (including DNS) per filesystem event

---

## Core Insight: What Is Remora Really Doing?

Strip away the abstraction layers and Remora does four things:

1. **Discover** — Scan source code with tree-sitter, produce a list of code nodes (functions, classes, files)
2. **Plan** — Map discovered nodes to agent bundles, build a dependency graph, determine execution order
3. **Execute** — For each agent: load bundle → run structured-agents kernel → .pym scripts compute in Cairn sandbox → collect validated results
4. **Index** — Maintain a persistent index of code nodes and their analysis results for incremental re-processing

Everything else is delivery mechanism: the Hub daemon delivers filesystem events to the indexer, the dashboard delivers status to humans, the event bus delivers lifecycle notifications to observers, the context system delivers bounded history to agents.

The current codebase obscures this by mixing delivery mechanisms into core logic — the `HubServer` both serves HTTP and executes graphs, `AgentNode` both represents graph topology and holds kernel state, `WorkspaceKV` both stores data and implements IPC.

A ground-up refactor should make these four concerns obvious in the code structure, with delivery mechanisms as thin, independent layers on top.

---

## Idea 1: Cairn Replaces All Workspace Abstractions

### Problem

Remora currently has three workspace abstractions:

- **`WorkspaceKV`** — file-backed JSON KV store with async locks. Keys split on `:` to path segments, stored as `.json` files. Used for agent state, IPC (outbox/inbox messaging), and metadata.
- **`GraphWorkspace`** — wraps `WorkspaceKV` with `agent_space()` and `shared_space()` partitioning, plus `snapshot_original()` and `merge()` for file versioning.
- **`WorkspaceManager`** — creates, lists, deletes, and caches `GraphWorkspace` instances. Contains the `asyncio.run()` inside sync method bug.

These collectively implement file isolation, versioning, and IPC — all things Cairn does natively with copy-on-write overlays and explicit accept/reject gates.

### Proposal: Cairn IS the Workspace

Replace all three classes with direct Cairn workspace usage:

- **File isolation**: Cairn's CoW overlay replaces `GraphWorkspace.agent_space()`. Each agent gets a Cairn workspace. Writes are isolated until explicitly accepted.
- **Shared state**: Cairn's base layer replaces `GraphWorkspace.shared_space()`. Accepted changes propagate to downstream agents' workspaces.
- **Versioning**: Cairn's snapshot/accept/reject replaces `snapshot_original()` and `merge()`.
- **Cleanup**: Cairn manages workspace lifecycle — no orphaned directories.

The Grail virtual filesystem is populated FROM Cairn workspaces: when a .pym tool executes, its `files={}` dict is built by reading the relevant files from the agent's Cairn workspace. This is the `DataProvider` pattern from structured-agents v0.3.

```python
class CairnDataProvider:
    """Populates Grail virtual FS from a Cairn workspace."""
    
    def __init__(self, workspace: CairnWorkspace):
        self._ws = workspace
    
    async def load_files(self, node: CSTNode) -> dict[str, str]:
        """Read the target file + related files from the workspace."""
        files = {}
        files[node.file_path] = await self._ws.read(node.file_path)
        # Add related files based on node metadata
        return files
```

### What This Eliminates

- `workspace.py` entirely (~200 lines)
- `agent_state.py` (`AgentKVStore` — workspace KV wrapper)
- The `asyncio.run()` in sync context bug
- Orphaned workspace directory problem
- File-backed JSON KV serialization/deserialization

### What This Preserves

- Isolated agent workspaces (now via CoW instead of directory copies)
- Shared state across agents in a graph (now via Cairn base layer)
- Snapshot/restore for checkpointing (now via Cairn snapshots)

### Trade-off

Cairn becomes a hard dependency rather than an optional one. Currently Cairn is used only for sandbox execution — this makes it the workspace layer too. Given that Remora's entire execution model depends on sandboxed script execution, Cairn is already effectively required. Making the dependency explicit is more honest than pretending workspace isolation can work without it.

---

## Idea 2: Align Agent Execution to structured-agents v0.3

### Problem

Remora's `GraphExecutor._run_kernel()` manually wires structured-agents internals: imports `AgentKernel`, `KernelConfig`, `QwenPlugin`, `GrailBackend`, `GrailBackendConfig`, `RegistryBackendToolSource`, `GrailRegistry`, `GrailRegistryConfig`, `GrammarConfig`. Hardcodes `http://remora-server:8000/v1` and `Qwen/Qwen3-4B-Instruct-2507-FP8`. Creates kernel with vLLM base_url, plugin, grammar config, tool source from registry+backend.

This is v0.2 wiring. structured-agents v0.3 replaces all of this with `Agent.from_bundle()`.

### Proposal: Use Agent.from_bundle() Directly

Each `AgentNode` in the graph holds a bundle path. Execution becomes:

```python
async def execute_agent(node: AgentNode, workspace: CairnWorkspace) -> RunResult:
    """Execute a single agent using structured-agents v0.3."""
    data_provider = CairnDataProvider(workspace)
    agent = await Agent.from_bundle(
        node.bundle_path,
        data_provider=data_provider,
        observer=node.observer,
    )
    return await agent.run(node.build_prompt())
```

That's it. No manual kernel wiring. No hardcoded URLs. The bundle YAML specifies the model, grammar strategy, limits, tools, and system prompt. structured-agents handles all internal construction.

**Remora's bundle.yaml extends structured-agents' format:**

```yaml
# Standard structured-agents fields
name: lint_agent
model: qwen
grammar: ebnf
limits: default
system_prompt: |
  You are a linting agent...
tools:
  - tools/*.pym
termination: submit_result
max_turns: 8

# Remora-specific extensions
node_types: [function, class]    # which CSTNode types this agent handles
priority: 10                     # execution priority in graph
requires_context: true           # whether to inject Two-Track Memory
```

### What This Eliminates

- `_run_kernel()` method entirely (~80 lines of manual wiring)
- Hardcoded vLLM URL and model name
- Direct dependency on structured-agents v0.2 internal classes (`GrailBackend`, `GrailRegistry`, `RegistryBackendToolSource`, etc.)
- `backend.py` (`require_backend_extra()` guard)

### What This Preserves

- Full control over agent behavior (via bundle YAML)
- Model selection and grammar strategy (via bundle config, not hardcoded)
- Tool discovery from .pym scripts (now via structured-agents' `discover_tools()`)
- Observable lifecycle (now via structured-agents' `Observer.emit()`)

### Trade-off

Remora becomes dependent on structured-agents v0.3's bundle format. If the bundle format changes, Remora's bundles need updating. This is acceptable because: (a) both libraries are in the same ecosystem, (b) the bundle format is a declarative contract that changes rarely, and (c) Remora was already deeply coupled to structured-agents internals — coupling to a public API is strictly better.

---

## Idea 3: Split the Hub Into Indexer and Dashboard

### Problem

The `hub/` package contains 14 files serving two unrelated purposes:

1. **Indexer** (`daemon.py`, `indexer.py`, `watcher.py`, `rules.py`, `call_graph.py`, `test_discovery.py`): Watches the filesystem, parses source files, maintains a `NodeStateStore` of function/class metadata. Runs as a background daemon.

2. **Dashboard** (`server.py`, `views.py`, `state.py`, `registry.py`): Serves an SSE-powered web UI, handles graph execution requests, manages interactive IPC. Runs as an HTTP server.

These share `store.py` and `models.py` but are otherwise independent. Jamming them into one package creates problems: `HubServer` imports `HubDaemon` internals, the daemon's `fsdantic.Workspace` leaks into server code, and `metrics.py`/`imports.py` are shared utilities that neither actually needs as shared code.

### Proposal: Two Independent Packages

**`remora/indexer/`** — Background file indexer:
- `daemon.py` — filesystem watcher + cold-start indexer
- `store.py` — fsdantic `TypedKVRepository` for node state
- `models.py` — `NodeState`, `FileIndex` (fsdantic `VersionedKVRecord`)
- `rules.py` — `RulesEngine` with update actions
- `scanner.py` — tree-sitter integration (extracts signatures, imports, call graph)

Entry point: `remora-index` CLI. Watches directories, maintains the index. No web server, no graph execution, no agent logic.

**`remora/dashboard/`** — Web interface:
- `app.py` — Starlette application with routes
- `views.py` — datastar-py SSE views
- `state.py` — dashboard-specific state (connected clients, active graphs)

Entry point: `remora-dashboard` CLI. Reads from the index store (read-only). Triggers graph execution via the core `GraphExecutor`. Serves SSE updates by subscribing to the EventBus.

**The shared dependency is the store**, which becomes a standalone module (`remora/store.py` or stays in `remora/indexer/store.py` with the dashboard importing it). The models are data — they can live anywhere both packages can import them.

### What This Eliminates

- `hub/` package entirely (14 files → 2 focused packages totaling ~10 files)
- Cross-contamination between daemon and server code
- `hub/cli.py` (split into two CLI entry points)
- `hub/imports.py` and `hub/metrics.py` (absorbed into their respective packages)
- The confusion of "what is the Hub?" — it's two things, so name them separately

### What This Preserves

- Background file indexing (indexer daemon)
- Web dashboard with SSE updates (dashboard server)
- Persistent node state store (shared via fsdantic)
- All current dashboard functionality

### Trade-off

Two processes instead of one. But they were already conceptually separate — the daemon runs independently of whether anyone is viewing the dashboard. Making this explicit prevents future coupling and makes each component independently deployable and testable.

---

## Idea 4: Flatten the Agent Graph

### Problem

`AgentGraph` and `GraphExecutor` are currently entangled with too many concerns. `AgentNode` holds: graph topology (upstream/downstream), agent identity (name, target CSTNode), execution state (state enum, result), kernel reference (typed as `Any`), workspace reference (typed as `Any`), inbox for IPC, and bundle config. It's a god object.

`GraphExecutor` handles: dependency ordering, semaphore-based concurrency, kernel construction and execution, simulation mode, checkpoint save/restore, event emission, error policy routing, and interactive coordination. It's a god method.

### Proposal: Separate Topology from Execution

**`AgentNode` becomes a pure data object:**

```python
@dataclass(frozen=True)
class AgentNode:
    """A node in the execution graph. Immutable topology."""
    id: str
    name: str
    target: CSTNode
    bundle_path: Path
    upstream: frozenset[str] = frozenset()
    downstream: frozenset[str] = frozenset()
```

No state, no kernel, no workspace, no inbox. Just "what agent, what target, what dependencies."

**`AgentGraph` becomes a pure function that builds the DAG:**

```python
def build_graph(
    nodes: list[CSTNode],
    bundles: dict[str, Path],   # node_type -> bundle path mapping
) -> list[AgentNode]:
    """Map discovered code nodes to agent nodes with dependency edges."""
    ...
```

**`GraphExecutor` becomes a focused async runner:**

```python
class GraphExecutor:
    """Runs agents in dependency order with bounded concurrency."""
    
    def __init__(self, config: GraphConfig, observer: Observer):
        self.config = config
        self.observer = observer
    
    async def run(self, graph: list[AgentNode]) -> dict[str, RunResult]:
        """Execute all agents in topological order."""
        # Dependency ordering + semaphore concurrency
        # For each ready node: create Cairn workspace, call execute_agent()
        # Collect results, handle errors per policy
        ...
```

The executor doesn't know about kernels, bundles, or IPC. It creates a Cairn workspace, calls `execute_agent()` (from Idea 2), and collects the `RunResult`. All structured-agents wiring is hidden behind `Agent.from_bundle()`.

### What This Eliminates

- `AgentNode` as a mutable god object → pure frozen dataclass
- `AgentInbox` (IPC moves to Idea 7)
- `AgentState` enum management inside AgentNode (state tracked by executor)
- `_simulate_execution()` method (testing uses the real executor with mock agents)
- `agent_graph.py` as a 400-line monolith → split into `graph.py` (topology) + `executor.py` (running)

### What This Preserves

- Dependency-ordered execution
- Configurable concurrency (semaphore)
- Error policies (STOP_GRAPH, SKIP_DOWNSTREAM, CONTINUE)
- Event emission at lifecycle points

### Trade-off

`AgentNode` can no longer carry mutable state through the execution. The executor must track state externally (a `dict[str, AgentState]`). This is actually cleaner — the node describes the work, the executor tracks progress.

---

## Idea 5: Unify the Event System

### Problem

Remora currently has its own `EventBus` with `Event` objects (category/action strings, Pydantic frozen models, wildcard subscriptions, async streaming). structured-agents v0.3 has its own `Observer.emit()` with typed event dataclasses and pattern matching. These are two separate event systems that don't talk to each other.

When `GraphExecutor` runs a kernel, the kernel emits structured-agents events (`ToolCallEvent`, `ModelResponseEvent`, etc.) to its observer, while the executor emits Remora events (`agent.started`, `agent.completed`, etc.) to the EventBus. Dashboard code subscribing to Remora's EventBus never sees kernel-level events. Kernel observers never see graph-level events.

Additionally, Remora's `EventBus` uses string-based `category:action` patterns with wildcard matching — functional but stringly typed and not amenable to exhaustive pattern matching.

### Proposal: One Event Taxonomy, One Dispatch Mechanism

Define a single `Event` union type that covers both graph-level and kernel-level events:

```python
# Remora graph events
@dataclass(frozen=True)
class GraphStartEvent:
    graph_id: str
    node_count: int
    timestamp: float

@dataclass(frozen=True)
class AgentStartEvent:
    graph_id: str
    agent_id: str
    node: CSTNode
    timestamp: float

@dataclass(frozen=True)
class AgentCompleteEvent:
    graph_id: str
    agent_id: str
    result: RunResult
    timestamp: float

@dataclass(frozen=True)
class AgentErrorEvent:
    graph_id: str
    agent_id: str
    error: str
    timestamp: float

# Re-export structured-agents kernel events as-is
# KernelStartEvent, ToolCallEvent, ToolResultEvent, etc.

# Union type
RemoraEvent = (
    GraphStartEvent | GraphCompleteEvent |
    AgentStartEvent | AgentCompleteEvent | AgentErrorEvent |
    KernelStartEvent | KernelEndEvent |
    ToolCallEvent | ToolResultEvent |
    ModelRequestEvent | ModelResponseEvent |
    ...
)
```

**The `EventBus` becomes a bridge:** it implements structured-agents' `Observer` protocol and adds Remora's pub/sub features on top:

```python
class EventBus:
    """Unified event dispatch. Implements structured-agents Observer."""
    
    async def emit(self, event: RemoraEvent) -> None:
        """Observer protocol — receives all events."""
        for handler in self._handlers:
            await handler(event)
    
    def subscribe(self, event_type: type, handler: Callable) -> None:
        """Subscribe to a specific event type."""
        ...
    
    async def stream(self, *event_types: type) -> AsyncIterator[RemoraEvent]:
        """Async iterator filtered to specific event types."""
        ...
```

The `GraphExecutor` passes the `EventBus` as the observer to each structured-agents `Agent`. All events — graph, kernel, tool, model — flow through one bus.

### What This Eliminates

- Dual event systems (Remora EventBus + structured-agents Observer)
- String-based `category:action` event naming
- The `Event` Pydantic model with convenience constructors
- `EventStream` class (replaced by `stream()` method on EventBus)
- Missed events between layers (kernel events now visible to dashboard)

### What This Preserves

- Pub/sub subscription (now type-based instead of string-based)
- Async streaming for SSE dashboard
- Wildcard-style filtering (subscribe to a base type to get all subtypes)
- Pattern matching on events (`match event: case AgentCompleteEvent(): ...`)

### Trade-off

Remora's event types become part of the public API surface. Adding or changing events requires thought about compatibility. This is actually desirable — it forces event design to be intentional rather than ad-hoc string construction.

---

## Idea 6: Simplify the Context System (Two-Track Memory)

### Problem

The context package has 5 files implementing Two-Track Memory:

- `manager.py` — `ContextManager` with `apply_event()` routing, `project()` for building prompts, `pull_hub_context()` for Hub integration
- `models.py` — `DecisionPacket` (Short Track), `RecentAction`, `KnowledgeEntry`
- `contracts.py` — `ToolResult` schema with `make_success()`/`make_error()`/`make_partial()` helpers
- `hub_client.py` — `HubClient` with "Lazy Daemon" pattern (read Hub workspace, fall back to ad-hoc indexing)
- `summarizers.py` — text summarization for knowledge entries

The `ContextManager` consumes Remora's current string-based events via `apply_event()`, which is a large switch statement on `event.category` and `event.action` strings. It builds a `DecisionPacket` that gets injected into the agent's system prompt.

The `contracts.py` module defines its own `ToolResult` schema that conflicts with structured-agents' `ToolResult` dataclass.

### Proposal: Context as an EventBus Subscriber

With the unified event system (Idea 5), the context manager becomes a simple event subscriber:

```python
class ContextBuilder:
    """Builds bounded context from the event stream."""
    
    def __init__(self, window_size: int = 20):
        self._recent: deque[RecentAction] = deque(maxlen=window_size)
        self._knowledge: dict[str, str] = {}
    
    async def handle(self, event: RemoraEvent) -> None:
        """EventBus subscriber — updates context from events."""
        match event:
            case ToolResultEvent(name=name, output=output, is_error=is_error):
                self._recent.append(RecentAction(
                    tool=name,
                    outcome="error" if is_error else "success",
                    summary=_summarize(output),
                ))
            case AgentCompleteEvent(agent_id=aid, result=result):
                self._knowledge[aid] = _extract_knowledge(result)
            case _:
                pass
    
    def build_prompt_section(self) -> str:
        """Render current context as a prompt section."""
        ...
```

**Key changes:**
- `ContextManager` → `ContextBuilder` (it builds context, it doesn't "manage" anything)
- `apply_event()` switch statement → pattern matching on typed events
- `contracts.py` eliminated — use structured-agents' `ToolResult` directly
- `hub_client.py` simplified — the indexer (Idea 3) provides node context via its store, not via a "Lazy Daemon" pattern
- `summarizers.py` absorbed into `ContextBuilder` (it's one function)

**Hub context integration:**

```python
class ContextBuilder:
    def __init__(self, store: NodeStateStore | None = None, ...):
        self._store = store
    
    def build_context_for(self, node: CSTNode) -> str:
        """Build full context: hub index data + rolling short track."""
        sections = []
        if self._store:
            # Pull related node data from the index
            related = self._store.get_related(node)
            sections.append(_format_related_nodes(related))
        sections.append(self.build_prompt_section())
        return "\n".join(sections)
```

### What This Eliminates

- `context/manager.py` (event routing switch statement → pattern matching)
- `context/contracts.py` (conflicting ToolResult schema → use structured-agents')
- `context/hub_client.py` ("Lazy Daemon" pattern → direct store read)
- `context/summarizers.py` (absorbed into ContextBuilder)
- 5 files → 2 files (`context.py` + `models.py`, or just `context.py`)

### What This Preserves

- Two-Track Memory concept (Short Track = rolling recent actions, Long Track = full event stream)
- `DecisionPacket` / bounded context for agent prompts
- Hub index integration for related-node context
- Knowledge accumulation across agent executions

### Trade-off

The `ContextBuilder` must understand structured-agents event types to pattern match on them. This is a tighter coupling to structured-agents' event model. Acceptable because: (a) Remora is already built on structured-agents, (b) the event types are frozen dataclasses — stable contracts, and (c) the alternative (string-based routing) was worse.

---

## Idea 7: Redesign Interactive IPC

### Problem

The current interactive system is broken:

1. **`externals.py`** — `ask_user()` is a synchronous function (called from within a Grail `@external`) that uses `time.sleep()` polling on a `WorkspaceKV` to wait for a response. It writes a question to `outbox:question:{id}` and polls `inbox:response:{id}`.

2. **`coordinator.py`** — `WorkspaceInboxCoordinator` polls the same `WorkspaceKV` from the server side, looking for outbox questions, and publishes events to prompt the dashboard.

3. **The critical bug:** `ask_user()` uses a `ContextVar` (`_current_workspace`) that is set in `agent_graph.py` before kernel execution. But the kernel runs Grail scripts in a different async context (and potentially a different thread via Cairn), so the `ContextVar` is not available. The IPC is fundamentally broken.

### Proposal: Event-Based Human-in-the-Loop

Replace file-based polling with event-based request/response through the unified EventBus:

```python
@dataclass(frozen=True)
class HumanInputRequestEvent:
    """Agent is blocked waiting for human input."""
    graph_id: str
    agent_id: str
    request_id: str
    question: str
    options: list[str] | None = None
    timestamp: float = field(default_factory=time.time)

@dataclass(frozen=True)
class HumanInputResponseEvent:
    """Human has responded to an input request."""
    request_id: str
    response: str
    timestamp: float = field(default_factory=time.time)
```

**On the agent side**, human input becomes a Grail `@external` that the host wires to an async event wait:

```python
async def ask_user_external(question: str) -> str:
    """Grail @external implementation. Emits event, awaits response."""
    request_id = uuid4().hex
    event = HumanInputRequestEvent(
        graph_id=current_graph_id,
        agent_id=current_agent_id,
        request_id=request_id,
        question=question,
    )
    await event_bus.emit(event)
    
    # Wait for matching response event
    response = await event_bus.wait_for(
        HumanInputResponseEvent,
        lambda e: e.request_id == request_id,
        timeout=300,  # 5 minute timeout
    )
    return response.response
```

**On the dashboard side**, the SSE stream delivers `HumanInputRequestEvent` to the browser. The user responds via HTTP POST, which emits `HumanInputResponseEvent`. The agent's `wait_for()` resolves.

**`EventBus.wait_for()` is the new primitive:**

```python
class EventBus:
    async def wait_for(
        self, 
        event_type: type[T], 
        predicate: Callable[[T], bool],
        timeout: float = 60,
    ) -> T:
        """Block until an event matching the predicate is emitted."""
        future: asyncio.Future[T] = asyncio.get_event_loop().create_future()
        
        def handler(event: RemoraEvent) -> None:
            if isinstance(event, event_type) and predicate(event):
                future.set_result(event)
        
        self.subscribe(event_type, handler)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.unsubscribe(handler)
```

### What This Eliminates

- `interactive/externals.py` (synchronous polling → async event wait)
- `interactive/coordinator.py` (KV polling → event subscription)
- `WorkspaceKV` as IPC mechanism (events replace file-based messaging)
- The `ContextVar` bug (no context vars needed — events are passed explicitly)
- `time.sleep()` polling (async `wait_for()` is non-blocking)

### What This Preserves

- Human-in-the-loop capability (agents can ask questions and wait for answers)
- Dashboard integration (SSE delivers questions, HTTP POST delivers answers)
- Timeout handling (configurable per request)

### Trade-off

The `EventBus` gains state (`wait_for` futures) and becomes more than a pure pub/sub bus. This is acceptable because: (a) the alternative (file-based polling) was broken, (b) `wait_for` is a well-understood async pattern (asyncio.Event, asyncio.Condition), and (c) it keeps the IPC in-process rather than crossing filesystem boundaries.

---

## Idea 8: .pym Scripts as Pure Functions via Virtual FS

### Problem

Current .pym scripts use `@external` declarations for all file I/O: `read_file`, `write_file`, `file_exists`, `run_command`, `run_json_command`. The host provides implementations of these externals that access the real filesystem (or workspace). This means:

1. Scripts have side effects during execution (they write files, run commands)
2. The host must implement 5+ external functions per agent bundle
3. External implementations are complex (workspace-aware file operations with path resolution)
4. Scripts are tightly coupled to the I/O mechanism (`@external` signatures must match exactly)
5. Some scripts duplicate helper code because they can't share modules

### Proposal: Data In via Virtual FS, Mutations Out via Return Value

Following the structured-agents v0.3 concept ("scripts as pure functions"):

**Before (current):**
```python
# read_file.pym
from grail import external

@external
async def read_file(path: str) -> str: ...

result = await read_file("src/foo.py")
# Script does I/O
```

**After (proposed):**
```python
# analyze_code.pym
from grail import Input
import os

# Data flows IN via virtual filesystem
source_code: str = Input("source_code")
file_path: str = Input("file_path")

# Or read from virtual FS directly
# content = open("target.py").read()  # reads from virtual FS, not real FS

# Pure computation
issues = []
for i, line in enumerate(source_code.split("\n")):
    if len(line) > 120:
        issues.append({"line": i + 1, "issue": "line too long"})

# Return structured result — host persists any mutations
result = {
    "file_path": file_path,
    "issues": issues,
    "suggested_fix": "...",
}
```

**The `CairnDataProvider` (from Idea 1) populates the virtual FS before execution:**

```python
files = {
    "target.py": source_code,
    "config.toml": project_config,
    "related/test_foo.py": existing_tests,
}
result = await script.run(inputs=inputs, files=files)
```

**The `ResultHandler` persists mutations after execution:**

```python
class CairnResultHandler:
    """Writes script results back to the Cairn workspace."""
    
    async def handle(self, result: dict, workspace: CairnWorkspace) -> None:
        if "written_file" in result:
            await workspace.write(result["file_path"], result["written_file"])
        if "lint_fixes" in result:
            # Apply fixes to workspace
            ...
```

**`@external` is reserved for genuine external services** — things the script legitimately cannot do in the sandbox:
- `ask_user(question) -> str` — human-in-the-loop (wired to Idea 7's event-based IPC)
- Future: API calls, database queries that can't be pre-loaded

### What This Eliminates

- All `@external` declarations for file I/O (`read_file`, `write_file`, `file_exists`)
- All `@external` declarations for command execution (`run_command`, `run_json_command`)
- Host-side external implementations (~20 lines per external per bundle)
- Script-side I/O coupling (scripts don't know how data gets to them)
- Duplicate helper code across scripts (each script is self-contained)

### What This Preserves

- Sandboxed execution (Grail's Monty runtime)
- Type-safe inputs (`Input()` with annotations)
- Output validation (`output_model` on `run()`)
- The ability to use `@external` for genuine external services

### Trade-off

Scripts can no longer make ad-hoc file reads during execution. All data must be pre-loaded into the virtual FS. This means the `DataProvider` must anticipate what data a script needs. In practice, this is knowable from the script's purpose and the target `CSTNode` — a lint tool needs the target file plus config, a test tool needs the target file plus existing tests. If a script needs data that wasn't pre-loaded, it's a `DataProvider` bug, not a script limitation.

---

## Idea 9: Simplify Discovery

### Problem

The discovery package has 5 files:

- `discoverer.py` — `TreeSitterDiscoverer` with thread pool execution, language detection, recursive directory walking
- `models.py` — `CSTNode` (frozen dataclass), `compute_node_id()` (SHA256-based)
- `match_extractor.py` — extracts matched nodes from tree-sitter captures
- `query_loader.py` — loads `.scm` query files from the `queries/` directory
- `source_parser.py` — parses source files with tree-sitter and applies queries

This works well but is over-modularized for what it does. The five files are always used together — there's no scenario where you use `match_extractor.py` without `source_parser.py`.

### Proposal: Consolidate to Two Files

**`discovery.py`** — the public API:

```python
@dataclass(frozen=True, slots=True)
class CSTNode:
    """A concrete syntax tree node discovered from source code."""
    node_id: str          # SHA256-based deterministic ID
    node_type: str        # "function", "class", "file", "section", "table"
    name: str
    file_path: str
    text: str
    start_line: int
    end_line: int

def discover(
    paths: list[Path],
    languages: list[str] | None = None,
    node_types: list[str] | None = None,
    max_workers: int = 4,
) -> list[CSTNode]:
    """Scan source paths with tree-sitter and return discovered nodes.
    
    Uses thread pool for parallel file parsing. Language auto-detected
    from file extension. Custom .scm queries loaded from queries/ dir.
    """
    ...
```

**`queries/`** directory stays as-is — `.scm` files organized by language and query set.

The internal implementation (`_parse_file`, `_load_queries`, `_extract_matches`) lives as private functions in `discovery.py`. No separate `source_parser.py`, `match_extractor.py`, `query_loader.py` — they're private implementation details of the `discover()` function.

### What This Eliminates

- 5 files → 1 file + queries directory
- `TreeSitterDiscoverer` class (it's stateless — a function is more appropriate)
- Import chains between discovery submodules
- Over-modularization of a cohesive concern

### What This Preserves

- Tree-sitter parsing with multi-language support
- Thread pool for parallel file processing
- Custom `.scm` query files
- `CSTNode` as the canonical discovered node type
- SHA256-based deterministic node IDs

### Trade-off

Losing separate files makes git blame less granular for the discovery internals. Acceptable because: (a) discovery is a stable, well-understood concern, (b) the files were always changed together, and (c) one 200-line file is easier to understand than five 40-line files with import dependencies.

---

## Idea 10: Flatten Configuration

### Problem

`RemoraConfig` is deeply nested Pydantic: `ServerConfig`, `RunnerConfig`, `DiscoveryConfig`, `CairnConfig`, `HubConfig`, plus bundle-level config. Configuration is loaded via `load_config()` from YAML with overrides. But:

1. The config is reloaded repeatedly (`HubDaemon` reloads on every file change)
2. Bundle config partially duplicates `RemoraConfig` fields
3. Some config is ignored (the hardcoded vLLM URL bypasses `ServerConfig`)
4. Nesting is deep: `config.runner.cairn.limits_preset` to set Grail limits

With structured-agents v0.3, most agent-level config moves to `bundle.yaml` (model, grammar, limits, tools). Remora's config should cover only Remora-specific concerns.

### Proposal: Two-Level Config

**Level 1: `remora.yaml`** — project-level config (loaded once at startup):

```yaml
# Where to find source code
discovery:
  paths: ["src/"]
  languages: ["python", "markdown"]
  
# Where to find agent bundles  
bundles:
  path: "agents/"
  mapping:
    function: lint
    class: docstring
    file: test

# Graph execution
execution:
  max_concurrency: 4
  error_policy: skip_downstream  # stop_graph | skip_downstream | continue
  timeout: 300

# Indexer daemon
indexer:
  watch_paths: ["src/"]
  store_path: ".remora/index"

# Dashboard
dashboard:
  host: "0.0.0.0"
  port: 8420
  
# Cairn workspace  
workspace:
  base_path: ".remora/workspaces"
  cleanup_after: "1h"

# Model server (used by bundles that don't specify their own)
model:
  base_url: "http://localhost:8000/v1"
  default_model: "Qwen/Qwen3-4B"
```

**Level 2: `bundle.yaml`** — per-agent config (structured-agents v0.3 format, see Idea 2).

The separation is clean: `remora.yaml` says "what to scan, how to execute, where to store." `bundle.yaml` says "what model, what grammar, what tools, what limits."

**Config loading:**

```python
@dataclass(frozen=True)
class RemoraConfig:
    discovery: DiscoveryConfig
    bundles: BundleConfig
    execution: ExecutionConfig
    indexer: IndexerConfig
    dashboard: DashboardConfig
    workspace: WorkspaceConfig
    model: ModelConfig

def load_config(path: Path = Path("remora.yaml")) -> RemoraConfig:
    """Load config once. Immutable after load."""
    ...
```

Frozen dataclass, not Pydantic. Loaded once. No re-reading. Passed explicitly to components that need it — no global `_config` singleton.

### What This Eliminates

- Deep nesting (`config.runner.cairn.limits_preset` → `bundle.yaml: limits: default`)
- Config reload on every file change
- Overlap between `RemoraConfig` and bundle config
- Ignored config fields (hardcoded URL was always used instead)
- `constants.py` (constants absorbed into config defaults)

### What This Preserves

- YAML-based configuration
- All configurable dimensions (paths, concurrency, timeout, ports)
- Override capability (environment variables can override config fields)

### Trade-off

Two config files instead of one. But they serve different audiences: `remora.yaml` is for the project operator, `bundle.yaml` is for the agent author. These are different people (or the same person wearing different hats). Separating their concerns reduces confusion.

---

## Idea 11: Checkpointing via Cairn Snapshots

### Problem

`CheckpointManager` currently materializes workspace state to a directory and exports `AgentKVStore` data as JSON. Restore reads the directory back. This is tightly coupled to `GraphWorkspace` and `AgentKVStore` — both of which are being eliminated (Ideas 1 and 4).

### Proposal: Cairn-Native Checkpointing

Cairn already provides snapshot and restore capabilities on workspaces. Checkpointing becomes:

```python
class CheckpointManager:
    """Save and restore graph execution state via Cairn snapshots."""
    
    async def save(self, graph_id: str, executor_state: ExecutorState) -> str:
        """Snapshot all agent workspaces + execution state."""
        checkpoint_id = f"{graph_id}_{datetime.now().isoformat()}"
        
        # Cairn snapshots each agent's workspace
        for agent_id, workspace in executor_state.workspaces.items():
            await workspace.snapshot(f"{checkpoint_id}/{agent_id}")
        
        # Save execution metadata (which agents completed, current state)
        metadata = executor_state.to_dict()
        await self._store.put(checkpoint_id, metadata)
        
        return checkpoint_id
    
    async def restore(self, checkpoint_id: str) -> ExecutorState:
        """Restore workspaces and execution state from checkpoint."""
        metadata = await self._store.get(checkpoint_id)
        workspaces = {}
        for agent_id in metadata["agents"]:
            workspaces[agent_id] = await CairnWorkspace.from_snapshot(
                f"{checkpoint_id}/{agent_id}"
            )
        return ExecutorState.from_dict(metadata, workspaces)
```

The `ExecutorState` is a frozen dataclass capturing: which agents have completed, their results, which are pending, and the current graph position. Combined with Cairn workspace snapshots, this provides full resume capability.

### What This Eliminates

- Current `CheckpointManager` (coupled to `GraphWorkspace` + `AgentKVStore`)
- Custom directory materialization code
- JSON export/import of KV store data

### What This Preserves

- Save/restore of graph execution state
- Resume from checkpoint after crash or interruption
- Multiple named checkpoints

### Trade-off

Checkpoint format changes — old checkpoints are not loadable. Since this is a clean break, that's fine.

---

## Proposed Module Structure

### Current: 7 Packages, ~50+ Files

```
src/remora/
  __init__.py, agent_graph.py, agent_state.py, backend.py, checkpoint.py,
  cli.py, client.py, config.py, constants.py, errors.py, event_bus.py,
  workspace.py, __main__.py

  hub/         (14 files)
  context/     (5 files)
  discovery/   (5 files)
  interactive/ (2 files)
  frontend/    (3 files)
  testing/     (2 files)
  utils/       (1 file)
  queries/     (.scm files)

agents/        (5 bundles, 22 .pym scripts)
```

### Proposed: 4 Packages, ~22 Files

```
src/remora/
  __init__.py          # Public API: discover, build_graph, GraphExecutor, EventBus, etc.
  config.py            # RemoraConfig (frozen dataclass), load_config()
  discovery.py         # CSTNode, discover() function
  graph.py             # AgentNode (frozen), build_graph() function
  executor.py          # GraphExecutor, ExecutorState, execute_agent()
  events.py            # RemoraEvent union type, all event dataclasses
  event_bus.py         # EventBus (implements Observer), subscribe, stream, wait_for
  context.py           # ContextBuilder, RecentAction, knowledge accumulation
  checkpoint.py        # CheckpointManager (Cairn-native)
  workspace.py         # CairnDataProvider, CairnResultHandler (thin wrappers)
  errors.py            # RemoraError hierarchy (simplified)
  cli.py               # Main CLI entry point
  __main__.py          # python -m remora

  indexer/
    __init__.py
    daemon.py          # Filesystem watcher + cold-start indexer
    store.py           # NodeStateStore (fsdantic TypedKVRepository)
    models.py          # NodeState, FileIndex
    rules.py           # RulesEngine, update actions
    cli.py             # remora-index entry point

  dashboard/
    __init__.py
    app.py             # Starlette application
    views.py           # datastar-py SSE views
    cli.py             # remora-dashboard entry point

  queries/             # .scm tree-sitter query files (unchanged)
    python/remora_core/{function,class,file}.scm
    markdown/remora_core/{section,file}.scm
    toml/remora_core/{table,file}.scm

agents/                # Agent bundles (rewritten per Idea 8)
  lint/        bundle.yaml + tools/*.pym
  docstring/   bundle.yaml + tools/*.pym
  test/        bundle.yaml + tools/*.pym
  sample_data/ bundle.yaml + tools/*.pym
  harness/     bundle.yaml + tools/*.pym
```

### Reduction

| Metric | Current | Proposed | Change |
|--------|---------|----------|--------|
| Python source files | ~50 | ~22 | -56% |
| Packages | 7 | 4 | -43% |
| Workspace abstractions | 3 | 1 (Cairn) | -67% |
| Event systems | 2 | 1 | -50% |
| Hub packages | 1 (mixed) | 2 (focused) | clearer |
| Discovery files | 5 | 1 | -80% |
| Context files | 5 | 1 | -80% |
| Interactive files | 2 | 0 (absorbed into events) | -100% |

### Rationale for Each Merge/Split

- **`hub/` → `indexer/` + `dashboard/`**: Split because they're independent programs (Idea 3)
- **`discovery/` → `discovery.py`**: Consolidate because all 5 files are one cohesive concern (Idea 9)
- **`context/` → `context.py`**: Consolidate because 5 files reduced to one subscriber (Idea 6)
- **`interactive/` → absorbed into `events.py` + `event_bus.py`**: IPC via events, not files (Idea 7)
- **`workspace.py` → `workspace.py` (rewritten)**: Thin Cairn wrappers replace 3 abstractions (Idea 1)
- **`agent_graph.py` → `graph.py` + `executor.py`**: Separate topology from execution (Idea 4)
- **`agent_state.py` + `backend.py` + `constants.py` + `client.py`**: Eliminated — functionality absorbed into executor, bundles, config
- **`frontend/`**: Absorbed into `dashboard/` — it was dashboard state/registry code

---

## Risk Assessment

| Idea | Risk Level | Risk Description | Mitigation |
|------|-----------|------------------|------------|
| 1. Cairn as workspace | Low | Cairn becomes a hard dependency | It's already effectively required; making it explicit is honest |
| 2. Agent.from_bundle() | Low | Coupled to structured-agents bundle format | Bundle format is a stable public API; better than coupling to internals |
| 3. Split Hub | Medium | Two processes to deploy | They were already independent; explicit separation prevents future coupling |
| 4. Flatten AgentGraph | Low | External state tracking | dict[str, AgentState] is simpler than mutable god object |
| 5. Unified events | Medium | Remora event types become public API | Forces intentional design; better than ad-hoc string events |
| 6. Simplify context | Low | Tighter coupling to structured-agents events | Events are frozen dataclasses — stable contracts |
| 7. Event-based IPC | Medium | EventBus gains state (wait_for futures) | Well-understood async pattern; vastly better than broken file polling |
| 8. Pure function scripts | Medium | DataProvider must anticipate all data needs | Knowable from script purpose + target node; failures are DataProvider bugs |
| 9. Consolidate discovery | Low | Less granular git blame | Discovery is stable; files always changed together |
| 10. Flatten config | Low | Two config files | Different audiences (operator vs agent author) |
| 11. Cairn checkpoints | Low | Old checkpoints not loadable | Clean break — no backwards compatibility expected |

**Highest-risk items** are 3 (Hub split), 7 (event-based IPC), and 8 (pure function scripts). These are also the items that fix the most broken parts of the current architecture. The risk is in the rewrite complexity, not in the design — the proposed designs are simpler than what they replace.

---

## What Does NOT Change

- **Tree-sitter as the discovery engine** — .scm queries, multi-language support, CSTNode as the canonical type
- **Grail as the script runtime** — .pym scripts in Monty sandbox, Input/external declarations
- **Cairn as the execution sandbox** — CoW isolation, accept/reject gates (now also the workspace layer)
- **fsdantic as the index store** — TypedKVRepository, VersionedKVRecord for NodeState
- **structured-agents as the kernel** — grammar-constrained LLM tool orchestration loop
- **Agent graph as dependency DAG** — discover nodes → map to bundles → execute in order
- **Two-Track Memory concept** — Short Track rolling context + Long Track full history
- **Starlette + datastar for dashboard** — SSE-powered web UI
- **Async-first** — everything remains async (with sync wrappers where needed for CLI)
- **The five agent bundles** — lint, docstring, test, sample_data, harness (scripts rewritten, bundles restructured)

The refactor changes how the pieces are organized and connected, not what the pieces do.

---

## Recommended Implementation Order

### Phase 1: Foundation (No Dependencies Between Items)

1. **`events.py` + `event_bus.py`** — Define the unified event types and EventBus with `emit()`, `subscribe()`, `stream()`, `wait_for()`. This is the nervous system everything else plugs into. Test with unit tests only.

2. **`discovery.py`** — Consolidate the 5 discovery files into one. This is mostly moving code, not rewriting it. Existing tree-sitter logic is solid. Test against real source files.

3. **`config.py`** — New `RemoraConfig` frozen dataclass with `load_config()`. Simple data parsing with no dependencies on other new modules.

### Phase 2: Core (Depends on Phase 1)

4. **`workspace.py`** — `CairnDataProvider` and `CairnResultHandler`. Thin wrappers around Cairn's workspace API. Depends on Cairn being available. Test with Cairn workspace fixtures.

5. **`graph.py`** — `AgentNode` frozen dataclass, `build_graph()` function. Pure data transformation: CSTNodes + bundle mapping → list of AgentNodes with dependency edges. Test with fixtures.

6. **`context.py`** — `ContextBuilder` as EventBus subscriber. Depends on event types from Phase 1. Test by emitting events and checking built context.

### Phase 3: Execution (Depends on Phase 2)

7. **`executor.py`** — `GraphExecutor` with dependency ordering, concurrency, error policies. Calls `Agent.from_bundle()` for each node. Depends on graph, workspace, events. This is the integration point. Test with mock agents first, then real bundles.

8. **`checkpoint.py`** — Cairn-native checkpointing. Depends on executor state model and Cairn workspace snapshots.

### Phase 4: Agents (Depends on Phase 3)

9. **Rewrite .pym scripts** — Convert all 22 scripts to pure-function style (virtual FS in, structured result out). Write corresponding `DataProvider` and `ResultHandler` implementations per bundle. Each bundle is independently testable.

10. **Update bundle.yaml files** — Align to structured-agents v0.3 format with Remora extensions.

### Phase 5: Services (Independent, Can Parallelize)

11. **`indexer/`** — Extract from current `hub/`, keeping daemon, store, models, rules. Wire to new event types. Test independently.

12. **`dashboard/`** — Extract from current `hub/`, thin Starlette app. Reads from indexer store, subscribes to EventBus for SSE, triggers GraphExecutor for runs. Test independently.

13. **`cli.py`** — Rewrite CLI entry points: `remora` (main), `remora-index`, `remora-dashboard`.

### Phase 6: Integration

14. **End-to-end testing** — Full pipeline: discover → build graph → execute → check results. Human-in-the-loop testing with dashboard.

15. **Cleanup** — Remove all old code, update pyproject.toml, update entry points.

---

## The Acid Test

Can a new developer understand Remora's architecture in 15 minutes? With the proposed design:

1. Read `discovery.py` — see how source code becomes CSTNodes
2. Read `graph.py` — see how CSTNodes become an agent DAG
3. Read `executor.py` — see how agents run in dependency order via structured-agents
4. Read `workspace.py` — see how Cairn provides data to scripts and receives results
5. Read `event_bus.py` — see how everything communicates

Five files. That's the whole system. The indexer and dashboard are independent services that plug in via the event bus and store.
