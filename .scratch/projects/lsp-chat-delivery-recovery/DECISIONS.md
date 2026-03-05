# DECISIONS — lsp-chat-delivery-recovery

## 2026-03-05 — Create dedicated forensic project
- Decision: Split this issue into a dedicated `.scratch/projects/lsp-chat-delivery-recovery/` workspace.
- Why: Morning fixes were spread across commits with overlapping hypotheses; centralizing evidence avoids repeated experiments.
- Inputs: `.scratch/CRITICAL_RULES.md` project convention and repeated lock-contention attempts in morning commits.

## 2026-03-05 — Prefer structural contention controls over timeout escalation
- Decision: Do not prioritize increasing SQLite busy timeout.
- Why: Morning evidence shows long retries and backoff did not reliably unblock chat delivery.
- Inputs: `server-2026-03-05_094004.log`, `server-2026-03-05_094547.log`, commit timeline.

## 2026-03-05 — Step-01 hypothesis is interactive scan gating
- Decision: Next remediation experiment will isolate one structural change: gate/pause background scan event emission during active chat windows.
- Why: Current logs are dominated by high-volume `NodeDiscoveredEvent` write bursts and this directly tests contention relief without changing startup or retry behavior.
- Inputs: `MORNING_COMMIT_FORENSIC_REPORT.md` anti-loop guidance and run plan in `runs/2026-03-05-step-01-interactive-scan-gate/NEXT_STEP_PLAN.md`.
