# Bootstrap Implementation Assumptions

## Audience
Developers implementing the Phase 2 bootstrap system on top of the existing
remora v1 codebase.

## V1 Components Being Reused
- `EventStore` (core/store/event_store.py) — event appending, WAL SQLite, triggers
- `CairnWorkspaceService` + `CairnExternals` (core/agents/cairn_bridge.py) — per-agent workspaces
- `RemoraGrailTool` + `discover_grail_tools()` (core/tools/grail.py) — .pym tool loading
- `SubscriptionRegistry` + `SubscriptionPattern` (core/events/subscriptions.py) — event routing
- `create_kernel()` (core/agents/kernel_factory.py) — LLM kernel construction

## Key Constraints
- Bootstrap module lives in `src/remora/bootstrap/` — new tach module
- tach.toml must declare this module and its dependencies (no hidden imports)
- Bootstrap bedrock functions are async — matches v1 async patterns throughout
- The bootstrap graph reuses the EventStore SQLite DB (new tables: bootstrap_nodes, bootstrap_edges)
- The TurnExecutor runs in parallel to v1's execute_agent_turn — no replacement

## Graph Store Decision
User chose "extend NodeStore" — implemented as:
- New tables `bootstrap_nodes` + `bootstrap_edges` in the existing event_store.db
- New class `BootstrapGraphStore` (similar to NodeStore) that shares the EventStore DB connection
- Added to event_store_schema.py's create_tables() and EventStore.initialize()

## schema.yaml vs manifest.yaml
Both exist in parallel. Bootstrap agents use schema.yaml + TurnExecutor.
V1 agents continue using BundleManifest + execute_agent_turn(). No migration required.

## .pym Tool Architecture
- System tools: `bootstrap/tools/*.pym` (committed to repo, not in src/)
- Agent-synthesized tools: `{swarm_root}/agents/{id}/workspace/tools/*.pym` (runtime)
- Both discovered by discover_grail_tools() with the bootstrap externals dict
- Synthesized tools declare @external on system tool functions, NOT on bedrock
