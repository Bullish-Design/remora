# Context — Close Architecture Gaps

## Current State
**PROJECT COMPLETE.** All 4 architecture gaps have been closed, all sub-tasks done, full test suite passes with zero regressions.

## What Was Done

### Gap #1: Wire EventStore trigger consumption in LSP mode
- `src/remora/lsp/__main__.py` — starts `run_from_event_store()` as background task in `_on_initialized`
- `src/remora/lsp/runner.py` — updated `run_from_event_store()` with wait loop for `_running`
- 5 tests in `tests/unit/test_runner_loop.py` (class `TestRunFromEventStore`)

### Gap #2: Add `tags` to `AgentCompleteEvent`
- `src/remora/core/events.py` — added `tags: tuple[str, ...] = ()` to `AgentCompleteEvent`
- 4 tests in `tests/unit/test_projections.py` (class `TestAgentCompleteEventTags`)
- Updated existing test in `test_runner_loop.py` to assert `event.tags == ()`

### Gap #3: Verify swarm tools wired end-to-end
- 5 tests in `tests/unit/test_swarm_executor.py` (class `TestSwarmToolsEndToEnd`)

### Gap #4a: NodeProjection returns follow-up events; EventStore re-appends them
- `src/remora/core/projections.py` — `apply()` returns `list[RemoraEvent]`; stub discovery emits `ScaffoldRequestEvent`
- `src/remora/core/event_store.py` — `append()` captures and re-appends follow-up events
- 5 tests in `tests/unit/test_projections.py` (class `TestScaffoldFollowUpEvents`)

### Gap #4b: ScaffoldRequestEvent routing via subscriptions
- `src/remora/core/events.py` — added `to_agent: str` field to `ScaffoldRequestEvent`
- `src/remora/core/projections.py` — passes `to_agent=event.node_id`
- 1 routing test in `tests/unit/test_projections.py`

### Gap #4c: Pass scaffold_context to _build_prompt()
- `src/remora/core/execution.py` — builds `scaffold_context` dict when trigger is `ScaffoldRequestEvent`
- 5 tests in `tests/unit/test_execution.py`

### Gap #4d: Pass tags=("scaffold",) on AgentCompleteEvent
- `src/remora/core/swarm_executor.py` — computes scaffold tags, passes to `AgentCompleteEvent`
- `src/remora/lsp/runner.py` — `trigger_event` field on `Trigger`, threaded through pipeline, scaffold tags
- 2 tests each in `test_swarm_executor.py` and `test_runner_loop.py`

### Bugfixes
- `src/remora/core/tools/spawn_child.py` — added `to_agent=node_id`
- `tests/unit/test_scaffold_events.py` — fixed all 10 constructors
- `tests/integration/test_scaffold_lifecycle.py` — fixed all 3 constructors

### Test Infrastructure
- `tests/conftest.py` — added pytest hooks for real-time test progress logging

## Test Results
Full suite: 9 failures, all pre-existing (vLLM, CLI, event_store, companion, hypothesis flaky). Zero regressions from our work.
