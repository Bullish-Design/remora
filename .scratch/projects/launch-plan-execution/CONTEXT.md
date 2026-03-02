# CONTEXT — Launch Plan Execution

## Current State
- **Active batch:** Batch 2 (Track B Medium Items) — COMPLETE (12/12 items done)
- **Next action:** Batch 3 (Critical Path — Runner Merge, item 1.2)

## What Just Happened
- Committed items 2.10 (ChatSession tests) and 2.11 (service tests) as `3c009c3`
- Completed item 2.12: Phase 1 testing gaps T1-T7
  - T1: 6 tests for `ToolSchema.to_llm_tool()` — validates OpenAI function-calling format, nested params, empty params, JSON serializability
  - T2: 7 tests for extension complex fields through projection round-trip — extra_tools, extra_subscriptions, mounted_workspaces survive EventStore→DB→from_row cycle
  - T3: 8 tests for `from_row()` error paths — malformed JSON raises JSONDecodeError, wrong structure raises TypeError, null fields default to empty lists
  - T4: 3 concurrency tests for `append()` — 50 concurrent appends same graph, 20 concurrent upserts same node_id with projection, 30 appends across 3 graphs
  - T5: Skipped — CSTNode→NodeDiscoveredEvent conversion path not built yet
  - T6: 5 tests for `extension_matches()` error isolation — ValueError propagates, old-API TypeError fallback works, old-API non-TypeError propagates, projection with first-match-wins skips broken extensions
  - T7: 5 tests for shared fixtures `make_agent_node()` and `make_discovered_event()` — defaults, overrides, round-trip
  - Total: 34 new tests, all passing
  - Full suite passes (only failure: test_real_vllm — infrastructure dependency)

## Completed Batches
- **Batch 1**: 25 quick fixes (committed `597a550`)
- **Batch 2**: 12 medium items (committed across `a69957c`, `6e85a43`, `97ab627`, `56a92be`, `6e9eadb`, `3c009c3`, + pending 2.12 commit)

## Next Steps — Batch 3: Critical Path — Runner Merge
Steps 3.1–3.9 in PROGRESS.md. This is the highest-priority architectural change:
1. Read and understand both runners (`core/agent_runner.py` + `lsp/runner.py`)
2. Write failing integration test
3. Start with LSP runner as base
4. Port cascade safety from core runner
5. Add pluggable tool registry
6. Make unified runner callable from LSP + swarm
7. Delete `core/agent_runner.py`
8. Refactor `swarm_executor.py` into tool provider
9. Verify all tests pass

## Key Context for Resumption
- Master task list: `REMORA_LAUNCH_PLAN.md` (root)
- Execution plan: `.scratch/projects/launch-plan-execution/PLAN.md`
- Progress tracker: `.scratch/projects/launch-plan-execution/PROGRESS.md`
- Test command: `python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py --ignore=tests/unit/test_graph_cli.py --ignore=tests/test_app.py --ignore=tests/test_bridge.py --ignore=tests/test_css.py --ignore=tests/test_entry_points.py --ignore=tests/test_integration_graph.py --ignore=tests/test_layout.py --ignore=tests/test_svg.py --ignore=tests/test_views.py -q`
- All work is in `src/remora/` — `remora_demo/` is out of scope
- Tests in `tests/unit/test_graph_*.py` and `tests/unit/test_web_layout.py` depend on `remora_demo` — ignore them

## Key Decisions Made (carried forward)
1. LSP events stored directly in EventStore (no `to_core_event()` conversion)
2. `to_hover()` dual-format — accepts both dicts and objects
3. Runner dict access — `event["event_type"]` for EventStore query results
4. `build_chat_tools` is broken — `Tool.from_function()` doesn't exist (documented with xfail)
5. `get_subscriptions` name collision — async method shadows property getter in RemoraService (documented with test)

## How to Resume
1. Read `.scratch/CRITICAL_RULES.md`
2. Read `.scratch/REPO_RULES.md`
3. Read this file
4. Commit item 2.12 if not yet committed
5. Start Batch 3 step 3.1 — read both runners
