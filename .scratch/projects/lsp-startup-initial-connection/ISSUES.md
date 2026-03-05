# ISSUES — LSP Startup Initial Connection

## Active Issues
- `ISSUE_001` — startup attach is delayed and interactive submit/panel paths remain unreliable in latest manual run.
  - Summary: `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-startup-initial-connection/ISSUE_001.md`
  - Index: `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-startup-initial-connection/issues/2026-03-05-latest-manual-run/LOG_ANALYSIS.md`
  - Hypothesis: `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-startup-initial-connection/issues/2026-03-05-latest-manual-run/HYPOTHESIS_REPORT.md`
  - Plan: `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-startup-initial-connection/issues/2026-03-05-latest-manual-run/NEXT_STEP_PLAN.md`

## Historical Pitfalls To Avoid
- Treating `startup` scenario PASS as attach proof without headless client-count validation.
- Tuning retry counts/timeouts without first proving where latency/blocking occurs.
- Mixing multiple unrelated fixes in one pass (hard to falsify).
