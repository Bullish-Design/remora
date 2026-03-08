# Bootstrap Implementation Project Context

## Status: COMPLETE — Implementation guide written

## Output
`.scratch/projects/bootstrap/IMPLEMENTATION_GUIDE.md` — 1888 lines, 10 sections

## What was done
Studied the v1 remora implementation and wrote a full actionable implementation
spec mapping every V6 bootstrap concept to v1 components.

## Key decisions captured (see DECISIONS.md)
- Bootstrap graph = new tables (bootstrap_nodes, bootstrap_edges) in the existing
  event_store.db, exposed via BootstrapGraphStore (sibling to NodeStore)
- Bedrock = async closures built per activation by build_bedrock() factory
- TurnExecutor runs parallel to v1's execute_agent_turn() — no replacement
- discover_grail_tools() extended with workspace_tools_dir + direct externals param

## V1 files modified (minimal)
- core/store/event_store_schema.py — add create_bootstrap_tables()
- core/store/event_store.py — expose .bootstrap_graph property
- core/tools/grail.py — add workspace_tools_dir + externals params to discover_grail_tools

## New files
- src/remora/bootstrap/__init__.py
- src/remora/bootstrap/bedrock.py
- src/remora/bootstrap/graph_store.py
- src/remora/bootstrap/schema_loader.py
- src/remora/bootstrap/turn_executor.py
- src/remora/bootstrap/seed_graph.py
- bootstrap/tools/*.pym (9 files)
- bootstrap/agents/DEFAULT_SCHEMA.yaml
- bootstrap/agents/base_code_agent.yaml

## Next step
Start M0 implementation: event_store_schema.py + graph_store.py + bedrock.py
