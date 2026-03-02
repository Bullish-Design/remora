# CONTEXT — Launch Plan Execution

## Current State
- **Active batch:** Batch 6.6 (Delete stdlib dataclass remnants) — pending
- **Last completed:** Batch 6.3 (Single SQLite Database)
- **Test suite:** 638 passed, 2 xfailed

## What Just Happened
- Completed Batch 6.3 (Single SQLite Database):
  - EventStore.initialize() now enables WAL mode + PRAGMA synchronous=NORMAL
  - EventStore.initialize() creates subscriptions table (shared with SubscriptionRegistry)
  - EventStore.initialize() creates RemoraDB operational tables (edges, proposals, cursor_focus, activation_chain, command_queue)
  - SubscriptionRegistry accepts optional `connection=` and `lock=` kwargs for shared-connection mode
  - RemoraDB accepts optional `connection=` and `lock=` kwargs for shared-connection mode
  - Both maintain full backward compatibility with standalone `db_path` mode
  - 15 TDD tests in `tests/unit/test_single_db.py`
  - 638 passed, 2 xfailed, 0 failures

## Completed Batches
- **Batch 1**: 25 quick fixes (commit `597a550`)
- **Batch 2**: 12 medium items (commits `a69957c` through `4eceb4c`)
- **Batch 3**: Runner merge (commit `59cb192`)
- **Batch 7**: Testing — 87 new tests (commit `81f851e`)
- **Batch 8**: Quality & Polish (commits `4038a02`, `595ceb9`)
- **Batch 4**: Identity unification (commit `e546588`)
- **Batch 5**: Post-Unification Cleanup (commit `9b9171a`)
- **Batch 6.1**: Unified events → frozen Pydantic (commit `b4f54d9`)
- **Batch 6.2**: Pydantic Config/BaseSettings (commit `b4f54d9`)
- **Batch 6.3**: Single SQLite Database (pending commit)
- **Batch 6.4**: Typed externals / AgentContext (commit `b4f54d9`)
- **Batch 6.5**: Kernel factory (commit `b4f54d9`)

## What Needs to Be Done Next

### Batch 6.6: Delete stdlib dataclass remnants (NOW)
- D9: Find and remove any remaining stdlib `@dataclass` models that have been replaced by Pydantic
- This was blocked on 6.1 and 6.2 completing the Pydantic migration

## Key Context for Resumption
- Master task list: `REMORA_LAUNCH_PLAN.md` (root)
- Execution plan: `.scratch/projects/launch-plan-execution/PLAN.md`
- Progress tracker: `.scratch/projects/launch-plan-execution/PROGRESS.md`
- Test command: `python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py --ignore=tests/unit/test_graph_cli.py --ignore=tests/test_app.py --ignore=tests/test_bridge.py --ignore=tests/test_css.py --ignore=tests/test_entry_points.py --ignore=tests/test_integration_graph.py --ignore=tests/test_layout.py --ignore=tests/test_svg.py --ignore=tests/test_views.py -q --no-cov`
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
11. **Core events are now frozen Pydantic BaseModel** — `_FrozenEvent` base class
12. **Config is Pydantic BaseSettings** — `env_prefix="REMORA_"`
13. **AgentContext replaces externals dict** — typed Pydantic model with `as_externals()`
14. **Kernel factory** — `create_kernel()` deduplicates boilerplate
15. **Single SQLite DB** — EventStore creates all tables; SubscriptionRegistry/RemoraDB accept shared connection

## How to Resume
1. Read `.scratch/CRITICAL_RULES.md`
2. Read `.scratch/REPO_RULES.md`
3. Read this file
4. Check PROGRESS.md for next batch
5. Start next pending batch
