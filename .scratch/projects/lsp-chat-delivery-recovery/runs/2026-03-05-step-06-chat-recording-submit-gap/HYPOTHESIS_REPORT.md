# Hypothesis Report

## Run Metadata
- Date: 2026-03-05
- Run directory: `/home/andrew/Documents/Projects/remora/.scratch/projects/lsp-chat-delivery-recovery/runs/2026-03-05-step-06-chat-recording-submit-gap`
- E2E scenario + command:
  - `devenv shell -- python -m e2e.run --scenario chat` (twice)
- Recording command + cast file:
  - `/home/andrew/Documents/Projects/remora/e2e/output/chat_20260305_124556.cast`
  - `/home/andrew/Documents/Projects/remora/e2e/output/chat_20260305_124926.cast`
- Input logs (absolute paths):
  - `/home/andrew/Documents/Projects/remora/.remora/logs/client-2026-03-05_124557.log`
  - `/home/andrew/Documents/Projects/remora/.remora/logs/server-2026-03-05_124608.log`
  - `/home/andrew/Documents/Projects/remora/.remora/logs/client-2026-03-05_124927.log`
  - `/home/andrew/Documents/Projects/remora/.remora/logs/server-2026-03-05_124938.log`
  - `/home/andrew/.local/state/nvim/lsp.log`
- Commit baseline: working tree (no commit captured for this step)

## Observed Symptoms
- Scenario `chat` can report `PASS` while server never receives `on_input_submitted`.
- Recorded UI shows chat prompt opened, but typed input is not reliably submitted.
- LSP attach is unstable in these runs (`NO remora clients found` storms, duplicate-instance warning in nvim LSP log).

## Error Signatures (Exact)
- Signature: `cmd_chat: requestInput sent` with no `on_input_submitted: params=`.
  - Source log: `/home/andrew/Documents/Projects/remora/.remora/logs/server-2026-03-05_124608.log`
  - Timestamp(s): `12:46:09.258`
  - Origin in code: `/home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/commands.py` `cmd_chat`
  - Why this matters: request-input stage succeeds; submit stage never fires, so runner never starts.
- Signature: same gap in second run (`FAIL` after tighter assertion).
  - Source log: `/home/andrew/Documents/Projects/remora/.remora/logs/server-2026-03-05_124938.log`
  - Timestamp(s): `12:49:39.389`
  - Origin in code: `/home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/commands.py` `cmd_chat`; missing handler call in `/home/andrew/Documents/Projects/remora/src/remora/lsp/notifications.py` `on_input_submitted`
  - Why this matters: confirms submit-path gap is reproducible and not just a one-off.
- Signature: duplicate-instance warning during/after startup.
  - Source log: `/home/andrew/.local/state/nvim/lsp.log`
  - Timestamp(s): `2026-03-05 12:49:40`
  - Origin in code: startup lock handling path (LSP process lock checks)
  - Why this matters: attach instability can alter prompt-routing behavior.

## Cast Evidence
- Snippet timestamp: `13.340s-21.996s` in `chat_20260305_124556.cast`
  - Cast file: `/home/andrew/Documents/Projects/remora/e2e/output/chat_20260305_124556.cast`
  - What was visible in UI: `Message to agent: ra` (key-sequence artifact), no submitted chat history entry.
  - Why this supports hypothesis: keystrokes are hitting wrong context (leader keys leaking into input prompt), not producing submit.
- Snippet timestamp: `13.489s+` in `chat_20260305_124926.cast`
  - Cast file: `/home/andrew/Documents/Projects/remora/e2e/output/chat_20260305_124926.cast`
  - What was visible in UI: `Message to agent:` stays empty, `No messages yet` remains.
  - Why this supports hypothesis: prompt is open but scenario interaction still fails to produce a sent message.

## Stage Counters
- `on_input_submitted`: `0` (latest server log `124938`)
- `HumanChatEvent emitted`: `0`
- `execute_turn: START`: `0`
- `execute_turn: ... calling LLM`: `0`
- `append: database locked`: `0`
- `batch_append: database locked`: `0`

## Code Areas to Inspect Next
- File: `/home/andrew/Documents/Projects/remora/e2e/scenarios/chat.py`
  - Function(s): `ChatScenario.run`
  - Reason: current interaction sequence is not deterministic for chat submit.
- File: `/home/andrew/Documents/Projects/remora/e2e/keys.py`
  - Function(s): `wait_for_chat_prompt`, leader/input helpers
  - Reason: missing helper that guarantees active input context before submit.
- File: `/home/andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/init.lua`
  - Function(s): `$/remora/requestInput` handler
  - Reason: routing branch depends on `panel._agent`; fallback path may conflict with scenario timing.
- File: `/home/andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/panel.lua`
  - Function(s): `send_message`, panel lifecycle/focus
  - Reason: verify when input window is active and which agent id is used for submit.

## Primary Hypothesis
The failure is currently dominated by non-deterministic client/UI input routing in the e2e flow: `requestInput` is emitted, but the scenario does not reliably place text into the active submit context (`panel input` vs `vim.ui.input`), so `$/remora/submitInput` is not sent.

## Recommended Fix
Implement a deterministic e2e chat-submit helper (in `e2e/keys.py`) that:
1. waits for prompt visibility,
2. detects/targets the active input context,
3. sends message + Enter in that context,
4. fails immediately if message is not visible in chat prompt/history,
and keep `chat` scenario assertions requiring that evidence.

## Why This Fix
It directly addresses the observed gap between `requestInput` and `on_input_submitted` and removes false-positive passes from UI timing/focus ambiguity.

## Falsification Criteria
- After deterministic submit helper, server logs still show `cmd_chat: requestInput sent=1` with `on_input_submitted: params==0` across multiple runs.
- Cast shows correctly typed message and Enter in active prompt, but no client-side submit notification and no server handler hit.

## Verification Plan
1. Command(s) to run:
   - `devenv shell -- python -m e2e.run --scenario chat`
2. Expected markers in logs:
   - client: `CMD RemoraChat`
   - server: `cmd_chat: requestInput sent`
   - server: `on_input_submitted: params=`
   - server: `execute_turn: START`
3. Pass/fail conditions:
   - Pass: all four markers present in same run.
   - Fail: any of the submit/runner markers missing.
4. If failed, first files/lines to inspect:
   - `/home/andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/init.lua` requestInput routing branch
   - `/home/andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/panel.lua` `send_message`
   - `/home/andrew/Documents/Projects/remora/e2e/scenarios/chat.py` message-submission sequence

## Notes
- This step isolated a critical process issue: `chat` could pass while never exercising submit/runner path.
- The tightened scenario now exposes this instead of masking it.
