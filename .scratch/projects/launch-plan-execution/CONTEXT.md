# CONTEXT — Launch Plan Execution

## Current State
- **Active batch:** Batch 5 (Post-Unification Cleanup) — starting
- **Next after:** Batch 6

## What Just Happened
- Completed Batch 4 (Identity Unification) as commit `e546588`
  - Reconciler rewritten to emit NodeDiscoveredEvent/NodeRemovedEvent
  - SwarmExecutor uses AgentNode instead of AgentState, explicit chat_history kwarg
  - CLI, service handlers, API, LSP server all use EventStore nodes table
  - AgentState/AgentMetadata/SwarmState removed from public re-exports
  - 19 TDD tests in test_identity_unification.py
  - 7 existing test files updated
- Full test suite: 502 passed, 2 xfailed

## Completed Batches
- **Batch 1**: 25 quick fixes (commit `597a550`)
- **Batch 2**: 12 medium items (commits `a69957c` through `4eceb4c`)
- **Batch 3**: Runner merge (commit `59cb192`)
- **Batch 7**: Testing — 87 new tests (commit `81f851e`)
- **Batch 8**: Quality & Polish (commits `4038a02`, `595ceb9`)
- **Batch 4**: Identity unification (commit `e546588`)

## Architecture After Batch 4
- **Single source of truth**: EventStore `nodes` table (via `NodeProjection`)
- **Reconciler**: Emits `NodeDiscoveredEvent`/`NodeRemovedEvent` → projection handles persistence
- **SwarmExecutor**: Takes `AgentNode` not `AgentState`, no `swarm_state` in constructor
- **CLI/Service/LSP**: All query `event_store.list_nodes()`/`get_node()` — no SwarmState
- **Still exist but unused by live code**: `agent_state.py`, SwarmState `agents` table
- **Single runner**: `src/remora/lsp/runner.py::AgentRunner` — handles both LSP and CLI modes

## What Needs to Be Done Next

### Batch 5: Post-Unification Cleanup (NOW) — 2 remaining items
- D13/D14 already done in Batch 4 (re-export cleanup)
- 5.1 (D1): Delete `agent_state.py` and its tests
- 5.2 (D2): Remove SwarmState `agents` table and its tests

### Batch 6: Architecture Alignment — 6 items
- 6.1 (2.1): Unify event models → frozen Pydantic
- 6.2 (2.3): Pydantic Config (BaseSettings)
- 6.3 (2.4): Single SQLite database
- 6.4 (2.5): Typed externals protocol
- 6.5 (2.6): Kernel factory
- 6.6 (D9): Delete stdlib dataclass models

## Key Context for Resumption
- Master task list: `REMORA_LAUNCH_PLAN.md` (root)
- Execution plan: `.scratch/projects/launch-plan-execution/PLAN.md`
- Progress tracker: `.scratch/projects/launch-plan-execution/PROGRESS.md`
- Test command: `python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py --ignore=tests/unit/test_graph_cli.py --ignore=tests/test_app.py --ignore=tests/test_bridge.py --ignore=tests/test_css.py --ignore=tests/test_entry_points.py --ignore=tests/test_integration_graph.py --ignore=tests/test_layout.py --ignore=tests/test_svg.py --ignore=tests/test_views.py -q`
- All work is in `src/remora/` — `remora_demo/` is out of scope

## Key Decisions Made (carried forward)
1. LSP events stored directly in EventStore (no `to_core_event()` conversion)
2. `to_hover()` dual-format — accepts both dicts and objects
3. Runner dict access — `event["event_type"]` for EventStore query results
4. `build_chat_tools` is broken — `Tool.from_function()` doesn't exist (documented with xfail)
5. `get_subscriptions` name collision — **FIXED**: property `subscription_registry` + method `get_agent_subscriptions(agent_id)`
6. LSP runner is the base for unification — modern AgentNode-based approach, tool loop, proposals
7. `_HeadlessServer` + `_HeadlessDB` stubs provide minimal server duck-type for CLI mode
8. `ExecutionContext` dropped — only used internally by the now-deleted core runner
9. **Reconciler uses NodeDiscoveredEvent/NodeRemovedEvent** — same projection path as LSP watcher
10. **SwarmExecutor chat history** pulled from `EventStore.get_recent_events()` — no mutable `state.chat_history`

## How to Resume
1. Read `.scratch/CRITICAL_RULES.md`
2. Read `.scratch/REPO_RULES.md`
3. Read this file
4. Check PROGRESS.md for next batch
5. Start next pending batch
