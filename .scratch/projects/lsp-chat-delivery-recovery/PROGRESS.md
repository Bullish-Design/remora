# PROGRESS — lsp-chat-delivery-recovery

## Phase 1: Forensics Baseline — IN PROGRESS
- [x] Create project structure with all required standard files.
- [x] Build detailed morning commit forensic report.
- [x] Capture today log metrics for submit/emission/runner/lock-error progression.
- [x] Identify minimal next remediation set from forensic findings.
- [x] Add reusable log simplifier script and generate first simplified artifact set.

## Phase 2: Controlled Reproduction — IN PROGRESS
- [ ] Write baseline reproducibility runbook.
- [ ] Execute and record one clean baseline run.
- [x] Capture 2026-03-05 11:22 connect-failure run artifacts and hypothesis report.
- [x] Capture 2026-03-05 11:34/11:35 post-lock-fix run artifacts and hypothesis report.
- [x] Capture 2026-03-05 12:27 post-instrumentation panel run artifacts and hypothesis report.
- [x] Capture 2026-03-05 12:46/12:49 chat recording evidence and cast-based submit-gap hypothesis report.

## Phase 3: Targeted Remediation — IN PROGRESS
- [x] Implement minimal client-side recovery/diagnostic fix for lock-collision startup failure.
- [x] Implement EventStore read-path timing + timeout instrumentation in LSP command handlers.
- [x] Fix e2e harness log routing so latest `client-*.log` and `server-*.log` land in repo `.remora/logs`.
- [x] Tighten recovery-loop skill/templates to require cast analysis + explicit error-origin details.
- [x] Implement deterministic e2e chat submit helper and remove false-positive `chat` passes.
- [x] Proactively autostart remora LSP on setup/VimEnter (no first-file-open dependency).
- [x] Implement lock-owner lifecycle hardening (heartbeat, stale-owner reclaim, signal cleanup, parent watchdog) for ISSUE_001.
- [ ] Validate lock-owner hardening in manual real Neovim run (previous `pid=250354` failure pattern).
- [ ] Re-run baseline and compare deltas.

## Phase 4: Verification and Closeout — PENDING
- [ ] Confirm baseline reliability end-to-end.
- [ ] Finalize lessons learned and anti-loop checklist.
