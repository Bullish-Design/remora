# CONTEXT — Launch Plan Execution

## Current State
- **Active batch:** Batch 3 (Runner Merge) — COMPLETE
- **Next action:** Batch 4 (Identity Unification) or continue with unblocked items

## What Just Happened
- Completed Batch 3: Unified AgentRunner merge
  - Steps 3.1-3.4: Read both runners, wrote 27 failing tests, ported cascade safety + EventStore bridge into `lsp/runner.py`
  - Step 3.5: Implemented `_HeadlessServer` adapter and `AgentRunner.create_headless()` classmethod — all 27 tests pass
  - Step 3.6: Updated CLI (`src/remora/cli/main.py`) to use `AgentRunner.create_headless()` + `run_from_event_store()`
  - Step 3.7: Deleted `src/remora/core/agent_runner.py`
  - Step 3.8: Updated `src/remora/__init__.py` and `src/remora/core/__init__.py` to re-export `AgentRunner` from `remora.lsp.runner` (dropped `ExecutionContext`)
  - Step 3.9: Rewrote `tests/integration/test_agent_runner.py` to use unified runner via `create_headless()`
  - Step 3.10: Full test suite passes (only `test_real_vllm` fails — infrastructure dependency)

## Completed Batches
- **Batch 1**: 25 quick fixes (committed `597a550`)
- **Batch 2**: 12 medium items (committed across `a69957c`, `6e85a43`, `97ab627`, `56a92be`, `6e9eadb`, `3c009c3`, `4eceb4c`)
- **Batch 3**: Runner merge — COMPLETE (pending commit)

## Architecture After Batch 3
- **Single runner**: `src/remora/lsp/runner.py::AgentRunner` — handles both LSP and CLI modes
- **LSP mode**: Constructed with a `RemoraLanguageServer` instance
- **CLI/headless mode**: Constructed via `AgentRunner.create_headless(event_store=...)` using `_HeadlessServer` adapter
- **Cascade safety**: depth tracking, cooldown, concurrency semaphore (ported from deleted core runner)
- **EventStore bridge**: `run_from_event_store()` feeds `get_triggers()` into the runner queue
- **Deleted**: `src/remora/core/agent_runner.py` and `ExecutionContext` dataclass
- **Re-exports**: `AgentRunner` now comes from `remora.lsp.runner` in both `remora.__init__` and `remora.core.__init__`

## Key Files Modified in Batch 3
| File | Change |
|------|--------|
| `src/remora/lsp/runner.py` | Added cascade safety, `_HeadlessServer`, `_HeadlessDB`, `create_headless()` |
| `tests/unit/test_unified_runner.py` | 27 tests for unified runner |
| `src/remora/cli/main.py` | Switched from core runner to `create_headless()` |
| `src/remora/core/agent_runner.py` | DELETED |
| `src/remora/__init__.py` | Updated re-export |
| `src/remora/core/__init__.py` | Updated re-export |
| `tests/integration/test_agent_runner.py` | Rewritten for unified runner |

## Next Steps
- Batch 4: Identity Unification (1.1) — now unblocked by Batch 3
- Batch 5: Post-Unification Cleanup — blocked on Batch 4
- Batch 7: Testing items 7.1, 7.2 — now unblocked by Batch 3
- Batch 8: Quality & Polish — independent items can proceed

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
6. LSP runner is the base for unification — it has the modern AgentNode-based approach, tool loop, proposals
7. `_HeadlessServer` + `_HeadlessDB` stubs provide minimal server duck-type for CLI mode
8. `ExecutionContext` dropped — only used internally by the now-deleted core runner

## How to Resume
1. Read `.scratch/CRITICAL_RULES.md`
2. Read `.scratch/REPO_RULES.md`
3. Read this file
4. Check PROGRESS.md for next batch
5. Start next pending batch
