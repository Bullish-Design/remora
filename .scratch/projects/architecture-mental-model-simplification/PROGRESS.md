# PROGRESS

## Status
- [x] Create new project scaffold for architecture cognitive-load reduction
- [x] Copy architecture diagram artifacts into project-local `diagrams/`
- [x] Capture strategy and phased plan for next session
- [x] Revised plan with detailed junior-developer-ready workstreams (W0–W7)
- [x] W0: Diagnostic — identify cycles and update baseline (COMPLETE — see findings below)
- [x] W1: Enforce Tach policy in tach.toml + CI gate (COMPLETE — 2026-03-07)
- [x] W2: Fix runner.agent_runner → lsp.models (move RewriteProposal to runner.models) (COMPLETE — 2026-03-07)
- [x] W3: Fix events.events → code.discovery (move from_cst_node to discovery.node_to_event) (COMPLETE — 2026-03-07)
- [x] W4: Decompose core.events.events into 4 bounded modules (COMPLETE — 2026-03-07)
- [x] W5: Break LSP barrel/server/handlers cycle — ALREADY DONE (no lsp.handlers → lsp barrel edges found)
- [x] W6: Thin orchestration hotspots (lsp.server, agents.execution, service.api) (COMPLETE — 2026-03-07)
- [x] W7: Barrel import audit + CI SLO gates (COMPLETE — 2026-03-07)

## OLD Baseline Snapshot (stale — from prior session graph, now superseded)
- These nodes used flat compatibility-shim paths (e.g. remora.core.agent_context) that have
  since been removed. The numbers below are from the prior architecture_refactor session.
- Modules: 112 | Edges: 296 | SCCs: 2

## CURRENT Baseline Snapshot (from W0 — 2026-03-07)
- Modules: 106 | Edges: 305 | Cycles: 0
- tach check: PASSES (all modules validated)
- Top hotspot degrees:
  - `remora.core.events.events`: degree 34 (in 33 / out 1)  ← PRIMARY TARGET
  - `remora.core` (barrel):       degree 19 (in  0 / out 19)
  - `remora.lsp.server`:          degree 17 (in  2 / out 15)
  - `remora.core.store.event_store`: degree 16 (in 10 / out 6)
  - `remora.service.api`:         degree 16 (in  3 / out 13)
  - `remora.core.agents.execution`: degree 16 (in 3 / out 13)
  - `remora.runner.agent_runner`: degree 16 (in  4 / out 12)
  - `remora.utils`:               degree 16 (in 12 / out  4)  ← expected for utility leaf
  - `remora.core.code.discovery`: degree 15 (in 13 / out  2)
  - `remora.cli.main`:            degree 15 (in  2 / out 13)

## W0 Findings

### Cycles
**Both baseline cycles are ALREADY FIXED** in the current codebase.

The baseline (old) graph had:
- Cycle 1 (9 modules): remora.lsp ↔ remora.lsp.server ↔ remora.lsp.handlers.* — RESOLVED
  (handlers no longer import the lsp barrel; they use remora.lsp.protocols instead)
- Cycle 2 (2 modules): remora.runner ↔ remora.runner.agent_runner — RESOLVED
  (agent_runner no longer imports the runner barrel)

The old baseline used flat compatibility shim modules (remora.core.agent_context, etc.)
that were removed during the architecture_refactor project. This explains the node count
difference (112 → 106).

### W5 Status
W5 (Break LSP barrel/handler cycle) is complete — no work needed. Can be skipped.

### Remaining Violations (confirmed by graph analysis)
Two planned violations still present:
1. `remora.runner.agent_runner → remora.lsp.models` — addressed by W2
2. `remora.core.events.events → remora.core.code.discovery` — addressed by W3

No core → adapter violations found (core is clean with respect to lsp/service/ui/companion/cli).

### Plan Impact
- W5 is DONE — remove from execution order
- Updated baseline numbers above replace the stale ones
- `core.events.events` in-degree is now 33 (worse than old baseline of 29 — codebase has grown)
- Priority of W4 (event decomposition) is confirmed as highest-value remaining workstream

## W1 Findings (2026-03-07)
- Updated `tach.toml` to document strict layering intent:
  - `remora.core` explicitly documented as not allowed to depend on adapter modules.
  - `remora.runner.agent_runner` now carries an explicit temporary violation comment for
    `remora.lsp.models` (to be removed in W2).
  - `remora.core.events.events` now carries an explicit temporary violation comment for
    `remora.core.code.discovery` (to be removed in W3).
- Added architecture gate to CI:
  - `.github/workflows/test.yml` now runs `tach check`.
- Added local task runner entry (user requested `just`, not `make`):
  - New `justfile` recipe: `check-arch` → `devenv shell -- tach check`.
- Baseline verification commands run:
  - `devenv shell -- uv sync --extra dev`
  - `devenv shell -- tach check`
  - Result: `✅ All modules validated!`

## W2 Findings (2026-03-07)
- Created `src/remora/runner/models.py` and moved:
  - `RewriteProposal`
  - `generate_id`
- Updated `src/remora/runner/agent_runner.py` to import from `remora.runner.models`.
- Reduced `src/remora/lsp/models.py` to a compatibility re-export:
  - `from remora.runner.models import RewriteProposal, generate_id`
  - Removed all `Lsp*` alias re-exports.
- Updated `src/remora/lsp/__init__.py` exports:
  - Removed `LspAgent*`/`LspRewrite*` exports.
  - Kept `RewriteProposal`, `generate_id`, `RemoraDB`, `LazyGraph`, `RemoraLanguageServer`.
- Updated Tach module policy in `tach.toml`:
  - `remora.runner.agent_runner` no longer depends on `remora.lsp.models`.
  - Added `remora.runner.models` with `depends_on = []`.
  - `remora.lsp.models` now depends on `remora.runner.models`.
- Updated test import sites that referenced removed aliases:
  - `tests/unit/test_lsp_models.py`
  - `tests/unit/test_unified_events.py`
- Acceptance checks:
  - `grep -r "from remora.lsp.models import" src/remora/runner/` → no results.
  - `devenv shell -- tach check` → pass.
  - `devenv shell -- python -c "from remora.runner.agent_runner import AgentRunner"` → pass.
- Test runs:
  - `devenv shell -- pytest tests/unit/test_lsp_models.py tests/unit/test_unified_events.py -q` → pass.
  - `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` → pass (warnings only).

## W3 Findings (2026-03-07)
- Added discovery-owned factory:
  - `src/remora/core/code/discovery.py`: `node_to_event(node: CSTNode) -> NodeDiscoveredEvent`
  - Exported via `__all__`.
- Updated runtime call sites to use `node_to_event()`:
  - `src/remora/lsp/handlers/documents.py`
  - `src/remora/lsp/server.py` (`_do_reparse`)
  - `src/remora/lsp/background_scanner.py`
- Removed event-layer coupling back to discovery:
  - Deleted `NodeDiscoveredEvent.from_cst_node()` from `src/remora/core/events/events.py`.
  - Removed `TYPE_CHECKING` import of `CSTNode` from `events.py`.
  - `events.py` no longer imports from `remora.core.code.discovery`.
- Updated tests for the new factory location:
  - `tests/test_events.py` now validates `node_to_event(...)`.
- Updated Tach policy:
  - `remora.core.events.events` now `depends_on = []`.
  - `remora.core.code.discovery` now allows `remora.core.events.events` (for `node_to_event`).
  - `remora.lsp.background_scanner` now allows `remora.core.code.discovery`.
- Acceptance checks:
  - `grep -n "from remora.core.code" src/remora/core/events/events.py` → no results.
  - `grep -n "from_cst_node" src/remora/core/events/events.py` → no results.
  - `grep -n "from_cst_node" src tests` → no results.
  - `devenv shell -- tach check` → pass.
- Test runs:
  - `devenv shell -- pytest tests/test_events.py tests/unit/test_lsp_event_completeness.py tests/unit/test_lsp_background_scan_manifest.py -q` → pass.

## W4 Findings (2026-03-07)
- Added bounded event modules under `src/remora/core/events/`:
  - `agent_events.py`
  - `interaction_events.py`
  - `code_events.py`
  - `kernel_events.py`
- Rewrote `src/remora/core/events/events.py` into a thin compatibility barrel with re-exports
  and `CoreEvent`.
- Updated `src/remora/core/events/__init__.py` to re-export from bounded modules and define
  `CoreEvent` directly.
- Migrated production imports from barrel to bounded modules across `src/`:
  - `agent_events` for agent/HITL/proposal events and `_FrozenEvent`
  - `interaction_events` for message/file/cursor/trigger events
  - `code_events` for node lifecycle events
  - `kernel_events` for structured-agents kernel event re-exports
- Updated `src/remora/core/code/discovery.py` to import `NodeDiscoveredEvent` from
  `remora.core.events.code_events` in `node_to_event()`.
- Updated architecture config using `devenv shell -- tach sync` after the import migration.
- TDD:
  - Added `tests/unit/test_event_module_split.py` (fail-first then pass) to assert bounded
    modules are independently importable.
- Acceptance checks:
  - `grep -rl "from remora.core.events.events import" src/` → no results.
  - `devenv shell -- tach check` → pass.
- Test runs:
  - `devenv shell -- pytest tests/unit/test_event_module_split.py tests/unit/test_unified_events.py tests/unit/test_event_bus.py tests/companion/test_claim_checker.py -q` → pass.
  - `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` → pass (warnings only).

## W6 Findings (2026-03-07)
- Added focused orchestration helpers and thinned hotspot entrypoints:
  - `src/remora/lsp/server_setup.py`
  - `src/remora/lsp/runtime_ops.py`
  - `src/remora/lsp/tooling.py`
  - `src/remora/core/agents/turn_context.py`
  - `src/remora/runner/turn_logic.py`
- `remora.lsp.server` now delegates handler registration/runtime operations/tool discovery and no longer owns handler registration logic.
- `remora.core.agents.execution` delegates per-turn assembly to `build_turn_context(...)`.
- `remora.service.api` is route/wiring focused and delegates runtime/bootstrap/render helpers to `service.handlers`.
- Hotspot out-degree verification (from `/tmp/remora_arch.dot` SCC/degree pass):
  - `remora.lsp.server`: out=7
  - `remora.core.agents.execution`: out=2
  - `remora.service.api`: out=7
  - `remora.runner.agent_runner`: out=7

## W7 Findings (2026-03-07)
- Barrel import audit complete for production code:
  - `rg -n "from remora.core import|from remora.lsp import|from remora.runner import" src/remora -g '!**/__init__.py'` → no results.
- Added architecture SLO gate:
  - New `scripts/check_arch_slo.py`
  - CI updated: `.github/workflows/test.yml` runs SLO script.
  - `justfile` recipes:
    - `check-arch`
    - `check-arch-slo`
    - `check`
- Generated architecture graph artifact:
  - `docs/architecture.mmd` via `devenv shell -- tach show --mermaid -o docs/architecture.mmd`

## Post-W7 Cleanup (No Compatibility Shims)
- Removed compatibility surfaces to align with clean-architecture direction:
  - Deleted `src/remora/lsp/models.py`
  - Deleted `src/remora/core/events/events.py`
  - Removed `register_handlers` compatibility shim from `src/remora/lsp/server.py`
- Updated production imports to canonical modules:
  - Rewrite proposal model imports now come from `remora.runner.models`.
  - Event imports resolve through bounded event modules/package exports.
- Refactored tests to current architecture (no legacy module paths).

## Final Verification (2026-03-07)
- `devenv shell -- uv sync --extra dev` → pass
- `devenv shell -- tach sync` → pass
- `devenv shell -- tach check` → pass
- `devenv shell -- python scripts/check_arch_slo.py` → `Architecture SLOs: OK`
- `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` → pass (warnings only)
- Cycle verification on generated DOT graph (`/tmp/remora_arch.dot`) → `cycles=0`
