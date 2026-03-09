# Bootstrap Implementation Project Context

## Status: COMPLETE — Implementation guide written

## Output
`.scratch/projects/bootstrap/IMPLEMENTATION_GUIDE.md` — 1888 lines, 10 sections

## What was done
Studied the v1 remora implementation and wrote a full actionable implementation
spec mapping every V6 bootstrap concept to v1 components.

## Key decisions captured (see DECISIONS.md)
- NodeStore is the unified graph API — extended with read_graph() + write_graph()
- New tables graph_nodes + graph_edges in event_store.db (not a separate file)
- Code topology (functions/classes/modules) is LIVE in nodes table — no seeding needed
- Bedrock _graph_read/_graph_write call event_store.nodes directly
- TurnExecutor runs parallel to v1's execute_agent_turn() — no replacement
- discover_grail_tools() extended with workspace_tools_dir + direct externals param

## V1 files modified (three only)
- core/store/event_store_schema.py — add create_graph_tables()
- core/store/node_store.py — add read_graph(), write_graph(), routing helpers
- core/tools/grail.py — add workspace_tools_dir + externals params

## New files
- src/remora/bootstrap/__init__.py
- src/remora/bootstrap/bedrock.py          (NO graph_store.py — it's in NodeStore now)
- src/remora/bootstrap/schema_loader.py
- src/remora/bootstrap/turn_executor.py
- src/remora/bootstrap/seed_graph.py
- bootstrap/tools/*.pym (9 files)
- bootstrap/agents/DEFAULT_SCHEMA.yaml
- bootstrap/agents/base_code_agent.yaml

## Next step
Start M0 implementation: event_store_schema.py + graph_store.py + bedrock.py
