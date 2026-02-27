# Remora v0.4.1 Review Refactoring Guide

## Purpose
This guide is a task‑by‑task refactoring playbook for a junior developer to bring Remora into full alignment with the v0.4.0 refactor plan. It focuses on fixing gaps surfaced in `CODE_REVIEW.md` while preserving the v0.4 architecture described in `docs/plans/2026-02-26-remora-v040-refactor-design.md` and the refactor plan.

## Audience
- Junior developer with Python experience.
- Assumes limited context on Remora’s architecture.
- Every step includes explicit files, commands, and expected outcomes.

## Guardrails
- Do not introduce new features outside the v0.4.0 plan.
- Do not fix unrelated bugs or tests not in scope.
- Prefer minimal, surgical edits.
- Keep the architecture clean: core modules under `src/remora/`, services under `src/remora/indexer/` and `src/remora/dashboard/`.

## Prerequisites
- Python 3.12+ environment.
- `structured-agents==0.3.4`, `grail==3.0.0`, `cairn` installed.
- A working `remora.yaml` in repo root.
- Ability to run tests locally.

## Phase Summary
1) Prep & baseline checks
2) Config schema alignment
3) Event taxonomy + EventBus compliance
4) Bundle metadata + graph topology
5) Cairn workspace layer
6) Agent execution wiring
7) Context builder wiring
8) Dashboard wiring
9) Tool + bundle cleanup
10) Legacy module removal
11) Test realignment
12) Final validation

---

## Phase 1: Prep & Baseline Checks

**Goal**: Establish safe working state and understand current failures.

**Files to touch**: None.

**Steps**
1. Record current failing tests (don’t fix them yet).
2. Confirm current config and plan docs exist.

**Commands**
- `ls remora.yaml`
- `ls docs/plans/2026-02-26-remora-v040-refactor-design.md`
- `pytest tests/unit/test_event_bus.py -q` (expect failures)

**Expected Results**
- Baseline test failures captured for later comparison.

---

## Phase 2: Config Schema Alignment

**Goal**: Align config dataclasses and serialization with v0.4 plan. Fix CLI misuse of config overrides.

**Files to touch**
- `src/remora/config.py`
- `src/remora/cli.py`
- `remora.yaml` (if missing fields)

**Context**
The v0.4 plan requires `model_base_url` and `api_key` in config. Remora also needs `BundleMetadata` mappings keyed by bundle name. `serialize_config()` currently references fields that don’t exist in the dataclasses.

**Steps**
1. Inspect `RemoraConfig` and related dataclasses.
2. Add fields for:
   - `model_base_url`
   - `api_key`
   - `BundleMetadata` mapping (e.g., `bundle_metadata: dict[str, BundleMetadata]`).
3. Update `serialize_config()` to only reference real fields.
4. Update `load_config()` to accept an optional overrides dict (or remove overrides usage in CLI).
5. Update `cli.py` so it either:
   - Calls `load_config(config_path)` with no overrides, or
   - Calls `load_config(config_path, overrides)` if you add overrides support.

**Commands**
- `pytest tests/test_config.py -q`

**Expected Results**
- No `AttributeError` in config serialization.
- CLI no longer raises `TypeError` when loading config.

---

## Phase 3: Event Taxonomy + EventBus Compliance

**Goal**: Replace stub kernel events with structured-agents event classes and ensure EventBus acts as a proper observer.

**Files to touch**
- `src/remora/events.py`
- `src/remora/event_bus.py`

**Context**
`events.py` defines stub versions of kernel events instead of importing them from `structured_agents.events`. This breaks compatibility with structured-agents kernels. The plan expects kernel events to be re‑emitted via the EventBus.

**Steps**
1. Replace stub kernel event class definitions with imports from `structured_agents.events`.
2. Ensure event naming matches structured‑agents (`TurnCompleteEvent`, etc.).
3. Confirm `EventBus.emit()` matches `structured_agents.events.observer.Observer` signature.
4. Update `__all__` exports accordingly.

**Commands**
- `pytest tests/unit/test_event_bus.py -q`

**Expected Results**
- EventBus is compatible with structured-agents observer.
- Kernel events re‑emitted without class conflicts.

---

## Phase 4: Bundle Metadata + Graph Topology

**Goal**: Introduce Remora’s `BundleMetadata` mapping and use it in `graph.py` to map node types → bundles and order by priority.

**Files to touch**
- `src/remora/config.py`
- `src/remora/graph.py`

**Context**
The plan forbids Remora‑specific fields inside `bundle.yaml`. Instead, Remora must maintain a separate `BundleMetadata` mapping keyed by bundle name. Graph builder must use this mapping to select bundles, apply priority, and track context requirements.

**Steps**
1. Define `BundleMetadata` dataclass (bundle name, node types handled, priority, requires_context).
2. Add a `bundle_metadata: dict[str, BundleMetadata]` field to `RemoraConfig`.
3. Update `build_graph()` to accept `BundleMetadata` mapping instead of raw `node_type → path` mapping.
4. Build `bundle_path` for a node by:
   - Finding bundles whose metadata includes the node’s type.
   - Selecting the highest priority match if multiple.
5. Preserve pure graph behavior: no side effects, no execution state.

**Commands**
- `pytest tests/unit/test_agent_graph.py -q`

**Expected Results**
- Graph nodes resolve to bundles via metadata.
- Graph remains deterministic and pure.

---

## Phase 5: Cairn Workspace Layer

**Goal**: Implement workspace creation, snapshot, and restore so executor and checkpoints can run.

**Files to touch**
- `src/remora/workspace.py`
- `src/remora/checkpoint.py`

**Context**
The workspace layer is currently a stub. Cairn should be the primary workspace provider, and checkpoints should snapshot Cairn workspace state.

**Steps**
1. Implement `create_workspace()` and `create_shared_workspace()` using Cairn.
2. Implement `snapshot_workspace()` and `restore_workspace()` wrappers that call Cairn snapshot/restore.
3. Update `CheckpointManager` to use the workspace helpers if needed.
4. Remove legacy workspace placeholder classes if they are no longer referenced.

**Commands**
- `pytest tests/unit/test_workspace.py -q`
- `pytest tests/unit/test_workspace_ipc.py -q`

**Expected Results**
- Workspace helpers create and snapshot Cairn workspaces.
- Checkpoint restore works end‑to‑end.

---

## Phase 6: Agent Execution Wiring

**Goal**: Execute agents through structured‑agents with the proper env vars, data providers, and result handlers.

**Files to touch**
- `src/remora/executor.py`
- `src/remora/workspace.py`

**Context**
`execute_agent()` is currently a stub. The plan requires using `Agent.from_bundle()` plus a Remora‑aware Grail tool loader and CairnDataProvider/ResultHandler integration.

**Steps**
1. Set `STRUCTURED_AGENTS_BASE_URL` + `STRUCTURED_AGENTS_API_KEY` from config before invoking the agent.
2. Load agent via `structured_agents.agent.Agent.from_bundle()`.
3. Inject EventBus as the observer.
4. Use `CairnDataProvider` to populate Grail `files` for tools.
5. Implement or integrate a Remora tool loader that instantiates Grail scripts once per bundle.
6. Run the agent and capture results.
7. Pass results to `CairnResultHandler` and return a `ResultSummary` for downstream use.

**Commands**
- `pytest tests/integration/test_agent_node_workflow.py -q`

**Expected Results**
- Agents execute via structured‑agents and produce usable results.
- EventBus captures kernel + agent events.

---

## Phase 7: Context Builder Wiring

**Goal**: Ensure `ContextBuilder` receives EventBus events and produces short/long‑track context.

**Files to touch**
- `src/remora/context.py`
- `src/remora/executor.py`

**Context**
The plan expects ContextBuilder to aggregate short‑track and optionally pull long‑track knowledge. Currently, it is not wired into executor flow.

**Steps**
1. Ensure executor subscribes ContextBuilder to EventBus events (ToolResult, AgentComplete).
2. Ensure agent prompts include context sections built by ContextBuilder.
3. Make sure ResultSummary feeds into knowledge accumulation.

**Commands**
- `pytest tests/test_context_manager.py -q`

**Expected Results**
- ContextBuilder produces prompt sections with recent actions and knowledge.

---

## Phase 8: Dashboard Wiring

**Goal**: Make dashboard respond to EventBus events and execute graphs correctly.

**Files to touch**
- `src/remora/dashboard/app.py`
- `src/remora/dashboard/state.py`

**Context**
The current dashboard does not record events or invoke the executor correctly.

**Steps**
1. In the EventBus stream loop, call `DashboardState.record(event)` for each event.
2. Ensure `_execute_graph()` passes a `workspace_config` into `GraphExecutor.run()`.
3. Ensure `_trigger_graph()` builds bundle mapping using `BundleMetadata` or proper node type mapping.

**Commands**
- `pytest tests/test_frontend_routes.py -q`

**Expected Results**
- SSE updates reflect new events.
- Graph execution starts from dashboard.

---

## Phase 9: Tool + Bundle Cleanup

**Goal**: Remove legacy tools and enforce Input‑only tools with `ask_user` as the only external.

**Files to touch**
- `agents/*/bundle.yaml`
- `agents/*/tools/*.pym`

**Context**
The plan removes local I/O externals (`read_file`, `run_tests`, `ruff_config`) and replaces them with data‑provider‑supplied files. Only `ask_user` remains external.

**Steps**
1. Remove tool references in bundle.yaml for deprecated tools.
2. Delete legacy `.pym` tool scripts that violate the Input‑only contract.
3. Ensure any needed tool data is provided through `files` dict from CairnDataProvider.

**Commands**
- `pytest tests/test_pym_validation.py -q`
- `pytest tests/test_tool_script_snapshots.py -q`

**Expected Results**
- All remaining tools are Input‑only and validate in tests.

---

## Phase 10: Legacy Module Removal

**Goal**: Remove deprecated modules and exports so only v0.4 surface remains.

**Files to touch**
- `src/remora/__init__.py`
- Remove `src/remora/hub/`, `src/remora/frontend/`, `src/remora/interactive/`
- Remove `src/remora/agent_graph.py`, `src/remora/agent_state.py`, `src/remora/backend.py`, `src/remora/constants.py`

**Context**
These modules are explicitly removed in the v0.4 plan to prevent legacy usage.

**Steps**
1. Remove legacy exports from `__init__.py`.
2. Delete legacy modules/directories.
3. Update imports in any remaining code.

**Commands**
- `rg "hub" src/remora`
- `rg "agent_graph|agent_state" src/remora`

**Expected Results**
- No remaining imports to legacy modules.

---

## Phase 11: Test Realignment

**Goal**: Add v0.4 tests and sunset v0.3 Hub tests.

**Files to touch**
- `tests/unit/test_event_bus.py`
- `tests/unit/test_agent_graph.py`
- New tests for executor/workspace/context if missing
- Remove or quarantine `tests/hub/*`

**Context**
Legacy tests currently hold the repo back from removing deprecated modules. Replace with v0.4 aligned tests.

**Steps**
1. Add v0.4 coverage for executor + workspace + context builder.
2. Remove legacy hub tests if no longer relevant.
3. Update CI/test scripts if needed.

**Commands**
- `pytest tests/unit -q`

**Expected Results**
- Unit suite passes using v0.4 architecture only.

---

## Phase 12: Final Validation

**Goal**: Ensure refactor is complete and stable.

**Commands**
- `pytest -q`

**Expected Results**
- All tests pass.
- No legacy modules remaining.
- Remora core matches v0.4.0 plan.

---

## Deliverables
- All phases complete with passing tests.
- Updated `remora.yaml` with new config fields.
- Clean v0.4 code surface with no legacy imports.
