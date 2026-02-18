# Remora Full-Rewrite Integration Plan (Cairn + Grail + Pydantree)

## Objective

Rewrite Remora to be a thin, reliable orchestration layer that:

- **Uses Cairn as the only execution runtime** (sandbox, lifecycle, workspace isolation).
- **Uses Grail as the only `.pym` parser/validator/executor** (inputs + externals + runtime).
- **Uses Pydantree as the only discovery engine** (concrete syntax spans + typed captures).

All existing Remora runtime paths are considered legacy unless they align with these contracts.

## Core Decisions (and Why)

1. **Cairn integration is CLI-first (not in-process API)**
   - **Why:** Keeps Remora loosely coupled, aligns with shell-first contracts, and allows independent versioning.
   - **Implication:** Remora must parse structured CLI outputs and map them into `AgentResult` consistently.
   - **Trade-off:** Less streaming granularity and higher process overhead than an in-process API.

2. **Grail is the source of truth for tool schemas**
   - **Why:** `.pym` is the canonical tool contract. Grail emits inputs/externals metadata deterministically.
   - **Implication:** Tool parameter schemas are generated from `inputs.json` and validated against `externals.json`.

3. **YAML overrides remain first-class (explicit precedence)**
   - **Why:** Some tools need enriched descriptions, custom names, or compatibility shims.
   - **Implication:** Schema assembly rules must be explicit and audited (see “Schema Assembly Rules”).

4. **Pydantree replaces AST discovery entirely**
   - **Why:** Concrete syntax spans + deterministic captures are required for reliable edits and tool context.
   - **Implication:** Remora must own a Pydantree query pack and version it via manifests.

5. **Single event stream across discovery + validation + execution**
   - **Why:** Remora’s UI/logs need a single timeline with consistent phase semantics.
   - **Implication:** All stages emit JSONL events with `phase` and structured payloads.

## Target Architecture

### 1) Execution + Workspaces (Cairn + Grail)

- Remora never executes `.pym` itself; it **always submits to Cairn**.
- Cairn runs `grail.load(...).check()` before execution and stores artifacts under `.grail/agents/{agent_id}/`.
- Cairn `submit_result()` payload becomes the canonical `AgentResult`.

**Why this is chosen:** Cairn already owns sandbox boundaries, copy-on-write overlays, and human gating. Remora should not duplicate runtime logic.

### 2) Tool Registry (Grail-first + YAML overrides)

- Every `.pym` must declare `Input(...)`s and `@external`s.
- Remora builds a tool catalog by running `grail check --strict` and reading:
  - `inputs.json` → parameter schema
  - `externals.json` → external function validation
  - `check.json` → validation status + warnings

**Why this is chosen:** It removes schema drift and keeps tool contracts aligned with executable code.

### 3) Discovery + CST (Pydantree-only)

- Remora ships a Pydantree query pack (ex: `python/remora_core`).
- Discovery runs through Pydantree’s runtime CLI and returns typed capture models.
- Remora maps capture spans to `CSTNode` with exact source text and byte ranges.

**Why this is chosen:** Pydantree enforces deterministic query workflows and provides concrete syntax spans.

### 4) Unified Event Model

All stages emit JSONL events with a shared schema:

- `phase`: `discovery | grail_check | execution | submission`
- `agent_id`, `node_id`, `tool_name` (where applicable)
- `status`, `error`, `duration_ms`

**Why this is chosen:** The UI and CLI can present one consistent timeline.

## Schema Assembly Rules (Grail + YAML)

1. Start with Grail `inputs.json`.
2. Apply YAML overrides:
   - `tool_name`, `tool_description`
   - `inputs_override` (add/replace/remove input fields)
3. Emit warnings when overrides change:
   - `type`, `required`, or `default` compared to Grail.
4. Final schema is the one surfaced to the model.

**Why this is chosen:** Grail stays canonical, but overrides allow compatibility fixes and richer metadata.

## Canonical Data Layout

Uses Cairn’s filesystem contract:

```
.agentfs/
  stable.db
  agent-{id}.db
  bin.db

.grail/agents/{agent_id}/
  task.pym
  check.json
  inputs.json
  externals.json
  stubs.pyi
  monty_code.py

logs/workshop.jsonl
```

Remora does not create parallel artifact directories.

## Config Surface (Rewrite)

- `discovery.language` (ex: `python`)
- `discovery.query_pack` (ex: `remora_core`)
- `cairn.command` (default: `cairn`)
- `cairn.home` and `cairn.max_concurrent_agents`
- `event_stream.output`

Remove:
- AST-specific `queries` config
- ad-hoc runtime toggles not aligned with Cairn/Grail/Pydantree

## Implementation Phases

### Phase 0 — Delete Parallel Runtimes
- Remove AST discovery pipeline.
- Remove any `.pym` subprocess execution.
- Remove manual tool parameter schemas (schema assembly becomes Grail-first).

### Phase 1 — Grail Tool Registry
- Implement a Grail validator/catalog builder:
  - runs `grail check --strict`
  - caches `inputs.json`, `externals.json`, `check.json`
- Build tool schemas from Grail + YAML overrides.

### Phase 2 — Cairn Execution Bridge (CLI)
- Implement a Cairn client wrapper that:
  - spawns/queues `.pym` via CLI,
  - waits for submission results,
  - maps submission payloads into `AgentResult`.

### Phase 3 — Pydantree Discovery
- Create a Pydantree query pack for Remora core needs.
- Build `PydantreeDiscoverer` that emits `CSTNode` from typed captures.
- Remove AST-based `NodeDiscoverer` entirely.

### Phase 4 — Unified Event + Result Model
- Emit discovery, validation, execution, and submission events into one stream.
- Add Grail validation summaries to `AgentResult.details`.

## Testing Strategy

- **Discovery tests:** Pydantree captures return stable spans and text for functions/classes.
- **Grail registry tests:** invalid `.pym` fails with structured errors; schemas match `inputs.json`.
- **End-to-end test:** runner triggers Cairn execution; Grail artifacts appear; `AgentResult` matches submission.

## Risks & Mitigations

- **Risk:** YAML overrides drift from Grail semantics.
  - **Mitigation:** emit warnings for type/required/default changes.
- **Risk:** Pydantree query pack drift.
  - **Mitigation:** lock query pack with manifest hashes and validate in CI.
- **Risk:** CLI execution limits visibility into live run state.
  - **Mitigation:** parse Cairn status outputs and emit intermediate events.

## Success Criteria

- All `.pym` tools validate with `grail check --strict` before execution.
- Remora never executes `.pym` outside Cairn.
- Discovery is Pydantree-only (no AST fallback).
- Tool schemas are Grail-first with explicit YAML overrides.
- A single event stream covers discovery → validation → execution → submission.
