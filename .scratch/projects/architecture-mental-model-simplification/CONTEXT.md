# CONTEXT

Updated on 2026-03-07 after completing W6 + W7 and final cleanup.

## Current state
- All workstreams W0–W7 are complete.
- Compatibility shims were intentionally removed:
  - `src/remora/lsp/models.py` deleted
  - `src/remora/core/events/events.py` deleted
  - `register_handlers` shim removed from `src/remora/lsp/server.py`
- Orchestration hotspot modules are thinned and below out-degree target:
  - `remora.lsp.server`: out=7
  - `remora.core.agents.execution`: out=2
  - `remora.service.api`: out=7
  - `remora.runner.agent_runner`: out=7
- Architecture wiring is complete:
  - `tach.toml` synced with explicit entries for newly introduced modules.
  - `scripts/check_arch_slo.py` enforced in CI and exposed through `just` recipes.
  - `docs/architecture.mmd` regenerated from current Tach graph.

## Verification snapshot
- `devenv shell -- uv sync --extra dev` ✅
- `devenv shell -- tach sync` ✅
- `devenv shell -- tach check` ✅
- `devenv shell -- python scripts/check_arch_slo.py` ✅ (`Architecture SLOs: OK`)
- `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` ✅ (warnings only)
- DOT SCC cycle analysis on `/tmp/remora_arch.dot` reports `cycles=0`.

## Immediate next step when resuming
- No implementation work remains for this plan. Next action is commit/push and open follow-up work only if new architecture constraints are requested.
