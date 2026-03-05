# ISSUE_001 — Startup Attach Delay + Submit/Panel Stall

## Status
OPEN

## Summary
In latest manual run (2026-03-05 14:33-14:35), proactive startup fired but client attach was delayed by multiple seconds. Chat prompt request reached server, but submit did not reach `on_input_submitted`. Panel requests timed out repeatedly while scan writes were slow.

## Primary Artifacts
- `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-startup-initial-connection/issues/2026-03-05-latest-manual-run/LOG_ANALYSIS.md`
- `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-startup-initial-connection/issues/2026-03-05-latest-manual-run/HYPOTHESIS_REPORT.md`
- `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-startup-initial-connection/issues/2026-03-05-latest-manual-run/NEXT_STEP_PLAN.md`

## Success Condition
One run proving all three:
1. `REMORA_CLIENTS>=1` from headless startup probe.
2. Submit chain reaches `on_input_submitted` and `execute_turn: START`.
3. Panel remains responsive (no timeout storm).
