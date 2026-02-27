# Remora v0.4.1 Refactor Implementation Design

## Objective
Deliberately follow the v0.4.1 Refactoring Guide by implementing the twelve phases in sequence, validating each phase with the corresponding tests, and keeping the core architecture aligned with the v0.4.0 plan.

## Architecture Focus
- Maintain the core modules under `src/remora/` and keep services in `src/remora/indexer/` and `src/remora/dashboard/`.
- Ensure EventBus, executor, workspace, context builder, and dashboard are wired through structured-agents, Grail, and Cairn contracts.
- Treat each phase as a focused validation point: config/schema, event taxonomy, bundle metadata, workspace layer, agent execution, context handling, dashboard wiring, cleanup/removal, and testing realignment.

## Implementation Strategy
1. Phase compliance: implement the code changes described in each step, then immediately run the listed pytests to verify behavior before moving to the next phase.
2. Respect purity goals: graph builders remain deterministic, workspaces interact only through Cairn helpers, and agents execute through structured-agents with EventBus-backed context.
3. Clean-up phases (tools, legacy modules, tests) align the repository with the v0.4.0 surface before final validation.

## Validation & Testing
- After each phase, run the tests noted in the guide (e.g., `tests/test_config.py` for config, `tests/unit/test_event_bus.py` for events).
- Final validation runs `pytest -q` to ensure the entire suite passes on the refactored surface.
- Track regressions by comparing results against the Phase 1 baseline failures before refactor work.

## Next Steps
- With this design approved, proceed to stage the implementation plan via the writing-plans skill and use the todowrite tool to organize work through the phases.
