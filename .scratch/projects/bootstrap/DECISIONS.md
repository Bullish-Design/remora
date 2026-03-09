# Bootstrap Implementation Decisions

## D1: Extend NodeStore — unified graph API, two tables
**Decision**: Extend the existing `NodeStore` class with `read_graph()` and
`write_graph()` methods. Add `graph_nodes` + `graph_edges` tables to event_store.db.
`NodeStore` routes queries to the appropriate table based on node kind:
- `kind in CODE_NODE_KINDS` → query v1 `nodes` table (live, from LSP scanner)
- everything else → query new `graph_nodes` table

No separate `BootstrapGraphStore` class. No parallel graph concept.

**Rationale**: Makes `event_store.nodes` the single, unified graph API. Bootstrap
agents can query live code topology (from `nodes` table via `caller_ids`/`callee_ids`)
and coordination topology (from `graph_nodes`/`graph_edges`) through the same tool
calls. No seeding needed for code topology — it's live.

**Key routing rule**:
```python
CODE_NODE_KINDS = frozenset({"function", "class", "method", "module", "file", "section"})
# reads: route to nodes table if kind in CODE_NODE_KINDS, else graph_nodes
# writes: always target graph_nodes (agents don't write code nodes directly)
```

**Tradeoff**: NodeStore grows slightly in scope. Mitigated by keeping existing
methods (`get_node`, `list_nodes`, etc.) completely unchanged — new methods are
additive only.

## D2: Bedrock functions are async closures, not module-level
**Decision**: Bedrock functions are built at runtime via a factory:
`build_bedrock(agent_id, cairn_service, graph_store, event_store, swarm_id)`
returns a dict of six async callables. The factory captures the per-agent
`CairnExternals` instance.

**Rationale**: `_cairn_read` / `_cairn_write` are per-agent (each agent has
its own workspace). Module-level functions would require thread-local storage
or injection per call. Closures are cleaner.

## D3: TurnSchema is a Pydantic model with strict validation
**Decision**: `TurnSchema` (schema_loader.py) is a Pydantic BaseModel. YAML
is loaded with PyYAML, then validated via `TurnSchema.model_validate(data)`.

**Rationale**: Gives agent schema evolution immediate validation feedback.
An agent that writes a malformed schema.yaml gets a clear error on the next
activation, not a runtime crash deep in LLM dispatch.

## D4: Context pipeline steps execute synchronously (one at a time)
**Decision**: Context pipeline steps run sequentially, not in parallel.

**Rationale**: Steps may depend on each other (step 2 uses the output of
step 1 via template variables). Parallel execution is unsafe in general.
Performance is acceptable — context steps are fast (local DB reads).

## D5: DEFAULT_SCHEMA is embedded in the schema_loader module
**Decision**: DEFAULT_SCHEMA is a YAML string constant in schema_loader.py,
not an external file.

**Rationale**: The schema_loader must always have a fallback. An external
file could be missing from a fresh install. Embedding it avoids a file-not-found
failure path and keeps the fallback path simple.

## D6: discover_grail_tools extended with workspace scan (not replaced)
**Decision**: Extend the existing discover_grail_tools() to accept both a
system_tools_dir (bootstrap/tools/) and an optional workspace_tools_dir
(agent's workspace/tools/). The v1 signature is preserved; new kwargs added.

**Rationale**: The v1 discover_grail_tools already handles compilation, error
logging, and SwarmTool mixing. Reusing it avoids duplicating that logic.

## D7: Reuse existing EventStore DB path
**Decision**: Bootstrap reuses the existing EventStore SQLite database at:
`.remora/events/events.db`

**Rationale**: Avoids split-brain state and keeps bootstrap on the same event
and node projection substrate as v1 runtime flows.

## D8: Subscription matching strategy for bootstrap events
**Decision**: Use a hybrid matching path in SubscriptionPattern:
`event_name = getattr(event, "event_type", type(event).__name__)`.
Keep class-name compatibility for existing events while enabling bootstrap's
dynamic `event_type` envelope model.

**Rationale**: Preserves v1 behavior while allowing bootstrap agents to emit
new event types without requiring a new Python class per event.

## D9: Event reads remain agent-centric for v1 bootstrap
**Decision**: Keep `_event_read` agent-centric for now, using
`EventStore.get_recent_events(agent_id, limit=...)`.
Do not add node-centric event queries in M0.

**Rationale**: Minimal, low-risk integration with current EventStore query
shape. Node-centric query support can be added later as an additive feature.

## D10: Code-neighbor reads are best-effort in v1
**Decision**: Bootstrap graph neighbors for code nodes may use existing
`caller_ids`/`callee_ids` when present, but bootstrap correctness must not
depend on complete call-graph coverage in v1.

**Rationale**: Current v1 projection does not reliably populate full call edges.
Treating this as optional avoids coupling bootstrap correctness to incomplete
topology data.

## D11: Bootstrap graph stays in EventStore, not LSP indexer DB
**Decision**: Add `graph_nodes`/`graph_edges` to EventStore DB and keep
bootstrap graph logic there. Do not depend on `lsp.RemoraDB` edge tables for
bootstrap core behavior.

**Rationale**: Keeps bootstrap runtime adapter-agnostic (works outside LSP),
and centralizes core state in EventStore.

## D12: Use `file` as canonical code unit kind (with optional alias)
**Decision**: Treat `file` as the canonical v1 code container kind in
bootstrap. `module` can be supported as a compatibility alias in read paths.

**Rationale**: Aligns with the current discovery and AgentNode model in v1,
reducing translation overhead and ambiguity.

## D13: Stage-gated implementation with verification at each milestone
**Decision**: Implement and verify one milestone at a time (M0 first), with
tests added and run between stages before moving forward.

**Rationale**: Reduces integration risk and keeps behavior changes reviewable.

## D14: Minimal extra v1 changes are allowed when required
**Decision**: The initial "three modified v1 files" target is preferred, but
minimal additional v1 changes are allowed if needed for correctness.
Every extra v1 change must be documented in project notes.

**Rationale**: Preserves focus while avoiding brittle constraints when runtime
compatibility requires a small supporting change.

## D15: Grail external names must be underscore-free in .pym scripts
**Decision**: Bootstrap system tool `.pym` scripts declare externals as
`cairn_read`, `cairn_write`, `graph_read`, `graph_write`, `event_read`,
`event_write` (no leading `_`).

**Rationale**: Current Grail/Monty type-checking treats references to
leading-underscore external names as unresolved in script execution. Using
underscore-free names keeps scripts executable.

## D16: Bedrock exposes both canonical and Grail-safe external keys
**Decision**: `build_bedrock()` returns both key sets:
- canonical: `_cairn_*`, `_graph_*`, `_event_*`
- aliases: `cairn_*`, `graph_*`, `event_*`

**Rationale**: Preserves the original bedrock naming contract while enabling
Grail scripts to bind to resolvable external names. This is additive and
keeps v1/M0 behavior intact.

## D17: schema.yaml source of truth is Cairn workspace, with one-level extends
**Decision**: `load_schema()` reads `schema.yaml` from `CairnExternals` (agent
workspace), falls back to embedded `DEFAULT_SCHEMA_YAML`, and resolves one
optional `extends` reference from `system_agents_dir/<name>.yaml`.

**Rationale**: Agent-authored schema files are written via workspace tools and
live in Cairn, not real filesystem paths. One-level extends gives practical
reuse without introducing recursive merge complexity in v1 bootstrap.

## D18: TurnExecutor context steps fail-soft and remain sequential
**Decision**: Context steps execute in order; missing/failed steps produce empty
values (with warning for non-optional steps) instead of aborting the turn.

**Rationale**: Preserves forward progress for bootstrap turns when a context
tool is unavailable or transiently fails, while still surfacing actionable logs.

## D19: Coordinator assignment source is agent node attrs, not edges
**Decision**: `find_unassigned_modules()` treats a module as assigned when at
least one `kind=agent` graph node has `attrs.assigned_node_id == module_id`.
It does not currently infer assignment from `assigned_to` edges.

**Rationale**: This aligns with how `handle_agent_needed()` persists assignment
state today and avoids edge-join complexity for initial M3 bootstrap logic.

## D20: Schema `subscriptions[].node_id` is informational in v1
**Decision**: Activation registers schema subscriptions by `event_type` only.
If `node_id` is present in schema, it is resolved for logging but ignored in
`SubscriptionPattern` registration.

**Rationale**: v1 `SubscriptionPattern` does not support node-id filtering.
Keeping this field informational preserves schema compatibility for future
matcher enhancements without blocking M3.

## D21: Agent IDs default to deterministic node-derived IDs
**Decision**: When `AgentNeededEvent.payload.agent_id` is absent, activation
derives a stable ID with `default_agent_id(node_id)`, including sanitized node
tail + short hash suffix.

**Rationale**: Deterministic IDs prevent accidental agent duplication across
repeated coordinator emissions and keep workspace identity stable.

## D22: Filesystem module seeding writes through projection events
**Decision**: `seed_module_nodes_from_filesystem()` seeds module/file nodes by
appending `NodeDiscoveredEvent` (with `NodeProjection`) into the `nodes` table,
instead of writing `kind=module` rows into `graph_nodes`.

**Rationale**: The graph API intentionally rejects code-kind writes through
`write_graph("add_node", ...)`. Projection events keep seeded module nodes in
the same read model as scanner-discovered nodes and avoid adding new write-path
exceptions to `NodeStore`.

## D23: Workspace sidebar panels are shown only when content exists
**Decision**: Companion sidebar renders a dedicated `## Workspace` section only
when at least one workspace panel (`role`, `schema`, `notes`, `todo`, `log`,
`tools`) is non-empty.

**Rationale**: Keeps non-bootstrap node sidebars uncluttered while still
surfacing bootstrap identity artifacts immediately once present.

## D24: ToolSynthesizedEvent is emitted by activation diff, not write tool
**Decision**: New workspace tools are detected in `handle_agent_needed()` via
before/after snapshots of `tools/*.pym`. For each newly seen file, activation
emits `ToolSynthesizedEvent` directly to EventStore.

**Rationale**: This avoids coupling event emission to one specific write tool
implementation and guarantees event generation even if tools are created by
different means during a turn.

## D25: Bootstrap runner uses coordinator pass + direct activation in v1
**Decision**: `BootstrapRunner.run_once()` executes:
1) `find_unassigned_modules()`
2) `emit_agent_needed_events()`
3) direct `handle_agent_needed(...)` calls for each planned assignment.

It does not rely on `EventStore.get_triggers()` for initial `AgentNeededEvent`
dispatch in v1.

**Rationale**: This keeps bootstrap progress deterministic with current v1
subscription semantics while still appending canonical `AgentNeededEvent`
records to EventStore for observability and replay.
