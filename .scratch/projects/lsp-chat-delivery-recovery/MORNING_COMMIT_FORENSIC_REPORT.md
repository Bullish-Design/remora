# Morning Commit Forensic Report — Baseline Chat Delivery

Date analyzed: 2026-03-05 (America/New_York)

## Executive Summary
Morning work focused on one root failure mode: chat submissions entered the LSP server but frequently failed before runner/LLM execution because event writes were blocked by SQLite lock contention. Multiple commits iterated timeout/backoff parameters and scan pacing; those changes reduced some symptoms but repeatedly re-entered the same lock storm pattern. The latest morning state shows partial improvement (`HumanChatEvent emitted` and `execute_turn: START` present in the 10:53 run), but full baseline reliability is not yet proven.

## Ground Truth Timeline (Commits)
1. `fd542f7` — 08:48:19 — "SQLite cursors were dangling"
- Files: `src/remora/core/event_store.py`, `src/remora/lsp/db.py`, `src/remora/lsp/graph.py`
- Intent: clean cursor lifecycle and DB access patterns.
- Category: SQLite hygiene.

2. `88f81db` — 09:11:42 — "Bug hunting..."
- File: `.remora/indexer.db` (binary change only)
- Intent: runtime DB churn, no durable code fix.
- Category: runtime artifact.

3. `c3aa9d2` — 09:26:26 — "Bug hunting v2..."
- Files: `event_store.py`, `lsp/__main__.py`, Neovim Lua client files.
- Intent:
  - reduce `event_store` timeout from long waits to short fail-fast retry,
  - add `batch_append`,
  - add LSP client retry/polling in Neovim.
- Category: lock retry tuning + client startup race handling.

4. `ea27001` — 09:41:03 — "Bug hunting v3..."
- File: `event_store.py`
- Intent:
  - add dedicated read connection (`_read_conn`),
  - move read paths off writer lock,
  - continue lock retry handling.
- Category: read/write separation.

5. `ec7d225` — 09:49:34 — "Bug hunting v4... Switch sqlite over to turso??"
- Files: `.scratch/LSP_Debugging_Summary.md`, `event_store.py`, `lsp/__main__.py`
- Intent:
  - shorten timeout/backoff further,
  - adjust scan behavior (initial delay and between-file delay),
  - document findings.
- Category: retry retuning + scan pacing.

6. `0d0d281` — 10:54:21 — "Bug hunting v5..."
- Files: `event_store.py`, `lsp/__init__.py`, `lsp/__main__.py`, `notifications.py`, `server.py`, `devenv.nix`
- Intent:
  - add lock diagnostics and jittered retry helpers,
  - add WAL checkpoint helpers/autocheckpoint,
  - add single-process lock files (`.remora/lsp.lock`, `.remora/lsp.pid`),
  - pause background scan during recent user activity,
  - persist scan manifest.
- Category: observability + process isolation + scan throttling.

## Runtime Evidence by Morning Server Log
`server-2026-03-05_092528.log`
- `on_input_submitted=1`, `HumanChatEvent emitted=0`, `execute_turn START=0`.
- Message reached handler but did not advance to event emission/runner.

`server-2026-03-05_094004.log`
- `on_input_submitted=2`, `HumanChatEvent emitted=0`, `execute_turn START=0`.
- `append_or_batch_locked_warnings=25`.
- Clear write contention during chat submissions.

`server-2026-03-05_094547.log`
- `on_input_submitted=2`, `HumanChatEvent emitted=0`, `execute_turn START=0`.
- `append_or_batch_locked_warnings=147`, `db_locked_errors=7`.
- Explicit `sqlite3.OperationalError: database is locked` in `EventStore.append` (`BEGIN IMMEDIATE`).

`server-2026-03-05_105316.log`
- `on_input_submitted=1`, `HumanChatEvent emitted=1`, `execute_turn START=1`.
- Improvement: chat now passes through event emission and enters runner at least once.
- Still missing proof of consistent `calling LLM` for baseline reliability.

## What Happened (Cause/Effect)
1. Primary blocker was pre-LLM: DB write contention in EventStore prevented `HumanChatEvent` append from completing, so runner was never triggered in most failing runs.
2. Morning fixes repeatedly tuned contention symptoms (timeouts/backoffs) without consistently removing the write-conflict source.
3. Startup/client retry changes were useful for a separate class of failures (client readiness) but did not solve DB writer contention.
4. The later structural changes (single-process lock + scan pausing + checkpoints + diagnostics) moved behavior forward, evidenced by the 10:53 run reaching `execute_turn`.

## Repetition/Loop Analysis
Patterns repeated across commits:
- Retuning timeout/backoff values multiple times (2s/5 attempts, then 100ms/10 attempts, etc.).
- Continuing to rely on retry under sustained write pressure from background scanning.
- Mixing two hypotheses in parallel (LSP startup race and SQLite write contention), making outcomes harder to attribute.

Why this caused circles:
- Each iteration changed several knobs at once, so failures persisted without clear falsification of individual hypotheses.
- Success criteria were not fixed per run (submit->emit->runner->LLM chain), so partial wins looked similar to full fixes.

## Do-Not-Repeat List
1. Do not run another “retry/backoff-only” patch without proving lock-holder source and contention window reduction.
2. Do not combine Neovim startup retry changes with EventStore contention changes in the same experiment.
3. Do not evaluate success solely on absence of stack traces; require stage-by-stage pipeline evidence.
4. Do not use binary DB diffs (`.db` file size growth) as proof of functional fix.

## Recommended Next Validation Loop (Minimal + Falsifiable)
1. Fix one structural contention hypothesis at a time.
2. For each run, record these counters from the server log:
- `on_input_submitted`
- `HumanChatEvent emitted`
- `execute_turn: START`
- `execute_turn: ... calling LLM`
- `append: database locked` / `batch_append: database locked`
3. Pass criteria for baseline app: all submitted chats reach `calling LLM` with no lock storm during interactive window.

## Artifacts Used
- Morning commits: `fd542f7`, `88f81db`, `c3aa9d2`, `ea27001`, `ec7d225`, `0d0d281`.
- Logs:
  - `.remora/logs/server-2026-03-05_092528.log`
  - `.remora/logs/server-2026-03-05_094004.log`
  - `.remora/logs/server-2026-03-05_094547.log`
  - `.remora/logs/server-2026-03-05_105316.log`
