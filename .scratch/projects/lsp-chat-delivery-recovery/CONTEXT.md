# CONTEXT — lsp-chat-delivery-recovery

## Current State
Active investigation has advanced through step-08. Step-07 deterministic chat-submit remediation remains validated, and step-08 lock-owner lifecycle hardening is now implemented with targeted unit + e2e validation.

## What We Know
- Multiple morning commits targeted SQLite lock contention and startup races.
- Most failing runs showed `on_input_submitted` without `HumanChatEvent emitted` or `execute_turn`.
- Lock-warning storms (`append`/`batch_append`) dominated failing windows.
- Later run (`server-2026-03-05_105316.log`) improved to `HumanChatEvent emitted` and `execute_turn: START`.
- New script `scripts/simplify_logs.py` removes repetitive low-signal `NodeDiscoveredEvent` triplets and writes per-run `simplify_summary.json`.
- Latest run pair (`client-2026-03-05_113433.log`, `server-2026-03-05_113451.log`) shows LSP eventually connected, but chat flow still stalls before `calling LLM`; latest investigation artifacts are in `runs/2026-03-05-step-03-post-lock-fix-check/`.
- Step-03 recommended fixes are now implemented:
  - LSP command handlers now log EventStore read start/end durations in `_resolve_agent` and `cmd_get_agent_panel`.
  - `_resolve_agent` now has a bounded timeout with explicit timeout logging and user-visible error handling in chat/rewrite commands.
- E2E harness now copies canonical `client-*.log` and `server-*.log` from demo workspace into repo `.remora/logs`, enabling local iteration without manual log copying.
- Local verification on 2026-03-05:
  - `e2e.run --scenario startup --no-record` created repo-side `client-2026-03-05_122639.log`.
  - `e2e.run --scenario chat --no-record` created repo-side `server-2026-03-05_122713.log` with `_resolve_agent` timing logs.
  - `e2e.run --scenario panel_nav --no-record` created `server-2026-03-05_122755.log` with `cmd_get_agent_panel` timing logs.
- New investigation loop artifacts were added at `runs/2026-03-05-step-04-post-instrumentation-check/` from latest logs:
  - `client-2026-03-05_122744.log`
  - `server-2026-03-05_122755.log`
  - Result: panel read timings are low (0.9-1.5ms for node lookup, 13.2-14.1ms for recent-events read), but chat path was not exercised in this run.
  - `~/.local/state/nvim/lsp.log` still shows duplicate-instance warning at `2026-03-05 12:27:58`.
- Step-05 instrumentation was applied in `src/remora/lsp/runner.py`:
  - pre-LLM stage timing logs (`set_node_status`, `get_node`, `get_events_for_correlation`)
  - bounded timeout around `execute_agent_turn`
  - unit coverage in `tests/unit/test_lsp_runner.py`.
- Step-06 recorded `chat` runs exposed a false-positive scenario pass:
  - `chat_20260305_124556.cast` + `server-2026-03-05_124608.log`: scenario passed, but `on_input_submitted=0`, `execute_turn: START=0`.
  - cast shows `Message to agent: ra` artifact (leader sequence leaking into prompt context).
  - after tightening `e2e/scenarios/chat.py` to assert visible message, `chat` fails (`chat_20260305_124926.cast`) with prompt open but no submitted message.
  - latest run artifacts in `runs/2026-03-05-step-06-chat-recording-submit-gap/` include raw logs, casts, simplified logs, `CAST_ANALYSIS.md`, `HYPOTHESIS_REPORT.md`, and `NEXT_STEP_PLAN.md`.
- Current code change in progress:
  - Deterministic submit helper added in `e2e/keys.py` (`submit_chat_message`, `wait_for_chat_history_message`).
  - `e2e/scenarios/chat.py` now uses deterministic helper and hard-fails unless server log contains:
    - `cmd_chat: requestInput sent`
    - `on_input_submitted: params=`
    - `execute_turn: START`
  - Chat scenario now targets the unambiguous prompt string `Message to agent:` (avoids matching panel winbar `Message agent...` before requestInput is active).
  - `src/remora/lsp/nvim/lua/remora/init.lua` requestInput handler logs explicit routing branch diagnostics.
  - `e2e/tests/test_keys.py` includes unit coverage for the new helper behavior and timeout semantics.
  - Validation on 2026-03-05:
    - `devenv shell -- pytest e2e/tests/test_keys.py -q` PASS
    - `devenv shell -- python -m e2e.run --scenario chat --no-record` PASS
    - server log `.remora/logs/server-2026-03-05_130514.log` includes submit/runner markers.
- Neovim client startup behavior updated:
  - `src/remora/lsp/nvim/lua/remora/init.lua` now proactively attempts `remora-lsp` start during setup (`vim.schedule`) and on `VimEnter` (once), instead of relying solely on first file open/filetype autocmd.
  - `kick_lsp_start` now sets `root_dir` from cwd when absent so startup can succeed from unnamed buffers.
- Latest real-run regression captured on 2026-03-05 13:10-13:11:
  - client log `.remora/logs/client-2026-03-05_131041.log` shows repeated `get_client_with_retry` exhaustion and command aborts.
  - explicit lock hint repeats: `another workspace lock owner exists (pid=250354)`.
  - `~/.local/state/nvim/lsp.log` confirms collisions with that same pid during the same minute.
  - lock metadata `.remora/lsp.pid` points to `250354`; process still alive long after initial startup.
  - issue artifacts created under `issues/2026-03-05-real-run-lock-owner-pid-250354/` with analysis + hypothesis + plan.
- Follow-up mitigation + validation (2026-03-05 13:20-13:21):
  - stale owner process `pid=250354` was terminated.
  - startup and chat e2e both pass again:
    - `devenv shell -- python -m e2e.run --scenario startup --no-record`
    - `devenv shell -- python -m e2e.run --scenario chat --no-record`
  - client logs now show proactive autostart before user commands:
    - `M.setup: proactive autostart registered`
    - `kick_lsp_start(vimenter-autostart): ...`
    - `autostart_lsp(vimenter-autostart): start_requested=true`
  - chat still completes full round-trip (`requestInput` -> `on_input_submitted` -> `execute_turn: START` -> `AgentTextResponse`).
- Step-08 lock-owner lifecycle hardening (2026-03-05 13:30-13:33):
  - `src/remora/lsp/__init__.py` now writes lock-owner heartbeat metadata (`pid`, `heartbeat_ms`, `ppid`) and refreshes it while lock is held.
  - startup collision path now attempts stale-owner reclaim when heartbeat is stale and owner process matches `remora-lsp` for same workspace.
  - lifecycle cleanup added via signal handlers and parent-process watchdog to reduce orphaned lock owners.
  - `src/remora/lsp/nvim/lua/remora/init.lua` lock hint now distinguishes fresh-owner, stale-heartbeat owner, and stale metadata.
  - new tests in `tests/unit/test_lsp_lock_owner.py` pass.
  - startup/chat e2e both pass after hardening:
    - `devenv shell -- python -m e2e.run --scenario startup --no-record`
    - `devenv shell -- python -m e2e.run --scenario chat --no-record`
  - implementation artifact: `runs/2026-03-05-step-08-lock-owner-lifecycle-hardening/IMPLEMENTATION_REPORT.md`.
- Skill updates:
  - `.scratch/skills/lsp-chat-recovery-loop/SKILL.md` now requires cast analysis when marker validation fails.
  - hypothesis/next-step templates now include cast evidence fields.

## Next Task
Run one manual real Neovim validation loop against ISSUE_001 to confirm lock-owner hardening resolves the prior `pid=250354` startup blockage pattern without manual process cleanup.
