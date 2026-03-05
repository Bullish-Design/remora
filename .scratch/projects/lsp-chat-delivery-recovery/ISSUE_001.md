# ISSUE_001 — Real Run Blocked By Persistent Lock Owner (pid=250354)

## Summary
Real Neovim run at `2026-03-05 13:10-13:11` failed to execute chat because no remora LSP client could attach. Retries consistently reported an active workspace lock owner (`pid=250354`) and aborted commands.

## Key Evidence
- Client run log: `.remora/logs/client-2026-03-05_131041.log`
  - repeated `get_client: ... clients=0`
  - `gave up after 20 attempts`
  - `lock hint: another workspace lock owner exists (pid=250354)`
  - `exec_command: no client after retry, aborting`
- Global Neovim LSP log: `~/.local/state/nvim/lsp.log`
  - repeated: `Another remora-lsp instance is already active for this workspace (pid=250354)`
- Lock metadata and process state:
  - `.remora/lsp.pid` line 1 is `250354`
  - live process: `remora-lsp` with long elapsed runtime.

## Detailed Artifacts
- `issues/2026-03-05-real-run-lock-owner-pid-250354/LOG_ANALYSIS.md`
- `issues/2026-03-05-real-run-lock-owner-pid-250354/HYPOTHESIS_REPORT.md`
- `issues/2026-03-05-real-run-lock-owner-pid-250354/NEXT_STEP_PLAN.md`
- `runs/2026-03-05-step-08-lock-owner-lifecycle-hardening/IMPLEMENTATION_REPORT.md`

## Status
In progress.

## 2026-03-05 Update
- Code hardening implemented:
  - lock-owner heartbeat refresh in `.remora/lsp.pid`
  - stale-owner reclaim attempt on startup lock collision
  - termination cleanup via signal handlers + parent watchdog
  - richer Neovim lock hints (healthy owner vs stale heartbeat vs stale metadata)
- Validation completed:
  - `tests/unit/test_lsp_lock_owner.py` PASS
  - `e2e.run --scenario startup --no-record` PASS
  - `e2e.run --scenario chat --no-record` PASS
- Remaining closure check:
  - one manual real-run confirmation for the exact historical failure mode.
