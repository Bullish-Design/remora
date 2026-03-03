# Event-Based Concept Gap Analysis — CONTEXT

## Project Status: COMPLETE

Both deliverables for this project are finished:

1. **`GAP_ANALYSIS.md`** (400 lines) — comprehensive comparison of `docs/EventBased_Concept.md` against the actual codebase, identifying 13 gaps with severity ratings and a priority matrix.

2. **`GAP_REFACTORING_PLAN.md`** (973 lines) — detailed plan for closing every gap, organized into 5 dependency-ordered workstreams with 9 sections covering: executive summary, per-workstream details (what changes, why, how, pseudocode, pros/cons), dependency graph & execution order, post-refactoring developer experience walkthrough, and risk assessment with mitigations.

## Summary of the Refactoring Plan

Five workstreams in recommended order:

| Workstream | Gaps | Effort | Key Change |
|------------|------|--------|------------|
| **A: Wire Reactive Loop** | #10 | Small | Add `FileSavedEvent`/`ContentChangedEvent` to `did_save` |
| **B: Unify Runners** | #6,7,8,9 | Large | Extract `execute_agent_turn()` from `SwarmExecutor`, make `AgentRunner` delegate to it |
| **C: Unify Discovery** | #3,4,5 | Medium | Make `ASTWatcher` delegate to `core.discovery.parse_content()` |
| **D: LSP Events** | #12,13 | Small-Med | Add `didChange` handler + debounce cursor tracking |
| **E: AgentNode** | #11 | Trivial | Verify/populate `last_trigger_event`/`last_completed_at` |

Estimated total: 12-18 developer-days.

## Recommended Next Project

Start implementing **Workstream A** — it's ~30 lines of code in one file, ships as one PR, and unblocks the reactive loop's primary trigger in LSP mode.
