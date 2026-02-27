# Remora v0.4.1 Implementation Plan

Note: The current refactor replaced `src/remora/dashboard/` with `src/remora/service/` and `src/remora/ui/`. Treat dashboard references below as historical.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement every phase from `V041_REVIEW_REFACTORING_GUIDE.md` so Remora matches the v0.4.0 architecture with the v0.4.1 cleanup.

**Architecture:** Follow a phase-driven refactor that wires config through EventBus, graph, workspace, executor, context, dashboard, and tests while keeping each module pure and aligned with structured-agents, Grail, and Cairn contracts.

**Tech Stack:** Python 3.12+, `structured-agents==0.3.4`, `grail==3.0.0`, `cairn`, `pytest` for validation.

---

### Task 1: Phase 1 & Config schema (config.py + cli.py)

**Files:**
- Modify: `src/remora/config.py`
- Modify: `src/remora/cli.py`
- Ensure: `remora.yaml` includes new fields (reference root file)
- Test: `tests/test_config.py`

**Step 1: Expand tests to cover config serialization**

```python
# tests/test_config.py line 10
from remora.config import RemoraConfig

def test_config_serialization_includes_auth_fields():
    cfg = RemoraConfig(model_base_url="https://model", api_key="key", bundle_metadata={})
    serialized = serialize_config(cfg)
    assert serialized["model_base_url"] == "https://model"
    assert serialized["api_key"] == "key"
```

**Step 2: Run config test to confirm failure**

```bash
pytest tests/test_config.py -q
```

Expected: FAIL because `RemoraConfig` lacks the fields or `serialize_config()` references missing attributes.

**Step 3: Implement config changes**
- Add `model_base_url: str`, `api_key: str`, and `bundle_metadata: dict[str, BundleMetadata]` to `RemoraConfig` dataclass.
- Define `BundleMetadata` dataclass with `name`, `node_types`, `priority`, `requires_context`.
- Update `serialize_config()` to build dict from actual fields.
- Update `load_config()` to accept optional overrides (or remove override usage) and make CLI call `load_config(config_path)`.

**Step 4: Re-run config test**

```bash
pytest tests/test_config.py -q
```

Expected: PASS with new fields present.

**Step 5: Record progress**

```bash
git add src/remora/config.py src/remora/cli.py remora.yaml tests/test_config.py docs/plans/2026-02-26-remora-v041-implementation-plan.md
git commit -m "refactor: align config schema"
```

### Task 2: Event taxonomy + EventBus compliance

**Files:**
- Modify: `src/remora/events.py`
- Modify: `src/remora/event_bus.py`
- Test: `tests/unit/test_event_bus.py`

**Step 1: Extend event bus tests**

Add assertions that `EventBus.emit()` accepts structured-agents event classes and a subscriber can observe them.

**Step 2: Run event bus tests**

```bash
pytest tests/unit/test_event_bus.py -q
```

Expected: FAIL because stub classes and observer mismatch.

**Step 3: Implement event updates**
- Import `structured_agents.events` classes (e.g., `TurnCompleteEvent`, `ToolResultEvent`).
- Remove stub classes from `events.py`, re-export imported names via `__all__`.
- Update `EventBus.emit()` signature to match `observer.Observer.on_event(self, event)` and ensure `subscribe`/`stream` return async iterables.

**Step 4: Re-run event bus tests**

```bash
pytest tests/unit/test_event_bus.py -q
```

Expected: PASS with structured-agents compatibility.

**Step 5: Commit**

```bash
git add src/remora/events.py src/remora/event_bus.py tests/unit/test_event_bus.py
git commit -m "refactor: wire structured-agents events"
```

### Task 3: Bundle metadata + graph topology

**Files:**
- Modify: `src/remora/graph.py`
- Modify: `src/remora/config.py`
- Test: `tests/unit/test_agent_graph.py`

**Step 1: Add graph tests confirming metadata selection**

Insert tests that `build_graph()` picks bundles via `bundle_metadata` (mock metadata, ensure priority is used).

**Step 2: Run agent graph tests**

```bash
pytest tests/unit/test_agent_graph.py -q
```

Expected: FAIL until builder uses metadata mapping.

**Step 3: Implement metadata-driven graph builder**
- Accept `bundle_metadata: dict[str, BundleMetadata]` in `build_graph()`.
- For each node, find metadata entries whose `node_types` include the node’s type, select highest `priority`, and return bundle path accordingly.
- Keep graph builder pure (no workspace interaction).

**Step 4: Re-run graph tests**

```bash
pytest tests/unit/test_agent_graph.py -q
```

Expected: PASS with deterministic mapping.

**Step 5: Commit**

```bash
git add src/remora/graph.py src/remora/config.py tests/unit/test_agent_graph.py
git commit -m "refactor: add bundle metadata graph"
```

### Task 4: Workspace & Cairn integration

**Files:**
- Modify: `src/remora/workspace.py`
- Modify: `src/remora/checkpoint.py`
- Test: `tests/unit/test_workspace.py`, `tests/unit/test_workspace_ipc.py`

**Step 1: Add workspace tests for Cairn creation**

Add tests that call `create_workspace()`/`snapshot_workspace()` and expect Cairn clients invoked.

**Step 2: Run workspace tests**

```bash
pytest tests/unit/test_workspace.py -q
pytest tests/unit/test_workspace_ipc.py -q
```

Expected: FAIL while functions are placeholders.

**Step 3: Implement Cairn helpers**
- Use `cairn` APIs to implement `create_workspace()` and `create_shared_workspace()`.
- Implement `snapshot_workspace()`/`restore_workspace()` wrappers over Cairn snapshot logic.
- Update `CheckpointManager` to leverage these helpers and remove legacy placeholders.

**Step 4: Re-run workspace tests**

```bash
pytest tests/unit/test_workspace.py -q
pytest tests/unit/test_workspace_ipc.py -q
```

Expected: PASS once Cairn-backed helpers work.

**Step 5: Commit**

```bash
git add src/remora/workspace.py src/remora/checkpoint.py tests/unit/test_workspace.py tests/unit/test_workspace_ipc.py
git commit -m "refactor: implement cairn workspace helpers"
```

### Task 5: Executor, context, dashboard wiring

**Files:**
- Modify: `src/remora/executor.py`
- Modify: `src/remora/context.py`
- Modify: `src/remora/dashboard/app.py`
- Modify: `src/remora/dashboard/state.py`
- Tests: `tests/integration/test_agent_node_workflow.py`, `tests/test_context_manager.py`, `tests/test_frontend_routes.py`

**Step 1: Add integration tests covering execution wiring**

Ensure tests assert agents run via structured-agents with EventBus observer and context builder observes events.

**Step 2: Run all executor/context/dashboard tests**

```bash
pytest tests/integration/test_agent_node_workflow.py -q
pytest tests/test_context_manager.py -q
pytest tests/test_frontend_routes.py -q
```

Expected: FAIL until wiring is complete.

**Step 3: Implement execution & context wiring**
- In `executor.py`, set `STRUCTURED_AGENTS_BASE_URL`/`STRUCTURED_AGENTS_API_KEY` from config, load agent via `Agent.from_bundle()`, attach EventBus as observer, use `CairnDataProvider`/`CairnResultHandler`, and return `ResultSummary`.
- Ensure ContextBuilder subscribes to EventBus events and can supply context sections when running agents.
- Dashboard app/state listens to EventBus events and passes metadata-driven graphs to executor, always supplying `workspace_config` to `GraphExecutor.run()`.

**Step 4: Re-run tests**

Repeat the same `pytest` commands.

**Step 5: Commit**

```bash
git add src/remora/executor.py src/remora/context.py src/remora/dashboard/app.py src/remora/dashboard/state.py tests/integration/test_agent_node_workflow.py tests/test_context_manager.py tests/test_frontend_routes.py
git commit -m "refactor: wire executor context dashboard"
```

### Task 6: Cleanup, legacy removal, tests

**Files:**
- Modify: `src/remora/__init__.py`
- Remove: legacy directories `src/remora/hub`, `src/remora/frontend`, `src/remora/interactive`, old modules listed in guide.
- Modify: tests (remove `tests/hub/*`, align new tests).
- Tests: `pytest tests/unit -q`, `pytest tests/test_pym_validation.py -q`, `pytest tests/test_tool_script_snapshots.py -q`

**Step 1: Write tests for tool/bundle cleanup**

Ensure remaining tools are input-only via the validation tests mentioned.

**Step 2: Run cleanup tests**

```bash
pytest tests/unit -q
pytest tests/test_pym_validation.py -q
pytest tests/test_tool_script_snapshots.py -q
```

Expected: FAIL while legacy modules/tools still exist.

**Step 3: Remove legacy files & enforce tool contracts**
- Delete legacy modules/directories and update `__init__.py` exports accordingly.
- Update bundles to remove deprecated tools and rely only on `ask_user` or files from `CairnDataProvider`.
- Add/adjust tests covering executor/workspace/context to ensure coverage after cleanup.

**Step 4: Re-run tests**

Repeat Step 2 commands.

**Step 5: Commit**

```bash
git rm -r src/remora/hub src/remora/frontend src/remora/interactive src/remora/agent_graph.py src/remora/agent_state.py src/remora/backend.py src/remora/constants.py
# re-add modified files if needed
git add src/remora/__init__.py tests tests/unit tests/test_pym_validation.py tests/test_tool_script_snapshots.py
git commit -m "refactor: retire legacy modules"
```

### Task 7: Final validation

**Files:**
- No direct modifications; run entire test suite.

**Step 1: Run full pytest suite**

```bash
pytest -q
```

Expected: PASS once refactor is complete.

**Step 2: Record baseline & summary**

Note test outputs for comparison with Phase 1.

**Step 3: (Optional) Prepare release notes or README updates referencing v0.4.1 clean surface.**

**Step 4: Celebrate progress.**

**Step 5: Commit if there are supporting docs or updates.**

---

Plan complete and saved to `docs/plans/2026-02-26-remora-v041-implementation-plan.md`. Two execution options:

1. Subagent-Driven (this session) - I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Parallel Session (separate) - Open a new session with executing-plans, batch execution with checkpoints.

Which approach?
