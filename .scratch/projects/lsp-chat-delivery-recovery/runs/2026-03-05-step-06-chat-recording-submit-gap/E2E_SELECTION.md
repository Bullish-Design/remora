# E2E Selection

## Selected Scenario
- `chat`

## Why This Scenario
- The failure under investigation is chat delivery (`RemoraChat` -> `$/remora/requestInput` -> `$/remora/submitInput` -> `on_input_submitted` -> `execute_turn`).
- `chat` is the only existing scenario intended to exercise this exact path end-to-end.

## Commands Run
1. `devenv shell -- python -m e2e.run --scenario chat`
   - Result: `PASS` at `2026-03-05 12:45-12:46`.
   - Logs: `/home/andrew/Documents/Projects/remora/.remora/logs/client-2026-03-05_124557.log`, `/home/andrew/Documents/Projects/remora/.remora/logs/server-2026-03-05_124608.log`
   - Cast: `/home/andrew/Documents/Projects/remora/e2e/output/chat_20260305_124556.cast`
2. `devenv shell -- python -m e2e.run --scenario chat`
   - Result: `FAIL` at `2026-03-05 12:49` after tightening scenario assertion.
   - Logs: `/home/andrew/Documents/Projects/remora/.remora/logs/client-2026-03-05_124927.log`, `/home/andrew/Documents/Projects/remora/.remora/logs/server-2026-03-05_124938.log`
   - Cast: `/home/andrew/Documents/Projects/remora/e2e/output/chat_20260305_124926.cast`

## Marker Validation Outcome
- Run 1 (`PASS`) was non-validating:
  - `CMD RemoraChat=1`
  - `cmd_chat: requestInput sent=1`
  - `on_input_submitted: params==0`
  - `execute_turn: START=0`
- Run 2 (`FAIL`) also did not reach submit path:
  - `CMD RemoraChat=1`
  - `cmd_chat: requestInput sent=1`
  - `on_input_submitted: params==0`
  - `execute_turn: START=0`

## New Scenario Needed?
- Not yet.
- First, fix `chat` scenario determinism and tighten marker checks so it cannot pass without submit/runner markers.
