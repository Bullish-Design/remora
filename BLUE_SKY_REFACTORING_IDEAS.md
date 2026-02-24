# Blue Sky Refactoring Ideas: Unified Interactive Agent Graph

> A radical reimagining of Remora's architecture to make interactive, graph-based agent workflows first-class citizens. This document captures "what if" ideas that could fundamentally simplify and unify the system.

---

## Executive Summary

After deep study of Remora and its underlying libraries (structured-agents, cairn, grail), I've identified opportunities for a **unified interactive agent graph** architecture that could dramatically simplify the system while adding powerful new capabilities.

**Key Insight**: The current architecture has three layers that could be unified:
1. **Remora** (orchestration, AST discovery)
2. **structured-agents** (single-agent kernel)
3. **cairn** (workspace management)

The interactive agent concept we're pursuing sits at the *intersection* of all three. By making it first-class, we can potentially eliminate layers of indirection.

---

## Part 1: Deep Analysis of Current Architecture

### The Stack Today

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Remora (this repo)                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Orchestrator    │ KernelRunner    │ ContextManager  │ EventBridge   │   │
│  │ (multi-agent)  │ (kernel wrap)  │ (short track)   │ (translation) │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Discovery (AST parsing, node discovery)                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────┴────────────────────────────────────────┐
│  structured-agents                                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ AgentKernel (single-agent loop)                                      │   │
│  │ - ToolSource (registry + backend)                                    │   │
│  │ - Observer (event hooks)                                            │   │
│  │ - ContextProvider (per-turn context)                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────┴────────────────────────────────────────┐
│  cairn + grail                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ GrailBackend (executes .pym in isolated processes)                  │   │
│  │ - Externals (filesystem, commands)                                  │   │
│  │ - Workspace (copy-on-write isolation)                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### What We Want: Interactive Agent Graph

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Interactive Agent Graph                              │
│                                                                             │
│    ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐            │
│    │ Agent A │────▶│ Agent B │────▶│ Agent C │────▶│ Agent D │            │
│    │ (lint)  │     │ (docstr)│     │ (types) │     │ (test)  │            │
│    └────┬────┘     └────┬────┘     └────┬────┘     └────┬────┘            │
│         │                │                │                │                  │
│         ▼                ▼                ▼                ▼                  │
│    ┌─────────────────────────────────────────────────────────┐              │
│    │              Shared Event Stream + Inbox                │◄── User Input │
│    └─────────────────────────────────────────────────────────┘              │
│                                                                             │
│    Each agent can:                                                          │
│    - Ask user questions (block and wait)                                   │
│    - Receive async messages from user                                      │
│    - Emit state changes to UI                                              │
│    - Pass results to downstream agents                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 2: Revolutionary Simplification Ideas

### Idea 1: Unify "Agent" and "Node" into a Single Concept

**Current State**:
- Remora has `CSTNode` (AST nodes from source code)
- Remora has `RemoraAgentContext` (agent run context)
- structured-agents has `AgentKernel` (the execution engine)

**The Problem**: Three different concepts of "a thing that runs"

**The Idea**: Unify into a single **`AgentNode`** concept that:
- Has identity (node_id, agent_id - they're the same)
- Has state (pending → running → blocked → completed)
- Has a inbox for user messages
- Can emit events
- Can be composed into graphs

```python
# The Unified AgentNode
@dataclass
class AgentNode:
    id: str                              # Same as node_id
    type: NodeType                       # AST type: function, class, etc.
    state: AgentState                    # pending, running, blocked, done
    source: str                          # The code this agent operates on
    
    # Inbox - the key innovation
    inbox: AgentInbox                    # User messages + blocking futures
    
    # Graph connections
    upstream: list[str]                  # Agent IDs that feed into this
    downstream: list[str]                # Agent IDs that consume this
    
    # Execution
    kernel: AgentKernel | None           # The structured-agents kernel
    result: AgentResult | None          # Final result when done
```

**Why This Matters**:
- Eliminates the mental mapping between AST nodes and agents
- Makes graph composition trivial (just link node IDs)
- The inbox is inherent to every agent, not an add-on

---

### Idea 2: Event Bus as the Single Source of Truth

**Current State**:
- Remora has `EventEmitter` (fire-and-forget JSONL)
- structured-agents has `Observer` (in-process callbacks)
- UI has to bridge between them

**The Problem**: Two separate event systems that don't talk to each other

**The Idea**: Make the **event bus** the central nervous system

```python
# The Unified Event Bus - single source of truth for everything
class EventBus:
    """One event bus to rule them all."""
    
    def __init__(self):
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers: dict[str, list[Callable]] = {}
    
    # Pub/Sub for any consumer
    async def publish(self, event: Event) -> None:
        await self._queue.put(event)
    
    async def subscribe(self, pattern: str, handler: Callable) -> None:
        """Pattern can be: "agent:*", "node:func_*", "state:blocked" """
        self._subscribers.setdefault(pattern, []).append(handler)
    
    # Built-in streams for different consumers
    def sse_stream(self) -> AsyncIterator[Event]:
        """For web dashboard SSE."""
        
    def ws_stream(self, agent_id: str) -> AsyncIterator[Event]:
        """For WebSocket subscriptions to specific agents."""
        
    def log_stream(self) -> AsyncIterator[Event]:
        """For JSONL file logging (backwards compat)."""
        
    def metrics_stream(self) -> AsyncIterator[Event]:
        """For Prometheus metrics."""
```

**Benefit**: Every component publishes to one bus, every consumer subscribes. No more "event bridge" translation layer.

---

### Idea 3: Make "Blocking for User Input" a First-Class Tool

**Current State**:
- We need to add `ask_user()` as an external function
- It needs special coordination to pause/resume
- It's not natively understood by structured-agents

**The Idea**: Make user interaction a **built-in tool** that's always available

```python
# In structured-agents or Remora, make this built-in:
TOOL_ASK_USER = {
    "name": "__ask_user__",
    "description": "Ask the user a question and wait for their response. "
                   "Use this when you need clarification or approval.",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question to ask"},
            "options": {
                "type": "array", 
                "items": {"type": "string"},
                "description": "Optional constrained choices"
            },
            "timeout_seconds": {"type": "number", "default": 300}
        },
        "required": ["question"]
    }
}
```

**Implementation**:
```python
class InteractiveToolBackend:
    """Backend that handles interactive tools natively."""
    
    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus
        self._pending_futures: dict[str, asyncio.Future] = {}
    
    async def execute(self, tool_call: ToolCall) -> ToolResult:
        if tool_call.name == "__ask_user__":
            return await self._handle_ask_user(tool_call)
        # ... handle other tools
    
    async def _handle_ask_user(self, tool_call: ToolCall) -> ToolResult:
        question = tool_call.arguments.get("question", "")
        options = tool_call.arguments.get("options")
        
        # Emit blocking event
        await self._event_bus.publish(Event(
            type="AGENT_BLOCKED",
            agent_id=tool_call.agent_id,
            payload={"question": question, "options": options}
        ))
        
        # Create future and wait
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_futures[tool_call.call_id] = future
        
        try:
            response = await asyncio.wait_for(
                future, 
                timeout=tool_call.arguments.get("timeout_seconds", 300)
            )
        except asyncio.TimeoutError:
            return ToolResult(
                call_id=tool_call.call_id,
                name="__ask_user__",
                output=json.dumps({"status": "timeout"}),
                is_error=True
            )
        
        return ToolResult(
            call_id=tool_call.call_id,
            name="__ask_user__",
            output=json.dumps({"status": "answered", "response": response}),
            is_error=False
        )
```

**Why This Matters**:
- No special code in externals - it's just another tool
- structured-agents handles the tool call/result flow naturally
- The UI just subscribes to `AGENT_BLOCKED` events
- Can add constraints/options for demo UI buttons

---

### Idea 4: Graph DSL for Agent Orchestration

**Current State**:
- Remora's orchestrator is imperative: iterate nodes, spawn agents
- Hard to express complex dependencies
- No first-class notion of "this agent depends on that agent"

**The Idea**: A tiny DSL to describe agent graphs

```python
# Define an agent graph declaratively
graph = AgentGraph("my-swarm")

# Add agents (automatically created from AST or manually)
graph.agent("lint", bundle="lint", target="{node}")
graph.agent("docstring", bundle="docstring", target="{node}")
graph.agent("types", bundle="type_hints", target="{node}")

# Define dependencies
graph.after("lint").run("docstring")  # docstring runs after lint
graph.after("docstring").run("types") # types runs after docstring

# Or in parallel groups
graph.group("analysis").run_parallel("lint", "docstring", "types")

# Add user interaction points
graph.agent("docstring").can_ask_user(
    "Which docstring format?",
    options=["google", "numpy", "sphinx"]
)

# Run the graph
results = await graph.execute(context={"node": my_ast_node})
```

**Why This Matters**:
- Declarative is easier to understand than imperative orchestration
- Makes "downstream" agents naturally receive upstream results
- User interaction points are explicit in the graph
- Can visualize the graph in the UI

---

### Idea 5: Persistent Agent State with Snapshots

**Current State**:
- Each agent run is a fresh process
- If something fails, you restart from scratch
- No way to "pause" an agent and resume later (across restarts)

**The Idea**: First-class snapshot support in the agent kernel

```python
# After every turn, optionally snapshot
@dataclass
class AgentSnapshot:
    agent_id: str
    turn: int
    messages: list[Message]
    tool_results: list[ToolResult]
    context: dict[str, Any]
    workspace_path: Path
    created_at: datetime

# The agent can be resumed from any snapshot
class ResumableAgent:
    """An agent that can pause and resume."""
    
    async def run(self, snapshot: AgentSnapshot | None = None) -> AgentResult:
        if snapshot:
            # Resume from snapshot
            return await self._resume(snapshot)
        else:
            # Fresh start
            return await self._run_fresh()
    
    async def snapshot(self) -> AgentSnapshot:
        """Create a snapshot of current state."""
        return AgentSnapshot(
            agent_id=self.agent_id,
            turn=self.current_turn,
            messages=self.messages.copy(),
            tool_results=self.tool_results.copy(),
            context=self.context.copy(),
            workspace_path=self.workspace.path,
            created_at=datetime.now()
        )
```

**Why This Matters**:
- Users can step away and come back
- Can implement "review before continuing"
- Enables true "human-in-the-loop" workflows
- Snapshots can be stored, shared, debugged

---

### Idea 6: Unified "Workspace" for Everything

**Current State**:
- cairn has its own workspace (copy-on-write)
- Remora creates separate workspaces per agent
- No sharing between agents unless explicitly merged

**The Idea**: One workspace per graph, shared intelligently

```python
@dataclass
class GraphWorkspace:
    """A workspace that spans an entire agent graph."""
    
    id: str
    root: Path
    
    # Each agent gets a private subdirectory
    def agent_space(self, agent_id: str) -> Path:
        return self.root / "agents" / agent_id
    
    # Shared space for passing artifacts between agents
    def shared_space(self) -> Path:
        return self.root / "shared"
    
    # Read-only snapshot of original source
    def original_source(self) -> Path:
        return self.root / "original"

# When running a graph
async def execute_graph(graph: AgentGraph, target: CSTNode) -> GraphResult:
    workspace = await GraphWorkspace.create(target.file_path)
    
    # All agents share the same workspace
    for agent in graph.agents:
        agent.workspace = workspace
    
    # Run the graph
    results = await graph.execute()
    
    # Merge changes back
    await workspace.merge()
    
    return results
```

**Why This Matters**:
- Simpler mental model (one workspace per task)
- Natural data sharing between agents
- Merge is explicit and auditable

---

## Part 3: The "Radical MVP" Approach

### What If We Started Over?

If we were to rebuild Remora from scratch with the interactive concept as the foundation, what would the minimal architecture look like?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           The Radical MVP                                   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     InteractiveGraph                                 │   │
│  │                                                                      │   │
│  │  1. Parse AST → AgentNode graph                                      │   │
│  │  2. For each node: spawn AgentKernel                                 │   │
│  │  3. Kernel has built-in __ask_user__ tool                            │   │
│  │  4. All events → EventBus                                            │   │
│  │  5. UI subscribes to EventBus via SSE                               │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           That's It.                                         │
│                                                                             │
│  Everything else (bundles, grail, cairn) is just configuration             │
│  of the kernel. The architecture is:                                        │
│                                                                             │
│     [AST] → [Graph] → [Kernel × N] → [EventBus] → [UI]                    │
│                                                                             │
│  Where:                                                                    │
│  - Graph = declarative agent dependencies                                  │
│  - Kernel = structured-agents with interactive tool                       │
│  - EventBus = single source of truth for all events                       │
│  - UI = any consumer (web, CLI, etc.)                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Migration Path from Current Code

| Current Component | New Component | What Changes |
|------------------|---------------|--------------|
| `Orchestrator` | `InteractiveGraph` | Declarative instead of imperative |
| `KernelRunner` | (embedded in Graph) | Simplified, no wrapper needed |
| `EventEmitter` + `EventBridge` | `EventBus` | Unified, async-native |
| `ContextManager` | (simplified) | Just provides context to kernel |
| Discovery | Same | AST parsing unchanged |

---

## Part 4: Specific Implementation Opportunities

### Opportunity 1: Add `__ask_user__` to structured-agents

Instead of adding it in Remora, contribute it to structured-agents as a built-in tool:

```python
# In structured-agents/tool_sources/
class InteractiveToolRegistry:
    """Registry that adds interactive tools."""
    
    BUILTIN_TOOLS = ["__ask_user__", "__get_user_messages__"]
    
    def resolve(self, name: str) -> ToolSchema | None:
        if name == "__ask_user__":
            return ToolSchema(
                name="__ask_user__",
                description="Ask the user a question...",
                parameters={...}
            )
        return None
```

**Benefit**: One implementation, works everywhere

### Opportunity 2: Make Observer Emit to Async Queue

The structured-agents Observer is in-process only. Add an adapter that emits to an async queue:

```python
class AsyncQueueObserver:
    """Observer that publishes to an async queue."""
    
    def __init__(self, queue: asyncio.Queue):
        self._queue = queue
    
    async def on_tool_result(self, event: ToolResultEvent) -> None:
        await self._queue.put(transform_to_unified_event(event))
```

**Benefit**: Events can flow to web UI without custom bridges

### Opportunity 3: Add Graph Visualization to Bundles

Bundles already have metadata. Add a tiny visualization spec:

```yaml
# agents/lint/bundle.yaml
name: lint
visualization:
  icon: "🔍"
  color: "#ff9900"
  description: "Find and fix lint errors"
  can_block: true  # This agent can ask user questions
```

**Benefit**: UI knows how to render each agent type

### Opportunity 4: Hot-Reload Bundles Without Restart

Currently bundles are loaded once. Make them watchable:

```python
class WatchableBundle:
    """Bundle that reloads when files change."""
    
    def __init__(self, path: Path):
        self._path = path
        self._bundle = load_bundle(path)
        self._watcher = Watcher(path, callback=self._on_change)
    
    def _on_change(self):
        self._bundle = load_bundle(self._path)  # Hot reload
        # Notify all waiting kernels
    
    @property
    def tool_schemas(self):
        return self._bundle.tool_schemas  # Always fresh
```

**Benefit**: Edit tools, see changes immediately

---

## Part 5: Summary of Key Changes Needed

To make this concept truly elegant, here are the concrete changes:

### Changes to Remora

1. **Replace Orchestrator with InteractiveGraph**
   - New class: `AgentGraph` with declarative dependency syntax
   - Removed: imperative node iteration

2. **Unified Event Bus**
   - New class: `UnifiedEventBus` (replaces EventEmitter + EventBridge)
   - All events flow through one system

3. **Remove KernelRunner wrapper**
   - Instead: Graph spawns kernels directly
   - Simplified: no more wrapper class

### Changes to structured-agents (Contribute back)

1. **Built-in `__ask_user__` tool**
   - Added to `ToolRegistry`
   - Handled by a new `InteractiveBackend`

2. **Async Queue Observer**
   - New observer that publishes to `asyncio.Queue`
   - Enables SSE without custom bridges

3. **Snapshot/Resume support**
   - Kernel can serialize/deserialize state

### Changes to UI

1. **Event-driven from ground up**
   - UI just subscribes to EventBus
   - No polling, no custom bridges

2. **Graph visualization**
   - Show agent dependencies
   - Show state flow

---

## Conclusion

The current Remora architecture is a successful layering of abstractions. But for the interactive agent concept to be truly elegant, we should consider:

1. **Unify** the multiple "agent" concepts into one (`AgentNode`)
2. **Centralize** events into one bus (`EventBus`)
3. **Simplify** orchestration into graphs (`AgentGraph`)
4. **Standardize** user interaction as a tool (`__ask_user__`)
5. **Enable** persistence for human-in-the-loop (`Snapshots`)

The result would be a system where:
- Agents are naturally composable into graphs
- User interaction is built-in, not an add-on
- UI is just another event consumer
- The mental model is simple: **graph → kernels → events → UI**

This is achievable incrementally by:
1. Adding `__ask_user__` to structured-agents first
2. Creating the UnifiedEventBus in Remora
3. Building InteractiveGraph as a new orchestrator
4. Adding the web UI as an event consumer

The concept is sound. The architecture is the main constraint to address.
