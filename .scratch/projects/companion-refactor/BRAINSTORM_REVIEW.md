# Brainstorm Review — clean-slate-brainstorm.md

> Review of the embeddy integration brainstorm, after studying both the
> remora codebase and the full embeddy source.

---

## 1. Executive Summary

**Overall verdict: The brainstorm is directionally correct but overreaches.**

**Adopt:**
- Embeddy replaces the companion indexing layer (embedder.py, store.py, chunker.py, indexer.py). This is the strongest proposal and is clearly correct.
- Async-native indexing. Companion's current indexing is synchronous; embeddy's Pipeline is fully async.
- Content-hash deduplication. Embeddy has this built in; companion doesn't.
- Hybrid search (vector + FTS5). Companion only does vector search; embeddy has hybrid with RRF/weighted fusion.
- Event-driven indexing. `FileSavedEvent` → IndexingAgent → Pipeline. Good pattern.

**Reject:**
- Agent consolidation (13→5 agents) in Phase 1. Too much behavioral risk with 177 tests. Do this as a separate follow-up.
- `SwarmExecutor.register_agent()` and rule-based execution paths. Too invasive to remora core. Not needed for Phase 1.
- Companion agents becoming registered AgentNodes. Contradicts D1 (thin bridge) and forces synthetic data into the nodes table.
- Two separate SQLite databases (EventStore + VectorStore). Unnecessarily complex. EventStore already exists; embeddy's VectorStore is a second database. That's fine — don't try to merge them.
- `WorkspaceWriteEvent` emission from workspace writes at the remora core level. This is a companion concern, not a core concern.

**Modify:**
- Search-as-workspace-reads pattern. The idea of writing queries/results to workspace paths is interesting but over-engineered for v1. Start with a simpler `IndexingService` that wraps embeddy's Pipeline + SearchService and is called directly by agents.
- `on_file_indexed` callback on Pipeline. The brainstorm requests this, but after reading embeddy's Pipeline code, a simpler approach is to just `await pipeline.ingest_file()` and emit the event yourself after it returns. No callback needed.
- Multi-collection search. The brainstorm proposes this for multi-facet embeddings (code, docstring, signature). This is Appendix A material — nice-to-have, not v1. Embeddy's SearchService already searches one collection at a time; searching multiple and merging results is trivial to build on top.

---


1. [Executive Summary](#1-executive-summary) — Overall verdict: what to adopt, what to reject, what to modify.
2. [Embeddy as Indexing Backend — Strong Yes](#2-embeddy-as-indexing-backend) — The case for replacing companion indexing with embeddy.
3. [What the Brainstorm Gets Right](#3-what-the-brainstorm-gets-right) — Correct observations and good ideas.
4. [What the Brainstorm Gets Wrong About Remora](#4-what-the-brainstorm-gets-wrong) — Misunderstandings of remora internals.
5. [Architecture Proposals — Accept/Reject/Modify](#5-architecture-proposals) — Section-by-section verdict on each proposal.
6. [Agent Consolidation — Too Aggressive](#6-agent-consolidation) — Why merging 13→5 agents is risky and unnecessary in Phase 1.
7. [Embeddy API Gaps](#7-embeddy-api-gaps) — What embeddy actually needs to change for clean integration.
8. [Revised Integration Strategy](#8-revised-integration-strategy) — Our recommended approach.
9. [Impact on Existing Decisions (D1-D6)](#9-impact-on-existing-decisions) — Which decisions need revision.

---

## 2. Embeddy as Indexing Backend

**Verdict: Strong yes. This is the clearest win in the brainstorm.**

### Current State (Companion Indexing)

The companion has a hand-rolled indexing stack in `remora_demo/companion/indexing/`:

| File | What it does | Lines |
|------|-------------|-------|
| `embedder.py` | `EmbedderBase` ABC + `SentenceTransformerEmbedder` (sync, sentence-transformers) | 128 |
| `store.py` | `VectorStore` wrapping sqlite-vec (sync, no FTS, L2 distance only) | 337 |
| `chunker.py` | Regex-based Python chunking, heading-based markdown chunking | 339 |
| `indexer.py` | `Indexer` orchestrating chunk→embed→store (sync) | 289 |

Problems:
1. **Sync-only.** `Indexer.index_file()` blocks the thread. `SentenceTransformerEmbedder.embed()` is synchronous.
2. **No FTS.** Only vector search. No hybrid mode.
3. **Regex-based Python chunking.** Uses `re.compile(r"^(class|def|async def)\s+(\w+)")` — misses decorated functions, nested classes, multiline signatures.
4. **No content-hash dedup.** Every `index_file()` call does `delete_by_file()` then re-indexes from scratch.
5. **No collections.** Single flat table — can't separate code vs docs vs web content.
6. **Minimal error handling.** No `IngestStats`, no structured error collection.

### Embeddy Equivalent

| Embeddy class | Replaces | Improvements |
|---------------|----------|-------------|
| `Embedder` + `RemoteBackend` | `SentenceTransformerEmbedder` | Async, LRU cache, local/remote modes, MRL dimension truncation |
| `VectorStore` | Companion `VectorStore` | Async (via `to_thread`), per-collection tables, FTS5, content-hash dedup |
| `PythonChunker` | `chunk_python_file()` | Proper `ast.parse()` instead of regex, extracts module/function/class chunks |
| `Pipeline` | `Indexer` | Async, content-hash dedup, `IngestStats`, `reindex_file()` |
| `SearchService` | `Indexer.search()` | Hybrid search (vector + BM25), RRF fusion, weighted fusion, min_score, find_similar |

The mapping is nearly 1:1. Embeddy is strictly better in every dimension:
- **Async-native** throughout (Pipeline, VectorStore, SearchService, Embedder all async)
- **AST-based chunking** (real `ast.parse()` vs regex)
- **Hybrid search** with RRF/weighted fusion
- **Content-hash dedup** built into Pipeline
- **Collections** for namespace isolation
- **Remote embedding** support (companion can offload to a GPU server)

### Integration Approach

The integration is straightforward — the companion creates an `IndexingService` that:
1. Holds an embeddy `Pipeline` and `SearchService`
2. Exposes `index_file(path)`, `search(query)`, `reindex_file(path)`
3. Is injected into agents that need indexing/search

This replaces the entire `remora_demo/companion/indexing/` directory. No remora core changes needed.

---

## 3. What the Brainstorm Gets Right

1. **"Companion indexing is solving a solved problem."** Correct. Embeddy's Pipeline + SearchService + VectorStore is the same thing but better.

2. **"The sync/async boundary is a real problem."** Correct. Companion's `Indexer` and `SentenceTransformerEmbedder` are synchronous. Running them in the event-driven companion runtime either blocks the loop or requires manual `to_thread()` wrapping. Embeddy is async-native.

3. **"Event-driven indexing is the right pattern."** Correct. `FileSavedEvent` → IndexingAgent → Pipeline → `IndexUpdatedEvent` is clean and fits remora's event-sourced philosophy.

4. **"Two separate databases is fine."** Correct. EventStore (remora core) stores events. VectorStore (embeddy) stores chunks and embeddings. They serve different purposes. Don't try to merge them.

5. **"Search should return structured results."** Correct. Embeddy's `SearchResults` model with typed `SearchResult` objects is better than the companion's raw list of tuples.

6. **"Content-hash dedup is essential for incremental indexing."** Correct. Currently the companion deletes all chunks for a file and re-indexes from scratch. Embeddy skips unchanged files.

7. **"Multi-facet embeddings (Appendix A) are a good future direction."** Correct as a direction, but it's Phase 2+ material. Embeddy's collection system already supports this — just create separate collections for code, docstring, signature facets.

---

## 4. What the Brainstorm Gets Wrong About Remora

1. **"Companion agents should become registered AgentNodes."** Wrong. AgentNode is for code-node agents — it has `source_code`, `start_line`, `file_path`, `caller_ids`. These fields are meaningless for service agents like CursorTracker. Stuffing companion agents into AgentNode creates synthetic data in the nodes table that violates AgentNode's invariant ("single Pydantic BaseModel, no subclasses, specialization via data"). Our D1 decision (thin bridge) is correct.

2. **"SwarmExecutor needs `register_agent()` for non-discovered agents."** Wrong for Phase 1. The companion doesn't need to register with SwarmExecutor. Companion agents participate in the *event system* (EventStore + SubscriptionPattern), not the *swarm execution system*. SwarmExecutor orchestrates code-analysis agents that are discovered from AST; companion agents are runtime services that react to editor events. Different concerns.

3. **"Rule-based agent execution path in SwarmExecutor."** Wrong abstraction. Companion agents don't need "rule-based execution" from SwarmExecutor. They need subscription-based event dispatch, which SubscriptionPattern + SubscriptionRegistry already provide. Adding rule-based execution to SwarmExecutor conflates two separate systems.

4. **"Cairn workspaces are ready for companion use."** Overstated. The brainstorm assumes Cairn is a fully-featured workspace system. Need to verify what Cairn actually provides — it may be early-stage. Our D3 decision (EventStore-backed workspace) doesn't depend on Cairn.

5. **"WorkspaceWriteEvent should be emitted from core workspace writes."** Wrong scope. This is a companion-level concern. Core remora shouldn't know about workspace write events. The companion's `EventStoreWorkspace` should emit its own events; core doesn't need to change.

6. **"Consolidate 13 agents into 5."** Not wrong per se, but wrong for Phase 1. This is a separate refactor with significant behavioral changes and 177 tests to migrate. Mixing it with embeddy integration makes both harder to land.

---

## 5. Architecture Proposals — Accept/Reject/Modify

### 5.1 Event-Driven Indexing (Accept)

The brainstorm proposes: `FileSavedEvent` → `IndexingAgent` → embeddy Pipeline → `IndexUpdatedEvent`.

**Accept.** This is the right pattern. The IndexingAgent subscribes to file-save events, calls `pipeline.reindex_file()`, and emits an `IndexUpdatedEvent` when done. Other agents (e.g., EmbeddingSearcher) can subscribe to `IndexUpdatedEvent` to know when new search results are available.

**Modification:** The brainstorm calls the agent "IndexingAgent" and proposes it as a new consolidated agent. We should just add indexing responsibility to the existing agent structure (or create a minimal IndexingAgent) without consolidating other agents into it.

### 5.2 Search as Workspace Reads (Reject for v1)

The brainstorm proposes: write a query to `/search/queries/q1`, SearchAgent writes results to `/search/results/q1`.

**Reject for v1.** This is architecturally interesting but over-engineered for the current use case. The EmbeddingSearcher agent can just call `search_service.search()` directly and write results to its workspace section. The indirection of writing a query to a workspace path, having a separate agent pick it up, and writing results to another path adds latency and complexity with no immediate benefit.

**Possible for Phase 2** if we want agents to be able to submit search queries asynchronously and have results arrive as events.

### 5.3 Two Separate SQLite Databases (Accept — It's Already The Case)

The brainstorm proposes: EventStore (events, nodes, graph) and VectorStore (chunks, vectors, FTS).

**Accept.** This is already the architecture. EventStore is remora core's SQLite database. VectorStore is embeddy's SQLite database. They don't need to share a database. The only connection is that events in EventStore can reference data in VectorStore (e.g., `IndexUpdatedEvent` with a `source_path` that has chunks in VectorStore).

### 5.4 New Event Types (Modify)

The brainstorm proposes: `IndexUpdatedEvent`, `SearchCompletedEvent`, `ContextExtractedEvent`, `AnalysisCompleteEvent`, `WorkspaceWriteEvent`.

**Modify.** Some of these are good:
- `CompanionIndexUpdatedEvent` — Yes, needed for event-driven indexing
- `CompanionWorkspaceWriteEvent` — Yes, this is our D3 design (workspace writes become events)

Some are unnecessary for v1:
- `SearchCompletedEvent` — Search is synchronous from the caller's perspective. The agent calls search, gets results, writes to workspace. No event needed.
- `ContextExtractedEvent` — Already handled by workspace writes
- `AnalysisCompleteEvent` — Already handled by workspace writes

### 5.5 Companion Agents as Registered AgentNodes (Reject)

See section 4 item 1. Our D1 (thin bridge) decision stands.

### 5.6 Appendix A: Multi-Facet Embeddings (Defer)

The brainstorm proposes: embed each code node multiple ways (code content, docstring, signature, name) into separate collections, then search across collections and merge.

**Defer.** This is a good idea for search quality but it's a Phase 2+ feature. For Phase 1, a single collection per content type (e.g., "python", "markdown") is sufficient. Embeddy's collection system and SearchService already support this — it's just a matter of creating multiple collections and merging results, which is a few lines of code on top of the existing API.

---

## 6. Agent Consolidation — Too Aggressive

The brainstorm proposes merging 13 companion agents into 5:

| Proposed Agent | Replaces |
|---------------|----------|
| IndexingAgent | New (handles file indexing) |
| ContextAgent | CursorTracker + ContextExtractor |
| SearchAgent | EmbeddingSearcher |
| AnalysisAgent | ConnectionFinder |
| ComposerAgent | SidebarComposer |

**This is too aggressive for Phase 1.** Reasons:

1. **177 tests.** Every test references specific agent classes, workspace paths, and event types. Consolidating agents means rewriting a large fraction of these tests.

2. **Behavioral risk.** CursorTracker and ContextExtractor have different activation patterns and workspace sections. Merging them changes when context extraction happens relative to cursor tracking.

3. **Orthogonal to embeddy integration.** Agent consolidation can happen after embeddy integration. The two changes are independent and should be landed separately.

4. **What gets lost:** The brainstorm drops NavigationTracker, SessionClock, EditTracker, ScopeAnalyzer, PatternDetector, SymbolTracer, FileRelationMapper, ActivityMonitor. Some of these may be vestigial, but that analysis should happen separately.

**Recommendation:** Keep all existing agents for Phase 1. Add a new `IndexingAgent` for embeddy integration. Consolidation (if desired) becomes a separate Phase 2 task.

---

## 7. Embeddy API Gaps

After reading embeddy's source code in full, here are the actual changes needed:

### 7.1 No Changes Needed (Brainstorm Was Wrong)

- **`on_file_indexed` callback on Pipeline.** Not needed. `pipeline.ingest_file()` and `pipeline.reindex_file()` both return `IngestStats`. The caller (IndexingAgent) can inspect the result and emit its own event. No callback is necessary.

### 7.2 Nice-to-Have (Not Blocking)

- **Multi-collection search in SearchService.** Currently `search()` takes a single `collection` string. For multi-facet search (Appendix A), we'd want `search(query, collections=["code", "docstrings"])` that searches both and merges. But this is trivial to build on top — call `search()` twice and merge results with RRF. Not a blocker; can be added to embeddy later if multi-facet becomes a real need.

### 7.3 Actual Integration Needs

1. **Embedder mode for companion.** The companion will use `mode="remote"` to offload embedding to a GPU server (the brainstorm correctly identifies this). Embeddy already supports this via `RemoteBackend`. No change needed.

2. **Dependency format.** Embeddy is at `/home/andrew/Documents/Projects/embeddy`. For the companion refactor, we need to add it as a dependency in `pyproject.toml`. Options:
   - Git dependency: `embeddy = {git = "...", branch = "main"}`
   - Path dependency: `embeddy = {path = "../embeddy"}`
   - Published package: `embeddy >= 0.3.12`

   **Recommendation:** Start with path dependency for local development, switch to git/published when ready.

3. **Embeddy's `LocalBackend._load_model_sync()` is `NotImplementedError`.** The local backend's actual model loading is not implemented yet — it raises `NotImplementedError`. This means **remote mode is the only working mode** for real embedding. For tests, we mock the Embedder. This is fine for our purposes.

---

## 8. Revised Integration Strategy

Based on this review, the integration strategy is:

### Phase 1A: Replace Indexing Layer with Embeddy (No Agent Changes)

1. Add embeddy as a dependency
2. Create `src/remora/companion/indexing_service.py` — wraps embeddy's `Pipeline` + `SearchService`
3. Replace references to old indexing classes (`Indexer`, `VectorStore`, `EmbedderBase`, `chunk_file`) with the new `IndexingService`
4. Create `CompanionIndexUpdatedEvent` (_FrozenEvent subclass)
5. Create a minimal `IndexingAgent` that subscribes to file-save events and calls `IndexingService.index_file()`
6. Update `EmbeddingSearcher` to use `IndexingService.search()` instead of the old `Indexer.search()`
7. Keep all other agents unchanged
8. Delete `remora_demo/companion/indexing/` once migration is verified

### Phase 1B: Event Model + Subscription Migration (Our Original Plan)

This is the original plan (Phases 1-4 from PLAN.md) — migrate events to `_FrozenEvent`, subscriptions to `SubscriptionPattern`, workspace to `EventStoreWorkspace`, runtime to registry-driven.

### Phase 1C: Package Relocation

Move `remora_demo/companion/` → `src/remora/companion/` (our original Phase 5).

### Phase 2 (Future, Separate Project)

- Agent consolidation (if desired)
- Multi-facet embeddings (Appendix A)
- Search-as-workspace-reads pattern
- Graph-linked search (search → expand via caller/callee edges)

---

## 9. Impact on Existing Decisions (D1-D6)

| Decision | Change? | Notes |
|----------|---------|-------|
| D1 (AgentNode — thin bridge) | **No change** | Brainstorm's proposal to register agents as AgentNodes is rejected. Thin bridge remains correct. |
| D2 (Events — _FrozenEvent) | **No change** | Add `CompanionIndexUpdatedEvent` to the event set. Same migration strategy. |
| D3 (Workspace — EventStore-backed) | **No change** | Brainstorm's Cairn workspace idea is speculative. Our EventStoreWorkspace design stands. |
| D4 (Subscriptions — SubscriptionPattern) | **No change** | IndexingAgent uses SubscriptionPattern like all other agents. |
| D5 (Package — src/remora/companion) | **No change** | Embeddy integration doesn't affect package location. |
| D6 (Runtime — registry-driven) | **No change** | IndexingAgent registers via the same registry mechanism. |
| **NEW: D7 (Indexing — embeddy)** | **New decision needed** | Embeddy replaces companion indexing. Details below. |

### New Decision: D7 — Indexing Backend

**Decision:** Replace `remora_demo/companion/indexing/` with an `IndexingService` that wraps embeddy's `Pipeline` + `SearchService`.

**Rationale:**
- Embeddy provides async Pipeline, hybrid search (vector + FTS5), AST-based chunking, content-hash dedup, collections — all missing from the companion's hand-rolled indexing.
- The mapping is nearly 1:1 and strictly better in every dimension.
- No remora core changes needed.
- Remote embedding support (offload to GPU server) comes for free.

**Dependency:** `embeddy` added to `pyproject.toml` as a path dependency initially, later as a git/published package.

**What changes:**
- New `IndexingService` class wrapping embeddy
- New `IndexingAgent` subscribing to file-save events
- `EmbeddingSearcher` updated to use `IndexingService.search()`
- Old `remora_demo/companion/indexing/` deleted

**What doesn't change:**
- No remora core changes
- No agent consolidation
- No SwarmExecutor changes
- All existing agents preserved

---

*End of review.*
