# Concept Overview: Stable Node Identity via Identity Resolver + Sidecar Anchor Store

Date: 2026-03-05
Status: Proposed
Owner: Remora Core/LSP

## Table of Contents

1. Executive Summary
   - One-page decision summary and recommendation.
2. Problem Statement
   - Why current identity behavior causes churn and state growth.
3. Goals and Non-Goals
   - Hard requirements, constraints, and explicit exclusions.
4. Current-State Analysis
   - Where identity is currently assigned and where instability enters.
5. Proposed Architecture
   - Components, responsibilities, and data flow across Core + LSP.
6. Identity Model
   - Definition of stable identity, anchors, and aliasing.
7. Sidecar Data Model (SQLite)
   - DDL, indexes, lifecycle rules, and transactional behavior.
8. Matching and Resolution Algorithm
   - Deterministic resolution order and tie-breaking rules.
9. Event Emission and Reconciliation Semantics
   - Delta-based behavior for NodeDiscovered/NodeRemoved.
10. Inline IDs Strategy (Optional, Not Default)
    - How inline IDs are consumed and when writeback is allowed.
11. Integration Plan (Core + LSP)
    - Concrete integration points in discovery, watcher, and handlers.
12. Migration Strategy
    - Backfill, compatibility, and rollback plan.
13. Testing Strategy
    - Unit, integration, property, and performance tests.
14. Observability and Operational Metrics
    - Instrumentation for churn, collisions, and event volume.
15. Risks and Mitigations
    - Key failure modes and practical guardrails.
16. Phased Rollout Plan
    - Sequenced implementation milestones with acceptance checks.
17. Open Questions
    - Decisions to finalize before implementation freeze.
18. Recommendation
    - Final implementation recommendation and why.

## 1. Executive Summary

This concept introduces a single identity authority (`NodeIdentityResolver`) backed by a dedicated SQLite sidecar store to stabilize node identity across edits, renames, and moves without requiring automatic source-file mutation.

Core idea:
- Stable identity is assigned and maintained in a sidecar identity store.
- Existing parser/extractor outputs (Tree-sitter nodes) are mapped to stable IDs through deterministic matching rules.
- Node lifecycle events are emitted from identity deltas, not from positional hashes.
- Inline IDs remain supported as an input signal, but are not mandatory and are not auto-written by default.

Why this is recommended now:
- It solves churn at the root (identity assignment), not just formatting symptoms.
- It minimizes user-facing source edits and avoids LSP save-time mutation side effects.
- It fits Remora’s existing EventStore + projection architecture with limited blast radius.


## 2. Problem Statement

Remora node identity currently changes too easily because identity depends on unstable attributes (path/line range and ad-hoc LSP remapping). This produces avoidable node churn, repeated node lifecycle events, and inflated downstream state.

Observed pressure points:
- Identity derived from source position changes under normal editing.
- LSP path uses heuristic ID reuse that is ambiguous for duplicate names.
- Save-time source mutation (`inject_ids`) can interfere with proposal ranges and developer workflow.
- Debounced reparsing may emit many events even for non-semantic edits.

When identity churn happens, the system pays multiple costs:
- Orphan/removal noise in EventStore.
- Lost continuity for agent-specific history and subscriptions.
- Increased cognitive load while debugging graph behavior.
- Higher risk of perceived “exponential growth” in tracked nodes/events.


## 3. Goals and Non-Goals

### Goals

1. Provide stable IDs for durable nodes (class/function/method/section/file-level where relevant) across:
- line shifts,
- non-semantic refactors,
- many rename/move scenarios.

2. Make identity assignment deterministic and centralized:
- one resolver used by both core discovery and LSP discovery paths.

3. Reduce event churn:
- emit `NodeDiscoveredEvent`/`NodeRemovedEvent` from semantic identity deltas, not parse-snapshot positional differences.

4. Preserve safety and developer ergonomics:
- no default automatic source mutation.
- inline ID support remains optional and explicit.

5. Maintain compatibility with existing `nodes` projection and event types.

### Non-Goals

1. Not attempting full compiler-grade global symbol resolution.
2. Not replacing EventStore or NodeProjection architecture.
3. Not requiring all repositories to adopt inline annotations.
4. Not solving all cross-language semantic equivalence cases in v1.
5. Not introducing distributed storage; scope is local SQLite sidecar.


## 4. Current-State Analysis

### 4.1 Core discovery identity

`compute_node_id()` in `src/remora/core/discovery.py` hashes:
- `file_path`,
- `name`,
- `start_line`,
- `end_line`.

This is documented and implemented around:
- `src/remora/core/discovery.py:50`
- `src/remora/core/discovery.py:77`

This means line movement or file relocation can generate a new ID even if semantic identity is unchanged.

### 4.2 LSP watcher identity

`ASTWatcher._convert_nodes()` currently reuses IDs by `(name, node_type)` from old nodes, otherwise generates a random `rm_xxxxxxxx` ID:
- `src/remora/lsp/watcher.py:43`
- `src/remora/lsp/watcher.py:70`

Issues:
- collisions when multiple nodes share same `(name, node_type)` in a file,
- weak stability under reordering and nesting changes.

### 4.3 Save-time mutation

`did_save` still calls `inject_ids()` for Python files:
- `src/remora/lsp/handlers/documents.py:170`

This mutates source text during save flows and can complicate proposal lifecycles and diffs.

### 4.4 Debounced reparse behavior

`_do_reparse()` in LSP appends node lifecycle events on each scheduled parse pass:
- `src/remora/lsp/server.py:78`

Without robust stable identity resolution, this can amplify churn under frequent edits.

### 4.5 Net assessment

Current behavior combines three identity patterns:
- positional deterministic IDs (core),
- heuristic reuse/random IDs (LSP),
- inline injected comments (`rm_...`) as side-effect persistence.

This split model is the primary structural cause of identity churn and inconsistent behavior between startup reconciliation and live editor flows.

## 5. Proposed Architecture

### 5.1 Components

1. `NodeIdentityResolver` (new)
- Single authority for assigning/resolving stable IDs.
- Accepts extracted node candidates and previous anchor context.
- Returns stable IDs plus resolution metadata (method used, confidence).

2. Sidecar Identity Store (new SQLite DB or new tables in existing DB namespace)
- Stores durable identity records and observed anchors.
- Supports aliasing during migration.

3. Discovery Integrations (core + LSP)
- Both `discover()/parse_content()` path and LSP watcher path call the same resolver.
- Removes duplicate identity logic.

4. Delta Emitter (new helper)
- Computes discovered/updated/removed sets using stable IDs.
- Emits lifecycle events only for real deltas.

5. Optional Annotator CLI (opt-in)
- Reads resolver decisions and proposes inline ID annotations.
- Never runs automatically on save by default.

### 5.2 Architectural Principle

Identity is stateful infrastructure, not a pure function of current parse coordinates.

Implication:
- Keep identity history/anchors in a sidecar store.
- Treat source text as a signal, not the exclusive authority (unless explicit inline ID exists).

### 5.3 High-Level Flow

1. Parse file via Tree-sitter and extract durable nodes.
2. Build candidate descriptors (`kind`, `name`, `qualified_name`, range, hashes).
3. Resolver maps each candidate to a stable ID.
4. Persist anchor updates in sidecar transaction.
5. Compare prior active set vs current active set for file.
6. Emit `NodeDiscoveredEvent`/`NodeRemovedEvent` based on stable ID delta.


## 6. Identity Model

### 6.1 Stable ID definition

Stable ID is an opaque identifier (UUIDv7 preferred, UUIDv4 acceptable) assigned once and reused across file moves and many rename operations.

Properties:
- globally unique per repository namespace,
- immutable once assigned,
- independent from transient location.

### 6.2 Anchor definition

An anchor is the latest known structural location/signature of a stable node.

Anchor fields should include:
- `file_path`,
- `start_byte`, `end_byte`,
- `kind`,
- `qualified_name`,
- `signature_hash`,
- `body_hash`,
- `last_seen_at`.

### 6.3 Alias definition

Alias maps legacy/transitional IDs to stable IDs.

Use cases:
- migration from existing `rm_*` IDs,
- compatibility when old IDs appear in cached events/tools,
- observability of ID unification effects.


## 7. Sidecar Data Model (SQLite)

### 7.1 DDL (conceptual)

```sql
CREATE TABLE node_identity (
  stable_id TEXT PRIMARY KEY,
  language TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at REAL NOT NULL,
  retired_at REAL
);

CREATE TABLE node_anchor (
  stable_id TEXT NOT NULL,
  file_path TEXT NOT NULL,
  start_byte INTEGER NOT NULL,
  end_byte INTEGER NOT NULL,
  qualified_name TEXT,
  signature_hash TEXT,
  body_hash TEXT,
  last_seen_at REAL NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (stable_id, file_path, start_byte, end_byte),
  FOREIGN KEY (stable_id) REFERENCES node_identity(stable_id)
);

CREATE TABLE node_alias (
  alias_id TEXT PRIMARY KEY,
  stable_id TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY (stable_id) REFERENCES node_identity(stable_id)
);

CREATE INDEX idx_anchor_file_active ON node_anchor(file_path, active);
CREATE INDEX idx_anchor_qname ON node_anchor(qualified_name);
CREATE INDEX idx_anchor_sig ON node_anchor(signature_hash);
CREATE INDEX idx_anchor_body ON node_anchor(body_hash);
CREATE INDEX idx_alias_stable ON node_alias(stable_id);
```

### 7.2 Storage invariants

1. `stable_id` never changes.
2. At most one active “best anchor” per stable node per file revision context.
3. Deactivation is logical (`active=0`) to preserve auditability.
4. Alias rows are append-only.

### 7.3 Transactional rules

Per indexed file change:
1. begin transaction,
2. resolve all candidates,
3. upsert identity/anchor rows,
4. deactivate stale anchors for that file,
5. write resolver audit rows (optional),
6. commit.


## 8. Matching and Resolution Algorithm

### 8.1 Deterministic resolution order

For each extracted candidate `c`, resolve in this strict order:

1. Inline explicit ID match (if allowed and valid).
2. Exact active anchor match (`file_path + kind + start/end byte` tolerance window for minor shifts).
3. Semantic anchor match (`file_path + kind + qualified_name`).
4. Rename/move heuristic match (`kind + unique body_hash` within repository).
5. Signature fallback (`kind + signature_hash` with tie-break on nearest prior anchor).
6. Mint new stable ID.

This order biases toward explicit signals, then locality, then semantics, then content-based recovery.

### 8.2 Tie-breaking

If multiple candidates match at one stage:
1. prefer same file path,
2. then smallest byte-distance from prior anchor,
3. then latest `last_seen_at`,
4. else mark ambiguous and mint new ID (with warning).

### 8.3 Pseudocode

```python

def resolve_candidate(c, store):
    if c.inline_id and store.is_valid_inline(c.inline_id):
        return Resolution(c.inline_id, method="inline")

    m = store.find_exact_anchor(c)
    if m:
        return Resolution(m.stable_id, method="exact_anchor")

    m = store.find_semantic(c.file_path, c.kind, c.qualified_name)
    if m:
        return Resolution(m.stable_id, method="semantic")

    ms = store.find_by_body_hash(c.kind, c.body_hash)
    if len(ms) == 1:
        return Resolution(ms[0].stable_id, method="body_hash")

    ms = store.find_by_signature(c.kind, c.signature_hash)
    if ms:
        return Resolution(tie_break(ms, c).stable_id, method="signature")

    sid = new_stable_id()
    store.create_identity(sid, c.language, c.kind)
    return Resolution(sid, method="new")
```

### 8.4 Safety policy

- Ambiguous matches never silently rebind.
- Ambiguity creates a new stable ID and records a resolver warning.
- Optional maintenance tool can later merge aliases if operator confirms.

## 9. Event Emission and Reconciliation Semantics

### 9.1 Delta model

For each file parse, compute:
- `previous_active_ids(file)` from sidecar,
- `current_resolved_ids(file)` from resolver pass.

Then:
- `added = current - previous` -> emit `NodeDiscoveredEvent`.
- `removed = previous - current` -> emit `NodeRemovedEvent`.
- `common` -> emit `NodeDiscoveredEvent` only if material fields changed (`source_hash`, range, parent, etc.).

### 9.2 Why this matters

This decouples event volume from parse frequency. Frequent reparses no longer imply large event bursts when identity is stable and content unchanged.

### 9.3 Startup reconcile behavior

Startup reconciliation should use resolver-backed IDs, not positional hash IDs, so offline edits and moved files preserve continuity whenever matching rules succeed.


## 10. Inline IDs Strategy (Optional, Not Default)

### 10.1 Policy

Inline IDs are accepted as a high-priority identity signal when present and valid.

However:
- auto-write on save is disabled by default,
- annotation is explicit via CLI (dry-run first),
- teams can opt-in repo-by-repo.

### 10.2 Benefits of optional mode

- avoids noisy code diffs by default,
- avoids proposal-range and formatter interaction risks,
- preserves portability option for teams that want source-embedded identity.

### 10.3 Suggested CLI

- `remora ids annotate --path <...> --dry-run`
- `remora ids annotate --path <...> --apply`
- `remora ids check --path <...>` (duplicates, malformed IDs, ambiguity report)


## 11. Integration Plan (Core + LSP)

### 11.1 Core discovery integration

Replace direct calls to positional `compute_node_id` with resolver output.

Primary touchpoints:
- `src/remora/core/discovery.py`
  - keep extraction logic,
  - remove ID assignment responsibility,
  - return candidate descriptors to resolver.

### 11.2 LSP watcher integration

Replace `(name, node_type)` reuse and random ID generation with resolver calls.

Primary touchpoint:
- `src/remora/lsp/watcher.py`
  - remove `old_by_key` identity logic,
  - call `NodeIdentityResolver.resolve_many(uri, candidates)`.

### 11.3 Save handler integration

Primary touchpoint:
- `src/remora/lsp/handlers/documents.py`

Changes:
- remove default `inject_ids()` call from `did_save`,
- keep explicit annotation command path.

### 11.4 Reparse integration

Primary touchpoint:
- `src/remora/lsp/server.py`

Changes:
- `_do_reparse()` uses resolver-based delta emitter,
- only emit lifecycle events for true additions/removals/updates.

### 11.5 Spawn child and scaffold tools

Primary touchpoint:
- `src/remora/core/tools/spawn_child.py`

Changes:
- stop deriving IDs from `file:name:lines`,
- request stable ID from resolver/store when node is scaffolded.


## 12. Migration Strategy

### 12.1 Phase 0: read-only shadow mode

- Keep existing IDs active in runtime.
- Run resolver in shadow mode and collect mapping stats:
  - legacy ID -> proposed stable ID,
  - churn reduction estimate,
  - ambiguity rate.

### 12.2 Phase 1: alias backfill

- Populate `node_alias` with old IDs (`rm_*` and positional hashes) mapped to stable IDs where high confidence.
- Preserve lookup compatibility for existing references.

### 12.3 Phase 2: authoritative switch

- `NodeDiscoveredEvent.node_id` becomes stable ID from resolver.
- Alias table used only for backwards resolution.

### 12.4 Rollback

- Feature flag: `identity.resolver.enabled`.
- If disabled, revert to legacy assignment without schema/data loss.
- Sidecar remains intact for later re-enable.


## 13. Testing Strategy

### 13.1 Unit tests

1. Resolver stage-order correctness.
2. Tie-break determinism.
3. Ambiguity handling (no silent rebinding).
4. Inline ID validation parsing.
5. Alias resolution behavior.

### 13.2 Integration tests

1. Rename function in same file preserves stable ID.
2. Move function across files preserves stable ID (when body hash unique).
3. Duplicate function names in distinct classes keep distinct stable IDs.
4. LSP `did_change` reparse without semantic change emits no lifecycle churn.
5. `did_save` no longer mutates file by default.

### 13.3 Property tests

1. Idempotence: indexing same snapshot twice yields identical IDs.
2. Stability under pure whitespace/comment edits.
3. Deterministic outcomes under randomized node ordering.

### 13.4 Performance tests

1. Resolver throughput per N candidates.
2. Sidecar query latency p50/p95/p99.
3. Event emission volume before vs after on same editing trace.

### 13.5 Acceptance targets

- >=90% reduction in node ID churn on typical edit traces.
- >=70% reduction in NodeRemovedEvent + NodeDiscoveredEvent pair churn on no-op reparses.
- 0 unintended source edits in default save path.

## 14. Observability and Operational Metrics

### 14.1 Required metrics

1. `identity_resolver.match_method.count{method}`
2. `identity_resolver.ambiguous.count`
3. `identity_resolver.new_id.count`
4. `identity_resolver.alias_hit.count`
5. `identity_resolver.resolve_ms`
6. `node_events.discovered.count`
7. `node_events.removed.count`
8. `node_events.updated.count`

### 14.2 Derived health indicators

1. Churn ratio:
- `(removed + discovered) / active_nodes` per file/session.

2. Stability ratio:
- `exact_anchor + semantic + inline` matches / total candidates.

3. Noise ratio:
- lifecycle events emitted during edits with unchanged semantic hashes.

### 14.3 Logging fields

For each resolved candidate:
- file path,
- node kind/name,
- chosen stable ID,
- method,
- confidence,
- competing matches (count),
- ambiguity flag.


## 15. Risks and Mitigations

### Risk 1: False-positive rebinding on content-hash match

Mitigation:
- require uniqueness for body-hash match,
- strict tie-break,
- ambiguous -> mint new ID + warning.

### Risk 2: Added complexity versus current simple hash

Mitigation:
- phased rollout with feature flags,
- keep resolver API small and deterministic,
- start with Python only.

### Risk 3: Performance overhead from sidecar lookups

Mitigation:
- indexed columns,
- batched `resolve_many`,
- prepared statements,
- benchmark gates before enabling by default.

### Risk 4: Migration confusion with old IDs

Mitigation:
- alias table,
- transitional compatibility resolver,
- CLI for alias inspection.

### Risk 5: Divergence between Core and LSP usage

Mitigation:
- enforce a single shared resolver module,
- remove duplicated identity logic from watcher.


## 16. Phased Rollout Plan

### Milestone A: Resolver library + sidecar schema

Deliverables:
- `NodeIdentityResolver` module,
- sidecar schema + store adapter,
- unit tests for algorithm semantics.

Exit criteria:
- deterministic test suite green,
- shadow-mode instrumentation available.

### Milestone B: Shadow-mode integration (no behavior change)

Deliverables:
- core + LSP run resolver in parallel,
- metrics/logging collected,
- no change to emitted node IDs yet.

Exit criteria:
- churn and ambiguity baseline report from real traces.

### Milestone C: Authoritative ID switch with alias support

Deliverables:
- resolver IDs power `NodeDiscoveredEvent.node_id`,
- alias compatibility lookup for existing references.

Exit criteria:
- regression suite green,
- measurable churn reduction targets achieved.

### Milestone D: Default disable save-time injection

Deliverables:
- remove automatic `inject_ids` from default `did_save` flow,
- add explicit annotate/check commands.

Exit criteria:
- proposal/edit workflows validated,
- no default file mutation side effects.

### Milestone E: Optional inline annotation UX

Deliverables:
- dry-run/apply annotation CLI,
- duplicate/malformed ID validator,
- repo policy docs.

Exit criteria:
- successful opt-in pilot in one repo segment.


## 17. Open Questions

1. Stable ID format choice: UUIDv7 vs UUIDv4.
2. Sidecar placement: separate DB file vs tables inside EventStore DB.
3. Matching policy strictness for low-confidence rename/move cases.
4. Whether file-level nodes should also use resolver IDs or remain deterministic path-based.
5. Retention policy for inactive anchors and alias rows.
6. Whether to expose resolver confidence/debug info in admin UI.


## 18. Recommendation

Implement the Identity Resolver + Sidecar Anchor Store as the canonical node identity mechanism, and treat inline IDs as optional input/portability metadata rather than default source mutation behavior.

Decision rationale:
- directly addresses root-cause identity instability,
- aligns with Remora’s EventStore projection model,
- reduces event churn and node lifecycle noise,
- avoids forcing codebase-wide comment annotations,
- preserves a path to inline IDs for teams that explicitly want source-embedded continuity.

This is the strongest balance of correctness, operational safety, and implementation practicality for the current Remora architecture.
