# Plan — Close All Remaining Architecture Gaps

> **ABSOLUTE RULE: NO SUBAGENTS.** Never use the Task tool. Do all work directly.

## Overview

Close the 4 remaining gaps from ARCHITECTURE_REASSESSMENT.md to bring Remora's implementation into full alignment with `docs/EventBased_Concept.md`.

## Implementation Order (dependency-aware)

### Step 1: Gap #2 — Add `tags` to `AgentCompleteEvent` (TRIVIAL, no deps)

**Files:**
- `src/remora/core/events.py` — Add `tags: tuple[str, ...] = ()` to `AgentCompleteEvent`
- `src/remora/lsp/runner.py` — Pass `tags=()` at lines 471-478 (no behavioral change yet)
- `tests/unit/test_events.py` or similar — Test that tags field exists and defaults to empty tuple

**Acceptance:**
- `AgentCompleteEvent(graph_id="x", agent_id="y", result_summary="z", tags=("scaffold",))` works
- Default is empty tuple
- Existing code that doesn't pass `tags` continues to work

### Step 2: Gap #1 — Wire EventStore trigger consumption in LSP mode (HIGH IMPACT)

**Problem:** `EventStore.append()` puts subscription-matched triggers into `_trigger_queue`, but in LSP mode nobody consumes it. `run_from_event_store()` exists but is only used for CLI/headless.

**Files:**
- `src/remora/lsp/__main__.py` — Start `run_from_event_store()` as background task alongside `run_forever()` in `_on_initialized`
- `src/remora/lsp/runner.py` — Add deduplication: when `run_from_event_store()` bridges a trigger, it should not duplicate triggers that were already manually enqueued via `runner.trigger()`. Strategy: track recently-triggered `(agent_id, event_type)` pairs with a short TTL set.
- Tests — Test that EventStore subscription-matched triggers flow to runner in LSP mode

**Deduplication Strategy:**
- `run_from_event_store()` already calls `self.trigger()`, which has cooldown checking
- The existing cooldown (`_check_cooldown` with `trigger_cooldown_ms=1000`) already prevents rapid re-triggering of the same agent
- So the existing cascade safety mechanisms handle dedup naturally — no extra dedup layer needed
- Just need to make sure `run_from_event_store()` passes meaningful correlation_ids

**Acceptance:**
- When EventStore.append() matches a subscription, the trigger flows to AgentRunner without manual wiring
- The full reactive loop is closed: event → EventStore → subscription → trigger → runner → execute
- No double-triggering due to manual trigger() + subscription trigger for same event

### Step 3: Gap #3 — Verify swarm tools wired end-to-end

**Discovery:** `SubscribeTool` and `UnsubscribeTool` already exist as Python `SwarmTool` classes in `src/remora/core/tools/swarm.py`. They are included in `build_swarm_tools()` which is called from `discover_grail_tools()` → `build_swarm_tools()`.

**Files:**
- Trace the full chain: `execution.py` → `discover_grail_tools()` → `build_swarm_tools()` → `SubscribeTool`/`UnsubscribeTool` → `AgentContext.register_subscription`/`unsubscribe_subscription` → `SubscriptionRegistry`
- Write a focused test verifying the chain: given an AgentContext with working callbacks, `SubscribeTool.execute()` creates a subscription in the registry

**Acceptance:**
- Test proves subscribe/unsubscribe tools work end-to-end with real SubscriptionRegistry
- No `.pym` scripts needed — the gap is confirmed closed

### Step 4: Gap #4 — Wire scaffold lifecycle (depends on Step 1)

**Problem:** `_is_stub()` detection works, `ScaffoldRequestEvent` exists, but nothing emits it and no subscription routes it.

**Files:**
- `src/remora/core/projections.py` — After detecting `status = "scaffold"` in `_project_node_discovered()`, emit a `ScaffoldRequestEvent`. BUT: projections run synchronously in the same SQLite transaction. We can't call `EventStore.append()` from inside the projection. Instead, return a list of "follow-up events" from `apply()` that EventStore will append after commit.
- Alternative: Have `EventStore.append()` check the return value of `_projection.apply()` for follow-up events and append them.
- `src/remora/core/reconciler.py` — Register default scaffold subscription in `reconcile_on_startup()`: subscribe all scaffold nodes to `ScaffoldRequestEvent` matching their `node_id`
- `src/remora/core/execution.py` — Pass `scaffold_context` to `_build_prompt()` when the triggering event is `ScaffoldRequestEvent`
- `src/remora/lsp/runner.py` — Pass `tags=("scaffold",)` on `AgentCompleteEvent` when the trigger was a `ScaffoldRequestEvent`
- Tests

**Acceptance:**
- When a stub node is discovered, `ScaffoldRequestEvent` is emitted
- A default subscription routes `ScaffoldRequestEvent` to the scaffold node's agent
- The agent receives scaffold context in its prompt
- On completion, `AgentCompleteEvent` includes `tags=("scaffold",)`

---

## Test Command

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py -q --timeout=30
```

Known pre-existing failures to ignore: `test_real_vllm_tool_calling`, `test_real_vllm_grail_tool_execution`, `test_event_store_append_and_replay`, `TestCLI::test_help_flag`

---

> **REMINDER: NO SUBAGENTS.** Never use the Task tool. Do all work directly.
