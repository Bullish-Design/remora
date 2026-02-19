# Node State Hub (Sidecar) Concept

## Executive Summary

**Problem**: FunctionGemma is a small, tool‑calling model. When it orchestrates multi‑step workflows end‑to‑end, it is prone to repetition loops, confusion, and inconsistent outcomes. At the same time, Remora still needs high‑quality, fast context for agents (tests, docstrings, linting) and for external consumers (IDE, Obsidian, CI).

**Solution**: Move to a **sidecar hub** that maintains a continuously updated, node‑level knowledge index. The hub does **not** drive workflows directly. Instead it builds and refreshes structured node state and markdown artifacts in the background. Existing subagents keep running as they do today, but can **optionally** read hub state as trusted context when it is fresh.

**Why this matters**: This approach separates **deterministic extraction** from **LLM reasoning**, reduces failure impact, and unlocks richer, reusable context for multiple consumers without blocking core workflows.

---

## Core Concept

### The Mental Model

Each tree‑sitter node (function, class, module) has three parallel representations:

1. **Source Node** — the canonical CST node from the codebase
2. **Node State** — structured metadata stored in a KV store
3. **Node Summary** — Obsidian‑compatible markdown generated from state

The **hub sidecar** watches for changes, derives diffs, and decides which **deterministic update scripts** should run. A small FunctionGemma model acts as a **triage layer** (not an orchestrator), deciding **what** to refresh based on diffs and policy constraints. A larger model is only used for expensive, human‑facing summaries when necessary.

### The Value Proposition

- **Reusable context** for any agent or tool that needs code understanding
- **Lower LLM cost** by running deterministic scripts first
- **Safer failures** because hub work is not on the critical path
- **Better quality** through consistent, structured node metadata

---

## Architectural Positioning (Sidecar)

The hub is **non‑blocking**. It runs in the background and never prevents existing Remora workflows from completing.

```
┌────────────────────────────────────────────────────────────┐
│ Remora Core Workflows (lint/test/docstring)                │
│ - Existing multi-turn FunctionGemma subagents              │
│ - Human review and workspace merge                          │
└────────────────────────────────────────────────────────────┘
                             │
                             │ (optional reads)
                             ▼
┌────────────────────────────────────────────────────────────┐
│ Node State Hub (Sidecar)                                   │
│ - Detects node changes                                     │
│ - Updates KV state + markdown index                        │
│ - Provides fresh context for consumers                     │
└────────────────────────────────────────────────────────────┘
```

**Implication**: If the hub is down or stale, Remora still works. The hub only improves context quality and consistency.

---

## Data Flow

```
1. File change detected
2. Node hash mismatch → build diff bundle
3. Deterministic rules propose candidate updates
4. FunctionGemma triage approves/adjusts updates
5. Update scripts refresh node state
6. Markdown regenerated (if configured)
7. State becomes available to agents & consumers
```

---

## Components

### 1. Change Detection

**Trigger**: Node content hash mismatch

```python
current_hash = hash(node.text)
stored_hash = kv.get(f"node:{node_id}:hash")

if current_hash != stored_hash:
    # Build diff bundle
    ...
```

### 2. Diff Scripts (Context Providers)

Diffs are deterministic and sandboxed. They supply the **signal layer**.

| Diff Script | Captures | Output |
|-------------|----------|--------|
| `diff_standard.pym` | Line‑level change info | Added/removed counts, diff snippets |
| `diff_structural.pym` | Signature/annotation changes | Flags + change lists |
| `diff_ast.pym` | Control flow and complexity | Complexity delta, new branches |
| `diff_embedding.pym` | Semantic drift | Similarity shift score |

### 3. Deterministic Rules Engine

Maps signals to candidate updates without LLM involvement.

```text
IF signature_changed → extract_signature
IF complexity_delta > 0 → compute_complexity
IF semantic_shift > 0.2 → search_similar
IF added_lines > 10 → generate_summary (candidate)
```

### 4. FunctionGemma Triage Layer

FunctionGemma does **not** execute tools or do multi‑turn planning. It only **confirms or rejects** which updates to run and can **escalate** ambiguous cases.

**Inputs**:
- Node state summary
- Diff bundle
- Candidate updates
- Policy constraints

**Outputs**:
- Approved updates
- Reasons for approvals/denials
- Escalation (optional)

### 5. Update Scripts

These are deterministic data refreshers with clear contracts:

- `extract_signature.pym`
- `compute_complexity.pym`
- `find_callers.pym`
- `find_callees.pym`
- `find_tests.pym`
- `search_similar.pym`

**LLM‑powered scripts** are limited to high‑value outputs such as summaries.

### 6. Node State (KV Store)

```python
# node:{node_id}:state
{
  "node_id": "func_process_data_abc123",
  "node_type": "function",
  "name": "process_data",
  "file_path": "src/processor.py",
  "content_hash": "sha256:abc123...",
  "source": "...full node text...",

  "signature": {...},
  "complexity": {...},
  "related": {...},
  "summary": "...",

  "last_updated": "2026-02-19T14:30:00Z",
  "last_signature_update": "2026-02-19T14:30:00Z",
  "last_complexity_update": "2026-02-19T14:30:00Z",
  "last_related_update": "2026-02-18T10:00:00Z",
  "last_summary_update": "2026-02-18T10:00:00Z"
}
```

### 7. Obsidian Markdown Output

Markdown is a **derived artifact** of the KV state and can be regenerated on demand.

**Path**: `.agentfs/nodes/{file_path}/{node_name}.md`

---

## Why the Sidecar Model is Valuable

### 1. Safety and Reliability
The hub cannot block or corrupt primary workflows. Agents still run even if the hub is stale or offline.

### 2. Better Context, Lower Cost
Deterministic scripts do the heavy lifting. The LLM only makes lightweight decisions or generates summaries when the signal merits it.

### 3. Consistency Across Agents
A single node state representation prevents each agent from re‑deriving context differently.

### 4. Incremental Adoption
The hub can be introduced gradually: first as a cache, then as optional context, and later as a trusted substrate for downstream tools.

---

## Remora Mapping (Sidecar)

**Existing components remain unchanged**:
- `remora.discovery` for CST nodes
- `remora.runner` for multi‑turn tool calling
- Existing subagents (lint/test/docstring)

**New sidecar components**:
- `hub` watcher and scheduler
- Diff scripts in `hub/diffs/*.pym`
- Update scripts in `hub/tools/*.pym`
- FunctionGemma triage model (LoRA adapter)
- KV + markdown outputs in `.agentfs/`

Agents can optionally add **context providers** that read the hub state and inject it into their prompt at decision time.

---

## Use Cases Beyond Remora

### 1. IDE/Editor Assistants
Provide node summaries, related tests, and call graphs without querying a large model.

### 2. Documentation Pipelines
Auto‑generate API references, release notes, or architecture overviews based on node state.

### 3. CI/CD Quality Gates
Track complexity drift, coverage expectations, or API changes at the node level.

### 4. Codebase Search and Navigation
Use embeddings + metadata for semantic code search or knowledge graph navigation.

### 5. Cross‑Repo Knowledge Indexing
Maintain a unified state index across multiple repos for dependency awareness.

---

## Configuration Sketch

```yaml
hub:
  enabled: true
  output_path: ".agentfs/nodes"

  embeddings:
    model: "sentence-transformers/all-MiniLM-L6-v2"
    index_path: ".agentfs/embeddings"

  markdown:
    on_state_change: true
    include_snippets: true
    snippet_max_lines: 10

  triage:
    model: "functiongemma-hub-triage"
    confidence_threshold: 0.7

  escalation:
    enabled: true
    target: "obsidian"  # or "api", "queue"
```

---

## Open Questions

1. **Freshness policy**: How do agents decide whether to trust hub state?
2. **Dependency invalidation**: How are caller/callee changes propagated?
3. **Embedding strategy**: When to rebuild index (watch mode, schedule, on‑demand)?
4. **State recovery**: How to detect corrupted/stale state and rebuild safely?
5. **Summary triggers**: What thresholds require a human‑readable summary?

---

## Demo‑Ready Use Cases

### 1. Pytest Failure Context Blob

**How it works**:
- Watch pytest output for failures and extract failing test node IDs.
- Hub gathers node state for the failing test, the target function under test, direct callees, fixtures, and related imports.
- FunctionGemma triage approves assembling a structured context bundle (signatures, summaries, recent diffs, and focused snippets).
- A downstream LLM formats the bundle into a human‑readable “Test Failure Overview.”

**Why it’s valuable**:
- Turns raw pytest output into actionable debugging context.
- Eliminates manual context hunting across files and fixtures.
- Creates a clean handoff to larger models or human reviewers.

### 2. Docstring Drift Detector

**How it works**:
- Structural/AST diffs detect signature or behavior changes.
- Hub compares current summary/state with existing docstrings.
- FunctionGemma triage decides whether to regenerate or flag the docstring.
- Optional LLM script proposes a new docstring based on updated state.

**Why it’s valuable**:
- Keeps documentation aligned with code behavior.
- Reduces stale docstrings without forcing full regeneration.
- Provides precise change rationale to reviewers.

### 3. API Change Impact Summary

**How it works**:
- Diff rules detect public API changes (exports, signature shifts).
- Hub finds callers, related tests, and docs from node state.
- FunctionGemma triage approves an impact bundle with affected call sites.
- Optional LLM script generates a breaking‑change summary.

**Why it’s valuable**:
- Makes API changes safer and more transparent.
- Helps teams assess blast radius quickly.
- Produces ready‑to‑share release notes context.

### 4. Complexity Regression Watch

**How it works**:
- AST diff computes complexity deltas and flags spikes.
- Hub gathers new branches/loops and nearby related functions.
- FunctionGemma triage decides whether to escalate or annotate.
- Optional LLM script proposes refactor targets or explanations.

**Why it’s valuable**:
- Catches maintainability regressions early.
- Encourages targeted refactors instead of blanket rewrites.
- Provides objective metrics with contextual guidance.

### 5. Cross‑Module Refactor Assistant

**How it works**:
- Structural diff + symbol search detects renames or moved definitions.
- Hub assembles references, import paths, and dependent tests/docs.
- FunctionGemma triage decides which updates to enqueue.
- Downstream scripts produce a refactor checklist or batch update plan.

**Why it’s valuable**:
- Reduces manual update errors during refactors.
- Speeds up large‑scale rename or extraction work.
- Provides a clear, auditable change plan for review.

### 6. Debugger Context Trace + Report

**How it works**:
- Debugger output is normalized into structured signals (frames, locals, exceptions).
- Deterministic scripts propose candidate actions and maintain a decision transcript.
- FunctionGemma chooses the next debugger action from a constrained list.
- The transcript is stored as per‑operation traces in the KV store with node/run indexes.
- A context bundle is assembled for a larger model or for a standardized report.

**Why it’s valuable**:
- Keeps FunctionGemma focused on tool decisions, not raw output parsing.
- Produces a complete, auditable trace for developer review.
- Enables high‑quality failure summaries with minimal extra work.

---

## Implementation Checklists (Demo Use Cases)

Each checklist captures the **signal → decision → update** path with brief component roles.

**Checklist Template**
- **Signals**: What triggers the hub work.
- **Diff/Rules**: Deterministic checks that propose candidate updates.
- **Triage**: FunctionGemma decision rules and escalation behavior.
- **Scripts**: Deterministic update scripts that refresh state.
- **Output**: Concrete artifacts produced for the demo.

### 1. Pytest Failure Context Blob
- **Signals**: Pytest failure line + failing test node ID.
- **Diff/Rules**: Resolve target function, fixtures, and direct callees from node state.
- **Triage**: Approve context bundle assembly when failure is reproducible.
- **Scripts**: `find_callers`, `find_callees`, `find_tests`, `extract_signature`, `search_similar`.
- **Output**: Structured “failure context blob” for LLM formatting.

### 2. Docstring Drift Detector
- **Signals**: Signature/AST diff + docstring mismatch flag.
- **Diff/Rules**: Compare current docstring vs. stored summary/signature.
- **Triage**: Approve regenerate vs. flag‑only based on change size.
- **Scripts**: `extract_signature`, `compute_complexity`, optional `generate_summary`.
- **Output**: Docstring drift report + candidate replacement.

### 3. API Change Impact Summary
- **Signals**: Public API change in exports or signature.
- **Diff/Rules**: Identify callers, related tests, and docs from node state.
- **Triage**: Approve impact bundle if change is breaking‑adjacent.
- **Scripts**: `find_callers`, `find_tests`, `list_exports`, `search_similar`.
- **Output**: Impact summary with affected call sites.

### 4. Complexity Regression Watch
- **Signals**: AST diff shows complexity delta above threshold.
- **Diff/Rules**: Capture new branches/loops and nearby functions.
- **Triage**: Approve escalation or annotate based on delta size.
- **Scripts**: `compute_complexity`, `find_callers`, `generate_summary` (optional).
- **Output**: Complexity spike report + refactor targets.

### 5. Cross‑Module Refactor Assistant
- **Signals**: Rename/move detected via structural diff + symbol search.
- **Diff/Rules**: Gather references, imports, and dependent tests/docs.
- **Triage**: Approve checklist generation and optional batch edits.
- **Scripts**: `find_callers`, `list_imports`, `find_tests`, `search_similar`.
- **Output**: Refactor checklist and file update plan.

### 6. Debugger Context Trace + Report
- **Signals**: Debugger stop event or failing test breakpoint.
- **Diff/Rules**: Normalize output into frames, locals, and exception signals.
- **Triage**: Choose next debugger action from ranked candidates.
- **Scripts**: `parse_debug_output`, `diagnose_exception`, `build_action_candidates`.
- **Output**: Decision transcript + context bundle for reporting.

---

## PKB Node Schema (Markdown)

This schema makes the background PKB routines concrete by standardizing article, note, and project nodes.

### Article Node
```yaml
node_type: article
id: article_graph_embeddings
source_url: https://example.com/graph-embeddings
summary: "Embedding graphs for semantic search."
key_points:
  - "Defines node embeddings for cross-document similarity."
  - "Compares cosine similarity vs. dot product."
tags: ["ml", "search"]
related_notes:
  - note_graph_embeddings_takeaways
related_articles:
  - article_vector_search_primer
```

### Note Node
```yaml
node_type: note
id: note_graph_embeddings_takeaways
linked_article: article_graph_embeddings
summary: "Key takeaways and implications for our PKB search."
quotes:
  - "Graph embeddings improve recall across sparse corpora."
projects:
  - project_semantic_search
```

### Project Node
```yaml
node_type: project
id: project_semantic_search
goal: "Ship semantic search across notes."
related_articles:
  - article_graph_embeddings
  - article_vector_search_primer
open_tasks:
  - "Prototype embedding index"
  - "Evaluate cosine threshold"
```

---

## Markdown PKB Background Brains (Automatic)

These are always‑on background routines that keep a personal knowledge base (PKB) continuously enriched.

### 1. Article Similarity Brain
**What it does**: Maintains an embedding‑based “related articles” list per note.

**Checklist**
- **Signals**: Article or reading note edits.
- **Diff/Rules**: Re‑embed changed note and compute nearest neighbors.
- **Triage**: Approve refresh when similarity set shifts beyond threshold.
- **Scripts**: `diff_embedding`, `search_similar`.
- **Output**: Updated “Related Articles” section.

### 2. Topic‑Activated Source Suggestions
**What it does**: When a project/topic note changes, it auto‑suggests relevant articles.

**Checklist**
- **Signals**: Topic note update or new tag addition.
- **Diff/Rules**: Search embeddings for top‑k related articles.
- **Triage**: Approve inclusion based on relevance score.
- **Scripts**: `diff_embedding`, `search_similar`.
- **Output**: Suggested sources with short summaries.

### 3. Note‑to‑Source Coverage Detector
**What it does**: Finds gaps between an article and the user’s notes about it.

**Checklist**
- **Signals**: Source article update or note edits.
- **Diff/Rules**: Compare key sections vs. extracted notes coverage.
- **Triage**: Approve “missing insights” list for review.
- **Scripts**: `diff_standard`, `generate_summary` (optional).
- **Output**: Missing‑insights checklist.

### 4. Cross‑Note Synthesis Brain
**What it does**: Detects clusters of notes and proposes synthesis summaries.

**Checklist**
- **Signals**: New notes with overlapping tags or embeddings.
- **Diff/Rules**: Cluster notes by semantic similarity.
- **Triage**: Approve synthesis when cluster crosses size threshold.
- **Scripts**: `search_similar`, `generate_summary`.
- **Output**: Synthesis snippet appended to a topic note.

### 5. Drift & Staleness Radar
**What it does**: Flags notes whose source articles or linked notes have changed.

**Checklist**
- **Signals**: Source article updates or dependency edits.
- **Diff/Rules**: Detect mismatched summaries or stale citations.
- **Triage**: Approve drift alert vs. silent refresh.
- **Scripts**: `diff_standard`, `extract_signature` (for structured headings).
- **Output**: Drift warnings and refresh suggestions.
