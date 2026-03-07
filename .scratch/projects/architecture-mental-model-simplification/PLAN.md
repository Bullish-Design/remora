# PLAN

## Objective
Reduce architectural cognitive load by shrinking coupling hotspots and enforcing a small dependency model that is easy to reason about.

## Target Mental Model
1. `core`: domain/state/event model
2. `runner`: application orchestration/use-cases
3. `adapters`: `lsp`, `service`, `cli`, `companion`, `ui`
4. `utils`: leaf helpers only

Rule: dependencies flow inward only; `core` must never depend on adapters.

## Workstreams

### W1: Enforce dependency policy in `tach.toml`
- Define explicit layer constraints and forbidden edges.
- Add checks for:
  - no `core -> lsp|service|cli|companion|ui|extensions`
  - no `runner -> lsp`
  - no internal imports from package barrels (`remora.core`, `remora.lsp`, `remora.runner`) where avoidable
- Add CI gate and fail on violations.

### W2: Break remaining package-level loop pressure (`lsp <-> runner`)
- Move shared DTO/protocol concepts from LSP-facing model types into neutral protocol module (`runner.protocols` or `core.protocols`).
- Keep LSP wire models local to `remora.lsp` and map at boundary.

### W3: Split event mega-hub
- Decompose `remora.core.events.events` into bounded event modules (candidate: `agent_events`, `code_events`, `interaction_events`, `system_events`).
- Update imports to consume narrow event modules instead of universal catch-all.

### W4: Decompose orchestrator hotspots
- Thin orchestration modules:
  - `remora.lsp.server`
  - `remora.core.agents.execution`
  - `remora.service.api`
  - `remora.runner.agent_runner`
- Extract use-case services and keep entry modules focused on wiring/composition.

### W5: Reduce barrel coupling and import fan-out
- Prevent internal code from importing top-level barrel modules (`remora.core`, `remora.lsp`, `remora.runner`).
- Prefer concrete submodule imports.

### W6: Architecture SLOs + observability
- Add architecture SLO thresholds:
  - max module out-degree <= 8
  - max module in-degree <= 12
- Produce package-level and strict mental-model graphs in CI artifacts.
- Track hotspot trend over time.

## Execution Order
1. W1 policy/rules first (guardrails)
2. W2 LSP/runner boundary decoupling
3. W3 event decomposition
4. W4 orchestrator decomposition
5. W5 import hygiene pass
6. W6 CI/reporting polish

## Acceptance Criteria
- No forbidden dependency edges by policy.
- `runner` does not depend on `lsp` modules.
- Event model no longer concentrated in one mega-hub module.
- Top hotspot degrees materially reduced from baseline.
- Diagram artifacts clearly show simpler structure at both package and module levels.

## Critical Reminder
NO SUBAGENTS. Do all work directly.
