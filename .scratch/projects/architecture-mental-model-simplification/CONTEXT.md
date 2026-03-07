# CONTEXT

Updated on 2026-03-07 after completing W3.

## Current state
- W0, W1, W2, and W3 are complete.
- `remora.core.events.events -> remora.core.code.discovery` has been removed.
- CI architecture gate added: `.github/workflows/test.yml` runs `tach check`.
- Local command added via `justfile`: `just check-arch`.
- W3 verification:
  - `devenv shell -- tach check`
  - `devenv shell -- pytest tests/test_events.py tests/unit/test_lsp_event_completeness.py tests/unit/test_lsp_background_scan_manifest.py -q`
  - Result: pass (`All modules validated`).

## Immediate next step when resuming
Start W4 in `PLAN.md`: split `src/remora/core/events/events.py` into bounded event modules (`agent_events`, `interaction_events`, `code_events`, `kernel_events`) and keep `events.py` as a thin compatibility re-export barrel.
