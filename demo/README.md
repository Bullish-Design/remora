# Remora Multi-Agent HTTP Demo

A live demonstration of Remora's full-stack agentic code automation capabilities over HTTP, showcasing how multiple distinct agent bundles can be invoked through a unified REST API.

## Quick Start

### Prerequisites

1. **vLLM Server** (for local model inference):
   ```bash
   vllm serve Qwen/Qwen3-4B-Instruct-2507-FP8 --dtype half --port 8000
   ```

2. **Install Dependencies**:
   ```bash
   uv pip install -e ".[frontend,backend]"
   uv pip install httpx httpx-sse
   ```

### Run the Demo

**Terminal 1** - Setup demo files:
```bash
cd demo
python setup_demo.py
```

**Terminal 2** - Start Hub Server:
```bash
cd demo
python start_server.py
```

**Terminal 3** - Run HTTP client:
```bash
cd demo
python api_demo.py
```

> **Note:** After making code changes to the server (e.g., the bundle path fix), restart the server in Terminal 2.

> **Current Status:** The demo demonstrates the full HTTP/SSE architecture. The actual bundle execution (running real grail scripts) requires the bundles to be properly registered with `bundle.yaml` files. Currently, the system falls back to a simulated execution that demonstrates the event flow without executing actual grail scripts.

---

# Understanding Remora

## The Problem

Software development teams face a fundamental bottleneck: **repetitive, mechanical tasks** that consume developer time but require minimal creativity. Code reviews, linting, docstring writing, test generation—these are necessary but tedious. Traditional automation tools are too rigid. LLMs are too expensive and unpredictable for autonomous execution at scale.

**What if you could have AI agents that reliably execute well-defined code automation tasks, with full auditability, at a fraction of the cost of general-purpose AI assistants?**

## What is Remora?

Remora is a **structured multi-agent orchestration framework** designed for reliable, observable, and composable code automation. It combines:

- **Graph-based agent execution** — Tasks are modeled as directed graphs where nodes represent agents and edges represent data flow and dependencies
- **Bundle-based skill system** — Agent capabilities are packaged as "bundles" (Grail scripts) that can be mixed, matched, and swapped at runtime
- **Event-driven architecture** — Real-time streaming of agent activities via Server-Sent Events (SSE) for complete observability
- **HTTP-native design** — Every agent execution is triggered via REST API, making integration with existing CI/CD pipelines trivial

---

# Deep Dive: The Remora Architecture

This section explains how Remora actually works under the hood.

## 1. AgentGraph: Declarative Agent Composition

At the core of Remora is the `AgentGraph` class (`src/remora/agent_graph.py`). Instead of imperatively orchestrating agents, you **declare** what you want:

```python
graph = AgentGraph()

# Add agents - each represents a unit of work
graph.agent("lint", bundle="run_linter", target=source_code)
graph.agent("docstring", bundle="write_docstring", target=source_code)

# Define execution order
graph.after("lint").run("docstring")

# Execute with configuration
config = GraphConfig(
    max_concurrency=4,
    interactive=True,
    timeout=300.0,
    error_policy=ErrorPolicy.STOP_GRAPH
)
executor = graph.execute(config=config)
await executor.run()
```

The graph model provides several key guarantees:

- **Deterministic execution order**: Dependencies are explicitly defined via `.after()` or implicit through discovery
- **Parallel execution**: Independent agents run concurrently (controlled by `max_concurrency`)
- **Error handling**: Configurable policies (`STOP_GRAPH`, `SKIP_DOWNSTREAM`, `CONTINUE`) determine failure behavior

### AgentNode: The Unit of Work

Each agent in the graph is an `AgentNode` — a unified concept that replaces scattered previous abstractions (CSTNode, RemoraAgentContext, KernelRunner):

```python
@dataclass
class AgentNode:
    id: str              # Unique identifier
    name: str            # Human-readable name
    target: str          # Code/text to operate on
    target_path: Path    # File path (if applicable)
    target_type: str     # "function", "class", "module", etc.
    
    state: AgentState    # PENDING → QUEUED → RUNNING → BLOCKED → COMPLETED/FAILED
    bundle: str          # Which bundle provides this agent's capabilities
    
    inbox: AgentInbox    # For human-in-the-loop interaction
    workspace: Any       # Sandboxed execution environment
    
    upstream: list[str]  # Agent IDs that must complete first
    downstream: list[str]# Agents that depend on this one
```

## 2. The Bundle System: Grail Scripts

Bundles are the **skill packages** that give agents their capabilities. Each bundle lives in `.grail/agents/<bundle_name>/` and contains:

- **`monty_code.py`** — The main execution logic (async Python)
- **`inputs.json`** — Input parameter definitions with types
- **`externals.json`** — External dependencies (commands, files)
- **`check.json`** — Validation rules

### Example: The `run_linter` Bundle

Looking at `.grail/agents/run_linter/`:

**inputs.json** defines what parameters the bundle accepts:
```json
{
  "inputs": [
    {"name": "check_only", "type": "bool", "required": false, "default": true},
    {"name": "target_file_input", "type": "str | None", "required": true}
  ]
}
```

**monty_code.py** contains the actual logic:
```python
# Simplified view of what runs
command_args = ['ruff', 'check', '--output-format', 'json']
if not check_only:
    command_args.append('--fix')
command_args.append(target_file)

completed = await run_command(cmd='ruff', args=command_args)
# Parse JSON output, extract issues, return structured result
```

The bundle returns a **structured result**:
```python
{
    "result": {
        "issues": [{"code": "F401", "line": 3, "message": "unused import"}],
        "total": 1,
        "fixable_count": 1
    },
    "summary": "Found 1 lint error, 1 fixable",
    "outcome": "partial"
}
```

This structured output is critical: it allows downstream agents to consume the results programmatically. The `apply_fix` bundle can take the linter's output and actually fix the issues.

### Bundle Discovery

Bundles are discovered dynamically via the discovery system. The `AgentGraph.discover()` method:

1. Scans code files using TreeSitter for AST parsing
2. Identifies "nodes" (functions, classes, modules)
3. Maps node types to bundles via configuration
4. Creates AgentNodes automatically

```python
graph = AgentGraph()
graph.discover(
    root_dirs=[Path("src/")],
    bundles={"function": "run_linter", "class": "write_docstring"},
    query_pack="remora_core"
)
```

## 3. The Event Bus: Observable Execution

Every component in Remora publishes events to a central `EventBus` (`src/remora/event_bus.py`). This is the "central nervous system" that enables:

- Real-time UI updates
- Logging and debugging
- Metrics collection
- External system integration

### Event Schema

All events follow a consistent schema:

```python
class Event(BaseModel):
    id: str              # Unique event ID
    timestamp: datetime # When it occurred
    
    category: Literal["agent", "tool", "model", "user", "graph"]
    action: str          # What happened (e.g., "started", "completed")
    
    agent_id: str | None    # Associated agent (if any)
    graph_id: str | None    # Associated graph (if any)
    
    payload: dict[str, Any]  # Additional data
```

### Event Types

| Category | Actions | Description |
|----------|---------|-------------|
| `agent` | started, blocked, resumed, completed, failed, cancelled | Agent lifecycle |
| `tool` | called, started, completed, failed | Tool invocations |
| `model` | request, response | LLM API calls |
| `graph` | started, progress, completed, failed | Graph execution |
| `user` | message | User interactions |

### SSE Streaming

The Hub Server exposes `/subscribe` as a Server-Sent Events (SSE) endpoint. Clients connect once and receive a continuous stream:

```
event: agent:started
data: {"agent_id": "lint-abc123", "bundle": "run_linter", ...}

event: tool:called
data: {"tool": "run_command", "cmd": "ruff", "args": [...]}

event: agent:completed
data: {"agent_id": "lint-abc123", "result": {...}}

event: graph:completed
data: {"graph_id": "xyz789", "agents_completed": 2}
```

This is what `api_demo.py` listens to — enabling real-time progress tracking.

## 4. Workspace Isolation

Each agent execution runs in a **sandboxed workspace** (`src/remora/workspace.py`). This provides:

- **File isolation**: Agents can't accidentally modify files outside their workspace
- **State persistence**: Workspace persists between agent runs
- **KV store**: Key-value IPC for agent ↔ frontend communication

### WorkspaceKV

Workspaces include a KV store for structured communication:

```python
# Agent writes a question for the user
await workspace.kv.set("outbox:question:123", {
    "question": "Should I apply this fix?",
    "options": ["Yes", "No", "Show me more"]
})

# Frontend reads and responds
response = await workspace.kv.get("inbox:response:123")

# List all pending questions
questions = await workspace.kv.list("outbox:question:")
```

Key patterns:
- `outbox:question:*` — Agent asking user
- `inbox:response:*` — User's answer
- `agent:*:state` — Agent state snapshots

## 5. The Hub Server: HTTP-Native Service

The Hub Server (`src/remora/hub/server.py`) exposes Remora as a REST API. This is what makes it different from other agent frameworks — it's not a library you import, it's a **service you call**.

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/graph/execute` | POST | Trigger a new agent graph |
| `/subscribe` | GET | SSE event stream |
| `/api/files` | GET | List workspace files |
| `/respond/{agent_id}` | POST | Send response to blocked agent |

### `/graph/execute` Payload

```json
{
    "bundle": "run_linter",
    "target_path": "src/main.py",
    "target": "def foo():\n    pass",
    "target_type": "function"
}
```

The server:
1. Creates a new `GraphWorkspace`
2. Compiles an `AgentGraph` from the bundle
3. Assigns the workspace to each agent
4. Schedules execution
5. Returns immediately with a `graph_id`

### Response

```json
{
    "graph_id": "abc123",
    "status": "started",
    "workspace": "ws-xyz789"
}
```

The client can then:
- Subscribe to `/subscribe` to watch progress
- Query `/api/files?path=` to see generated files
- POST to `/respond/{agent_id}` when the agent blocks

### Hub Server Internals

The Hub Server is built on **Starlette** (ASGI framework) and consists of several key components:

```python
class HubServer:
    def __init__(self, workspace_path, host, port, workspace_base):
        self.workspace_path = workspace_path
        self.host = host
        self.port = port
        self.workspace_base = workspace_base  # Base directory for all workspaces
        
        self._event_bus = get_event_bus()    # Central event system
        self._workspace_manager = WorkspaceManager(base_dir=self.workspace_base)
        self._coordinator = WorkspaceInboxCoordinator(self._event_bus)
        self._hub_state = HubState()          # In-memory state tracking
        self._running_graphs: dict[str, asyncio.Task] = {}
```

**Server Lifecycle:**

1. **Start** → Initializes event bus, workspace manager, subscribes to events
2. **Request** → Routes through Starlette, creates/finds workspace
3. **Execute** → Compiles AgentGraph, schedules async execution
4. **Stream** → Events flow through EventBus, state updates, SSE emitted
5. **Complete** → Final state persisted, resources cleaned up

**Route Registration:**

```python
def _build_app(self) -> Starlette:
    return Starlette(routes=[
        Route("/", self.home),                              # Dashboard UI
        Route("/subscribe", self.subscribe),               # SSE stream
        Route("/graph/execute", self.execute_graph, methods=["POST"]),
        Route("/graph/list", self.list_graphs, methods=["GET"]),
        Route("/api/files", self.list_workspace_files),
        Route("/agent/{agent_id}/respond", self.respond, methods=["POST"]),
        Mount("/static", StaticFiles(...)),
    ])
```

### The Datastar Framework

**What is Datastar?**  
[Datastar](https://starfederation.github.io/datastar/) is a library that enables **server-side rendering with fine-grained reactivity** using Server-Sent Events (SSE). Think of it as HTMX, but with SSE for real-time updates.

**Why Datastar?**  
Traditional web apps require either:
- **Full page reloads** (slow, poor UX)
- **Client-side SPA** (complex, heavy JS bundles)
- **WebSocket polling** (overhead, bidirectional complexity)

Datastar gives you:
- **Server-driven DOM updates** via SSE
- **Zero JavaScript** on the client side (just the Datastar library)
- **Fine-grained reactivity** — only affected elements update
- **Signals** — reactive state that syncs between server and client

**How Remora Uses Datastar:**

1. **Initial Load** — Server renders full HTML with `data-signals` containing initial state
2. **Subscribe Endpoint** — Returns `DatastarResponse` with `@datastar_response` decorator
3. **Event Loop** — On each EventBus event, re-render view, yield `SSE.patch_elements()`

```python
@datastar_response
async def event_stream():
    # Send initial state
    view_data = self._hub_state.get_view_data()
    yield SSE.patch_elements(dashboard_view(view_data))
    
    # On each event, re-render and push updates
    async for _ in self._event_bus.stream():
        view_data = self._hub_state.get_view_data()
        yield SSE.patch_elements(dashboard_view(view_data))
```

**Datastar Attributes in Remora's UI:**

```html
<!-- Initialize SSE connection, fetch from /subscribe -->
<body data-init="@get('/subscribe')">

<!-- Bind input to signal -->
<input data-bind="graphLauncher.bundle">

<!-- On click, POST to endpoint -->
<button data-on="click" 
        data-on-click="@post('/graph/execute', payload)">
```

This is what powers the live dashboard — no WebSocket, no client-side state management, just pure SSE-driven reactivity.

### Full API Interaction Guide

Here's how to integrate with Remora as an external client:

#### 1. Start a Graph Execution

```bash
curl -X POST http://localhost:8001/graph/execute \
  -H "Content-Type: application/json" \
  -d '{
    "bundle": "run_linter",
    "target_path": "src/main.py",
    "target": "def calculate_sum(a, b):\n    result = a + b\n    return result"
  }'
```

**Response:**
```json
{
  "graph_id": "abc123def",
  "status": "started",
  "agents": 1,
  "workspace": "ws-abc123def"
}
```

#### 2. Subscribe to Events (SSE)

There are two SSE endpoints:

**`/events`** - Raw JSON events (recommended for API clients):
```bash
curl -N http://localhost:8001/events
```

**Event Format:**
```
event: agent:started
data: {"agent_id": "run_linter-agent-abc123def", "bundle": "run_linter", ...}

event: tool:called
data: {"tool": "run_command", "cmd": "ruff", "args": ["check", ...]}

event: agent:completed
data: {"agent_id": "...", "result": {"issues": [...], "total": 5}}

event: graph:completed
data: {"graph_id": "abc123def", "agents_completed": 1}
```

**`/subscribe`** - Datastar HTML patches (for the dashboard UI):
```bash
curl -N http://localhost:8001/subscribe
```

This endpoint streams full HTML page updates for the browser-based dashboard.

#### 3. List Workspace Files

```bash
curl "http://localhost:8001/api/files?path="
```

**Response:**
```json
{
  "path": "",
  "entries": [
    {"name": "src", "type": "directory"},
    {"name": ".remora", "type": "directory"}
  ]
}
```

#### 4. Respond to Blocked Agent

When an agent blocks (e.g., asking whether to apply a fix):

```bash
curl -X POST http://localhost:8001/agent/run_linter-agent-abc123def/respond \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Apply these lint fixes?",
    "answer": "Yes",
    "msg_id": "msg-123"
  }'
```

#### 5. List All Graphs

```bash
curl http://localhost:8001/graph/list
```

**Response:**
```json
{
  "graphs": [
    {
      "graph_id": "abc123def",
      "bundle": "run_linter",
      "target": "def calculate_sum...",
      "target_path": "src/main.py",
      "created_at": "2024-01-15T10:30:00Z",
      "status": "running"
    }
  ]
}
```

#### Python Client Example

Here's a robust Python client for interacting with Remora:

```python
import asyncio
import httpx
from httpx_sse import aconnect_sse
import json

class RemoraClient:
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
    
    async def execute(self, bundle: str, target: str, target_path: str = None) -> str:
        """Start a graph execution, return graph_id."""
        async with httpx.AsyncClient() as client:
            payload = {"bundle": bundle, "target": target}
            if target_path:
                payload["target_path"] = target_path
            
            response = await client.post(
                f"{self.base_url}/graph/execute",
                json=payload
            )
            return response.json()["graph_id"]
    
    async def events(self):
        """Yield events from SSE stream."""
        async with httpx.AsyncClient() as client:
            async with aconnect_sse(client, "GET", f"{self.base_url}/subscribe") as stream:
                async for sse in stream.aiter_sse():
                    if sse.data:
                        yield json.loads(sse.data)
    
    async def respond(self, agent_id: str, answer: str, question: str = None, msg_id: str = None):
        """Send response to a blocked agent."""
        async with httpx.AsyncClient() as client:
            payload = {"answer": answer}
            if question:
                payload["question"] = question
            if msg_id:
                payload["msg_id"] = msg_id
            
            await client.post(
                f"{self.base_url}/agent/{agent_id}/respond",
                json=payload
            )
    
    async def files(self, path: str = "") -> list:
        """List files in workspace."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/api/files?path={path}")
            return response.json()["entries"]

# Usage
async def main():
    client = RemoraClient()
    
    # Start execution
    graph_id = await client.execute(
        bundle="run_linter",
        target="import os\ndef foo():\n    pass",
        target_path="main.py"
    )
    print(f"Started graph: {graph_id}")
    
    # Listen for completion
    async for event in client.events():
        print(f"Event: {event}")
        if event.get("category") == "graph" and event.get("action") == "completed":
            break

asyncio.run(main())
```

#### Event Types Reference

| Event | Fields | Description |
|-------|--------|-------------|
| `agent:started` | `agent_id`, `bundle`, `name` | Agent began execution |
| `agent:blocked` | `agent_id`, `question`, `options`, `msg_id` | Agent waiting for user |
| `agent:resumed` | `agent_id`, `answer` | User provided response |
| `agent:completed` | `agent_id`, `result` | Agent finished successfully |
| `agent:failed` | `agent_id`, `error` | Agent encountered error |
| `tool:called` | `tool`, `input` | Tool invocation started |
| `tool:completed` | `tool`, `output` | Tool finished |
| `model:request` | `model`, `prompt` | LLM API call made |
| `model:response` | `model`, `output` | LLM response received |
| `graph:started` | `graph_id` | Graph execution started |
| `graph:completed` | `graph_id`, `agents_completed` | All agents finished |

## 6. The Inbox System: Human-in-the-Loop

Agents can pause and ask questions via the **AgentInbox** (`src/remora/agent_graph.py`). This enables:

- Confirmation before destructive actions
- Clarification on ambiguous tasks
- Human oversight on critical decisions

```python
class AgentInbox:
    async def ask_user(self, question: str, timeout: float = 300.0) -> str:
        """Block and wait for user response."""
        self.blocked = True
        self.blocked_question = question
        # ... waits for response via KV store
```

When an agent calls `ask_user()`:
1. Agent state → `BLOCKED`
2. Event `agent:blocked` emitted with the question
3. Question written to workspace KV (`outbox:question:{id}`)
4. Graph execution pauses
5. External client reads question, decides
6. POST to `/respond/{agent_id}` with answer
7. Agent resumes with the answer

---

# Why It's Useful

### For Developers
- **Plug-and-play agent bundles**: Need a linter? Use the `run_linter` bundle. Need docstrings? Use `write_docstring`. Bundles are self-contained and reusable.
- **Observable execution**: Every agent step emits typed events. You see exactly what the agent is doing, when it's doing it, and what it produced.
- **Composability**: Bundle outputs feed into other bundles. A linter bundle can feed its results into an `apply_fix` bundle in a single graph execution.

### For Platform Engineers
- **HTTP-first**: Remora isn't a Python library you import—it's a service you call. Trigger agents from your CLI, CI pipeline, or any external system via simple REST calls.
- **Workspace isolation**: Each agent execution gets its own sandboxed workspace. No cross-contamination between runs.
- **Type-safe contracts**: Agent inputs and outputs follow defined schemas. No guessing what an agent will return.

---

# Why It's Interesting (Technical)

### The Bundle Architecture

Remora agents are defined by **bundles**—collections of Grail scripts that implement specific capabilities. Bundles are discovered dynamically at runtime based on configuration. This is fundamentally different from:

- **LangChain/Agents**: Where tools are hardcoded Python functions
- **AutoGen**: Where agents are monolithic LLM wrappers
- **Devin/Cline**: General-purpose AI assistants with no explicit structure

In Remora, a "bundle" is a first-class concept. The `run_linter` bundle contains scripts that analyze code, invoke linters, and return structured findings. The `write_docstring` bundle contains scripts that analyze function signatures and generate documentation. These bundles are:

- **Discoverable**: Found via the discovery system based on query packs
- **Composable**: Bundles can depend on other bundles
- **Versionable**: Bundles evolve independently
- **Observable**: Every bundle execution emits events with full context

### The Graph Execution Model

Remora doesn't just "run an agent"—it compiles and executes an **AgentGraph**. This graph:

1. **Resolves dependencies**: Figure out what agents need to run, and in what order
2. **Manages concurrency**: Execute independent agents in parallel
3. **Handles errors gracefully**: Configurable error policies (stop on first error, retry, continue)
4. **Streams results**: Real-time SSE events for each node completion

This graph-based model is what makes Remora **reliable**. Unlike general-purpose LLM calls where you don't know what you'll get, Remora graphs have predictable behavior because they're built from well-defined components.

### HTTP as a First-Class Boundary

Most agent frameworks treat HTTP as an implementation detail. Remora treats it as an **architectural principle**:

- `/graph/execute`: Trigger any agent graph via POST
- `/subscribe`: Stream all agent events in real-time
- `/api/files`: Query workspace state after execution
- `/respond`: Interactive human-in-the-loop via HTTP

This design means Remora integrates with **any** ecosystem. Your CI/CD system, your monitoring tools, your existing backend services—all can invoke Remora agents without Python dependencies.

---

# Why It's Valuable (Business)

### The Market Opportunity

The global software development market is $500B+. Every company is trying to do more with fewer developers. The promise of AI-assisted development is real, but current solutions suffer from:

- **Unreliability**: General-purpose AI makes mistakes that are hard to catch
- **Opacity**: You can't explain why an AI made a decision
- **Cost**: Running GPT-4 on every code change is prohibitively expensive
- **Integration friction**: Most tools require ripping out your existing workflow

### Remora's Value Proposition

| Problem | Remora Solution |
|---------|-----------------|
| Unreliable AI | Structured bundles with typed inputs/outputs |
| Opaque decisions | Full event streaming + workspace artifacts |
| High cost | Small, focused models (4B-8B parameters) |
| Integration friction | HTTP-native, language-agnostic |

### Competitive Moat

Remora's moat isn't the idea of AI agents—it's the **architecture**:

- **Bundle ecosystem**: The more bundles built, the more valuable the platform
- **Graph compiler**: Hard to replicate the graph execution + event streaming
- **HTTP-native design**: Most competitors are Python libraries; Remora is a service
- **Observability by default**: Every execution produces audit trails

### Scaling Path

1. **Today**: Developer-focused CLI + Hub Server for individual teams
2. **Near-term**: SaaS offering with managed inference + bundle marketplace
3. **Long-term**: Enterprise platform with custom bundle development + compliance features

The bundle model creates a **network effect**: as more developers build and share bundles, the platform becomes more valuable to everyone.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        External Client                          │
│                  (api_demo.py - HTTP calls)                     │
└─────────────────────────┬───────────────────────────────────────┘
                          │ HTTP
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Remora Hub Server                            │
│              (Starlette/FastAPI on port 8001)                   │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ /graph/exec │  │ /subscribe  │  │ /api/files             │  │
│  │   (POST)    │  │   (SSE)     │  │   (GET)                │  │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘  │
│         │                │                     │                │
│         ▼                │                     │                │
│  ┌─────────────┐        │                     │                │
│  │AgentGraph   │        │                     │                │
│  │ Compiler    │◄───────┴─────────────────────┘                │
│  └──────┬──────┘                                                │
│         │                                                        │
│         ▼                                                        │
│  ┌─────────────┐  ┌─────────────┐                              │
│  │   Agent 1   │  │   Agent 2   │  (parallel execution)       │
│  │ (run_linter)│  │(write_docstr)│                             │
│  └──────┬──────┘  └──────┬──────┘                              │
│         │                │                                      │
│         ▼                ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              GraphWorkspace (sandboxed)                 │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐   │   │
│  │  │ KV Store    │  │ Files       │  │ Bundles       │   │   │
│  │  │ (IPC)       │  │ (artifacts) │  │ (skills)      │   │   │
│  │  └─────────────┘  └─────────────┘  └────────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                          │
                          │ SSE Events
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Event Bus                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │agent:*   │  │tool:*    │  │model:*   │  │graph:*       │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Demo Walkthrough

When you run `api_demo.py`, here's what happens:

1. **Client connects** to `/subscribe` SSE endpoint
2. **Client POSTs** to `/graph/execute` with:
   - `bundle: "run_linter"` → targets `demo_input/src/main.py`
   - `bundle: "write_docstring"` → targets `demo_input/src/utils/helpers.py`
3. **Server compiles** two separate AgentGraphs, one for each bundle
4. **Parallel execution**: Both graphs run concurrently
5. **Events stream back**: You see every tool call, every agent state change
6. **Workspace queried**: Final state retrieved via `/api/files`

This demonstrates the core value: **one HTTP endpoint, multiple agent behaviors, complete observability**.

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/remora/agent_graph.py` | AgentGraph, AgentNode, AgentInbox classes |
| `src/remora/event_bus.py` | Event system and SSE streaming |
| `src/remora/workspace.py` | Workspace isolation and KV store |
| `src/remora/hub/server.py` | Hub REST API server |
| `.grail/agents/*/` | Bundle implementations (Grail scripts) |

---

## Next Steps

- Explore the bundle system in `.grail/agents/`
- Read the technical documentation in `docs/`
- Try adding a new bundle to the system
- Run the demo and watch the SSE events in real-time

## License

MIT
