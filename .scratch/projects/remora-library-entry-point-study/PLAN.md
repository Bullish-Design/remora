# PLAN - Remora Library Entry Point Study

## CRITICAL RULE (REPEATED): NO SUBAGENTS
All work in this project is done directly in-repo with no subagent delegation.

## Objective
Create a high-signal overview of the key Remora entry points to study first, ordered so a reader can build a correct mental model from runtime edges inward to core domain logic.

## Deliverables
1. `ENTRY_POINTS_OVERVIEW.md` with:
   - Script/module entry points
   - Runtime call chains (CLI, LSP, HTTP service)
   - Prioritized file study order
   - Recommended study sequence
2. Standard project tracking files (`ASSUMPTIONS.md`, `PROGRESS.md`, `CONTEXT.md`, `DECISIONS.md`, `ISSUES.md`)

## Implementation Steps
1. Read repo/session rules and gather package/script entry points.
2. Trace code paths from entry points into core runtime components.
3. Produce prioritized entry point overview with practical study order.
4. Record assumptions/decisions/progress for resumability.

## Acceptance Criteria
- A new project directory exists under `.scratch/projects/`.
- The overview names concrete files in `src/remora` and explains why each is early-study material.
- The order supports understanding the full reactive loop (discovery -> events -> routing -> runner execution).
- Project tracking files reflect completed status and rationale.

## CRITICAL RULE (REPEATED): NO SUBAGENTS
Do not use Task/subagents for any project step.
