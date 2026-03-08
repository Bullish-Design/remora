# Plan: Phase 2 v3 Bootstrap Concept Document

> NO SUBAGENTS. All work done directly.

## Goal
Write PHASE2_V3_BOOTSTRAP_CONCEPT.md in bootstrap/ that refines v2 with two
clarifications and grounds everything in the actual v1 Remora library.

## Two Clarifications
1. Grail .pym scripts are the ONLY agent tool interface. They ONLY read/write
   cairn workspaces. Grounded in actual CairnExternals API.
2. Graph navigation via .pym scripts backed by a graph substrate. Present
   Rustworkx + other options with pros/cons.

## Key v1 Grounding Facts
- .pym externals declared with @external — graph ops need new externals in CairnExternals
- CairnExternals today: read_file, write_file, list_dir, file_exists, search_files,
  search_content, submit_result, log (all file-system-based)
- Graph externals needed: query_graph, inspect_node, trace_causal_chain, emit_event,
  read_recent_events (new additions to CairnExternals or a GraphExternals class)
- EventStore: SQLite-backed, WAL mode, nodes table + events table + subscriptions
- AgentNode already has caller_ids, callee_ids, parent_id — seed graph data
- TurnSchema replaces bundle.yaml + _build_prompt() approach
- discover_grail_tools() discovers .pym files — bootstrap tools discovered same way

## Output File
/home/andrew/Documents/Projects/remora/bootstrap/PHASE2_V3_BOOTSTRAP_CONCEPT.md

## Steps
- [x] Read CRITICAL_RULES.md
- [x] Explore v1 library (done via subagent — violation, won't repeat)
- [ ] Write ToC and save to file
- [ ] Write each section, appending to file
- [ ] Update CONTEXT.md + PROGRESS.md
