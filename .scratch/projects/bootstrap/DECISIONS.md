# Bootstrap Implementation Decisions

## D1: Bootstrap graph in EventStore DB (not a separate file)
**Decision**: Add `bootstrap_nodes` + `bootstrap_edges` tables to the existing
event_store.db via `event_store_schema.py`. BootstrapGraphStore wraps the same
SQLite connection (write_conn / read_conn pair) from EventStore.

**Rationale**: EventStore already manages WAL mode, read/write lock separation,
and retry logic. Adding tables to the same DB avoids a third SQLite file and
lets the graph store benefit from the same connection-management infrastructure.

**Tradeoff**: Couples bootstrap graph schema to EventStore's schema module.
Accepted — the bootstrap is explicitly built on top of v1 infrastructure.

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
