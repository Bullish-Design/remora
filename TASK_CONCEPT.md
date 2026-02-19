# Task Concept for Remora

This document describes a task system built on top of Remora that uses the Cairn KV store for persistence, the hub context layer for provenance, and an embeddings pipeline for semantic recall and deduplication. It focuses on automatic extraction from unstructured notes and a task DAG for decomposition and execution.

## Goals

- Persist tasks across sessions with reliable, local-first storage.
- Automatically extract tasks from unstructured notes or conversations.
- Support task decomposition into a DAG with dependencies and subtasks.
- Provide semantic search for similar completed or open tasks.
- Tie tasks to hub context so provenance and tool outputs are recoverable.

## Recommended Design Choices

- **Context strategy:** Hybrid context (task-level context + per-subtask deltas).
  - This keeps storage modest while preserving precise provenance when needed.
- **Embedding updates:** Update embeddings on edit with a debounce window.
  - This keeps retrieval accurate without heavy re-index churn.

## Architecture Overview

1. **Ingest note stream** (raw text, meeting notes, chat logs).
2. **Chunk & filter** via embeddings to find task-like spans.
3. **Task extraction** via functiongemma to identify concrete tasks.
4. **Task decomposition** via functiongemma into subtasks + dependencies.
5. **Persist DAG** in Cairn KV + attach hub context references.
6. **Embed tasks** for retrieval against similar tasks and open work.
7. **Execute or assist** via Remora tool calling.

## Architecture Integration

### Remora
- Hosts the orchestration loop, tool calling, and functiongemma prompts.
- Owns the task extraction/decomposition workflow and DAG validation.
- Emits task updates as events for status, outputs, and summaries.

### Cairn KV
- Stores task records, indices, and DAG relationships.
- Stores hub context pointers and task metadata.
- Acts as the source of truth for task state.

### Grail
- Holds embedding vectors for tasks, outputs, and notes.
- Supports similarity search for completed/open task recall.
- Provides vector IDs referenced from Cairn KV records.

### Tree-sitter
- Provides structured chunking for code or config notes.
- Enables better task extraction in code-heavy notes.
- Supplies symbol-level anchors for task context deltas.

### Data Flow Diagram (simplified)

```
[Notes/Chat]
     │
     ▼
[Chunk + Embed Filter] ──► [functiongemma Extract]
     │                          │
     │                          ▼
     │                    [Task Decompose]
     ▼                          │
[Hub Context] ◄─────────────────┘
     │
     ▼
[Cairn KV Task DAG] ──► [Grail Embeddings]
     │                          │
     └─────────────► [Similarity Retrieval]
                             │
                             ▼
                      [Remora Tooling]
```

## Task Extraction Pipeline (Plan C)

### 1) Chunking
Split a stream-of-consciousness note into sentence or paragraph chunks. Keep offsets for provenance.

### 2) Embedding Filter
Embed each chunk and compare to a small set of “task prototype” embeddings. Only pass likely task chunks to the model.

- **Prototypes** might include examples like:
  - “Fix the failing build on main.”
  - “Schedule a follow-up meeting.”
  - “Update the onboarding doc.”

### 3) Functiongemma Classification
For candidate chunks, the model returns:

- `is_task`: boolean
- `task_span`: offsets in the source note
- `task_title`: canonical short label
- `confidence`: score used for triage

### 4) Post-processing
- Merge adjacent task spans.
- Drop low-confidence tasks or ask user for confirmation.

## Task Decomposition & DAG Construction

### Decomposition Output
For each extracted task, functiongemma returns:

- `subtasks`: a list of smaller items
- `dependencies`: edges between subtasks
- `expected_outputs`: artifacts or checkpoints

### DAG Rules
- Tasks form a DAG (no cycles).
- Each node has optional parent, child, and dependency links.
- Nodes can be edited by users; the DAG is revalidated after edits.

### Editable DAG
Start with **Tier 1** editing:

- Edit title, notes, status, dependencies.
- Add/remove subtasks.
- Revalidate edges via functiongemma (optional).

Tier 2 (later): merge/split nodes with automatic re-embedding.

## Storage Model (Cairn KV)

Use namespaced keys with minimal duplication. The following is a concrete baseline.

### Schema Diagram (simplified)

```
 task:{id}
   ├─ title
   ├─ status
   ├─ notes
   ├─ parent_id
   ├─ dependency_ids[]
   ├─ created_at / updated_at
   ├─ context_ref ─────────────▶ hub_context:{id}
   └─ embedding_ref ───────────▶ grail_vector:{id}

 task:children:{id} ───────────▶ [child_ids]
```

### Core Records

- `task:{id}`
  - `title`, `status`, `priority`, `notes`, `created_at`, `updated_at`
  - `parent_id`, `dependency_ids[]`, `tag_ids[]`

- `task:children:{id}`
  - list of `child_ids[]`

- `task:context:{id}`
  - pointer to hub context (see below)

- `task:embedding:{id}`
  - embedding vector reference or embedding record id

### Optional Indices

- `task:status:{status}` → ids
- `task:tag:{tag}` → ids
- `task:updated` → list or sort key

## Hub Context Integration

Use the hub context layer to capture provenance for both parent tasks and subtasks.

### Recommended Hybrid Approach

- **Parent task** context captures the full note source and initial tool outputs.
- **Subtasks** store only deltas (new tool outputs, follow-up notes).

This allows:

- Fast rehydration at the task level.
- Precise tracing when drilling into subtasks.
- Reduced duplication across the DAG.

## Embeddings Strategy

### What to Embed
- Task title + notes + expected outputs (primary vector).
- Optional secondary vectors for outputs or tool artifacts.

### When to Update
- Recompute embeddings on edit with a debounce (for example, 2–5 seconds).
- Use a single “latest embedding” pointer per task.

### Retrieval Use Cases
- **Similar completed tasks** → show prior context and tool actions.
- **Similar open tasks** → suggest batching or dependency merges.
- **Task duplication detection** → propose dedup.

## Functiongemma Prompts

### Task Extraction Prompt (outline)
- Input: chunk text + example tasks.
- Output: task detection + a canonical task title + confidence.

### Task Decomposition Prompt (outline)
- Input: canonical task + note context.
- Output: subtasks + dependencies + expected outputs.

### DAG Validation Prompt (outline)
- Input: proposed DAG edges.
- Output: accept/reject cycles + suggested fixes.

## Task Lifecycle

1. Created from notes or user request.
2. Decomposed into subtasks and dependencies.
3. Executed by Remora or user with updates to status.
4. Completed tasks stored with final outputs and summaries.

## Recommended Defaults

- **Automatic extraction** enabled for new note inputs.
- **Confidence threshold** (example: 0.6) for auto-created tasks.
- **User review** for low-confidence tasks.
- **Debounced embedding updates** on edits.

## Future Extensions

- Task prioritization with learned ranking.
- Time estimates and scheduling.
- Multi-user task assignment.
- DAG visualization and manual rearrangement.

## Minimal Demo Scenario

1. User pastes a raw note dump.
2. System extracts 4 tasks automatically.
3. Each task becomes a DAG with subtasks.
4. Similar completed tasks are surfaced.
5. User chooses one task; Remora executes the next subtask.
