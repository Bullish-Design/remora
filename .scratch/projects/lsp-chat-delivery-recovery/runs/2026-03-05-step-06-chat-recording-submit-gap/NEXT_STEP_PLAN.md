# Next Step Plan

## Goal
- Make `chat` e2e deterministically drive a real chat submit (`$/remora/submitInput`) and fail whenever submit/runner markers are missing.

## Reproduction Command
- `devenv shell -- python -m e2e.run --scenario chat --no-record`
- `devenv shell -- python -m e2e.run --scenario chat` (recording on)

## Target Files and Functions
- `/home/andrew/Documents/Projects/remora/e2e/keys.py`
  - function(s): add a dedicated chat submit helper (prompt detection + submit)
  - expected change: remove ambiguous ad-hoc key sequencing from scenarios.
- `/home/andrew/Documents/Projects/remora/e2e/scenarios/chat.py`
  - function(s): `ChatScenario.run`
  - expected change: use helper and assert message evidence before panel verification.
- `/home/andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/init.lua`
  - function(s): `$/remora/requestInput` handler
  - expected change: add branch diagnostics and robust routing notes for panel-vs-fallback path if submit still fails.

## Expected Error/Signal Changes
- Existing signature expected to decrease/disappear:
  - `cmd_chat: requestInput sent` with missing `on_input_submitted: params=` should disappear.
- New instrumentation markers expected:
  - client logs should show input handler path used consistently (panel focus or fallback submit).
- What should appear if hypothesis is wrong:
  - cast shows message entered + Enter, but server still has zero `on_input_submitted`.
- Cast/UI change expected (exact prompt/history behavior):
  - prompt should contain sent text briefly and chat history should no longer stay at `No messages yet`.

## Minimal Change Set
1. Change:
   - file/function: `e2e/keys.py` add `submit_chat_message(text)` helper
   - why this is minimal: isolates UI-driving reliability without touching server behavior.
2. Change:
   - file/function: `e2e/scenarios/chat.py` replace manual key sequence with helper + explicit assertion
   - why this is minimal: keeps scenario intent identical while making it falsifiable.

## Validation
1. Tests:
   - `devenv shell -- pytest e2e/tests/test_keys.py -q`
2. E2E run:
   - `devenv shell -- python -m e2e.run --scenario chat`
3. Log checks (`rg` patterns):
   - `CMD RemoraChat`
   - `cmd_chat: requestInput sent`
   - `on_input_submitted: params=`
   - `execute_turn: START`
4. Cast checks (timestamps/snippets):
   - `Message to agent:` contains typed message then transitions to history entry
   - no stray `ra` artifact in prompt

## Exit Criteria
- `chat` e2e either:
  - reliably produces all submit/runner markers in one run, or
  - fails with explicit assertion tied to missing submit evidence (never false-passes).
