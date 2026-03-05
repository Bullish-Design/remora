# COMPANION_REFACTOR_PLAN.md

> Step-by-step plan to refactor the existing companion from a demo-bolted-on
> system into the unified architecture described in COMPANION_CONCEPT.md.

---

## Guiding Principles

1. **COMPANION_CONCEPT.md is the source of truth.** When conflicts exist between it and the brainstorm docs, the concept doc wins.
2. **Remora core primitives are the foundation.** `_FrozenEvent`, `EventStore`, `SubscriptionPattern`, `SubscriptionRegistry`, `EventBus` — the companion is built entirely on these.
3. **No AgentNode for companion pipeline stages.** Companion nodes are event handlers, not code-node agents (Option C from the brainstorm).
4. **Each companion node gets its own persistent Cairn workspace** for long-term memory and cached analysis.
5. **Embeddy is the indexing layer from day one.** Not a migration, but the starting point.
6. **Swarm agents are the "brain"; the pipeline is the "nervous system."** Deterministic pipeline + emergent swarm are complementary, not competing.

---

## Phase 0: Preparation & Scaffolding

### Step 0.1 — Create the new companion package location

Create the target directory structure under `src/remora/companion/`:

```
src/remora/companion/
├── __init__.py
├── config.py                  # CompanionConfig (Pydantic)
├── dispatcher.py              # CompanionDispatcher
├── state.py                   # CompanionState projection
├── events.py                  # All Companion _FrozenEvent subclasses
├── indexing_service.py        # IndexingService (wraps embeddy)
├── handlers/
│   ├── __init__.py
│   ├── base.py                # CompanionHandler protocol
│   ├── context_extractor.py
│   ├── edit_summarizer.py
│   ├── search_handler.py
│   ├── indexing_handler.py
│   ├── connection_finder.py
│   ├── task_inferrer.py
│   ├── claim_checker.py
│   └── sidebar_composer.py
└── startup.py                 # start_companion() entrypoint
```

### Step 0.2 — Add embeddy as a dependency

Add embeddy to `pyproject.toml`:

```toml
[project.dependencies]
embeddy = { path = "../embeddy" }  # local path initially, then git/published
```

### Step 0.3 — Create the task.md tracking file

Track progress across phases with a detailed checklist (as a working document, not committed).

---

## Phase 1: Event Types

> Migrate from frozen dataclasses (`CursorMoved`, `ContentEdited`, etc.) to
> `_FrozenEvent` Pydantic subclasses. Reuse core events where they already exist.

### Step 1.1 — Define companion event types

Create `src/remora/companion/events.py` with all companion-specific `_FrozenEvent` subclasses. These are the typed outputs of every pipeline stage.

**Source events (reuse from core):**
- `CursorFocusEvent` — already in `remora.core.events`
- `ContentChangedEvent` — already in `remora.core.events`
- `FileSavedEvent` — already in `remora.core.events`

**New companion-specific source event:**
```python
class CompanionSessionTick(_FrozenEvent):
    elapsed_ms: int
    tick_number: int
    timestamp: float = Field(default_factory=time.time)
```

**Stage 1 output events:**
```python
class CompanionContextExtracted(_FrozenEvent):
    file: str
    line: int
    structure_type: str       # "function", "class", "module", "section"
    structure_name: str
    content_type: str         # "python", "markdown", "toml", etc.
    surrounding_code: str
    scope_path: tuple[str, ...]
    timestamp: float = Field(default_factory=time.time)

class CompanionEditSummary(_FrozenEvent):
    file: str
    summary: str
    edit_count: int
    lines_changed: int
    timestamp: float = Field(default_factory=time.time)
```

**Stage 2 output events:**
```python
class CompanionSearchResult(_FrozenEvent):
    file: str
    chunk_text: str
    score: float
    content_type: str | None = None
    chunk_type: str | None = None
    start_line: int = 0
    end_line: int = 0
    name: str | None = None

class CompanionSearchCompleted(_FrozenEvent):
    query: str
    results: tuple[CompanionSearchResult, ...]
    search_type: str           # "vector", "fulltext", "hybrid"
    timestamp: float = Field(default_factory=time.time)

class CompanionIndexUpdated(_FrozenEvent):
    file: str
    chunks_stored: int
    chunks_skipped: int
    chunks_created: int
    timestamp: float = Field(default_factory=time.time)
```

**Stage 3 output events:**
```python
class CompanionConnection(_FrozenEvent):
    source: str
    target: str
    relationship: str         # "calls", "imports", "similar_to", "shares_pattern"
    confidence: float

class CompanionConnectionsFound(_FrozenEvent):
    connections: tuple[CompanionConnection, ...]
    timestamp: float = Field(default_factory=time.time)

class CompanionTaskInferred(_FrozenEvent):
    task_description: str
    confidence: float
    evidence: tuple[str, ...]
    timestamp: float = Field(default_factory=time.time)

class CompanionClaim(_FrozenEvent):
    claim_text: str
    status: str               # "verified", "unverified", "contradicted"
    evidence: str

class CompanionClaimsChecked(_FrozenEvent):
    claims: tuple[CompanionClaim, ...]
    timestamp: float = Field(default_factory=time.time)
```

**Stage 4 (Sink) events:**
```python
class CompanionSidebarComposed(_FrozenEvent):
    markdown: str
    sections: tuple[str, ...]
    timestamp: float = Field(default_factory=time.time)
```

### Step 1.2 — Register companion events with the RemoraEvent union

Either add the new companion events to the `RemoraEvent` union type in `remora.core.events`, or create a `CompanionEvent` union in `remora.companion.events` and have the routing system recognize them. The latter keeps companion concerns separate from core.

**Decision needed:** Whether to extend `RemoraEvent` or create a parallel union. The concept doc favors keeping them in the same system for unified dispatch, so extending `RemoraEvent` is preferred.

---

## Phase 2: CompanionState Projection

> Create the fast, in-memory read-model that aggregates the "most recent" of
> each companion event type.

### Step 2.1 — Implement CompanionState

Create `src/remora/companion/state.py`:

```python
class CompanionState:
    """Read-only projection of companion event stream.
    
    Continuously updated as events arrive. Handlers read from this
    for current state instead of querying EventStore directly.
    """
    
    def __init__(self) -> None:
        self._latest: dict[str, _FrozenEvent] = {}
    
    def apply(self, event: _FrozenEvent) -> None:
        event_type = type(event).__name__
        if event_type.startswith("Companion") or event_type in (
            "CursorFocusEvent", "ContentChangedEvent", "FileSavedEvent"
        ):
            self._latest[event_type] = event
    
    @property
    def context(self) -> CompanionContextExtracted | None: ...
    
    @property
    def search_results(self) -> CompanionSearchCompleted | None: ...
    
    @property
    def connections(self) -> CompanionConnectionsFound | None: ...
    
    @property
    def task(self) -> CompanionTaskInferred | None: ...
    
    @property
    def claims(self) -> CompanionClaimsChecked | None: ...
    
    @property
    def sidebar(self) -> CompanionSidebarComposed | None: ...
    
    @property
    def edit_summary(self) -> CompanionEditSummary | None: ...
```

Properties provide typed access to the latest event of each type. The projection is rebuildable from EventStore replay.

---

## Phase 3: Handler Protocol & Cairn Workspaces

> Define the handler contract and give every handler its own persistent Cairn workspace.

### Step 3.1 — Define the CompanionHandler protocol

Create `src/remora/companion/handlers/base.py`:

```python
from __future__ import annotations
from typing import Protocol

class CompanionHandler(Protocol):
    """Protocol for companion pipeline handlers.
    
    Each handler:
    1. Subscribes to specific event types
    2. Receives the triggering event + current CompanionState
    3. Returns zero or more new events to emit
    4. Has access to its own persistent Cairn workspace
    """
    
    async def handle(
        self,
        event: _FrozenEvent,
        state: CompanionState,
    ) -> list[_FrozenEvent]: ...
```

### Step 3.2 — Integrate Cairn workspaces per handler

Each handler gets a persistent `Cairn` workspace via `CairnWorkspaceService.get_agent_workspace()`. The workspace is created with the handler's agent_id (e.g., `"companion.task_inferrer"`).

```python
class CompanionHandlerBase:
    """Base implementation providing Cairn workspace access."""
    
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._workspace: AgentWorkspace | None = None
    
    async def initialize(self, cairn_service: CairnWorkspaceService) -> None:
        self._workspace = await cairn_service.get_agent_workspace(self.agent_id)
    
    @property
    def workspace(self) -> AgentWorkspace:
        assert self._workspace is not None, "Handler not initialized"
        return self._workspace
```

This gives each handler:
- Persistent SQLite-backed storage across restarts
- Ability to organize historical insights, cache analysis, build collections
- Full isolation from other handlers' workspaces

### Step 3.3 — Cairn workspace use cases per handler

| Handler | Cairn Workspace Usage |
|---------|----------------------|
| `ContextExtractor` | Cache AST parse results for frequently visited files |
| `EditSummarizer` | Store rolling edit history for macro-level summaries |
| `SearchHandler` | Cache recent query → result mappings |
| `IndexingHandler` | Track indexed file hashes for incremental re-indexing decisions |
| `ConnectionFinder` | Persist discovered connection graphs across sessions |
| `TaskInferrer` | Build persistent task boards mapping evolving user intentions |
| `ClaimChecker` | Cache verified claim proofs, avoid re-checking unchanged claims |
| `SidebarComposer` | Store template fragments, user preference snapshots |

---

## Phase 4: Embeddy Integration — IndexingService

> Build the `IndexingService` wrapper around embeddy's `Pipeline` + `SearchService`.

### Step 4.1 — Create IndexingService configuration

Create `src/remora/companion/config.py` with Pydantic config models:

```python
from embeddy.config import EmbedderConfig, StoreConfig, ChunkConfig

class IndexingConfig(BaseModel):
    embedder: EmbedderConfig = Field(
        default_factory=lambda: EmbedderConfig(mode="remote")
    )
    store: StoreConfig = Field(
        default_factory=lambda: StoreConfig(db_path=".companion/vectors.db")
    )
    chunk: ChunkConfig = Field(default_factory=ChunkConfig)
    collections: dict[str, str] = Field(default_factory=lambda: {
        "python": "python",
        "markdown": "markdown",
        "config": "config",
    })

class CompanionConfig(BaseModel):
    workspace_path: Path = Field(default_factory=Path.cwd)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    session_id: str = Field(default_factory=lambda: f"companion-{uuid4()}")
    sidebar_output_path: Path | None = None
    auto_index: bool = True
```

### Step 4.2 — Implement IndexingService

Create `src/remora/companion/indexing_service.py`:

```python
from embeddy import Embedder, VectorStore, Pipeline, SearchService
from embeddy.config import EmbedderConfig, StoreConfig, ChunkConfig
from embeddy.models import SearchMode, SearchResults, IngestStats

class IndexingService:
    """Thin wrapper around embeddy for companion indexing and search."""
    
    def __init__(self, config: IndexingConfig) -> None:
        self._config = config
        self._embedder = Embedder(config.embedder)
        self._store = VectorStore(config.store)
        self._pipelines: dict[str, Pipeline] = {}
        self._search = SearchService(
            embedder=self._embedder, store=self._store
        )
    
    async def initialize(self) -> None:
        await self._store.initialize()
        # Create pipelines per collection
        for collection_name in self._config.collections.values():
            self._pipelines[collection_name] = Pipeline(
                embedder=self._embedder,
                store=self._store,
                collection=collection_name,
                chunk_config=self._config.chunk,
            )
    
    async def index_file(self, path: str) -> CompanionIndexUpdated:
        collection = self._collection_for_file(path)
        pipeline = self._pipelines[collection]
        stats: IngestStats = await pipeline.ingest_file(path)
        return CompanionIndexUpdated(
            file=path,
            chunks_stored=stats.chunks_stored,
            chunks_skipped=stats.chunks_skipped,
            chunks_created=stats.chunks_created,
        )
    
    async def reindex_file(self, path: str) -> CompanionIndexUpdated:
        collection = self._collection_for_file(path)
        pipeline = self._pipelines[collection]
        stats: IngestStats = await pipeline.reindex_file(path)
        return CompanionIndexUpdated(
            file=path,
            chunks_stored=stats.chunks_stored,
            chunks_skipped=stats.chunks_skipped,
            chunks_created=stats.chunks_created,
        )
    
    async def search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int = 10,
        mode: SearchMode = SearchMode.HYBRID,
    ) -> list[CompanionSearchResult]:
        target = collection or "python"
        results: SearchResults = await self._search.search(
            query=query,
            collection=target,
            top_k=top_k,
            mode=mode,
        )
        return [
            CompanionSearchResult(
                file=r.source_path or "",
                chunk_text=r.content,
                score=r.score,
                content_type=r.content_type,
                chunk_type=r.chunk_type,
                start_line=r.start_line or 0,
                end_line=r.end_line or 0,
                name=r.name,
            )
            for r in results.results
        ]
    
    async def index_directory(self, root: Path) -> IngestStats:
        stats = IngestStats()
        for collection_name, pipeline in self._pipelines.items():
            include = self._include_for_collection(collection_name)
            result = await pipeline.ingest_directory(
                str(root), include=include
            )
            # Aggregate stats
            stats.files_processed += result.files_processed
            stats.chunks_stored += result.chunks_stored
            stats.chunks_skipped += result.chunks_skipped
        return stats
    
    def _collection_for_file(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        mapping = {".py": "python", ".md": "markdown"}
        return mapping.get(ext, "config")
    
    def _include_for_collection(self, collection: str) -> list[str]:
        mapping = {
            "python": ["*.py"],
            "markdown": ["*.md"],
            "config": ["*.toml", "*.yaml", "*.yml", "*.json"],
        }
        return mapping.get(collection, ["*"])
    
    async def close(self) -> None:
        # embeddy cleanup if needed
        pass
```

> **Key embeddy API alignment:**
> - `Pipeline(embedder, store, collection, chunk_config)` — per-collection pipelines
> - `Pipeline.ingest_file(path)` → `IngestStats`
> - `Pipeline.reindex_file(path)` → `IngestStats`
> - `Pipeline.ingest_directory(path, include, exclude)` → `IngestStats`
> - `SearchService(embedder, store)`
> - `SearchService.search(query, collection, top_k, mode)` → `SearchResults`
> - `SearchResults.results` → `list[SearchResult]`
> - `SearchResult` fields: `chunk_id`, `content`, `score`, `source_path`, `content_type`, `chunk_type`, `start_line`, `end_line`, `name`

---

## Phase 5: Implement Handlers

> Port the logic from the 13 existing agents into focused event handlers.
> Sensors become integration code. The remaining 8 pipeline stages become handler classes.

### Step 5.1 — Eliminate sensor agents (they become integration code)

The following old agents are **not** reimplemented as handlers. Their job is done by the LSP server or thin startup code that calls `event_store.append()`:

| Old Agent | Replacement |
|-----------|------------|
| `CursorTracker` | LSP `textDocument/didFocus` → `event_store.append(CursorFocusEvent)` |
| `EditTracker` | LSP `textDocument/didChange` → `event_store.append(ContentChangedEvent)` |
| `FileWatcher` | LSP `workspace/didChangeWatchedFiles` → `event_store.append(FileSavedEvent)` |
| `SessionClock` | `asyncio.create_task()` ticking `CompanionSessionTick` events |

This code lives in `startup.py` or in the LSP server integration layer.

### Step 5.2 — Implement Stage 1 handlers

**ContextExtractor handler** (`handlers/context_extractor.py`):
- Subscribes to: `CursorFocusEvent`
- Logic: Read file, parse AST (or heading structure for markdown), identify enclosing function/class/section
- Emits: `CompanionContextExtracted`
- Cairn usage: Cache AST parse results

**EditSummarizer handler** (`handlers/edit_summarizer.py`):
- Subscribes to: `ContentChangedEvent`
- Logic: Accumulate edits, debounce, produce macro-level summary
- Emits: `CompanionEditSummary`
- Cairn usage: Store rolling edit history across sessions

### Step 5.3 — Implement Stage 2 handlers

**SearchHandler** (`handlers/search_handler.py`):
- Subscribes to: `CompanionContextExtracted`
- Logic: Build hybrid search query from context fields, call `IndexingService.search()`, wrap results
- Emits: `CompanionSearchCompleted`
- Cairn usage: Cache recent query→result mappings

**IndexingHandler** (`handlers/indexing_handler.py`):
- Subscribes to: `FileSavedEvent`
- Logic: Call `IndexingService.index_file()` (or `reindex_file()`)
- Emits: `CompanionIndexUpdated`
- Cairn usage: Track file hash history for incremental decisions

### Step 5.4 — Implement Stage 3 handlers

**ConnectionFinder** (`handlers/connection_finder.py`):
- Subscribes to: `CompanionSearchCompleted`
- Logic: Analyze structural graph calls + embeddy search results for similarity bridges
- Emits: `CompanionConnectionsFound`
- Cairn usage: Persist discovered connection graphs

**TaskInferrer** (`handlers/task_inferrer.py`):
- Subscribes to: `CompanionContextExtracted`
- Logic: Translate code mutations + file jumps into inferred goals. Use Cairn workspace to build persistent task boards across sessions
- Emits: `CompanionTaskInferred`
- Cairn usage: **Primary user** — organize historical understanding of user objectives

**ClaimChecker** (`handlers/claim_checker.py`):
- Subscribes to: `CompanionContextExtracted` (filtered to markdown `content_type`)
- Logic: Parse claims from markdown, verify against codebase search results
- Emits: `CompanionClaimsChecked`
- Cairn usage: Cache verified claim proofs, avoid redundant checks

### Step 5.5 — Implement Stage 4 (Sink) handler

**SidebarComposer** (`handlers/sidebar_composer.py`):
- Subscribes to: `CompanionContextExtracted`, `CompanionSearchCompleted`, `CompanionConnectionsFound`, `CompanionEditSummary`, `CompanionTaskInferred`, `CompanionClaimsChecked`
- Logic: Read from `CompanionState` projection for latest values, compose rich markdown sidebar
- Emits: `CompanionSidebarComposed`
- Debounce: 100ms+ to avoid rapid recomposition
- Cairn usage: Store sidebar template fragments

---

## Phase 6: CompanionDispatcher

> Build the dispatch loop that routes events from EventStore/EventBus to the
> correct handler.

### Step 6.1 — Choose dispatch mechanism

Per the concept doc, the companion uses the **EventBus** (in-memory pub/sub) for lightweight dispatch. This avoids competing with `SwarmExecutor` for the EventStore trigger queue.

The `EventBus` already supports type-based subscription, async handlers, and streaming — exactly what the companion needs.

### Step 6.2 — Implement CompanionDispatcher

Create `src/remora/companion/dispatcher.py`:

```python
class HandlerConfig(BaseModel):
    handler_id: str
    debounce_ms: int = 0

class CompanionDispatcher:
    """Routes events to companion handlers via EventBus."""
    
    def __init__(
        self,
        event_store: EventStore,
        event_bus: EventBus,
        state: CompanionState,
        handlers: dict[str, CompanionHandler],
        handler_configs: dict[str, HandlerConfig] | None = None,
        session_id: str = "companion",
    ) -> None:
        self._store = event_store
        self._bus = event_bus
        self._state = state
        self._handlers = handlers
        self._configs = handler_configs or {}
        self._session_id = session_id
        self._debounce_tasks: dict[str, asyncio.Task] = {}
    
    async def start(self) -> None:
        """Register EventBus subscriptions for all handlers."""
        # Map: event_type → list of handler_ids
        routing = self._build_routing_table()
        
        # Subscribe to EventBus for each event type
        for event_type, handler_ids in routing.items():
            async def on_event(event, hids=handler_ids):
                self._state.apply(event)
                for hid in hids:
                    await self._dispatch(hid, event)
            self._bus.subscribe(event_type, on_event)
    
    async def _dispatch(self, handler_id: str, event: _FrozenEvent) -> None:
        config = self._configs.get(handler_id)
        if config and config.debounce_ms > 0:
            await self._dispatch_debounced(handler_id, event, config.debounce_ms)
        else:
            await self._invoke(handler_id, event)
    
    async def _invoke(self, handler_id: str, event: _FrozenEvent) -> None:
        handler = self._handlers[handler_id]
        new_events = await handler.handle(event, self._state)
        for new_event in new_events:
            await self._store.append(self._session_id, new_event)
            await self._bus.emit(new_event)
    
    async def _dispatch_debounced(
        self, handler_id: str, event: _FrozenEvent, ms: int
    ) -> None:
        # Cancel pending invocation
        if handler_id in self._debounce_tasks:
            self._debounce_tasks[handler_id].cancel()
        
        async def delayed():
            await asyncio.sleep(ms / 1000)
            await self._invoke(handler_id, event)
        
        self._debounce_tasks[handler_id] = asyncio.create_task(delayed())
```

### Step 6.3 — Define the routing table

The routing table connects event types to handler IDs. This replaces both `SubscriptionPattern` registrations and the old `_on_path_change()` if/elif chain.

```python
ROUTING_TABLE = {
    CursorFocusEvent: ["companion.context_extractor"],
    ContentChangedEvent: ["companion.edit_summarizer"],
    FileSavedEvent: ["companion.indexing_handler"],
    CompanionContextExtracted: [
        "companion.search_handler",
        "companion.task_inferrer",
        "companion.claim_checker",
        "companion.sidebar_composer",
    ],
    CompanionSearchCompleted: [
        "companion.connection_finder",
        "companion.sidebar_composer",
    ],
    CompanionConnectionsFound: ["companion.sidebar_composer"],
    CompanionEditSummary: ["companion.sidebar_composer"],
    CompanionTaskInferred: ["companion.sidebar_composer"],
    CompanionClaimsChecked: ["companion.sidebar_composer"],
}
```

### Step 6.4 — Configure debouncing

```python
HANDLER_CONFIGS = {
    "companion.sidebar_composer": HandlerConfig(
        handler_id="companion.sidebar_composer",
        debounce_ms=150,
    ),
    "companion.edit_summarizer": HandlerConfig(
        handler_id="companion.edit_summarizer",
        debounce_ms=500,
    ),
}
```

---

## Phase 7: Startup & Lifecycle

> Wire everything together in a `start_companion()` entrypoint.

### Step 7.1 — Implement start_companion()

Create `src/remora/companion/startup.py`:

```python
async def start_companion(
    event_store: EventStore,
    event_bus: EventBus,
    cairn_service: CairnWorkspaceService,
    config: CompanionConfig | None = None,
) -> CompanionDispatcher:
    cfg = config or CompanionConfig()
    
    # 1. Create CompanionState projection
    state = CompanionState()
    
    # 2. Create IndexingService (embeddy wrapper)
    indexing = IndexingService(cfg.indexing)
    await indexing.initialize()
    
    # 3. Create all handlers
    handlers: dict[str, CompanionHandler] = {
        "companion.context_extractor": ContextExtractorHandler("companion.context_extractor"),
        "companion.edit_summarizer": EditSummarizerHandler("companion.edit_summarizer"),
        "companion.search_handler": SearchHandler("companion.search_handler", indexing),
        "companion.indexing_handler": IndexingHandler("companion.indexing_handler", indexing),
        "companion.connection_finder": ConnectionFinderHandler("companion.connection_finder"),
        "companion.task_inferrer": TaskInferrerHandler("companion.task_inferrer"),
        "companion.claim_checker": ClaimCheckerHandler("companion.claim_checker"),
        "companion.sidebar_composer": SidebarComposerHandler("companion.sidebar_composer"),
    }
    
    # 4. Initialize Cairn workspaces for each handler
    for handler in handlers.values():
        if hasattr(handler, "initialize"):
            await handler.initialize(cairn_service)
    
    # 5. Optionally do initial workspace indexing
    if cfg.auto_index:
        await indexing.index_directory(cfg.workspace_path)
    
    # 6. Create and start the dispatcher
    dispatcher = CompanionDispatcher(
        event_store=event_store,
        event_bus=event_bus,
        state=state,
        handlers=handlers,
        handler_configs=HANDLER_CONFIGS,
        session_id=cfg.session_id,
    )
    await dispatcher.start()
    
    # 7. Start the session tick loop
    async def tick_loop():
        tick = 0
        while True:
            await asyncio.sleep(30)
            tick += 1
            event = CompanionSessionTick(
                elapsed_ms=tick * 30000, tick_number=tick
            )
            await event_store.append(cfg.session_id, event)
            await event_bus.emit(event)
    
    asyncio.create_task(tick_loop())
    
    return dispatcher
```

### Step 7.2 — Register with the LSP server

The LSP server (or whichever editor integration layer exists) should:
1. Call `start_companion()` during initialization
2. Emit `CursorFocusEvent`, `ContentChangedEvent`, `FileSavedEvent` into both the `EventStore` and `EventBus` on editor notifications
3. Subscribe to `CompanionSidebarComposed` events on the EventBus to push sidebar updates to the editor

---

## Phase 8: Swarm Synergy Integration Points

> Set up the plumbing for the deterministic pipeline to invoke the Swarm when
> deep reasoning is needed.

### Step 8.1 — Define swarm dispatch events

These events signal that a handler wants LLM-powered analysis:

```python
class CompanionSwarmRequest(_FrozenEvent):
    """Request the Swarm to perform deep analysis on a topic."""
    requesting_handler: str
    analysis_type: str        # "task_inference", "claim_verification", etc.
    context: str
    target_workspace: str     # Cairn workspace path for results
    timestamp: float = Field(default_factory=time.time)

class CompanionSwarmResult(_FrozenEvent):
    """Swarm completed its analysis and wrote results to Cairn."""
    requesting_handler: str
    analysis_type: str
    summary: str
    timestamp: float = Field(default_factory=time.time)
```

### Step 8.2 — Handler-to-Swarm delegation pattern

When a handler encounters a situation requiring deep reasoning:
1. The handler emits a `CompanionSwarmRequest` event
2. A SwarmBridge component (future implementation) subscribes to this event
3. The SwarmBridge dispatches code agents that write results into the handler's Cairn workspace
4. A `CompanionSwarmResult` event is emitted, which the original handler can subscribe to

This keeps the pipeline deterministic while enabling emergent complexity when needed.

> **Note:** This phase defines the *interface* only. Full Swarm integration
> is a follow-up effort after the core pipeline is working.

---

## Phase 9: Delete Old Code

> Remove the legacy companion implementation once the new one is verified.

### Step 9.1 — Delete old companion agents

Remove the entire `remora_demo/companion/agents/` directory:
- `sensors/` — `cursor_tracker.py`, `edit_tracker.py`, `file_watcher.py`, `session_clock.py`
- `extractors/` — `context_extractor.py`, `edit_summarizer.py`
- `searchers/` — `embedding_searcher.py`
- `analyzers/` — `claim_checker.py`, `connection_finder.py`, `question_generator.py`, `task_inferrer.py`
- `composers/` — `sidebar_composer.py`, `session_summarizer.py`
- `base.py` — `AgentBase`, `WorkspaceInterface`, `Subscription`, `subscribe`

### Step 9.2 — Delete old models

Remove `remora_demo/companion/models/`:
- `events.py` — `CursorMoved`, `ContentEdited`, `FileChanged`, `SessionTick`, `PathChanged`
- `workspace.py` — All workspace schema dataclasses

### Step 9.3 — Delete old indexing stack

Remove `remora_demo/companion/indexing/`:
- `embedder.py` — `EmbedderBase`, `SentenceTransformerEmbedder`
- `store.py` — Old `VectorStore`
- `chunker.py` — Regex-based chunking
- `indexer.py` — `Indexer` orchestrator

### Step 9.4 — Delete old runtime

Remove `remora_demo/companion/runtime.py` — `CompanionConfig` (dataclass), `CompanionRuntime`

### Step 9.5 — Remove or redirect old companion `__init__.py`

Update `remora_demo/companion/__init__.py` to either become a thin re-export of `remora.companion` or be deleted entirely if the demo package is deprecated.

---

## Phase 10: Testing

### Step 10.1 — Unit tests for events

Test that all companion `_FrozenEvent` subclasses:
- Are frozen (immutable)
- Serialize/deserialize correctly
- Have correct default timestamps

### Step 10.2 — Unit tests for CompanionState

Test that the projection correctly tracks the latest event of each type and exposes typed properties.

### Step 10.3 — Unit tests for IndexingService

Mock embeddy's `Pipeline` and `SearchService` to verify:
- `index_file()` calls `pipeline.ingest_file()` and returns the correct event
- `search()` calls `search_service.search()` and maps `SearchResult` → `CompanionSearchResult` correctly
- Collection routing by file extension works

### Step 10.4 — Unit tests for each handler

Test each handler in isolation:
- Feed it a triggering event + mock `CompanionState`
- Verify it returns the expected output events
- Mock Cairn workspace interactions where needed

### Step 10.5 — Integration test for the dispatch loop

Test the full pipeline cascade:
1. Emit a `CursorFocusEvent`
2. Verify `ContextExtractor` fires, emitting `CompanionContextExtracted`
3. Verify `SearchHandler` fires on the extracted context
4. Verify `SidebarComposer` eventually fires and produces `CompanionSidebarComposed`

### Step 10.6 — Integration test for embeddy

Use embeddy with a small test corpus to verify real search results flow through the pipeline end-to-end.

---

## Execution Order Summary

| Phase | What | Depends On | Estimated Effort |
|-------|------|-----------|-----------------|
| 0 | Scaffolding + dependency | — | Small |
| 1 | Event types | Phase 0 | Small |
| 2 | CompanionState | Phase 1 | Small |
| 3 | Handler protocol + Cairn | Phase 2 | Medium |
| 4 | IndexingService (embeddy) | Phase 0 | Medium |
| 5 | All 8 handlers | Phases 3, 4 | Large |
| 6 | CompanionDispatcher | Phases 2, 5 | Medium |
| 7 | Startup + LSP wiring | Phases 5, 6 | Medium |
| 8 | Swarm synergy interfaces | Phase 5 | Small (interface only) |
| 9 | Delete old code | Phases 7, 10 | Small |
| 10 | Testing | All phases | Large |

Phases 1–4 can be worked on in parallel after Phase 0. Phase 5 depends on both 3 and 4. Phase 6 depends on 5. Phases 9 and 10 are the final validation gates.

---

## Key Decisions Tracker

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent model | Option C — no AgentNode, handlers only | Pipeline stages aren't code entities; `_FrozenEvent` handlers are simpler |
| Dispatch mechanism | EventBus (not trigger queue) | Avoids competing with SwarmExecutor; lighter for data transforms |
| Inter-handler communication | Events only | Data travels via typed `_FrozenEvent` objects, not workspace writes |
| Per-handler state | Cairn workspaces | Long-term memory survives restarts; isolated per handler |
| Shared read-model | CompanionState projection | In-memory, derived from events, avoids EventStore queries |
| Indexing backend | embeddy (`Pipeline` + `SearchService`) | Async, AST chunking, hybrid search, content-hash dedup, collections |
| Graph_id strategy | Session-level (`"companion-{uuid}"`) | Single long-lived graph_id per companion session |
| Debouncing | Dispatcher-level per handler | `SidebarComposer` at 150ms, `EditSummarizer` at 500ms |
| Swarm integration | Event-based delegation (future) | Pipeline emits requests; Swarm writes to Cairn workspace |
