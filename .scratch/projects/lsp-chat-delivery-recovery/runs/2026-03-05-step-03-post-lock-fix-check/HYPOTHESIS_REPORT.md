# Hypothesis Report

## Run Metadata
- Date: 2026-03-05
- Run directory: `.scratch/projects/lsp-chat-delivery-recovery/runs/2026-03-05-step-03-post-lock-fix-check/`
- Input logs:
  - `.remora/logs/client-2026-03-05_113433.log`
  - `.remora/logs/server-2026-03-05_113451.log`
  - `~/.local/state/nvim/lsp.log`
- Related commit context: client retry/start diagnostics fix already applied in `9f1bf2b`

## Observed Symptoms
- LSP eventually connected in this run (new server log exists), so startup failure mode regressed less.
- Chat pipeline started once (`on_input_submitted -> HumanChatEvent emitted -> execute_turn: START`) but never reached `calling LLM`.
- Later chat/panel commands at line 90 stop at `_resolve_agent: querying EventStore...` with no follow-up completion logs.

## Stage Counters
- `on_input_submitted: params=`: 1
- `on_input_submitted: HumanChatEvent emitted`: 1
- `execute_turn: START`: 1
- `calling LLM`: 0
- `append: database locked`: 0
- `batch_append: database locked`: 0

Client-side context:
- `CMD RemoraChat`: 3
- `panel.send_message: sending`: 1
- `NO remora clients found`: 25 (startup window)
- `connected after`: 1

Transport log context:
- `~/.local/state/nvim/lsp.log` shows at `2026-03-05 11:34:55`:
  - `Another remora-lsp instance is already active for this workspace (pid=250354)`
  - This indicates repeated startup attempts collided with the already-running instance after one start succeeded.

## Primary Hypothesis
Primary current blocker moved from "cannot attach LSP" to "post-trigger execution stalls before LLM call," likely around long/blocking EventStore interactions during concurrent background scan and command lookups.

Evidence:
- Runner begins turn and enters `execute_agent_turn: initializing workspace service`, then no `calling LLM`.
- Later `cmd_chat` calls stop at `_resolve_agent: querying EventStore...` with no completion line.
- No explicit lock error is emitted, consistent with blocking/serialization without timeout-triggered failure logging.

## Recommended Next Fix (minimal, falsifiable)
Add explicit timing + timeout instrumentation around EventStore read paths used by chat/command handlers:
1. Wrap `_resolve_agent` EventStore query in a bounded timeout and log elapsed time + timeout events.
2. Add start/end duration logs around EventStore calls used by `cmd_get_agent_panel` and `cmd_chat`.
3. Return a user-visible timeout error from command handlers instead of hanging silently.

## Why This Fix
- It is the smallest change that can prove/disprove read-path blocking as the immediate cause.
- It converts silent stalls into measurable signals, enabling the next structural fix to target a confirmed bottleneck.

## Falsification Criteria
- If the new timing logs show fast EventStore reads while `calling LLM` is still absent, this hypothesis is wrong.
- If no timeouts/slow queries appear but command flow still stalls, the block is elsewhere (e.g., workspace init path or runner internals).

## Verification Plan
1. Re-run the same interaction pattern (open panel, `RemoraChat`, send a message).
2. Verify logs now include EventStore read durations and/or timeout markers.
3. Pass criteria for this experiment:
   - Either reads are proven slow/blocked (confirming hypothesis), or
   - reads are proven healthy (falsifying hypothesis and narrowing scope).
