# Clean-Slate Brainstorm — The Companion, Rebuilt from Nothing

> If we could change anything — remora core, AgentNode, the event model,
> the subscription system, the workspace, the agent topology, everything —
> how would we build the companion from scratch so it *is* remora, not
> something bolted onto remora?

---

## 3. Remora Primitives Inventory

Before designing the companion on remora's primitives, let's be precise about what those primitives actually are and what they're designed for.

### 3.1 `_FrozenEvent` — The event base class

```python
class _FrozenEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
```

That's the entire thing. A frozen Pydantic model. All domain events inherit from this. Events are immutable, serializable, and pattern-matchable. The `RemoraEvent` union type collects them all for type-checked pattern matching.

**What it's designed for:** Any immutable fact that happened in the system.

**What the companion needs:** Exactly this. Cursor moved, context extracted, search completed, sidebar composed — these are all immutable facts. No modification needed.

### 3.2 `EventStore` — The persistence and dispatch layer

SQLite-backed event store that:
- `append(graph_id, event)` — persists an event, triggers subscription matching, and enqueues matched agents
- `replay(graph_id, ...)` — replays events with filters (type, time range, after_id)
- `get_triggers()` — async iterator yielding `(agent_id, event_id, event)` for matched subscriptions

Key design: EventStore is both **storage** and **dispatch**. Appending an event automatically checks subscriptions and enqueues triggers. This is the reactive core.

**What it's designed for:** Persisting events for code-node agents, triggering agent execution when events match subscriptions.

**What the companion needs:** Exactly this — but with one wrinkle. EventStore currently requires a `graph_id` for every event. Code-node agents have a natural graph_id (the analysis run). What's the companion's graph_id? Options:
- A single long-lived graph_id per session (e.g., `"companion-session-{uuid}"`)
- A new graph_id per "focus episode" (each time the user focuses on a new code region)
- The graph_id concept doesn't apply — companion events aren't part of a graph execution

This needs a decision. For now, a session-level graph_id is simplest.

### 3.3 `SubscriptionPattern` — Declarative event matching

```python
class SubscriptionPattern(BaseModel):
    event_types: list[str] | None = None     # Match by event class name
    from_agents: list[str] | None = None     # Match by sender
    to_agent: str | None = None              # Match by recipient
    path_glob: str | None = None             # Match by file path
    tags: list[str] | None = None            # Match by event tags
```

All fields optional. `None` = match anything. Multiple values = OR.

**What it's designed for:** Routing events to code-node agents. An agent subscribes to changes in its own file (`path_glob`), direct messages (`to_agent`), or specific event types.

**What the companion needs:** Mostly this. But there's a gap: `path_glob` matches against `event.path` — a filesystem path. The companion wants to match against *workspace paths* like `/companion/context/structure`. These are logical paths in the workspace namespace, not filesystem paths.

Options:
- Overload `path_glob` to match workspace paths too (if the event has a `path` field that's a workspace path)
- Add a new field like `workspace_glob` to SubscriptionPattern
- Use `tags` to encode workspace path segments
- Don't use SubscriptionPattern for workspace routing — use a separate mechanism

The cleanest option might be to make workspace writes into events that have a `path` field, then `path_glob` naturally matches workspace paths. More on this in Section 6.

### 3.4 `SubscriptionRegistry` — Persistent subscription management

SQLite-backed registry that:
- Stores subscriptions as (agent_id, pattern_json, is_default)
- Provides `get_matching_agents(event)` with an in-memory cache indexed by event_type
- Supports default subscriptions (direct messages + source file changes)

**What it's designed for:** Managing code-node agent subscriptions that persist across restarts.

**What the companion needs:** The same thing. Companion event handlers register their subscriptions at startup. The registry matches incoming events and returns which handlers should fire. No modification needed — the companion just registers different patterns than code-node agents.

### 3.5 `AgentNode` — The code-node agent model

A single Pydantic model with fields for identity (`node_id`, `node_type`, `file_path`, `source_code`, `start_line`), graph context (`caller_ids`, `callee_ids`), runtime state (`status`), and specialization (`custom_system_prompt`, `extra_tools`, `extra_subscriptions`).

**What it's designed for:** Representing a discovered code entity (function, class, method, file) as an autonomous agent with LLM capabilities.

**What the companion needs:** This is the key tension. The companion doesn't have code entities. It has event handlers. See Section 4 for the full analysis.

### 3.6 `NodeProjection` — Event-to-state materialization

Not listed above, but referenced in EventStore. The projection applies events to materialized state (the `nodes` table). `NodeDiscoveredEvent` → upsert node. `NodeRemovedEvent` → delete node.

**What the companion needs:** This pattern — projecting events into materialized state — is exactly what the companion needs for its "workspace." But the companion's projection targets a different table (workspace state, not nodes). The pattern is right; the specific projection is different.

### Summary: What fits, what doesn't

| Primitive | Fits companion? | Notes |
|-----------|----------------|-------|
| `_FrozenEvent` | Yes, perfectly | All companion events become `_FrozenEvent` subclasses |
| `EventStore` | Yes, with graph_id decision | Need to pick a graph_id strategy for companion events |
| `SubscriptionPattern` | Yes, with workspace path consideration | `path_glob` could match workspace paths if events carry them |
| `SubscriptionRegistry` | Yes, as-is | Companion handlers register patterns like code-node agents do |
| `AgentNode` | **No** | Wrong abstraction for pipeline stages |
| `NodeProjection` | The *pattern* fits | Need a companion-specific projection for workspace state |

The verdict: **4 out of 5 primitives are directly usable.** AgentNode is the only one that doesn't fit, and we may not need it at all.

---


Strip away the implementation. Forget InMemoryWorkspace, AgentBase, CompanionRuntime, the 13 agent classes. What's left?

### The essence, in one sentence

**The companion is a reactive pipeline that transforms a stream of editor events into a continuously-updated contextual understanding of what the developer is working on.**

The sidebar is just a rendering of that understanding. The "agents" are just named stages in the pipeline. The workspace is just intermediate state between stages.

### Input → Processing → Output

```
INPUTS (from editor)          PROCESSING (reactive)              OUTPUT
─────────────────────         ─────────────────────              ──────
cursor position        ──→    extract context around cursor  ──→
file content edits     ──→    search for related code        ──→  contextual
file saves             ──→    find connections/patterns      ──→  sidebar
time passing           ──→    infer tasks, check claims      ──→  markdown
                              compose everything together    ──→
```

That's it. The companion is a **data-flow pipeline** with:
- **Sources**: editor events (cursor, edits, saves, time)
- **Transforms**: context extraction, semantic search, analysis, composition
- **Sink**: a rendered sidebar (markdown)

Each transform takes some combination of (editor events, previous transform outputs, indexed codebase) and produces structured data that flows downstream.

### What the 13 agents actually are

Let's categorize the current agents by their role in this pipeline:

| Agent | Pipeline Role | Input | Output |
|-------|--------------|-------|--------|
| **CursorTracker** | Source adapter | Raw cursor notifications | Debounced cursor events |
| **EditTracker** | Source adapter | Raw edit notifications | Structured edit events |
| **FileWatcher** | Source adapter | Filesystem events | File change events |
| **SessionClock** | Source adapter | Wall clock | Periodic tick events |
| **ContextExtractor** | Transform (stage 1) | Cursor position | Code structure, region, content type |
| **EditSummarizer** | Transform (stage 1) | Edit events | Edit summaries |
| **EmbeddingSearcher** | Transform (stage 2) | Context from stage 1 | Semantically related code chunks |
| **ConnectionFinder** | Transform (stage 3) | Search results | Connections between current code and results |
| **ClaimChecker** | Transform (stage 3) | Context from stage 1 | Verified/flagged claims in markdown |
| **TaskInferrer** | Transform (stage 3) | Context from stage 1 | Inferred developer tasks |
| **QuestionGenerator** | Transform (stage 3) | Context + connections | Interesting questions about the code |
| **SidebarComposer** | Sink | All transform outputs | Rendered sidebar markdown |
| **SessionSummarizer** | Sink (periodic) | Session history | Session summary |

This reveals something important: **the agents aren't peers**. They form a directed acyclic graph (DAG):

```
Sources:  CursorTracker  EditTracker  FileWatcher  SessionClock
              │              │             │            │
Stage 1:  ContextExtractor  EditSummarizer             │
              │    │    │       │                       │
Stage 2:  EmbeddingSearcher    │                       │
              │                │                       │
Stage 3:  ConnectionFinder  ClaimChecker               │
          TaskInferrer      QuestionGenerator           │
              │    │    │       │    │                  │
Sinks:    SidebarComposer              SessionSummarizer
```

The current implementation obscures this DAG with uniform `AgentBase` subclasses and `_on_path_change()` routing. A clean-slate design should make the DAG explicit.

### The companion is NOT a swarm

The code-node agent system is a **swarm** — hundreds or thousands of agents (one per code entity) that can talk to each other, self-modify, and exhibit emergent behavior. That's the right model for code understanding: each function is an autonomous agent that knows its own body and can reason about changes.

The companion is NOT that. It's a **pipeline** — a small, fixed topology of transforms that process a stream. The transforms don't talk to each other peer-to-peer; data flows in one direction through stages. There's no emergence from agent-to-agent communication; there's deterministic data transformation.

This distinction matters for the design. Trying to build a pipeline with swarm primitives is like using a message queue to implement a function call — technically possible but architecturally confused.

### So what do we actually need?

1. **Event sources** that produce typed events from editor actions
2. **Event handlers** that subscribe to specific event types, perform transforms, and emit new events
3. **A subscription system** that routes events to the right handlers
4. **A persistence layer** that stores all events for replay and debugging
5. **A projection** that materializes the current state from the event stream (the "sidebar")
6. **An indexing service** (embeddy) that provides semantic search over the codebase

That's remora's primitives. EventStore, SubscriptionPattern, `_FrozenEvent`. The companion doesn't need AgentBase, WorkspaceInterface, InMemoryWorkspace, or CompanionRuntime. It needs event handlers registered with the subscription system.

---


Our previous planning (D1-D7, PLAN.md) was incremental: take the existing 13-agent companion, migrate its events to `_FrozenEvent`, swap its workspace for an EventStore-backed one, replace its indexing with embeddy, and move the package. That plan preserved all 177 tests, all 13 agents, all workspace paths. It was a bridge — keep behavior identical, change the plumbing.

But a bridge assumes the existing shape is worth preserving. Is it?

The companion was built as a **demo** — proof that reactive agents could produce a useful sidebar. It was built *outside* remora's primitives because those primitives didn't exist yet when the companion was first written. The result is two parallel systems:

| Concern | Remora Core | Companion Demo |
|---------|-------------|----------------|
| Events | `_FrozenEvent` (Pydantic, frozen, in EventStore) | frozen dataclasses (in-memory only) |
| Routing | `SubscriptionPattern` + `SubscriptionRegistry` | manual `_on_path_change()` if/elif |
| State | EventStore (SQLite, persistent, replayable) | `InMemoryWorkspace` (volatile dict) |
| Agents | `AgentNode` (code-node, single model) | `AgentBase` ABC with 13 subclasses |
| Communication | Events via EventStore | Workspace writes + listener callbacks |
| Indexing | N/A | Hand-rolled sync stack |

The incremental plan says: migrate column by column, keeping the shape. The clean-slate question says: **if we were building this today, knowing what remora's primitives are, would we build it this way at all?**

The answer is almost certainly no. And so this document asks: what *would* we build?

### What "clean slate" means here

- We can change anything in the companion — agents, events, workspace, runtime, agent topology.
- We can change things in remora core if the companion's needs reveal genuine generalizations (e.g., if AgentNode should accommodate non-code agents).
- We are NOT rewriting remora from scratch. Core is stable and correct. We're asking how the companion should be built *on top of* (or *into*) core.
- The 177 existing tests are useful as behavioral documentation but not as a constraint. If the design says "3 event handlers, no agents," the tests get rewritten.
- Embeddy is the indexing layer from day one. Not a migration target — the starting point.

### The real question

> If the companion is a first-class part of remora — not a demo bolted on top — what does it look like when it's *native*? When it uses the same primitives, follows the same patterns, and exists in the same conceptual space as the code-node agent system?

---


1. [The Question](#1-the-question) — Why "clean slate" and not "incremental migration." What we're really asking.

2. [What IS the Companion?](#2-what-is-the-companion) — Strip away 13 agents, the workspace, the runtime. What's the essence? A reactive pipeline that transforms editor events into continuously-updated contextual understanding.

3. [Remora Primitives Inventory](#3-remora-primitives-inventory) — What remora core already provides: EventStore, SubscriptionPattern, _FrozenEvent, AgentNode, projections. What's load-bearing vs. accidental.

4. [The AgentNode Question](#4-the-agentnode-question) — AgentNode is for code-node agents. Companion agents aren't code nodes. Do we: (a) generalize AgentNode, (b) create a parallel model, or (c) realize that the companion doesn't need "agents" at all?

5. [Events as the Universal Substrate](#5-events-as-the-universal-substrate) — Everything is an event. Editor actions, workspace writes, search results, sidebar updates. No side channels. No in-memory-only state that matters.

6. [Workspace as Event Projection](#6-workspace-as-event-projection) — The workspace isn't a key-value store. It's a materialized view of the event log. Reads are projections. Writes are events. The InMemoryWorkspace was a prototype; the real workspace IS EventStore.

7. [Agent Topology — From 13 Agents to What?](#7-agent-topology--from-13-agents-to-what) — Do we need 13 agents? 5? 3? Zero named agents and just event handlers? What's the right decomposition when you're building natively on event-driven primitives?

8. [The Reactive Pipeline — Built from Scratch](#8-the-reactive-pipeline--built-from-scratch) — Forget CompanionRuntime. How does data flow from cursor-move to sidebar-update through pure event cascades and subscription matching?

9. [Embeddy as Native Indexing](#9-embeddy-as-native-indexing) — Embeddy isn't a replacement for the companion's indexing layer. It's the indexing layer from day one. How does it integrate natively?

10. [What Changes in Core Remora?](#10-what-changes-in-core-remora) — A clean slate might require generalizing core primitives. What would need to change in EventStore, SubscriptionPattern, or AgentNode to natively support both code-node and reactive-pipeline use cases?

11. [The Clean-Slate Architecture](#11-the-clean-slate-architecture) — Putting it all together: the concrete design. Event types, subscription patterns, data flow, module structure.

12. [Open Questions](#12-open-questions) — Unresolved tensions and things we need to decide before writing code.

---

## 4. The AgentNode Question

This is the central design tension. Let's work through it carefully.

### The problem

`AgentNode` is remora's single agent model. The philosophy says: "No subclasses. Specialization via data." Every agent in remora IS an AgentNode — a discovered code entity with source code, line numbers, caller/callee relationships, LLM system prompts, and tools.

The companion's "agents" are not code entities. They're pipeline stages. CursorTracker doesn't have source code (well, it does — its own Python implementation — but that's not what it *tracks*). SidebarComposer doesn't have caller_ids. They don't need LLM system prompts because they don't call LLMs.

Our D1 decision said: "thin bridge — don't force companion agents into AgentNode." That was the incremental answer. But a clean slate asks a deeper question: **should we even think of companion pipeline stages as "agents"?**

### Three options

#### Option A: Generalize AgentNode

Make AgentNode flexible enough to represent both code-node agents and pipeline stages.

```python
class AgentNode(BaseModel):
    node_id: str
    node_type: str          # "function", "class", "method", "pipeline_stage", "sensor"
    name: str
    # Code-node fields (optional for non-code agents)
    file_path: str = ""
    source_code: str = ""
    start_line: int = 0
    end_line: int = 0
    # ... etc
```

**Problem:** This violates the spirit of AgentNode. Making half the fields optional or meaningless for companion stages means the model is trying to be two things. "Specialization via data" works when the data dimensions are shared — all code nodes have source code, lines, callers. Pipeline stages don't share these dimensions. You'd end up with a god-model that's half-empty depending on the node type.

**Verdict:** Reject. AgentNode is for code-node agents. It's good at that. Don't dilute it.

#### Option B: Create a parallel model for pipeline stages

```python
class PipelineStage(BaseModel):
    stage_id: str
    stage_type: str          # "source", "transform", "sink"
    name: str
    subscriptions: list[SubscriptionPattern]
    handler: Callable
    # ...
```

**Problem:** Now we have two agent models. The "single agent model" philosophy is broken. The subscription registry, EventStore triggers, and event dispatch all need to handle both. We've essentially forked the system.

**Verdict:** Possible but philosophically uncomfortable. It's the "thin bridge" approach from D1, just made explicit as a model.

#### Option C: The companion doesn't have "agents" — it has event handlers

This is the radical option. What if the companion doesn't use AgentNode *or* a parallel model? What if it's just:

```python
# Register a handler function with a subscription pattern
await registry.register(
    agent_id="companion.context_extractor",
    pattern=SubscriptionPattern(event_types=["CompanionCursorMoved"]),
)

# The handler is a plain async function
async def extract_context(event: CompanionCursorMoved, event_store: EventStore) -> None:
    context = analyze_code_at(event.file, event.line)
    await event_store.append(session_id, CompanionContextExtracted(
        file=event.file,
        line=event.line,
        structure=context.structure,
        content_type=context.content_type,
    ))
```

No AgentBase. No PipelineStage model. No agent classes at all. Just:
1. Event types (`_FrozenEvent` subclasses)
2. Handler functions (plain async functions)
3. Subscription registrations (connecting handlers to event patterns)
4. EventStore (persistence + dispatch)

The "agent_id" in the subscription registry is just a string identifier for routing purposes. It doesn't correspond to an object in memory, a row in a table, or a class instance. It's a name for a handler.

**This is the most aligned with remora's ethos.** Remora says: "Emergent behavior from simple rules. Each agent is small and focused." The simplest possible "agent" is a function that reacts to an event and emits new events. No base class, no lifecycle, no state machine — just a function.

**But wait — what about state?**

Code-node agents have state in the nodes table (status, last_trigger_event). Companion handlers need state too — at minimum, the current context, the latest search results, the composed sidebar. Where does that state live?

Answer: **in the event log.** The current context IS the most recent `CompanionContextExtracted` event. The latest search results ARE the most recent `CompanionSearchCompleted` event. The sidebar IS the most recent `CompanionSidebarComposed` event. You don't need a workspace or a state store — you need a way to query "what's the most recent event of type X?"

This is event sourcing taken seriously. State is a projection of the event stream.

### The recommendation: Option C

**The companion should not have "agents" in the remora sense.** It should have:

1. **Event types** — `_FrozenEvent` subclasses for every stage output
2. **Handler functions** — async functions that subscribe to events and emit events
3. **Subscriptions** — `SubscriptionPattern` registrations connecting handlers to event types
4. **Projections** — functions that materialize "current state" from the event stream (for efficiency)

This means the companion is built entirely from remora's existing primitives. No new abstractions. No AgentBase. No WorkspaceInterface. No CompanionRuntime. Just events, handlers, and subscriptions — the same way code-node agents work, but without the AgentNode wrapper because there's no code entity to wrap.

The `agent_id` strings in the registry (`"companion.context_extractor"`, `"companion.sidebar_composer"`) are just routing labels. They let EventStore's trigger queue know which handler to call. They're not objects.

---

## 5. Events as the Universal Substrate

If the companion is built on events, we need to design the event types carefully. Every piece of data that flows through the pipeline is an event.

### Design principle: Events are facts, not commands

An event records that something happened. It doesn't tell anyone to do anything. The subscription system handles routing — the event itself is just data.

```python
# Good: records a fact
class CompanionContextExtracted(_FrozenEvent):
    file: str
    line: int
    structure_type: str    # "function", "class", "module"
    structure_name: str
    content_type: str      # "python", "markdown", "unknown"
    surrounding_code: str

# Bad: encodes a command
class ExtractContextCommand(_FrozenEvent):  # Don't do this
    target_file: str
    target_line: int
```

When `CompanionContextExtracted` is appended to EventStore, the subscription system automatically routes it to any handler that subscribes to that event type. The handler that does embedding search doesn't need to know *who* extracted the context or *why* — it just reacts to the fact that context was extracted.

### The complete event vocabulary

Here's every event type the companion needs, organized by pipeline stage:

#### Source events (from editor)

These already exist in remora core or need minimal additions:

```python
# Already exists in remora core:
class CursorFocusEvent(_FrozenEvent):       # cursor moved (debounced)
class ContentChangedEvent(_FrozenEvent):     # file content modified
class FileSavedEvent(_FrozenEvent):          # file saved to disk

# New — companion-specific sources:
class CompanionSessionTick(_FrozenEvent):
    """Periodic heartbeat for time-based processing."""
    elapsed_ms: int
    tick_number: int
    timestamp: float = Field(default_factory=time.time)
```

Note: We reuse core's `CursorFocusEvent`, `ContentChangedEvent`, and `FileSavedEvent` directly. The companion doesn't need its own cursor/edit events. This is a key advantage of being native — the same events that trigger code-node agents also trigger companion handlers.

#### Stage 1 events (context extraction)

```python
class CompanionContextExtracted(_FrozenEvent):
    """Context around the cursor was analyzed."""
    file: str
    line: int
    structure_type: str          # "function", "class", "module", "section"
    structure_name: str
    content_type: str            # "python", "markdown", "toml", etc.
    surrounding_code: str        # The code/text around the cursor
    scope_path: tuple[str, ...]  # e.g., ("module", "MyClass", "my_method")
    timestamp: float = Field(default_factory=time.time)

class CompanionEditSummary(_FrozenEvent):
    """A batch of recent edits was summarized."""
    file: str
    summary: str
    edit_count: int
    lines_changed: int
    timestamp: float = Field(default_factory=time.time)
```

#### Stage 2 events (search)

```python
class CompanionSearchCompleted(_FrozenEvent):
    """Semantic search returned results for the current context."""
    query: str
    results: tuple[CompanionSearchResult, ...]  # Frozen tuple of results
    search_type: str             # "vector", "fulltext", "hybrid"
    timestamp: float = Field(default_factory=time.time)

class CompanionSearchResult(_FrozenEvent):
    """A single search result (nested in CompanionSearchCompleted)."""
    file: str
    chunk_text: str
    score: float
    start_line: int = 0
    end_line: int = 0
```

#### Stage 3 events (analysis)

```python
class CompanionConnectionsFound(_FrozenEvent):
    """Connections between current context and search results were identified."""
    connections: tuple[CompanionConnection, ...]
    timestamp: float = Field(default_factory=time.time)

class CompanionConnection(_FrozenEvent):
    """A single connection (nested)."""
    source: str           # Current context reference
    target: str           # Related code reference
    relationship: str     # "calls", "imports", "similar_to", "shares_pattern"
    confidence: float

class CompanionTaskInferred(_FrozenEvent):
    """A developer task was inferred from context."""
    task_description: str
    confidence: float
    evidence: tuple[str, ...]
    timestamp: float = Field(default_factory=time.time)

class CompanionClaimsChecked(_FrozenEvent):
    """Claims in markdown content were verified."""
    claims: tuple[CompanionClaim, ...]
    timestamp: float = Field(default_factory=time.time)

class CompanionClaim(_FrozenEvent):
    """A single claim check result (nested)."""
    claim_text: str
    status: str           # "verified", "unverified", "contradicted"
    evidence: str

class CompanionQuestionsGenerated(_FrozenEvent):
    """Interesting questions about the current context were generated."""
    questions: tuple[str, ...]
    timestamp: float = Field(default_factory=time.time)
```

#### Sink events (output)

```python
class CompanionSidebarComposed(_FrozenEvent):
    """The sidebar was recomposed from current state."""
    markdown: str
    sections: tuple[str, ...]    # Section names present in the sidebar
    timestamp: float = Field(default_factory=time.time)

class CompanionSessionSummary(_FrozenEvent):
    """Periodic session summary was generated."""
    summary: str
    duration_ms: int
    events_processed: int
    timestamp: float = Field(default_factory=time.time)
```

#### Indexing events

```python
class CompanionIndexUpdated(_FrozenEvent):
    """A file was indexed or re-indexed."""
    file: str
    chunks_added: int
    chunks_removed: int
    chunks_unchanged: int
    timestamp: float = Field(default_factory=time.time)
```

### Event count: from 5 dataclasses to ~14 frozen events

The current companion has 5 event types (CursorMoved, ContentEdited, FileChanged, SessionTick, PathChanged). The clean-slate design has ~14 (reusing 3 from core). But PathChanged disappears entirely — it was an artifact of workspace-based communication. Now everything is an explicit, typed event.

This is more events, but each one carries precise, typed data. No more `PathChanged(path="/companion/context/structure", value="function")` where the semantics are in the path string. Instead: `CompanionContextExtracted(structure_type="function", ...)` where the semantics are in the type and fields.

### The key insight: events replace the workspace

In the current companion, agents communicate by writing to workspace paths and subscribing to path changes. Agent A writes to `/companion/context/structure`, Agent B subscribes to `/companion/context/*` and reads the value.

In the clean-slate design, Agent A emits `CompanionContextExtracted(structure_type="function")` and Agent B subscribes to `CompanionContextExtracted` events. The data is IN the event, not in a separate store that the event points to.

This eliminates the workspace entirely for inter-handler communication. The workspace was a side channel — events are the real channel.

---

## 6. Workspace as Event Projection

If events replace the workspace for inter-handler communication, do we still need a "workspace" at all?

### What the workspace currently does

In the current companion, `InMemoryWorkspace` serves three purposes:

1. **Inter-agent communication**: Agent A writes to `/companion/context/structure`, Agent B reads it. → **Replaced by events.** Data is in the event itself.

2. **Current-state query**: "What's the current context?" → read `/companion/context/structure`. → **Replaced by "most recent event" query.** What's the latest `CompanionContextExtracted`?

3. **Sidebar source data**: `SidebarComposer` reads from multiple workspace paths to compose the sidebar. → **Replaced by querying recent events.** The composer handler reads the latest event of each relevant type.

So the workspace as a separate data store is unnecessary. But the *need* it serves — "give me the current state" — remains.

### The projection pattern

Remora core already has this pattern. `NodeProjection` projects `NodeDiscoveredEvent` into the `nodes` table. The nodes table is a materialized view of the event stream — you could delete it and rebuild it by replaying events.

The companion needs the same thing: a materialized view of "current companion state" built from the event stream. But it's simpler than the nodes table because the companion's state is just "the most recent event of each type."

```python
class CompanionState:
    """Materialized view of companion state, built from events.
    
    This is NOT a workspace. It's a read-only projection of the event log.
    Handlers don't write to it — they emit events, and the projection
    updates itself.
    """
    
    def __init__(self) -> None:
        self._latest: dict[str, _FrozenEvent] = {}
    
    def apply(self, event: _FrozenEvent) -> None:
        """Update projection with a new event."""
        event_type = type(event).__name__
        if event_type.startswith("Companion"):
            self._latest[event_type] = event
    
    @property
    def context(self) -> CompanionContextExtracted | None:
        return self._latest.get("CompanionContextExtracted")
    
    @property
    def search_results(self) -> CompanionSearchCompleted | None:
        return self._latest.get("CompanionSearchCompleted")
    
    @property
    def sidebar(self) -> CompanionSidebarComposed | None:
        return self._latest.get("CompanionSidebarComposed")
    
    # ... etc for each event type
```

This projection is:
- **Read-only** — handlers never write to it directly; they emit events
- **Derived** — it's purely a function of the event stream
- **Rebuildable** — delete and replay events to reconstruct
- **In-memory** — no persistence needed because EventStore has the events

### Do handlers need to read current state?

Yes. The sidebar composer needs to read the current context, search results, connections, etc. to compose the sidebar. In the current system, it reads workspace paths. In the clean-slate design, it reads from the projection.

But here's the question: **should the handler receive the triggering event only, or should it also have access to the current state?**

Option A: **Event-only handlers** — each handler receives only the triggering event and must query EventStore for any additional state it needs.

```python
async def compose_sidebar(event: CompanionContextExtracted, store: EventStore) -> None:
    # Need to query for latest search results, connections, etc.
    recent = await store.replay(session_id, event_types=["CompanionSearchCompleted"], ...)
    # Compose from event + queried state
```

Option B: **Handlers receive event + state projection** — the dispatch system passes both the triggering event and a `CompanionState` snapshot.

```python
async def compose_sidebar(
    event: CompanionContextExtracted, 
    state: CompanionState,
    store: EventStore,
) -> None:
    # State projection has latest everything
    search = state.search_results
    connections = state.connections
    # Compose from event + state
```

**Option B is better.** It avoids redundant EventStore queries, keeps handlers simple, and is how projections are meant to be used. The state projection is updated after every event append (inside EventStore's append flow, just like NodeProjection), so it's always current.

### Workspace = gone

In the clean-slate design:
- `InMemoryWorkspace` → deleted
- `WorkspaceInterface` → deleted
- `EventStoreWorkspace` (from D3) → never created
- `PathChanged` event → deleted
- `/companion/context/*` paths → replaced by typed event fields
- `_on_path_change()` routing → replaced by SubscriptionPattern matching

The "workspace" is replaced by:
1. **Events** carrying data between handlers (push)
2. **CompanionState** projection for querying current state (pull)

This is simpler, more aligned with remora's ethos, and eliminates an entire abstraction layer.

---

## 7. Agent Topology — From 13 Agents to What?

The current companion has 13 agents. The embeddy brainstorm proposed consolidating to 5. Our BRAINSTORM_REVIEW.md said "too aggressive for Phase 1." But this is a clean slate — what's the right number?

### The real question: what are the independent concerns?

An "agent" (or handler, in our clean-slate language) should exist when there's an independent concern that:
1. Has its own subscription pattern (reacts to specific events)
2. Produces its own event type (outputs specific data)
3. Has independent activation timing (shouldn't be coupled to other handlers)

Let's evaluate each current agent:

#### Sensors: CursorTracker, EditTracker, FileWatcher, SessionClock

These are **source adapters** — they convert external signals into events. In the clean-slate design, they're not agents or handlers. They're integration code that calls `event_store.append()`.

- **CursorTracker**: Receives raw cursor notifications from LSP, debounces, emits `CursorFocusEvent`. This is the LSP integration layer, not a companion agent. It already exists in remora core (the LSP server already emits `CursorFocusEvent`).
- **EditTracker**: Same — the LSP server receives `textDocument/didChange` and could emit `ContentChangedEvent` directly.
- **FileWatcher**: Watches filesystem, emits `FileSavedEvent`. This is infrastructure, not companion logic.
- **SessionClock**: Periodic timer that emits `CompanionSessionTick`. This is a simple `asyncio.create_task(tick_loop())`.

**Verdict: 0 handlers needed.** These become thin integration code in the LSP server or a companion startup function. No agent classes, no subscriptions — just code that calls `event_store.append()`.

#### Stage 1: ContextExtractor, EditSummarizer

These are real transforms:

- **ContextExtractor**: Subscribes to `CursorFocusEvent`, analyzes code at cursor position (reads file, finds enclosing function/class, identifies content type), emits `CompanionContextExtracted`. This is a real handler with real logic.
- **EditSummarizer**: Subscribes to `ContentChangedEvent`, accumulates edits, produces periodic summaries as `CompanionEditSummary`. This is a real handler.

**Verdict: 2 handlers.** But could they merge? They have different triggers (`CursorFocusEvent` vs `ContentChangedEvent`) and different outputs. Keeping them separate respects the "small and focused" principle.

#### Stage 2: EmbeddingSearcher

- **EmbeddingSearcher**: Subscribes to `CompanionContextExtracted`, uses the context to build a search query, calls embeddy's SearchService, emits `CompanionSearchCompleted`.

**Verdict: 1 handler.** Clear, focused, independent.

#### Stage 3: ConnectionFinder, ClaimChecker, TaskInferrer, QuestionGenerator

These all subscribe to stage 1/2 outputs and produce analysis:

- **ConnectionFinder**: Subscribes to `CompanionSearchCompleted`, finds relationships between current code and search results, emits `CompanionConnectionsFound`.
- **ClaimChecker**: Subscribes to `CompanionContextExtracted` (specifically for markdown content), verifies claims, emits `CompanionClaimsChecked`.
- **TaskInferrer**: Subscribes to `CompanionContextExtracted`, infers what the developer is doing, emits `CompanionTaskInferred`.
- **QuestionGenerator**: Subscribes to `CompanionContextExtracted` + `CompanionConnectionsFound`, generates questions, emits `CompanionQuestionsGenerated`.

These are the most debatable. Are they independent concerns or could they merge?

Analysis:
- ConnectionFinder depends on search results (stage 2). The others depend on context (stage 1).
- ClaimChecker only fires for markdown content. The others fire for all content.
- TaskInferrer and QuestionGenerator have similar triggers but different outputs.

**Two options:**

**Option 1: Keep them separate (4 handlers).** Respects "small and focused." Each handler is a pure function: event in, event out. Easy to test, easy to understand, easy to disable individually.

**Option 2: Merge into 1-2 handlers.** Reduce dispatching overhead. But merging ClaimChecker (markdown-only) with TaskInferrer (all content) creates branching logic inside the handler — which is the anti-pattern we're trying to eliminate.

**Verdict: Keep separate.** 4 handlers for stage 3. The overhead of 4 subscription registrations is negligible compared to the clarity of separation.

#### Sinks: SidebarComposer, SessionSummarizer

- **SidebarComposer**: Subscribes to all companion events (context, search, connections, claims, tasks, questions), reads from CompanionState projection, composes sidebar markdown, emits `CompanionSidebarComposed`.
- **SessionSummarizer**: Subscribes to `CompanionSessionTick`, summarizes the session, emits `CompanionSessionSummary`.

**Verdict: 2 handlers.**

#### Indexing: (new) IndexingHandler

- Subscribes to `FileSavedEvent`, calls embeddy's Pipeline, emits `CompanionIndexUpdated`.

**Verdict: 1 handler.**

### The clean-slate topology

```
                             SOURCES (integration code, not handlers)
                    LSP server / tick loop / file watcher
                    emit: CursorFocusEvent, ContentChangedEvent,
                          FileSavedEvent, CompanionSessionTick
                                    │
                    ┌───────────────┼───────────────────┐
                    │               │                   │
            ┌───────▼──────┐ ┌─────▼──────┐  ┌────────▼────────┐
STAGE 1:    │  context_     │ │  edit_      │  │  indexing_       │
            │  extractor    │ │  summarizer │  │  handler         │
            └───────┬──────┘ └─────┬──────┘  └────────┬────────┘
                    │              │                   │
            emits:  │         emits:              emits:
     ContextExtracted    EditSummary          IndexUpdated
                    │              │
        ┌───────┬──┴──┬────────┐  │
        │       │     │        │  │
  ┌─────▼──┐ ┌─▼───┐ ┌▼─────┐ ┌▼─▼──────┐
  │ search │ │claim│ │task  │ │question  │
  │ handler│ │check│ │infer │ │generator │
  └───┬────┘ └──┬──┘ └──┬──┘ └────┬─────┘
      │         │       │         │
  ┌───▼────┐    │       │         │
  │connect │    │       │         │
  │finder  │    │       │         │
  └───┬────┘    │       │         │
      │         │       │         │
      └────┬────┴───┬───┴─────────┘
           │        │
    ┌──────▼──────┐ ┌──▼───────────┐
    │  sidebar    │ │  session     │
    │  composer   │ │  summarizer  │
    └─────────────┘ └──────────────┘

Total: 10 handlers (down from 13 agents)
Removed: CursorTracker, EditTracker, FileWatcher, SessionClock (became integration code)
Added: indexing_handler (new)
```

That's 10 handlers — but 4 of the original 13 weren't doing companion-specific work at all (they were source adapters). The actual pipeline logic went from 9 agents to 10 handlers (+1 for indexing).

### But do we even need all 10?

Honest assessment of the stage 3 handlers:

- **ClaimChecker**: Only useful for markdown. How often is the user in markdown? Maybe 10% of the time. Is this core to "understanding what the developer is working on"? Debatable.
- **QuestionGenerator**: Interesting but speculative. Are the generated questions actually useful? Unclear.
- **TaskInferrer**: Could be very useful but is currently pure heuristics (no LLM). How good are the inferences?

These three could be dropped in a minimal v1 and added back when they prove their value. The **essential** pipeline is:

```
CursorFocusEvent → context_extractor → CompanionContextExtracted
                                            │
                                            ▼
                                    search_handler → CompanionSearchCompleted
                                            │
                                            ▼
                                    connection_finder → CompanionConnectionsFound
                                            │
                                            ▼
                                    sidebar_composer → CompanionSidebarComposed
```

Plus `indexing_handler` (reacts to file saves) and `edit_summarizer` (reacts to edits).

**Minimal v1: 6 handlers.** Expandable to 10 by adding claim_checker, task_inferrer, question_generator, and session_summarizer.

---

## 8. The Reactive Pipeline — Built from Scratch

Forget CompanionRuntime. Let's trace exactly how data flows from a cursor movement to a sidebar update, using only remora primitives.

### The setup (once, at startup)

```python
async def start_companion(event_store: EventStore, registry: SubscriptionRegistry) -> CompanionDispatcher:
    """Initialize the companion pipeline."""
    
    # Create the state projection
    state = CompanionState()
    
    # Create the embeddy indexing service
    indexing = IndexingService(embeddy_config)
    
    # Register all handlers with their subscription patterns
    handlers = {
        "companion.context_extractor": ContextExtractorHandler(),
        "companion.edit_summarizer": EditSummarizerHandler(),
        "companion.search": SearchHandler(indexing),
        "companion.connection_finder": ConnectionFinderHandler(),
        "companion.sidebar_composer": SidebarComposerHandler(),
        "companion.indexing": IndexingHandler(indexing),
    }
    
    # Register subscription patterns
    await registry.register(
        "companion.context_extractor",
        SubscriptionPattern(event_types=["CursorFocusEvent"]),
    )
    await registry.register(
        "companion.edit_summarizer",
        SubscriptionPattern(event_types=["ContentChangedEvent"]),
    )
    await registry.register(
        "companion.search",
        SubscriptionPattern(event_types=["CompanionContextExtracted"]),
    )
    await registry.register(
        "companion.connection_finder",
        SubscriptionPattern(event_types=["CompanionSearchCompleted"]),
    )
    await registry.register(
        "companion.sidebar_composer",
        SubscriptionPattern(event_types=[
            "CompanionContextExtracted",
            "CompanionSearchCompleted",
            "CompanionConnectionsFound",
            "CompanionEditSummary",
        ]),
    )
    await registry.register(
        "companion.indexing",
        SubscriptionPattern(event_types=["FileSavedEvent"]),
    )
    
    # Return a dispatcher that routes triggers to handlers
    return CompanionDispatcher(event_store, state, handlers)
```

### The dispatch loop

EventStore already has a trigger queue. When an event is appended, it checks subscriptions and enqueues `(agent_id, event_id, event)` tuples. We need something to drain that queue and call the right handler.

For code-node agents, `SwarmExecutor` does this. For the companion, we need a simpler dispatcher:

```python
class CompanionDispatcher:
    """Drains EventStore triggers and calls companion handlers."""
    
    def __init__(
        self,
        event_store: EventStore,
        state: CompanionState,
        handlers: dict[str, CompanionHandler],
    ) -> None:
        self._store = event_store
        self._state = state
        self._handlers = handlers
    
    async def run(self) -> None:
        """Main dispatch loop — runs until cancelled."""
        async for agent_id, event_id, event in self._store.get_triggers():
            # Update state projection
            self._state.apply(event)
            
            # Find and call the handler
            handler = self._handlers.get(agent_id)
            if handler is None:
                continue
            
            # Call handler with event + state
            new_events = await handler.handle(event, self._state)
            
            # Append any emitted events (which triggers further dispatching)
            for new_event in new_events:
                await self._store.append(self._session_id, new_event)
```

**Wait — there's a problem.** EventStore's trigger queue is shared between code-node agents and companion handlers. The `SwarmExecutor` drains the same queue. If both are running, they'll fight over triggers.

This is a real architectural issue. Options:

1. **Separate trigger queues**: EventStore supports multiple consumers, each getting their own copy of triggers. Companion handlers get companion-prefixed triggers, SwarmExecutor gets code-node triggers.

2. **Single dispatcher for everything**: Replace SwarmExecutor's trigger consumption with a unified dispatcher that routes to both code-node agents and companion handlers.

3. **Companion uses its own EventStore**: The companion creates a second EventStore instance with its own SQLite database. Events from the editor are appended to both. The companion's trigger queue is independent.

4. **Companion subscribes to events via EventBus, not trigger queue**: EventStore already has an EventBus (`self._event_bus`) that broadcasts events after append. Companion handlers subscribe to the EventBus (in-memory pub/sub) instead of the trigger queue.

**Option 4 is interesting.** The trigger queue is designed for "run this agent" semantics (SwarmExecutor pulls triggers and executes LLM agents). Companion handlers are lighter — they're just functions that transform data. They don't need the full trigger-queue → agent-execution pipeline. An EventBus listener that pattern-matches and calls handlers directly is simpler.

But this creates two routing paths: trigger queue for code-node agents, EventBus for companion handlers. That's two systems doing similar things.

**Option 2 is the most aligned** with "single system, no parallel implementations." A unified dispatcher that handles both code-node agent execution and companion handler invocation. SwarmExecutor becomes a client of this dispatcher, not the dispatcher itself.

But this is a significant core refactor. For a clean slate, it might be worth it. For a practical first step, Option 4 (EventBus) is simpler.

**Recommendation for the brainstorm**: Design for Option 2 conceptually (unified dispatch), but implement using Option 4 (EventBus) initially. The companion registers an EventBus listener that pattern-matches events and calls handlers. This is lighter than the trigger queue, doesn't interfere with SwarmExecutor, and can be migrated to unified dispatch later.

### Tracing a cursor movement through the pipeline

Let's trace a complete flow:

```
1. User moves cursor to line 42 of src/main.py
   
2. LSP server receives textDocument/didFocus (or similar)
   → Calls event_store.append(session_id, CursorFocusEvent(
       focused_agent_id=None, file_path="src/main.py", line=42))

3. EventStore.append() runs:
   a. Persists event to SQLite
   b. Checks subscriptions → "companion.context_extractor" matches
   c. Enqueues trigger (or broadcasts via EventBus)

4. CompanionDispatcher receives trigger
   → Updates CompanionState with CursorFocusEvent
   → Calls context_extractor.handle(event, state)

5. context_extractor reads src/main.py around line 42
   → Identifies: inside function `process_data`, in class `DataPipeline`
   → Returns [CompanionContextExtracted(
       file="src/main.py", line=42,
       structure_type="function", structure_name="process_data",
       content_type="python",
       surrounding_code="def process_data(self, items): ...",
       scope_path=("DataPipeline", "process_data"))]

6. Dispatcher appends CompanionContextExtracted to EventStore

7. EventStore.append() runs:
   a. Persists event
   b. Checks subscriptions → "companion.search" matches
                            → "companion.sidebar_composer" matches

8. Dispatcher receives trigger for companion.search
   → Calls search.handle(CompanionContextExtracted, state)
   → search builds query from context, calls embeddy SearchService
   → Returns [CompanionSearchCompleted(
       query="DataPipeline process_data",
       results=(SearchResult(...), SearchResult(...), ...),
       search_type="hybrid")]

9. Dispatcher appends CompanionSearchCompleted to EventStore

10. EventStore.append() runs:
    → "companion.connection_finder" matches
    → "companion.sidebar_composer" matches

11. Dispatcher receives trigger for companion.connection_finder
    → Analyzes relationships between context and search results
    → Returns [CompanionConnectionsFound(connections=(...))]

12. Dispatcher appends CompanionConnectionsFound
    → "companion.sidebar_composer" matches

13. Meanwhile (or after), sidebar_composer has been triggered by:
    - CompanionContextExtracted (step 7)
    - CompanionSearchCompleted (step 10)
    - CompanionConnectionsFound (step 12)
    
    Each trigger causes a recomposition. The composer reads from
    CompanionState (which has the latest of each event type) and
    renders the sidebar markdown.

14. Dispatcher appends CompanionSidebarComposed
    → LSP server picks this up and sends to the editor sidebar
```

That's 14 steps, but each step is tiny. The whole thing is a cascade of events flowing through pure functions. No workspace writes, no manual routing, no `_on_path_change()`.

### Debouncing

The sidebar composer will be triggered multiple times in rapid succession (once for each upstream event). We need debouncing — don't recompose the sidebar on every intermediate event, only after things settle.

Two approaches:

1. **Handler-level debouncing**: The dispatcher supports debounce configuration per handler. `sidebar_composer` has `debounce_ms=100` — triggers are coalesced, and the handler is called once with the latest state.

2. **Event-level deduplication**: The sidebar composer checks if the state actually changed since the last composition. If not, it skips.

Both are needed. Debouncing prevents rapid recomposition. Deduplication prevents unnecessary work even after debouncing.

```python
# In the dispatcher
class CompanionDispatcher:
    async def _dispatch_with_debounce(self, agent_id: str, event: _FrozenEvent) -> None:
        config = self._handler_configs.get(agent_id)
        if config and config.debounce_ms > 0:
            # Cancel any pending invocation
            # Schedule new invocation after debounce_ms
            ...
        else:
            await self._invoke_handler(agent_id, event)
```

This is the same debouncing logic that `AgentBase._invoke_handler()` currently does. We'd move it to the dispatcher.

---

## 9. Embeddy as Native Indexing

In the incremental plan, embeddy was a replacement for the existing indexing stack. In the clean-slate design, embeddy is the indexing layer from day one — it's never *replacing* anything because there's nothing to replace.

### How embeddy fits

The companion needs two indexing capabilities:

1. **Index files** when they're saved (or at startup for the whole workspace)
2. **Search** for code related to the current context

Embeddy provides:
- `Pipeline.ingest_file(path)` / `Pipeline.reindex_file(path)` — async, content-hash dedup, AST-based chunking
- `SearchService.search(query, collection, mode)` — async, hybrid (vector + BM25), RRF fusion
- `VectorStore` — SQLite + sqlite-vec + FTS5, per-collection tables

### The IndexingService wrapper

We still need a thin wrapper because:
- Embeddy needs configuration (embedding model, database path, chunker selection)
- We want to hide embeddy's API behind a companion-specific interface (in case we switch backends)
- The wrapper translates between companion events and embeddy calls

```python
class IndexingService:
    """Thin wrapper around embeddy for companion use."""
    
    def __init__(self, config: IndexingConfig) -> None:
        self._pipeline = Pipeline(config.pipeline_config)
        self._search = SearchService(config.search_config)
    
    async def index_file(self, path: str) -> CompanionIndexUpdated:
        """Index a file and return an event describing what happened."""
        stats = await self._pipeline.reindex_file(path)
        return CompanionIndexUpdated(
            file=path,
            chunks_added=stats.chunks_added,
            chunks_removed=stats.chunks_removed,
            chunks_unchanged=stats.chunks_unchanged,
        )
    
    async def search(self, query: str, limit: int = 10) -> list[CompanionSearchResult]:
        """Search the index and return typed results."""
        results = await self._search.search(
            query=query,
            collection="code",
            mode="hybrid",
            limit=limit,
        )
        return [
            CompanionSearchResult(
                file=r.metadata.get("file_path", ""),
                chunk_text=r.text,
                score=r.score,
                start_line=r.metadata.get("start_line", 0),
                end_line=r.metadata.get("end_line", 0),
            )
            for r in results.results
        ]
    
    async def index_directory(self, root: Path) -> None:
        """Index all files in a directory."""
        for path in root.rglob("*.py"):
            await self._pipeline.ingest_file(str(path))
        # Add other file types as needed
```

### The indexing handler

```python
class IndexingHandler:
    """Reacts to file saves by re-indexing."""
    
    def __init__(self, indexing: IndexingService) -> None:
        self._indexing = indexing
    
    async def handle(
        self, event: FileSavedEvent, state: CompanionState
    ) -> list[_FrozenEvent]:
        result = await self._indexing.index_file(event.path)
        return [result]  # CompanionIndexUpdated event
```

### The search handler

```python
class SearchHandler:
    """Reacts to context extraction by searching for related code."""
    
    def __init__(self, indexing: IndexingService) -> None:
        self._indexing = indexing
    
    async def handle(
        self, event: CompanionContextExtracted, state: CompanionState
    ) -> list[_FrozenEvent]:
        # Build query from context
        query = f"{event.structure_name} {event.content_type}"
        if event.surrounding_code:
            # Use the first meaningful line as additional query context
            query = event.surrounding_code[:200]
        
        results = await self._indexing.search(query)
        return [CompanionSearchCompleted(
            query=query,
            results=tuple(results),
            search_type="hybrid",
        )]
```

### Collections for different content types

Embeddy supports per-collection tables. The companion should use collections to separate different content types:

- `"python"` — Python source code (chunked with PythonChunker)
- `"markdown"` — Markdown files (chunked with MarkdownChunker)
- `"config"` — TOML/YAML/JSON configuration files

This maps naturally to embeddy's `VectorStore.create_collection()`. The `IndexingService` selects the right collection based on file extension.

### What about the code-node agent system?

There's an interesting overlap: remora core discovers code nodes via AST parsing and stores them in the nodes table. Embeddy chunks code via AST parsing and stores chunks in the vector store. These are doing related but different things:

- Code-node discovery: produces `AgentNode` objects for LLM interaction
- Embeddy indexing: produces vector embeddings for semantic search

They could share the AST parsing, but they serve different purposes. For now, keep them separate. In the future, if AgentNode grows semantic search capabilities (e.g., "find agents related to this one"), the code-node system might use embeddy too.

---

