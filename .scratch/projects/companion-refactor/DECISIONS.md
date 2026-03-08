# Companion Refactor — Decisions

> **CRITICAL RULES:**
> - **NO SUBAGENTS** — Do ALL work directly.
> - **NEVER STOP AFTER COMPACTION** — Resume immediately.

## D1: Cairn is required, not optional

**Decision:** `CairnWorkspaceService` is a required parameter to `start_companion()`.
There is no `cairn_service=None` fallback anywhere in the new companion code.

**Rationale:** The entire value proposition is persistence. Without Cairn, notes are lost,
history is lost. Treating Cairn as optional would produce dead code paths.

## D2: CursorFocusEvent.focused_agent_id IS the node_id

**Decision:** `NodeAgentRouter` uses `event.focused_agent_id` directly as node_id.

**Rationale:** Already populated by the LSP notification handler with the AgentNode.node_id.

## D3: No global CompanionState

**Decision:** No global state projection. Each NodeAgent owns its own state (in-memory +
Cairn workspace).

**Rationale:** Global state was a symptom of the old single-pipeline design.

## D4: MicroSwarms use LLM calls

**Decision:** SummarizerSwarm, ReflectionSwarm, CategorizerSwarm use single-turn LLM calls.
LinkerSwarm v1 uses text matching only.

**Rationale:** Single-turn calls are cheap and produce substantially better quality than
heuristics. LinkerSwarm uses text matching because node_id resolution is a lookup problem.

## D5: All companion commands via workspace/executeCommand

**Decision:** No new LSP methods. All pushes use `$/remora/companionSidebarUpdated`.

**Rationale:** Zero changes to LSP capability negotiation. Simpler.

## D6: Registry LRU eviction, per-node locking

**Decision:** Max 20 live agents (configurable). LRU by _last_visited. Per-node asyncio.Lock
prevents double-instantiation.

## D7: ChatSession deleted — not kept

**Decision:** `core/agents/chat.py` deleted in Phase 0. NodeAgent.send() replaces it
completely. No alternative API kept alongside.

---

## Table of Contents

1. [D1: How companion agents relate to AgentNode](#d1-companion-agents-and-agentnode)
2. [D2: Event model — dataclasses vs Pydantic _FrozenEvent](#d2-event-model)
3. [D3: Workspace — InMemoryWorkspace vs EventStore-backed](#d3-workspace-model)
4. [D4: Subscription routing — manual vs SubscriptionPattern](#d4-subscription-routing)
5. [D5: Package location — remora_demo vs src/remora](#d5-package-location)
6. [D6: Runtime wiring — hardcoded vs registry-driven](#d6-runtime-wiring)
7. [D7: Indexing backend — companion indexing vs embeddy](#d7-indexing-backend)

---

## D1: Companion Agents and AgentNode

### Problem

AgentNode is designed for code-node agents — it has `source_code`, `start_line`, `file_path`, `caller_ids`. Companion agents are functional/service agents (cursor_tracker, sidebar_composer) that don't correspond to code nodes.

### Options Considered

1. **Companion agents become AgentNodes with synthetic fields** — Register them in the nodes table with `node_type="service"`, empty `source_code`, file_path pointing to their implementation file.
2. **Companion agents use EventStore directly without AgentNode** — They participate in the event system (append events, register subscriptions) but don't have entries in the nodes table.
3. **New base model for service agents** — Create a separate Pydantic model for non-code agents.
4. **Thin bridge layer** — Keep companion agent classes mostly as-is but bridge their events into EventStore and use SubscriptionPattern for routing.

### Decision: Option 4 — Thin Bridge Layer

**Rationale:**
- AgentNode's invariant is "single Pydantic BaseModel, no subclasses, specialization via data." Stuffing service agents into AgentNode with fake source_code/line numbers violates the spirit even if it follows the letter.
- Companion agents don't need to be in the nodes table — they're not code entities that users navigate to via LSP.
- The value of "first-class" is using core *primitives* (EventStore, SubscriptionPattern, _FrozenEvent) — not forcing companion agents into the AgentNode model.
- A thin bridge means: companion agents emit/receive `_FrozenEvent`-based events through EventStore, register `SubscriptionPattern`s in `SubscriptionRegistry`, but keep their own agent class hierarchy for their domain logic.

**What changes:**
- Companion events become `_FrozenEvent` subclasses (Pydantic, frozen)
- Companion subscriptions use `SubscriptionPattern` for routing
- Companion runtime uses `EventStore.append()` and `EventStore.get_triggers()` for event flow
- `AgentBase` is simplified — it no longer manages its own subscription matching; it delegates to SubscriptionRegistry
- AgentNode stays untouched — it's for code-node agents only

**What doesn't change:**
- Companion agents remain their own classes (CursorTracker, ContextExtractor, etc.)
- The `WorkspaceInterface` abstraction remains (but gets a new EventStore-backed implementation)
- Agent activation tracking remains (but activations become events in EventStore)

---

## D2: Event Model

### Problem

Companion events are frozen dataclasses. Core remora events are `_FrozenEvent` (Pydantic, frozen). Two parallel type systems.

### Decision: Migrate companion events to `_FrozenEvent` subclasses

**Rationale:**
- Core EventStore's `_serialize_event()` already handles Pydantic models cleanly via `model_dump()`
- `SubscriptionPattern.matches()` checks attributes with `getattr()` — works with any event type, but Pydantic events get proper validation
- Using `_FrozenEvent` means companion events can be added to the `RemoraEvent` union type, enabling pattern matching
- Frozen dataclasses and frozen Pydantic models have near-identical semantics — migration is mechanical

**Migration:**
```python
# Before (frozen dataclass)
@dataclass(frozen=True)
class CursorMoved:
    file: str
    line: int
    col: int
    lingered: bool = False

# After (frozen Pydantic)
class CompanionCursorMoved(_FrozenEvent):
    file: str
    line: int
    col: int
    lingered: bool = False
    timestamp: float = Field(default_factory=time.time)
```

Note: We add `timestamp` to all companion events (aligns with core convention). We prefix with `Companion` to avoid name collisions with core events (e.g., `CursorFocusEvent` already exists).

---

## D3: Workspace Model

### Problem

InMemoryWorkspace is volatile — state is lost on restart, no audit trail, no replay. Core remora uses EventStore as the source of truth.

### Decision: EventStore-backed workspace with in-memory cache

**Rationale:**
- The workspace is the companion's shared state. Making it event-sourced means every workspace write is an event in EventStore — persistent, replayable, auditable.
- Read performance matters (agents read workspace frequently), so we keep an in-memory dict as a cache, but writes go through EventStore.
- The `WorkspaceInterface` ABC stays — we just add a new implementation `EventStoreWorkspace` alongside the existing `InMemoryWorkspace` (which remains for unit tests).

**Design:**
- `workspace.write(path, value)` → emits a `CompanionWorkspaceWrite` event to EventStore
- `workspace.read(path)` → reads from in-memory cache (populated by projecting workspace events)
- `workspace.list(pattern)` → reads from in-memory cache
- Path change notifications come from EventStore subscription matching, not from workspace listeners

---

## D4: Subscription Routing

### Problem

`CompanionRuntime._on_path_change()` is a giant if/elif that manually routes workspace changes to agents. This is the anti-pattern the subscription system was designed to eliminate.

### Decision: Replace manual routing with SubscriptionPattern registration

**Rationale:**
- Each companion agent registers its own `SubscriptionPattern`s at startup (e.g., context_extractor subscribes to `CompanionCursorMoved` events)
- Path-based subscriptions use `SubscriptionPattern.path_glob` (e.g., sidebar_composer subscribes to `path_glob="/companion/context/*"`)
- The runtime's `_on_path_change()` method is eliminated entirely
- EventStore's trigger queue drives agent invocation

**Example:**
```python
# context_extractor registers at startup:
await registry.register(
    agent_id="context_extractor",
    pattern=SubscriptionPattern(event_types=["CompanionCursorMoved"]),
)

# sidebar_composer registers:
await registry.register(
    agent_id="sidebar_composer",
    pattern=SubscriptionPattern(
        event_types=["CompanionWorkspaceWrite"],
        path_glob="/companion/context/*",
    ),
)
```

---

## D5: Package Location

### Problem

Companion lives in `remora_demo/companion/`. Should it move to `src/remora/companion/`?

### Decision: Move to `src/remora/companion/`

**Rationale:**
- "First-class" means it's part of the package, importable as `remora.companion`
- It depends on core remora primitives (`EventStore`, `SubscriptionPattern`, `_FrozenEvent`)
- Tests move from `tests/companion/` to `tests/companion/` (same location, just update imports)
- The demo harness / scenarios can stay in `remora_demo/` since they're demo-specific

**What moves:**
- `remora_demo/companion/agents/` → `src/remora/companion/agents/`
- `remora_demo/companion/models/` → `src/remora/companion/models/`
- `remora_demo/companion/runtime.py` → `src/remora/companion/runtime.py`
- `remora_demo/companion/indexing/` → `src/remora/companion/indexing/`

**What stays:**
- `remora_demo/companion/demo/` — demo harness, scenarios, recording
- `remora_demo/companion/lsp/` — LSP server (integration layer)
- `remora_demo/companion/nvim/` — Neovim plugin
- `remora_demo/companion/timeline/` — web UI

---

## D6: Runtime Wiring

### Problem

`CompanionRuntime.start()` hardcodes agent instantiation and manual event wiring. Adding a new agent requires 5-6 edits to runtime.py.

### Decision: Registry-driven agent discovery

**Rationale:**
- Each companion agent class registers itself with the runtime via a decorator or registry
- The runtime discovers all registered agents, instantiates them, and registers their subscriptions
- Adding a new agent means creating the agent class and registering it — no edits to runtime.py

**Design:**
- A companion agent registry (simple dict: name → factory function)
- Each agent module registers via `@companion_agent("cursor_tracker")` or explicit registration
- Runtime iterates the registry, creates agents, registers their `SubscriptionPattern`s
- Event dispatch goes through EventStore trigger queue → matched agent's handler

This eliminates the manual wiring entirely and makes the system extensible.

---

## D7: Indexing Backend

### Problem

The companion has a hand-rolled indexing stack in `remora_demo/companion/indexing/` — `Indexer`, `VectorStore`, `SentenceTransformerEmbedder`, `chunk_file()`. This stack is synchronous, uses regex-based Python chunking, has no FTS/hybrid search, no content-hash deduplication, and no collection namespacing.

Meanwhile, the `embeddy` library (`/home/andrew/Documents/Projects/embeddy`) provides all of this in an async-native, well-tested package.

### Options Considered

1. **Keep companion indexing, improve incrementally** — Fix the sync issue, add FTS, add AST chunking. Lots of work duplicating embeddy.
2. **Replace companion indexing with embeddy** — Delete `remora_demo/companion/indexing/`, create an `IndexingService` wrapping embeddy's Pipeline + SearchService.
3. **Partial integration** — Use only embeddy's Embedder and VectorStore, keep companion's chunking/indexer.

### Decision: Option 2 — Full replacement with embeddy

**Rationale:**
- Embeddy's Pipeline, SearchService, VectorStore, PythonChunker, and Embedder are direct replacements for companion's Indexer, VectorStore, SentenceTransformerEmbedder, and chunk_file(). The mapping is 1:1.
- Embeddy is strictly better: async-native, AST-based Python chunking (`ast.parse()` vs regex), hybrid search (vector + BM25 with RRF/weighted fusion), content-hash dedup, per-collection namespacing, remote embedding support.
- No remora core changes needed. This is purely a companion-internal swap.
- Partial integration (option 3) would keep companion's weakest code (the regex chunker) while throwing away embeddy's strongest (the Pipeline orchestrator).

**Integration design:**
- New `IndexingService` class wrapping `embeddy.Pipeline` + `embeddy.SearchService`
- Holds a configured `Embedder`, `VectorStore`, `Pipeline`, `SearchService`
- Exposes: `index_file(path)`, `reindex_file(path)`, `search(query, ...)`, `index_directory(root)`
- New `IndexingAgent` subscribes to file-save events, calls `IndexingService`
- `EmbeddingSearcher` updated to call `IndexingService.search()`
- New `CompanionIndexUpdatedEvent` emitted after successful indexing

**Dependency:**
- `embeddy` added as a path dependency initially: `embeddy = {path = "../embeddy"}`
- Later migrated to git or published package dependency

**What changes:**
- New `IndexingService` wrapping embeddy
- New `IndexingAgent` (minimal, subscribes to file-save events)
- `EmbeddingSearcher` updated to use `IndexingService.search()`
- `remora_demo/companion/indexing/` deleted

**What doesn't change:**
- No remora core changes
- No agent consolidation (all 13 agents preserved)
- No SwarmExecutor changes
- `AgentBase`, `WorkspaceInterface`, event model — all unchanged by this decision

**Assumptions informing this decision:**
- A1: Embeddy's API is stable enough for companion to depend on
- A2: Remote embedding mode is the primary deployment mode (companion offloads to GPU server)
- A3: Multi-facet embeddings (Appendix A of brainstorm) are Phase 2+, not needed for initial integration
