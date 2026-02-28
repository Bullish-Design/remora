# Remora CST Agent Swarm - Reactive Architecture

## Executive Summary

This document describes the architecture for a **CST Agent Swarm** - a system where every node in a codebase's Concrete Syntax Tree operates as an autonomous agent. The key insight is that this can be achieved with **minimal changes to existing Remora** by treating:

- **Agent = Workspace + persisted state**
- **Message bus = EventStore (already SQLite)**
- **Execution = reactive, subscription-driven**
- **Overlay filesystems = Jujutsu VCS**

---

## Part 1: Core Concepts

### 1.1 The CST Agent Model

Every CST node becomes an agent with persistent state:

```
workspace/
├── swarm_state.db              ← SQLite: agent registry + metadata
├── events.db                   ← SQLite: EventStore (message bus)
├── subscriptions.db            ← SQLite: SubscriptionRegistry
├── agents/
│   ├── file_main_py/
│   │   ├── state.jsonl         ← agent identity, connections, chat history
│   │   └── workspace.db        ← Cairn workspace (CoW content)
│   ├── func_format_date/
│   │   ├── state.jsonl
│   │   └── workspace.db
│   └── class_user/
│       ├── state.jsonl
│       └── workspace.db
└── jj/                         ← Jujutsu repo (optional, for versioning)
```

### 1.2 Agent Capabilities

Each agent has:

| Capability | Implementation |
|------------|----------------|
| **Identity** | `state.jsonl` - id, name, node_type, path, parent_id |
| **Workspace** | `workspace.db` - Cairn CoW workspace (existing) |
| **Subscriptions** | SubscriptionRegistry - patterns that trigger this agent |
| **Outbox** | EventStore append with `from_agent` field |
| **Tools** | Existing Grail tools + messaging tools |
| **Memory** | `state.jsonl` - learned connections dict |
| **Content** | Workspace read/write (existing) |

### 1.3 Reactive Communication Model

**Key Insight**: Subscriptions subsume both polling AND tagging.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     REACTIVE EVENT FLOW                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  EVENT SOURCES                   SUBSCRIPTION REGISTRY               │
│  ─────────────                   ────────────────────                │
│  • File watcher                  agent_id → [patterns]               │
│  • User chat                                                         │
│  • Agent outbox        ───→  EventStore.append(event)               │
│  • External triggers              │                                  │
│                                   ▼                                  │
│                          ┌─────────────────┐                         │
│                          │ Match against   │                         │
│                          │ subscriptions   │                         │
│                          └────────┬────────┘                         │
│                                   │                                  │
│                    ┌──────────────┼──────────────┐                   │
│                    ▼              ▼              ▼                   │
│              agent_A         agent_B         agent_C                 │
│              (matched)       (matched)       (no match)              │
│                    │              │                                  │
│                    ▼              ▼                                  │
│              ┌──────────┐  ┌──────────┐                              │
│              │Run Turn  │  │Run Turn  │                              │
│              │w/ event  │  │w/ event  │                              │
│              └──────────┘  └──────────┘                              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.4 Subscription Patterns

Agents register interest in event patterns. When events match, the agent is triggered.

```python
@dataclass
class SubscriptionPattern:
    """Pattern for matching events."""
    event_types: list[str] | None = None     # ["ContentChanged", "AgentMessage"]
    from_agents: list[str] | None = None     # ["linter", "test_*"]
    to_agent: str | None = None              # Shortcut: messages addressed to me
    path_glob: str | None = None             # "utils/*.py"
    tags: list[str] | None = None            # ["urgent", "review"]

    def matches(self, event: Event) -> bool:
        """All specified conditions must match (AND logic)."""
        ...
```

**Default subscriptions** (implicit for every agent):
```python
# Every agent subscribes to:
# 1. Direct messages addressed to them
SubscriptionPattern(to_agent=self.agent_id)

# 2. Changes to their source file
SubscriptionPattern(event_types=["ContentChanged"], path_glob=self.file_path)
```

**Custom subscriptions** (agent-defined):
```python
# Example: A test agent watching for function changes
SubscriptionPattern(
    event_types=["ContentChanged"],
    path_glob="src/utils/*.py",
    tags=["function"]
)

# Example: A linter watching all Python files
SubscriptionPattern(
    event_types=["FileSaved"],
    path_glob="**/*.py"
)
```

### 1.5 Why Subscriptions > Polling

| Aspect | Polling | Subscriptions |
|--------|---------|---------------|
| Responsiveness | Delayed (poll interval) | Immediate |
| Efficiency | O(agents × events) queries | O(events) matching |
| State tracking | Must track `last_seen_event_id` | Handled by registry |
| Coupling | Implicit (query patterns) | Explicit (declared patterns) |
| Debugging | Hard to trace | Easy - subscriptions are visible |

### 1.6 Tagging Is Just Subscription

"Direct messaging" is a special case of subscriptions:

```python
# Agent sends message with to_agent field
await event_store.append(AgentMessageEvent(
    from_agent="test_agent",
    to_agent="func_format_date",  # Explicit recipient
    content={"task": "add edge case"}
))

# func_format_date has implicit subscription:
SubscriptionPattern(to_agent="func_format_date")

# Event matches → agent triggered
```

**Broadcast** works the same way:
```python
# Sender broadcasts to all children
await event_store.append(AgentMessageEvent(
    from_agent="file_utils",
    to_agent="broadcast:children",
    content={"type": "refactor_notice"}
))

# Each child has subscription:
SubscriptionPattern(to_agent="broadcast:children", from_agents=[self.parent_id])
```

### 1.7 Agent Turn Model (Simplified)

```
┌─────────────────────────────────────────────────────────────────┐
│                 REACTIVE AGENT TURN                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  EVENT ARRIVES                                                   │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Subscription Match                                       │    │
│  │ "Does this event match any of my patterns?"              │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │ YES                                  │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ TRIGGER TURN                                             │    │
│  │                                                          │    │
│  │  1. Load state.jsonl                                     │    │
│  │  2. Receive triggering event(s) ← DELIVERED, not polled │    │
│  │  3. Build prompt with event context                      │    │
│  │  4. Run AgentKernel turn                                 │    │
│  │  5. Emit outgoing events → triggers other subscriptions  │    │
│  │  6. Save state.jsonl                                     │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  WHAT'S REMOVED:                                                 │
│  ✗ last_seen_event_id tracking                                  │
│  ✗ Inbox polling/querying                                        │
│  ✗ "Check if anything new" logic                                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.8 Startup: Reconciliation

On startup:

1. **Discover** - Run tree-sitter on current files
2. **Load** - Read `swarm_state.db` for last known agents
3. **Diff** - Compare discovered nodes vs saved state
4. **Reconcile**:
   - New nodes → spawn agents + register default subscriptions
   - Deleted nodes → mark agents as orphaned + remove subscriptions
   - Changed nodes → emit `ContentChanged` event (triggers subscriptions)
5. **Restore subscriptions** - Load custom subscriptions from agent states
6. **Start event loop** - Begin processing events

```python
async def reconcile_on_startup(workspace_path: Path) -> SwarmState:
    # 1. Discover current CST
    current_nodes = discover(workspace_path)
    current_ids = {node.node_id for node in current_nodes}

    # 2. Load saved state
    saved_agents = await load_swarm_state(workspace_path / "swarm_state.db")
    saved_ids = set(saved_agents.keys())

    # 3. Diff
    new_ids = current_ids - saved_ids
    deleted_ids = saved_ids - current_ids
    existing_ids = current_ids & saved_ids

    # 4. Reconcile
    for node_id in new_ids:
        await spawn_agent(node_id, current_nodes[node_id])
        await subscriptions.register_defaults(node_id)

    for node_id in deleted_ids:
        await mark_agent_orphaned(node_id)
        await subscriptions.unregister_all(node_id)

    for node_id in existing_ids:
        if content_changed(current_nodes[node_id], saved_agents[node_id]):
            # Emit event - subscriptions will handle triggering
            await event_store.append(ContentChangedEvent(
                agent_id=node_id,
                path=current_nodes[node_id].file_path
            ))

    # 5. Restore custom subscriptions
    for agent_id in existing_ids | new_ids:
        state = AgentState.load(state_path(agent_id))
        for pattern in state.custom_subscriptions:
            await subscriptions.register(agent_id, pattern)

    return SwarmState(...)
```

### 1.9 Cascade Prevention

With reactive subscriptions, cascades are possible (A triggers B triggers A...).

**Solution: Cooldown + Depth Limit**

```python
@dataclass
class TriggerContext:
    event_id: int
    depth: int = 0
    cooldowns: dict[str, float] = field(default_factory=dict)

    def can_trigger(self, agent_id: str, now: float) -> bool:
        # Depth limit
        if self.depth >= MAX_DEPTH:
            return False
        # Cooldown (100ms)
        if agent_id in self.cooldowns:
            if now - self.cooldowns[agent_id] < 0.1:
                return False
        return True

    def child_context(self, agent_id: str, now: float) -> "TriggerContext":
        """Create context for downstream triggers."""
        return TriggerContext(
            event_id=self.event_id,
            depth=self.depth + 1,
            cooldowns={**self.cooldowns, agent_id: now}
        )
```

### 1.10 Jujutsu for Overlay Filesystems

The key insight: **CST hierarchy maps to the same files**.

- A file agent and its function children all reference `main.py`
- No need for complex overlay - they're literally the same file
- Jujutsu tracks changes at the file level

One-way sync: Remora → Jujutsu (never reverse)

```bash
# After agent makes changes
jj status                    # See what changed
jj commit -m "Agent: func_format_date added timezone support"
```

Benefits:
- Full history of agent modifications
- Easy rollback if agent breaks something
- No merge conflicts (one-way sync)
- Human can review agent changes before accepting

---

## Part 2: Architecture

### 2.1 High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CST Agent Swarm (Reactive)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                         Swarm Runtime                               │     │
│  │                                                                     │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │     │
│  │  │   Agent     │  │   Agent     │  │   Agent     │   (dormant)    │     │
│  │  │  (file)     │  │  (func)     │  │  (class)    │                │     │
│  │  │             │  │             │  │             │                │     │
│  │  │ state.jsonl │  │ state.jsonl │  │ state.jsonl │                │     │
│  │  │ workspace.db│  │ workspace.db│  │ workspace.db│                │     │
│  │  │ subscriptions│ │ subscriptions│ │ subscriptions│               │     │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                │     │
│  │         │                │                │                        │     │
│  │         └────────────────┼────────────────┘                        │     │
│  │                          │                                         │     │
│  │  ┌───────────────────────┴───────────────────────────────────┐    │     │
│  │  │              SubscriptionRegistry + EventStore             │    │     │
│  │  │  ┌─────────────────┐  ┌─────────────┐  ┌───────────────┐  │    │     │
│  │  │  │ subscriptions.db │  │ events.db   │  │ TriggerQueue  │  │    │     │
│  │  │  │ (patterns)       │  │ (messages)  │  │ (agent,event) │  │    │     │
│  │  │  └─────────────────┘  └─────────────┘  └───────────────┘  │    │     │
│  │  └────────────────────────────────────────────────────────────┘    │     │
│  │                                                                     │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                      Existing Remora (Unchanged)                    │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │     │
│  │  │ AgentKernel │  │ Grail Tools │  │ Discovery   │  │ EventBus │ │     │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘ │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                         External (Optional)                         │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐│     │
│  │  │ Jujutsu VCS │  │ File Watcher│  │ Neovim Plugin               ││     │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────────┘│     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Details

#### SubscriptionRegistry (New: ~150 lines)

```python
@dataclass
class Subscription:
    id: str
    agent_id: str
    pattern: SubscriptionPattern
    created_at: float

class SubscriptionRegistry:
    """Manages agent subscriptions to events."""

    def __init__(self, db_path: Path):
        self._db = sqlite3.connect(db_path)
        self._cache: dict[str, list[Subscription]] = {}
        self._init_db()

    async def register(
        self,
        agent_id: str,
        pattern: SubscriptionPattern,
    ) -> str:
        """Register a subscription. Returns subscription_id."""
        sub_id = f"{agent_id}_{uuid4().hex[:8]}"
        # Persist to DB
        await self._insert(sub_id, agent_id, pattern)
        # Update cache
        if agent_id not in self._cache:
            self._cache[agent_id] = []
        self._cache[agent_id].append(Subscription(sub_id, agent_id, pattern, time.time()))
        return sub_id

    async def register_defaults(self, agent_id: str, metadata: AgentMetadata) -> None:
        """Register implicit subscriptions for a new agent."""
        # 1. Direct messages
        await self.register(agent_id, SubscriptionPattern(to_agent=agent_id))
        # 2. File changes
        await self.register(agent_id, SubscriptionPattern(
            event_types=["ContentChanged", "FileSaved"],
            path_glob=metadata.file_path
        ))

    async def unregister(self, subscription_id: str) -> None:
        """Remove a subscription."""
        ...

    async def unregister_all(self, agent_id: str) -> None:
        """Remove all subscriptions for an agent."""
        ...

    async def get_matching_agents(self, event: Event) -> list[str]:
        """Return agent_ids whose subscriptions match this event."""
        matching = set()
        for agent_id, subs in self._cache.items():
            for sub in subs:
                if sub.pattern.matches(event):
                    matching.add(agent_id)
                    break  # One match is enough
        return list(matching)

    async def get_subscriptions(self, agent_id: str) -> list[Subscription]:
        """Get all subscriptions for an agent."""
        return self._cache.get(agent_id, [])
```

#### EventStore Extension (Modify: ~50 lines)

Add trigger queue to existing EventStore:

```python
class EventStore:
    def __init__(
        self,
        db_path: Path,
        subscriptions: SubscriptionRegistry,
        event_bus: EventBus,
    ):
        self._db_path = db_path
        self._subscriptions = subscriptions
        self._event_bus = event_bus
        self._trigger_queue: asyncio.Queue[tuple[str, int, Event]] = asyncio.Queue()

    async def append(self, event: Event) -> int:
        """Append event and trigger matching subscriptions."""
        # 1. Persist event
        event_id = await self._insert(event)

        # 2. Find matching subscriptions
        matching_agents = await self._subscriptions.get_matching_agents(event)

        # 3. Queue triggers
        for agent_id in matching_agents:
            await self._trigger_queue.put((agent_id, event_id, event))

        # 4. Also emit to EventBus for UI updates
        await self._event_bus.emit(event)

        return event_id

    async def get_triggers(self) -> AsyncIterator[tuple[str, int, Event]]:
        """Yield (agent_id, event_id, event) as they arrive."""
        while True:
            yield await self._trigger_queue.get()
```

#### AgentState (New: ~80 lines)

```python
@dataclass
class AgentState:
    """Per-agent state stored in state.jsonl."""
    identity: AgentIdentity
    connections: dict[str, str]       # symbolic_name -> agent_id
    chat_history: list[Message]
    custom_subscriptions: list[SubscriptionPattern]  # Agent-defined subscriptions
    last_content_hash: str
    last_activated: float

    @classmethod
    def load(cls, path: Path) -> "AgentState":
        """Load from JSONL file."""

    def save(self, path: Path) -> None:
        """Save to JSONL file (append-only for history)."""
```

#### AgentRunner (New: ~120 lines)

Simplified - receives events instead of polling:

```python
class AgentRunner:
    """Runs agent turns in response to events."""

    def __init__(
        self,
        config: Config,
        event_store: EventStore,
        swarm_state: SwarmState,
    ):
        self.config = config
        self.event_store = event_store
        self.swarm_state = swarm_state

    async def run_loop(self) -> None:
        """Main event loop - process triggers as they arrive."""
        context = TriggerContext(event_id=0)

        async for agent_id, event_id, event in self.event_store.get_triggers():
            now = time.time()
            if context.can_trigger(agent_id, now):
                child_ctx = context.child_context(agent_id, now)
                await self._run_turn(agent_id, event, child_ctx)

    async def _run_turn(
        self,
        agent_id: str,
        triggering_event: Event,
        context: TriggerContext,
    ) -> TurnResult:
        """Run one turn for an agent."""
        # 1. Load state (no last_seen_event_id needed!)
        state = AgentState.load(self._state_path(agent_id))
        workspace = await self._get_workspace(agent_id)

        # 2. Build prompt with triggering event (not inbox query!)
        prompt = self._build_prompt(state, triggering_event)

        # 3. Run kernel (existing)
        kernel = self._create_kernel(agent_id, workspace)
        result = await kernel.run(
            messages=[
                Message(role="system", content=self._system_prompt(state)),
                Message(role="user", content=prompt),
            ],
            tools=self._get_tools(state)
        )

        # 4. Process outgoing messages from tool calls
        for tool_call in result.tool_calls:
            if tool_call.name == "send_message":
                # This will trigger other agents' subscriptions
                await self.event_store.append(AgentMessageEvent(
                    from_agent=agent_id,
                    to_agent=tool_call.args["to"],
                    action=tool_call.args["action"],
                    content=tool_call.args["content"],
                ))

        # 5. Save state
        state.last_activated = time.time()
        state.save(self._state_path(agent_id))

        return TurnResult(agent_id=agent_id, output=result.output)
```

#### SwarmState (New: ~100 lines)

```python
@dataclass
class SwarmState:
    """Global swarm state backed by SQLite."""
    db_path: Path
    agents: dict[str, AgentMetadata]  # agent_id -> metadata

    async def register_agent(self, agent_id: str, metadata: AgentMetadata) -> None:
        """Register a new agent."""

    async def get_agent(self, agent_id: str) -> AgentMetadata | None:
        """Get agent metadata."""

    async def list_agents(self, parent_id: str | None = None) -> list[AgentMetadata]:
        """List agents, optionally filtered by parent."""

    async def list_agents_for_file(self, path: Path) -> list[AgentMetadata]:
        """List agents that belong to a file."""

    async def mark_orphaned(self, agent_id: str) -> None:
        """Mark an agent as orphaned (source node deleted)."""
```

### 2.3 New Tools for Messaging

```python
# tools/send_message.py
"""Send a message to another agent."""

async def send_message(
    to_agent: str,      # agent_id, "parent", "broadcast:children"
    action: str,        # "request", "response", "notify"
    content: dict,
) -> dict:
    """
    Send a message to another agent. The message will trigger
    the recipient's subscriptions and run their turn.

    Special recipients:
    - "parent": Send to this agent's parent
    - "broadcast:children": Send to all child agents
    - "broadcast:siblings": Send to all sibling agents
    """
    # Resolved by AgentRunner before appending to EventStore
    return {"status": "sent", "to": to_agent}
```

```python
# tools/subscribe.py
"""Add a custom subscription."""

async def subscribe(
    event_types: list[str] | None = None,
    from_agents: list[str] | None = None,
    path_glob: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """
    Subscribe to events matching the given pattern.
    Your agent will be triggered when matching events arrive.

    Example: Subscribe to all test failures
        subscribe(event_types=["TestFailed"], tags=["unit"])
    """
    # Added to agent's custom_subscriptions in state.jsonl
    return {"status": "subscribed", "pattern": {...}}
```

---

## Part 3: File Structure

```
remora/
├── core/
│   ├── __init__.py
│   ├── agent.py              [KEEP] AgentKernel usage
│   ├── config.py             [KEEP]
│   ├── discovery.py          [KEEP]
│   ├── errors.py             [EXTEND] + SwarmError
│   ├── event_bus.py          [KEEP]
│   ├── event_store.py        [EXTEND] + trigger queue integration
│   ├── events.py             [EXTEND] + AgentMessageEvent, ContentChangedEvent
│   ├── subscriptions.py      [NEW] SubscriptionRegistry, SubscriptionPattern
│   ├── executor.py           [KEEP] Used for batch mode
│   ├── graph.py              [KEEP]
│   ├── workspace.py          [KEEP] AgentWorkspace
│   └── tools/
│       ├── grail.py          [KEEP]
│       ├── send_message.py   [NEW]
│       └── subscribe.py      [NEW]
│
├── swarm/                    [NEW] ~400 lines total
│   ├── __init__.py
│   ├── state.py              # SwarmState, AgentState
│   ├── runner.py             # AgentRunner (simplified)
│   └── reconciler.py         # Startup diff reconciliation
│
├── service/
│   ├── api.py                [KEEP]
│   ├── swarm_api.py          [NEW] Swarm HTTP endpoints
│   └── handlers.py           [KEEP]
│
└── adapters/
    └── starlette.py          [EXTEND] + swarm routes
```

**Total new code: ~450 lines** (vs ~400 in polling model, but simpler logic)

---

## Part 4: Implementation Plan

### Phase 1: SubscriptionRegistry

1. Create `subscriptions.py` with `SubscriptionPattern` and `SubscriptionRegistry`
2. Add SQLite persistence for subscriptions
3. Implement pattern matching logic

**Estimated: ~150 lines new**

### Phase 2: EventStore Integration

1. Add trigger queue to EventStore
2. Integrate subscription matching on `append()`
3. Add `get_triggers()` async iterator

**Estimated: ~50 lines changed**

### Phase 3: Agent State & Swarm State

1. Create `AgentState` with custom_subscriptions field
2. Create `SwarmState` for agent registry
3. Remove `last_seen_event_id` tracking

**Estimated: ~150 lines new**

### Phase 4: Agent Runner

1. Create `AgentRunner` with reactive event loop
2. Implement cascade prevention (cooldown + depth)
3. Wire up to EventStore triggers

**Estimated: ~120 lines new**

### Phase 5: Reconciler

1. Create startup reconciler
2. Register default subscriptions for new agents
3. Emit events for changed content

**Estimated: ~80 lines new**

### Phase 6: HTTP API & Demo

1. Add swarm endpoints to Starlette adapter
2. Build simple demo UI
3. Test with sample codebase

**Estimated: ~100 lines new**

---

## Part 5: API Reference

### Swarm Service Endpoints

```
POST   /swarm/start
  Body: { path: string }
  Response: { swarm_id: string, agent_count: number }

POST   /swarm/stop
  Body: { swarm_id: string }
  Response: { success: boolean }

GET    /swarm/agents
  Query: ?parent_id=X&status=active
  Response: { agents: AgentSummary[] }

GET    /swarm/agents/{id}
  Response: { agent: AgentDetail, subscriptions: Subscription[], state: AgentState }

GET    /swarm/agents/{id}/subscriptions
  Response: { subscriptions: Subscription[] }

POST   /swarm/agents/{id}/subscribe
  Body: { pattern: SubscriptionPattern }
  Response: { subscription_id: string }

DELETE /swarm/agents/{id}/subscriptions/{sub_id}
  Response: { success: boolean }

POST   /swarm/agents/{id}/chat
  Body: { message: string }
  Response: { response: string, tool_calls: ToolCall[] }

POST   /swarm/agents/{id}/trigger
  Body: { event: Event }
  Response: { turn_result: TurnResult }

GET    /swarm/events
  Query: ?since_id=X&agent_id=Y
  SSE stream of events
```

### Event Types

```python
@dataclass(frozen=True)
class AgentMessageEvent:
    """Message between agents."""
    from_agent: str
    to_agent: str           # agent_id, "parent", "broadcast:*"
    action: str             # "request", "response", "notify"
    content: dict[str, Any]
    correlation_id: str | None = None
    tags: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

@dataclass(frozen=True)
class ContentChangedEvent:
    """File content was modified."""
    agent_id: str
    path: str
    change_type: str        # "created", "modified", "deleted"
    timestamp: float = field(default_factory=time.time)

@dataclass(frozen=True)
class FileSavedEvent:
    """File was saved (from editor)."""
    path: str
    source: str             # "neovim", "vscode", "manual"
    timestamp: float = field(default_factory=time.time)
```

---

## Part 6: Key Insights

### Why Reactive > Polling

1. **Simpler Agent Code**
   - No inbox query logic
   - No `last_seen_event_id` tracking
   - Events are delivered, not fetched

2. **Better Performance**
   - O(events) subscription matching vs O(agents × events) polling
   - Immediate response vs polling interval delay

3. **Explicit Dependencies**
   - Subscriptions declare what each agent cares about
   - Easy to visualize and debug the event flow

4. **Natural Fit for Async Python**
   - `async for trigger in event_store.get_triggers()`
   - No timers or polling loops needed

### Trade-offs

| Approach | Latency | Complexity | Debuggability |
|----------|---------|------------|---------------|
| Continuous async | Low | High | Hard |
| Polling | Medium | Medium | Medium |
| **Reactive subscriptions** | **Low** | **Medium** | **Easy** |

### The Unified Model

```
Agent = CSTNode + Workspace + State + Subscriptions

Subscription = Pattern that triggers this agent

Turn = Event matched → Load → Run → Emit → Save

Swarm = Agents + EventStore + SubscriptionRegistry
```

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **Agent** | Workspace + state representing a CST node |
| **Subscription** | Pattern declaring which events trigger an agent |
| **Turn** | One activation cycle: event → load → process → save |
| **Trigger** | (agent_id, event) pair queued for execution |
| **Cascade** | Chain of agents triggering each other |
| **Cooldown** | Minimum time between triggers for same agent |

---

*Document version: 3.0*
*Status: Reactive Architecture - Ready for Implementation*
