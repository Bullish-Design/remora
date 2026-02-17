# Swarm Agents Research: Context-Gathering Swarms Built on Remora Primitives

## Executive Summary

Remora's architecture — declarative YAML-defined agents, sandboxed Cairn workspaces, multi-turn tool-calling loops on tiny local models, and async concurrent orchestration — provides a foundation that can be extended into a **self-spawning swarm** of context-gathering agents. The idea: instead of one agent answering a question, a coordinator dispatches dozens of specialized retrievers that fan out across local knowledge sources (offline Wikipedia dumps, vendored codebases, embedding indexes), gather the most relevant fragments, and synthesize them into a dense context package. That package is then fed to a smaller/cheaper model that produces a final answer at quality levels normally requiring a much larger model.

This document analyzes the feasibility, architecture, and performance implications of this approach using remora's existing primitives.

---

## 1. From Code Analysis to Context-Gathering Swarms

### What Remora Already Does

Remora's current design processes **CSTNodes** (functions, classes, files) through **domain-specialized FunctionGemma subagents** running in parallel. Each agent:

- Receives a node + system prompt as initial context
- Has 4-8 coarse-grained tools (backed by sandboxed `.pym` scripts)
- Runs a multi-turn tool-calling loop until it calls `submit_result`
- Operates in its own copy-on-write Cairn workspace
- Returns a structured result conforming to a standard contract

The coordinator spawns agents concurrently (bounded by `max_concurrent_runners`) and aggregates results.

### The Conceptual Leap: Nodes → Queries, Code Analysis → Information Retrieval

The architecture generalizes naturally. Replace:

| Remora Concept | Swarm Equivalent |
|---|---|
| CSTNode (code to analyze) | **Query facet** (an aspect of the user's request to research) |
| Subagent (lint, test, docstring) | **Retriever agent** (wikipedia_searcher, codebase_searcher, embedding_searcher) |
| Tool (.pym script) | **Retrieval tool** (search_index, read_article, embed_query, rank_passages) |
| Workspace (copy-on-write) | **Result workspace** (gathered passages, ranked snippets, metadata) |
| submit_result | **submit_findings** (ranked, deduplicated context fragments) |

The multi-turn loop is the key enabler. A static retrieval pipeline runs one query and returns results. A swarm agent can:

1. Run an initial search
2. Inspect the results
3. Decide they're too broad — refine the query
4. Find a promising article — follow a cross-reference
5. Discover a related concept — spawn a sub-query
6. Judge that it has enough high-quality passages — submit findings

This iterative refinement is exactly what FunctionGemma's multi-turn loop provides.

---

## 2. Architecture of a Self-Generating Swarm

### Phase 1: Query Decomposition (the "self-generating" part)

The swarm starts with a single user request. A **decomposer agent** breaks it into facets:

```
User request: "How does Python's GIL interact with asyncio when using
               thread pool executors for CPU-bound tasks?"

Decomposer output:
  facet_1: "Python GIL mechanism and thread scheduling"
  facet_2: "asyncio event loop and thread pool executor integration"
  facet_3: "CPU-bound vs IO-bound task behavior under GIL"
  facet_4: "ThreadPoolExecutor implementation details in concurrent.futures"
```

Each facet becomes the equivalent of a CSTNode — the unit of work for a retriever agent.

The "self-generating" property comes from **recursive decomposition**: a retriever agent, while searching, may discover that its facet is too broad or touches an unexpected subtopic. It can call a `spawn_subfacet` tool that registers a new facet with the coordinator, which spawns another retriever. This is the swarm growing itself.

### Phase 2: Parallel Retrieval

For each facet, the coordinator spawns retriever agents across all configured knowledge sources:

```
facet_1 × [wikipedia_agent, codebase_agent, embedding_agent]
facet_2 × [wikipedia_agent, codebase_agent, embedding_agent]
facet_3 × [wikipedia_agent, codebase_agent, embedding_agent]
facet_4 × [wikipedia_agent, codebase_agent, embedding_agent]
```

That's 12 agents running concurrently (or more, if subfacets are spawned). Each one:

1. Receives the facet query as initial context
2. Uses domain-specific tools to search its knowledge source
3. Iterates: refine queries, follow cross-references, rank passages
4. Submits its top-K findings with relevance scores

### Phase 3: Synthesis

A **synthesis agent** receives all findings, deduplicates, ranks by relevance, and compresses them into a context package that fits within a target token budget. This package becomes the prompt context for the final model call.

### Proposed Subagent Definitions

#### Decomposer Agent
```yaml
name: decomposer_agent
model: agents/decomposer/models/decomposer_functiongemma_q8.gguf

initial_context:
  system_prompt: |
    You decompose user requests into independent research facets.
    Each facet should be a self-contained query that can be researched independently.
  node_context: |
    User request: {{ request_text }}

tools:
  - name: analyze_request
    pym: agents/decomposer/tools/analyze_request.pym
    description: Parse the request to identify key concepts and relationships.

  - name: check_knowledge_sources
    pym: agents/decomposer/tools/check_sources.pym
    description: Check which knowledge sources are available and their coverage.

  - name: submit_facets
    pym: agents/decomposer/tools/submit_facets.pym
    description: Submit the decomposed facets for parallel retrieval.
    parameters:
      type: object
      properties:
        facets:
          type: array
          items:
            type: object
            properties:
              query: { type: string }
              priority: { type: integer }
              target_sources: { type: array, items: { type: string } }
            required: [query, priority]
      required: [facets]
      additionalProperties: false
```

#### Wikipedia Retriever Agent
```yaml
name: wikipedia_retriever
model: agents/retriever/models/retriever_functiongemma_q8.gguf

initial_context:
  system_prompt: |
    You search an offline Wikipedia database to find passages relevant to
    a research query. Use iterative search refinement to find the most
    relevant content. Follow cross-references when they look promising.
  node_context: |
    Research query: {{ facet_query }}
    Priority: {{ facet_priority }}

tools:
  - name: search_index
    pym: agents/retriever/tools/search_wiki_index.pym
    description: Full-text search over the Wikipedia dump. Returns titles + snippets.
    parameters:
      type: object
      properties:
        query: { type: string }
        max_results: { type: integer }
      required: [query]
      additionalProperties: false

  - name: read_article
    pym: agents/retriever/tools/read_wiki_article.pym
    description: Read a specific Wikipedia article by title. Returns full text.
    parameters:
      type: object
      properties:
        title: { type: string }
        section: { type: string }
      required: [title]
      additionalProperties: false

  - name: find_related
    pym: agents/retriever/tools/find_related.pym
    description: Find articles linked from a given article.

  - name: spawn_subfacet
    pym: agents/retriever/tools/spawn_subfacet.pym
    description: >
      Register a new sub-query with the coordinator if you discover
      a related topic that deserves independent investigation.
    parameters:
      type: object
      properties:
        query: { type: string }
        reason: { type: string }
      required: [query, reason]
      additionalProperties: false

  - name: submit_findings
    pym: agents/retriever/tools/submit_findings.pym
    description: Submit ranked passages with relevance scores.
    parameters:
      type: object
      properties:
        passages:
          type: array
          items:
            type: object
            properties:
              text: { type: string }
              source: { type: string }
              relevance_score: { type: number }
            required: [text, source, relevance_score]
        summary: { type: string }
      required: [passages, summary]
      additionalProperties: false
```

#### Embedding/Semantic Search Agent
```yaml
name: embedding_retriever
model: agents/retriever/models/retriever_functiongemma_q8.gguf

initial_context:
  system_prompt: |
    You perform semantic similarity search over a local vector database.
    Use embedding-based retrieval to find passages semantically related
    to the query, even when exact keywords don't match.
  node_context: |
    Research query: {{ facet_query }}

tools:
  - name: embed_and_search
    pym: agents/retriever/tools/embed_search.pym
    description: >
      Embed the query and return top-K nearest passages from the vector store.
    parameters:
      type: object
      properties:
        query: { type: string }
        top_k: { type: integer }
        collection: { type: string }
      required: [query, top_k]
      additionalProperties: false

  - name: rerank_passages
    pym: agents/retriever/tools/rerank.pym
    description: >
      Re-rank a set of candidate passages using cross-encoder scoring
      against the original query.

  - name: submit_findings
    pym: agents/retriever/tools/submit_findings.pym
    description: Submit ranked passages with relevance scores.
```

#### Codebase Retriever Agent
```yaml
name: codebase_retriever
model: agents/retriever/models/retriever_functiongemma_q8.gguf

initial_context:
  system_prompt: |
    You search vendored dependency codebases to find relevant source code,
    documentation, and usage examples for a research query.
  node_context: |
    Research query: {{ facet_query }}

tools:
  - name: search_code
    pym: agents/retriever/tools/search_code.pym
    description: Grep/ripgrep over vendored codebases for patterns.

  - name: search_docs
    pym: agents/retriever/tools/search_docs.pym
    description: Search docstrings, README files, and inline documentation.

  - name: read_file
    pym: agents/retriever/tools/read_source.pym
    description: Read a specific source file from the vendored codebase.

  - name: find_references
    pym: agents/retriever/tools/find_references.pym
    description: Find all references to a symbol across the codebase.

  - name: submit_findings
    pym: agents/retriever/tools/submit_findings.pym
    description: Submit ranked code snippets and documentation passages.
```

### Coordinator Extension: Dynamic Agent Spawning

The key extension to remora's existing coordinator is **dynamic spawning**. Currently, the coordinator knows all agents upfront. For a swarm, it needs:

```python
class SwarmCoordinator:
    """Extended coordinator that supports dynamic agent spawning."""

    def __init__(self, config, cairn_client):
        self.pending_facets: asyncio.Queue[Facet] = asyncio.Queue()
        self.active_runners: dict[str, FunctionGemmaRunner] = {}
        self.results: list[FindingsResult] = []
        self.semaphore = asyncio.Semaphore(config.runner.max_concurrent_runners)
        self.max_total_agents = config.swarm.max_total_agents  # circuit breaker

    async def run_swarm(self, request: str) -> SynthesizedContext:
        # Phase 1: Decompose
        facets = await self._decompose(request)
        for f in facets:
            await self.pending_facets.put(f)

        # Phase 2: Process facets (including dynamically spawned ones)
        workers = [
            asyncio.create_task(self._facet_worker())
            for _ in range(config.runner.max_concurrent_runners)
        ]
        await self.pending_facets.join()
        for w in workers:
            w.cancel()

        # Phase 3: Synthesize
        return await self._synthesize(self.results)

    async def _facet_worker(self):
        while True:
            facet = await self.pending_facets.get()
            async with self.semaphore:
                for source in facet.target_sources:
                    runner = FunctionGemmaRunner(
                        definition=self._get_retriever_def(source),
                        node=facet.as_node(),  # facet adapts to CSTNode interface
                        workspace_id=f"{source}-{facet.id}",
                        cairn_client=self.cairn_client,
                        on_spawn_subfacet=self._handle_subfacet,  # callback
                    )
                    result = await runner.run()
                    self.results.append(result)
            self.pending_facets.task_done()

    async def _handle_subfacet(self, subfacet: Facet):
        """Called by spawn_subfacet tool. Adds new work to the queue."""
        if len(self.active_runners) < self.max_total_agents:
            await self.pending_facets.put(subfacet)
```

The `spawn_subfacet` tool is the mechanism for self-generation. When a retriever agent discovers a related topic worth investigating, it calls this tool, which pushes a new facet onto the queue. The coordinator spawns a new retriever for it — the swarm grows organically based on what the agents discover.

**Circuit breakers** are essential:
- `max_total_agents`: hard cap on total spawned agents (e.g., 50)
- `max_depth`: limit on recursive subfacet depth (e.g., 3 levels)
- `max_turns` per agent: existing remora config (e.g., 15)
- `timeout` per agent: existing remora config (e.g., 300s)

---

## 3. Using Gathered Context to Elevate a Lower-Quality Model

This is the core value proposition: **swarm-gathered context as a quality multiplier for cheaper models**.

### The Insight

Large language models are expensive because they need to store and retrieve knowledge from their parameters. A significant portion of a large model's capacity is dedicated to **memorized facts** — not to **reasoning ability**. If you externalize the knowledge retrieval (via the swarm), a smaller model only needs to be good at **reasoning over provided context**, which is a much simpler capability.

Research supports this. Retrieval-Augmented Generation (RAG) has shown that:
- A 7B model with good retrieval can match a 70B model without retrieval on knowledge-intensive tasks
- The quality of retrieved context matters more than the size of the model reading it
- Passage ranking and deduplication are critical — bad retrieval hurts more than no retrieval

### Architecture: Two-Phase Execution

```
Phase 1: Swarm Retrieval (cheap, parallel, local)
┌──────────────────────────────────────────────────────┐
│  N retriever agents (FunctionGemma 270M each)        │
│  Running on local CPU cores                          │
│  Searching: Wikipedia dump, vendored code, embeddings│
│  Cost: ~0 (local inference, no API calls)            │
│  Output: Ranked, deduplicated context package         │
└──────────────────────────────────────────────────────┘
                          ↓
Phase 2: Final Generation (one call to a smaller model)
┌──────────────────────────────────────────────────────┐
│  Smaller/cheaper model (e.g., 7B local or cheap API) │
│  Input: User request + swarm-gathered context         │
│  The model only needs to REASON, not RECALL           │
│  Output: High-quality answer                          │
└──────────────────────────────────────────────────────┘
```

### Context Package Format

The synthesis agent produces a structured context package:

```python
class ContextPackage(BaseModel):
    """Dense, ranked context ready for the final model."""

    request: str                              # Original user request
    facets: list[FacetSummary]                # What was researched
    passages: list[RankedPassage]             # Top-K passages, deduplicated
    total_passages_gathered: int              # How many the swarm found
    total_passages_after_dedup: int           # After dedup + ranking
    token_count: int                          # Fits within target budget
    source_breakdown: dict[str, int]          # Passages per source type

class RankedPassage(BaseModel):
    text: str                                 # The passage content
    source_type: str                          # "wikipedia", "codebase", "embedding"
    source_id: str                            # Article title, file path, etc.
    relevance_score: float                    # 0-1, from reranking
    facet_query: str                          # Which facet found this
```

### Why This Works: Decomposition of Intelligence

A large model like GPT-4 or Claude does three things simultaneously:
1. **Knowledge retrieval** — recalling facts from training data
2. **Reasoning** — logical inference, comparison, synthesis
3. **Generation** — producing coherent, well-structured text

The swarm externalizes #1 entirely. The final model only needs #2 and #3. This means:

- **A 7B model with perfect context** can match a 70B model on factual accuracy
- **A fine-tuned 3B model** specialized in reasoning-over-context could perform even better per dollar
- **Even FunctionGemma (270M)** could serve as the final model for simple factual queries where the answer is directly in the retrieved passages

### Quality Levers

The quality of the final output depends on:

1. **Retrieval recall**: Did the swarm find all relevant passages? (More agents + recursive subfacets help here)
2. **Retrieval precision**: Are the top-ranked passages actually relevant? (Reranking via cross-encoder scoring helps here)
3. **Context compression**: Does the context package fit the target model's context window? (Synthesis agent handles this)
4. **Reasoning capability**: Can the final model reason over the provided context? (This is the irreducible minimum — the model must be good enough at reading comprehension)

### Practical Implementation

```python
async def answer_with_swarm(request: str, config: SwarmConfig) -> str:
    # Phase 1: Gather context via swarm
    coordinator = SwarmCoordinator(config, cairn_client)
    context_package = await coordinator.run_swarm(request)

    # Phase 2: Generate answer with cheaper model
    prompt = f"""You are answering a technical question. Use ONLY the provided
context passages to inform your answer. If the context doesn't contain
enough information, say so.

## Question
{context_package.request}

## Context (ranked by relevance)
{format_passages(context_package.passages)}

## Your Answer
"""

    # Could be a local 7B model, a cheap API call, or even FunctionGemma
    response = await cheaper_model.generate(prompt)
    return response
```

---

## 4. Performance Impact of Running Multiple Agents Simultaneously

### Resource Model per Agent

Each FunctionGemma retriever agent consumes:

| Resource | Per Agent | Notes |
|---|---|---|
| **RAM (model)** | ~300MB | 288MB GGUF + inference buffers. But cached — shared across agents using the same model. |
| **RAM (context)** | ~2-8MB | Message history + workspace state |
| **CPU** | 2 threads | `n_threads=2` in llama.cpp config |
| **Disk I/O** | Minimal | Cairn workspace reads/writes (CoW, small) |
| **Network** | Zero | Fully local |

### The Critical Insight: Model Caching Eliminates the Main Bottleneck

Remora's `ModelCache` means that all retriever agents using the same GGUF model (e.g., `retriever_functiongemma_q8.gguf`) share a **single loaded instance** in memory. Loading 288MB from disk happens once. After that, additional agents using the same model only add context memory (~2-8MB each).

This means the RAM cost of running 20 retriever agents simultaneously is:

```
1 × 300MB (model, loaded once)
+ 20 × 5MB (context per agent)
= ~400MB total
```

Not `20 × 300MB = 6GB`.

### CPU Contention: The Real Bottleneck

The genuine performance concern is **CPU contention during inference**. `llama.cpp` uses CPU threads for matrix multiplication. With `n_threads=2` per agent and 20 agents, that's 40 threads competing for CPU time.

On a modern machine with 8-16 cores:

| Concurrent Agents | Behavior |
|---|---|
| 1-4 | Near-linear scaling. Each agent gets dedicated cores. |
| 4-8 | Slight contention. Per-agent throughput drops ~10-20%. Total throughput still increases. |
| 8-16 | Moderate contention. Per-agent throughput drops ~30-50%. Total throughput plateaus. |
| 16+ | Diminishing returns. Context switching overhead grows. Per-agent throughput drops significantly but total throughput may still be slightly higher than 16 agents. |

**However**: agents are not continuously doing inference. The multi-turn loop alternates between:
1. **Model inference** (~8 seconds, CPU-intensive)
2. **Tool execution** (~0.1-2 seconds, I/O-bound: reading indexes, searching files)
3. **Message processing** (milliseconds, negligible)

During tool execution, the CPU is mostly idle for that agent. With 20 agents in different phases of their loops, the actual concurrent inference load at any instant is typically **3-6 agents**, not 20. This natural interleaving means the effective throughput scales much better than the raw thread count would suggest.

### Latency vs. Throughput Tradeoff

```
Scenario A: Sequential (1 agent at a time)
  4 facets × 3 sources × 15 turns × 8s/turn = 24 minutes
  Peak CPU: 2 threads
  Total throughput: 1 agent worth

Scenario B: Moderate concurrency (max_concurrent_runners=8)
  All 12 agents start simultaneously
  Per-agent time: ~3 minutes (15 turns × 12s/turn due to contention)
  Wall clock: ~3 minutes
  Peak CPU: 8-16 threads
  Total throughput: ~8× improvement

Scenario C: High concurrency (max_concurrent_runners=20)
  All 12 agents + subfacet agents running
  Per-agent time: ~4 minutes (contention + context switching)
  Wall clock: ~4 minutes (slightly worse per-agent but handles more agents)
  Peak CPU: 16+ threads
  Total throughput: ~6× improvement (diminishing returns)
```

The sweet spot is typically **max_concurrent_runners = number of CPU cores / 2**. This leaves one thread per core for inference while keeping overhead low.

### Workspace I/O: Not a Bottleneck

Cairn's copy-on-write workspaces are lightweight. Each retriever agent writes small result files (passages, metadata). Even with 50 workspaces active simultaneously, the disk I/O is negligible compared to model inference time. SQLite-based fsdantic handles concurrent reads well, and each agent writes to its own workspace (no write contention).

### Memory Scaling With Multiple Model Types

If you use different specialized models for different retriever types (which is recommended for quality), the memory cost grows:

```
1 wikipedia retriever model:  300MB
1 codebase retriever model:   300MB
1 embedding retriever model:  300MB
1 decomposer model:           300MB
1 synthesis model:             300MB
                              ------
Total model memory:           1.5GB

+ 20 agents × 5MB context:    100MB
                              ------
Grand total:                  ~1.6GB
```

This is well within the range of any modern development machine.

### Summary: Would There Even Be a Performance Impact?

**For the swarm use case specifically, the answer is: the performance impact is surprisingly low.** The reasons:

1. **Model caching**: Agents sharing a model type share the loaded model in memory. The dominant memory cost (288MB per model) is paid once, not per-agent.

2. **Natural interleaving**: Multi-turn agents alternate between CPU-bound inference and I/O-bound tool execution. At any instant, only a fraction of agents are actually doing inference.

3. **Bounded concurrency**: The `max_concurrent_runners` semaphore prevents runaway resource consumption. The circuit breaker on total agents prevents the swarm from growing unboundedly.

4. **Tool execution is cheap**: Searching a local SQLite FTS index, reading files from a vendored codebase, or querying a local vector store takes milliseconds. The bottleneck is always model inference, not tool execution.

5. **270M models are tiny**: FunctionGemma at 270M parameters is orders of magnitude smaller than the models people typically think of when they imagine "running LLMs locally." Inference at 125 tokens/second on a single CPU core is fast enough that multi-turn loops complete in seconds per turn.

The main risk is **not performance but quality**: if the FunctionGemma models aren't fine-tuned well enough for the retrieval task, they may waste turns on poor queries, miss relevant passages, or fail to follow cross-references. The performance overhead of running 20 bad agents is low — but the wasted wall-clock time is real. Quality of the fine-tuned models is the gating factor, not compute resources.

---

## 5. Practical Considerations

### Knowledge Source Preparation

The swarm's value depends on having searchable local knowledge sources:

| Source | Preparation | Search Tool |
|---|---|---|
| **Offline Wikipedia** | Download [Kiwix ZIM file](https://wiki.kiwix.org/wiki/Content) or parsed dump; build FTS5 index in SQLite | `search_index.pym` queries SQLite FTS5 |
| **Vendored codebases** | Clone dependencies into a `vendor/` directory; optionally build ctags/LSP index | `search_code.pym` uses ripgrep; `find_references.pym` uses ctags |
| **Embedding index** | Pre-compute embeddings for all documents using a local embedding model (e.g., all-MiniLM-L6-v2 at 80MB); store in SQLite-vss or FAISS flat index | `embed_search.pym` loads embedding model, computes query vector, queries index |
| **Documentation corpus** | Collect man pages, API docs, language specs; chunk and index | `search_docs.pym` queries FTS5 over chunked docs |

### Embedding Model Choice

For the embedding/semantic search tools, a small local embedding model runs inside the `.pym` tool script:

- **all-MiniLM-L6-v2**: 80MB, 384-dim, fast CPU inference
- **bge-small-en-v1.5**: 130MB, 384-dim, slightly better quality
- **nomic-embed-text-v1**: 274MB, 768-dim, good quality/size tradeoff

These run in the `.pym` tool's Python environment, not in the FunctionGemma model. The embedding model is loaded once (cached) and used for all embedding queries across all agents.

### Reranking Strategy

Raw retrieval (BM25 or embedding similarity) returns approximate matches. The synthesis agent should rerank using a cross-encoder:

```python
# Inside agents/synthesis/tools/rerank.pym
from sentence_transformers import CrossEncoder
model = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')  # 80MB

scores = model.predict([(query, passage.text) for passage in candidates])
ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
```

This adds ~200ms for 100 candidate passages and dramatically improves precision.

### Context Budget Management

The synthesis agent must compress findings to fit the final model's context window:

```python
# Target: 4096 tokens for a small local model, or 8192 for a mid-range one
MAX_CONTEXT_TOKENS = 4096

def build_context_package(all_findings, tokenizer):
    # Deduplicate by content hash
    unique = deduplicate(all_findings)
    # Sort by relevance score (post-reranking)
    ranked = sorted(unique, key=lambda p: p.relevance_score, reverse=True)
    # Greedily fill context budget
    selected = []
    token_count = 0
    for passage in ranked:
        passage_tokens = len(tokenizer.encode(passage.text))
        if token_count + passage_tokens > MAX_CONTEXT_TOKENS:
            break
        selected.append(passage)
        token_count += passage_tokens
    return ContextPackage(passages=selected, token_count=token_count)
```

---

## 6. Expected Quality Improvement Curve

Based on RAG literature and the architecture described:

| Final Model Size | Without Swarm Context | With Swarm Context (estimated) |
|---|---|---|
| 270M (FunctionGemma) | Poor for open-domain Q&A | Usable for factual lookups where answer is in passages |
| 1-3B | Mediocre, frequent hallucination | Good for straightforward questions; struggles with multi-hop reasoning |
| 7B | Decent, some hallucination | Strong; approaches 70B-without-retrieval quality |
| 13-30B | Good | Excellent; marginal gains from retrieval diminish |

The **sweet spot** for this architecture is likely a **3-7B final model**: large enough to reason over context, small enough that the swarm's context-gathering provides meaningful uplift. Below 3B, the model may struggle to synthesize multiple passages. Above 30B, the model's internal knowledge makes retrieval less valuable.

---

## 7. Summary

### Feasibility

Remora's primitives — declarative YAML agents, async concurrent orchestration, sandboxed tool execution, multi-turn loops, structured result contracts — map directly onto the swarm retrieval use case with minimal architectural changes. The main extensions needed are:

1. **Dynamic spawning** via a `spawn_subfacet` tool and queue-based coordinator
2. **New retriever tool `.pym` scripts** for each knowledge source type
3. **A synthesis agent** that reranks, deduplicates, and compresses findings
4. **Fine-tuned FunctionGemma checkpoints** specialized for retrieval tasks

### Performance

Running 20+ agents simultaneously on a modern development machine is feasible. Model caching, natural CPU interleaving during tool execution, and the small size of FunctionGemma (270M) mean the resource overhead is modest: ~1.5GB RAM for models + ~100MB for agent contexts, with CPU contention as the practical ceiling.

### Quality Uplift

The swarm's context package can meaningfully elevate a smaller model's output quality by externalizing knowledge retrieval. A 7B model with swarm-gathered context can approach the factual accuracy of a much larger model operating from parametric memory alone. The limiting factor is not compute but the quality of retrieval — which is exactly what the multi-turn agent loop is designed to optimize through iterative refinement.
