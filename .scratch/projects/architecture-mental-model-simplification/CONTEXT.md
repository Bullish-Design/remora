# CONTEXT

Updated on 2026-03-07 after completing W2.

## Current state
- W0, W1, and W2 are complete.
- `tach.toml` now documents one remaining temporary violation:
  - `remora.core.events.events -> remora.core.code.discovery` (to remove in W3)
- CI architecture gate added: `.github/workflows/test.yml` runs `tach check`.
- Local command added via `justfile`: `just check-arch`.
- W2 verification:
  - `devenv shell -- tach check`
  - `devenv shell -- python -c "from remora.runner.agent_runner import AgentRunner"`
  - `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`
  - Result: pass (`All modules validated`).

## Immediate next step when resuming
Start W3 in `PLAN.md`: move `NodeDiscoveredEvent.from_cst_node` conversion into `remora.core.code.discovery.node_to_event`, remove `core.events.events -> core.code.discovery`, and then update `tach.toml` so `remora.core.events.events` has no internal deps.
