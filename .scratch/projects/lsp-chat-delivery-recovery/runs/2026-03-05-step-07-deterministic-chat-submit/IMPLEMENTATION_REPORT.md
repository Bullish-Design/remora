# Implementation Report — Step 07 Deterministic Chat Submit

## Changes Implemented
- Added deterministic chat-submit helpers in `e2e/keys.py`:
  - `submit_chat_message(...)`
  - `wait_for_chat_history_message(...)`
- Wired `e2e/scenarios/chat.py` to use the new helper and fail if required server markers are missing.
- Tightened chat prompt targeting to `"Message to agent:"` to avoid matching panel winbar text (`"Message agent..."`) before real request-input is active.
- Added request-input routing diagnostics in `src/remora/lsp/nvim/lua/remora/init.lua`.
- Added unit coverage for the new key helpers in `e2e/tests/test_keys.py`.

## Validation
- Unit tests:
  - `devenv shell -- pytest e2e/tests/test_keys.py -q` (PASS)
- E2E:
  - `devenv shell -- python -m e2e.run --scenario chat --no-record` (PASS)

## Marker Evidence
Server log: `.remora/logs/server-2026-03-05_130514.log`
- `cmd_chat: requestInput sent` at line 48
- `on_input_submitted: params=...` at line 74
- `execute_turn: START ...` at line 100

Client log: `.remora/logs/client-2026-03-05_130504.log`
- `HANDLER $/remora/requestInput: panel closed; using vim.ui.input fallback`
- `HANDLER $/remora/requestInput: user input="what do you do?"`
- `HANDLER $/remora/requestInput: sending $/remora/submitInput params=...`
