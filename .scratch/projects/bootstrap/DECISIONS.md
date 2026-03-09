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
