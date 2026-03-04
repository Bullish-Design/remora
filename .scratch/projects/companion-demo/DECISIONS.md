# Companion Demo — Decisions Log

> Load ASSUMPTIONS.md before making decisions.

---

## Decision Format

```
### D-XXX: [Short Title]

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Superseded

**Context:**
What is the situation or problem?

**Options Considered:**
1. Option A — pros/cons
2. Option B — pros/cons

**Decision:**
What we decided and why.

**Consequences:**
What follows from this decision.
```

---

## Decisions

### D-001: Use ChromaDB for Vector Store

**Date:** 2026-03-03
**Status:** Proposed

**Context:**
Need a vector store for embedding search. Options range from simple (ChromaDB) to complex (FAISS, Pinecone).

**Options Considered:**
1. **ChromaDB** — Pure Python, embedded, easy setup. May not scale to huge codebases.
2. **sqlite-vec** — Single file, fast, SQLite extension. More manual embedding handling.
3. **FAISS** — Very fast, battle-tested. More complex setup.
4. **Pinecone/cloud** — Violates local-first assumption.

**Decision:**
Use ChromaDB for initial implementation. Easy to swap later if needed.

**Consequences:**
- Simple setup, just `pip install chromadb`
- May need to revisit for very large codebases (100k+ files)
- API is clean, migration to alternatives straightforward

---

### D-002: Use sentence-transformers for Embeddings

**Date:** 2026-03-03
**Status:** Proposed

**Context:**
Need an embedding model that runs locally, no API required.

**Options Considered:**
1. **sentence-transformers** — Pure Python, many models, well-documented.
2. **Ollama embeddings** — Uses existing Ollama setup if present.
3. **OpenAI API** — Best quality but violates local-first assumption.

**Decision:**
Use sentence-transformers with `all-MiniLM-L6-v2` model. Fast, 384 dimensions, good enough for semantic search.

**Consequences:**
- ~100MB model download on first run
- CPU inference is fast enough for our use case
- Can upgrade to larger model if quality insufficient

---

### D-003: Single Process, Async Agents

**Date:** 2026-03-03
**Status:** Proposed

**Context:**
How should agents run? Separate processes, threads, or async tasks?

**Options Considered:**
1. **Single process, asyncio** — Simple, shared memory, easy debugging.
2. **Multi-process** — True parallelism, isolation. Complex IPC.
3. **Threads** — GIL limits parallelism for CPU-bound work.

**Decision:**
Single process with asyncio. All agents are I/O-bound (embeddings, file reads, network), so async is sufficient.

**Consequences:**
- Simple architecture, easy to debug
- One slow agent could block others if not properly async
- May revisit if embedding search proves CPU-bound

---

### D-004: Workspace Paths vs Event Bus

**Date:** 2026-03-03
**Status:** Proposed

**Context:**
Should agents communicate via events or workspace path subscriptions?

**Options Considered:**
1. **Events only** — Clear pub/sub, but need event types for everything.
2. **Paths only** — Watch workspace paths, react to changes.
3. **Hybrid** — Events for external triggers, paths for agent-to-agent.

**Decision:**
Hybrid approach. Sensors emit events (CursorMoved, etc.). Downstream agents subscribe to workspace paths.

**Consequences:**
- Natural fit: sensors deal with external world (events), agents deal with data (paths)
- Path subscriptions enable glob patterns (`/search/*`)
- May need to verify Cairn supports efficient path watching
