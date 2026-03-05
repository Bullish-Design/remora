# Next Step Plan — Recover and Prevent Stale Lock Owners

## Goal
Restore reliable real-run chat by removing stale lock-owner blockage, then implement a durable fix so unusable lock owners cannot block future sessions.

## Phase 1 — Fast Validation (Operational)
1. Capture pre-action evidence snapshot.
   - Save current outputs of:
     - `ps -p 250354 -o pid,ppid,etime,%cpu,%mem,state,cmd`
     - `cat .remora/lsp.pid`
     - tail of `client-2026-03-05_131041.log`
2. Terminate stale lock owner process.
   - `kill 250354` (or `kill -TERM 250354`), verify process exit.
3. Retry a real chat action in Neovim.
4. Verify success markers in fresh logs:
   - client: `HANDLER $/remora/requestInput`
   - server: `on_input_submitted`, `execute_turn: START`, `AgentTextResponse`

## Phase 2 — Product Fix (Code)
1. Add owner-liveness metadata to lock state.
   - Extend `.remora/lsp.pid` heartbeat semantics (pid + last-seen timestamp written periodically).
2. Add startup stale-owner takeover rule.
   - If owner heartbeat is older than threshold and no active client evidence, treat as stale and reclaim lock.
3. Add disconnect/idle shutdown guarantees.
   - On transport/client disconnect, ensure remora-lsp exits promptly and releases lock.
4. Improve client diagnostics.
   - Distinguish:
     - owner alive and healthy,
     - owner alive but stale/unresponsive,
     - stale metadata only.

## Phase 3 — Verification
1. Add regression test(s) for stale-owner recovery.
2. Run real-run validation twice back-to-back to prove lock is released/reacquired cleanly.
3. Re-run `chat` e2e to ensure submit-path improvements remain intact.

## Exit Criteria
- Real run can send/receive chat without manual process cleanup.
- No repeated `another workspace lock owner exists` loop for stale owners.
- Server lifecycle shows clean startup and shutdown behavior across repeated sessions.
