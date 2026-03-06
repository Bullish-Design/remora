# Persistent Node IDs for Remora: Proposal Comparison & Recommendation

## The Problem

Remora's node identity is unstable. Two independent paths produce IDs in incompatible ways, and both are fragile:

| Path | How ID is computed | Fragility |
|---|---|---|
| **Core** ([compute_node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81)) | `sha256(file_path:name:start_line:end_line)[:16]` | Any line shift → new ID |
| **LSP** (`ASTWatcher._convert_nodes`) | Reuse old ID if [(name, node_type)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/models.py#41-51) matches; else random `rm_xxxxxxxx` | Duplicate names collide; restart = all new IDs |

This causes:
- **Churn**: [NodeRemovedEvent](file:///home/andrew/Documents/Projects/remora/src/remora/core/events.py#197-202) + [NodeDiscoveredEvent](file:///home/andrew/Documents/Projects/remora/src/remora/core/events.py#160-176) pairs on every non-trivial edit
- **Restart amnesia**: LSP random IDs have no persistence; core positional IDs drift after offline edits
- **Source mutation side-effects**: [inject_ids()](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#143-161) writes `# rm_…` comments into [.py](file:///home/andrew/Documents/Projects/remora/src/remora/__init__.py) files on every save

---

## Proposal A: Inline Trailing Comments ([treesitter-inline-ids.md](file:///home/andrew/Documents/Projects/remora/.scratch/projects/treesitter-node-persistent-ids/treesitter-inline-ids.md))

**Core idea**: Embed a durable `graph:id=<uuid>` comment on each declaration's header line. Identity becomes an explicit source-level fact recovered via regex scan on Tree-sitter node start lines.

### Strengths
- Identity survives restarts, repo clones, branch switches — it's *in the source*
- No sidecar state to corrupt/lose/migrate
- Conceptually simple: parse → scan header line → have ID
- Well-thought-out incremental parsing strategy using `Tree.edit` + `changed_ranges`

### Weaknesses for Remora
- **Source pollution is the #1 concern**: Every tracked declaration gets a permanently appended comment. Remora already has [inject_ids()](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#143-161) and users find it intrusive — this doubles down on that approach rather than fixing it.
- **Formatter/linter interference**: Tools like `black`, `ruff`, `prettier` can reflow lines. The proposal acknowledges this but has no real mitigation beyond "auto-repair."
- **Markdown**: Using `<!-- graph:id=... -->` on headings is ugly and confusing for documentation authors.
- **Scope inflation**: The proposal builds an entire parallel indexing pipeline (SQLite entity/anchor/edge tables, worker sharding, batch DB writes) that duplicates what Remora's EventStore + NodeProjection already does.
- **Ignores existing architecture**: No mention of `EventStore`, [NodeProjection](file:///home/andrew/Documents/Projects/remora/src/remora/core/projections.py#82-237), [AgentNode](file:///home/andrew/Documents/Projects/remora/src/remora/core/agent_node.py#67-280), subscriptions, or the LSP event flow. The proposal designs a standalone code indexer, not an integration with Remora.
- **Chicken-and-egg**: Files without IDs need writeback, but writeback requires parse correctness, formatter cooperation, and team buy-in — all friction points.

---

## Proposal B: Identity Resolver + Sidecar Anchor Store ([identity-resolver-sidecar-concept.md](file:///home/andrew/Documents/Projects/remora/.scratch/projects/treesitter-node-persistent-ids/identity-resolver-sidecar-concept.md))

**Core idea**: A centralized `NodeIdentityResolver` backed by a SQLite sidecar store. Stable IDs are assigned once and maintained in the sidecar. Matching uses a priority cascade: inline ID → exact anchor → semantic match → body hash → signature hash → mint new.

### Strengths
- **No default source mutation** — the biggest win. Inline IDs are accepted as input but never auto-written.
- **Architecture-aware**: Explicitly references [compute_node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81), `ASTWatcher._convert_nodes`, [inject_ids](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#143-161), [_do_reparse](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py#78-118), and [did_save](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py#110-181). Proposes integration points in existing modules.
- **Delta-based events**: [NodeDiscoveredEvent](file:///home/andrew/Documents/Projects/remora/src/remora/core/events.py#160-176)/[NodeRemovedEvent](file:///home/andrew/Documents/Projects/remora/src/remora/core/events.py#197-202) emitted from stable-ID set differences, not positional hash diffs — directly addresses the churn problem.
- **Phased rollout**: Shadow mode → alias backfill → authoritative switch → disable inject_ids. This is operationally safe.
- **Migration story**: Alias table maps old `rm_*` IDs to stable IDs, preserving continuity.
- **Observability**: Metrics for match method, ambiguity rate, churn ratio.

### Weaknesses
- **Over-engineered for current scale**: 5 tables, 5 indexes, audit rows, confidence scores, retention policies — Remora currently tracks ~tens of nodes per file, not millions.
- **Heuristic matching complexity**: The 6-stage resolution cascade (inline → exact anchor → semantic → body hash → signature → new) is powerful but hard to debug and test. False rebinding on body hash match across files is a real risk.
- **Performance overhead**: Every parse now requires sidecar queries before identity assignment. For LSP [did_change](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py#91-108) at 500ms debounce, this adds latency.
- **Still proposes SQLite sidecar**: A separate DB introduces operational burden (backup, corruption risk, versioning) that may not be necessary.

---

## My Recommendation: Hybrid Approach — Semantic Identity in EventStore

After studying both proposals and Remora's actual architecture, I recommend a **simpler approach** that takes the best ideas from Proposal B but avoids the separate sidecar, avoids source mutation, and fits naturally into the existing EventStore + projection model.

### Core Principle

**Identity = [(file_path, kind, qualified_name)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/models.py#41-51)**, stored as an index in the existing [nodes](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#35-99) table. The [node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81) is a random UUID assigned once on first discovery and persisted via the EventStore projection — which is already a SQLite-backed read model. No new database. No source comments.

### Why This Works

1. **EventStore already persists nodes.** The [nodes](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#35-99) table (materialized by [NodeProjection](file:///home/andrew/Documents/Projects/remora/src/remora/core/projections.py#82-237)) already stores [node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81), [name](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#289-302), `node_type`, `file_path`, `start_line`, `end_line`, `source_code`, [source_hash](file:///home/andrew/Documents/Projects/remora/src/remora/core/reconciler.py#40-43). It survives restarts. We just need to use it properly for identity resolution instead of recomputing IDs from scratch.

2. **Qualified name is the natural stable key.** For Python: `module.ClassName.method_name`. For Markdown: `heading1.heading2`. `ASTWatcher._assign_parents` already computes `full_name` via line-range containment. This qualified name rarely changes except on actual renames.

3. **The reconciler already diffs.** [reconcile_on_startup](file:///home/andrew/Documents/Projects/remora/src/remora/core/reconciler.py#45-178) computes `new_ids - existing_ids` and `existing_ids - new_ids`. If we match by qualified name instead of positional hash, the diff becomes semantically meaningful.

### Concrete Changes

#### 1. Replace [compute_node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81) with semantic key lookup

```python
# Before (positional — breaks on any line shift):
def compute_node_id(file_path, name, start_line, end_line):
    return sha256(f"{file_path}:{name}:{start_line}:{end_line}")[:16]

# After (semantic — stable across line shifts):
def compute_semantic_key(file_path, kind, qualified_name):
    return f"{file_path}:{kind}:{qualified_name}"
```

The [node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81) is no longer derived from position. Instead, on first discovery, mint a UUID. On subsequent parses, look up the existing [node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81) for the semantic key from the [nodes](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#35-99) table.

#### 2. Unify core and LSP identity in one resolver function

```python
def resolve_node_ids(
    file_path: str,
    candidates: list[CSTNode],
    existing_nodes: list[AgentNode],
) -> list[tuple[CSTNode, str]]:
    """Match candidates to existing node_ids or mint new ones."""
    existing_by_key = {
        (n.node_type, n.full_name): n.node_id
        for n in existing_nodes
    }
    results = []
    for c in candidates:
        key = (c.node_type, c.full_name)
        node_id = existing_by_key.pop(key, None) or generate_id()
        results.append((c, node_id))
    return results
    # remaining keys in existing_by_key → orphaned → NodeRemovedEvent
```

This replaces:
- [compute_node_id()](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81) in core discovery
- `old_by_key` dict in `ASTWatcher._convert_nodes`

Both paths call the same function.

#### 3. Stop mutating source files

Remove [inject_ids()](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#143-161) from the [did_save](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py#110-181) handler. No more `# rm_xxxxxxxx` comments appended to source lines. Identity lives in the EventStore, not in source code.

#### 4. Add body-hash fallback for renames

For the rename case (qualified name changed but body is identical), add a single fallback:

```python
if not node_id:
    # Try body hash match (handles renames)
    body_hash = sha256(c.text)[:16]
    match = next(
        (n for n in remaining_existing if sha256(n.source_code)[:16] == body_hash),
        None,
    )
    if match:
        node_id = match.node_id
```

This handles the 80% rename case without the full 6-stage cascade from Proposal B.

#### 5. Add `semantic_key` column to nodes table

The `NodeProjection._project_node_discovered` method already does an UPSERT on [node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81). Add a `semantic_key` column:

```sql
ALTER TABLE nodes ADD COLUMN semantic_key TEXT;
CREATE INDEX idx_nodes_semantic_key ON nodes(semantic_key);
```

This lets the resolver query `SELECT node_id FROM nodes WHERE semantic_key = ? AND file_path = ?` to find existing IDs.

### What This Doesn't Do (Intentionally)

- **No sidecar database** — uses existing EventStore/nodes table
- **No inline source comments** — identity is ephemeral metadata, not source code
- **No anchor history** — we don't need to track where a node *was* in the past
- **No alias table** — old `rm_*` IDs are naturally replaced on first reparse; no backward compatibility needed since the system is pre-production
- **No multi-repo coordination** — out of scope
- **No incremental Tree-sitter parsing** — Remora currently does full-file parses via [parse_content()](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#421-499); incremental parsing is a separate optimization

### Migration Path

1. Add `semantic_key` column to nodes table (non-breaking schema change)
2. Create `resolve_node_ids()` function, used by both core and LSP paths
3. Replace [compute_node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81) calls with semantic key lookup + UUID mint
4. Replace `old_by_key` logic in `ASTWatcher._convert_nodes`
5. Remove [inject_ids()](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#143-161) call from [did_save](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py#110-181)
6. Remove [inject_ids()](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#143-161) function entirely
7. Run test suite — zero-churn on non-semantic edits should be verifiable

### Why Not the Other Proposals

| Criteria | Proposal A (Inline) | Proposal B (Sidecar) | Recommended (EventStore) |
|---|:---:|:---:|:---:|
| No source mutation | ❌ | ✅ | ✅ |
| No new database | ❌ | ❌ | ✅ |
| Uses existing architecture | ❌ | Partially | ✅ |
| Handles line shifts | ✅ | ✅ | ✅ |
| Handles renames | ✅ (if ID embedded) | ✅ (body hash) | ✅ (body hash fallback) |
| Survives restarts | ✅ | ✅ | ✅ |
| Implementation complexity | High (new pipeline) | High (resolver + sidecar) | Low (~200 LOC change) |
| Risk | Formatter conflicts | Over-engineering | Qualified name collisions (mitigated by file scoping) |

### Bottom Line

Both intern proposals solve the *technical problem* of stable identity, but neither is right for Remora *today*:

- **Proposal A** is a standalone code indexer design. It ignores Remora's EventStore architecture and doubles down on source mutation, which is already a pain point.
- **Proposal B** is architecturally sound and well-researched, but over-scoped. A 5-table sidecar with 6-stage resolution, alias migration, and observability metrics is enterprise-grade infrastructure for a system that currently tracks a few dozen nodes per file.

The recommended approach is ~200 lines of change across 4 files, uses infrastructure that already exists, and solves the core problem: **stable identity across edits, restarts, and non-semantic refactors — without touching user source code.**
