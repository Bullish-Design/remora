# Bootstrap Implementation Progress

## Status: M6 COMPLETE (implementation guide milestones complete)

## Tasks

| # | Task | Status |
|---|------|--------|
| 1 | Read V6 concept doc | done |
| 2 | Study v1 implementation | done |
| 3 | Write ASSUMPTIONS.md | done |
| 4 | Write DECISIONS.md | done |
| 5 | Write IMPLEMENTATION_GUIDE.md — ToC | done |
| 6 | Write IMPLEMENTATION_GUIDE.md — §1 Overview | done |
| 7 | Write IMPLEMENTATION_GUIDE.md — §2 Module Layout | done |
| 8 | Write IMPLEMENTATION_GUIDE.md — §3 M0 Bedrock | done |
| 9 | Write IMPLEMENTATION_GUIDE.md — §4 M1 System Tools | done |
| 10 | Write IMPLEMENTATION_GUIDE.md — §5 M2 Turn Executor | done |
| 11 | Write IMPLEMENTATION_GUIDE.md — §6 M3 Self-Bootstrap | done |
| 12 | Write IMPLEMENTATION_GUIDE.md — §7 M4 Graph Seeding | done |
| 13 | Write IMPLEMENTATION_GUIDE.md — §8 M5 Companion | done |
| 14 | Write IMPLEMENTATION_GUIDE.md — §9 M6 Tool Synthesis | done |
| 15 | Write IMPLEMENTATION_GUIDE.md — §10 Testing Plan | done |
| 16 | Write CONTEXT.md | done |

## Implementation execution (post-guide)

| # | Task | Status |
|---|------|--------|
| M0.1 | Add EventStore graph tables (`graph_nodes`, `graph_edges`) | done |
| M0.2 | Extend NodeStore with `read_graph()` / `write_graph()` | done |
| M0.3 | Implement bootstrap bedrock module (`build_bedrock`, event/write/read closures) | done |
| M0.4 | Add hybrid subscription event-name matching (`event_type` fallback) | done |
| M0.5 | Add and run targeted M0 tests | done |
| M1.1 | Extend `discover_grail_tools()` for bootstrap externals + workspace tools scan | done |
| M1.2 | Add nine bootstrap system tools (`bootstrap/tools/*.pym`) | done |
| M1.3 | Add M1 tests (tool compilation, externals, discovery behavior) | done |
| M1.4 | Run targeted M0+M1 regression suites and ruff checks | done |
| M2.1 | Add schema loader (`schema_loader.py`) with default fallback + extends merge | done |
| M2.2 | Add turn executor (`turn_executor.py`) with context pipeline + kernel dispatch | done |
| M2.3 | Add M2 tests (`test_schema_loader.py`, `test_turn_executor.py`) | done |
| M2.4 | Run targeted M0+M1+M2 regression suites and ruff checks | done |
| M3.1 | Add bootstrap agent schema assets (`bootstrap/agents/*.yaml`) | done |
| M3.2 | Add coordinator helpers (`find_unassigned_modules`, `emit_agent_needed_events`) | done |
| M3.3 | Add activation handler (`handle_agent_needed`) for AgentNeeded flow | done |
| M3.4 | Add M3 tests (`test_agent_schemas.py`, `test_coordinator.py`, `test_activation.py`) | done |
| M3.5 | Run targeted M3 tests + lint checks | done |
| M4.1 | Add `seed_graph.py` module seeding helpers | done |
| M4.2 | Add M4 tests (`test_seed_graph.py`) | done |
| M4.3 | Run targeted M4 + focused bootstrap regression suites | done |
| M5.1 | Add companion workspace panel builder | done |
| M5.2 | Integrate workspace panels into sidebar composer output | done |
| M5.3 | Add companion tests for workspace panel rendering | done |
| M5.4 | Run targeted companion tests + lint | done |
| M6.1 | Emit `ToolSynthesizedEvent` when new workspace `.pym` tools appear after activation | done |
| M6.2 | Add M6 activation test coverage for synthesized-tool event emission | done |
| M6.3 | Run targeted bootstrap + companion regression checks | done |
