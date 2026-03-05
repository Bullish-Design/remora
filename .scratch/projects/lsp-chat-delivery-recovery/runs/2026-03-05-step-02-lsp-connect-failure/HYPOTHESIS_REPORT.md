# Hypothesis Report

## Run Metadata
- Date: 2026-03-05
- Run directory: `.scratch/projects/lsp-chat-delivery-recovery/runs/2026-03-05-step-02-lsp-connect-failure/`
- Input logs:
  - `.remora/logs/client-2026-03-05_112250.log`
  - `.remora/logs/server-2026-03-05_105316.log` (latest available; no new 11:22 server log created)
  - `~/.local/state/nvim/lsp.log`
- Commit baseline: working tree at run start

## Observed Symptoms
- Neovim panel and commands repeatedly reported no Remora LSP client.
- Chat command aborted with `exec_command: no client after retry, aborting`.
- No new server log was created for the 11:22 evaluation run.

## Stage Counters
- `on_input_submitted`: 0 (no new server session for this run)
- `HumanChatEvent emitted`: 0 (no new server session for this run)
- `execute_turn: START`: 0 (no new server session for this run)
- `execute_turn: ... calling LLM`: 0 (no new server session for this run)
- `append: database locked`: 0 (no new server session for this run)
- `batch_append: database locked`: 0 (no new server session for this run)
- `get_client: NO remora clients found` in client log: 91
- `get_client_with_retry: gave up after 20 attempts` in client log: 2

## Primary Hypothesis
The 11:22 run failed before server initialization because startup hit the workspace process lock path, and client retry logic did not re-trigger LSP startup or surface lock-owner context to the user.

Supporting evidence:
- `~/.local/state/nvim/lsp.log` contains:
  - `[2026-03-05 11:23:08] ... "Another remora-lsp instance is already active for this workspace (pid=191467)"`
- Latest server log remains `server-2026-03-05_105316.log`; no `server-2026-03-05_1122xx.log` exists.

## Recommended Fix
Improve Neovim client recovery/diagnostics in `src/remora/lsp/nvim/lua/remora/init.lua`:
1. During `get_client_with_retry`, explicitly attempt `vim.lsp.start(...)` on initial no-client state and periodically during retries.
2. When retries exhaust, include lock-owner hints from `.remora/lsp.pid` in the warning message.

## Why This Fix
- If lock contention is transient (previous instance shutting down), periodic start kicks can recover automatically in the same session.
- If lock contention is persistent, users now get explicit lock-owner context instead of only generic “LSP not available”.
- This is minimal and isolated: it does not alter EventStore contention behavior or retry/backoff in the server.

## Falsification Criteria
- If retries still fail and lock-owner hints do not appear when `.remora/lsp.pid` exists, this fix is incomplete.
- If lock-owner hints appear but no recovery occurs even after prior owner exits, server-side lock behavior needs a follow-up change.

## Verification Plan
1. Run Neovim evaluation as before and trigger panel/chat.
2. Check client log for:
  - `kick_lsp_start(initial-no-client)`
  - `kick_lsp_start(retry-5)` (or similar periodic attempts)
  - lock hint message on final failure, if applicable.
3. Pass criteria:
  - Either Remora client attaches and chat can execute, or final warning clearly indicates lock-owner context.

## Notes
- This run confirms startup lock-collision behavior and answers the question: yes, the run attempted to start `remora-lsp`, but startup aborted because it detected an active previous workspace lock owner.
