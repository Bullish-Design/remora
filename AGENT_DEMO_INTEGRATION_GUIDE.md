# REMORA HUB AGENT INTEGRATION GUIDE

> **Goal:** Wire the Hub Server to execute real Remora agents instead of fake demo agents
> 
> **Prerequisites:** Phase 1 implementation complete (Hub server with SSE, workspace KV, coordinator)

---

## Architecture Overview

### The User Interaction Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AGENT EXECUTION WITH USER INPUT                     │
└─────────────────────────────────────────────────────────────────────────────┘

1. Graph Execution Starts
   └─→ Hub receives POST /graph/execute with graph_id
   └─→ Creates GraphWorkspace
   └─→ Registers agents with WorkspaceRegistry
   └─→ Starts WorkspaceInboxCoordinator watchers
   └─→ Publishes Event.agent_started for each agent

2. Agent Runs and Needs User Input
   └─→ Agent calls ask_user(question) in a .pym tool
   └─→ ask_user() writes to workspace.kv:
       key: "outbox:question:{msg_id}"
       value: {"question": "...", "options": [...], "status": "pending"}
   └─→ ask_user() polls workspace.kv:
       key: "inbox:response:{msg_id}"

3. Coordinator Detects Blocked Agent
   └─→ WorkspaceInboxCoordinator polls workspace.kv.list("outbox:question:")
   └─→ Finds pending questions
   └─→ Publishes Event.agent_blocked(agent_id, question, msg_id)

4. Hub Updates Frontend via SSE
   └─→ HubState.record() processes the event
   └─→ /subscribe endpoint sends SSE.patch_elements with updated view
   └─→ Frontend displays blocked agent card with response form

5. User Responds
   └─→ User fills form and clicks Send
   └─→ POST /agent/{agent_id}/respond with {question, answer, msg_id}
   └─→ Hub calls WorkspaceInboxCoordinator.respond()
   └─→ Writes to workspace.kv:
       key: "inbox:response:{msg_id}"
       value: {"answer": "...", "responded_at": "..."}
   └─→ Publishes Event.agent_resumed

6. Agent Resumes
   └─→ ask_user() polling finds response
   └─→ Returns the answer to the agent
   └─→ Agent continues execution
   └─→ Eventually publishes Event.agent_completed

7. Final State
   └─→ HubState records completion
   └─→ Frontend updates via SSE
```

---

## Step-by-Step Implementation Guide

### Step 1: Understand the Core Components

Before implementing, understand these key components that already exist:

#### 1.1 Event Bus (`remora/event_bus.py`)

```python
# Key classes:
- Event: Pydantic model for all events
  - category: "agent" | "tool" | "model" | "user" | "graph"
  - action: str (e.g., "started", "blocked", "resumed", "completed")
  - agent_id: str | None
  - graph_id: str | None
  - payload: dict[str, Any]
  
- EventBus: Central event system
  - await event_bus.publish(event)
  - await event_bus.subscribe("agent:*", handler)  # pattern matching
  - event_bus.stream()  # async iterator for SSE

# Convenience constructors:
Event.agent_started(agent_id="...", name="...", workspace_id="...")
Event.agent_blocked(agent_id="...", question="...", options=[...], msg_id="...")
Event.agent_resumed(agent_id="...", answer="...", msg_id="...")
Event.agent_completed(agent_id="...", result="...")
```

#### 1.2 Workspace (`remora/workspace.py`)

```python
# Key classes:
- GraphWorkspace: Workspace spanning an entire agent graph
  - id: str
  - root: Path
  - .kv: WorkspaceKV  # Key-value store for IPC
  - .agent_space(agent_id): Path  # Per-agent directory
  - .shared_space(): Path  # Shared directory

- WorkspaceKV: KV store for agent↔frontend IPC
  - await kv.set(key, value)      # Set a value
  - await kv.get(key)             # Get a value
  - await kv.list(prefix="...")   # List keys with prefix
  - await kv.delete(key)          # Delete a key
  
# Key patterns:
# - outbox:question:{msg_id} - Agent asking user
# - inbox:response:{msg_id}  - User's response

- WorkspaceManager: Manages multiple workspaces
  - await manager.create(id): GraphWorkspace
  - manager.get(id): GraphWorkspace | None
```

#### 1.3 Interactive Coordinator (`remora/interactive/coordinator.py`)

```python
# Key class:
class WorkspaceInboxCoordinator:
    """Watches workspace KV stores for agent questions and writes responses."""
    
    def __init__(self, event_bus: EventBus, poll_interval: float = 0.5):
    
    # Start watching a workspace for outbox questions
    async def watch_workspace(self, agent_id: str, workspace: GraphWorkspace):
        """Starts polling this workspace for questions."""
        
    # Write user response - this unblocks the agent!
    async def respond(self, agent_id: str, msg_id: str, answer: str, workspace: GraphWorkspace):
        """Write response to workspace KV and publish agent_resumed event."""
        
    # Stop watching
    async def stop_watching(self, agent_id: str):
```

#### 1.4 ask_user External (`remora/interactive/externals.py`)

```python
# This is called from within agent tools (.pym files)

def ask_user(
    question: str,
    options: list[str] | None = None,
    timeout: float = 300.0,
    poll_interval: float = 0.5,
) -> str:
    """
    Ask the user a question and wait for their response.
    
    Uses workspace KV store as communication mechanism:
    1. Writes to outbox:question:{msg_id}
    2. Polls inbox:response:{msg_id} until response arrives
    
    Returns:
        The user's response string
        
    Raises:
        TimeoutError: If user doesn't respond within timeout
    """
```

#### 1.5 Agent Graph (`remora/agent_graph.py`)

```python
# Key classes:

@dataclass
class AgentInbox:
    """Inbox for user interaction - handles agent blocking."""
    
    blocked: bool = False
    blocked_question: str | None = None
    
    async def ask_user(self, question: str, timeout: float = 300.0) -> str:
        """Block and wait for user response."""
        
    async def send_message(self, message: str) -> None:
        """Queue a message for the agent."""
        
    async def resolve_response_async(self, response: str) -> bool:
        """Called by UI to resolve blocked ask_user."""


@dataclass  
class AgentNode:
    """An agent in the graph."""
    
    id: str
    name: str
    bundle: str          # Bundle name (e.g., "lint", "docstring")
    target: str          # Code to operate on
    target_path: Path | None
    target_type: str
    
    state: AgentState    # PENDING, RUNNING, BLOCKED, COMPLETED, FAILED
    inbox: AgentInbox    # For user interaction
    workspace: Any        # GraphWorkspace
    result: Any          # Result when completed


class AgentGraph:
    """Declarative graph of agents."""
    
    def agent(self, name: str, bundle: str, target: str, ...) -> AgentGraph:
        """Add an agent to the graph."""
        
    def execute(self, config: GraphConfig | None = None) -> GraphExecutor:
        """Execute the graph and return an executor."""
        
    def on_blocked(self, handler: Callable[[AgentNode, str], Awaitable[str]]) -> AgentGraph:
        """Set handler for when agent asks user a question."""
```

#### 1.6 Workspace Registry (`remora/frontend/registry.py`)

```python
class WorkspaceRegistry:
    """Maps agent_ids to their workspaces."""
    
    async def register(self, agent_id: str, workspace_id: str, workspace: GraphWorkspace):
        """Register a workspace for an agent."""
        
    def get_workspace(self, agent_id: str) -> GraphWorkspace | None:
        """Get the workspace for an agent."""
        
workspace_registry = WorkspaceRegistry()  # Global singleton
```

---

### Step 2: Modify HubServer.execute_graph()

The key change is in `remora/hub/server.py`. Replace the demo agents with real graph execution.

#### 2.1 Current Fake Implementation

```python
# Current (fake) implementation:
async def execute_graph(self, request: Request) -> JSONResponse:
    signals = await read_signals(request) or {}
    graph_id = signals.get("graph_id", "")
    
    workspace = await self._workspace_manager.create(graph_id)
    
    # FAKE demo agents - replace this!
    demo_agents = [
        {"id": "root-1", "name": "Root Analyzer", "parent": None},
        {"id": "root-2", "name": "Root Validator", "parent": None},
        {"id": "branch-a", "name": "Branch A", "parent": "root-1"},
        {"id": "leaf-a1", "name": "Leaf A1", "parent": "branch-a"},
    ]
    
    for agent in demo_agents:
        agent_id = agent["id"]
        await workspace_registry.register(agent_id, workspace.id, workspace)
        await self._coordinator.watch_workspace(agent_id, workspace)
        await self._event_bus.publish(Event.agent_started(...))
    
    return JSONResponse({...})
```

#### 2.2 Real Implementation Pattern

```python
async def execute_graph(self, request: Request) -> JSONResponse:
    signals = await read_signals(request) or {}
    graph_id = signals.get("graph_id", "")
    
    if not graph_id:
        return JSONResponse({"error": "graph_id required"}, status_code=400)
    
    # Step 1: Create workspace for this graph
    workspace = await self._workspace_manager.create(graph_id)
    
    # Step 2: Load remora config (from remora.yaml or default)
    config = self._load_config()
    
    # Step 3: Discover code structure OR load from config
    # Option A: Use discovery to find nodes
    # nodes = self._discover_nodes(config)
    
    # Option B: Use config-defined operations
    nodes = [{"name": "example", "text": "code..."}]  # Placeholder
    
    # Step 4: Build AgentGraph with real agents
    graph = self._build_agent_graph(graph_id, workspace, config, nodes)
    
    # Step 5: Register all agents with workspace registry
    for agent_id, agent in graph.agents().items():
        await workspace_registry.register(agent_id, workspace.id, workspace)
        await self._coordinator.watch_workspace(agent_id, workspace)
    
    # Step 6: Execute graph in background (don't await!)
    asyncio.create_task(self._execute_graph_async(graph, config))
    
    return JSONResponse({
        "status": "started",
        "graph_id": graph_id,
        "agents": len(graph.agents()),
        "workspace": workspace.id,
    })


async def _execute_graph_async(self, graph: AgentGraph, config: GraphConfig):
    """Execute the graph and publish events."""
    try:
        executor = graph.execute(config=config)
        await executor.run()
    except Exception as e:
        # Publish error event
        await self._event_bus.publish(Event.agent_failed(
            agent_id="graph",
            error=str(e)
        ))
```

---

### Step 3: Implement Agent Graph Execution

The `AgentGraph.execute()` returns a `GraphExecutor` that runs agents. You need to implement actual agent execution in the executor.

#### 3.1 The Missing Piece: Real Agent Execution

In `remora/agent_graph.py`, the current `GraphExecutor._run_agent()` is incomplete:

```python
# Current (incomplete) implementation:
async def _run_agent(self, name: str) -> None:
    agent = self._graph[name]
    
    async with self._semaphore:
        await self._event_bus.publish(
            Event.agent_started(agent_id=agent.id, graph_id=self._graph.id, name=name, bundle=agent.bundle)
        )
        
        # THIS IS WHERE REAL EXECUTION NEEDS TO HAPPEN
        # Currently just marks as complete!
        agent.state = AgentState.COMPLETED
        
        await self._event_bus.publish(Event.agent_completed(agent_id=agent.id, graph_id=self._graph.id, name=name))
```

#### 3.2 Implement Real Execution

```python
async def _run_agent(self, name: str) -> None:
    """Run a single agent with real execution."""
    agent = self._graph[name]
    
    async with self._semaphore:
        await self._event_bus.publish(
            Event.agent_started(
                agent_id=agent.id, 
                graph_id=self._graph.id, 
                name=name, 
                bundle=agent.bundle
            )
        )
        
        try:
            # Step 1: Set workspace context for ask_user
            self._set_workspace_context(agent.workspace)
            
            # Step 2: Load the bundle (tool definition)
            bundle = self._load_bundle(agent.bundle)
            
            # Step 3: Execute the agent with the kernel
            result = await self._execute_agent_kernel(
                agent=agent,
                bundle=bundle,
                config=self._config,
            )
            
            # Step 4: Handle result
            agent.result = result
            agent.state = AgentState.COMPLETED
            
            await self._event_bus.publish(
                Event.agent_completed(
                    agent_id=agent.id,
                    graph_id=self._graph.id,
                    name=name,
                    result=str(result),
                )
            )
            
        except Exception as e:
            agent.state = AgentState.FAILED
            agent.error = str(e)
            
            await self._event_bus.publish(
                Event.agent_failed(
                    agent_id=agent.id,
                    graph_id=self._graph.id,
                    name=name,
                    error=str(e),
                )
            )


def _set_workspace_context(self, workspace: GraphWorkspace):
    """Set the workspace context var so ask_user works in subprocess."""
    import contextvars
    _workspace_var: contextvars.ContextVar = contextvars.ContextVar("workspace", default=None)
    _workspace_var.set(workspace)


async def _execute_agent_kernel(
    self,
    agent: AgentNode,
    bundle: Any,
    config: GraphConfig,
) -> Any:
    """
    Execute the agent using the structured-agents kernel.
    
    This is where you'd integrate with:
    - KernelRunner (from deprecated/, but pattern is clear)
    - Or direct structured-agents API
    
    The key is that the agent's tools can call ask_user(),
    which uses the workspace KV for IPC.
    """
    # This is placeholder - integrate with actual kernel
    # The pattern from KernelRunner shows:
    # 1. Create kernel with bundle and config
    # 2. Run with workspace context
    # 3. Return result
    
    # For now, simulate execution
    await asyncio.sleep(0.1)  # Placeholder
    
    # If agent asks user, it will:
    # 1. Call ask_user(question) 
    # 2. ask_user writes to workspace.kv
    # 3. Coordinator detects, publishes event
    # 4. Frontend shows form, user responds
    # 5. Coordinator writes response to workspace.kv
    # 6. ask_user returns answer
    
    return {"status": "completed", "output": "..."}
```

---

### Step 4: Ensure ask_user Works in Agent Context

The `ask_user` function in `remora/interactive/externals.py` uses a context variable for the workspace. You must ensure this is set before the agent runs.

#### 4.1 How ask_user Gets the Workspace

```python
# From remora/interactive/externals.py:

def _get_current_workspace() -> Any:
    """Get the current workspace from context."""
    import contextvars
    _workspace: contextvars.ContextVar[Any] = contextvars.ContextVar("workspace")
    ws = _workspace.get(None)
    if ws is None:
        raise RuntimeError("ask_user called outside workspace context")
    return ws
```

#### 4.2 Setting the Context Before Execution

```python
# In GraphExecutor or wherever you run the agent:

import contextvars

# Define the context var at module level
_workspace_var: contextvars.ContextVar[Any] = contextvars.ContextVar("workspace", default=None)


async def _run_agent(self, name: str) -> None:
    agent = self._graph[name]
    
    # SET THE CONTEXT BEFORE RUNNING
    _workspace_var.set(agent.workspace)
    
    try:
        # Now ask_user() will work
        result = await self._execute_agent_kernel(agent, bundle, config)
    finally:
        # Clear after execution
        _workspace_var.set(None)
```

---

### Step 5: Handle Graph Dependencies

If agents have dependencies (one must complete before another starts), handle this in execution.

#### 5.1 Current Simple Implementation

```python
# From agent_graph.py - current simple batching:
def _build_execution_batches(self) -> list[list[str]]:
    """Build batches of agents that can run in parallel."""
    if self._graph._parallel_groups:
        return self._graph._parallel_groups
    # Default: all agents in one batch (run in parallel)
    return [list(self._graph.agents().keys())]
```

#### 5.2 Dependency-Aware Implementation

```python
async def run(self) -> dict[str, Any]:
    """Execute all agents respecting dependencies."""
    batches = self._build_execution_batches()
    
    completed = set()
    
    for batch in batches:
        # Wait for all agents in this batch to complete
        tasks = [
            asyncio.create_task(self._run_agent(name, completed))
            for name in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Add completed agents to the set
        for name, result in zip(batch, results):
            if not isinstance(result, Exception):
                completed.add(name)
        
        # Check error policy
        if self._config.error_policy == ErrorPolicy.STOP_GRAPH:
            has_error = any(isinstance(r, Exception) for r in results)
            if has_error:
                break
    
    return {name: agent.result for name, agent in self._graph.agents().items()}


async def _run_agent(self, name: str, completed: set[str]) -> None:
    """Run a single agent after waiting for dependencies."""
    agent = self._graph[name]
    
    # Wait for upstream dependencies
    while agent.upstream and not all(up in completed for up in agent.upstream):
        await asyncio.sleep(0.1)
    
    # Now run the agent
    await self._execute_agent(agent)
```

---

### Step 6: End-to-End Testing Checklist

Once implemented, verify the complete flow:

- [ ] Hub starts on Python 3.10+
- [ ] POST /graph/execute triggers agent discovery
- [ ] Agents appear in HubState.agent_states
- [ ] Events stream via SSE to /subscribe
- [ ] Agent calls ask_user() → writes to workspace.kv
- [ ] Coordinator detects blocked question
- [ ] Event.agent_blocked published
- [ ] Frontend shows blocked agent card
- [ ] User submits response via form
- [ ] POST /agent/{agent_id}/respond called
- [ ] Coordinator writes to workspace.kv inbox
- [ ] Event.agent_resumed published
- [ ] ask_user() returns with answer
- [ ] Agent completes execution
- [ ] Event.agent_completed published
- [ ] Results appear in dashboard

---

## Key Integration Points Summary

| Component | File | What to Do |
|-----------|------|------------|
| Execute Graph | `remora/hub/server.py` | Replace demo agents with real `AgentGraph` creation |
| Graph Execution | `remora/agent_graph.py` | Implement `_run_agent()` to actually run the kernel |
| Workspace Context | `remora/agent_graph.py` | Set `_workspace_var` before running agent |
| Config Loading | `remora/hub/server.py` | Load `remora.yaml` or default config |
| Discovery | `remora/hub/server.py` | Use `TreeSitterDiscoverer` to find code nodes |

---

## References

- `remora/event_bus.py` - Event system
- `remora/workspace.py` - Workspace and KV store
- `remora/interactive/coordinator.py` - Coordinator for user responses
- `remora/interactive/externals.py` - `ask_user()` implementation
- `remora/frontend/registry.py` - Agent→Workspace mapping
- `remora/agent_graph.py` - AgentGraph and AgentNode
