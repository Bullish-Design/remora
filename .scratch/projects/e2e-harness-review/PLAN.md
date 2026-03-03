# PLAN: E2E Harness Review

## IMPORTANT: NO SUBAGENTS — Do all work directly. No Task tool. No delegation.

## Goal

Consolidate findings from the `verify-e2e-live` project (12 scenario reports) into a single actionable review document (`E2E_HARNESS_UPDATES.md`) that describes all necessary changes to the E2E harness, keys.py, and individual scenarios.

## Steps

1. Read all 12 report files from `verify-e2e-live` — **DONE**
2. Read `e2e/harness.py` and `e2e/keys.py` for current implementation — **DONE**
3. Analyze cross-cutting patterns (LSP readiness, focus management, assertions)
4. Write `E2E_HARNESS_UPDATES.md` with:
   - Table of contents
   - Executive summary
   - Cross-scenario issues (harness-level)
   - keys.py improvements
   - Per-scenario fix lists
   - Backend bugs discovered
   - Priority ordering
5. Update PROGRESS.md and CONTEXT.md

## Acceptance Criteria

- `E2E_HARNESS_UPDATES.md` covers all 12 scenarios
- Every cross-scenario issue is documented with root cause and fix
- Each scenario has specific, actionable improvement steps
- Priority ordering makes it clear what to fix first
- Document is self-contained (readable without the individual reports)

## IMPORTANT: NO SUBAGENTS — Do all work directly. No Task tool. No delegation.
