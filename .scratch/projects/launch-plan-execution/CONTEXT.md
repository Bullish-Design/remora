# CONTEXT — Launch Plan Execution

## Current State
- **Active batch:** ALL BATCHES COMPLETE
- **Last completed:** Appendix A (Data Flow Walkthrough) for PYDANTIC_CONSOLIDATION_REFACTOR.md
- **Test suite:** 653 passed, 2 xfailed

## What Just Happened
- Completed `PYDANTIC_CONSOLIDATION_REFACTOR.md` — full document with Appendix A:
  - **Sections 1-9** (989 lines): Executive summary, before/after analysis for all 5 conversion items (ToolSchema, SubscriptionPattern/Subscription, CSTNode, ToolCall/LLMResponse, Message/ChatConfig/AgentResponse), serialization simplification, implementation order, estimated scope
  - **Appendix A** — Data Flow Walkthrough (Before/After), 4 scenarios:
    - A.1 — Discovery → Storage → LSP Display (Neovim Path) — COMPLETE
    - A.2 — Event → Subscription → Trigger → LLM → Proposal (Reactive Path) — COMPLETE
    - A.3 — Chat Service → Message → AgentResponse (HTTP API Path) — COMPLETE
    - A.4 — Events → UiStateProjector → Graph Web UI (Frontend Path) — COMPLETE
    - Cross-cutting summary table at the end
  - Total document: ~1800+ lines
- All launch plan batches remain complete (653 passed, 2 xfailed)

## What Needs to Be Done Next

ALL BATCHES COMPLETE. ALL DOCUMENTATION COMPLETE.
- The launch plan execution is finished (75+ items, Batches 1-8)
- The Pydantic consolidation refactor guide is finished (sections 1-9 + Appendix A)
- Implementation of the Pydantic consolidation is a future task (~78 LOC, ~90 min, 7 files)

## Key Context for Resumption
- Master task list: `REMORA_LAUNCH_PLAN.md` (root)
- Execution plan: `.scratch/projects/launch-plan-execution/PLAN.md`
- Progress tracker: `.scratch/projects/launch-plan-execution/PROGRESS.md`
- Pydantic refactor guide: `PYDANTIC_CONSOLIDATION_REFACTOR.md` (root)
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
16. **UI components stay as @dataclass** — rendering components (Component ABC), not data models
17. **`is_dataclass` branches kept in projector** — needed for `structured_agents` external events

## How to Resume
1. Read `.scratch/CRITICAL_RULES.md`
2. Read `.scratch/REPO_RULES.md`
3. Read this file
4. Check PROGRESS.md for next batch
5. Start next pending batch
