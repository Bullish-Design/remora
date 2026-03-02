# CONTEXT — Launch Plan Execution

## Current State
- **Active batch:** Batch 2 (Track B Medium Items) — 10 of 12 items COMPLETE
- **Next action:** Item 2.10 (Write ChatSession tests)

## What Just Happened
- Completed item 2.1: RemoraDB dual-write elimination
  - EventStore now has `get_recent_events()` and `get_events_for_correlation()` methods
  - LSP `emit_event()` stores Pydantic events directly in EventStore (no `to_core_event()` conversion)
  - Removed events table, indexes, and 4 event methods from RemoraDB
  - Updated 3 reader call sites (commands.py, hover.py, runner.py) to use EventStore
  - Updated `to_hover()` in agent_node.py to handle both dicts and objects
  - Cleaned up test_lsp_db.py (removed dead test) and test_lsp_runner.py (removed stale mock)
  - 12 new TDD tests in test_event_store_queries.py — all passing
  - Full test suite passes (only failure: test_real_vllm — infrastructure dependency)

## Completed Batch 2 Items
- 2.1: RemoraDB dual-write elimination (committed)
- 2.2: SubscribeTool self-referencing bug (committed `97ab627`)
- 2.3: Hardcoded LLM configs (committed `6e85a43`)
- 2.4: Reconciler stale metadata (committed `97ab627`)
- 2.5: Widen AgentExtension.matches() API (committed `97ab627`)
- 2.6: Populate last_trigger_event (committed `6e85a43`)
- 2.7: Add start_byte/end_byte to NodeDiscoveredEvent (committed `a69957c`)
- 2.8: Parameterize language in system prompt (committed `a69957c`)
- 2.9: Subscription index for O(1) lookup (committed `56a92be`)

## Remaining Batch 2 Items (suggested order)
- **2.10**: Write ChatSession tests
- **2.11**: Write service/ package tests
- **2.12**: Phase 1 testing gaps T1-T7

## Key Context for Resumption
- Master task list: `REMORA_LAUNCH_PLAN.md` (root)
- Execution plan: `.scratch/projects/launch-plan-execution/PLAN.md`
- Progress tracker: `.scratch/projects/launch-plan-execution/PROGRESS.md`
- Test command: `python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py --ignore=tests/unit/test_graph_cli.py --ignore=tests/test_app.py --ignore=tests/test_bridge.py --ignore=tests/test_css.py --ignore=tests/test_entry_points.py --ignore=tests/test_integration_graph.py --ignore=tests/test_layout.py --ignore=tests/test_svg.py --ignore=tests/test_views.py -q`
- All work is in `src/remora/` — `remora_demo/` is out of scope
- Tests in `tests/unit/test_graph_*.py` and `tests/unit/test_web_layout.py` depend on `remora_demo` — ignore them

## How to Resume
1. Read `.scratch/CRITICAL_RULES.md`
2. Read `.scratch/REPO_RULES.md`
3. Read this file
4. Continue with next Batch 2 item (2.10)
