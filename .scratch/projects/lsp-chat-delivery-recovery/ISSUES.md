# ISSUES — lsp-chat-delivery-recovery

## Active Issues
- `ISSUE_001` — real-run startup blocked by persistent lock owner (`pid=250354`), preventing any LSP client attach and chat command execution.
  - Current status: lifecycle hardening implemented; pending one manual real-run confirmation.
  - Index: `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-chat-delivery-recovery/ISSUE_001.md`
  - Artifacts:
    - `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-chat-delivery-recovery/issues/2026-03-05-real-run-lock-owner-pid-250354/LOG_ANALYSIS.md`
    - `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-chat-delivery-recovery/issues/2026-03-05-real-run-lock-owner-pid-250354/HYPOTHESIS_REPORT.md`
    - `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-chat-delivery-recovery/issues/2026-03-05-real-run-lock-owner-pid-250354/NEXT_STEP_PLAN.md`
    - `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-chat-delivery-recovery/runs/2026-03-05-step-08-lock-owner-lifecycle-hardening/IMPLEMENTATION_REPORT.md`

## Historical Pattern to Avoid
- Repeated retry/backoff tuning without isolating lock holder ownership or proving causal improvement.
