# CONTEXT

Created on 2026-03-07 after reviewing Tach dependency graphs with the user.

User requested a follow-up project that packages the architecture simplification ideas and all diagram artifacts for continuation in a future session.

## What was prepared
- New project directory:
  - `.scratch/projects/architecture-mental-model-simplification/`
- Standard project files populated (`PLAN`, `ASSUMPTIONS`, `PROGRESS`, `CONTEXT`, `DECISIONS`, `ISSUES`)
- Diagram corpus copied into:
  - `diagrams/current_root/`
  - `diagrams/architecture_refactor/`
  - `diagrams/graph_views/`

## Key architectural direction for next session
- Enforce strict layer boundaries in Tach first.
- Remove residual `lsp <-> runner` conceptual coupling.
- Decompose event and orchestrator hotspots.
- Gate complexity via architecture SLO checks in CI.

## Immediate next step when resuming
Start W1 in `PLAN.md`: codify and enforce dependency constraints in `tach.toml` and run Tach checks to establish a failing/passing baseline.
