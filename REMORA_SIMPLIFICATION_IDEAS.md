# Remora Unification & Simplification Analysis

## Executive Summary

This document analyzes how to **unify three concepts** into one simple, elegant library:

1. **Remora** (existing) - Graph execution with workspaces, events, tools
2. **CST Agent Swarm** - Persistent agents with reactive message passing
3. **Neovim Integration** - Editor as swarm UI

The goal is a **single mental model** that's easy to reason about while retaining all necessary functionality.

**Key Insight**: Much of what Remora already has is *exactly what we need* for the swarm - we just need to reframe it, not remove it. The reactive subscription model makes the system both simpler AND more responsive.

---

## Part 1: The Unified Mental Model

### Current Remora Mental Model

```
Discovery → Graph → Executor → Results
              ↓
         (batch execution, then done)
```

### Unified Mental Model (Reactive)

```
┌─────────────────────────────────────────────────────────────────┐
│                     UNIFIED REMORA (REACTIVE)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  AGENTS = CST Nodes with persistent state + subscriptions       │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Agent                                                   │    │
│  │  ├── identity (node_id, type, path, parent)             │    │
│  │  ├── workspace (Cairn .db file)                         │    │
│  │  ├── state (connections, chat_history) → state.jsonl    │    │
│  │  ├── subscriptions ← patterns that trigger this agent   │    │
│  │  └── outbox → EventStore appends                        │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  EXECUTION = Reactive, subscription-driven                       │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                                                          │    │
│  │  Event arrives → Match subscriptions → Trigger agents    │    │
│  │                                                          │    │
│  │  Agent Turn:                                             │    │
│  │  1. Load state                                           │    │
│  │  2. Receive triggering event(s) ← PUSHED, not polled    │    │
│  │  3. Run kernel                                           │    │
│  │  4. Emit outbox events → trigger other subscriptions    │    │
│  │  5. Save state                                           │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  COMMUNICATION = EventStore + SubscriptionRegistry              │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  EventStore.append(event) → triggers matching subs      │    │
│  │  SubscriptionRegistry.match(event) → list of agents     │    │
│  │  EventBus.emit(event) → UI updates                      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### The "Aha!" Realizations

1. **EventStore IS the message bus** - We don't need a new system. Just add routing columns.

2. **Subscriptions subsume inbox polling** - No `last_seen_event_id` tracking needed.

3. **Workspaces ARE agent state** - Cairn already provides persistent, isolated workspaces per agent.

4. **GraphExecutor can run single agents** - It already handles one agent at a time internally.

5. **Events already flow to UI** - The projector pattern works for both batch execution AND swarm visualization.

6. **Discovery already maps CST → Agents** - We just need to persist the mapping.

7. **Neovim is just another subscriber** - It subscribes to events like any agent would.

---

## Part 2: What Remora Already Has (And We Need)

### 2.1 EventStore - THE MESSAGE BUS + TRIGGER SOURCE

**Location**: `core/event_store.py`

**What it does**:
- SQLite-backed event persistence
- Indexed queries by `graph_id`, `event_type`, `timestamp`
- Replay with filtering (`since`, `until`, `after_id`)

**Why we NEED it for swarm**:
- Agent messages are just events with routing
- Combined with SubscriptionRegistry, it drives reactive execution
- Already handles concurrency (async locks)

**Modification needed**: Add routing + subscription integration
```python
class EventStore:
    def __init__(self, db_path, subscriptions: SubscriptionRegistry, event_bus: EventBus):
        self._subscriptions = subscriptions
        self._event_bus = event_bus
        self._trigger_queue: asyncio.Queue = asyncio.Queue()

    async def append(self, event: Event) -> int:
        event_id = await self._insert(event)

        # Find matching subscriptions → queue triggers
        matching = await self._subscriptions.get_matching_agents(event)
        for agent_id in matching:
            await self._trigger_queue.put((agent_id, event_id, event))

        # Also emit to EventBus for UI
        await self._event_bus.emit(event)
        return event_id

    async def get_triggers(self) -> AsyncIterator[tuple[str, int, Event]]:
        """Yield (agent_id, event_id, event) as they arrive."""
        while True:
            yield await self._trigger_queue.get()
```

**Verdict**: **KEEP and EXTEND** (~50 lines to add)

---

### 2.2 SubscriptionRegistry - THE REACTIVE CORE (NEW)

**Location**: `core/subscriptions.py` (NEW)

**What it does**:
- Pattern-based subscription matching
- Persistent storage (SQLite)
- Default subscriptions for every agent

**Why we NEED it**:
- Replaces inbox polling with reactive triggering
- Explicit declaration of what each agent cares about
- Enables both direct messaging AND ambient awareness

```python
@dataclass
class SubscriptionPattern:
    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None  # Shortcut: messages addressed to me
    path_glob: str | None = None
    tags: list[str] | None = None

    def matches(self, event: Event) -> bool:
        # All specified conditions must match (AND logic)
        ...

class SubscriptionRegistry:
    async def register(self, agent_id: str, pattern: SubscriptionPattern) -> str
    async def register_defaults(self, agent_id: str, metadata: AgentMetadata) -> None
    async def unregister_all(self, agent_id: str) -> None
    async def get_matching_agents(self, event: Event) -> list[str]
    async def get_subscriptions(self, agent_id: str) -> list[Subscription]
```

**Default subscriptions** (implicit for every agent):
```python
# 1. Direct messages
SubscriptionPattern(to_agent=self.agent_id)

# 2. Changes to source file
SubscriptionPattern(event_types=["FileSaved"], path_glob=self.file_path)
```

**Verdict**: **NEW** (~150 LOC)

---

### 2.3 EventBus - UI COORDINATION

**Location**: `core/event_bus.py`

**What it does**:
- In-memory pub/sub for live events
- Type-based subscription
- Async streaming for UI

**Why we NEED it for swarm**:
- Live notifications to Neovim
- UI updates during agent turns
- Separate from SubscriptionRegistry (which is for agent triggers)

**Verdict**: **KEEP AS-IS** (already simple enough)

---

### 2.4 Discovery - CST → AGENT MAPPING

**Location**: `core/discovery.py`

**What it does**:
- Tree-sitter parsing
- `CSTNode` with `node_id`, `node_type`, `file_path`, `start_line`, `end_line`
- Deterministic ID generation

**Why we NEED it for swarm**:
- Maps code constructs to agents
- IDs are stable across restarts
- Multi-language support

**Verdict**: **KEEP AS-IS** (core value)

---

### 2.5 Workspaces - AGENT ISOLATION

**Location**: `core/workspace.py`, `core/cairn_bridge.py`

**What it does**:
- Per-agent `.db` files via Cairn
- CoW semantics
- Read/write isolation

**Why we NEED it for swarm**:
- Each agent has isolated workspace
- Content modifications don't conflict
- Already persistent!

**Modification needed**:
- Add `state.jsonl` alongside `workspace.db` for agent metadata

**Verdict**: **KEEP and EXTEND**

---

### 2.6 Executor - AGENT TURN RUNNER

**Location**: `core/executor.py`

**What it does**:
- Runs agent kernels with tools
- Handles concurrency, timeouts, errors
- Emits lifecycle events

**Why we NEED it for swarm**:
- Core execution logic is reusable
- Already integrates with workspaces, tools, events

**Modification needed**:
- Extract single-agent execution as `AgentRunner.run_turn(agent_id, event)`
- Keep graph execution for batch mode

**Verdict**: **KEEP and REFACTOR** (extract `AgentRunner`)

---

### 2.7 Graph - AGENT TOPOLOGY

**Location**: `core/graph.py`

**What it does**:
- `AgentNode` with `upstream`/`downstream` relationships
- Topological sorting
- Batch computation

**Why we NEED it for swarm**:
- Agents have parent/child relationships
- Message routing uses topology
- Batch execution still useful

**Verdict**: **KEEP AS-IS**

---

### 2.8 Context Builder - PROMPT ENRICHMENT

**Location**: `core/context.py`

**What it does**:
- Builds context from recent events
- Two-track memory (recent + long-term)

**Assessment**: The two-track pattern IS useful for agents that need to remember things. However, with the reactive model, agents receive events directly instead of querying inbox.

**Modification needed**:
- Simplify to work with triggering events + agent state
- Remove "since_id" tracking

**Verdict**: **SIMPLIFY** (merge into agent state)

---

## Part 3: What Can Actually Be Removed

### 3.1 DI Container

**Location**: `core/container.py` (~150 LOC)

**Current purpose**: Wire up dependencies for graph execution.

**Why remove**:
- For a personal project, explicit wiring is clearer
- Container adds indirection without proportional benefit
- Swarm mode needs different initialization anyway

**Replacement**:
```python
# In service/api.py or a new swarm/runtime.py
def create_swarm(config_path: Path) -> SwarmRuntime:
    config = Config.from_yaml(config_path)
    subscriptions = SubscriptionRegistry(config.workspace_path / "subscriptions.db")
    event_store = EventStore(config.workspace_path / "events.db", subscriptions)
    # ... explicit, readable wiring
```

**Verdict**: **REMOVE** (~150 LOC saved)

---

### 3.2 Checkpoint System

**Location**: `core/checkpoint.py` (~170 LOC)

**Current purpose**: Save/restore graph execution state.

**Why remove**:
- Swarm agents have persistent state by design (state.jsonl)
- Graph execution checkpoints are separate from agent persistence
- For personal use, "rerun if it fails" is fine

**What replaces it**: Agent state persistence (simpler, per-agent)

**Verdict**: **REMOVE** (~170 LOC saved)

---

### 3.3 Indexer Subsystem

**Location**: `indexer/` (~300 LOC)

**Current purpose**: Background code indexing daemon.

**Why remove**:
- Never completed or integrated
- Discovery already does what we need
- Swarm agents ARE the "index"

**Verdict**: **REMOVE** (~300 LOC saved)

---

### 3.4 Tool Registry Abstraction

**Location**: `core/tool_registry.py` (~120 LOC)

**Current purpose**: Dynamic tool registration with presets.

**Why simplify**:
- Tools don't change at runtime
- Presets rarely used
- Direct imports are clearer

**Replacement**:
```python
# In core/tools/grail.py
def get_tools_for_agent(agent_type: str, externals: dict) -> list[Tool]:
    base_tools = [ReadFileTool(externals), WriteFileTool(externals), ...]
    if agent_type == "function":
        return base_tools + [SendMessageTool(), SubscribeTool(), ...]
    return base_tools
```

**Verdict**: **SIMPLIFY** (~80 LOC saved)

---

### 3.5 Streaming Sync Manager

**Location**: `core/streaming_sync.py` (~150 LOC)

**Current purpose**: Lazy file syncing with batching.

**Assessment**: Only needed for `SyncMode.LAZY`. For personal use on local files, `SyncMode.FULL` is fine and much simpler.

**Verdict**: **REMOVE** if only using FULL sync (~150 LOC saved)

---

### 3.6 Dead Code

| Item | Location | LOC |
|------|----------|-----|
| `WorkspaceManager` class | `workspace.py` | ~50 |
| `EventBridge` class | `event_bus.py` | ~30 |
| Workspace snapshot stubs | `workspace.py` | ~20 |

**Verdict**: **REMOVE** (~100 LOC saved)

---

## Part 4: What Needs to Be Added

### 4.1 SubscriptionRegistry (THE KEY NEW COMPONENT)

**New file**: `core/subscriptions.py` (~150 LOC)

```python
@dataclass
class SubscriptionPattern:
    """Pattern for matching events."""
    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None

    def matches(self, event: Event) -> bool:
        """All specified conditions must match (AND logic)."""
        ...

class SubscriptionRegistry:
    """Manages agent subscriptions to events."""

    def __init__(self, db_path: Path):
        self._db = sqlite3.connect(db_path)
        self._cache: dict[str, list[Subscription]] = {}

    async def register(self, agent_id: str, pattern: SubscriptionPattern) -> str
    async def register_defaults(self, agent_id: str, metadata: AgentMetadata) -> None
    async def unregister(self, subscription_id: str) -> None
    async def unregister_all(self, agent_id: str) -> None
    async def get_matching_agents(self, event: Event) -> list[str]
    async def get_subscriptions(self, agent_id: str) -> list[Subscription]
```

### 4.2 Agent State Persistence

**New file**: `core/agent_state.py` (~80 LOC)

```python
@dataclass
class AgentState:
    """Persistent state for a swarm agent."""
    identity: AgentIdentity
    connections: dict[str, str]           # symbolic_name -> agent_id
    chat_history: list[Message]
    custom_subscriptions: list[SubscriptionPattern]
    last_content_hash: str
    last_activated: float

    @classmethod
    def load(cls, path: Path) -> "AgentState": ...
    def save(self, path: Path) -> None: ...
```

### 4.3 Swarm State Registry

**New file**: `core/swarm_state.py` (~100 LOC)

```python
class SwarmState:
    """Registry of all agents in the swarm."""

    async def register_agent(self, agent_id: str, metadata: AgentMetadata) -> None
    async def get_agent(self, agent_id: str) -> AgentMetadata | None
    async def list_agents(self, parent_id: str | None = None) -> list[AgentMetadata]
    async def list_agents_for_file(self, path: Path) -> list[AgentMetadata]
    async def mark_orphaned(self, agent_id: str) -> None
```

### 4.4 Agent Runner (Reactive)

**New file**: `core/agent_runner.py` (~120 LOC)

```python
class AgentRunner:
    """Runs agent turns in response to events."""

    async def run_loop(self) -> None:
        """Main event loop - process triggers as they arrive."""
        async for agent_id, event_id, event in self._event_store.get_triggers():
            if self._can_trigger(agent_id):
                await self._run_turn(agent_id, event)

    async def _run_turn(self, agent_id: str, triggering_event: Event) -> TurnResult:
        # 1. Load agent state (no last_seen_event_id needed!)
        state = AgentState.load(self._state_path(agent_id))

        # 2. Build prompt with triggering event (not inbox query!)
        prompt = self._build_prompt(state, triggering_event)

        # 3. Run kernel (reuse from executor)
        result = await kernel.run(...)

        # 4. Process outbox - emit events (triggers other subscriptions)
        for tool_call in result.tool_calls:
            if tool_call.name == "send_message":
                await self.event_store.append(AgentMessageEvent(...))

        # 5. Save state
        state.save(self._state_path(agent_id))
```

### 4.5 Startup Reconciler

**New file**: `core/reconciler.py` (~100 LOC)

```python
async def reconcile(project_path: Path, swarm_state: SwarmState, subscriptions: SubscriptionRegistry) -> ReconcileResult:
    """Diff current CST against saved agents, spawn/update/orphan as needed."""
    current_nodes = discover(project_path)
    saved_agents = await swarm_state.list_agents()

    # Diff
    new_ids = current_ids - saved_ids
    deleted_ids = saved_ids - current_ids

    # Reconcile
    for node_id in new_ids:
        await swarm_state.register_agent(node_id, metadata)
        await subscriptions.register_defaults(node_id, metadata)

    for node_id in deleted_ids:
        await swarm_state.mark_orphaned(node_id)
        await subscriptions.unregister_all(node_id)
```

### 4.6 EventStore Extension

**Modify**: `core/event_store.py` (~50 LOC added)

- Add trigger queue integration with SubscriptionRegistry
- Add routing columns (`from_agent`, `to_agent`, `correlation_id`, `tags`)
- Add `get_triggers()` async iterator

### 4.7 Agent Message Events

**Modify**: `core/events.py` (~30 LOC added)

```python
@dataclass(frozen=True)
class AgentMessageEvent:
    """Message between agents."""
    from_agent: str
    to_agent: str
    action: str  # "request", "response", "notify"
    content: dict[str, Any]
    correlation_id: str | None = None
    tags: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

@dataclass(frozen=True)
class FileSavedEvent:
    """File was saved (from editor)."""
    path: str
    source: str  # "neovim", "vscode", "manual"
    timestamp: float = field(default_factory=time.time)
```

### 4.8 Neovim RPC Server

**New file**: `nvim/server.py` (~250 LOC)

```python
class NvimRpcServer:
    """JSON-RPC server for Neovim plugin with subscription support."""

    async def _select_agent(self, params) -> dict
    async def _emit_event(self, params) -> dict
    async def _nvim_subscribe(self, client, params) -> dict
    async def _nvim_unsubscribe(self, client, params) -> dict

    # Forward matching events to connected Neovim clients
    def _setup_event_forwarding(self):
        async def forward_handler(event):
            for client in self.clients:
                for pattern in client.subscriptions:
                    if pattern.matches(event):
                        await self._notify_client(client, event)
```

---

## Part 5: The Unified Architecture

### File Structure

```
remora/
├── core/
│   ├── __init__.py
│   ├── config.py             # SIMPLIFY: Flatten to ~100 LOC
│   ├── discovery.py          # KEEP: ~250 LOC
│   ├── graph.py              # KEEP: ~150 LOC
│   ├── executor.py           # KEEP: For batch mode, ~300 LOC
│   ├── agent_runner.py       # NEW: Reactive agent turns, ~120 LOC
│   ├── agent_state.py        # NEW: Persistent agent state, ~80 LOC
│   ├── swarm_state.py        # NEW: Agent registry, ~100 LOC
│   ├── subscriptions.py      # NEW: SubscriptionRegistry, ~150 LOC
│   ├── reconciler.py         # NEW: Startup diff, ~100 LOC
│   ├── events.py             # EXTEND: +AgentMessageEvent, ~160 LOC
│   ├── event_bus.py          # KEEP: ~120 LOC
│   ├── event_store.py        # EXTEND: +subscription integration, ~330 LOC
│   ├── workspace.py          # SIMPLIFY: AgentWorkspace only, ~100 LOC
│   ├── cairn_bridge.py       # KEEP: ~200 LOC
│   ├── cairn_externals.py    # KEEP: ~70 LOC
│   └── tools/
│       └── grail.py          # EXTEND: +messaging tools, ~280 LOC

├── nvim/                     # NEW
│   ├── __init__.py
│   └── server.py             # Neovim RPC with subscriptions, ~250 LOC

├── service/
│   ├── api.py                # SIMPLIFY: ~100 LOC
│   └── handlers.py           # KEEP: ~150 LOC

├── adapters/
│   └── starlette.py          # EXTEND: +swarm routes, ~150 LOC

├── ui/
│   ├── projector.py          # KEEP: ~150 LOC
│   ├── view.py               # KEEP: ~50 LOC
│   └── components/           # KEEP: ~300 LOC

├── cli/
│   └── main.py               # EXTEND: +swarm commands, ~150 LOC

└── utils/                    # KEEP: ~110 LOC

REMOVED:
├── core/container.py         # -150 LOC (DI container)
├── core/checkpoint.py        # -170 LOC (checkpointing)
├── core/context.py           # -170 LOC (merged into agent_state)
├── core/tool_registry.py     # -120 LOC (simplified)
├── core/streaming_sync.py    # -150 LOC (not needed for FULL sync)
└── indexer/                  # -300 LOC (dead code)
```

### Line Count Summary

| Category | Removed | Added | Net |
|----------|---------|-------|-----|
| Dead code (indexer, stubs) | -400 | - | -400 |
| DI Container | -150 | - | -150 |
| Checkpoint | -170 | - | -170 |
| Context → Agent State | -170 | +80 | -90 |
| Tool Registry → Direct | -120 | +30 | -90 |
| Streaming Sync | -150 | - | -150 |
| SubscriptionRegistry | - | +150 | +150 |
| Swarm additions | - | +400 | +400 |
| Neovim server | - | +250 | +250 |
| **Total** | **-1160** | **+910** | **-250** |

**Result**: Slightly smaller codebase that does MORE with a cleaner model.

---

## Part 6: The Simple Mental Model

### One Sentence

> **Remora treats every code construct as a persistent agent with subscriptions, where events flow through an SQLite store that triggers matching agents reactively.**

### The Core Loop (Reactive)

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│   STARTUP                                                        │
│   ───────                                                        │
│   1. Load config                                                │
│   2. Discover CST nodes (tree-sitter)                           │
│   3. Reconcile: diff vs saved agents, spawn/update/orphan       │
│   4. Register default subscriptions for each agent              │
│   5. Start event loop                                           │
│   6. Start Neovim RPC server (optional)                         │
│                                                                  │
│   EVENT LOOP (reactive)                                          │
│   ─────────────────────                                          │
│   async for (agent_id, event) in event_store.get_triggers():    │
│       await agent_runner.run_turn(agent_id, event)              │
│                                                                  │
│   AGENT TURN (triggered by event)                                │
│   ───────────────────────────────                                │
│   1. Load agent state from state.jsonl                          │
│   2. Receive triggering event(s) ← PUSHED, not polled           │
│   3. Build prompt (code content + event + chat history)         │
│   4. Run kernel with tools                                      │
│   5. Emit outgoing events → triggers other subscriptions        │
│   6. Save agent state                                           │
│                                                                  │
│   COMMUNICATION                                                  │
│   ─────────────                                                  │
│   • Agent A sends: EventStore.append(to_agent=B)                │
│   • Agent B triggered: Subscription matches → turn runs         │
│   • Neovim sees: EventBus subscription → notification pushed    │
│                                                                  │
│   WHAT'S REMOVED                                                 │
│   ──────────────                                                 │
│   ✗ last_seen_event_id tracking                                 │
│   ✗ Inbox polling/querying                                      │
│   ✗ "Check if anything new" logic                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Equations

```
Agent = CSTNode + Workspace + State + Subscriptions

Subscription = Pattern that triggers this agent

Turn = Event matched → Load → Run → Emit → Save

Swarm = Agents + EventStore + SubscriptionRegistry

Communication = EventStore.append(event) → SubscriptionRegistry.match(event) → Trigger agents
```

---

## Part 7: Configuration Simplification

### Current (6 nested classes)

```python
RemoraConfig
├── DiscoveryConfig
├── BundleConfig
├── ExecutionConfig
├── IndexerConfig      # Remove (unused)
├── WorkspaceConfig
└── ModelConfig
```

### Simplified (1 flat class)

```python
@dataclass
class Config:
    # Project
    project_path: Path = Path.cwd()
    languages: list[str] = field(default_factory=lambda: ["python"])

    # Execution
    max_concurrency: int = 4
    timeout: int = 120

    # Model
    model_url: str = "http://localhost:8000/v1"
    model_name: str = "Qwen/Qwen3-4B"
    api_key: str = "EMPTY"

    # Swarm
    swarm_path: Path = field(default_factory=lambda: Path.home() / ".cache/remora")

    # Reactive
    max_trigger_depth: int = 10
    trigger_cooldown_ms: int = 100

    # Neovim
    nvim_socket: str = "/tmp/remora.sock"

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
```

---

## Part 8: Migration Path

### Phase 1: Clean Up

1. Delete `indexer/` directory
2. Delete `container.py`
3. Delete `checkpoint.py`
4. Delete `streaming_sync.py`
5. Delete dead code (WorkspaceManager, EventBridge, snapshot stubs)
6. Flatten config.py

**Result**: Cleaner base to build on

### Phase 2: SubscriptionRegistry

1. Create `subscriptions.py` with `SubscriptionPattern` and `SubscriptionRegistry`
2. Add SQLite persistence for subscriptions
3. Implement pattern matching logic

**Result**: Reactive core ready

### Phase 3: Extend EventStore

1. Add routing columns (`from_agent`, `to_agent`, `correlation_id`, `tags`)
2. Integrate with SubscriptionRegistry on `append()`
3. Add trigger queue and `get_triggers()` iterator
4. Add event types to `events.py`

**Result**: Message bus with reactive triggers

### Phase 4: Add Agent State

1. Create `agent_state.py` with `AgentState` class (no `last_seen_event_id`!)
2. Create `swarm_state.py` with `SwarmState` registry
3. Create `reconciler.py` for startup diff + subscription registration

**Result**: Persistent agents

### Phase 5: Add Agent Runner

1. Create `agent_runner.py` with reactive event loop
2. Implement cascade prevention (cooldown + depth limit)
3. Wire up to EventStore triggers

**Result**: Reactive execution

### Phase 6: Add Neovim Server

1. Create `nvim/server.py` with subscription support
2. Implement RPC handlers + event forwarding
3. Add to CLI

**Result**: Neovim integration

### Phase 7: Polish

1. Update CLI with swarm commands
2. Update HTTP API with swarm routes
3. Test end-to-end

**Result**: Unified system

---

## Part 9: What's Different From Previous Analysis

### Changed Model: Polling → Reactive

| Aspect | Polling Model | Reactive Model |
|--------|---------------|----------------|
| Triggering | Check inbox periodically | Events trigger subscriptions |
| State tracking | `last_seen_event_id` per agent | None needed |
| Responsiveness | Delayed (poll interval) | Immediate |
| Complexity | Query logic in agent | Declaration in subscription |
| Debugging | Hard to trace | Subscriptions are visible |

### Changed Verdicts

| Component | Previous Verdict | Current Verdict | Reason |
|-----------|-----------------|-----------------|--------|
| EventStore | KEEP & EXTEND | **KEEP & EXTEND MORE** | Integration with subscriptions |
| EventBus | KEEP AS-IS | **KEEP AS-IS** | Still needed for UI |
| - | - | **NEW: SubscriptionRegistry** | The reactive core |
| AgentRunner | Read inbox | **Receive events** | No polling |
| AgentState | Has `last_seen_event_id` | **No tracking needed** | Events are pushed |

### Key Realization

The polling model was simpler to explain but added hidden complexity:
- Every agent must track `last_seen_event_id`
- Agents must query their inbox
- "When does the poll happen?" is an open question

The reactive model is simpler to implement:
- Events trigger subscriptions automatically
- Agents receive events, don't query for them
- The subscription IS the "when"

---

## Conclusion

### Before: Three Separate Concepts

1. Remora = batch graph execution
2. CST Swarm = persistent agent system (proposed)
3. Neovim = editor integration (proposed)

### After: One Unified Reactive System

> **Remora is a CST agent swarm where code constructs are persistent agents with subscriptions, events flow through SQLite and trigger matching agents, with Neovim as just another subscriber.**

### The Numbers

| Metric | Before | After |
|--------|--------|-------|
| Total LOC | ~4150 | ~3900 |
| Concepts to understand | 3 separate | 1 unified |
| Mental model complexity | High | Low |
| Responsiveness | Poll-based | Immediate |
| Capabilities | Less | More |

### The One-Liner

**Old**: "Remora runs agents in dependency order with isolated workspaces."

**New**: "Remora makes every function an agent that reacts to events."

---

*Document version: 3.0*
*Status: Reactive Unified Architecture Complete*
