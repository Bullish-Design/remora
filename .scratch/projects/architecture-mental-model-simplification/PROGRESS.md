# PROGRESS

## Status
- [x] Create new project scaffold for architecture cognitive-load reduction
- [x] Copy architecture diagram artifacts into project-local `diagrams/`
- [x] Capture strategy and phased plan for next session
- [ ] Implement Tach rule constraints (W1)
- [ ] Decouple LSP/runner model boundary (W2)
- [ ] Split `core.events.events` into bounded modules (W3)
- [ ] Decompose orchestration hotspots (W4)
- [ ] Barrel import cleanup + CI SLO gates (W5/W6)

## Baseline Snapshot (from current graph analysis)
- Modules: 112
- Edges: 296
- Module SCCs >1: 2
- Top hotspot degrees (full graph):
  - `remora.core.events.events`: degree 30 (in 29 / out 1)
  - `remora.lsp.server`: degree 17 (in 2 / out 15)
  - `remora.core.agents.execution`: degree 17 (in 4 / out 13)
  - `remora.service.api`: degree 16 (in 3 / out 13)
  - `remora.runner.agent_runner`: degree 14 (in 4 / out 10)
