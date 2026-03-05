# COMPANION_CONCEPT.md

> A unified vision for the Remora Companion, fusing the streamlined "Clean-Slate" architecture with native `embeddy` capabilities and persistent `Cairn` workspaces for long-term node autonomy and memory.

---

## 1. Core Architectural Paradigm: A Reactive DAG Pipeline

The companion is not a Swarm of code-agents; it is a **Reactive Data-Flow Pipeline** modeled as a Directed Acyclic Graph (DAG) of focused pipeline stages (nodes). 

Driven entirely by Remora's core primitives (`_FrozenEvent`, `EventStore`, `SubscriptionPattern`, and `SubscriptionRegistry`), the Companion translates real-time IDE occurrences (cursors, saves, content changes) into rich, layered, contextual understanding. 

Unlike older iterations that relied on volatile dictionaries (`InMemoryWorkspace`) or manual polling/routing, this unified architecture treats the stream of editor activity exactly like traditional system events. 

### The Dispatch Loop
1. The IDE/Editor produces standardized events: `CursorFocusEvent`, `FileSavedEvent`, etc.
2. `EventStore` durably writes the event and triggers subscribed companion nodes.
3. Nodes process the event rapidly, often referring to their persistent internal `Cairn` storage or making semantic queries to `embeddy`.
4. Nodes emit well-typed output events (`CompanionContextExtracted`, `CompanionSearchCompleted`) that inherently cascade down the DAG to the final consumers (like the `SidebarComposer`).
5. A fast, in-memory `CompanionState` projection continuously aggregates the "most recent" of each event type, serving as a rapid read-model so nodes don’t have to hammer the SQlite datastore.

---

## 2. Advanced Indexing & Semantic Superpowers: Embeddy

By adopting `embeddy` not just as a side library but as the fundamental, event-driven indexing substrate, the companion gains AST-aware, multimodal, hybrid-search capabilities.

- **Indexing as Node Capability**: An infrastructural `IndexingHandler` node subscribes exclusively to `FileSavedEvent`s. Upon triggering, it invokes embeddy's pipeline to content-hash, incrementally deduplicate, chunk (via `PythonChunker` or `MarkdownChunker`), and embed. It outputs a lightweight `CompanionIndexUpdated` summarizing the change so internal code-agents know an update occurred.
- **Search Democratized**: A dedicated `SearchHandler` node listens for `CompanionContextExtracted` signals and synthesizes a hybrid search query (vector + BM25 via sqlite-vec and FTS5). Search operates across segregated collections (`emb_code`, `emb_docstrings`, `emb_signatures`) to achieve semantic density and unparalleled search relevancy. 
- **Graph-Augmented Search**: `embeddy`'s results can be immediately enriched natively by the `EventStore`'s awareness of call graphs (`parent_id`, `caller_ids`, `callee_ids`).

---

## 3. Persistent, Autonomous Workspaces (Cairn)

While inter-node coordination and the data-flow pipeline run entirely on explicit, immutable `_FrozenEvent`s, **each companion node maintains its own durable `Cairn` workspace**.

In the original brainstorms, the workspace was either the sole form of communication or entirely deleted in favor of the EventStore. This unified concept combines the best of both:
1. **Eventual Communication**: All data *between* nodes travels via explicit event objects (`CompanionSearchCompleted`, `CompanionEditSummary`). This preserves a pristine audit trail, time-travel debugging, and rigorous DAG flow constraint.
2. **Persistent Private Storage (Cairn)**: Every node is granted an isolated, copy-on-write `Cairn Workspace` backed by persistent SQLite. This serves as the node's long-term memory buffer where it can:
   - **Organize Historical Insights**: The `TaskInferrer` can build persistent task boards mapping evolving user intentions across multiple weeks and sessions.
   - **Cache Expensive Analysis**: Deep AST traversals or intense verification data aggregated by the `ClaimChecker` can be securely committed to persistent layout rather than discarding it at the death of the runtime process.
   - **Organize Collections**: Nodes can build and manage folders of generated templates, frequently visited files, or debugging heuristics. 
   - **State Survival**: The node state (which is completely distinct from the pipeline's immediate event cascade) spans continuously across restarts or editor reloads.

---

## 4. The Companion Node Topology

Instead of 13 scattered rule sets, the architecture condenses to a streamlined roster of essential nodes. Source inputs map straight from core infrastructure (like the LSP server).

**Stage 1: The Extractors**
- **ContextExtractor**: Instantly identifies the AST context, parent class, or section the user's cursor is dwelling in. Emits `CompanionContextExtracted`. 
- **EditSummarizer**: Bundles `ContentChangedEvent`s to provide macro-summaries of what the developer is physically typing. Emits `CompanionEditSummary`.

**Stage 2: The Semantic Layer**
- **SearchHandler**: Ingests context and invokes deep multi-collection search against `embeddy`. Emits `CompanionSearchCompleted`.
- **IndexingHandler**: A background listener for file saves that drives the unified embeddy pipeline. Emits `CompanionIndexUpdated`.

**Stage 3: The Analyzers**
- **ConnectionFinder**: Assesses both deep structural graph calls and embeddy search results for similarities bridging disjointed files. Emits `CompanionConnectionsFound`.
- **TaskInferrer**: Translates code mutations and file jumps into inferred goals. Leverages its local `Cairn` workspace to organize a historical understanding of previous user objectives. Emits `CompanionTaskInferred`.
- **ClaimChecker**: Operates on docstrings/markdown, caching verified proofs continuously in its own `Cairn` workspace. Emits `CompanionClaimsChecked`.

**Stage 4: The Consumers (Sinks)**
- **SidebarComposer**: Polls the in-memory `CompanionState` projection + arriving synthesized events to construct beautifully compiled markdown. Emits `CompanionSidebarComposed` back to the editor. 

---

## 5. Summary of the Hybrid Architecture
By distilling the system into focused input/output nodes acting on explicit `_FrozenEvent` types, we solve the routing complexities, blockages, and non-durable logic traps that plagued the V1 system. Introducing `embeddy` natively into the `EventStore`'s domain establishes superior multi-facet hybrid searches out-of-the-box.

Finally, allocating dedicated `Cairn` workspaces back to these optimized handlers bridges the gap between reactive logic and autonomous, long-term state preservation. A pipeline node isn’t just a simple mapping function—it acts as an independent guardian of highly-organized long-term storage across user sessions.

---

## 6. The Swarm Synergy: Emergent Complexity in the Workspace

While the companion's core event routing uses a deterministic DAG pipeline for speed and reliability, the **Swarm of Code Agents** still plays a critical, emergent role within this architecture. The deterministic pipeline nodes and the free-form agent swarm are not mutually exclusive; they act in synergy.

### Swarm-Driven Workspace Management
Since each companion node (like `TaskInferrer` or `ClaimChecker`) has its own persistent `Cairn` workspace, these nodes do not have to rely solely on rigid heuristics. Instead, they can act as **Swarm Orchestrators**:
- **Delegated Analysis**: When the `ContextExtractor` identifies a complex or highly-connected code region, the pipeline can emit a specific event that dynamically summons a swarm of LLM-powered code-node agents. These native agents can converse, debate the code's purpose or potential bugs, and collectively write a highly accurate summary directly into the companion's `Cairn` workspace.
- **Emergent Task Inference**: The `TaskInferrer` doesn't just guess what you are doing based on simple keystrokes. It can dispatch a code-agent to read your recent edits and spawn sub-agents to verify if corresponding tests were updated or if documentation was modified. The swarm autonomously builds and organizes a "Task Board" in the `TaskInferrer`'s workspace through collaborative deduction.
- **Proactive Workspace Organization**: Just like development teams maintain documentation, background code-agents can continuously roam the companion's `Cairn` workspaces during idle time. They can organize scattered notes, consolidate redundant claim proofs, and organically restructure the node's long-term memory without user intervention.

### The Pipeline as the Senses, The Swarm as the Brain
In this unified model, the pipeline nodes act as the rapid, deterministic "nervous system" (processing cursor movements, indexing files, running hybrid searches). When deep reasoning is required, the pipeline drops an event into the `EventStore` that awakens the free-form Swarm. The Swarm then uses its emergent complexity to populate, curate, and deeply reason about the content inside the companion's persistent workspaces.
