# Phase 3 Plan Gap Analysis

## Scope
This document captures follow-up analysis for item #3 from the architecture discussion:
"what was missed in the design plan after finishing the concrete implementation gaps (#1 and #2)."

Date: 2026-03-06
Project: architecture_refactor

## Problems
1. The Phase 5 "move runner to remora.runner" step did not force a full dependency-boundary extraction.
2. The previous plan treated file movement and protocol introduction as sufficient, but behavior-level coupling remained.
3. LSP-specific proposal and event orchestration lived inside `AgentRunner`, so module relocation alone could not achieve true decoupling.

## Issues
1. Boundary ambiguity: `runner` was expected to be generic, but still owned editor-specific flows.
2. Coupling via command path: proposal acceptance logic was reachable through handler internals instead of a stable server interface.
3. Type-surface drift: handler modules typed against concrete server module paths, creating dependency pressure toward cycles.

## Concerns
1. Regression risk: architectural drift can reappear when new features are added to the runner without explicit boundary tests.
2. Test masking: compatibility aliases can hide structural problems while behavior tests still pass.
3. Ownership confusion: proposal/event responsibilities were split across runner/server/handlers without a clearly enforced contract.

## Implications
1. Refactors become harder because package boundaries are not behaviorally enforced.
2. Static dependency tooling can report recurring cycles even when runtime behavior works.
3. Future maintainers may reintroduce `runner -> lsp` imports unless interface constraints are codified and checked.

## Opportunities
1. Add architecture tests that fail on forbidden imports (`runner -> lsp`, `handlers -> server`).
2. Keep server-side event/proposal emission as the single integration seam used by runner.
3. Keep compatibility aliases temporary and track explicit removal milestones.
4. Introduce a "boundary checklist" in the refactor guide for each moved module:
   - no imports from old layer,
   - no calls into layer-private handlers,
   - protocol methods cover all cross-layer operations.

## Suggested Next Actions
1. Add CI checks for forbidden dependency edges.
2. Add documentation for server/runner contract methods and expected ownership.
3. Create a deprecation plan for compatibility aliases in `core/*` and `lsp/*` shim modules.
