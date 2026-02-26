# Implementation Guide: Step 13 - Verification and Smoke Tests

## Target
Create the verification plan covering unit tests, integration smoke tests, and documentation updates so the v0.4.0 refactor is provably correct and runnable.

## Overview
- Unit tests for each new module (event bus, graph, executor, workspace, context, checkpoint, indexer, dashboard) to guard contracts.
- Integration smoke tests that run a single bundle (e.g., lint) through discovery → graph → executor with Cairn-managed workspaces and ensure the unified EventBus handles human-in-the-loop flows.
- Documentation verifying CLI commands, entry points, and service separation.

## Steps
1. Add targeted unit tests (`tests/test_events.py`, `tests/test_graph.py`, `tests/test_executor.py`, `tests/test_workspace.py`, `tests/test_context.py`, `tests/test_checkpoint.py`, `tests/test_indexer.py`, `tests/test_dashboard.py`) that verify the new modules behave as described in Steps 1-12.
2. Add integration scripts (`tests/integration/test_lint_bundle.py`, etc.) that run an entire bundle against sample code, ensures DataProvider/ResultHandler plumbing works, and that the GraphExecutor emits the expected events on the bus.
3. Run CLI smoke tests after installing in editable mode: `remora --help`, `remora discover`, `remora-index --help`, `remora-dashboard --help`, and ensure each service logs startup output and exits cleanly.
4. Document the new architecture and commands in README/docs, referencing `docs/plans/V040_GROUND_UP_REFACTOR_PLAN.md` and the reworked `.refactor` guides so future contributors understand the breakdown.
