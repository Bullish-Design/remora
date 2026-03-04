# Clean-Slate Redesign: Remora + Embeddy Full Alignment

> What would it look like if we redesigned the remora companion from the ground up with embeddy at its core — not as a bolted-on dependency, but as a deeply integrated substrate? What would that enable?

---

## 1. The Vision — Full Alignment

### What "Aligned" Means

The previous brainstorms treated embeddy as something remora *uses* — a better indexing backend, a search library to call. That framing inherits a fundamental assumption: that indexing and search are *services* sitting outside the agent architecture, called imperatively when needed.

Full alignment means something different. It means embeddy's capabilities are expressed *through* remora's primitives:

- **Indexing is event-driven.** When remora emits a `FileSavedEvent` or `NodeDiscoveredEvent`, the IndexingAgent reacts by calling embeddy's Pipeline. Chunks are stored in embeddy's own tables (not the event log), and the agent emits a single `IndexUpdatedEvent` summarizing what changed. The event log stays lean — it records *what happened* (a file was indexed), not the thousands of individual chunks produced. Other agents can subscribe to `IndexUpdatedEvent` to react to index changes.

- **Search is a workspace read.** An agent doesn't call `search_service.hybrid_search(query)`. It writes a query to a workspace path (`/search/queries/q_12345`), and a SearchAgent reacts by writing results to `/search/results/q_12345/*`. Downstream agents subscribe to those result paths. The search *happens* through the same reactive mechanism as everything else.

- **The index is causally derived from events.** Every chunk in the index exists because some event (FileSaved, NodeDiscovered) triggered the IndexingAgent. You could delete the entire index and rebuild it by replaying the triggering events through the IndexingAgent. The index is derived state — but the chunks themselves live in embeddy's storage tables, not in the event log. This keeps the event log focused on meaningful system events while the index handles its own high-volume data.

- **Embedding is an agent capability.** Any agent in the swarm can request embeddings. The embedding model is a shared resource, not locked inside an indexing pipeline. An agent analyzing code can embed its own summary and store it for others to find.

- **Storage is cleanly separated.** Remora's EventStore and embeddy's VectorStore are separate SQLite databases with separate concerns. The EventStore holds events, nodes, subscriptions, and graph edges — the system of record. The VectorStore holds chunks, vectors, and FTS indexes — the derived search index. They communicate through events (`IndexUpdatedEvent`), not shared connections. Each database has its own WAL-mode connection, its own lifecycle, and can be backed up or rebuilt independently.

### The Core Insight

Remora's architecture is built on three primitives: **events**, **workspaces**, and **agents**. Embeddy's architecture is built on three primitives: **chunks**, **embeddings**, and **search**. Full alignment means mapping the latter onto the former:

| Embeddy Primitive | Remora Expression |
|---|---|
| Chunk | Stored in embeddy tables, causally linked to triggering event via IndexUpdatedEvent |
| Embedding | Agent capability (tool on any AgentNode) |
| Search | Agent (SearchAgent subscribes to query events, writes results to workspace) |
| Collection | Workspace partition or metadata tag |
| Pipeline | Event-driven agent chain (file event -> IndexingAgent -> embeddy Pipeline -> IndexUpdatedEvent) |

When the primitives map cleanly, there's no integration layer. Embeddy doesn't sit beside remora — it dissolves into it.

### What This Is NOT

This is not "remora depends on embeddy" or "embeddy depends on remora." Neither library absorbs the other. Instead:

- **Embeddy** remains a standalone embedding/search library. It gains hooks and extension points that make it event-source-aware, but it works fine without remora.
- **Remora** remains a standalone agent swarm framework. It gains built-in semantic capabilities, but those capabilities are provided through its own primitives (events, agents, workspaces).
- **The integration** is a thin mapping layer — probably a single module — that expresses embeddy operations as remora events and agents. This layer lives in remora (or in a shared package), not in embeddy.

The result: remora gets semantic superpowers without architectural compromise. Embeddy gets a reactive, event-driven deployment mode without losing its standalone identity.

---

## 2. Current Architectural Tensions

The companion feature was built as a proof-of-concept alongside remora core, and it shows. It replicates several of remora's core mechanisms in simplified, incompatible forms. Before designing the unified architecture, we need to name these tensions precisely.

### Tension 1: Two Workspace Systems

**Remora core** uses Cairn — a copy-on-write filesystem backed by SQLite. Each agent gets an isolated workspace via `CairnWorkspaceService`. Writes are layered (agent workspace -> stable workspace -> disk). The workspace is persistent, observable, and supports directory listing and path-based reads.

**Companion** uses `InMemoryWorkspace` — a Python `dict[str, str]`. It's fast and simple but ephemeral, invisible to other systems, and has no persistence. When the companion process dies, all workspace state vanishes.

**Why this matters:** Remora's architecture assumes workspace writes are the communication primitive between agents. If companion agents write to a dict that nothing else can see, they're cut off from the swarm. No core agent can observe what the companion is doing. No companion agent can read what a core agent wrote.

### Tension 2: Two Event Systems

**Remora core** has `EventStore` — an append-only SQLite-backed event log with a trigger queue. Events are frozen Pydantic models persisted to a `events` table. The trigger queue enables reactive routing: when an event is stored, matching subscriptions are identified and the relevant agents are queued for execution.

**Companion** has `PathChanged` events — lightweight in-memory dataclasses routed manually by `CompanionRuntime._handle_path_change()`. The routing logic is hardcoded: it iterates over all agents and checks if any of their subscribed path prefixes match the changed path. There's no persistence, no subscription registry, no trigger queue.

**Why this matters:** Two event systems means two realities. An event in the EventStore doesn't trigger companion agents. A PathChanged in the companion doesn't appear in the EventStore. There's no unified event log. You can't replay events to reconstruct state. You can't add a new agent that reacts to both core and companion events.

### Tension 3: Two Agent Models

**Remora core** has `AgentNode` — a rich model combining identity (from code AST), graph context (parent, callers, callees), runtime state, tools, subscriptions, and an LLM system prompt. AgentNodes are *discovered* from code via tree-sitter, not manually instantiated. They participate in the swarm via `SwarmExecutor.execute_agent_turn()`.

**Companion** has `AgentBase` — a manually instantiated base class with a `@subscribe` decorator for path patterns. Companion agents are rule-based (no LLM), have no graph context, no identity from code, and no tools. They're instantiated directly in `CompanionRuntime.__init__()` with hardcoded wiring.

**Why this matters:** Companion agents are invisible to remora's swarm. The SwarmExecutor doesn't know they exist. They can't be discovered, scheduled, or coordinated with core agents. If a core agent needs search results, it can't ask the companion's EmbeddingSearcher — they live in different universes.

### Tension 4: Sync vs Async

**Remora core** is async throughout — `EventStore.store()` is async, `SwarmExecutor.execute_agent_turn()` is async, workspace operations are async.

**Companion indexing** is entirely synchronous — `Indexer.index_file()` blocks, `SentenceTransformerEmbedder.embed()` blocks, `VectorStore.search()` blocks. The companion agents themselves are async (they use `async def process()`), but when `EmbeddingSearcher` calls `self.indexer.search()`, it blocks the event loop.

**Embeddy** is async throughout — `Pipeline.ingest_file()` is async, `SearchService.search()` is async, `VectorStore.store_chunks()` is async, `Embedder.encode()` is async.

**Why this matters:** The sync companion indexing blocks the async companion agent loop. This limits throughput and prevents concurrent indexing of multiple files. Embeddy's async nature aligns with remora core, but the current companion creates a sync bottleneck between them.

### Tension 5: Two Storage Layers

**Remora core** uses a SQLite database (via EventStore) containing: `events`, `nodes`, `subscriptions`, `edges`, `activation_chain`, `proposals`, `cursor_focus`, `command_queue`. WAL mode enabled.

**Companion indexing** uses a *separate* SQLite database (via its own VectorStore) containing: `chunks` table with a `chunks_vec` virtual table (sqlite-vec). No FTS5. No collections. Separate file, separate connection, separate lifecycle.

**Embeddy** uses its *own* SQLite database with: per-collection `{name}_chunks` tables, per-collection `{name}_vec` virtual tables (sqlite-vec), per-collection `{name}_fts` virtual tables (FTS5), plus a `collections` metadata table. WAL mode enabled.

**Why this matters:** Three databases means three storage systems that can drift. If the event log says a file was indexed but the vector store disagrees, which is right? If the companion's VectorStore has chunks that embeddy's VectorStore doesn't, which do you search? Replacing the companion's ad-hoc VectorStore with embeddy reduces this to two well-defined systems (EventStore + embeddy VectorStore), and `IndexUpdatedEvent` provides the causal link between them — when the EventStore says a file was indexed, the VectorStore has the chunks to prove it.

### The Compound Effect

These tensions aren't independent — they compound. Because the companion has its own workspace, it needs its own event routing. Because it has its own event routing, it needs its own agent model. Because it has its own agent model, it needs its own storage. Each divergence necessitates the next, until the companion is effectively a separate system running inside remora's process but sharing none of its architecture.

The clean-slate redesign eliminates all five tensions simultaneously by expressing companion capabilities through remora's existing primitives.

---

## 3. Unified Architecture Proposal

### The Big Picture

```
                          ┌─────────────────────────────────┐
                          │        Remora Swarm              │
                          │                                  │
  File saved ──────►  EventStore  ◄──── Node discovered      │
  Content changed ──►  (SQLite)   ◄──── Cursor moved         │
  Cursor focus ─────►    │        ◄──── Agent messages        │
                         │                                   │
                    SubscriptionRegistry                     │
                         │                                   │
              ┌──────────┼──────────────┐                    │
              ▼          ▼              ▼                     │
        ┌──────────┐ ┌──────────┐ ┌──────────┐              │
        │ Indexing  │ │ Search   │ │ Context  │  ... more    │
        │ Agent    │ │ Agent    │ │ Agent    │  agents      │
        └────┬─────┘ └────┬─────┘ └────┬─────┘              │
             │            │            │                     │
             │  embeddy   │  embeddy   │                     │
             │  Pipeline  │  Search    │                     │
             │     │      │  Service   │                     │
             ▼     │      ▼            │                     │
        ┌──────────┴───────────┐       │                     │
        │  Embeddy VectorStore │       │                     │
        │  (SQLite: vectors,   │       │                     │
        │   FTS, chunks)       │       │                     │
        └──────────────────────┘       │                     │
                                       │                     │
                    Cairn Workspaces (CoW per agent)          │
                          │                                  │
              ┌───────────┼───────────┐                      │
              ▼           ▼           ▼                      │
        /index/status  /search/results  /context/*           │
        /index/collections  /search/queries  /analysis/*     │
                                                             │
                          └─────────────────────────────────┘

Note: EventStore and VectorStore use separate SQLite databases.
They are fundamentally different systems (event log vs vector DB)
and communicate through events, not shared connections.
```

### The Five Resolutions

Each tension from Section 2 is resolved by a specific architectural choice:

| Tension | Resolution |
|---|---|
| Two workspace systems | Companion agents use Cairn workspaces (same as core agents) |
| Two event systems | All events go through EventStore. PathChanged becomes a real event type. |
| Two agent models | Companion agents become AgentNodes (registered, not discovered from AST) |
| Sync vs async | Companion indexing uses embeddy's async Pipeline. No sync code. |
| Two storage layers | Companion's ad-hoc VectorStore replaced by embeddy. Two clean databases (EventStore + VectorStore) linked by IndexUpdatedEvent |

### New Agent Roster

The current companion has 5 agents with ad-hoc wiring. The unified architecture has the same logical capabilities expressed as proper AgentNodes:

#### IndexingAgent (replaces Indexer)
- **Type:** Registered AgentNode (not AST-discovered, since it's infrastructure)
- **Subscribes to:** `FileSavedEvent`, `ContentChangedEvent`, `NodeDiscoveredEvent`
- **Uses:** embeddy `Pipeline` for chunk/embed/store
- **Emits:** `IndexUpdatedEvent(source, collection, chunks_added, chunks_removed, content_hash)`
- **Workspace writes:** `/index/status/{source_path}` (JSON: chunks indexed, hash, timestamp)
- **Behavior:** On file event, computes content hash. If unchanged, skip. If changed, calls `Pipeline.reindex_file()`. Emits a single `IndexUpdatedEvent` summarizing the result. Writes status to workspace. Chunks are stored in embeddy's own tables, not in the event log — this keeps the event log lean (one event per file, not one per chunk).

#### SearchAgent (replaces EmbeddingSearcher)
- **Type:** Registered AgentNode
- **Subscribes to:** Workspace path `/search/queries/*` (written by other agents)
- **Uses:** embeddy `SearchService` for vector, fulltext, and hybrid search
- **Emits:** `SearchCompletedEvent(query_id, result_count, search_type)`
- **Workspace writes:** `/search/results/{query_id}/*` (one file per result, JSON)
- **Behavior:** Reads query from workspace path. Calls appropriate SearchService method. Writes ranked results to workspace. Emits completion event.

#### ContextAgent (replaces CursorTracker + ContextExtractor)
- **Type:** Registered AgentNode
- **Subscribes to:** `CursorFocusEvent` (already exists in remora core)
- **Uses:** Workspace reads for source file content
- **Emits:** `ContextExtractedEvent(file_path, region, content_type)`
- **Workspace writes:** `/context/current_region` (the extracted text), `/context/metadata` (content type, line range, etc.)
- **Behavior:** On cursor focus, extracts surrounding code region. Writes to workspace. Also writes a search query to `/search/queries/context_{ts}` to trigger SearchAgent.

#### AnalysisAgent (replaces ConnectionFinder)
- **Type:** Registered AgentNode
- **Subscribes to:** `SearchCompletedEvent` (from SearchAgent)
- **Uses:** Workspace reads of search results + context
- **Emits:** `AnalysisCompleteEvent(connections_found)`
- **Workspace writes:** `/analysis/connections/*` (JSON per connection: type, source, target, confidence)
- **Behavior:** Reads search results from workspace. Identifies connections (test<->impl, doc<->code, concept links). Now has three search channels to work with (vector, fulltext, hybrid) instead of just KNN.

#### ComposerAgent (replaces SidebarComposer)
- **Type:** Registered AgentNode
- **Subscribes to:** `ContextExtractedEvent`, `SearchCompletedEvent`, `AnalysisCompleteEvent`
- **Uses:** Workspace reads of context, search results, analysis
- **Workspace writes:** `/output/sidebar.md` (composed markdown)
- **Behavior:** Composes a human-readable sidebar from all available context. Reads from workspace paths populated by other agents. Produces final output.

### Agent Registration vs Discovery

Remora core discovers AgentNodes from code via tree-sitter — the code IS the agent. But companion agents aren't code entities; they're infrastructure. The clean-slate design introduces a distinction:

- **Discovered agents:** Found in code via tree-sitter. Identity comes from AST. These are the code-intelligence agents that remora is built for.
- **Registered agents:** Declared programmatically. Identity comes from configuration. These are infrastructure agents that provide services (indexing, search, analysis) to the discovered agents.

Both types are full AgentNodes with subscriptions, tools, and workspace access. The only difference is how they enter the system. Remora core needs a `register_agent()` method on the SwarmExecutor or EventStore to support this — a small addition that makes the agent model complete.

### The Data Flow

Here's a concrete scenario showing how data flows through the unified system when a developer saves a file:

```
1. Developer saves auth.py
2. IDE emits FileSavedEvent(path="auth.py") → EventStore
3. SubscriptionRegistry matches:
   - IndexingAgent (subscribed to FileSavedEvent)
4. SwarmExecutor queues IndexingAgent for execution
5. IndexingAgent:
   a. Reads auth.py content
   b. Computes SHA-256 hash → different from stored hash
   c. Calls Pipeline.reindex_file("auth.py", content)
   d. Pipeline: chunks (PythonChunker) → embeds (Embedder) → stores (VectorStore)
   e. Emits IndexUpdatedEvent(path="auth.py", collection="code", chunks_added=12, chunks_removed=8)
   g. Writes /index/status/auth.py → {"chunks": 12, "hash": "abc123", "ts": ...}
6. Meanwhile, developer's cursor is in auth.py
7. IDE emits CursorFocusEvent(path="auth.py", line=42) → EventStore
8. SubscriptionRegistry matches:
   - ContextAgent (subscribed to CursorFocusEvent)
9. ContextAgent:
   a. Extracts code region around line 42
   b. Writes /context/current_region → extracted code
   c. Writes /search/queries/ctx_001 → {"query": <extracted code>, "type": "hybrid", "k": 10}
10. Workspace write to /search/queries/* triggers:
    - SearchAgent (subscribed to /search/queries/*)
11. SearchAgent:
    a. Reads query from /search/queries/ctx_001
    b. Calls SearchService.hybrid_search(query, k=10)
    c. Writes /search/results/ctx_001/result_0 ... result_9
    d. Emits SearchCompletedEvent(query_id="ctx_001", count=10)
12. SearchCompletedEvent triggers:
    - AnalysisAgent (subscribed to SearchCompletedEvent)
    - ComposerAgent (subscribed to SearchCompletedEvent)
13. AnalysisAgent:
    a. Reads search results from /search/results/ctx_001/*
    b. Finds: test_auth.py tests this function, auth_docs.md documents it
    c. Writes /analysis/connections/conn_001 → {type: "test", source: "auth.py:42", target: "test_auth.py:15"}
    d. Emits AnalysisCompleteEvent
14. ComposerAgent:
    a. Reads /context/current_region, /search/results/ctx_001/*, /analysis/connections/*
    b. Composes sidebar markdown
    c. Writes /output/sidebar.md
15. Sidebar displayed to developer
```

Every step is an event or a workspace write. Every agent is a proper AgentNode. Every piece of data is in the EventStore, embeddy's VectorStore, or Cairn workspaces. Nothing is hidden in a Python dict or a sync function call.

---

## 4. Reactive Indexing Pipeline — Events In, Chunks Out

### How Indexing Works Today

**Companion (current):** `CompanionRuntime.__init__()` calls `self.indexer.index_directory(project_root)` at startup. This synchronously walks every file, chunks it, embeds all chunks in a batch, and stores them. It's a one-shot operation. If a file changes after startup, the companion has no mechanism to re-index it (the `FileChanged` model exists in models/events.py but nothing actually triggers re-indexing from it).

**Embeddy (standalone):** `Pipeline.ingest_file()` is async and supports `reindex_file()` which deletes old chunks for a source and re-ingests. It has content-hash deduplication — if a chunk's content hasn't changed, the hash matches and the embedding is reused. But the Pipeline is pull-based: something must call `ingest_file()`. There's no built-in way to react to external events.

### How Indexing Works in the Unified Architecture

The IndexingAgent bridges remora's event system and embeddy's Pipeline:

```python
class IndexingAgent:
    """Registered AgentNode that reacts to file/node events by indexing content."""

    subscriptions = [
        SubscriptionPattern(event_types=["FileSavedEvent"]),
        SubscriptionPattern(event_types=["ContentChangedEvent"]),
        SubscriptionPattern(event_types=["NodeDiscoveredEvent"]),
    ]

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline  # embeddy Pipeline (own database)

    async def handle_event(self, event: Event, workspace: AgentWorkspace):
        if isinstance(event, (FileSavedEvent, ContentChangedEvent)):
            stats = await self.pipeline.reindex_file(
                source=event.file_path,
                content=event.content,  # or read from disk
                collection="code",       # route to appropriate collection
            )
            await workspace.write(
                f"/index/status/{event.file_path}",
                json.dumps({"chunks": stats.chunks_stored, "hash": stats.content_hash})
            )

        elif isinstance(event, NodeDiscoveredEvent):
            # Index the discovered code node directly
            await self.pipeline.ingest_text(
                text=event.source_code,
                source=f"node:{event.node_id}",
                collection="nodes",
                metadata={"node_type": event.node_type, "file": event.file_path}
            )
```

### Three Indexing Triggers

The unified architecture has three distinct triggers for indexing, each serving a different purpose:

**1. FileSavedEvent — File-level indexing**
When the IDE saves a file, the entire file is re-indexed. Embeddy's `reindex_file()` handles this efficiently: it computes a content hash, compares with the stored hash, and only re-embeds if the content actually changed. Changed chunks are identified by comparing individual chunk hashes.

**2. ContentChangedEvent — Incremental indexing**
When the IDE reports a content change (e.g., a keystroke or paste), the IndexingAgent can decide whether to re-index immediately or debounce. For keystroke-level changes, debouncing to ~2 seconds avoids thrashing. For large pastes or reformats, immediate re-index makes sense. The agent has context to decide.

**3. NodeDiscoveredEvent — Semantic indexing**
This is new and powerful. When remora's tree-sitter parser discovers a code node (function, class, method), it emits `NodeDiscoveredEvent` with the node's source code, type, and identity. The IndexingAgent can embed this node in a dedicated `nodes` collection, with metadata linking it to its file and position. This creates a *semantic* index of the codebase — not just file chunks, but meaningful code units.

### The Index as Derived State

A key property of this design: the vector index is *causally derived* from the event log. Every chunk in the index exists because some event (FileSaved, NodeDiscovered) triggered the IndexingAgent to create it. However, chunks themselves are **not** stored as events — they live in embeddy's own tables (`{collection}_chunks`, `{collection}_vec`, `{collection}_fts`). The event log records the *operations* (`IndexUpdatedEvent`), not the individual artifacts.

> **Why not store chunks as events?** A modest project produces 2,000-5,000 chunks on first index, with 10-50 more per file save. Making each chunk an event would flood the event log — outnumbering real system events (FileSaved, CursorFocus, AgentComplete) by 10-100x. This causes: trigger queue thrashing (subscription matching for every chunk), WAL pressure during bulk indexing, and an event log dominated by indexing noise rather than meaningful system events. Storing one `IndexUpdatedEvent` per file keeps the event log lean and focused.

This means:

- **Rebuild from scratch:** Delete the vector tables and replay all `FileSavedEvent` and `NodeDiscoveredEvent` from the event log *through the IndexingAgent*. The agent re-chunks, re-embeds, and re-stores. Content-hash dedup makes this efficient — unchanged chunks skip embedding.
- **Audit trail:** `IndexUpdatedEvent` records which file was indexed, how many chunks were added/removed, and the content hash. For finer detail, the chunks table itself has `content_hash` and `source` metadata.
- **Time travel:** Because events are timestamped and ordered, you could (in principle) reconstruct the index at any point by replaying events up to that timestamp through the IndexingAgent.
- **Consistency guarantee:** The IndexingAgent stores chunks in embeddy's VectorStore, then emits `IndexUpdatedEvent` to remora's EventStore. If the chunk store succeeds but the event emission fails, the IndexingAgent can retry the event — the chunks are idempotent (content-hash dedup). The `on_file_indexed` pipeline hook provides the natural boundary between the two operations.

This is the pragmatic middle ground: events *drive* indexing, indexing *produces* chunks, chunks live in their own tables. The event log stays lean and meaningful. The index is still deterministically derivable from the event history.

### Content-Hash Deduplication — Already Aligned

Both systems already use content hashing:

- **Embeddy:** `Pipeline._compute_hash()` uses SHA-256 on chunk content. Before embedding a chunk, it checks if a chunk with the same hash already exists. If so, skip.
- **Remora:** `NodeDiscoveredEvent.source_hash` is a hash of the node's source code. The nodes table tracks `source_hash` per node.

In the unified system, these hashes serve the same purpose and can be compared directly. When a `NodeDiscoveredEvent` arrives with a `source_hash` that matches an existing chunk's `content_hash`, the IndexingAgent knows the embedding is still valid. Zero redundant work.

### Collection Routing

The IndexingAgent routes content to appropriate embeddy collections based on the event type and content:

| Event | Collection | Rationale |
|---|---|---|
| FileSavedEvent (*.py) | `code` | Source code, chunked by PythonChunker (AST-aware) |
| FileSavedEvent (*.md) | `docs` | Documentation, chunked by MarkdownChunker (heading-aware) |
| FileSavedEvent (*.txt, *.rst) | `docs` | Documentation, generic chunking |
| NodeDiscoveredEvent | `nodes` | Semantic code units (functions, classes) — one chunk per node |
| ContentChangedEvent | Same as file type | Re-indexes the changed file's collection |

Collections provide namespace isolation for search. When the SearchAgent does a code search, it queries the `code` collection. When it searches documentation, it queries `docs`. Hybrid search can span multiple collections when needed.

---

## 5. Search as Agent Capability

### The Current Problem

In the companion today, search is buried inside `EmbeddingSearcher.process()`:

```python
# Current: search is an imperative call hidden inside one agent
results = self.indexer.search(query_text, k=5)
```

No other agent can search. The ConnectionFinder can't do a targeted search. The SidebarComposer can't verify a connection by searching. If a future agent needs to find related code, it has to somehow reach the Indexer instance — breaking the "agents don't know each other" principle.

### Two Modes of Search Access

The unified architecture provides search through two complementary mechanisms:

#### Mode 1: Search as a Tool (Direct)

Embeddy's `SearchService` is wrapped as a `ToolSchema` that can be attached to any AgentNode:

```python
search_tool = ToolSchema(
    name="search_codebase",
    description="Search the indexed codebase using vector, fulltext, or hybrid search",
    parameters={
        "query": {"type": "string", "description": "Search query text"},
        "search_type": {"type": "string", "enum": ["vector", "fulltext", "hybrid"], "default": "hybrid"},
        "collection": {"type": "string", "default": "code"},
        "k": {"type": "integer", "default": 10},
    },
    handler=search_service_handler,
)
```

Any AgentNode — discovered or registered — can have this tool attached. An LLM-powered code agent can call `search_codebase` to find relevant code before making a suggestion. A documentation agent can search for code that matches a doc string. The search capability is democratized across the entire swarm.

This is the mode for LLM-powered agents that make tool calls during `execute_agent_turn()`.

#### Mode 2: Search as Reactive Agent (Indirect)

For rule-based agents (like the current companion agents), search works through the workspace:

1. Agent writes a query to `/search/queries/{query_id}` (JSON with query text, type, params)
2. SearchAgent (subscribed to `/search/queries/*`) picks it up
3. SearchAgent calls `SearchService`, writes results to `/search/results/{query_id}/*`
4. Original agent (or any interested agent) reads results from workspace

This is the mode for reactive pipeline agents that communicate through workspace paths. It preserves the "agents don't know each other" principle — the requesting agent doesn't know or care that SearchAgent is the one fulfilling the query.

### Three Search Channels

The companion's current EmbeddingSearcher only has KNN vector search. Embeddy brings three distinct search methods, each with different strengths:

**Vector search (KNN via sqlite-vec):**
- Finds semantically similar content
- Great for: "code that does something like this," conceptual matches, cross-language similarity
- Misses: exact name matches, keyword queries, short identifiers

**Fulltext search (BM25 via FTS5):**
- Finds exact and stemmed keyword matches
- Great for: function names, variable names, error messages, exact strings
- Misses: conceptual similarity, paraphrased content, cross-language matches

**Hybrid search (RRF or weighted fusion):**
- Combines vector and fulltext results using Reciprocal Rank Fusion or weighted scoring
- Gets the best of both: semantic similarity AND keyword precision
- This is what the ContextAgent should use by default for companion-style queries

### Impact on ConnectionFinder

The current ConnectionFinder identifies connections like test<->implementation, doc<->code, and parallel implementations. It works from KNN results only, which means:

- It catches *conceptually similar* code (good for parallel implementations)
- It misses *name-based* connections (test_auth.py testing auth.py — BM25 catches this instantly by matching "auth")

With three search channels, the AnalysisAgent (successor to ConnectionFinder) receives richer input:

- **Vector results** surface conceptually related code (e.g., two different auth implementations)
- **Fulltext results** surface name-linked code (e.g., `test_authenticate` matches `authenticate`)
- **Hybrid results** surface the best of both

The AnalysisAgent can also *issue its own follow-up searches* via the search tool or workspace queries. It sees a potential connection and searches for more evidence. This turns analysis from a single-pass operation into an iterative refinement.

### Search Result Format

Results written to workspace paths use a consistent JSON format:

```json
// /search/results/{query_id}/result_003
{
    "rank": 3,
    "score": 0.847,
    "search_type": "hybrid",
    "source": "src/auth/handler.py",
    "chunk_id": "abc123",
    "content": "def authenticate(user, password): ...",
    "metadata": {
        "content_type": "python",
        "line_start": 42,
        "line_end": 67,
        "collection": "code"
    }
}
```

This format is consumable by any downstream agent — rule-based or LLM-powered. An LLM agent can read the content directly. A rule-based agent can filter by score, source, or content type.

---

## 6. Workspace Convergence — Cairn All the Way Down

### The InMemoryWorkspace Problem

The companion's `InMemoryWorkspace` is a `dict[str, str]` with `read()`, `write()`, `exists()`, and `list_dir()` methods. It works, but it has critical limitations:

1. **No persistence.** Process dies, state dies. There's no way to resume a companion session.
2. **No isolation.** All agents share the same dict. An agent can overwrite another agent's data. There's no copy-on-write boundary.
3. **No observability.** `CompanionRuntime` manually polls for path changes after each agent runs. There's no event emitted on write, no subscription mechanism for path patterns.
4. **No fallback to disk.** Agent workspaces in remora core have a layered read: agent workspace -> stable workspace -> disk. The companion's dict is flat.

### Cairn as the Universal Workspace

Remora core already has the right abstraction: `AgentWorkspace` wraps a Cairn workspace with CoW semantics. Each agent gets its own workspace ID. Writes are isolated. Reads fall back through layers. The workspace is SQLite-backed (or could be), so it persists across restarts.

In the unified architecture, companion agents use `AgentWorkspace` exactly like core agents:

```python
# Current companion agent
class ContextExtractor(AgentBase):
    async def process(self, workspace: InMemoryWorkspace, ...):
        await workspace.write("/companion/context/current_region", text)

# Unified architecture
class ContextAgent:  # registered AgentNode
    async def handle_event(self, event: CursorFocusEvent, workspace: AgentWorkspace):
        await workspace.write("/context/current_region", text)
```

The API is nearly identical — `write(path, content)`, `read(path)`, `exists(path)`, `list_dir(path)`. The difference is everything underneath: persistence, isolation, observability.

### Workspace Writes as Events

Here's the key architectural insight: in remora core, workspace writes can (and should) produce events. When an agent writes to `/search/queries/ctx_001`, that write can emit a `WorkspaceWriteEvent(agent_id, path, workspace_id)` into the EventStore. The SubscriptionRegistry can then match this event against subscriptions with `path_glob` patterns.

This unifies the two event systems completely:

- **Core events** (FileSaved, NodeDiscovered, etc.) trigger agent subscriptions via EventStore
- **Workspace writes** also trigger agent subscriptions via EventStore
- **No separate PathChanged routing needed**

The companion's current `CompanionRuntime._handle_path_change()` — which manually iterates agents and checks path prefixes — is replaced by the standard SubscriptionRegistry doing its normal job.

### Workspace Path Convention

With Cairn workspaces, the path namespace becomes a shared contract between agents. Here's the proposed layout:

```
/                               # workspace root
├── index/
│   ├── status/                 # IndexingAgent writes here
│   │   ├── src/auth.py         # {"chunks": 12, "hash": "abc...", "ts": 1234}
│   │   └── src/models.py
│   └── collections/            # collection metadata
│       ├── code                # {"count": 450, "last_indexed": ...}
│       └── docs
├── context/
│   ├── current_region          # ContextAgent: extracted code around cursor
│   ├── metadata                # ContextAgent: content type, line range
│   └── history/                # recent cursor contexts
│       ├── ctx_001
│       └── ctx_002
├── search/
│   ├── queries/                # Any agent can write here to request a search
│   │   ├── ctx_001             # {"query": "...", "type": "hybrid", "k": 10}
│   │   └── analysis_follow_001
│   └── results/                # SearchAgent writes here
│       ├── ctx_001/
│       │   ├── result_000
│       │   └── result_009
│       └── analysis_follow_001/
├── analysis/
│   └── connections/            # AnalysisAgent writes here
│       ├── conn_001            # {"type": "test", "source": ..., "target": ...}
│       └── conn_002
└── output/
    └── sidebar.md              # ComposerAgent writes here
```

Every path is readable by any agent. Every write is observable through workspace events. The path structure is a convention, not a hard schema — new agents can create new paths without modifying existing code.

### Shared vs Isolated Workspaces

One nuance: remora core uses CoW workspaces so that agent modifications don't affect other agents until committed. For the companion agents, this isolation is desirable for some paths and unnecessary for others:

- **Shared paths** (`/search/queries/*`, `/search/results/*`, `/output/*`): These are communication channels. Writes should be immediately visible to other agents. Use a shared (stable) workspace for these.
- **Isolated paths** (`/context/*`, `/analysis/*`): These are working state. An agent might write intermediate results before finalizing. Use per-agent CoW workspaces for these, with a commit/promote step when done.

The Cairn workspace model already supports both modes. The SwarmExecutor decides when to merge an agent's workspace into the stable workspace (typically after a successful agent turn). This gives companion agents the same transactional semantics as core agents.

---

## 7. New Capabilities Unlocked

The previous sections describe *how* the architecture works. This section describes *what becomes possible* — capabilities that neither remora nor embeddy can provide alone, but that emerge from their alignment.

### 7.1 Semantic Agent Discovery

**Today:** Remora discovers agents from code via tree-sitter. It finds functions, classes, methods — structural code units. Routing is based on event type matching and path glob patterns.

**With alignment:** When a new event arrives and no subscription explicitly matches, the SwarmExecutor could *search* for a relevant agent. Embed the event description, search the `nodes` collection, find agent nodes whose source code is semantically related to the event. "This event is about authentication — which agents deal with authentication?"

This turns agent routing from a pure subscription-match into a hybrid subscription + semantic search. Explicit subscriptions take priority (fast, deterministic). Semantic search is the fallback (slower, fuzzy, but handles novel situations).

```python
# Pseudocode for semantic agent routing
async def route_event(event: Event) -> list[AgentNode]:
    # 1. Explicit subscription match (existing behavior)
    matched = subscription_registry.match(event)
    if matched:
        return matched

    # 2. Semantic fallback — search for relevant agents
    query = f"{event.event_type}: {event.summary()}"
    results = await search_service.vector_search(query, collection="nodes", k=5)
    candidate_agents = [r.metadata["agent_id"] for r in results if r.score > 0.7]
    return candidate_agents
```

### 7.2 Embedding-Augmented LLM Context

**Today:** When remora's SwarmExecutor runs an LLM-powered agent turn, it constructs a context window from: the agent's system prompt, its graph context (parent, callers, callees), and the triggering event. This context is *structural* — it comes from the code graph.

**With alignment:** Before constructing the LLM context, the executor can search for *semantically relevant* code. The triggering event mentions "authentication" — search the `code` collection, find the top 5 relevant chunks, include them in the context window. The LLM now has not just structural context (what calls this function) but semantic context (what else in the codebase deals with similar concerns).

```python
# Pseudocode for augmented agent context
async def build_agent_context(agent: AgentNode, event: Event) -> str:
    # Structural context (existing)
    structural = agent.graph_context()  # parent, callers, callees

    # Semantic context (new)
    query = event.source_code or event.summary()
    semantic_results = await search_service.hybrid_search(query, collection="code", k=5)
    semantic = "\n".join([r.content for r in semantic_results])

    return f"{agent.system_prompt}\n\n## Structural Context\n{structural}\n\n## Related Code\n{semantic}"
```

This is RAG (Retrieval-Augmented Generation) applied to agent execution. It's not a separate RAG system — it's the same search infrastructure that powers the companion, now augmenting every LLM agent in the swarm.

### 7.3 Cross-Project Search

**Today:** Each remora instance operates on a single project. The companion indexes one directory.

**With alignment:** Embeddy's collection model naturally supports multi-project indexing. Each project gets its own collection (or set of collections). A developer working on a microservice can search across all related services:

```python
# Search across multiple project collections
results = await search_service.hybrid_search(
    query="rate limiting middleware",
    collection=["api_gateway_code", "auth_service_code", "billing_code"],
    k=10
)
```

This requires no architectural change — just indexing multiple project roots into different collections. The SearchAgent could accept a `collections` parameter in its query format, allowing any agent to specify which projects to search.

### 7.4 Index Rebuild from Event History

**Today:** If the companion's vector store gets corrupted or you want to change the embedding model, you have to re-index everything from scratch by re-scanning the filesystem.

**With alignment:** The index is causally derived from events. To rebuild:

1. Delete embeddy's database (or drop its collections)
2. Replay all `FileSavedEvent` and `NodeDiscoveredEvent` from the event log *through the IndexingAgent*
3. The IndexingAgent re-chunks, re-embeds, and re-stores, building a fresh vector index in embeddy's database

This works because:
- Events are immutable and ordered in the EventStore
- Content-hash dedup means replaying produces identical chunks
- The new embedding model produces new vectors, but the chunks and hashes are the same

You can even run this as a background task while the old index is still serving queries — swap atomically when the rebuild is complete.

### 7.5 Proactive "You Might Want to Look At..." Suggestions

**Today:** The companion reacts to cursor position. It finds similar code and connections. But it only searches based on what's under the cursor *right now*.

**With alignment:** The IndexingAgent emits `IndexUpdatedEvent` when a file is re-indexed. Any agent can subscribe to this. A new `SuggestionAgent` could:

1. Subscribe to `IndexUpdatedEvent`
2. When a file is re-indexed, search for files that *used to be* similar (from the old chunks) but might be affected by the change
3. Write suggestions to `/suggestions/` workspace paths
4. The ComposerAgent includes them in the sidebar: "auth.py was just modified — you might want to update test_auth.py (last modified 3 days ago)"

This is proactive, not reactive. The developer didn't ask — the system noticed a potential inconsistency and surfaced it.

### 7.6 Codebase-Aware Agent Routing

**Today:** Remora routes events to agents based on subscription patterns — event types, path globs, tags. These patterns are static.

**With alignment:** The `nodes` collection contains embedded representations of every discovered code node. When a new agent is registered or discovered, its source code is embedded and stored. This creates a *semantic map* of the agent swarm.

New routing possibilities:
- "Route this event to the agent whose code is most similar to the event's context"
- "Find all agents that deal with database operations" (semantic search on agent source code)
- "This error occurred in auth.py — which agents have modified auth.py before?" (combine event log query with semantic search)

### 7.7 Persistent Companion State

**Today:** The companion's `InMemoryWorkspace` is lost on restart. Every session starts cold — no memory of previous contexts, searches, or connections.

**With alignment:** Cairn workspaces persist to SQLite. The companion's workspace state survives restarts:
- Previous search results are still available
- Index status shows what's already indexed (no redundant startup scan)
- Context history shows where the developer was working before
- Analysis connections persist across sessions

This transforms the companion from a stateless reactor into a persistent assistant with memory.

### 7.8 Event-Sourced Analytics

**Today:** Neither system tracks usage patterns or provides analytics.

**With alignment:** The event log captures everything: every file save, every cursor movement, every search query, every index update. This is a complete record of developer behavior and system activity.

Possible analytics (all derivable from the event log):
- "Which files are modified most frequently?" (count FileSavedEvents per path)
- "Which code regions attract the most cursor time?" (aggregate CursorFocusEvents)
- "What search queries produce the best results?" (correlate SearchCompletedEvents with developer actions)
- "How stale is the index?" (compare last IndexUpdatedEvent per file with last FileSavedEvent)

These analytics aren't a separate system — they're just queries over the event log that already exists.

---

## 8. Migration Path

This is a clean-slate *design*, but it doesn't require a big-bang *implementation*. The architecture can be reached incrementally in two phases, each delivering value independently.

### Phase 1: Embeddy as Backend (Companion Internals Only)

**Scope:** Replace the companion's indexing internals with embeddy. No changes to remora core. No changes to the agent model. The companion still uses InMemoryWorkspace and PathChanged routing.

**What changes:**
- `companion/indexing/embedder.py` -> embeddy `Embedder`
- `companion/indexing/store.py` -> embeddy `VectorStore`
- `companion/indexing/chunker.py` -> embeddy chunker factory (`get_chunker()`)
- `companion/indexing/indexer.py` -> embeddy `Pipeline`
- `EmbeddingSearcher` calls `SearchService.hybrid_search()` instead of `Indexer.search()`
- `CompanionRuntime` initializes embeddy `Pipeline` instead of companion `Indexer`

**What stays the same:**
- `AgentBase`, `InMemoryWorkspace`, `PathChanged` routing — all unchanged
- Agent wiring in `CompanionRuntime` — same agents, same paths
- All 5 companion agents — same interfaces, same behavior

**What you get:**
- Hybrid search (vector + BM25) instead of KNN-only
- AST-aware Python chunking instead of regex-based
- Content-hash deduplication
- Async indexing (no more blocking the event loop)
- Larger embedding model (Qwen3-VL-2B vs Qwen3-0.6B) — better quality
- Collection support (separate code and docs indexes)

**Effort:** Small. This is essentially the "Option A" from the first brainstorm. A few days of work. Backward-compatible. Easy to test — same companion behavior, better search results.

**Risk:** Low. If something goes wrong, revert to the old indexing code. The companion's external behavior doesn't change.

### Phase 2: Agents as AgentNodes (Architecture Alignment)

**Scope:** Make companion agents proper AgentNodes. Introduce `register_agent()` to remora core. Replace InMemoryWorkspace with Cairn. Replace PathChanged with EventStore events.

**What changes:**
- `AgentBase` subclasses -> registered `AgentNode` instances
- `InMemoryWorkspace` -> `AgentWorkspace` (Cairn-backed)
- `PathChanged` events -> `WorkspaceWriteEvent` in EventStore
- `CompanionRuntime._handle_path_change()` -> SubscriptionRegistry matching
- Companion agents get proper `SubscriptionPattern` instead of `@subscribe` decorators
- `CompanionRuntime` becomes thin — just registers agents and starts the swarm

**What you get:**
- Companion agents are visible to the swarm
- Core agents can react to companion workspace writes
- Companion agents can react to core events (FileSaved, NodeDiscovered, etc.)
- Persistent workspace state (survives restarts)
- Unified event log (companion events visible to core, and vice versa)

**New in remora core:**
- `SwarmExecutor.register_agent(node: AgentNode)` — register non-discovered agents
- `WorkspaceWriteEvent` — emitted on workspace writes (optional, configurable)
- Agent execution for non-LLM agents — `execute_agent_turn()` currently assumes LLM; needs a path for rule-based agents

**Effort:** Medium. Requires changes to remora core (register_agent, WorkspaceWriteEvent, rule-based execution). Requires rewriting companion agents to use AgentNode/AgentWorkspace APIs. Maybe 1-2 weeks.

**Risk:** Medium. Changing the agent execution model affects remora core. Needs careful testing. But the core changes are additive — existing discovered agents are unaffected.

### Phase Summary

| Phase | Delivers | Changes Embeddy | Changes Remora Core | Changes Companion | Effort | Risk |
|---|---|---|---|---|---|---|
| 1 | Better search, async indexing | None | None | Indexing internals | Small | Low |
| 2 | Unified agents, persistent state | Event hooks (on_file_indexed) | register_agent, WorkspaceWriteEvent, IndexUpdatedEvent | Agent model, workspace, event integration | Medium | Medium |

Each phase is independently valuable and testable. Phase 1 can ship tomorrow. Phase 2 requires remora core work but unlocks the architectural alignment — including event integration where the IndexingAgent emits `IndexUpdatedEvent` and the Pipeline gains an `on_file_indexed` callback hook.

---

## 9. Concrete Changes Needed in Each Library

### Changes to Embeddy

These changes make embeddy integration-ready without breaking its standalone identity.

#### 9.1 Pipeline: on_file_indexed Hook (Phase 2)

**File:** `src/embeddy/pipeline/pipeline.py`

**Change:** Add an optional callback hook:
- `on_file_indexed(source: str, stats: IngestStats)` — called after a file is fully indexed

This is a simple callable (sync or async) passed at Pipeline construction. The IndexingAgent uses it to emit `IndexUpdatedEvent` into remora's EventStore. This is the bridge between embeddy's indexing pipeline and remora's event system — embeddy does the chunking/embedding/storing, then fires the callback so the IndexingAgent can announce the result.

**Backward compatible:** Yes. Hook is optional, defaults to None.

#### 9.2 SearchService: Multi-Collection Search (Phase 1+)

**File:** `src/embeddy/search/search_service.py`

**Change:** Allow `collection` parameter to accept a list of collection names. Search across multiple collections and merge results. This is useful for cross-collection queries (search both `code` and `docs`).

**Current state:** SearchService already takes a `collection: str` parameter. Change to `collection: str | list[str]`.

**Backward compatible:** Yes. Single string still works.

#### 9.3 Embedder: Expose as Standalone Utility (Already Done)

**File:** `src/embeddy/embedding/embedder.py`

**No change needed.** The `Embedder` class already supports `encode()` for arbitrary text. Any agent can use it directly to embed content. The LRU cache prevents redundant encoding.

### Changes to Remora Core

These changes extend remora core to support registered agents and workspace events.

#### 9.4 SwarmExecutor: register_agent() (Phase 2)

**File:** `src/remora/core/swarm_executor.py`

**Change:** Add `register_agent(node: AgentNode)` method. Stores the AgentNode in the nodes table and registers its subscriptions in the SubscriptionRegistry. Unlike discovered agents (from tree-sitter), registered agents have no AST identity — their identity comes from a provided `agent_id` string.

**Impact:** Additive. Discovered agents unaffected.

#### 9.5 SwarmExecutor: Rule-Based Agent Execution (Phase 2)

**File:** `src/remora/core/swarm_executor.py`

**Change:** `execute_agent_turn()` currently constructs an LLM prompt and calls the model. For registered infrastructure agents, it needs an alternate path: call the agent's `handle_event()` method directly (no LLM). The AgentNode needs a field like `execution_mode: Literal["llm", "direct"]` to distinguish.

**Impact:** Moderate. The execution path branches, but LLM agents are unaffected.

#### 9.6 New Event Types (Phase 2)

**File:** `src/remora/core/events.py`

**New events:**
- `WorkspaceWriteEvent(agent_id, workspace_id, path, content_hash)` — emitted when an agent writes to a workspace path. Enables subscription matching on workspace writes.
- `IndexUpdatedEvent(source, collection, chunks_added, chunks_removed, content_hash)` — emitted after a file is fully indexed. One event per file, NOT per chunk — keeps the event log lean. See Section 4 for rationale.
- `SearchCompletedEvent(query_id, search_type, result_count)` — emitted after a search completes
- `ContextExtractedEvent(file_path, line_start, line_end, content_type)` — emitted after context extraction
- `AnalysisCompleteEvent(connection_count)` — emitted after analysis finishes

**Impact:** Additive. New event types don't affect existing events.

#### 9.7 Workspace: Write Event Emission (Phase 2)

**File:** `src/remora/core/workspace.py`

**Change:** `AgentWorkspace.write()` optionally emits a `WorkspaceWriteEvent` to the EventStore. This is what replaces the companion's PathChanged routing. Configurable per-workspace (not all writes need events — high-frequency writes like cursor tracking might want to opt out).

**Impact:** Low. Existing workspace behavior unchanged unless opted in.

### Changes to Companion (Remora Demo)

These changes rewrite the companion on top of the unified architecture.

#### 9.8 Delete: Companion Indexing Layer (Phase 1)

**Files to remove:**
- `remora_demo/companion/indexing/embedder.py`
- `remora_demo/companion/indexing/store.py`
- `remora_demo/companion/indexing/chunker.py`
- `remora_demo/companion/indexing/indexer.py`

**Replace with:** embeddy `Pipeline`, `SearchService`, `Embedder`, `VectorStore` (configured via `EmbeddyConfig`).

#### 9.9 Rewrite: Companion Agents (Phase 2)

**Files to rewrite:**
- `remora_demo/companion/agents/base.py` -> Delete (use AgentNode)
- `remora_demo/companion/agents/sensors/cursor_tracker.py` -> Merge into ContextAgent
- `remora_demo/companion/agents/extractors/context_extractor.py` -> ContextAgent
- `remora_demo/companion/agents/searchers/embedding_searcher.py` -> SearchAgent
- `remora_demo/companion/agents/analyzers/connection_finder.py` -> AnalysisAgent
- `remora_demo/companion/agents/composers/sidebar_composer.py` -> ComposerAgent

**New files:**
- `remora_demo/companion/agents/indexing_agent.py`
- `remora_demo/companion/agents/search_agent.py`
- `remora_demo/companion/agents/context_agent.py`
- `remora_demo/companion/agents/analysis_agent.py`
- `remora_demo/companion/agents/composer_agent.py`

Each is a thin wrapper: an AgentNode with subscriptions, a `handle_event()` method, and calls to embeddy or workspace operations.

#### 9.10 Rewrite: CompanionRuntime (Phase 2)

**File:** `remora_demo/companion/runtime.py`

**Current:** Manually instantiates agents, manages InMemoryWorkspace, routes PathChanged events, calls `indexer.index_directory()` at startup.

**New:** Registers agents via `SwarmExecutor.register_agent()`, initializes embeddy Pipeline with shared config, starts the swarm. No manual routing — SubscriptionRegistry handles it.

The runtime shrinks from ~200 lines of manual wiring to ~50 lines of registration.

#### 9.11 Delete: InMemoryWorkspace (Phase 2)

**File:** `remora_demo/companion/agents/base.py`

**Removed entirely.** Companion agents use `AgentWorkspace` (Cairn-backed) provided by the SwarmExecutor on each turn.

#### 9.12 Delete: PathChanged Event System (Phase 2)

**File:** `remora_demo/companion/models/events.py`

**PathChanged, CursorMoved, ContentEdited, FileChanged, SessionTick** — all replaced by remora core events (CursorFocusEvent, FileSavedEvent, ContentChangedEvent, etc.) or WorkspaceWriteEvent.

### What Stays Unchanged

- **Remora core event model** — frozen Pydantic events, EventStore, SubscriptionRegistry. All existing event types unchanged.
- **Remora core agent discovery** — tree-sitter based AgentNode discovery from code. Unaffected.
- **Embeddy standalone usage** — CLI, server, client, direct library usage. All unchanged.
- **Embeddy chunking** — PythonChunker, MarkdownChunker, etc. Used as-is by the companion's IndexingAgent.
- **Embeddy search** — SearchService with vector/fulltext/hybrid. Used as-is by the companion's SearchAgent.

---

## Summary

Full alignment means embeddy's capabilities are expressed through remora's primitives — events, workspaces, and agents. The companion stops being a parallel system and becomes part of the swarm. The result is:

1. **One event system** — all events in one EventStore, all routing through one SubscriptionRegistry
2. **One workspace system** — all agents use Cairn workspaces, all writes are observable
3. **One agent model** — discovered (from code) and registered (infrastructure), both full AgentNodes
4. **Clean storage separation** — EventStore (events, nodes, graph) and VectorStore (chunks, vectors, FTS) as separate databases linked by `IndexUpdatedEvent`
5. **Async throughout** — no sync bottlenecks

What this enables:
- Semantic agent discovery and routing
- Embedding-augmented LLM context (RAG for every agent)
- Cross-project search
- Index as derived state (rebuildable from event history, auditable via IndexUpdatedEvent)
- Proactive suggestions
- Persistent companion state
- Event-sourced analytics

The migration is incremental: Phase 1 (embeddy as backend) delivers immediate value with minimal risk. Phase 2 (agents as AgentNodes) unlocks full architectural alignment with event integration, persistent workspaces, and unified agent routing. Each phase is independently valuable and shippable.

---

## Appendix A: AST-Aware, Node-Type-Specific Search & Graph-Linked Embeddings

### The Missing Dimension

The main brainstorm treats indexing as file-level: a file is saved, the IndexingAgent chunks it, embeds the chunks, stores them. But this misses something fundamental about how remora sees code. Remora doesn't see *files* — it sees *nodes*. Functions, methods, classes, sections, tables, notes. Each with a type, a parent, callers, callees. A graph.

The question is: what happens when we embed at the *node* level, not the file level? And what happens when the graph relationships between nodes are preserved in the embedding index?

### What Remora's Tree-Sitter Discovery Gives Us

When remora parses a Python file, it doesn't produce one CSTNode. It produces a *hierarchy*:

```
file: auth.py
├── class: AuthHandler
│   ├── method: __init__
│   ├── method: authenticate
│   └── method: validate_token
├── function: hash_password
└── <module>: imports, constants, module docstring
```

Each node has:
- `node_type`: "function", "method", "class", "file", "section", "table", "note", "todo"
- `source_code`: the literal source text of that node
- `parent_id`: the parent node (class for methods, file for top-level functions)
- `caller_ids` / `callee_ids`: the call graph edges
- `name` / `full_name`: the identifier

This is already in remora's EventStore. Every `NodeDiscoveredEvent` carries all of this. The nodes table indexes it. The edges table stores the graph.

### The Insight: Different Node Facets Need Different Embeddings

A function like `authenticate(user: str, password: str) -> bool` has several *facets* that serve different search purposes:

1. **The code itself** — the implementation logic, control flow, data transformations
2. **The docstring** — natural language description of what it does, its parameters, return value
3. **The signature** — `def authenticate(user: str, password: str) -> bool` — the API contract
4. **The name** — `authenticate` — the identifier chosen by the developer
5. **Its graph context** — called by `LoginHandler.post()`, calls `hash_password()`, child of `AuthHandler`

When a developer asks "how do we authenticate users?", the *docstring* and *name* are the best match (natural language question -> natural language description). When a developer asks "find functions that take a user and password", the *signature* is the best match. When a developer looks at broken code and wonders "what else calls hash_password?", the *call graph* is the answer — but *embedding* the caller's code and searching for similar code catches callers that remora's static analysis might miss (dynamic dispatch, indirect calls through wrappers).

A single embedding of the entire function body conflates all these facets. It's a lossy compression of multiple distinct signals into one vector. What if we didn't compress?

### Multi-Facet Embedding: One Node, Many Vectors

For each discovered code node, the IndexingAgent can produce multiple embeddings stored in different collections (or with different metadata tags):

```
NodeDiscoveredEvent(node_id="abc123", node_type="method", name="authenticate", ...)
  │
  ├── emb_code collection:
  │   chunk: full source code of authenticate()
  │   metadata: {node_id: "abc123", node_type: "method", facet: "code"}
  │
  ├── emb_docstrings collection:
  │   chunk: "Authenticate a user against the database. Args: user (str): ..."
  │   metadata: {node_id: "abc123", node_type: "method", facet: "docstring"}
  │
  ├── emb_signatures collection:
  │   chunk: "def authenticate(user: str, password: str) -> bool"
  │   metadata: {node_id: "abc123", node_type: "method", facet: "signature"}
  │
  └── emb_names collection:
      chunk: "AuthHandler.authenticate"
      metadata: {node_id: "abc123", node_type: "method", facet: "name"}
```

Now when a search query arrives, the SearchAgent can *fan out* to multiple collections simultaneously and merge the results:

```python
async def multi_facet_search(query: str, node_types: list[str] | None = None):
    """Search across multiple facets, weighted by relevance."""

    # Natural language queries match docstrings best
    doc_results = await search_service.hybrid_search(
        query, collection="emb_docstrings", k=10
    )

    # Code-like queries match code best
    code_results = await search_service.vector_search(
        query, collection="emb_code", k=10
    )

    # Short identifier queries match names/signatures best
    if len(query.split()) <= 3:
        name_results = await search_service.fulltext_search(
            query, collection="emb_names", k=10
        )
        sig_results = await search_service.fulltext_search(
            query, collection="emb_signatures", k=10
        )
    else:
        name_results = sig_results = []

    # Merge via RRF, optionally filtering by node_type
    merged = rrf_merge(doc_results, code_results, name_results, sig_results)
    if node_types:
        merged = [r for r in merged if r.metadata.get("node_type") in node_types]
    return merged
```

### Per-Node-Type Search

This is where remora's node types become search dimensions. The user (or an agent) can constrain a search to specific node types:

| Query Intent | Node Types | Facets | Search Mode |
|---|---|---|---|
| "How do we authenticate users?" | any | docstrings, names | Hybrid |
| "Functions that hash passwords" | function, method | code, signatures | Hybrid |
| "Classes that handle HTTP requests" | class | docstrings, code | Vector |
| "What tests exist for auth?" | function (test_*) | names, code | Fulltext |
| "Documentation about deployment" | section, note | docstrings (=content) | Hybrid |
| "TOML config for database" | table | code (=toml content) | Fulltext |

The `SearchFilters` model in embeddy already has a `chunk_types` field — this maps directly to node types. The metadata on each chunk carries the `node_type` from the `NodeDiscoveredEvent`. No new infrastructure needed — just routing the right metadata through during indexing.

### Node-Type-Specialized Extractors

Different node types have different internal structure. A class has methods, a docstring, a base class list, and decorators. A function has a signature, a docstring, a body, and decorators. A markdown section has a heading and body text. Extracting the right facets requires node-type-aware parsing.

```python
def extract_facets(node: NodeDiscoveredEvent) -> dict[str, str]:
    """Extract embeddable facets from a discovered node."""
    facets = {"code": node.source_code}

    if node.node_type in ("function", "method"):
        parsed = ast.parse(node.source_code)
        func = parsed.body[0]  # FunctionDef or AsyncFunctionDef

        # Signature
        sig_lines = node.source_code.split("\n")
        sig = next((l for l in sig_lines if l.strip().startswith("def ")), "")
        facets["signature"] = sig.strip().rstrip(":")

        # Docstring
        docstring = ast.get_docstring(func)
        if docstring:
            facets["docstring"] = docstring

        # Name (qualified)
        facets["name"] = node.full_name  # e.g., "method:authenticate"

    elif node.node_type == "class":
        parsed = ast.parse(node.source_code)
        cls = parsed.body[0]  # ClassDef

        # Class signature (name + bases)
        bases = [node.source_code[b.col_offset:b.end_col_offset]
                 for b in getattr(cls, 'bases', [])]
        facets["signature"] = f"class {cls.name}({', '.join(bases)})" if bases else f"class {cls.name}"

        # Docstring
        docstring = ast.get_docstring(cls)
        if docstring:
            facets["docstring"] = docstring

        # Method listing (lightweight summary)
        methods = [n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if methods:
            facets["methods"] = ", ".join(methods)

        facets["name"] = node.full_name

    elif node.node_type == "section":
        # Markdown section: heading is the "name", body is the "docstring"
        lines = node.source_code.split("\n", 1)
        facets["name"] = lines[0].lstrip("#").strip()
        if len(lines) > 1:
            facets["docstring"] = lines[1].strip()

    elif node.node_type in ("note", "todo"):
        facets["docstring"] = node.source_code  # Full content is the description
        facets["name"] = node.name

    elif node.node_type == "table":
        facets["name"] = node.name  # TOML table name
        # TOML content is structured, embed as-is
        facets["code"] = node.source_code

    return facets
```

This extraction happens in the IndexingAgent when processing a `NodeDiscoveredEvent`. Each facet becomes a separate chunk in the appropriate collection. All chunks share the same `node_id` in their metadata, linking them back to the same graph node.

### Graph-Linked Search: Walking the Edges

Here's where it gets interesting. Remora's graph isn't just metadata — it's a navigation structure. The edges table stores `(from_id, to_id, edge_type)` triples. The nodes table stores `parent_id`, `caller_ids`, `callee_ids`. Combined with per-node embeddings, this enables *graph-aware search patterns*:

#### Pattern 1: "Search, then expand via graph"

1. Search for "authentication" in docstrings → find `authenticate()` method
2. Follow `parent_id` → find `AuthHandler` class
3. Follow `callee_ids` → find `hash_password()`, `db.query()`
4. Follow `caller_ids` → find `LoginHandler.post()`, `api_auth_middleware()`
5. Return the subgraph: the found node + its neighborhood

This gives a *contextual cluster* around the search hit — not just "here's a matching function" but "here's the function, its class, what it calls, and what calls it." The AnalysisAgent already does something like this (finding connections), but with graph edges it becomes structural instead of heuristic.

```python
async def graph_expanded_search(query: str, hops: int = 1) -> list[SearchResult]:
    """Search and expand results via graph edges."""

    # 1. Core search
    results = await search_service.hybrid_search(query, collection="emb_docstrings", k=5)

    # 2. Collect node_ids from results
    hit_node_ids = {r.metadata["node_id"] for r in results.results}

    # 3. Expand via graph
    expanded_ids = set()
    for node_id in hit_node_ids:
        node = await event_store.get_node(node_id)
        if node:
            if node.parent_id:
                expanded_ids.add(node.parent_id)
            expanded_ids.update(node.caller_ids)
            expanded_ids.update(node.callee_ids)

    # 4. Fetch expanded nodes' embeddings and rank by relevance to query
    neighbor_results = []
    for nid in expanded_ids - hit_node_ids:
        neighbor_chunks = await vector_store.get_chunks_by_metadata(
            collection="emb_code", metadata_match={"node_id": nid}
        )
        for chunk in neighbor_chunks:
            # Score these by similarity to the query
            sim = await embedder.similarity(query_embedding, chunk.embedding)
            neighbor_results.append((chunk, sim, "graph_neighbor"))

    # 5. Merge core results + graph neighbors, annotated with relationship type
    return merge_with_provenance(results, neighbor_results)
```

#### Pattern 2: "Find all implementations of this pattern"

A developer is looking at a `validate_token()` method and wants to find all other validation methods across the codebase. Traditional search: embed `validate_token`'s code, find similar code via KNN. This works but is noisy.

Graph-enhanced search:
1. Note that `validate_token` is a `method` with parent `AuthHandler` (a class)
2. Search the `emb_signatures` collection for methods matching `validate_*`
3. Also search `emb_code` for semantically similar method bodies
4. For each result, check if its parent class is semantically similar to `AuthHandler` (are they doing related things?)
5. Rank higher those results where both the method AND its parent class are relevant

This uses the graph to add *structural plausibility* to semantic search results. A method that lives inside a related class is more likely to be a meaningful match than one in an unrelated class.

#### Pattern 3: "Hierarchical search with scoping"

The user asks "find database code in the auth module." This is a *scoped* search:
1. First, find the scope: search `emb_names` for nodes in files matching `**/auth/**` or classes named `*Auth*`
2. Within those scope nodes, find their children (methods, nested functions) via `parent_id`
3. Search only those children's embeddings for "database" in the `emb_code` collection

This is graph-constrained search — the graph determines the search space, the embeddings determine the ranking within it.

### Collection Architecture for Multi-Facet + Node-Type

Two design options for organizing the collections:

#### Option A: Collections by Facet

```
emb_code        — all code bodies (functions, classes, modules)
emb_docstrings  — all docstrings/descriptions
emb_signatures  — all signatures
emb_names       — all qualified names
```

Filter by `node_type` using SearchFilters.chunk_types at query time.

**Pros:** Fewer collections. Simple to manage. Query-time filtering is flexible.
**Cons:** Large collections with mixed node types. Filtering adds overhead to every query.

#### Option B: Collections by Facet x Node-Type

```
emb_function_code, emb_function_docstrings, emb_function_signatures
emb_class_code,    emb_class_docstrings,    emb_class_signatures
emb_method_code,   emb_method_docstrings,   emb_method_signatures
emb_section_code,  emb_section_docstrings
emb_note_code,     emb_note_docstrings
...
```

**Pros:** Each collection is homogeneous. No filtering needed. sqlite-vec KNN over a smaller table is faster.
**Cons:** Many collections (potentially ~20+). More complex collection management. Harder to search "all code" without querying many collections.

#### Option C: Collections by Facet, Metadata for Node-Type (Recommended)

```
emb_code        — chunk_type stores node_type, metadata stores facet details
emb_docstrings  — same
emb_signatures  — same
emb_names       — same
```

Use embeddy's existing `SearchFilters.chunk_types` to filter by node type at query time. Use `SearchFilters.metadata_match` for finer constraints. This leverages what embeddy already supports.

**Pros:** Clean separation by embedding *purpose* (code vs. natural language vs. identifier). Node type filtering uses existing infrastructure. Best balance of simplicity and specificity.
**Cons:** Slightly slower than dedicated per-type collections for very large codebases. Acceptable tradeoff.

### The Graph Index: Edges in SQLite for Traversal

The graph relationships need to be queryable independently of the event log. Remora's `edges` table already stores `(from_id, to_id, edge_type)`. For graph-enhanced search, we also need efficient lookups like:

- "Give me all nodes that are children of node X" → `SELECT * FROM nodes WHERE parent_id = ?`
- "Give me all callers of node X" → edges table with `edge_type = 'calls'` and `to_id = ?`
- "Give me all nodes in file Y" → `SELECT * FROM nodes WHERE file_path = ?`

These are already indexed in remora's schema (`idx_nodes_parent_id`, `idx_nodes_file_path`, `idx_nodes_node_type`). The graph traversal is pure SQL against remora's EventStore. The semantic search is embeddy's VectorStore. The combination — SQL graph traversal to define scope, then embeddy search within that scope — is the power of having both systems connected through the agent layer.

### Multi-Agent Fan-Out: Parallel Facet Search

The cleanest way to implement multi-facet search is as multiple agents working in parallel:

```
User question: "How do we handle authentication?"
                        │
                  ContextAgent writes query to workspace
                        │
              ┌─────────┼──────────┐
              ▼         ▼          ▼
        DocSearch   CodeSearch  NameSearch
        Agent       Agent       Agent
              │         │          │
              ▼         ▼          ▼
        searches      searches   searches
        emb_docstrings emb_code  emb_names
              │         │          │
              └─────────┼──────────┘
                        ▼
                  FusionAgent
                  (merges results, applies graph expansion)
                        │
                        ▼
                  AnalysisAgent
                  (finds connections in merged results)
```

Each search agent is a registered AgentNode subscribed to a specific query path pattern. The ContextAgent writes the query once; the SubscriptionRegistry routes it to all search agents simultaneously. A FusionAgent (new) subscribes to all search result paths and merges them using RRF or learned weights.

Alternatively, a single SearchAgent could internally fan out across collections. The multi-agent approach is more aligned with remora's philosophy (agents don't know each other, communicate via workspace), but the single-agent approach is simpler and has less overhead. Worth considering both.

### Embedding Model Considerations

Different facets have different optimal embedding strategies:

- **Code embeddings** benefit from code-specialized models or code-aware instruction prefixes. Qwen3-VL-Embedding-2B handles code well, but the instruction prefix matters: "Represent this code for retrieval" vs. "Represent this text for retrieval."

- **Docstring embeddings** are natural language and work best with standard text embedding instructions. The same model works but with different instruction prefixes.

- **Signature embeddings** are short, structured, and keyword-heavy. BM25 (fulltext) might actually outperform vector search for signatures. Consider whether signatures need embedding at all, or just FTS.

- **Name embeddings** are very short (1-5 tokens). Vector search on single tokens is unreliable — cosine similarity between single-word embeddings is noisy. FTS5 is better here. Consider not embedding names at all, just indexing them in FTS.

Practical recommendation:
- `emb_code`: Vector + FTS (hybrid search)
- `emb_docstrings`: Vector + FTS (hybrid search)
- `emb_signatures`: FTS only (fulltext, no embedding — signatures are short and keyword-rich)
- `emb_names`: FTS only (fulltext, no embedding — names are identifiers, exact/stemmed match is better)

This halves the embedding cost (only code and docstrings need vector embedding) while maintaining search quality across all facets.

### How This Maps to Embeddy's Existing Capabilities

Let me be concrete about what embeddy already supports and what needs to change:

**Already supported:**
- Multiple collections (`emb_code`, `emb_docstrings`, etc.) — VectorStore.create_collection()
- Per-chunk metadata (`node_id`, `node_type`, `facet`, etc.) — Chunk.metadata dict
- chunk_type field on Chunk — maps to node_type
- SearchFilters.chunk_types — filter by node type
- SearchFilters.metadata_match — filter by arbitrary metadata
- Hybrid search (vector + BM25) per collection
- FTS-only search (fulltext mode)
- Content-hash dedup per chunk

**Needs addition:**
- Multi-collection search in a single call (Section 9.2) — needed for cross-facet queries
- Metadata-filtered KNN in sqlite-vec — currently embeddy does post-filtering, which is inefficient for large collections. Pre-filtering would require either partitioned virtual tables or a two-step approach (SQL filter -> KNN on subset).
- Instruction-prefix-per-collection — embeddy's Embedder uses a global instruction prefix. Different collections (code vs. docstrings) might want different prefixes. Add optional per-collection encode config.

**Needs addition in remora:**
- Facet extraction in IndexingAgent — parse node source code to extract docstrings, signatures, names
- Graph-expanded search — a new pattern in SearchAgent or a dedicated GraphSearchAgent
- Scope-constrained search — SQL query on nodes table to define search scope before calling embeddy

### Worked Example: "Find all functions that validate user input"

Let's trace this query through the full multi-facet, graph-aware search:

```
1. Query arrives: "find all functions that validate user input"

2. Query analysis (by ContextAgent or SearchAgent):
   - Node type hint: "functions" → filter node_type in ("function", "method")
   - Intent: natural language description → prioritize docstring search
   - Keywords: "validate", "user", "input" → also good for FTS

3. Fan-out searches (parallel):

   a. emb_docstrings (hybrid, node_type in [function, method]):
      → "Validate user credentials against the database"  (score: 0.91)
      → "Check if user input meets validation rules"      (score: 0.87)
      → "Sanitize and validate form input"                 (score: 0.82)

   b. emb_code (vector, node_type in [function, method]):
      → validate_credentials() body                        (score: 0.79)
      → check_input() body                                 (score: 0.76)
      → sanitize_form_data() body                          (score: 0.71)

   c. emb_names (FTS, node_type in [function, method]):
      → "validate_user_input"                              (score: BM25 12.3)
      → "validate_credentials"                             (score: BM25 8.7)
      → "validate_email"                                   (score: BM25 7.2)

   d. emb_signatures (FTS, node_type in [function, method]):
      → "def validate_user_input(data: dict) -> bool"     (score: BM25 10.1)
      → "def validate(user: User, input: str) -> Result"  (score: BM25 9.4)

4. RRF fusion across all four result sets:
   → validate_credentials() — appeared in docstrings (1st), code (1st), names (2nd)
   → validate_user_input() — appeared in names (1st), signatures (1st)
   → check_input() — appeared in docstrings (2nd), code (2nd)
   [... ranked list ...]

5. Graph expansion (1 hop):
   → validate_credentials() has parent_id → AuthHandler class
     → AuthHandler has other methods: authenticate(), refresh_token()
     → validate_credentials() calls: db.query(), hash_compare()
     → validate_credentials() called_by: LoginHandler.post()

6. Final result returned to workspace:
   /search/results/q_001/result_000 → validate_credentials()
     + graph context: parent=AuthHandler, callers=[LoginHandler.post], callees=[db.query]
   /search/results/q_001/result_001 → validate_user_input()
     + graph context: parent=FormValidator, callers=[APIHandler.create]
   [...]
```

The developer gets not just matching functions, but their *structural context* in the codebase. This is qualitatively different from flat search results.

### Open Questions

1. **Embedding cost.** Multi-facet means more embeddings per node. For a codebase with 1000 functions, that's potentially 3000-4000 embeddings (code + docstring per function, signatures and names go to FTS only). Is the embedding time acceptable? With Qwen3-VL-2B on GPU, ~100 embeddings/sec means ~30-40 seconds for initial indexing. Incremental updates are cheap (content-hash dedup skips unchanged nodes).

2. **Staleness.** When a function's code changes but its docstring doesn't, only the code facet needs re-embedding. The facet extraction needs to be diff-aware to avoid re-embedding unchanged facets. Content-hash dedup per facet handles this naturally — each facet chunk has its own hash.

3. **Method-level vs. class-level.** Should we embed methods independently, or as part of their parent class? Both have value. A method embedding is precise but loses class context. A class embedding captures the whole structure but is too broad for method-level queries. The answer: embed both. The `method` node gets its own embeddings; the `class` node gets its own embeddings. Graph links connect them. Search can find either and expand to the other.

4. **Cross-language graph.** Remora supports Python, JavaScript, TypeScript, Go, Rust, Markdown, TOML, YAML, JSON. The graph links are within-language (parent/caller/callee). But *embedding similarity* is cross-language — a Python auth function and a TypeScript auth function will have similar docstring embeddings. This enables cross-language discovery that the graph alone can't provide.

5. **Embedding instruction prefixes.** Should the IndexingAgent use different instruction prefixes for code vs. docstrings? Research suggests yes — code embedding quality improves with code-specific instructions. Embeddy's Embedder supports per-call instruction overrides via `encode(inputs, instruction="Represent this code: ")`. The IndexingAgent should use `"Represent this code for retrieval: "` for code facets and `"Represent this text for retrieval: "` for docstring facets.

### Impact on the Migration Path

Multi-facet, graph-aware search is a Phase 2 capability. It requires:
- Phase 2: Companion agents as AgentNodes (to access the graph via EventStore and coordinate with embeddy's VectorStore through the agent layer)

But the foundations can be laid in Phase 1:
- During Phase 1, the IndexingAgent can start extracting facets and storing them in separate collections
- SearchService.hybrid_search already works per-collection
- The graph expansion is a Phase 2 addition when the EventStore is accessible

So Phase 1 gets multi-facet search (better precision through collection specialization). Phase 2 adds graph awareness (structural context around search hits, graph-scoped queries via SQL on the EventStore combined with embeddy search).
